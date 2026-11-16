//! Durable control fences; uncertain operations retain admissions and cannot become resumable.
use super::{events, filters, storage::*};
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};

pub fn work(value: &Value, reason: &str) -> Result<Option<Value>> {
    let stage = value["stage"].as_str().ok_or_else(invalid)?;
    let status = value["status"].as_str().ok_or_else(invalid)?;
    if filters::TERMINAL.contains(&stage) || status == "unknown" {
        return Ok(None);
    }
    let mut next_value = value.clone();
    let uncertain = status == "executing"
        && value["operation"]
            .as_str()
            .is_some_and(|s| filters::WRITES.contains(&s));
    if stage != "PAUSED" {
        next_value["paused_context"] = json!({"stage":value["stage"],"status":value["status"],"operation":value["operation"],"reason":value["reason"]});
    }
    next_value["stage"] = json!(if uncertain {
        "SUBMISSION_UNKNOWN"
    } else {
        "PAUSED"
    });
    next_value["status"] = json!(if uncertain { "unknown" } else { "waiting" });
    next_value["reason"] = json!(reason);
    next_value["revision"] = json!(next(value)?);
    next_value["lease_token"] = Value::Null;
    next_value["lease_until"] = Value::Null;
    Ok(Some(next_value))
}
pub fn resume(value: &Value) -> Result<Option<Value>> {
    if value["status"] == "unknown"
        || value["stage"] != "PAUSED"
        || !matches!(
            value["reason"].as_str(),
            Some("owner_pause" | "global_stop" | "queue_policy_changed")
        )
    {
        return Ok(None);
    }
    let previous = &value["paused_context"];
    let waiting = previous["status"] == "waiting";
    let mut next_value = value.clone();
    next_value["stage"] = previous
        .get("stage")
        .cloned()
        .unwrap_or(json!("DISCOVERED"));
    next_value["status"] = json!(if waiting { "waiting" } else { "queued" });
    next_value["operation"] = previous
        .get("operation")
        .cloned()
        .unwrap_or(json!("inspect_job"));
    next_value["reason"] = previous["reason"].clone();
    next_value["revision"] = json!(next(value)?);
    if !waiting
        && next_value["form_pending"] == true
        && matches!(
            next_value["operation"].as_str(),
            Some(
                "prepare_questionnaire"
                    | "inspect_questionnaire"
                    | "refresh_questionnaire_profile"
                    | "refresh_questionnaire_job"
                    | "answer_questionnaire"
            )
        )
    {
        next_value["operation"] = json!("refresh_questionnaire_profile");
        next_value["stage"] = json!("QUESTIONS");
    } else if !waiting
        && next_value["operation"]
            .as_str()
            .is_some_and(|s| filters::WRITES.contains(&s))
    {
        next_value["operation"] = json!(if next_value["account_sha256"]
            .as_str()
            .is_some_and(|s| !s.is_empty())
            && next_value["admitted_actions"] == json!([])
        {
            "inspect_profile"
        } else {
            "inspect_application"
        });
        next_value["stage"] = json!("VERIFYING");
    }
    Ok(Some(next_value))
}
pub(super) async fn queue(
    tx: &mut Transaction<'_, Postgres>,
    reason: &str,
    now: DateTime<Utc>,
) -> Result<()> {
    if let Some(mut sync) = get(tx, "apply_profile_sync:naukri").await? {
        let revision = next(&sync)?;
        sync.as_object_mut()
            .ok_or_else(invalid)?
            .remove("approved_summary");
        sync["status"] = json!("idle");
        sync["lease_token"] = Value::Null;
        sync["lease_until"] = Value::Null;
        sync["revision"] = json!(revision);
        sync["last_error"] = json!(reason);
        put(tx, "apply_profile_sync:naukri", &sync).await?;
    }
    if let Some(mut search) = get(tx, "apply_search:naukri").await? {
        let revision = next(&search)?;
        search["status"] = json!("idle");
        search["lease_token"] = Value::Null;
        search["lease_until"] = Value::Null;
        search["next_at"] = Value::Null;
        search["revision"] = json!(revision);
        search["last_error"] = json!(reason);
        put(tx, "apply_search:naukri", &search).await?;
    }
    let rows:Vec<(String,Value)>=sqlx::query_as("SELECT key,value FROM owner_preferences WHERE starts_with(key,'apply_work:') AND value->>'stage' NOT IN ('SUBMITTED_RECORDED','SUBMITTED_CONFIRMED','FAILED_FINAL','SKIPPED') AND (value->>'stage'!='NEEDS_INPUT' OR value->>'status'!='waiting' OR value->>'packet_id' IS NOT NULL OR value->>'lease_until' IS NOT NULL OR value->>'form_pending'='true' OR coalesce(value->>'admitted_actions','unknown')!='[]') ORDER BY created_at,key LIMIT 10001").fetch_all(&mut **tx).await.map_err(db)?;
    if rows.len() > 10000 {
        return Err(Failure("execution_active_inventory_limit"));
    }
    for (key, value) in rows {
        if let Some(fenced) = work(&value, reason)? {
            put(tx, &key, &fenced).await?;
            events::queue(tx, &fenced, "fenced", now).await?;
        }
    }
    Ok(())
}
pub(super) async fn resume_queue(
    tx: &mut Transaction<'_, Postgres>,
    now: DateTime<Utc>,
) -> Result<()> {
    let rows:Vec<(String,Value)>=sqlx::query_as("SELECT key,value FROM owner_preferences WHERE starts_with(key,'apply_work:') AND value->>'stage'='PAUSED' ORDER BY created_at,key LIMIT 10001").fetch_all(&mut **tx).await.map_err(db)?;
    if rows.len() > 10000 {
        return Err(Failure("execution_active_inventory_limit"));
    }
    for (key, value) in rows {
        if let Some(resumed) = resume(&value)? {
            put(tx, &key, &resumed).await?;
            events::queue(tx, &resumed, "resumed_for_fresh_inspection", now).await?;
        }
    }
    Ok(())
}
pub(super) async fn legacy(
    tx: &mut Transaction<'_, Postgres>,
    reason: &str,
    now: DateTime<Utc>,
) -> Result<()> {
    let rows:Vec<(String,Value)>=sqlx::query_as("SELECT o.key,o.value FROM owner_preferences o WHERE starts_with(o.key,'exec:') AND (o.value->>'platform'='naukri' OR EXISTS(SELECT 1 FROM jobs j WHERE j.id::text=o.value->>'job_id' AND j.source_platform='naukri')) AND o.value->>'state' NOT IN ('REJECTED','FAILED_FINAL','SUBMITTED_CONFIRMED','SUBMISSION_UNKNOWN','PAUSED') ORDER BY o.created_at,o.key LIMIT 10001").fetch_all(&mut **tx).await.map_err(db)?;
    if rows.len() > 10000 {
        return Err(Failure("execution_active_inventory_limit"));
    }
    for (key, mut value) in rows {
        let stage = value["state"].clone();
        value["state"] = json!(if stage == "SUBMITTING" {
            "SUBMISSION_UNKNOWN"
        } else {
            "PAUSED"
        });
        value["paused_state"] = stage;
        value["cancelled"] = json!(false);
        value["revision"] = json!(next(&value)?);
        value["fence"] = json!(
            value["fence"]
                .as_i64()
                .filter(|n| *n >= 0)
                .and_then(|n| n.checked_add(1))
                .ok_or_else(invalid)?
        );
        value["lease_until"] = Value::Null;
        put(tx, &key, &value).await?;
        events::legacy(tx, &value, "owner_pause", now).await?;
    }
    crate::browser_profiles::fence_naukri(tx, reason, now).await
}
