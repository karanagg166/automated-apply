//! Actual person/request DTOs and narrow provider projection; no vendor blob is retained.
use super::*;
use std::sync::LazyLock;
#[derive(Clone, Copy)]
pub enum Kind {
    Request,
    Observation,
}
struct Contract {
    schema: Value,
    validator: jsonschema::Validator,
}
fn schema(kind: Kind) -> &'static Contract {
    fn compile(raw: &str) -> Contract {
        let schema: Value = serde_json::from_str(raw).expect("frozen contact person contract");
        let validator = jsonschema::draft202012::options()
            .should_validate_formats(false)
            .build(&schema)
            .expect("contact person schema");
        Contract { schema, validator }
    }
    static REQUEST: LazyLock<Contract> = LazyLock::new(|| {
        compile(include_str!(
            "../../../schemas/contact-provider-request.json"
        ))
    });
    static OBSERVATION: LazyLock<Contract> = LazyLock::new(|| {
        compile(include_str!(
            "../../../schemas/contact-person-observation.json"
        ))
    });
    match kind {
        Kind::Request => &REQUEST,
        Kind::Observation => &OBSERVATION,
    }
}
fn invalid_person() -> Failure {
    Failure("invalid_contact_person_contract")
}
fn boolean(value: &Value) -> Result<Value> {
    Ok(match value {
        Value::Bool(v) => json!(v),
        Value::Number(n) if n.as_f64() == Some(1.0) => json!(true),
        Value::Number(n) if n.as_f64() == Some(0.0) => json!(false),
        Value::String(s) => match s.to_ascii_lowercase().as_str() {
            "true" | "1" | "yes" | "on" | "y" | "t" => json!(true),
            "false" | "0" | "no" | "off" | "n" | "f" => json!(false),
            _ => return Err(invalid_person()),
        },
        _ => return Err(invalid_person()),
    })
}
pub fn normalize(kind: Kind, mut value: Value) -> Result<Value> {
    let contract = schema(kind);
    let props = contract.schema["properties"]
        .as_object()
        .expect("person properties");
    let fields = value.as_object_mut().ok_or_else(invalid_person)?;
    if matches!(kind, Kind::Request) {
        fields.retain(|key, _| props.contains_key(key));
    }
    for (key, property) in props {
        if !fields.contains_key(key) {
            if let Some(default) = property.get("default") {
                fields.insert(key.clone(), default.clone());
            } else if matches!(key.as_str(), "target_roles") {
                fields.insert(key.clone(), json!([]));
            }
        }
    }
    for key in [
        "full_name",
        "role_title",
        "company_domain",
        "provider_person_id",
        "source",
    ] {
        if let Some(Value::String(s)) = fields.get_mut(key) {
            *s = s
                .trim_matches(crate::context_contract::python_space)
                .to_owned();
        }
    }
    for key in ["company_id", "person_id", "discovered_person_id"] {
        if let Some(Value::String(s)) = fields.get_mut(key) {
            *s = s.parse::<Uuid>().map_err(|_| invalid_person())?.to_string();
        }
    }
    for key in ["allow_paid", "human_confirmed"] {
        if let Some(v) = fields.get_mut(key) {
            *v = boolean(v)?;
        }
    }
    if let Some(v) = fields.get_mut("max_people") {
        *v = json!(
            crate::profile_contract::pagination_integer(v.clone(), 1, 25)
                .map_err(|_| invalid_person())?
        );
    }
    if let Some(v) = fields.get_mut("linkedin_url") {
        if let Some(raw) = v.as_str() {
            *v = if raw.is_empty() {
                Value::Null
            } else {
                json!(lookups::linkedin(raw).ok_or_else(invalid_person)?)
            };
        }
    }
    for key in [
        "email_publication_url",
        "professional_url",
        "permission_evidence_url",
        "evidence_url",
    ] {
        if let Some(v) = fields.get_mut(key) {
            if let Some(raw) = v.as_str() {
                *v = json!(crate::resources::public_https(raw).ok_or_else(invalid_person)?);
            }
        }
    }
    if let Some(v) = fields.get_mut("observed_at") {
        if !v.is_null() {
            *v = crate::packet_record::timestamp(v, false).map_err(|_| invalid_person())?;
        }
    }
    if let Some(roles) = fields.get_mut("target_roles").and_then(Value::as_array_mut) {
        for role in roles {
            if let Some(s) = role.as_str() {
                *role = json!(s.trim_matches(crate::context_contract::python_space));
            }
        }
    }
    if !contract.validator.is_valid(&value) {
        return Err(invalid_person());
    }
    Ok(value)
}
/// Company website identity can use HTTP syntax; no URL is fetched and only the public host survives.
pub fn identity_domain(raw: &str) -> Option<String> {
    let raw = if raw.contains("://") {
        raw.to_owned()
    } else {
        format!("https://{raw}")
    };
    let url = reqwest::Url::parse(&raw).ok()?;
    if !matches!(url.scheme(), "http" | "https")
        || !url.username().is_empty()
        || url.password().is_some()
    {
        return None;
    }
    let host = url.host_str()?;
    lookups::domain(host)
}
pub fn apollo(person: &Value, request: &Value) -> Result<Option<Value>> {
    let request = normalize(Kind::Request, request.clone())?;
    if !person.is_object() {
        return Err(invalid_person());
    }
    for field in ["name", "first_name", "last_name"] {
        if person
            .get(field)
            .is_some_and(|v| !v.is_null() && !v.is_string())
        {
            return Err(invalid_person());
        }
    }
    let domain = request["company_domain"]
        .as_str()
        .and_then(identity_domain)
        .ok_or_else(invalid_person)?;
    let org = &person["organization"];
    if !org.is_null() && !org.is_object() {
        return Err(invalid_person());
    }
    let raw = if rules::truthy(&org["primary_domain"]) {
        &org["primary_domain"]
    } else {
        &org["website_url"]
    };
    let actual = raw.as_str().and_then(identity_domain);
    if actual.as_deref() != Some(domain.as_str()) {
        return Ok(None);
    }
    let name = if let Some(name) = person["name"].as_str().filter(|s| !s.is_empty()) {
        Some(name.to_owned())
    } else {
        match (
            person["first_name"].as_str().filter(|s| !s.is_empty()),
            person["last_name"].as_str().filter(|s| !s.is_empty()),
        ) {
            (Some(first), Some(last)) => Some(format!("{first} {last}")),
            _ => None,
        }
    };
    let Some(name) = name.filter(|s| !s.contains('*')) else {
        return Ok(None);
    };
    let email = person["email"]
        .as_str()
        .and_then(|s| rules::business_email(s, &domain));
    let kind = email
        .as_deref()
        .map(rules::email_kind)
        .unwrap_or("person_specific");
    normalize(Kind::Observation,json!({"full_name":name,"role_title":person["title"],"company_domain":domain,"linkedin_url":person["linkedin_url"],"email":email,"source":"apollo","provider_person_id":person["id"],"email_status":if email.is_some(){"provider_reported"}else{"unknown"},"email_kind":kind,"provider_verification_claim":person["email_status"],"evidence_strength":"moderate"})).map(Some)
}
fn rating(value: &Value) -> Result<String> {
    match value {
        Value::Null => Ok("None".into()),
        Value::Bool(v) => Ok(if *v { "True" } else { "False" }.into()),
        Value::String(v) => Ok(v.clone()),
        Value::Number(n) => Ok(n.to_string()),
        _ => Err(invalid_person()),
    }
}
fn array<'a>(value: &'a Value, key: &str, max: usize) -> Result<&'a [Value]> {
    match value.get(key) {
        None => Ok(&[]),
        Some(Value::Array(a)) if a.len() <= max => Ok(a),
        _ => Err(invalid_person()),
    }
}
pub fn signalhire(candidate: &Value, request: &Value) -> Result<Option<Value>> {
    if !candidate.is_object() {
        return Err(invalid_person());
    }
    let request = normalize(Kind::Request, request.clone())?;
    let domain = request["company_domain"]
        .as_str()
        .and_then(identity_domain)
        .ok_or_else(invalid_person)?;
    let experience = array(candidate, "experience", 1000)?;
    let current = experience
        .iter()
        .filter(|e| {
            e["current"] == true
                && e["website"].as_str().and_then(identity_domain).as_deref()
                    == Some(domain.as_str())
        })
        .collect::<Vec<_>>();
    if current.is_empty() {
        return Ok(None);
    }
    let social = array(candidate, "social", 100)?;
    let mut links = BTreeSet::new();
    for entry in social {
        if entry["type"] == "li" {
            let profile = entry["link"]
                .as_str()
                .and_then(lookups::linkedin)
                .ok_or_else(invalid_person)?;
            links.insert(profile);
        }
    }
    if links.len() > 1 {
        return Err(Failure("contact_provider_identity_conflict"));
    }
    let contacts = array(candidate, "contacts", 1000)?;
    let mut addresses = BTreeMap::new();
    for entry in contacts {
        if entry["type"] == "email" && entry["subType"] == "work" {
            if let Some(email) = entry["value"]
                .as_str()
                .and_then(|s| rules::business_email(s, &domain))
            {
                addresses.entry(email).or_insert(entry);
            }
        }
    }
    if addresses.len() > 1 {
        return Err(Failure("contact_provider_mailbox_conflict"));
    }
    let email = addresses.keys().next().cloned();
    let claim = addresses
        .values()
        .next()
        .map(|entry| rating(&entry["rating"]).map(|r| format!("rating:{r}")))
        .transpose()?;
    normalize(Kind::Observation,json!({"full_name":candidate["fullName"],"role_title":current[0]["position"],"company_domain":domain,"linkedin_url":links.into_iter().next(),"email":email,"source":"signalhire","provider_person_id":candidate["uid"],"email_status":if email.is_some(){"provider_reported"}else{"unknown"},"email_kind":email.as_deref().map(rules::email_kind).unwrap_or("person_specific"),"provider_verification_claim":claim})).map(Some)
}
