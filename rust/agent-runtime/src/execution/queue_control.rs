//! Owner policy/control under the same durable lock as claims. No browser or provider IO.
use super::{
    automatic,
    contracts::{self, Kind},
    fences, queue_status,
    storage::*,
    supervised_listing,
};
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;

pub(super) async fn configuration(tx: &mut Transaction<'_, Postgres>) -> Result<Value> {
    queue_status::configuration(get(tx, "application_queue_policy").await?.as_ref())
}
fn filter_snapshot(policy: &Value) -> Result<Value> {
    let mut limits = contracts::limits(policy, "naukri")?;
    limits
        .as_object_mut()
        .ok_or_else(invalid)?
        .remove("daily_cap");
    let setting = &policy["platforms"]["naukri"];
    Ok(
        json!({"limits":limits,"enabled":setting["enabled"],"sources":setting["sources"],"skill_match_mode":setting["skill_match_mode"],"preferences_mode":setting["preferences_mode"],"preferences":setting["preferences"]}),
    )
}
pub(super) async fn configure(
    tx: &mut Transaction<'_, Postgres>,
    data: Value,
    now: DateTime<Utc>,
) -> Result<Value> {
    let mut current = configuration(tx).await?;
    if current["revision"] != data["expected_revision"] {
        return Err(Failure("queue_policy_revision_conflict"));
    }
    automatic::require_policy(tx, &data["policy"], now).await?;
    let before = contracts::limits(&current["policy"], "naukri")?;
    let after = contracts::limits(&data["policy"], "naukri")?;
    let filters_changed = filter_snapshot(&current["policy"])? != filter_snapshot(&data["policy"])?;
    fences::queue(tx, "queue_policy_changed", now).await?;
    current["revision"] = json!(next(&current)?);
    if current["state"] == "RUNNING" {
        current["state"] = json!("PAUSED");
    }
    supervised_listing::clear(&mut current)?;
    current["policy"] = data["policy"].clone();
    put(tx, "application_queue_policy", &current).await?;
    if before["unknown_applicants"] == "needs_review"
        && !before["applicant_limit"].is_null()
        && (after["unknown_applicants"] != "needs_review"
            || after["applicant_limit"] != before["applicant_limit"])
    {
        sqlx::query("UPDATE owner_notifications SET kind='automation_policy_resolved',title='Naukri applicant-count policy updated',body='Your saved applicant-count rule changed. Check the current Naukri queue policy; other filters and submission prerequisites remain enforced.' WHERE dedup_key=$1 AND kind='automation_policy_question'").bind(format!("naukri_applicant_question:{}",before["applicant_limit"])).execute(&mut **tx).await.map_err(db)?;
        let stale:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM owner_notifications WHERE dedup_key=$1 AND kind='automation_policy_question')").bind(format!("naukri_applicant_question:{}",before["applicant_limit"])).fetch_one(&mut **tx).await.map_err(db)?;
        if stale {
            return Err(Failure("execution_write_ack_failed"));
        }
    }
    if filters_changed {
        put(tx,"apply_filter_recheck",&json!({"id":Uuid::new_v4(),"status":"pending","cursor":null,"reason":"owner_policy_filters_changed","requested_at":stamp(now),"checked":0,"fresh_reads":0})).await?;
    }
    Ok(current)
}
pub(super) async fn control(
    tx: &mut Transaction<'_, Postgres>,
    data: Value,
    now: DateTime<Utc>,
) -> Result<Value> {
    let mut current = configuration(tx).await?;
    if current["revision"] != data["expected_revision"] {
        return Err(Failure("queue_policy_revision_conflict"));
    }
    let action = data["action"]
        .as_str()
        .ok_or(Failure("invalid_execution_contract"))?;
    let state = if action == "start" {
        if supervised_listing::scoped(&current) {
            return Err(Failure("stop_supervised_listing_before_start"));
        }
        require_start(tx, &current, now).await?;
        fences::resume_queue(tx, now).await?;
        "RUNNING"
    } else {
        let reason = if action == "stop" {
            "global_stop"
        } else {
            "owner_pause"
        };
        fences::queue(tx, reason, now).await?;
        fences::legacy(tx, reason, now).await?;
        let state = if action == "stop" {
            "STOPPED"
        } else {
            "PAUSED"
        };
        if let Some(mut legacy) = get(tx, "naukri_automation").await?
            && revision(&legacy)? > 0
        {
            legacy["state"] = json!(state);
            legacy["revision"] = json!(next(&legacy)?);
            put(tx, "naukri_automation", &legacy).await?;
        }
        state
    };
    supervised_listing::clear(&mut current)?;
    current["state"] = json!(state);
    current["revision"] = json!(next(&current)?);
    put(tx, "application_queue_policy", &current).await?;
    Ok(current)
}

pub(super) async fn require_start(
    tx: &mut Transaction<'_, Postgres>,
    current: &Value,
    now: DateTime<Utc>,
) -> Result<()> {
    let config = contracts::normalize(
        Kind::Configuration,
        get(tx, "exec_config:naukri").await?.unwrap_or(json!({})),
    )
    .map_err(|_| invalid())?;
    if config["mode"] == "OFF" {
        return Err(Failure("execution_mode_off"));
    }
    if !current["policy"]["platforms"]
        .as_object()
        .ok_or_else(invalid)?
        .values()
        .any(|p| p["enabled"] == true)
    {
        return Err(Failure("enabled_platform_required"));
    }
    automatic::require_policy(tx, &current["policy"], now).await
}
