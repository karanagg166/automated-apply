//! Actual bounded research inputs. Normalization never fetches URLs or grants provider access.
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use std::sync::LazyLock;
#[derive(Clone, Copy)]
pub enum Kind {
    PublicPerson,
    OfficialPerson,
    PeopleQuery,
    CompanyObservation,
    StartupRun,
    StartupKeyed,
}
struct Contract {
    schema: Value,
    validator: jsonschema::Validator,
}
fn contract(kind: Kind) -> &'static Contract {
    fn build(raw: &str) -> Contract {
        compile(serde_json::from_str(raw).expect("frozen research contract"))
    }
    fn compile(schema: Value) -> Contract {
        let validator = jsonschema::draft202012::options()
            .should_validate_formats(false)
            .build(&schema)
            .expect("research schema");
        Contract { schema, validator }
    }
    static PUBLIC: LazyLock<Contract> =
        LazyLock::new(|| build(include_str!("../schemas/public-person.json")));
    static OFFICIAL: LazyLock<Contract> =
        LazyLock::new(|| build(include_str!("../schemas/official-person-evidence.json")));
    static PEOPLE: LazyLock<Contract> =
        LazyLock::new(|| build(include_str!("../schemas/people-query.json")));
    static COMPANY: LazyLock<Contract> =
        LazyLock::new(|| build(include_str!("../schemas/company-observation.json")));
    static RUN: LazyLock<Contract> =
        LazyLock::new(|| build(include_str!("../schemas/startup-run-request.json")));
    static KEYED: LazyLock<Contract> = LazyLock::new(|| {
        let mut schema = RUN.schema.clone();
        schema["required"]
            .as_array_mut()
            .expect("startup required fields")
            .retain(|field| field != "idempotency_key");
        compile(schema)
    });
    match kind {
        Kind::PublicPerson => &PUBLIC,
        Kind::OfficialPerson => &OFFICIAL,
        Kind::PeopleQuery => &PEOPLE,
        Kind::CompanyObservation => &COMPANY,
        Kind::StartupRun => &RUN,
        Kind::StartupKeyed => &KEYED,
    }
}
fn invalid() -> Failure {
    Failure("invalid_research_contract")
}
fn public_url(value: &mut Value) -> Result<()> {
    if !value.is_null() {
        *value = json!(
            crate::resources::public_https(value.as_str().ok_or_else(invalid)?)
                .ok_or_else(invalid)?
        );
    }
    Ok(())
}
fn domain(value: &mut Value) -> Result<()> {
    if let Value::String(s) = value {
        let domain = s
            .to_lowercase()
            .trim_matches(crate::context_contract::python_space)
            .trim_end_matches('.')
            .to_owned();
        static HOST: LazyLock<regex::Regex> =
            LazyLock::new(|| regex::Regex::new(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$").unwrap());
        if !HOST.is_match(&domain) {
            return Err(invalid());
        }
        crate::job_urls::canonical(&format!("https://{domain}")).map_err(|_| invalid())?;
        *s = domain;
    }
    Ok(())
}
fn actual_time(value: &mut Value, now: DateTime<Utc>) -> Result<()> {
    let at = crate::packet_record::expiry(value)
        .map_err(|_| invalid())?
        .ok_or_else(invalid)?;
    if at > now + chrono::Duration::minutes(5) {
        return Err(invalid());
    }
    *value = json!(at.to_rfc3339_opts(
        if at.timestamp_subsec_micros() == 0 {
            chrono::SecondsFormat::Secs
        } else {
            chrono::SecondsFormat::Micros
        },
        true
    ));
    Ok(())
}
fn trim(value: &mut Value) {
    if let Value::String(s) = value {
        // Pydantic's str_strip_whitespace follows Unicode whitespace.  Its
        // behavior deliberately preserves ASCII information separators.
        *s = s.trim().to_owned();
    }
}
fn boolean(fields: &mut serde_json::Map<String, Value>, keys: &[&str]) -> Result<()> {
    for key in keys {
        if let Some(v) = fields.get_mut(*key) {
            *v = crate::resource_contract::boolean(v).map_err(|_| invalid())?;
        }
    }
    Ok(())
}
fn query(mut value: Value) -> Result<Value> {
    let fields = value.as_object_mut().ok_or_else(invalid)?;
    for (key, default) in [
        ("keywords", json!([])),
        ("locations", json!([])),
        ("remote_preference", Value::Null),
        ("employment_types", json!([])),
        ("page", json!(1)),
        ("limit", json!(20)),
        ("max_age_days", Value::Null),
    ] {
        fields.entry(key).or_insert(default);
    }
    for key in ["keywords", "locations"] {
        if let Some(Value::Array(rows)) = fields.get_mut(key) {
            for v in rows {
                trim(v);
            }
        }
    }
    for (key, min, max) in [
        ("page", 1, 100),
        ("limit", 1, 100),
        ("max_age_days", 1, 3650),
    ] {
        if let Some(v) = fields.get_mut(key) {
            if !v.is_null() {
                *v = json!(
                    crate::profile_contract::pagination_integer(v.clone(), min, max)
                        .map_err(|_| invalid())?
                );
            }
        }
    }
    Ok(value)
}
pub fn normalize(kind: Kind, mut value: Value, now: DateTime<Utc>) -> Result<Value> {
    if value.to_string().len() > 2 * 1024 * 1024 {
        return Err(invalid());
    }
    let schema = contract(kind);
    let fields = value.as_object_mut().ok_or_else(invalid)?;
    for (key, p) in schema.schema["properties"]
        .as_object()
        .expect("research properties")
    {
        if let Some(default) = p.get("default") {
            fields.entry(key.clone()).or_insert(default.clone());
        }
    }
    match kind {
        Kind::PublicPerson => {
            if let Some(v) = fields.get_mut("linkedin_url") {
                *v = json!(
                    v.as_str()
                        .and_then(crate::contacts::enrichment::lookups::linkedin)
                        .ok_or_else(invalid)?
                );
            }
            if let Some(v) = fields.get_mut("evidence_url") {
                *v = json!(
                    crate::job_urls::canonical(v.as_str().ok_or_else(invalid)?)
                        .map_err(|_| invalid())?
                );
            }
        }
        Kind::OfficialPerson => {
            for key in ["full_name", "role_title"] {
                if let Some(v) = fields.get_mut(key) {
                    trim(v);
                }
            }
            for key in [
                "evidence_url",
                "professional_url",
                "permission_evidence_url",
                "email_publication_url",
            ] {
                if let Some(v) = fields.get_mut(key) {
                    public_url(v)?;
                }
            }
            if let Some(v) = fields.get_mut("business_email") {
                if !v.is_null() {
                    *v = json!(
                        crate::profile_contract::email(v.as_str().ok_or_else(invalid)?)
                            .map_err(|_| invalid())?
                    );
                }
            }
            if let Some(v) = fields.get_mut("observed_at") {
                actual_time(v, now)?;
            }
            boolean(fields, &["human_confirmed"])?;
            if fields.get("business_email").is_some_and(|v| !v.is_null())
                != fields
                    .get("email_publication_url")
                    .is_some_and(|v| !v.is_null())
            {
                return Err(invalid());
            }
        }
        Kind::PeopleQuery => {
            fields
                .entry("roles")
                .or_insert(json!(["founder", "cto", "recruiter"]));
            for key in ["manual_people", "official_people"] {
                fields.entry(key).or_insert(json!([]));
            }
            for key in ["company_name", "location"] {
                if let Some(v) = fields.get_mut(key) {
                    trim(v);
                }
            }
            if let Some(v) = fields.get_mut("company_domain") {
                domain(v)?;
            }
            if let Some(v) = fields.get_mut("limit") {
                *v = json!(
                    crate::profile_contract::pagination_integer(v.clone(), 1, 20)
                        .map_err(|_| invalid())?
                );
            }
            boolean(fields, &["allow_paid", "permission_confirmed"])?;
            for (key, nested) in [
                ("manual_people", Kind::PublicPerson),
                ("official_people", Kind::OfficialPerson),
            ] {
                if let Some(Value::Array(rows)) = fields.get_mut(key) {
                    if rows.len() > 20 {
                        return Err(invalid());
                    }
                    for v in rows {
                        *v = normalize(nested, v.clone(), now)?;
                    }
                }
            }
        }
        Kind::CompanyObservation => {
            fields.entry("technology_stack").or_insert(json!([]));
            for key in [
                "name",
                "source_company_id",
                "country",
                "location",
                "industry",
                "stage",
                "yc_batch",
                "product_category",
            ] {
                if let Some(v) = fields.get_mut(key) {
                    trim(v);
                }
            }
            if let Some(Value::Array(rows)) = fields.get_mut("technology_stack") {
                for v in rows {
                    trim(v);
                }
            }
            if let Some(v) = fields.get_mut("domain") {
                domain(v)?;
            }
            for key in ["source_url", "permission_evidence_url", "careers_url"] {
                if let Some(v) = fields.get_mut(key) {
                    public_url(v)?;
                }
            }
            if let Some(v) = fields.get_mut("observed_at") {
                actual_time(v, now)?;
            }
            boolean(fields, &["historical", "authoritative_statement"])?;
            if let Some(v) = fields.get_mut("founding_year") {
                if !v.is_null() {
                    *v = json!(
                        crate::profile_contract::pagination_integer(v.clone(), 1800, 2100)
                            .map_err(|_| invalid())?
                    );
                }
            }
            if let Some(count) = fields.get("employee_count").filter(|v| !v.is_null()) {
                let count = count
                    .as_i64()
                    .filter(|n| (1..=10000000).contains(n))
                    .ok_or_else(invalid)?;
                let expected = crate::startup_catalog::rules::size_band(Some(count))?;
                let band = fields
                    .get("team_size_band")
                    .and_then(Value::as_str)
                    .ok_or_else(invalid)?;
                if band != "unknown"
                    && band != expected
                    && !(band == "2-10" && (2..=10).contains(&count))
                {
                    return Err(invalid());
                }
                if band != "2-10" {
                    fields.insert("team_size_band".into(), json!(expected));
                }
            }
            if fields.get("hiring_statement") == Some(&json!("not_currently_hiring"))
                && fields.get("authoritative_statement") != Some(&json!(true))
            {
                return Err(invalid());
            }
        }
        Kind::StartupRun | Kind::StartupKeyed => {
            fields.entry("companies").or_insert(json!([]));
            fields.entry("query").or_insert(json!({}));
            fields.entry("filters").or_insert(json!({}));
            boolean(fields, &["permission_confirmed", "allow_paid"])?;
            if let Some(v) = fields.get_mut("query") {
                *v = query(v.clone())?;
            }
            if let Some(v) = fields.get_mut("filters") {
                *v = crate::startup_catalog::contract::normalize(
                    crate::startup_catalog::contract::Kind::Filters,
                    v.clone(),
                )
                .map_err(|_| invalid())?;
            }
            if let Some(Value::Array(rows)) = fields.get_mut("companies") {
                if rows.len() > 100 {
                    return Err(invalid());
                }
                for v in rows {
                    *v = normalize(Kind::CompanyObservation, v.clone(), now)?;
                }
            }
            if fields["companies"]
                .as_array()
                .is_some_and(|rows| !rows.is_empty())
                && (fields["mode"] != "company_first"
                    || fields["source"] != "manual"
                    || fields["permission_confirmed"] != true)
            {
                return Err(invalid());
            }
            if fields["companies"].as_array().is_some_and(|rows| {
                rows.len() as u64 > fields["query"]["limit"].as_u64().unwrap_or(0)
            }) {
                return Err(invalid());
            }
        }
    }
    if !schema.validator.is_valid(&value) {
        return Err(invalid());
    }
    Ok(value)
}
