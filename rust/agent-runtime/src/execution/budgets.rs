//! Durable lifetime/hour/day admissions in the caller's owner transaction. Never refund.
use super::{contracts, storage::*};
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;

pub(crate) async fn reserve_in(
    tx: &mut Transaction<'_, Postgres>,
    work: &Value,
    policy: &Value,
    now: DateTime<Utc>,
) -> Result<()> {
    work["id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    let platform = work["platform"].as_str().ok_or_else(invalid)?;
    let setting = &policy["platforms"][platform];
    let totals: Value =
        sqlx::query_scalar(include_str!("../../sql/execution_admission_totals.sql"))
            .bind(platform)
            .bind(now)
            .fetch_one(&mut **tx)
            .await
            .map_err(db)?;
    if totals["invalid"] != false {
        return Err(Failure("admission_history_requires_reconciliation"));
    }
    let count = |key: &str| totals[key].as_i64().filter(|n| *n >= 0).ok_or_else(invalid);
    if setting["mode"] == "SUPERVISED"
        && work["operation"] == "apply"
        && count("lifetime_apply")?
            >= setting["supervised_submission_cap"]
                .as_i64()
                .ok_or_else(invalid)?
    {
        return Err(Failure("supervised_application_allowance_exhausted"));
    }
    let day = contracts::day_bucket(now, policy["day_timezone"].as_str().ok_or_else(invalid)?)?;
    let key = format!("apply_budget:{platform}:{day}");
    let mut budget = get(tx, &key).await?.unwrap_or(json!({"reservations":[]}));
    let reservations = budget["reservations"]
        .as_array()
        .ok_or(Failure("admission_history_requires_reconciliation"))?;
    if reservations
        .iter()
        .any(|r| r.as_str().and_then(|s| s.parse::<Uuid>().ok()).is_none())
    {
        return Err(Failure("admission_history_requires_reconciliation"));
    }
    if reservations.contains(&work["id"]) {
        return Ok(());
    }
    let mut cap = contracts::limits(policy, platform)?["daily_cap"]
        .as_i64()
        .ok_or_else(invalid)?;
    if setting["mode"] == "SUPERVISED" {
        cap = cap.min(
            setting["supervised_submission_cap"]
                .as_i64()
                .ok_or_else(invalid)?,
        );
    }
    if reservations.len() >= usize::try_from(cap).map_err(|_| invalid())? {
        return Err(Failure("daily_application_cap_reached"));
    }
    if count("hourly_work")?
        >= setting["hourly_submission_cap"]
            .as_i64()
            .ok_or_else(invalid)?
    {
        return Err(Failure("hourly_application_cap_reached"));
    }
    let mut reservations = reservations.clone();
    reservations.push(work["id"].clone());
    budget["reservations"] = json!(reservations);
    put(tx, &key, &budget).await
}
