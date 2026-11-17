//! Actual owner discovery rows coupled to one original paid child, with local-only result completion.
use super::{admission, controller, intake, settings::Settings, transport::Client};
use crate::{
    Failure, Result,
    job_sources::{access, ranking, scope},
};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;
fn db(_: sqlx::Error) -> Failure {
    Failure("apify_owner_run_database_error")
}
fn invalid() -> Failure {
    Failure("invalid_apify_owner_run")
}
fn ack() -> Failure {
    Failure("apify_owner_run_write_ack_failed")
}
fn key(id: Uuid) -> String {
    format!("apify_owner:{}", id.simple())
}
async fn clock(tx: &mut Transaction<'_, Postgres>) -> Result<DateTime<Utc>> {
    sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut **tx)
        .await
        .map_err(db)
}
async fn row_in(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Option<Value>> {
    let v:Option<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(to_jsonb(r)::text)<=4194304 THEN to_jsonb(r) ELSE NULL END FROM discovery_runs r WHERE id=$1")
        .bind(id).fetch_optional(&mut **tx).await.map_err(db)?;
    match v {
        Some(Some(v)) => Ok(Some(v)),
        Some(None) => Err(Failure("apify_owner_run_saved_limit")),
        None => Ok(None),
    }
}
async fn journal_in(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Value> {
    let v:Option<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(value::text)<=4194304 THEN value ELSE NULL END FROM owner_preferences WHERE key=$1")
        .bind(key(id)).fetch_optional(&mut **tx).await.map_err(db)?;
    match v {
        Some(Some(v)) => Ok(v),
        Some(None) => Err(Failure("apify_owner_run_saved_limit")),
        None => Err(Failure("apify_owner_original_scope_missing")),
    }
}
struct State {
    row: Value,
    journal: Value,
    child: Value,
    selected: Value,
    receipt: Option<Value>,
}
fn terminal_status(receipt: &Value) -> Result<&str> {
    let status = receipt["provider_status"]
        .as_str()
        .filter(|s| matches!(*s, "success" | "partial" | "no_results"))
        .ok_or_else(invalid)?;
    Ok(
        if status == "success" && receipt["job_ids"].as_array().is_some_and(|a| a.is_empty()) {
            "no_results"
        } else {
            status
        },
    )
}
async fn state_in(
    tx: &mut Transaction<'_, Postgres>,
    id: Uuid,
    now: DateTime<Utc>,
) -> Result<State> {
    let row = row_in(tx, id)
        .await?
        .ok_or(Failure("discovery_run_not_found"))?;
    let journal = journal_in(tx, id).await?;
    let child = admission::load_in(tx, id)
        .await?
        .ok_or(Failure("apify_owner_child_missing"))?;
    let selected = admission::project_in(tx, &child, id, now).await?;
    let hash = scope::request_hash(&child["request"])?;
    if journal["schema"] != 1
        || !matches!(journal["state"].as_str(), Some("admitted" | "completed"))
        || journal["request_id"] != json!(id)
        || journal["child_id"] != json!(id)
        || journal["row"] != row
        || journal["child_scope_hash"] != child["scope_hash"]
        || journal["configuration_hash"] != child["configuration_hash"]
        || row["source"] != child["source"]
        || row["request_hash"] != hash
        || child["request_hash"] != hash
        || row["query_summary"]["explicit_query"] != child["request"]["query"]
        || row["query_summary"]["effective_query"] != child["effective_query"]
        || row["query_summary"]["profile_version"] != child["profile_pin"]["version"]
        || row["query_summary"]["native_request_id"] != json!(id)
        || access::time(&child["started_at"])? > access::time(&row["started_at"])?
        || access::time(&row["started_at"])? > access::time(&child["expires_at"])?
        || access::time(&row["started_at"])? > now
    {
        return Err(invalid());
    }
    let receipt = intake::read_in(tx, &child, id, now).await?;
    if journal["state"] == "admitted" {
        if row["status"] != "running"
            || !row["finished_at"].is_null()
            || !row["provider_run_id"].is_null()
            || row["rankings"] != json!([])
            || row["query_summary"]["job_ids"] != json!([])
            || row["counts"] != json!({})
            || row["errors"] != json!([])
        {
            return Err(invalid());
        }
    } else {
        let receipt = receipt
            .as_ref()
            .ok_or(Failure("apify_owner_local_receipt_missing"))?;
        if selected["finding_retained"] != true
            || row["status"] != terminal_status(receipt)?
            || row["counts"] != receipt["counts"]
            || row["query_summary"]["job_ids"] != receipt["job_ids"]
            || journal["local_receipt_hash"] != crate::python_json::digest(receipt)
            || journal["rankings_hash"] != crate::python_json::digest(&row["rankings"])
            || row["provider_run_id"] != selected["run_id"]
            || row["errors"] != selected["errors"]
            || row["usage"]["provider_http_attempts"] != selected["provider_http_attempts"]
            || row["usage"]["provider_responses_observed"] != selected["provider_http_responses"]
            || row["usage"]["billing_final"] != false
            || access::time(&row["finished_at"])? < access::time(&receipt["ingested_at"])?
            || access::time(&row["finished_at"])? > now
        {
            return Err(invalid());
        }
        ranking::project(&row["rankings"], receipt, &child["profile_pin"]["version"])?;
    }
    Ok(State {
        row,
        journal,
        child,
        selected,
        receipt,
    })
}
fn output(state: &State, id: Uuid, now: DateTime<Utc>) -> Result<Value> {
    let complete = state.journal["state"] == "completed";
    let finding = state.selected["finding_retained"] == true;
    let unknown = state.selected["status"] == "outcome_unknown"
        || now >= access::time(&state.child["expires_at"])?;
    let mut counts = json!({"discovered":state.selected["jobs"].as_array().map_or(0,Vec::len),"inserted":0,"updated":0,"duplicate":0,"rejected":state.selected["rejected_count"].as_u64().unwrap_or(0),"skipped":0,"failed":0});
    let mut ids = json!([]);
    if let Some(receipt) = &state.receipt {
        counts = receipt["counts"].clone();
        ids = receipt["job_ids"].clone();
    }
    let rankings = if complete {
        let receipt = state.receipt.as_ref().ok_or_else(invalid)?;
        let rankings = ranking::project(
            &state.row["rankings"],
            receipt,
            &state.child["profile_pin"]["version"],
        )?;
        let suppressed = state.row["usage"]["suppressed_prior_history"]
            .as_u64()
            .filter(|n| *n <= 100)
            .ok_or_else(invalid)?;
        let count = rankings.as_array().ok_or_else(invalid)?.len();
        let unique = ids
            .as_array()
            .ok_or_else(invalid)?
            .iter()
            .filter_map(Value::as_str)
            .collect::<std::collections::BTreeSet<_>>()
            .len();
        if state.child["profile_pin"].is_null() {
            if count != 0 || suppressed != 0 || !state.journal["history_hash"].is_null() {
                return Err(invalid());
            }
        } else if count + suppressed as usize != unique
            || state.journal["history_hash"]
                .as_str()
                .is_none_or(|s| s.len() != 64 || !s.bytes().all(|b| b.is_ascii_hexdigit()))
        {
            return Err(invalid());
        }
        if state.row["usage"]["stage"] != "completed"
            || state.row["usage"]["ranking_count"] != json!(count)
        {
            return Err(invalid());
        }
        rankings
    } else {
        json!([])
    };
    let stage = if complete {
        "completed"
    } else if state.receipt.is_some() {
        "rankings_pending"
    } else if finding {
        "local_intake_pending"
    } else {
        "provider_pending_or_unknown"
    };
    Ok(
        json!({"id":id,"source":state.row["source"],"status":if complete{state.row["status"].clone()}else{json!(if unknown{"recovery_required"}else{"running"})},"counts":counts,"errors":state.selected["errors"],"started_at":state.row["started_at"],"finished_at":state.row["finished_at"],"provider_run_id":state.selected["run_id"],"rankings":rankings,"job_ids":ids,"profile_version":state.child["profile_pin"]["version"],"usage":{"stage":stage,"provider_status":state.selected["status"],"provider_http_attempts":state.selected["provider_http_attempts"],"provider_responses_observed":state.selected["provider_http_responses"],"http_counts_are_minimum":state.selected["http_counts_are_minimum"],"finding_retained":finding,"provider_batch_complete":state.selected["batch_complete"],"ranking_count":rankings.as_array().ok_or_else(invalid)?.len(),"suppressed_prior_history":if complete{state.row["usage"]["suppressed_prior_history"].clone()}else{json!(0)},"replay_authorized":false,"read_rounds_admitted":state.selected["read_rounds_admitted"],"read_round_limit":state.selected["read_round_limit"],"last_read_request_id":state.selected["last_read_request_id"],"read_next_allowed_at":state.selected["read_next_allowed_at"]},"reservation":state.selected["reservation"],"billing_final":false,"local_intake_complete":state.receipt.is_some(),"rankings_complete":complete,"original_scope_available":true,"application_dispatch":false,"live_verified":false,"evidence_basis":"original_paid_owner_run_and_retained_local_result"}),
    )
}
pub struct Claim {
    id: Uuid,
    journal: Value,
    child: Option<Box<admission::Claim>>,
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
) -> Result<Admission> {
    let input = admission::request(input)?;
    let mut tx = admission::transaction(c).await?;
    let out = admit_in(&mut tx, settings, input, id).await?;
    tx.commit()
        .await
        .map_err(|_| Failure("apify_owner_commit_outcome_unknown"))?;
    Ok(out)
}
pub(crate) async fn admit_in(
    tx: &mut Transaction<'_, Postgres>,
    settings: &Settings,
    input: Value,
    id: Uuid,
) -> Result<Admission> {
    if id.is_nil() {
        return Err(invalid());
    }
    let input = admission::request(input)?;
    let hash = scope::request_hash(&input)?;
    let now = clock(tx).await?;
    if let Some(row) = row_in(tx, id).await? {
        if row["request_hash"] != hash {
            return Err(Failure("discovery_run_request_conflict"));
        }
        return Ok(Admission::Retained(output(
            &state_in(tx, id, now).await?,
            id,
            now,
        )?));
    }
    let compat = input["idempotency_key"]
        .as_str()
        .map(str::to_owned)
        .unwrap_or_else(|| format!("native_apify_{}", id.simple()));
    let used: bool =
        sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM discovery_runs WHERE idempotency_key=$1)")
            .bind(&compat)
            .fetch_one(&mut **tx)
            .await
            .map_err(db)?;
    if used {
        return Err(Failure("discovery_run_compatibility_key_conflict"));
    }
    let child = match admission::admit_in(tx, settings, input.clone(), id).await? {
        admission::Admission::Original(claim) => claim,
        _ => return Err(Failure("apify_owner_child_already_claimed")),
    };
    let stamp: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut **tx)
        .await
        .map_err(db)?;
    let summary = json!({"explicit_query":input["query"],"effective_query":child.journal["effective_query"],"profile_version":child.journal["profile_pin"]["version"],"job_ids":[],"native_request_id":id});
    let expected = json!({"id":id,"source":input["source"],"request_hash":hash,"query_summary":summary,"status":"running","rankings":[],"counts":{},"errors":[],"started_at":stamp,"finished_at":null,"provider_run_id":null,"usage":{"stage":"original_admission","provider_http_attempts":null},"idempotency_key":compat});
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO discovery_runs AS r(id,source,request_hash,query_summary,status,rankings,counts,errors,started_at,finished_at,provider_run_id,usage,idempotency_key) SELECT $1,$2->>'source',$2->>'request_hash',$2->'query_summary','running','[]','{}','[]',($2->>'started_at')::timestamptz,NULL,NULL,$2->'usage',$2->>'idempotency_key' RETURNING to_jsonb(r)").bind(id).bind(&expected).fetch_optional(&mut **tx).await.map_err(db)?;
    if saved.as_ref() != Some(&expected) {
        return Err(ack());
    }
    let journal = json!({"schema":1,"request_id":id,"child_id":id,"state":"admitted","child_scope_hash":child.journal["scope_hash"],"configuration_hash":child.journal["configuration_hash"],"row":expected});
    let saved: Option<Value> = sqlx::query_scalar(
        "INSERT INTO owner_preferences(key,value) VALUES($1,$2) RETURNING value",
    )
    .bind(key(id))
    .bind(&journal)
    .fetch_optional(&mut **tx)
    .await
    .map_err(db)?;
    if saved.as_ref() != Some(&journal)
        || journal_in(tx, id).await? != journal
        || row_in(tx, id).await?.as_ref() != Some(&expected)
    {
        return Err(ack());
    }
    admission::assert_original_in(tx, settings, &child).await?;
    let claim = Claim {
        id,
        journal,
        child: Some(child),
    };
    assert_original_in(tx, settings, &claim).await?;
    let end = clock(tx).await?;
    output(&state_in(tx, id, end).await?, id, end)?;
    Ok(Admission::Original(Box::new(claim)))
}
pub(crate) async fn assert_original_in(
    tx: &mut Transaction<'_, Postgres>,
    settings: &Settings,
    claim: &Claim,
) -> Result<()> {
    let now = clock(tx).await?;
    let state = state_in(tx, claim.id, now).await?;
    if state.journal != claim.journal {
        return Err(ack());
    }
    admission::assert_original_in(tx, settings, claim.child.as_ref().ok_or_else(ack)?).await
}
pub async fn read(c: &mut PgConnection, id: Uuid) -> Result<Value> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let now = clock(&mut tx).await?;
    let out = output(&state_in(&mut tx, id, now).await?, id, now)?;
    tx.commit().await.map_err(db)?;
    Ok(out)
}
pub(crate) async fn read_in(
    tx: &mut Transaction<'_, Postgres>,
    id: Uuid,
    at: DateTime<Utc>,
) -> Result<Value> {
    output(&state_in(tx, id, at).await?, id, at)
}
pub(crate) async fn scope_in(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Value> {
    let at = clock(tx).await?;
    let state = state_in(tx, id, at).await?;
    Ok(
        json!({"request_hash":state.child["request_hash"],"effective_query":state.child["effective_query"],"profile_pin":state.child["profile_pin"],"configuration_hash":state.child["configuration_hash"],"scope_hash":state.child["scope_hash"]}),
    )
}
pub(crate) async fn local_receipt_in(
    tx: &mut Transaction<'_, Postgres>,
    id: Uuid,
) -> Result<Option<Value>> {
    let at = clock(tx).await?;
    Ok(state_in(tx, id, at).await?.receipt)
}
pub(crate) async fn current_context_in(
    tx: &mut Transaction<'_, Postgres>,
    settings: &Settings,
    id: Uuid,
) -> Result<()> {
    let at = clock(tx).await?;
    let state = state_in(tx, id, at).await?;
    intake::context_in(tx, &state.child, settings, at).await
}
pub(crate) async fn ledger_in(
    tx: &mut Transaction<'_, Postgres>,
    id: Uuid,
) -> Result<(Value, String)> {
    let at = clock(tx).await?;
    let state = state_in(tx, id, at).await?;
    super::budget::monthly_snapshot_in(tx, &state.child["reservation"]).await
}
/// Finish saved findings/receipts locally; never construct a provider acquisition grant.
pub async fn finish(c: &mut PgConnection, settings: &Settings, id: Uuid) -> Result<Value> {
    let mut tx = admission::transaction(c).await?;
    let now = clock(&mut tx).await?;
    let state = state_in(&mut tx, id, now).await?;
    if state.journal["state"] == "completed" {
        let out = output(&state, id, now)?;
        tx.commit()
            .await
            .map_err(|_| Failure("apify_owner_commit_outcome_unknown"))?;
        return Ok(out);
    }
    if state.selected["finding_retained"] != true {
        return Err(Failure("apify_intake_finding_missing"));
    }
    intake::context_in(&mut tx, &state.child, settings, now).await?;
    let completion = intake::complete_in(&mut tx, &state.child, settings, id, now).await?;
    let profile = crate::startup_catalog::detail::profile_in(
        &mut tx,
        state.child["request"]["use_profile"] == true,
    )
    .await?;
    if scope::profile_pin(profile.as_ref())? != state.child["profile_pin"] {
        return Err(Failure("apify_intake_profile_changed"));
    }
    let ranked = ranking::rank_in(&mut tx, &completion.receipt, profile.as_ref(), now).await?;
    let stamp: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let mut expected = state.row.clone();
    expected["status"] = json!(terminal_status(&completion.receipt)?);
    expected["counts"] = completion.receipt["counts"].clone();
    expected["query_summary"]["job_ids"] = completion.receipt["job_ids"].clone();
    expected["rankings"] = ranked.entries.clone();
    expected["finished_at"] = stamp;
    expected["provider_run_id"] = state.selected["run_id"].clone();
    expected["errors"] = state.selected["errors"].clone();
    expected["usage"] = json!({"stage":"completed","ranking_count":ranked.entries.as_array().ok_or_else(invalid)?.len(),"suppressed_prior_history":ranked.suppressed,"provider_http_attempts":state.selected["provider_http_attempts"],"provider_responses_observed":state.selected["provider_http_responses"],"billing_final":false});
    let saved:Option<Value>=sqlx::query_scalar("UPDATE discovery_runs AS r SET query_summary=$2->'query_summary',status=$2->>'status',counts=$2->'counts',rankings=$2->'rankings',errors=$2->'errors',finished_at=($2->>'finished_at')::timestamptz,provider_run_id=$2->>'provider_run_id',usage=$2->'usage' WHERE id=$1 AND to_jsonb(r)=$3 RETURNING to_jsonb(r)").bind(id).bind(&expected).bind(&state.row).fetch_optional(&mut *tx).await.map_err(db)?;
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
    let end = clock(&mut tx).await?;
    let after = state_in(&mut tx, id, end).await?;
    if after.child != state.child || after.journal != journal || after.row != expected {
        return Err(ack());
    }
    completion
        .verify_in(&mut tx, &after.child, settings, id, end)
        .await?;
    intake::context_in(&mut tx, &after.child, settings, end).await?;
    ranked.verify_in(&mut tx).await?;
    let out = output(&after, id, end)?;
    tx.commit()
        .await
        .map_err(|_| Failure("apify_owner_commit_outcome_unknown"))?;
    Ok(out)
}
pub struct Service<'a> {
    pub settings: &'a Settings,
    pub client: &'a Client,
}
impl Service<'_> {
    pub async fn run(&self, c: &mut PgConnection, input: Value, id: Uuid) -> Result<Value> {
        self.acquire(c, input, id).await?;
        finish(c, self.settings, id).await
    }
    pub async fn acquire(&self, c: &mut PgConnection, input: Value, id: Uuid) -> Result<Value> {
        match admit(c, self.settings, input, id).await? {
            Admission::Retained(out) => Ok(out),
            Admission::Original(claim) => self.acquire_original(c, *claim).await,
        }
    }
    pub(crate) async fn acquire_original(
        &self,
        c: &mut PgConnection,
        mut claim: Claim,
    ) -> Result<Value> {
        let child = claim
            .child
            .take()
            .ok_or(Failure("apify_owner_original_child_missing"))?;
        controller::Service {
            settings: self.settings,
            client: self.client,
        }
        .acquire_original(c, *child)
        .await?;
        read(c, claim.id).await
    }
}
