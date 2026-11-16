//! Saved professional contacts. Provider/enrichment/correction operations are separate services.
pub mod contract;
pub mod correction;
pub mod rules;
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use std::collections::{BTreeMap, BTreeSet};
use uuid::Uuid;
pub struct Settings {
    pub cache_days: i64,
    pub retention_days: i64,
}
impl Settings {
    pub fn from_values(values: &BTreeMap<String, String>) -> Result<Self> {
        let integer = |key: &str, default: &str, max: i64| -> Result<i64> {
            values
                .get(key)
                .map(String::as_str)
                .unwrap_or(default)
                .parse::<i64>()
                .ok()
                .filter(|n| (1..=max).contains(n))
                .ok_or(Failure("invalid_contact_settings"))
        };
        Ok(Self {
            cache_days: integer("CONTACT_CACHE_TTL_DAYS", "30", 90)?,
            retention_days: integer("CONTACT_RETENTION_DAYS", "90", 365)?,
        })
    }
}
fn invalid() -> Failure {
    Failure("invalid_contact_saved_record")
}
fn db(_: sqlx::Error) -> Failure {
    Failure("contact_database_error")
}
#[derive(Clone, Copy)]
pub enum Route {
    Company(Uuid),
    Detail(Uuid),
    Recommended(Uuid),
}
impl Route {
    pub fn accepts(self, method: &str) -> bool {
        method == "GET" || matches!(self, Self::Detail(_)) && method == "PATCH"
    }
    pub fn allow(self) -> &'static str {
        if matches!(self, Self::Detail(_)) {
            "GET, PATCH"
        } else {
            "GET"
        }
    }
}
pub fn route(path: &str) -> Option<Route> {
    if let Some(id) = path
        .strip_prefix("/api/v1/companies/")
        .and_then(|s| s.strip_suffix("/contacts"))
    {
        return id.parse().ok().map(Route::Company);
    }
    if let Some(id) = path.strip_prefix("/api/v1/contacts/") {
        return id.parse().ok().map(Route::Detail);
    }
    path.strip_prefix("/api/v1/jobs/")
        .and_then(|s| s.strip_suffix("/recommended-contacts"))
        .and_then(|s| s.parse().ok())
        .map(Route::Recommended)
}
#[derive(Default)]
pub struct Page {
    pub limit: i64,
    pub offset: i64,
    role: Option<String>,
    email_status: Option<String>,
    provider: Option<String>,
    strength: Option<String>,
    after: Option<DateTime<Utc>>,
    suppressed: Option<bool>,
    linkedin: Option<bool>,
    business: Option<bool>,
}
impl Page {
    pub fn parse(route: Route, query: Option<&str>) -> Result<Self> {
        let mut result = Self {
            limit: if matches!(route, Route::Recommended(_)) {
                10
            } else {
                25
            },
            ..Self::default()
        };
        let mut fields = BTreeMap::new();
        if let Some(query) = query {
            if query.len() > 4096 {
                return Err(Failure("invalid_contact_query"));
            }
            let url = reqwest::Url::parse(&format!("http://127.0.0.1/?{query}"))
                .map_err(|_| Failure("invalid_contact_query"))?;
            for (key, value) in url.query_pairs() {
                if fields
                    .insert(key.into_owned(), value.into_owned())
                    .is_some()
                {
                    return Err(Failure("invalid_contact_query"));
                }
            }
        }
        let error = || Failure("invalid_contact_query");
        for (key, value) in fields {
            if matches!(route, Route::Detail(_))
                || matches!(route, Route::Recommended(_)) && key != "limit"
            {
                return Err(error());
            }
            match key.as_str() {
                "limit" => {
                    result.limit = crate::profile_contract::pagination_integer(
                        json!(value),
                        1,
                        if matches!(route, Route::Recommended(_)) {
                            25
                        } else {
                            100
                        },
                    )
                    .map_err(|_| error())?
                }
                "offset" => {
                    result.offset =
                        crate::profile_contract::pagination_integer(json!(value), 0, 100000)
                            .map_err(|_| error())?
                }
                "role" if value.chars().count() <= 255 => result.role = Some(value),
                "email_status"
                    if [
                        "unknown",
                        "candidate",
                        "provider_reported",
                        "verified",
                        "invalid",
                    ]
                    .contains(&value.as_str()) =>
                {
                    result.email_status = Some(value)
                }
                "provider"
                    if ["apollo", "signalhire", "manual", "public_search"]
                        .contains(&value.as_str()) =>
                {
                    result.provider = Some(value)
                }
                "min_evidence_strength"
                    if ["weak", "moderate", "strong"].contains(&value.as_str()) =>
                {
                    result.strength = Some(value)
                }
                "last_observed_after" => {
                    result.after = Some(
                        crate::gmail_history::contract::timestamp(&json!(value))
                            .ok_or_else(error)?
                            .with_timezone(&Utc),
                    )
                }
                "suppressed" | "has_linkedin" | "has_business_email" => {
                    let parsed = match value.to_lowercase().as_str() {
                        "true" | "1" | "yes" | "on" => true,
                        "false" | "0" | "no" | "off" => false,
                        _ => return Err(error()),
                    };
                    match key.as_str() {
                        "suppressed" => result.suppressed = Some(parsed),
                        "has_linkedin" => result.linkedin = Some(parsed),
                        _ => result.business = Some(parsed),
                    }
                }
                _ => return Err(error()),
            }
        }
        Ok(result)
    }
}

impl Page {
    fn value(&self, target: Option<Uuid>) -> Value {
        let role = self.role.as_ref().filter(|s| !s.is_empty()).map(|s| {
            format!(
                "%{}%",
                s.replace('\\', "\\\\")
                    .replace('%', "\\%")
                    .replace('_', "\\_")
            )
        });
        json!({"role":role,"email_status":self.email_status,"provider":self.provider,"strength":self.strength,"after":self.after,"suppressed":self.suppressed,"linkedin":self.linkedin,"business":self.business,"target_job_id":target})
    }
}
// Only fields needed for ranking/review cross this boundary; vendor payloads stay private.
const CONTACT: &str = r#"jsonb_build_object('id',c.id,'review_version',c.xmin::text||':'||extract(epoch from c.updated_at)::text,'company_id',c.company_id,'full_name',c.full_name,'role_title',c.role_title,'linkedin_url',c.linkedin_url,'email',c.email,'email_status',c.email_status,'confidence_score',c.confidence_score,'enrichment_source',c.enrichment_source,'last_verified_at',c.last_verified_at,'last_checked_at',c.last_checked_at,'last_reviewed_at',c.last_reviewed_at,'do_not_contact',c.do_not_contact,'suppression_reason',CASE WHEN octet_length(c.suppression_reason)<=10000 THEN c.suppression_reason ELSE NULL END,'human_review_notes',CASE WHEN octet_length(c.human_review_notes)<=10000 THEN c.human_review_notes ELSE NULL END,'_metadata_invalid',coalesce(jsonb_typeof(c.metadata::jsonb)<>'object',false) OR coalesce(octet_length(c.metadata::text)>262144,false) OR coalesce(octet_length(c.suppression_reason)>10000,false) OR coalesce(octet_length(c.human_review_notes)>10000,false) OR coalesce(jsonb_typeof(c.metadata::jsonb->'job_ids') NOT IN ('array','null'),false),'metadata_',jsonb_strip_nulls(jsonb_build_object('email_observed_at',c.metadata::jsonb->'email_observed_at','identity_review_required',c.metadata::jsonb->'identity_review_required','hiring_responsibility_confirmed',c.metadata::jsonb->'hiring_responsibility_confirmed','evidence_strength',c.metadata::jsonb->'evidence_strength','email_publication_confirmed',c.metadata::jsonb->'email_publication_confirmed','email_publication_url',c.metadata::jsonb->'email_publication_url','email_publication_digest',c.metadata::jsonb->'email_publication_digest','job_ids',CASE WHEN jsonb_typeof(c.metadata::jsonb->'job_ids')='array' THEN jsonb_path_query_array(c.metadata::jsonb->'job_ids','$[0 to 99]') ELSE '[]'::jsonb END)),'_target_job_associated',($2::jsonb->>'target_job_id' IS NOT NULL AND coalesce(c.metadata::jsonb->'job_ids' @> jsonb_build_array($2::jsonb->>'target_job_id'),false)))"#;
const FILTER: &str = r#"c.company_id=$1 AND ($2::jsonb->>'role' IS NULL OR c.role_title ILIKE ($2::jsonb->>'role') ESCAPE '\') AND ($2::jsonb->>'email_status' IS NULL OR c.email_status=$2::jsonb->>'email_status') AND ($2::jsonb->>'suppressed' IS NULL OR c.do_not_contact=($2::jsonb->>'suppressed')::boolean) AND ($2::jsonb->>'linkedin' IS NULL OR (c.linkedin_url IS NOT NULL)=($2::jsonb->>'linkedin')::boolean) AND ($2::jsonb->>'business' IS NULL OR (c.email IS NOT NULL AND c.email_status IN ('provider_reported','verified'))=($2::jsonb->>'business')::boolean) AND ($2::jsonb->>'after' IS NULL OR c.last_checked_at>=($2::jsonb->>'after')::timestamptz) AND (($2::jsonb->>'provider' IS NULL AND $2::jsonb->>'strength' IS NULL) OR EXISTS(SELECT 1 FROM contact_evidence e WHERE e.contact_id=c.id AND ($2::jsonb->>'provider' IS NULL OR e.source=$2::jsonb->>'provider') AND ($2::jsonb->>'strength' IS NULL OR (e.expires_at>$3 AND e.strength=ANY(CASE $2::jsonb->>'strength' WHEN 'weak' THEN ARRAY['weak','moderate','strong'] WHEN 'moderate' THEN ARRAY['moderate','strong'] ELSE ARRAY['strong'] END)))))"#;
async fn company(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Value> {
    sqlx::query_scalar("SELECT jsonb_build_object('id',id,'name',name,'metadata_',jsonb_build_object('employee_count',metadata::jsonb->'employee_count','_verified_team_size_band',metadata::jsonb->'_verified_team_size_band')) FROM companies WHERE id=$1").bind(id).fetch_optional(&mut **tx).await.map_err(db)?.ok_or(Failure("contact_company_not_found"))
}
async fn list(
    tx: &mut Transaction<'_, Postgres>,
    id: Uuid,
    page: &Page,
    settings: &Settings,
    now: DateTime<Utc>,
) -> Result<Value> {
    let company = company(tx, id).await?;
    let filters = page.value(None);
    let count: i64 = sqlx::query_scalar(&format!("SELECT count(*) FROM contacts c WHERE {FILTER}"))
        .bind(id)
        .bind(&filters)
        .bind(now)
        .fetch_one(&mut **tx)
        .await
        .map_err(db)?;
    let rows: Vec<Value> = sqlx::query_scalar(&format!(
        "SELECT {CONTACT} FROM contacts c WHERE {FILTER} ORDER BY c.id LIMIT $4 OFFSET $5"
    ))
    .bind(id)
    .bind(&filters)
    .bind(now)
    .bind(page.limit)
    .bind(page.offset)
    .fetch_all(&mut **tx)
    .await
    .map_err(db)?;
    let contacts = rows
        .iter()
        .map(|contact| rules::output(contact, &company, None, settings, now))
        .collect::<Result<Vec<_>>>()?;
    Ok(json!({"contacts":contacts,"total":count,"offset":page.offset,"limit":page.limit}))
}
async fn detail(
    tx: &mut Transaction<'_, Postgres>,
    id: Uuid,
    settings: &Settings,
    now: DateTime<Utc>,
) -> Result<Value> {
    let contact: Value =
        sqlx::query_scalar(&format!("SELECT {CONTACT} FROM contacts c WHERE c.id=$1"))
            .bind(id)
            .bind(json!({}))
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?
            .ok_or(Failure("contact_not_found"))?;
    let company_id = contact["company_id"]
        .as_str()
        .and_then(|s| s.parse().ok())
        .ok_or_else(invalid)?;
    let company = company(tx, company_id).await?;
    let mut value = rules::output(&contact, &company, None, settings, now)?;
    let evidence:Vec<Value>=sqlx::query_scalar("SELECT jsonb_build_object('id',id,'source',source,'type',evidence_type,'url',evidence_url,'observed_role',observed_role,'observed_company',observed_company,'provider_verification_claim',provider_verification_claim,'strength',strength,'collected_at',collected_at,'expires_at',expires_at,'user_confirmed',user_confirmed,'provenance',CASE WHEN expires_at<$2 THEN '{\"expired\":true}'::jsonb WHEN octet_length(provenance::text)>262144 THEN NULL ELSE provenance::jsonb END) FROM contact_evidence WHERE contact_id=$1 ORDER BY collected_at DESC,id LIMIT 100").bind(id).bind(now).fetch_all(&mut **tx).await.map_err(db)?;
    let evidence = evidence
        .into_iter()
        .map(|mut evidence| {
            if evidence["provenance"].is_null() {
                return Err(invalid());
            }
            if let Some(raw) = evidence["url"].as_str() {
                evidence["url"] = crate::resources::public_https(raw)
                    .map(|s| json!(s))
                    .unwrap_or(Value::Null);
            }
            Ok(evidence)
        })
        .collect::<Result<Vec<_>>>()?;
    value["evidence"] = json!(evidence);
    Ok(value)
}
async fn recommended(
    tx: &mut Transaction<'_, Postgres>,
    id: Uuid,
    page: &Page,
    settings: &Settings,
    now: DateTime<Utc>,
) -> Result<Value> {
    let job:Value=sqlx::query_scalar("SELECT jsonb_build_object('id',id,'company_id',company_id,'title',title) FROM jobs WHERE id=$1").bind(id).fetch_optional(&mut **tx).await.map_err(db)?.ok_or(Failure("contact_job_not_found"))?;
    let Some(company_id) = job["company_id"].as_str().and_then(|s| s.parse().ok()) else {
        return Ok(json!({"contacts":[]}));
    };
    let company = match company(tx, company_id).await {
        Ok(value) => value,
        Err(Failure("contact_company_not_found")) => return Ok(json!({"contacts":[]})),
        Err(error) => return Err(error),
    };
    let filters = json!({"target_job_id":id});
    let mut contacts:Vec<Value>=sqlx::query_scalar(&format!("SELECT {CONTACT} FROM contacts c WHERE c.company_id=$1 AND c.do_not_contact=false ORDER BY c.id LIMIT 1001")).bind(company_id).bind(filters).fetch_all(&mut **tx).await.map_err(db)?;
    let truncated = contacts.len() > 1000;
    contacts.truncate(1000);
    let mut contacts = contacts
        .iter()
        .map(|contact| rules::output(contact, &company, Some(&job), settings, now))
        .collect::<Result<Vec<_>>>()?;
    contacts
        .sort_by_key(|contact| std::cmp::Reverse(contact["ordering_score"].as_i64().unwrap_or(0)));
    contacts.truncate(page.limit as usize);
    Ok(
        json!({"job_id":id,"contacts":contacts,"outreach_mode":"manual_review","outbound_messages_sent":0,"candidate_inventory_limit":1000,"candidate_inventory_truncated":truncated}),
    )
}
pub async fn dispatch(
    c: &mut PgConnection,
    route: Route,
    method: &str,
    query: Option<&str>,
    body: &[u8],
    settings: &Settings,
) -> Result<Value> {
    if method != "GET" {
        return Err(Failure("contact_method_not_allowed"));
    }
    if !body.is_empty() {
        return Err(Failure("invalid_contact_query"));
    }
    let page = Page::parse(route, query)?;
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let result = match route {
        Route::Company(id) => list(&mut tx, id, &page, settings, now).await?,
        Route::Detail(id) => detail(&mut tx, id, settings, now).await?,
        Route::Recommended(id) => recommended(&mut tx, id, &page, settings, now).await?,
    };
    tx.commit()
        .await
        .map_err(|_| Failure("contact_commit_outcome_unknown"))?;
    Ok(result)
}
