//! Separate bounded read intents over acknowledged original runs. Saved replay never renews a grant.
use super::{admission, budget, read_context::ReadContext, settings::Settings};
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;
fn db(_: sqlx::Error) -> Failure {
    Failure("apify_read_database_error")
}
fn invalid() -> Failure {
    Failure("apify_read_intent_invalid")
}
fn ack() -> Failure {
    Failure("apify_read_write_ack_failed")
}
fn uuid(v: &Value) -> Result<Uuid> {
    v.as_str()
        .and_then(|s| s.parse().ok())
        .filter(|v: &Uuid| !v.is_nil())
        .ok_or_else(invalid)
}
fn hash(v: &Value) -> Result<&str> {
    v.as_str()
        .filter(|s| s.len() == 64 && s.bytes().all(|b| b.is_ascii_hexdigit()))
        .ok_or_else(invalid)
}
fn time(v: &Value) -> Result<DateTime<Utc>> {
    crate::job_sources::access::time(v).map_err(|_| invalid())
}
pub(super) fn key(id: Uuid) -> String {
    format!("apify_read:{}", id.simple())
}
pub(super) struct Allowance {
    pub(super) ids: Vec<Uuid>,
    last: Option<DateTime<Utc>>,
    pub(super) next: Option<DateTime<Utc>>,
}
pub(super) fn allowance(original: &Value) -> Result<Allowance> {
    let value = &original["read_recovery"];
    if value["schema"] != 1 || value.as_object().is_none_or(|m| m.len() != 4) {
        return Err(invalid());
    }
    let ids = value["requests"]
        .as_array()
        .filter(|a| a.len() <= 3)
        .ok_or_else(invalid)?
        .iter()
        .map(uuid)
        .collect::<Result<Vec<_>>>()?;
    if ids.iter().collect::<std::collections::BTreeSet<_>>().len() != ids.len() {
        return Err(invalid());
    }
    let (last, next) = if ids.is_empty() {
        if !value["last_admitted_at"].is_null() || !value["next_allowed_at"].is_null() {
            return Err(invalid());
        }
        (None, None)
    } else {
        let last = time(&value["last_admitted_at"])?;
        let next = time(&value["next_allowed_at"])?;
        if last < time(&original["expires_at"])? || next != last + chrono::Duration::minutes(5) {
            return Err(invalid());
        }
        (Some(last), Some(next))
    };
    Ok(Allowance { ids, last, next })
}
pub(super) async fn load_in(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Option<Value>> {
    let value:Option<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(value::text)<=9437184 THEN value ELSE NULL END FROM owner_preferences WHERE key=$1")
        .bind(key(id)).fetch_optional(&mut **tx).await.map_err(db)?;
    match value {
        Some(Some(v)) => Ok(Some(v)),
        Some(None) => Err(Failure("apify_read_saved_limit")),
        None => Ok(None),
    }
}
fn visible(
    j: &Value,
    original: &Value,
    ordinal: usize,
    now: DateTime<Utc>,
    reservation: &Value,
) -> Result<Value> {
    let id = uuid(&j["read_request_id"])?;
    let parent = uuid(&original["request_id"])?;
    let at = time(&j["admitted_at"])?;
    let expires = time(&j["expires_at"])?;
    if j["schema"] != 1
        || j["request_id"] != json!(parent)
        || id == parent
        || j["round"] != json!(ordinal + 1)
        || j["source"] != original["source"]
        || j["scope_hash"] != original["scope_hash"]
        || j["configuration_hash"] != original["configuration_hash"]
        || j["credential_context"] != original["credential_context"]
        || j["run_id"] != original["selected_run"]["id"]
        || j["read_admissions"] != 1
        || !matches!(
            j["state"].as_str(),
            Some(
                "read_admitted"
                    | "operation_admitted"
                    | "response_retained"
                    | "finding_retained"
                    | "failed"
            )
        )
        || at < time(&original["expires_at"])?
        || at > now
        || expires != at + chrono::Duration::seconds(45)
    {
        return Err(invalid());
    }
    hash(&j["original_journal_hash"])?;
    uuid(&j["invocation_id"])?;
    let sequence = j["operation"]["sequence"].as_u64().unwrap_or(0);
    let attempts = j["http_attempts"]
        .as_u64()
        .filter(|n| *n <= sequence && *n <= 4)
        .ok_or_else(invalid)?;
    let responses = j["http_responses"]
        .as_u64()
        .filter(|n| *n <= attempts)
        .ok_or_else(invalid)?;
    if sequence > 4 || j["decoded_bytes"].as_u64().is_none_or(|n| n > 4194304) {
        return Err(invalid());
    }
    if sequence == 0 {
        if !j["operation"].is_null()
            || !matches!(j["state"].as_str(), Some("read_admitted" | "failed"))
        {
            return Err(invalid());
        }
    } else if !matches!(
        j["operation"]["kind"].as_str(),
        Some("status" | "run_build" | "dataset")
    ) || !matches!(
        j["operation"]["state"].as_str(),
        Some("admitted" | "retained")
    ) || hash(&j["operation"]["target_hash"]).is_err()
    {
        return Err(invalid());
    }
    let errors = j["failure_codes"]
        .as_array()
        .filter(|a| {
            a.len() <= 30
                && a.iter().all(|v| {
                    v.as_str().is_some_and(|s| {
                        !s.is_empty()
                            && s.len() <= 150
                            && s.bytes()
                                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_')
                    })
                })
        })
        .ok_or_else(invalid)?;
    if j["state"] == "finding_retained"
        && (original["state"] != "finding_retained"
            || j["finding_hash"] != original["finding_hash"]
            || original["read_finding"]["schema"] != 1
            || original["read_finding"]["read_request_id"] != json!(id)
            || original["read_finding"]["finding_hash"] != j["finding_hash"])
    {
        return Err(invalid());
    }
    let local_merge = original["read_observation"]["read_request_id"] == json!(id)
        && super::read_finding::project(original, j, now)?.is_some_and(|finding| {
            crate::job_sources::access::time(&finding["observed_at"])
                .is_ok_and(|at| now - at <= chrono::Duration::hours(24))
        });
    Ok(
        json!({"request_id":parent,"read_request_id":id,"source":j["source"],"round":ordinal+1,"read_round_limit":3,"read_admissions":1,"recorded_state":j["state"],"status":if j["state"]=="finding_retained"{"finding_retained"}else if now>=expires || !errors.is_empty() || j["operation"]["state"]=="admitted"{"outcome_unknown"}else{"pending"},"run_id":j["run_id"],"provider_status":j["selected_run"]["status"],"termination_observed":j["selected_run"]["termination_observed"],"independent_termination_verified":false,"admitted_at":j["admitted_at"],"expires_at":j["expires_at"],"http_attempts":attempts,"http_responses":responses,"http_counts_are_minimum":j["operation"]["state"]=="admitted","errors":errors,"finding_retained":j["state"]=="finding_retained","local_merge_available":local_merge,"reservation":reservation,"billing_final":false,"provider_start_authorized":false,"provider_abort_authorized":false,"replay_authorized":false,"application_dispatch":false,"live_verified":false,"evidence_basis":"separate_original_acknowledged_run_read_intent"}),
    )
}
async fn originals_in(
    tx: &mut Transaction<'_, Postgres>,
    original: &Value,
    now: DateTime<Utc>,
    reservation: &Value,
) -> Result<Vec<Value>> {
    let allowed = allowance(original)?;
    let mut rows = Vec::new();
    let mut previous = None;
    for (index, id) in allowed.ids.iter().enumerate() {
        let row = load_in(tx, *id)
            .await?
            .ok_or(Failure("apify_read_prior_intent_missing"))?;
        if uuid(&row["read_request_id"])? != *id {
            return Err(invalid());
        }
        visible(&row, original, index, now, reservation)?;
        let admitted = time(&row["admitted_at"])?;
        if previous.is_some_and(|at| at >= admitted) {
            return Err(invalid());
        }
        previous = Some(admitted);
        if index + 1 == allowed.ids.len() && Some(time(&row["admitted_at"])?) != allowed.last {
            return Err(invalid());
        }
        rows.push(row);
    }
    Ok(rows)
}
pub struct Claim {
    pub(super) id: Uuid,
    pub(super) parent: Uuid,
    pub(super) journal: Value,
    pub(super) original: Value,
    pub(super) context: Option<ReadContext>,
    pub(super) invocation: Uuid,
    pub(super) expires: DateTime<Utc>,
    pub(super) monthly: (Value, String),
}
impl Claim {
    pub fn read_request_id(&self) -> Uuid {
        self.id
    }
}
pub enum Admission {
    Retained(Value),
    Original(Box<Claim>),
}
async fn clock(tx: &mut Transaction<'_, Postgres>) -> Result<DateTime<Utc>> {
    sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut **tx)
        .await
        .map_err(db)
}
async fn cooling(tx: &mut Transaction<'_, Postgres>, now: DateTime<Utc>) -> Result<bool> {
    sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM discovery_monthly_budgets WHERE provider='apify' AND cooldown_until>$1)").bind(now).fetch_one(&mut **tx).await.map_err(db)
}
pub async fn admit(
    c: &mut PgConnection,
    settings: &Settings,
    parent: Uuid,
    id: Uuid,
) -> Result<Admission> {
    if id.is_nil() || parent.is_nil() || id == parent {
        return Err(invalid());
    }
    let mut tx = admission::transaction(c).await?;
    let now = clock(&mut tx).await?;
    let original = admission::load_in(&mut tx, parent)
        .await?
        .ok_or(Failure("apify_original_intent_not_found"))?;
    let projection = admission::project_in(&mut tx, &original, parent, now).await?;
    let allowed = allowance(&original)?;
    let prior = originals_in(&mut tx, &original, now, &projection["reservation"]).await?;
    if let Some(saved) = load_in(&mut tx, id).await? {
        let ordinal = allowed
            .ids
            .iter()
            .position(|v| *v == id)
            .ok_or(Failure("apify_read_request_conflict"))?;
        let out = visible(&saved, &original, ordinal, now, &projection["reservation"])?;
        tx.commit()
            .await
            .map_err(|_| Failure("apify_read_commit_outcome_unknown"))?;
        return Ok(Admission::Retained(out));
    }
    if allowed.ids.contains(&id) {
        return Err(Failure("apify_read_prior_intent_missing"));
    }
    if original["state"] == "finding_retained" {
        let out = json!({"request_id":parent,"read_request_id":id,"recorded_state":"not_needed","finding_retained":true,"provider_calls":0,"provider_start_authorized":false,"replay_authorized":false,"reservation":projection["reservation"],"billing_final":false,"application_dispatch":false,"live_verified":false});
        tx.commit()
            .await
            .map_err(|_| Failure("apify_read_commit_outcome_unknown"))?;
        return Ok(Admission::Retained(out));
    }
    if let Some(previous) = prior.last() {
        let index = prior.len() - 1;
        if visible(previous, &original, index, now, &projection["reservation"])?["local_merge_available"]
            == true
        {
            return Err(Failure("apify_read_local_completion_required"));
        }
    }
    if allowed.ids.len() >= 3 {
        return Err(Failure("apify_read_lifetime_limit"));
    }
    if allowed.next.is_some_and(|next| next > now)
        || prior
            .last()
            .is_some_and(|row| time(&row["expires_at"]).is_ok_and(|at| at > now))
    {
        return Err(Failure("apify_read_spacing_required"));
    }
    if cooling(&mut tx, now).await? {
        return Err(Failure("apify_execution_cooling_down"));
    }
    let plan = settings.plan(
        original["source"].as_str().ok_or_else(invalid)?,
        original["effective_query"].clone(),
        original["request"]["allow_paid"] == true,
        now,
    )?;
    if original["credential_context"] != settings.credential_context()? {
        return Err(Failure("apify_read_configuration_changed"));
    }
    let context = ReadContext::from_retained(plan, &original, now)?;
    let mut next = original.clone();
    let mut ids = allowed.ids;
    ids.push(id);
    next["read_recovery"] = json!({"schema":1,"requests":ids,"last_admitted_at":now.to_rfc3339(),"next_allowed_at":(now+chrono::Duration::minutes(5)).to_rfc3339()});
    let monthly = budget::monthly_snapshot_in(&mut tx, &original["reservation"]).await?;
    let invocation = Uuid::new_v4();
    let expires = now + chrono::Duration::seconds(45);
    let journal = json!({"schema":1,"request_id":parent,"read_request_id":id,"round":ids.len(),"read_admissions":1,"source":original["source"],"scope_hash":original["scope_hash"],"configuration_hash":original["configuration_hash"],"credential_context":original["credential_context"],"run_id":context.run_id(),"original_journal_hash":crate::python_json::digest(&next),"invocation_id":invocation,"state":"read_admitted","admitted_at":now.to_rfc3339(),"expires_at":expires.to_rfc3339(),"operation":null,"http_attempts":0,"http_responses":0,"decoded_bytes":0,"failure_codes":[]});
    let saved:Option<Value>=sqlx::query_scalar("UPDATE owner_preferences SET value=$2,updated_at=clock_timestamp() WHERE key=$1 AND value=$3 RETURNING value").bind(admission::key(parent)).bind(&next).bind(&original).fetch_optional(&mut *tx).await.map_err(db)?;
    if saved.as_ref() != Some(&next) {
        return Err(ack());
    }
    let saved: Option<Value> = sqlx::query_scalar(
        "INSERT INTO owner_preferences(key,value) VALUES($1,$2) RETURNING value",
    )
    .bind(key(id))
    .bind(&journal)
    .fetch_optional(&mut *tx)
    .await
    .map_err(db)?;
    if saved.as_ref() != Some(&journal) {
        return Err(ack());
    }
    let claim = Claim {
        id,
        parent,
        journal,
        original: next,
        context: Some(context),
        invocation,
        expires,
        monthly,
    };
    assert_original_in(&mut tx, settings, &claim).await?;
    tx.commit()
        .await
        .map_err(|_| Failure("apify_read_commit_outcome_unknown"))?;
    Ok(Admission::Original(Box::new(claim)))
}
pub(super) async fn assert_original_in(
    tx: &mut Transaction<'_, Postgres>,
    settings: &Settings,
    claim: &Claim,
) -> Result<()> {
    let now = clock(tx).await?;
    verify_saved_in(
        tx,
        claim,
        &claim.journal,
        &claim.original,
        &claim.monthly,
        now,
    )
    .await?;
    let plan = settings.plan(
        claim.original["source"].as_str().ok_or_else(invalid)?,
        claim.original["effective_query"].clone(),
        true,
        now,
    )?;
    if plan.context()
        != claim.original["configuration_hash"]
            .as_str()
            .ok_or_else(invalid)?
        || claim.original["credential_context"] != settings.credential_context()?
        || now >= claim.expires
        || cooling(tx, now).await?
    {
        return Err(ack());
    }
    Ok(())
}
/// Response retention may finish after the dispatch deadline or install a cooldown; it cannot dispatch.
pub(super) async fn verify_saved_in(
    tx: &mut Transaction<'_, Postgres>,
    claim: &Claim,
    read: &Value,
    original: &Value,
    monthly: &(Value, String),
    now: DateTime<Utc>,
) -> Result<()> {
    if admission::load_in(tx, claim.parent).await?.as_ref() != Some(original)
        || load_in(tx, claim.id).await?.as_ref() != Some(read)
        || budget::monthly_snapshot_in(tx, &original["reservation"]).await? != *monthly
    {
        return Err(ack());
    }
    let projected = admission::project_in(tx, original, claim.parent, now).await?;
    originals_in(tx, original, now, &projected["reservation"]).await?;
    Ok(())
}
pub async fn read(c: &mut PgConnection, parent: Uuid, id: Uuid) -> Result<Value> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let now = clock(&mut tx).await?;
    let out = read_in(&mut tx, parent, id, now).await?;
    tx.commit().await.map_err(db)?;
    Ok(out)
}
pub(super) async fn read_in(
    tx: &mut Transaction<'_, Postgres>,
    parent: Uuid,
    id: Uuid,
    now: DateTime<Utc>,
) -> Result<Value> {
    let original = admission::load_in(tx, parent)
        .await?
        .ok_or(Failure("apify_original_intent_not_found"))?;
    let projection = admission::project_in(tx, &original, parent, now).await?;
    let allowed = allowance(&original)?;
    let ordinal = allowed
        .ids
        .iter()
        .position(|v| *v == id)
        .ok_or(Failure("apify_read_intent_not_found"))?;
    let rows = originals_in(tx, &original, now, &projection["reservation"]).await?;
    let out = visible(
        &rows[ordinal],
        &original,
        ordinal,
        now,
        &projection["reservation"],
    )?;
    Ok(out)
}
