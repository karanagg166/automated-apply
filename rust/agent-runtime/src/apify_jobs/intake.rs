//! Atomic local SQL over an original retained paid finding. This module has no transport client.
use super::{admission, budget, settings::Settings};
use crate::{Failure, Result, job_sources::intake as shared};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;
fn db(_: sqlx::Error) -> Failure {
    Failure("apify_intake_database_error")
}
fn invalid() -> Failure {
    Failure("invalid_apify_intake_receipt")
}
fn ack() -> Failure {
    Failure("apify_intake_write_ack_failed")
}
fn key(id: Uuid) -> String {
    format!("apify_intake:{}", id.simple())
}
async fn clock(tx: &mut Transaction<'_, Postgres>) -> Result<DateTime<Utc>> {
    sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut **tx)
        .await
        .map_err(db)
}
async fn saved_in(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Option<Value>> {
    let v: Option<Option<Value>> = sqlx::query_scalar("SELECT CASE WHEN octet_length(value::text)<=262144 THEN value ELSE NULL END FROM owner_preferences WHERE key=$1")
        .bind(key(id)).fetch_optional(&mut **tx).await.map_err(db)?;
    match v {
        Some(Some(v)) => Ok(Some(v)),
        Some(None) => Err(Failure("apify_intake_receipt_limit")),
        None => Ok(None),
    }
}
/// Validates the full original paid journal/reservation before exposing selected normalized claims.
async fn finding_in(
    tx: &mut Transaction<'_, Postgres>,
    journal: &Value,
    id: Uuid,
    now: DateTime<Utc>,
) -> Result<Value> {
    let selected = admission::project_in(tx, journal, id, now).await?;
    if selected["finding_retained"] != true || journal["reservation"]["state"] != "run_attached" {
        return Err(Failure("apify_intake_finding_missing"));
    }
    // Project the same closed finding used by saved owner reads; no private journal extras.
    super::finding::project(
        &journal["finding"],
        journal["source"].as_str().ok_or_else(invalid)?,
        journal["effective_query"]["limit"]
            .as_u64()
            .ok_or_else(invalid)?,
        now,
    )
}
pub(super) async fn context_in(
    tx: &mut Transaction<'_, Postgres>,
    journal: &Value,
    settings: &Settings,
    now: DateTime<Utc>,
) -> Result<()> {
    let at = crate::job_sources::access::time(&journal["finding"]["observed_at"])?;
    if at > now || now - at > chrono::Duration::hours(24) {
        return Err(Failure("apify_intake_finding_expired"));
    }
    let profile =
        crate::startup_catalog::detail::profile_in(tx, journal["request"]["use_profile"] == true)
            .await?;
    if crate::job_sources::scope::profile_pin(profile.as_ref())? != journal["profile_pin"] {
        return Err(Failure("apify_intake_profile_changed"));
    }
    let plan = settings.plan(
        journal["source"].as_str().ok_or_else(invalid)?,
        journal["effective_query"].clone(),
        journal["request"]["allow_paid"] == true,
        now,
    )?;
    if journal["configuration_hash"] != plan.context()
        || journal["credential_context"] != settings.credential_context()?
    {
        return Err(Failure("apify_intake_configuration_changed"));
    }
    Ok(())
}
fn retained(saved: &Value, journal: &Value, finding: &Value, id: Uuid) -> Result<Value> {
    if saved["schema"] != 1
        || saved["request_id"] != json!(id)
        || saved["scope_hash"] != journal["scope_hash"]
        || saved["configuration_hash"] != journal["configuration_hash"]
        || saved["finding_hash"] != journal["finding_hash"]
        || saved["run_hash"] != journal["selected_run_hash"]
        || saved["reservation_hash"] != crate::python_json::digest(&journal["reservation"])
        || saved["receipt_hash"] != crate::python_json::digest(&saved["receipt"])
        || saved["billing_final"] != false
    {
        return Err(Failure("apify_intake_receipt_conflict"));
    }
    let mut receipt = shared::receipt(&saved["receipt"], finding, id, &journal["source"])?;
    receipt["billing_final"] = json!(false);
    receipt["budget_accounting"] = json!("full_cap_retained");
    receipt["provider_run_id"] = journal["selected_run"]["id"].clone();
    Ok(receipt)
}
/// A receipt can be recovered without any current token, configuration, profile or provider call.
pub(super) async fn read_in(
    tx: &mut Transaction<'_, Postgres>,
    journal: &Value,
    id: Uuid,
    now: DateTime<Utc>,
) -> Result<Option<Value>> {
    let Some(saved) = saved_in(tx, id).await? else {
        return Ok(None);
    };
    let finding = finding_in(tx, journal, id, now).await?;
    Ok(Some(retained(&saved, journal, &finding, id)?))
}
pub(super) struct Completion {
    pub(super) receipt: Value,
    saved: Value,
    batch: Option<shared::Batch>,
    monthly: (Value, String),
}
impl Completion {
    pub(super) async fn verify_in(
        &self,
        tx: &mut Transaction<'_, Postgres>,
        journal: &Value,
        settings: &Settings,
        id: Uuid,
        now: DateTime<Utc>,
    ) -> Result<()> {
        if admission::load_in(tx, id).await?.as_ref() != Some(journal)
            || saved_in(tx, id).await?.as_ref() != Some(&self.saved)
            || budget::monthly_snapshot_in(tx, &journal["reservation"]).await? != self.monthly
        {
            return Err(ack());
        }
        let finding = finding_in(tx, journal, id, now).await?;
        if retained(&self.saved, journal, &finding, id)? != self.receipt {
            return Err(ack());
        }
        if let Some(batch) = &self.batch {
            batch.verify(tx).await?;
            context_in(tx, journal, settings, now).await?;
        }
        Ok(())
    }
}
pub(super) async fn complete_in(
    tx: &mut Transaction<'_, Postgres>,
    journal: &Value,
    settings: &Settings,
    id: Uuid,
    now: DateTime<Utc>,
) -> Result<Completion> {
    let finding = finding_in(tx, journal, id, now).await?;
    let monthly = budget::monthly_snapshot_in(tx, &journal["reservation"]).await?;
    if let Some(saved) = saved_in(tx, id).await? {
        return Ok(Completion {
            receipt: retained(&saved, journal, &finding, id)?,
            saved,
            batch: None,
            monthly,
        });
    }
    context_in(tx, journal, settings, now).await?;
    sqlx::query("SELECT pg_advisory_xact_lock(240204)")
        .execute(&mut **tx)
        .await
        .map_err(db)?;
    let batch = shared::batch_in(
        tx,
        &finding,
        &journal["request"]["query"],
        &journal["effective_query"],
        id,
        now,
    )
    .await?;
    let expected = json!({"schema":1,"request_id":id,"scope_hash":journal["scope_hash"],"configuration_hash":journal["configuration_hash"],"finding_hash":journal["finding_hash"],"run_hash":journal["selected_run_hash"],"reservation_hash":crate::python_json::digest(&journal["reservation"]),"receipt":batch.receipt,"receipt_hash":crate::python_json::digest(&batch.receipt),"billing_final":false});
    let saved: Option<Value> = sqlx::query_scalar(
        "INSERT INTO owner_preferences(key,value) VALUES($1,$2) RETURNING value",
    )
    .bind(key(id))
    .bind(&expected)
    .fetch_optional(&mut **tx)
    .await
    .map_err(db)?;
    if saved.as_ref() != Some(&expected) {
        return Err(ack());
    }
    let completion = Completion {
        receipt: retained(&expected, journal, &finding, id)?,
        saved: expected,
        batch: Some(batch),
        monthly,
    };
    let end = clock(tx).await?;
    completion.verify_in(tx, journal, settings, id, end).await?;
    Ok(completion)
}
/// Only local SQL. A retained remote finding survives any rollback here; a replay never starts an Actor.
pub async fn ingest_retained(c: &mut PgConnection, settings: &Settings, id: Uuid) -> Result<Value> {
    let mut tx = admission::transaction(c).await?;
    let journal = admission::load_in(&mut tx, id)
        .await?
        .ok_or(Failure("apify_original_intent_not_found"))?;
    let now = clock(&mut tx).await?;
    let completion = complete_in(&mut tx, &journal, settings, id, now).await?;
    let end = clock(&mut tx).await?;
    completion
        .verify_in(&mut tx, &journal, settings, id, end)
        .await?;
    tx.commit()
        .await
        .map_err(|_| Failure("apify_intake_commit_outcome_unknown"))?;
    Ok(completion.receipt)
}
/// Snapshot read; missing local receipt is distinct from missing original paid intent.
pub async fn read(c: &mut PgConnection, id: Uuid) -> Result<Option<Value>> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let journal = admission::load_in(&mut tx, id)
        .await?
        .ok_or(Failure("apify_original_intent_not_found"))?;
    let now = clock(&mut tx).await?;
    admission::project_in(&mut tx, &journal, id, now).await?;
    let out = read_in(&mut tx, &journal, id, now).await?;
    tx.commit().await.map_err(db)?;
    Ok(out)
}
