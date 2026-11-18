//! One saved snapshot for company evidence, jobs, current professional counts and relevance.
use super::{
    contract::{self, Kind},
    intelligence, ranking, rules,
};
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;
fn db(_: sqlx::Error) -> Failure {
    Failure("startup_catalog_database_error")
}
fn invalid() -> Failure {
    Failure("invalid_startup_catalog_record")
}
fn time(v: &Value) -> Result<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(v.as_str().ok_or_else(invalid)?)
        .map(|d| d.to_utc())
        .map_err(|_| invalid())
}
fn inventory(rows: Vec<Option<Value>>, max: usize) -> Result<Vec<Value>> {
    if rows.len() > max {
        return Err(Failure("startup_catalog_inventory_limit"));
    }
    let rows = rows
        .into_iter()
        .map(|v| v.ok_or_else(invalid))
        .collect::<Result<Vec<_>>>()?;
    if rows.iter().map(|v| v.to_string().len()).sum::<usize>() > 8 * 1024 * 1024 {
        return Err(Failure("startup_catalog_inventory_limit"));
    }
    Ok(rows)
}
pub fn route(path: &str) -> Option<Uuid> {
    path.strip_prefix("/api/v1/startups/")?.parse().ok()
}
pub(crate) async fn profile_in(
    tx: &mut Transaction<'_, Postgres>,
    enabled: bool,
) -> Result<Option<Value>> {
    if !enabled {
        return Ok(None);
    }
    match crate::profile_store::get(tx).await {
        Ok(profile) => Ok(Some(profile.value)),
        Err(e) if e.0 == "profile_not_found" => Ok(None),
        Err(e) => Err(e),
    }
}
pub(crate) async fn load_in(
    tx: &mut Transaction<'_, Postgres>,
    id: Uuid,
    filters: &Value,
    profile: Option<&Value>,
    settings: &crate::contacts::Settings,
    now: DateTime<Utc>,
) -> Result<Value> {
    Ok(snapshot_in(tx, id, filters, profile, settings, now)
        .await?
        .public)
}
pub(crate) struct Snapshot {
    pub public: Value,
    pub jobs: Vec<Value>,
}
pub(crate) async fn snapshot_in(
    tx: &mut Transaction<'_, Postgres>,
    id: Uuid,
    filters: &Value,
    profile: Option<&Value>,
    settings: &crate::contacts::Settings,
    now: DateTime<Utc>,
) -> Result<Snapshot> {
    let company:Option<Value>=sqlx::query_scalar("SELECT CASE WHEN octet_length(metadata::text)<=524288 THEN jsonb_build_object('id',id,'name',name,'domain',domain,'metadata_',metadata) ELSE NULL END FROM companies WHERE id=$1").bind(id).fetch_optional(&mut **tx).await.map_err(db)?.ok_or(Failure("startup_catalog_not_found"))?;
    let company = company.ok_or_else(invalid)?;
    if !company["metadata_"].is_object() {
        return Err(invalid());
    }
    let observations:Vec<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(to_jsonb(o)::text)<=262144 THEN to_jsonb(o) ELSE NULL END FROM company_source_observations o WHERE company_id=$1 ORDER BY observed_at DESC,id LIMIT 1001").bind(id).fetch_all(&mut **tx).await.map_err(db)?;
    let observations = inventory(observations, 1000)?;
    for observation in &observations {
        crate::companies::observation(observation.clone(), now)?;
    }
    // Only expiry/current-listing claims enter this private job snapshot, never arbitrary payloads.
    let jobs:Vec<Option<Value>>=sqlx::query_scalar("WITH selected AS (SELECT jsonb_build_object('id',id,'company_id',company_id,'title',title,'description',description,'job_url',job_url,'source_platform',source_platform,'source_verification_status',source_verification_status,'skills_required',skills_required,'location',location,'is_remote',is_remote,'remote_type',remote_type,'experience_level',experience_level,'employment_type',employment_type,'salary_min',salary_min,'salary_max',salary_max,'salary_currency',salary_currency,'salary_period',salary_period,'date_posted',date_posted,'last_observed_at',last_observed_at,'status',status,'discovery_metadata',jsonb_build_object('date_expires',discovery_metadata::jsonb->'date_expires','expires_at',discovery_metadata::jsonb->'expires_at','is_expired',discovery_metadata::jsonb->'is_expired','listing_status',discovery_metadata::jsonb->'listing_status','is_confirmed_current',discovery_metadata::jsonb->'is_confirmed_current')) AS value,last_observed_at,id FROM jobs WHERE company_id=$1 ORDER BY last_observed_at DESC NULLS LAST,id LIMIT 501) SELECT CASE WHEN octet_length(value::text)<=2097152 THEN value ELSE NULL END FROM selected ORDER BY last_observed_at DESC NULLS LAST,id").bind(id).fetch_all(&mut **tx).await.map_err(db)?;
    let jobs = inventory(jobs, 500)?;
    for job in &jobs {
        if job["job_url"]
            .as_str()
            .and_then(crate::resources::public_https)
            .is_none()
        {
            return Err(invalid());
        }
    }
    let ids = jobs
        .iter()
        .map(|j| {
            j["id"]
                .as_str()
                .and_then(|s| s.parse::<Uuid>().ok())
                .ok_or_else(invalid)
        })
        .collect::<Result<Vec<_>>>()?;
    let board_rows:Vec<Option<Value>>=sqlx::query_scalar("SELECT jsonb_build_object('job_id',job_id,'source',source,'last_observed_at',last_observed_at,'verification_status',verification_status) FROM job_source_observations WHERE job_id=ANY($1) ORDER BY last_observed_at DESC,id LIMIT 2001").bind(&ids).fetch_all(&mut **tx).await.map_err(db)?;
    let board_rows = inventory(board_rows, 2000)?;
    let mut attributes = json!({});
    let mut ordered = observations
        .iter()
        .map(|o| Ok((o, time(&o["observed_at"])?)))
        .collect::<Result<Vec<_>>>()?;
    ordered.sort_by(|(a, at), (b, bt)| {
        (a["verification_status"] == "human_confirmed")
            .cmp(&(b["verification_status"] == "human_confirmed"))
            .then_with(|| at.cmp(bt))
            .then_with(|| a["id"].as_str().cmp(&b["id"].as_str()))
    });
    let mut future = false;
    for (o, at) in ordered {
        future |= at > now;
        if at <= now
            && at >= now - chrono::Duration::days(180)
            && !crate::contacts::rules::truthy(&o["attributes"]["historical"])
            && matches!(
                o["verification_status"].as_str(),
                Some("source_reported" | "human_confirmed")
            )
        {
            let public = crate::companies::attributes(&o["attributes"])?;
            for (key, value) in public.as_object().ok_or_else(invalid)? {
                if !value.is_null() && value != &json!([]) && value != "unknown" {
                    attributes[key] = value.clone();
                }
            }
        }
    }
    let size = intelligence::company_size(&observations, now, 180)?;
    let hiring = intelligence::hiring(
        &jobs,
        &observations,
        &board_rows,
        now,
        filters["freshness_days"].as_i64().ok_or_else(invalid)?,
    )?;
    let counts = crate::contacts::startup_counts_in(tx, &company, &size, settings, now).await?;
    let fresh = hiring["hiring_evidence"]
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .filter(|j| j["fresh"] == true)
        .map(|j| j["job_id"].as_str().ok_or_else(invalid))
        .collect::<Result<std::collections::BTreeSet<_>>>()?;
    let mut roles = filters["roles"]
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .map(|v| v.as_str().map(String::from).ok_or_else(invalid))
        .collect::<Result<Vec<_>>>()?;
    if roles.is_empty()
        && let Some(profile) = profile
    {
        roles = profile["preferences"]["target_titles"]
            .as_array()
            .ok_or_else(invalid)?
            .iter()
            .map(|v| v.as_str().map(String::from).ok_or_else(invalid))
            .collect::<Result<Vec<_>>>()?;
    }
    let relevant = jobs
        .iter()
        .filter(|j| {
            j["id"].as_str().is_some_and(|id| fresh.contains(id))
                && j["title"]
                    .as_str()
                    .is_some_and(|title| rules::role_allowed(title, &roles))
        })
        .cloned()
        .collect::<Vec<_>>();
    let supported = if counts["professional_contact_count"]
        .as_u64()
        .ok_or_else(invalid)?
        > 0
    {
        vec![json!({"confidence":"supported","priority":"preferred"})]
    } else {
        vec![]
    };
    let rank = ranking::rank(ranking::RankInput {
        company: &company,
        jobs: &relevant,
        attributes: &attributes,
        size: &size,
        hiring: &hiring,
        contacts: &supported,
        profile,
        filters,
    })?;
    let review = crate::contacts::rules::truthy(&company["metadata_"]["identity_review_required"]);
    let mut result = json!({"company_id":id,"company_name":company["name"],"company_domain":company["domain"],"attributes":attributes,"identity_review_required":review,"current_job_count":fresh.len(),"available_evidence_count":observations.len(),"shortlisted":false,"evidence_basis":"saved_local_records","live_verified":false,"profile_basis":"saved_profile_not_application_authority"});
    for value in [&size, &hiring, &rank, &counts] {
        for (key, value) in value.as_object().ok_or_else(invalid)? {
            result[key] = value.clone();
        }
    }
    if review {
        result["missing_information"]
            .as_array_mut()
            .ok_or_else(invalid)?
            .push(json!("company_identity_requires_review"));
    }
    if future {
        result["missing_information"]
            .as_array_mut()
            .ok_or_else(invalid)?
            .push(json!("future_company_observation_requires_review"));
    }
    let domain = company["domain"]
        .as_str()
        .and_then(crate::contacts::enrichment::lookups::domain);
    if !company["domain"].is_null() && domain.is_none() {
        result["missing_information"]
            .as_array_mut()
            .ok_or_else(invalid)?
            .push(json!("company_domain_requires_review"));
    }
    result["company_domain"] = json!(domain);
    let mut sources = std::collections::BTreeSet::new();
    for o in observations.iter().chain(board_rows.iter()) {
        sources.insert(
            o["source"]
                .as_str()
                .filter(|s| s.len() <= 100)
                .ok_or_else(invalid)?
                .to_owned(),
        );
    }
    result["sources"] = json!(sources);
    result["next_steps"] = json!({"jobs":format!("/api/v1/startups/{id}/jobs"),"contacts":format!("/api/v1/companies/{id}/contacts"),"contact_enrichment_preview":format!("/api/v1/companies/{id}/contacts/preview"),"outreach":"/api/v1/outreach/drafts","application_preview_template":"/api/v1/jobs/{job_id}/application-preview"});
    let shortlisted: bool = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM startup_shortlist_entries WHERE company_id=$1)",
    )
    .bind(id)
    .fetch_one(&mut **tx)
    .await
    .map_err(db)?;
    result["shortlisted"] = json!(shortlisted);
    Ok(Snapshot {
        public: result,
        jobs,
    })
}
pub async fn read(
    c: &mut PgConnection,
    id: Uuid,
    method: &str,
    query: Option<&str>,
    body: &[u8],
    settings: &crate::contacts::Settings,
) -> Result<Value> {
    if method != "GET" {
        return Err(Failure("startup_catalog_method_not_allowed"));
    }
    if query.is_some_and(|q| !q.is_empty()) || !body.is_empty() {
        return Err(Failure("invalid_startup_query"));
    }
    let filters = contract::normalize(Kind::Filters, json!({"max_employees":null}))?;
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let now: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let now = time(&now)?;
    let profile = profile_in(&mut tx, true).await?;
    let result = load_in(&mut tx, id, &filters, profile.as_ref(), settings, now).await?;
    tx.commit()
        .await
        .map_err(|_| Failure("startup_catalog_read_commit_failed"))?;
    Ok(result)
}
