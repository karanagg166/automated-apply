//! Original owner discovery admission, retained acquisition and local-only atomic result completion.
use super::{access, intake, plan::Source, ranking, scope, transport::Client};
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
    intake: Option<Value>,
}
pub(super) async fn state_in(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<State> {
    let row = row_in(tx, id)
        .await?
        .ok_or(Failure("discovery_run_not_found"))?;
    let journal = journal_in(tx, id).await?;
    if journal["schema"] != 1
        || journal["request_id"] != json!(id)
        || journal["child_id"] != json!(id)
        || !matches!(journal["state"].as_str(), Some("admitted" | "completed"))
        || journal["row"] != row
        || journal["scope_hash"] != crate::python_json::digest(&journal["scope"])
        || journal["scope"]["request_hash"] != row["request_hash"]
        || journal["scope"]["source"] != row["source"]
        || journal["state"] == "admitted" && row["status"] != "running"
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
    let mut state = State {
        row,
        journal,
        child,
        intake: None,
    };
    state.intake = intake::read_in(tx, &state, id).await?;
    if state.journal["state"] == "completed" {
        let receipt = state
            .intake
            .as_ref()
            .ok_or(Failure("discovery_run_intake_receipt_missing"))?;
        let expected = terminal_status(&receipt)?;
        if state.row["status"] != expected
            || state.row["counts"] != receipt["counts"]
            || state.row["query_summary"]["job_ids"] != receipt["job_ids"]
            || state.journal["local_receipt_hash"] != crate::python_json::digest(&receipt)
            || state.journal["rankings_hash"] != crate::python_json::digest(&state.row["rankings"])
            || state.row["provider_run_id"] != Value::Null
            || access::time(&state.row["finished_at"])? < access::time(&receipt["ingested_at"])?
        {
            return Err(invalid());
        }
        ranking::project(
            &state.row["rankings"],
            &receipt,
            &state.journal["scope"]["profile_pin"]["version"],
        )?;
    }
    Ok(state)
}
fn terminal_status(receipt: &Value) -> Result<&str> {
    let source = receipt["provider_status"].as_str().ok_or_else(invalid)?;
    Ok(
        if source == "success"
            && receipt["counts"]["discovered"]
                .as_u64()
                .is_some_and(|n| n > 0)
            && receipt["job_ids"].as_array().is_some_and(|a| a.is_empty())
        {
            "no_results"
        } else {
            source
        },
    )
}
fn output(state: &State, id: Uuid, now: DateTime<Utc>) -> Result<Value> {
    let child = access::visible(&state.child, id, now)?;
    if state.journal["state"] == "completed" {
        let receipt = state.intake.as_ref().ok_or_else(invalid)?;
        if access::time(&state.row["finished_at"])? > now {
            return Err(invalid());
        }
        let suppressed = state.row["usage"]["suppressed_prior_history"]
            .as_u64()
            .filter(|v| *v <= 100)
            .ok_or_else(invalid)?;
        let count = state.row["rankings"].as_array().ok_or_else(invalid)?.len();
        let original_profile = !state.journal["scope"]["profile_pin"].is_null();
        let unique = receipt["job_ids"]
            .as_array()
            .ok_or_else(invalid)?
            .iter()
            .filter_map(Value::as_str)
            .collect::<std::collections::BTreeSet<_>>()
            .len();
        if original_profile {
            if count + suppressed as usize != unique
                || state.journal["history_hash"]
                    .as_str()
                    .is_none_or(|s| s.len() != 64 || !s.bytes().all(|b| b.is_ascii_hexdigit()))
            {
                return Err(invalid());
            }
        } else if count != 0 || suppressed != 0 || !state.journal["history_hash"].is_null() {
            return Err(invalid());
        }
        if state.row["usage"]["stage"] != "completed"
            || state.row["usage"]["ranking_count"] != json!(count)
        {
            return Err(invalid());
        }
        let rankings = ranking::project(
            &state.row["rankings"],
            receipt,
            &state.journal["scope"]["profile_pin"]["version"],
        )?;
        if state.row["errors"] != child["errors"] {
            return Err(invalid());
        }
        return Ok(
            json!({"id":id,"source":state.row["source"],"status":state.row["status"],"counts":receipt["counts"],"errors":child["errors"],"started_at":state.row["started_at"],"finished_at":state.row["finished_at"],"provider_run_id":null,"rankings":rankings,"job_ids":receipt["job_ids"],"profile_version":state.journal["scope"]["profile_pin"]["version"],"usage":{"stage":"completed","provider_status":receipt["provider_status"],"provider_http_attempts":child["provider_http_attempts"],"provider_responses_observed":child["provider_responses_observed"],"provider_batch_complete":receipt["provider_batch_complete"],"finding_retained":true,"ranking_count":count,"suppressed_prior_history":suppressed,"replay_authorized":false},"local_intake_complete":true,"rankings_complete":true,"application_dispatch":false,"live_verified":false,"evidence_basis":"original_retained_finding_and_atomic_local_result"}),
        );
    }
    let started = access::time(&state.row["started_at"])?;
    let deadline = state.journal["timeout_seconds"]
        .as_f64()
        .ok_or_else(invalid)?
        + 120.0;
    let expired = (now - started).num_milliseconds() as f64 > deadline * 1000.0;
    if let Some(receipt) = &state.intake {
        return Ok(
            json!({"id":id,"source":state.row["source"],"status":if expired{"recovery_required"}else{"running"},"counts":receipt["counts"],"errors":child["errors"],"started_at":state.row["started_at"],"finished_at":null,"provider_run_id":null,"rankings":[],"job_ids":receipt["job_ids"],"profile_version":state.journal["scope"]["profile_pin"]["version"],"usage":{"stage":"rankings_pending","provider_status":child["status"],"provider_http_attempts":child["provider_http_attempts"],"provider_responses_observed":child["provider_responses_observed"],"finding_retained":true,"replay_authorized":false},"local_intake_complete":true,"rankings_complete":false,"application_dispatch":false,"live_verified":false,"evidence_basis":"original_owner_run_and_retained_local_receipt"}),
        );
    }
    let finding = child["recorded_state"] == "finding_retained";
    let count = child["jobs"].as_array().map_or(0, Vec::len);
    let errors = child.get("errors").cloned().unwrap_or(json!([]));
    Ok(
        json!({"id":id,"source":state.row["source"],"status":if expired{"recovery_required"}else{"running"},"counts":{"discovered":count,"inserted":0,"updated":0,"duplicate":0,"rejected":child["rejected_count"].as_u64().unwrap_or(0),"failed":0,"skipped":child["rejected_count"].as_u64().unwrap_or(0)},"errors":errors,"started_at":state.row["started_at"],"finished_at":null,"provider_run_id":null,"rankings":[],"job_ids":[],"profile_version":state.journal["scope"]["profile_pin"]["version"],"usage":{"stage":if finding{"local_intake_pending"}else{"provider_pending_or_unknown"},"provider_status":child["status"],"provider_http_attempts":child["provider_http_attempts"],"provider_responses_observed":child["provider_responses_observed"],"finding_retained":finding,"replay_authorized":false},"local_intake_complete":false,"rankings_complete":false,"application_dispatch":false,"live_verified":false,"evidence_basis":"original_owner_run_and_retained_child_state"}),
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
/// Finish retained observations using local SQL only. Original HTTP admission is never renewed.
pub async fn finish(c: &mut PgConnection, settings: &Settings, id: Uuid) -> Result<Value> {
    let mut tx = access::transaction(c).await?;
    let state = state_in(&mut tx, id).await?;
    let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    if state.journal["state"] == "completed" {
        let out = output(&state, id, now)?;
        tx.commit()
            .await
            .map_err(|_| Failure("discovery_run_commit_outcome_unknown"))?;
        return Ok(out);
    }
    intake::context_in(&mut tx, &state, settings, now).await?;
    let completion = intake::complete_in(&mut tx, &state, settings, id, now).await?;
    let profile = crate::startup_catalog::detail::profile_in(
        &mut tx,
        state.journal["scope"]["use_profile"] == true,
    )
    .await?;
    if scope::profile_pin(profile.as_ref())? != state.journal["scope"]["profile_pin"] {
        return Err(Failure("public_job_intake_profile_changed"));
    }
    let ranked = ranking::rank_in(&mut tx, &completion.receipt, profile.as_ref(), now).await?;
    let stamp: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let mut expected = state.row.clone();
    expected["query_summary"]["job_ids"] = completion.receipt["job_ids"].clone();
    expected["counts"] = completion.receipt["counts"].clone();
    expected["rankings"] = ranked.entries.clone();
    expected["status"] = json!(terminal_status(&completion.receipt)?);
    expected["finished_at"] = stamp;
    expected["errors"] = state.child["finding"]["errors"].clone();
    expected["usage"] = json!({"stage":"completed","provider_http_attempts":state.child["finding"]["provider_http_attempts"],"provider_responses_observed":state.child["finding"]["provider_responses_observed"],"ranking_count":ranked.entries.as_array().ok_or_else(invalid)?.len(),"suppressed_prior_history":ranked.suppressed});
    let saved:Option<Value>=sqlx::query_scalar("UPDATE discovery_runs AS r SET query_summary=$2->'query_summary',status=$2->>'status',counts=$2->'counts',rankings=$2->'rankings',errors=$2->'errors',finished_at=($2->>'finished_at')::timestamptz,usage=$2->'usage' WHERE id=$1 RETURNING to_jsonb(r)").bind(id).bind(&expected).fetch_optional(&mut *tx).await.map_err(db)?;
    if saved.as_ref() != Some(&expected) || row_in(&mut tx, id).await?.as_ref() != Some(&expected) {
        return Err(ack());
    }
    let mut journal = state.journal.clone();
    journal["state"] = json!("completed");
    journal["row"] = expected.clone();
    journal["local_receipt_hash"] = json!(crate::python_json::digest(&completion.receipt));
    journal["rankings_hash"] = json!(crate::python_json::digest(&ranked.entries));
    journal["history_hash"] = ranked.history_hash.clone();
    let saved:Option<Value>=sqlx::query_scalar("UPDATE owner_preferences SET value=$2,updated_at=clock_timestamp() WHERE key=$1 AND value=$3 RETURNING value").bind(key(id)).bind(&journal).bind(&state.journal).fetch_optional(&mut *tx).await.map_err(db)?;
    if saved.as_ref() != Some(&journal)
        || journal_in(&mut tx, id).await? != journal
        || row_in(&mut tx, id).await?.as_ref() != Some(&expected)
    {
        return Err(ack());
    }
    let after = state_in(&mut tx, id).await?;
    if after.child != state.child || after.journal != journal || after.row != expected {
        return Err(ack());
    }
    let end: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    completion
        .verify_in(&mut tx, &after, settings, id, end)
        .await?;
    intake::context_in(&mut tx, &after, settings, end).await?;
    ranked.verify_in(&mut tx).await?;
    let out = output(&after, id, end)?;
    tx.commit()
        .await
        .map_err(|_| Failure("discovery_run_commit_outcome_unknown"))?;
    Ok(out)
}
pub struct Service<'a> {
    pub settings: &'a Settings,
    pub client: &'a Client,
    pub timeout_seconds: f64,
}
impl Service<'_> {
    /// Compose original-only acquisition and atomic local result completion. A replay can only recover local work.
    pub async fn run(&self, c: &mut PgConnection, input: Value, id: Uuid) -> Result<Value> {
        self.acquire(c, input, id).await?;
        finish(c, self.settings, id).await
    }
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
