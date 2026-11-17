//! Atomic original paid intent and full-cap reservation. Saved state cannot reconstruct a remote grant.
use super::{budget, plan::Plan, settings::Settings};
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;
fn db(_: sqlx::Error) -> Failure {
    Failure("apify_execution_database_error")
}
fn invalid() -> Failure {
    Failure("invalid_apify_original_intent")
}
fn ack() -> Failure {
    Failure("apify_execution_write_ack_failed")
}
pub(super) fn key(id: Uuid) -> String {
    format!("apify_job:{}", id.simple())
}
pub(super) async fn transaction(c: &mut PgConnection) -> Result<Transaction<'_, Postgres>> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    crate::execution::lock_owner_in(&mut tx).await?;
    Ok(tx)
}
async fn clock(tx: &mut Transaction<'_, Postgres>) -> Result<DateTime<Utc>> {
    sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut **tx)
        .await
        .map_err(db)
}
pub(super) async fn load_in(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Option<Value>> {
    let value:Option<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(value::text)<=9437184 THEN value ELSE NULL END FROM owner_preferences WHERE key=$1").bind(key(id)).fetch_optional(&mut **tx).await.map_err(db)?;
    match value {
        Some(Some(v)) => Ok(Some(v)),
        Some(None) => Err(Failure("apify_original_intent_saved_limit")),
        None => Ok(None),
    }
}
fn request(value: Value) -> Result<Value> {
    let input = crate::job_sources::scope::normalize(value)?;
    if input["source"]
        .as_str()
        .is_none_or(|s| !crate::source_registry::APIFY_PORTALS.contains(&s))
    {
        return Err(Failure("apify_portal_unknown"));
    }
    if input["manual_jobs"]
        .as_array()
        .is_none_or(|a| !a.is_empty())
    {
        return Err(Failure("apify_manual_records_not_supported"));
    }
    Ok(input)
}
fn time(v: &Value) -> Result<DateTime<Utc>> {
    crate::job_sources::access::time(v).map_err(|_| invalid())
}
fn hash(v: &Value) -> Result<&str> {
    v.as_str()
        .filter(|s| s.len() == 64 && s.bytes().all(|b| b.is_ascii_hexdigit()))
        .ok_or_else(invalid)
}
pub(super) async fn project_in(
    tx: &mut Transaction<'_, Postgres>,
    journal: &Value,
    id: Uuid,
    now: DateTime<Utc>,
) -> Result<Value> {
    let started = time(&journal["started_at"])?;
    let expires = time(&journal["expires_at"])?;
    let request = request(journal["request"].clone())?;
    let query = crate::job_sources::contract::query(journal["effective_query"].clone())?;
    if id.is_nil()
        || journal["schema"] != 1
        || journal["request_id"] != json!(id)
        || !matches!(
            journal["state"].as_str(),
            Some(
                "dispatch_admitted"
                    | "operation_admitted"
                    | "response_retained"
                    | "finding_retained"
                    | "failed"
            )
        )
        || journal["start_admissions"] != 1
        || journal["request_hash"] != crate::job_sources::scope::request_hash(&request)?
        || journal["request"] != request
        || journal["source"] != request["source"]
        || query != journal["effective_query"]
        || started > now
        || expires != started + chrono::Duration::seconds(75)
        || journal["invocation_id"]
            .as_str()
            .and_then(|v| v.parse::<Uuid>().ok())
            .is_none_or(|v| v.is_nil())
    {
        return Err(invalid());
    }
    hash(&journal["credential_context"])?;
    hash(&journal["configuration_hash"])?;
    if journal["scope_hash"]
        != crate::python_json::digest(
            &json!({"request_hash":journal["request_hash"],"effective_query":query,"profile_pin":journal["profile_pin"],"configuration_hash":journal["configuration_hash"],"credential_context":journal["credential_context"]}),
        )
    {
        return Err(invalid());
    }
    let pin = &journal["profile_pin"];
    if pin.is_null() {
        if query != request["query"] {
            return Err(invalid());
        }
    } else if request["use_profile"] != true
        || pin.as_object().is_none_or(|p| p.len() != 3)
        || pin["id"]
            .as_str()
            .and_then(|s| s.parse::<Uuid>().ok())
            .is_none_or(|v| v.is_nil())
        || pin["version"]
            .as_i64()
            .is_none_or(|v| v <= 0 || v > i32::MAX as i64)
        || hash(&pin["content_hash"]).is_err()
    {
        return Err(invalid());
    }
    for field in ["page", "limit", "max_age_days"] {
        if query[field] != request["query"][field] {
            return Err(invalid());
        }
    }
    for field in ["keywords", "locations", "employment_types"] {
        if request["query"][field]
            .as_array()
            .is_some_and(|a| !a.is_empty())
            && query[field] != request["query"][field]
        {
            return Err(invalid());
        }
    }
    if !request["query"]["remote_preference"].is_null()
        && query["remote_preference"] != request["query"]["remote_preference"]
    {
        return Err(invalid());
    }
    let reservation = budget::read_reserved_in(tx, id, &journal["reservation"]).await?;
    let operation = journal.get("operation").filter(|v| v.is_object());
    let (attempts, responses) = if let Some(op) = operation {
        let seq = op["sequence"]
            .as_u64()
            .filter(|n| (1..=12).contains(n))
            .ok_or_else(invalid)?;
        if !matches!(
            op["kind"].as_str(),
            Some(
                "actor" | "reviewed_build" | "start" | "status" | "run_build" | "dataset" | "abort"
            )
        ) || !matches!(op["state"].as_str(), Some("admitted" | "retained"))
        {
            return Err(invalid());
        }
        hash(&op["target_hash"])?;
        let attempts = journal["http_attempts"]
            .as_u64()
            .filter(|n| *n <= seq)
            .ok_or_else(invalid)?;
        let responses = journal["http_responses"]
            .as_u64()
            .filter(|n| *n <= attempts)
            .ok_or_else(invalid)?;
        if journal["decoded_bytes"]
            .as_u64()
            .is_none_or(|n| n > 8388608)
        {
            return Err(invalid());
        }
        (Some(attempts), Some(responses))
    } else {
        if journal["state"] != "dispatch_admitted" {
            return Err(invalid());
        }
        (None, None)
    };
    let start = if journal["start_intent"] == true {
        match journal["start_attempted"] {
            Value::Bool(v) => json!(v),
            Value::Null => Value::Null,
            _ => return Err(invalid()),
        }
    } else if operation.is_some() {
        json!(false)
    } else {
        Value::Null
    };
    let selected_run = journal.get("selected_run");
    if let Some(run) = selected_run {
        if journal["selected_run_hash"] != crate::python_json::digest(run)
            || run["id"] != journal["reservation"]["provider_run_id"]
            || run["billing_final"] != false
            || run["independent_termination_verified"] != false
            || run["id"].as_str().is_none_or(|s| {
                s.is_empty()
                    || s.len() > 100
                    || !s
                        .bytes()
                        .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
            })
        {
            return Err(invalid());
        }
    }
    let errors = journal.get("failure_codes").cloned().unwrap_or(json!([]));
    if errors.as_array().is_none_or(|a| {
        a.len() > 30
            || a.iter().any(|v| {
                v.as_str().is_none_or(|s| {
                    s.len() > 150
                        || !s
                            .bytes()
                            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_')
                })
            })
    }) {
        return Err(invalid());
    }
    let mut out = json!({"request_id":id,"source":journal["source"],"recorded_state":journal["state"],"status":if journal["state"]=="failed" || errors.as_array().is_some_and(|a|!a.is_empty()) || now>=expires{"outcome_unknown"}else{"pending"},"started_at":journal["started_at"],"expires_at":journal["expires_at"],"start_admissions":1,"provider_start_attempted":start,"provider_response_retained":responses.is_some_and(|n|n>0),"provider_http_attempts":attempts,"provider_http_responses":responses,"http_counts_are_minimum":operation.is_some_and(|v|v["state"]=="admitted"),"run_id":selected_run.map(|v|v["id"].clone()),"dataset_id":null,"jobs":[],"errors":errors,"reservation":reservation,"replay_authorized":false,"account_rotation":false,"application_dispatch":false,"live_verified":false,"evidence_basis":"original_paid_intent_and_selected_checkpoints"});
    if journal["state"] == "finding_retained" {
        if journal["finding_hash"] != crate::python_json::digest(&journal["finding"])
            || journal["selected_run"]["status"] != "SUCCEEDED"
        {
            return Err(invalid());
        }
        let finding = super::finding::project(
            &journal["finding"],
            journal["source"].as_str().ok_or_else(invalid)?,
            query["limit"].as_u64().ok_or_else(invalid)?,
            now,
        )?;
        for job in finding["jobs"].as_array().ok_or_else(invalid)? {
            if job["data_provenance"]["provider_run_id"] != journal["selected_run"]["id"]
                || crate::apify_config::safe_actor(
                    job["data_provenance"]["actor_id"]
                        .as_str()
                        .ok_or_else(invalid)?,
                )? != journal["selected_actor"]["alias"]
                    .as_str()
                    .ok_or_else(invalid)?
                || job["data_provenance"]["actor_build"] != journal["selected_run"]["buildNumber"]
            {
                return Err(invalid());
            }
        }
        for field in [
            "status",
            "jobs",
            "rejected_count",
            "duplicate_count",
            "observed_at",
            "batch_complete",
            "billing_final",
        ] {
            out[field] = finding[field].clone();
        }
        out["finding_retained"] = json!(true);
        out["local_intake_complete"] = json!(false);
        out["evidence_basis"] = json!("retained_selected_apify_dataset_not_local_job_intake");
    }
    Ok(out)
}
/// Only the original in-memory claim holds this grant; no Clone/Serialize/Debug or rehydrate constructor.
pub(super) struct Grant {
    pub(super) plan: Plan,
    pub(super) id: Uuid,
    pub(super) invocation: Uuid,
    pub(super) expires: DateTime<Utc>,
}
pub struct Claim {
    pub(super) journal: Value,
    pub(super) grant: Option<Grant>,
}
impl Claim {
    pub fn request_id(&self) -> Uuid {
        self.grant.as_ref().map(|g| g.id).unwrap_or(Uuid::nil())
    }
}
pub enum Admission {
    Retained(Value),
    Original(Box<Claim>),
}
pub async fn admit(
    c: &mut PgConnection,
    settings: &Settings,
    raw: Value,
    id: Uuid,
) -> Result<Admission> {
    if id.is_nil() {
        return Err(invalid());
    }
    let input = request(raw)?;
    let input_hash = crate::job_sources::scope::request_hash(&input)?;
    let mut tx = transaction(c).await?;
    let now = clock(&mut tx).await?;
    if let Some(saved) = load_in(&mut tx, id).await? {
        if saved["request_hash"] != input_hash {
            return Err(Failure("apify_original_intent_request_conflict"));
        }
        let result = project_in(&mut tx, &saved, id, now).await?;
        tx.commit()
            .await
            .map_err(|_| Failure("apify_execution_commit_outcome_unknown"))?;
        return Ok(Admission::Retained(result));
    }
    let profile =
        crate::startup_catalog::detail::profile_in(&mut tx, input["use_profile"] == true).await?;
    let query = crate::job_sources::scope::effective_query(&input["query"], profile.as_ref())?;
    let pin = crate::job_sources::scope::profile_pin(profile.as_ref())?;
    let source = input["source"].as_str().ok_or_else(invalid)?;
    let plan = settings.plan(source, query.clone(), input["allow_paid"] == true, now)?;
    let credential = settings.credential_context()?;
    let reservation =
        budget::reserve_in(&mut tx, id, plan.cap(), settings.monthly_cap(), now).await?;
    let scope = json!({"request_hash":input_hash,"effective_query":query,"profile_pin":pin,"configuration_hash":plan.context(),"credential_context":credential});
    let invocation = Uuid::new_v4();
    let expires = now + chrono::Duration::seconds(75);
    let journal = json!({"schema":1,"request_id":id,"source":source,"state":"dispatch_admitted","start_admissions":1,"request":input,"request_hash":input_hash,"effective_query":query,"profile_pin":pin,"configuration_hash":plan.context(),"credential_context":credential,"scope_hash":crate::python_json::digest(&scope),"invocation_id":invocation,"started_at":now.to_rfc3339(),"expires_at":expires.to_rfc3339(),"reservation":reservation.row});
    if journal.to_string().len() > 524288 {
        return Err(Failure("apify_original_intent_saved_limit"));
    }
    let saved: Option<Value> = sqlx::query_scalar(
        "INSERT INTO owner_preferences(key,value) VALUES($1,$2) RETURNING value",
    )
    .bind(key(id))
    .bind(&journal)
    .fetch_optional(&mut *tx)
    .await
    .map_err(db)?;
    if saved.as_ref() != Some(&journal) || load_in(&mut tx, id).await?.as_ref() != Some(&journal) {
        return Err(ack());
    }
    reservation.verify_in(&mut tx).await?;
    let profile_now =
        crate::startup_catalog::detail::profile_in(&mut tx, input["use_profile"] == true).await?;
    if crate::job_sources::scope::profile_pin(profile_now.as_ref())? != pin {
        return Err(ack());
    }
    let end = clock(&mut tx).await?;
    project_in(&mut tx, &journal, id, end).await?;
    if end >= expires {
        return Err(Failure("apify_original_intent_expired_before_commit"));
    }
    tx.commit()
        .await
        .map_err(|_| Failure("apify_execution_commit_outcome_unknown"))?;
    Ok(Admission::Original(Box::new(Claim {
        journal,
        grant: Some(Grant {
            plan,
            id,
            invocation,
            expires,
        }),
    })))
}
pub async fn read(c: &mut PgConnection, id: Uuid) -> Result<Value> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let now = clock(&mut tx).await?;
    let saved = load_in(&mut tx, id)
        .await?
        .ok_or(Failure("apify_original_intent_not_found"))?;
    let out = project_in(&mut tx, &saved, id, now).await?;
    tx.commit().await.map_err(db)?;
    Ok(out)
}
