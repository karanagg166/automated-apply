//! Packet material has its own legacy fingerprint recipe, separate from answer-generation stamps.
//! Only a preloaded owner snapshot belongs here; this module performs no IO or authority changes.
use crate::{
    Failure, Result,
    job_context::Reviewed,
    packet_platform::{self, Policy},
    profile_contract,
    resources::{self, Resource},
};
use automated_apply_domain::matching::{self, Company, Listing, Profile};
use chrono::{DateTime, NaiveDate, NaiveDateTime, SecondsFormat, Timelike, Utc};
use serde::Deserialize;
use serde_json::{Map, Value, json};
use sqlx::{Postgres, Transaction};
use std::{collections::BTreeSet, sync::LazyLock};
use uuid::Uuid;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Material {
    job: Value,
    profile: Option<Value>,
    company: Option<Value>,
    resources: Vec<Resource>,
    evidence: Vec<Value>,
    observations: Vec<(String, String)>,
    revisions: Vec<Value>,
    selected: Option<Uuid>,
}
pub struct Built {
    pub job: Value,
    pub profile: Option<Value>,
    pub snapshot: Value,
    pub resources: Vec<Resource>,
}
fn invalid() -> Failure {
    Failure("invalid_packet_context_record")
}
fn uuid(value: &Value) -> Result<Uuid> {
    value
        .as_str()
        .and_then(|s| s.parse().ok())
        .ok_or_else(invalid)
}
fn instant(value: &str) -> Result<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(value)
        .map(|d| d.with_timezone(&Utc))
        .or_else(|_| {
            NaiveDateTime::parse_from_str(value, "%Y-%m-%dT%H:%M:%S%.f").map(|d| d.and_utc())
        })
        .map_err(|_| invalid())
}
/// asyncpg exposes timestamptz as UTC datetime; canonical fingerprints use Python's space separator.
fn python_time(value: &str) -> Result<String> {
    let date = instant(value)?;
    Ok(format!(
        "{}{}+00:00",
        date.format("%Y-%m-%d %H:%M:%S"),
        if date.timestamp_subsec_micros() == 0 {
            String::new()
        } else {
            format!(".{:06}", date.nanosecond() / 1000)
        }
    ))
}
fn rfc_time(value: &str) -> Result<String> {
    let date = instant(value)?;
    Ok(date.to_rfc3339_opts(
        if date.timestamp_subsec_micros() == 0 {
            SecondsFormat::Secs
        } else {
            SecondsFormat::Micros
        },
        true,
    ))
}
fn normalized_profile(raw: Value) -> Result<(Value, Value)> {
    let mut body = raw.as_object().ok_or_else(invalid)?.clone();
    for key in ["id", "version", "singleton_key", "created_at", "updated_at"] {
        body.remove(key);
    }
    let candidate =
        profile_contract::normalize_record(Value::Object(body)).map_err(|_| invalid())?;
    let mut profile = candidate.clone();
    profile["id"] = json!(uuid(&raw["id"])?);
    let version = raw["version"]
        .as_i64()
        .and_then(|v| i32::try_from(v).ok())
        .filter(|v| *v > 0)
        .ok_or_else(invalid)?;
    profile["version"] = json!(version);
    Ok((profile, candidate))
}
fn optional_text(value: &Value) -> Result<Option<&str>> {
    if value.is_null() {
        Ok(None)
    } else {
        value.as_str().map(Some).ok_or_else(invalid)
    }
}
fn trim(value: &Value) -> Result<Value> {
    Ok(match optional_text(value)? {
        Some(s) => json!(s.trim()),
        None => Value::Null,
    })
}
pub(crate) fn date_present(value: &Value) -> bool {
    let Some(s) = value.as_str() else {
        return false;
    };
    DateTime::parse_from_rfc3339(s).is_ok()
        || NaiveDateTime::parse_from_str(s, "%Y-%m-%dT%H:%M:%S%.f").is_ok()
        || NaiveDateTime::parse_from_str(s, "%Y-%m-%d %H:%M:%S%.f").is_ok()
        || NaiveDate::parse_from_str(s, "%Y-%m-%d").is_ok()
}
fn discovery(job: &Value, profile: &Value, company: Option<&Value>) -> Result<Value> {
    let mut listing = job.clone();
    for key in ["salary_min", "salary_max"] {
        if let Some(s) = listing[key].as_str() {
            let n = s
                .parse::<f64>()
                .ok()
                .filter(|n| n.is_finite())
                .ok_or_else(invalid)?;
            listing[key] = json!(n);
        }
    }
    if listing["skills_required"].is_null() {
        listing["skills_required"] = json!([]);
    }
    if listing["remote_type"].is_null() || listing["remote_type"] == "" {
        listing["remote_type"] = json!("unknown");
    }
    let listing: Listing = serde_json::from_value(listing).map_err(|_| invalid())?;
    let profile: Profile = serde_json::from_value(profile.clone()).map_err(|_| invalid())?;
    let company=company.map(|c| {
        let data=&c["metadata_"]["startup_discovery"];
        serde_json::from_value::<Company>(json!({"name":c["name"],"domain":c["domain"],"startup_stage":data["stage"],"startup_source":data["source"]})).map_err(|_|invalid())
    }).transpose()?;
    Ok(json!(matching::discovery_match(
        &listing,
        &profile,
        company.as_ref(),
        false
    )))
}
pub fn validate_snapshot(value: &Value) -> Result<()> {
    static SNAPSHOT: LazyLock<jsonschema::Validator> = LazyLock::new(|| {
        let schema: Value = serde_json::from_str(include_str!("../schemas/packet-snapshot.json"))
            .expect("frozen packet snapshot schema");
        jsonschema::draft202012::options()
            .should_validate_formats(false)
            .build(&schema)
            .expect("local packet snapshot validator")
    });
    if SNAPSHOT.is_valid(value) {
        Ok(())
    } else {
        Err(invalid())
    }
}
pub fn build(input: Value, policy: &Policy, now: DateTime<Utc>) -> Result<Built> {
    let mut data: Material = serde_json::from_value(input).map_err(|_| invalid())?;
    if data.resources.len() > 10000
        || data.evidence.len() > 10000
        || data.observations.len() > 10000
        || data.revisions.len() > 10000
    {
        return Err(Failure("packet_context_inventory_limit"));
    }
    uuid(&data.job["id"])?;
    if !data.job["company_id"].is_null() {
        uuid(&data.job["company_id"])?;
    }
    let original_profile = data.profile.clone();
    let (profile, candidate) = match data.profile {
        Some(profile) => {
            let (profile, candidate) = normalized_profile(profile)?;
            (Some(profile), candidate)
        }
        None => (None, Value::Null),
    };
    if profile.is_none() {
        data.resources.clear();
        data.evidence.clear();
        data.revisions.clear();
    }
    data.resources.sort_by_key(|r| r.id);
    // Destination selection uses the database's observation order. The digest
    // independently sorts/deduplicates below, as the legacy material recipe does.
    let reviewed = Reviewed::new(data.job, data.company)?;
    let mut job = reviewed.job_view().clone();
    let company = reviewed.employer();
    if job["source_platform"] == "naukri" && job["discovery_metadata"]["source_name"] == "naukri" {
        job["is_remote"] = json!(job["remote_type"] == "remote");
        job["date_posted"] = if date_present(&job["discovery_metadata"]["date_posted"]) {
            job["discovery_metadata"]["date_posted"].clone()
        } else {
            Value::Null
        };
    }
    let platform = packet_platform::select_at(&job, &data.observations, policy, now)?;
    let mut links = Map::new();
    if let Some(profile) = &original_profile {
        for (key, attr) in [
            ("github", "github_url"),
            ("linkedin", "linkedin_url"),
            ("portfolio", "portfolio_url"),
        ] {
            if let Some(url) = profile[attr].as_str().and_then(resources::public_https) {
                links.insert(key.into(), json!(url));
            }
        }
    }
    let resource_stamps = data
        .resources
        .iter()
        .map(|r| {
            Ok(json!([
                r.id,
                r.label,
                r.url,
                r.user_confirmed,
                r.is_primary,
                python_time(&r.updated_at)?
            ]))
        })
        .collect::<Result<Vec<_>>>()?;
    for resource in &mut data.resources {
        resource.updated_at = rfc_time(&resource.updated_at)?;
    }
    let resume = resources::select_resume(&data.resources, data.selected)?;
    let mut evidence = Vec::new();
    for row in data.evidence {
        let values = row
            .as_array()
            .filter(|a| a.len() == 3)
            .ok_or_else(invalid)?;
        if !values[2].is_boolean() {
            return Err(invalid());
        }
        evidence.push(json!([
            uuid(&values[0])?,
            python_time(values[1].as_str().ok_or_else(invalid)?)?,
            values[2]
        ]));
    }
    evidence.sort_by(|a, b| a[0].as_str().cmp(&b[0].as_str()));
    let observations = data.observations.iter().cloned().collect::<BTreeSet<_>>();
    let mut material = Map::new();
    material.insert("profile".into(), candidate.clone());
    material.insert(
        "profile_id".into(),
        profile
            .as_ref()
            .map(|p| p["id"].clone())
            .unwrap_or(Value::Null),
    );
    material.insert(
        "profile_version".into(),
        profile
            .as_ref()
            .map(|p| p["version"].clone())
            .unwrap_or(Value::Null),
    );
    let mut saved_job = Map::new();
    for key in [
        "id",
        "company_id",
        "title",
        "source_platform",
        "job_url",
        "application_url",
        "description",
        "skills_required",
        "location",
        "remote_type",
        "employment_type",
        "experience_level",
        "salary_min",
        "salary_max",
        "salary_currency",
        "salary_period",
        "source_verification_status",
    ] {
        saved_job.insert(key.into(), job[key].clone());
    }
    material.insert("job".into(), Value::Object(saved_job));
    material.insert("closed".into(), json!(job["status"] == "archived"));
    let metadata = if job["discovery_metadata"].is_null() {
        json!({})
    } else {
        job["discovery_metadata"].clone()
    };
    if !metadata.is_object() {
        return Err(invalid());
    }
    material.insert(
        "reviewed_opportunity".into(),
        metadata["application_opportunity"].clone(),
    );
    material.insert(
        "opportunity_evidence_current".into(),
        json!(
            !reviewed
                .opportunity(
                    now.timestamp() as f64 + f64::from(now.timestamp_subsec_micros()) / 1_000_000.0
                )?
                .is_empty()
        ),
    );
    material.insert(
        "company".into(),
        company
            .map(|c| json!([c["name"], c["domain"], c["metadata_"]]))
            .unwrap_or(Value::Null),
    );
    material.insert("resources".into(), json!(resource_stamps));
    material.insert("evidence".into(), json!(evidence));
    material.insert("observations".into(), json!(observations));
    if platform
        .platform
        .is_some_and(packet_platform::requires_manual_handoff)
    {
        material.insert(
            "platform_destination".into(),
            json!([
                platform.platform,
                platform.destination.application_url,
                platform.destination.valid,
                platform.destination.source_confidence,
                platform.destination.kind
            ]),
        );
    }
    if job["source_platform"] == "naukri" {
        material.insert("naukri_listing_review".into(),json!({"observed_criteria":metadata,"posting_unavailable":packet_platform::posting_unavailable(&job,now.date_naive())?}));
    }
    if profile.is_some() && !data.revisions.is_empty() {
        material.insert("owner_answer_revisions".into(), json!(data.revisions));
    }
    let digest = crate::python_json::digest(&Value::Object(material));
    let mut warnings = vec!["A recently observed job is not guaranteed to remain open".to_owned()];
    let observed = job["last_observed_at"].as_str().map(instant).transpose()?;
    if observed.is_none_or(|date| date < now - chrono::Duration::days(30)) {
        warnings.push(
            "Job information may be outdated; check that the vacancy is still open before approval"
                .into(),
        );
    }
    if job["description"].is_null() || job["description"] == "" {
        warnings.push(
            "Job description is missing; role-specific narrative generation may require input"
                .into(),
        );
    }
    let urls = data
        .observations
        .iter()
        .map(|(_, u)| u)
        .filter(|u| resources::public_https(u).is_some())
        .cloned()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .map(|s| s.trim().to_owned())
        .collect::<Vec<_>>();
    let original = packet_platform::hiringcafe_source_posting(&job, &data.observations)
        .map(Value::String)
        .unwrap_or(trim(&job["job_url"])?);
    let snapshot = json!({"preparation_supported":platform.preparation_supported,"platform":platform.platform,"company_id":job["company_id"],"company_name":company.map(|c|trim(&c["name"])).transpose()?.unwrap_or(Value::Null),"job_title":trim(&job["title"])?,"source_platform":trim(&job["source_platform"])?,"original_job_url":original,"source_observation_urls":urls,"destination":platform.destination,"candidate":candidate,"professional_links":links,"resume":resume,"match":profile.as_ref().map(|p|discovery(&job,p,company)).transpose()?,"context_digest":digest,"warnings":warnings});
    validate_snapshot(&snapshot)?;
    Ok(Built {
        job,
        profile,
        snapshot,
        resources: data.resources,
    })
}

fn db(error: sqlx::Error) -> Failure {
    crate::packet_service::db(error)
}
/// Retain the legacy material lock order before edits/review. Called after the packet claim.
pub(crate) async fn lock_in(tx: &mut Transaction<'_, Postgres>, job: Uuid) -> Result<()> {
    let company: Option<Option<Uuid>> =
        sqlx::query_scalar("SELECT company_id FROM jobs WHERE id=$1 FOR UPDATE")
            .bind(job)
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?;
    let company = company.ok_or(Failure("packet_job_not_found"))?;
    let profile: Option<Uuid> = sqlx::query_scalar(
        "SELECT id FROM candidate_profiles WHERE singleton_key='primary' FOR UPDATE",
    )
    .fetch_optional(&mut **tx)
    .await
    .map_err(db)?;
    if let Some(company) = company {
        sqlx::query("SELECT id FROM companies WHERE id=$1 FOR UPDATE")
            .bind(company)
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?;
    }
    if let Some(profile) = profile {
        sqlx::query("SELECT id FROM candidate_resources WHERE candidate_profile_id=$1 ORDER BY id FOR UPDATE").bind(profile).fetch_all(&mut **tx).await.map_err(db)?;
        sqlx::query("SELECT id FROM candidate_evidence WHERE candidate_profile_id=$1 ORDER BY id FOR UPDATE").bind(profile).fetch_all(&mut **tx).await.map_err(db)?;
        let available: bool =
            sqlx::query_scalar("SELECT to_regclass('owner_preferences') IS NOT NULL")
                .fetch_one(&mut **tx)
                .await
                .map_err(db)?;
        if available {
            sqlx::query("SELECT key FROM owner_preferences WHERE starts_with(key,'needs_input:') AND value->>'candidate_profile_id'=$1 AND (value->>'job_id' IS NULL OR value->>'job_id'=$2) ORDER BY key FOR UPDATE").bind(profile.to_string()).bind(job.to_string()).fetch_all(&mut **tx).await.map_err(db)?;
        }
    }
    sqlx::query("SELECT id FROM job_source_observations WHERE job_id=$1 ORDER BY source,original_url,id FOR UPDATE").bind(job).fetch_all(&mut **tx).await.map_err(db)?;
    Ok(())
}
/// Preload from the caller's existing consistent transaction. No connection, commit,
/// schema operation or source URL fetch is hidden inside packet material construction.
pub async fn load_in(
    tx: &mut Transaction<'_, Postgres>,
    id: Uuid,
    selected: Option<Uuid>,
    policy: &Policy,
    now: DateTime<Utc>,
) -> Result<Built> {
    let isolation: String = sqlx::query_scalar("SELECT current_setting('transaction_isolation')")
        .fetch_one(&mut **tx)
        .await
        .map_err(db)?;
    if !matches!(isolation.as_str(), "repeatable read" | "serializable") {
        return Err(Failure("packet_context_snapshot_required"));
    }
    load_material_in(tx, id, selected, policy, now).await
}
/// For review/handoff, acquire all legacy material locks and load immediately in the
/// same exclusive borrow. READ COMMITTED then observes STOP/preferences after the owner fence.
pub(crate) async fn load_locked_in(
    tx: &mut Transaction<'_, Postgres>,
    id: Uuid,
    selected: Option<Uuid>,
    policy: &Policy,
) -> Result<Built> {
    lock_in(tx, id).await?;
    load_material_in(tx, id, selected, policy, Utc::now()).await
}
async fn load_material_in(
    tx: &mut Transaction<'_, Postgres>,
    id: Uuid,
    selected: Option<Uuid>,
    policy: &Policy,
    now: DateTime<Utc>,
) -> Result<Built> {
    let job:Option<Value>=sqlx::query_scalar("SELECT jsonb_build_object('id',id,'company_id',company_id,'title',title,'source_platform',source_platform,'job_url',job_url,'application_url',application_url,'description',description,'skills_required',skills_required,'location',location,'remote_type',remote_type,'is_remote',is_remote,'employment_type',employment_type,'experience_level',experience_level,'salary_min',salary_min::text,'salary_max',salary_max::text,'salary_currency',salary_currency,'salary_period',salary_period,'source_verification_status',source_verification_status,'status',status,'discovery_metadata',discovery_metadata,'date_posted',date_posted,'last_observed_at',last_observed_at) FROM jobs WHERE id=$1").bind(id).fetch_optional(&mut **tx).await.map_err(db)?;
    let job = job.ok_or(Failure("packet_job_not_found"))?;
    let profile = match crate::profile_store::get(tx).await {
        Ok(saved) => Some(saved.value),
        Err(Failure("profile_not_found")) => None,
        Err(error) => return Err(error),
    };
    let company = if !job["company_id"].is_null() {
        sqlx::query_scalar::<_,Value>("SELECT jsonb_build_object('id',id,'name',name,'domain',domain,'metadata_',metadata) FROM companies WHERE id=$1").bind(uuid(&job["company_id"])?).fetch_optional(&mut **tx).await.map_err(db)?
    } else {
        None
    };
    let (resources, evidence, revisions) = if let Some(profile) = &profile {
        let owner = uuid(&profile["id"])?;
        let resources:Vec<Value>=sqlx::query_scalar("SELECT jsonb_build_object('id',id,'resource_type',resource_type,'label',label,'url',url,'is_primary',is_primary,'user_confirmed',user_confirmed,'source_type',source_type,'updated_at',updated_at) FROM candidate_resources WHERE candidate_profile_id=$1 ORDER BY id LIMIT 10001").bind(owner).fetch_all(&mut **tx).await.map_err(db)?;
        let evidence:Vec<Value>=sqlx::query_scalar("SELECT jsonb_build_array(id,updated_at,user_confirmed) FROM candidate_evidence WHERE candidate_profile_id=$1 ORDER BY id LIMIT 10001").bind(owner).fetch_all(&mut **tx).await.map_err(db)?;
        let available: bool =
            sqlx::query_scalar("SELECT to_regclass('owner_preferences') IS NOT NULL")
                .fetch_one(&mut **tx)
                .await
                .map_err(db)?;
        let revisions: Vec<Value> = if available {
            sqlx::query_scalar("SELECT jsonb_build_array(key,value->'version',value->'status',value->'context_digest') FROM owner_preferences WHERE starts_with(key,'needs_input:') AND value->>'candidate_profile_id'=$1 AND (value->>'ever_approved')::boolean IS TRUE AND (value->>'job_id' IS NULL OR value->>'job_id'=$2) ORDER BY key LIMIT 10001").bind(owner.to_string()).bind(id.to_string()).fetch_all(&mut **tx).await.map_err(db)?
        } else {
            vec![]
        };
        (resources, evidence, revisions)
    } else {
        (vec![], vec![], vec![])
    };
    let observations:Vec<(String,String)>=sqlx::query_as("SELECT source,original_url FROM job_source_observations WHERE job_id=$1 ORDER BY source,original_url LIMIT 10001").bind(id).fetch_all(&mut **tx).await.map_err(db)?;
    build(
        json!({"job":job,"profile":profile,"company":company,"resources":resources,"evidence":evidence,"observations":observations,"revisions":revisions,"selected":selected}),
        policy,
        now,
    )
}
