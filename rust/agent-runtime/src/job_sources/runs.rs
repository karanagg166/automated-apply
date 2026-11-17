//! Actual owner discovery run + original child admission. Acquisition never completes local job intake.
use super::{access, plan::Source, scope, transport::Client};
use crate::{Failure, Result, source_registry::Settings};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;
fn db(_: sqlx::Error) -> Failure {
    Failure("discovery_run_database_error")
}
fn invalid() -> Failure {
    Failure("invalid_discovery_owner_run")
}
fn ack() -> Failure {
    Failure("discovery_run_write_ack_failed")
}
fn key(id: Uuid) -> String {
    format!("job_run:{}", id.simple())
}
fn timeout(value: f64) -> Result<()> {
    if value.is_finite() && (5.0..=180.0).contains(&value) {
        Ok(())
    } else {
        Err(invalid())
    }
}
async fn row_in(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Option<Value>> {
    let value:Option<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(to_jsonb(r)::text)<=4194304 THEN to_jsonb(r) ELSE NULL END FROM discovery_runs r WHERE id=$1").bind(id).fetch_optional(&mut **tx).await.map_err(db)?;
    match value {
        Some(Some(v)) => Ok(Some(v)),
        Some(None) => Err(Failure("discovery_run_saved_limit")),
        None => Ok(None),
    }
}
async fn journal_in(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Value> {
    let value:Option<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(value::text)<=1048576 THEN value ELSE NULL END FROM owner_preferences WHERE key=$1").bind(key(id)).fetch_optional(&mut **tx).await.map_err(db)?;
    match value {
        Some(Some(v)) => Ok(v),
        Some(None) => Err(Failure("discovery_run_saved_limit")),
        None => Err(Failure("discovery_run_original_scope_missing")),
    }
}
pub(super) struct State {
    pub(super) row: Value,
    pub(super) journal: Value,
    pub(super) child: Value,
}
pub(super) async fn state_in(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<State> {
    let row = row_in(tx, id)
        .await?
        .ok_or(Failure("discovery_run_not_found"))?;
    let journal = journal_in(tx, id).await?;
    if journal["schema"] != 1
        || journal["request_id"] != json!(id)
        || journal["child_id"] != json!(id)
        || journal["state"] != "admitted"
        || journal["row"] != row
        || journal["scope_hash"] != crate::python_json::digest(&journal["scope"])
        || journal["scope"]["request_hash"] != row["request_hash"]
        || journal["scope"]["source"] != row["source"]
        || row["status"] != "running"
    {
        return Err(invalid());
    }
    timeout(journal["timeout_seconds"].as_f64().ok_or_else(invalid)?)?;
    scope::validate(&journal["scope"])?;
    let child = access::load_in(tx, id)
        .await?
        .ok_or(Failure("discovery_run_child_missing"))?;
    if child["source"] != row["source"]
        || child["query"] != journal["scope"]["effective_query"]
        || child["configuration_hash"] != journal["configuration_hash"]
    {
        return Err(invalid());
    }
    let parent_at = access::time(&row["started_at"])?;
    if access::time(&child["started_at"])? > parent_at
        || parent_at > access::time(&child["expires_at"])?
    {
        return Err(invalid());
    }
    Ok(State {
        row,
        journal,
        child,
    })
}
fn output(state: &State, id: Uuid, now: DateTime<Utc>) -> Result<Value> {
    let child = access::visible(&state.child, id, now)?;
    let started = access::time(&state.row["started_at"])?;
    let deadline = state.journal["timeout_seconds"]
        .as_f64()
        .ok_or_else(invalid)?
        + 120.0;
    let expired = (now - started).num_milliseconds() as f64 > deadline * 1000.0;
    let finding = child["recorded_state"] == "finding_retained";
    let count = child["jobs"].as_array().map_or(0, Vec::len);
    let errors = child.get("errors").cloned().unwrap_or(json!([]));
    Ok(
        json!({"id":id,"source":state.row["source"],"status":if expired{"recovery_required"}else{"running"},"counts":{"discovered":count,"inserted":0,"updated":0,"duplicate":0,"rejected":child["rejected_count"].as_u64().unwrap_or(0),"failed":0,"skipped":child["rejected_count"].as_u64().unwrap_or(0)},"errors":errors,"started_at":state.row["started_at"],"finished_at":null,"provider_run_id":null,"rankings":[],"job_ids":[],"profile_version":state.journal["scope"]["profile_pin"]["version"],"usage":{"stage":if finding{"local_intake_pending"}else{"provider_pending_or_unknown"},"provider_status":child["status"],"provider_http_attempts":child["provider_http_attempts"],"provider_responses_observed":child["provider_responses_observed"],"finding_retained":finding,"replay_authorized":false},"local_intake_complete":false,"application_dispatch":false,"live_verified":false,"evidence_basis":"original_owner_run_and_retained_child_state"}),
    )
}
pub struct Claim {
    id: Uuid,
    child: Option<Box<access::Claim>>,
}
impl Claim {
    pub fn request_id(&self) -> Uuid {
        self.id
    }
}
pub enum Admission {
    Retained(Value),
    Original(Box<Claim>),
}
pub async fn admit(
    c: &mut PgConnection,
    settings: &Settings,
    input: Value,
    id: Uuid,
    deadline: f64,
) -> Result<Admission> {
    timeout(deadline)?;
    let request = scope::normalize(input)?;
    let hash = scope::request_hash(&request)?;
    let source = Source::parse(request["source"].as_str().ok_or_else(invalid)?)?;
    if request["manual_jobs"]
        .as_array()
        .is_none_or(|a| !a.is_empty())
    {
        return Err(Failure("public_job_manual_source_required"));
    }
    let mut tx = access::transaction(c).await?;
    let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    if let Some(row) = row_in(&mut tx, id).await? {
        if row["request_hash"] != hash {
            return Err(Failure("discovery_run_request_conflict"));
        }
        let state = state_in(&mut tx, id).await?;
        let out = output(&state, id, now)?;
        tx.commit()
            .await
            .map_err(|_| Failure("discovery_run_commit_outcome_unknown"))?;
        return Ok(Admission::Retained(out));
    }
    let compat = request["idempotency_key"]
        .as_str()
        .map(str::to_owned)
        .unwrap_or_else(|| format!("native_public_{}", id.simple()));
    let exists: bool =
        sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM discovery_runs WHERE idempotency_key=$1)")
            .bind(&compat)
            .fetch_one(&mut *tx)
            .await
            .map_err(db)?;
    if exists {
        return Err(Failure("discovery_run_compatibility_key_conflict"));
    }
    let profile =
        crate::startup_catalog::detail::profile_in(&mut tx, request["use_profile"] == true).await?;
    let plan = scope::build(request.clone(), profile.as_ref())?;
    let child = match access::admit_in(
        &mut tx,
        settings,
        source,
        plan["effective_query"].clone(),
        id,
        Some(now + chrono::Duration::microseconds((deadline * 1_000_000.0).floor() as i64)),
    )
    .await?
    {
        access::Admission::Original(claim) => claim,
        _ => return Err(Failure("discovery_run_source_id_already_claimed")),
    };
    let stamp: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let summary = json!({"explicit_query":plan["explicit_query"],"effective_query":plan["effective_query"],"profile_version":plan["profile_pin"]["version"],"job_ids":[],"native_request_id":id});
    let expected = json!({"id":id,"source":source.name(),"request_hash":hash,"query_summary":summary,"status":"running","rankings":[],"counts":{},"errors":[],"started_at":stamp,"finished_at":null,"provider_run_id":null,"usage":{"stage":"original_admission","provider_http_attempts":null},"idempotency_key":compat});
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO discovery_runs AS r(id,source,request_hash,query_summary,status,rankings,counts,errors,started_at,finished_at,provider_run_id,usage,idempotency_key) SELECT $1,$2->>'source',$2->>'request_hash',$2->'query_summary','running','[]','{}','[]',($2->>'started_at')::timestamptz,NULL,NULL,$2->'usage',$2->>'idempotency_key' RETURNING to_jsonb(r)").bind(id).bind(&expected).fetch_optional(&mut *tx).await.map_err(db)?;
    if saved.as_ref() != Some(&expected) {
        return Err(ack());
    }
    let journal = json!({"schema":1,"request_id":id,"child_id":id,"state":"admitted","scope":plan,"scope_hash":crate::python_json::digest(&plan),"configuration_hash":child.journal["configuration_hash"],"row":expected,"timeout_seconds":deadline});
    let saved: Option<Value> = sqlx::query_scalar(
        "INSERT INTO owner_preferences(key,value) VALUES($1,$2) RETURNING value",
    )
    .bind(key(id))
    .bind(&journal)
    .fetch_optional(&mut *tx)
    .await
    .map_err(db)?;
    if saved.as_ref() != Some(&journal)
        || journal_in(&mut tx, id).await? != journal
        || row_in(&mut tx, id).await?.as_ref() != Some(&expected)
    {
        return Err(ack());
    }
    access::assert_original_in(&mut tx, &child).await?;
    let profile_now =
        crate::startup_catalog::detail::profile_in(&mut tx, request["use_profile"] == true).await?;
    if scope::profile_pin(profile_now.as_ref())? != journal["scope"]["profile_pin"] {
        return Err(ack());
    }
    let state = state_in(&mut tx, id).await?;
    output(&state, id, now.max(access::time(&expected["started_at"])?))?;
    tx.commit()
        .await
        .map_err(|_| Failure("discovery_run_commit_outcome_unknown"))?;
    Ok(Admission::Original(Box::new(Claim {
        id,
        child: Some(child),
    })))
}
pub async fn read(c: &mut PgConnection, id: Uuid) -> Result<Value> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let state = state_in(&mut tx, id).await?;
    let out = output(&state, id, now)?;
    tx.commit().await.map_err(db)?;
    Ok(out)
}
pub struct Service<'a> {
    pub settings: &'a Settings,
    pub client: &'a Client,
    pub timeout_seconds: f64,
}
impl Service<'_> {
    pub async fn acquire(&self, c: &mut PgConnection, input: Value, id: Uuid) -> Result<Value> {
        match admit(c, self.settings, input, id, self.timeout_seconds).await? {
            Admission::Retained(v) => Ok(v),
            Admission::Original(mut claim) => {
                let child = claim
                    .child
                    .take()
                    .ok_or(Failure("discovery_run_original_child_missing"))?;
                super::controller::acquire_original(c, self.client, *child).await?;
                read(c, claim.id).await
            }
        }
    }
}
