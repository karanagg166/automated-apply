//! Legacy preparation-only intents and crash recovery. No native/browser/network dispatch.
use super::{events, legacy_policy, storage::*};
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;
pub const TERMINAL: &[&str] = &[
    "REJECTED",
    "FAILED_FINAL",
    "SUBMITTED_CONFIRMED",
    "SUBMISSION_UNKNOWN",
];
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Claim {
    pub id: Uuid,
    pub fence: i64,
}
pub(crate) async fn save_in(tx: &mut Transaction<'_, Postgres>, value: &Value) -> Result<()> {
    let id = value["id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    put(tx, &format!("exec:{id}"), value).await
}
pub(crate) async fn move_in(
    tx: &mut Transaction<'_, Postgres>,
    value: &mut Value,
    state: &str,
    reason: Option<&str>,
    now: DateTime<Utc>,
) -> Result<()> {
    if value["question_only"] == true
        && matches!(state, "FILLING" | "SUBMITTING" | "SUBMITTED_CONFIRMED")
    {
        return Err(Failure("question_context_cannot_execute"));
    }
    if value["platform"] == "naukri" && matches!(state, "SUBMITTING" | "SUBMITTED_CONFIRMED") {
        return Err(Failure("naukri_submission_capability_not_verified"));
    }
    let old = value["state"].as_str().ok_or_else(invalid)?.to_owned();
    if !matches!(
        (old.as_str(), state),
        ("DISCOVERED", "MATCHED")
            | ("MATCHED", "ELIGIBLE" | "REJECTED" | "NEEDS_INPUT")
            | ("ELIGIBLE", "PREPARING")
            | ("PREPARING", "FILLING" | "NEEDS_INPUT" | "READY_FOR_REVIEW")
            | ("FILLING", "NEEDS_INPUT" | "READY_FOR_REVIEW")
            | ("NEEDS_INPUT", "PREPARING")
            | ("READY_FOR_REVIEW", "FILLING" | "SUBMITTING" | "NEEDS_INPUT")
            | ("SUBMITTING", "SUBMITTED_CONFIRMED" | "SUBMISSION_UNKNOWN")
            | ("FAILED_RETRYABLE", "PREPARING" | "FAILED_FINAL")
    ) {
        return Err(Failure("invalid_execution_transition"));
    }
    let mut history = value["history"].as_array().ok_or_else(invalid)?.clone();
    history.push(json!({"from":old,"to":state,"reason":reason}));
    value["history"] = json!(history);
    value["state"] = json!(state);
    value["revision"] = json!(next(value)?);
    value["diagnostic"] = json!(reason);
    save_in(tx, value).await?;
    events::legacy(tx, value, "state_changed", now).await
}
pub(crate) async fn fenced_in(
    tx: &mut Transaction<'_, Postgres>,
    claim: Claim,
    now: DateTime<Utc>,
) -> Result<Value> {
    let value = get(tx, &format!("exec:{}", claim.id))
        .await?
        .ok_or(Failure("execution_not_found"))?;
    if value["id"] != claim.id.to_string() {
        return Err(invalid());
    }
    if value.get("automation_revision").is_some() {
        let automation = legacy_policy::record(tx).await?;
        if automation["state"] != "RUNNING"
            || automation["revision"] != value["automation_revision"]
        {
            return Err(Failure("automation_authority_lost"));
        }
    }
    if value["fence"] != claim.fence
        || value["lease_until"].is_null()
        || timestamp(&value["lease_until"])? <= now
        || TERMINAL.contains(&value["state"].as_str().ok_or_else(invalid)?)
        || value["state"] == "PAUSED"
    {
        return Err(Failure("execution_lease_lost"));
    }
    Ok(value)
}
pub async fn claim(c: &mut PgConnection) -> Result<Option<Claim>> {
    let hint:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM owner_preferences WHERE starts_with(key,'exec:') AND value->'question_only' IS DISTINCT FROM 'true'::jsonb AND value->>'state' NOT IN ('REJECTED','FAILED_FINAL','SUBMITTED_CONFIRMED','SUBMISSION_UNKNOWN','PAUSED','NEEDS_INPUT','READY_FOR_REVIEW') AND NOT EXISTS(SELECT 1 FROM owner_preferences WHERE key='exec_config:naukri' AND value->>'mode'='OFF') AND (value->>'lease_until' IS NULL OR CASE WHEN pg_input_is_valid(value->>'lease_until','timestamp with time zone') THEN (value->>'lease_until')::timestamptz<=clock_timestamp() ELSE true END) AND (value->>'state' IN ('FILLING','SUBMITTING') OR CASE WHEN pg_input_is_valid(value->>'available_at','timestamp with time zone') THEN (value->>'available_at')::timestamptz<=clock_timestamp() ELSE true END))").fetch_one(&mut *c).await.map_err(db)?;
    if !hint {
        return Ok(None);
    }
    let mut tx = c.begin().await.map_err(db)?;
    let result=async{
        sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE").execute(&mut *tx).await.map_err(db)?;lock(&mut tx).await?;
        if legacy_policy::configuration(&mut tx).await?["mode"]=="OFF"{return Ok(None);}
        let now=now(&mut tx).await?;let automation=legacy_policy::record(&mut tx).await?;
        let rows:Vec<Value>=sqlx::query_scalar("SELECT value FROM owner_preferences WHERE starts_with(key,'exec:') AND value->'question_only' IS DISTINCT FROM 'true'::jsonb AND value->>'state' NOT IN ('REJECTED','FAILED_FINAL','SUBMITTED_CONFIRMED','SUBMISSION_UNKNOWN','PAUSED','NEEDS_INPUT','READY_FOR_REVIEW') ORDER BY created_at,key LIMIT 10001").fetch_all(&mut *tx).await.map_err(db)?;
        if rows.len()>10000{return Err(Failure("execution_active_inventory_limit"));}
        for mut value in rows{
            if value.get("automation_revision").is_some()&&(automation["state"]!="RUNNING"||automation["revision"]!=value["automation_revision"]){continue;}
            if !value["lease_until"].is_null()&&timestamp(&value["lease_until"])? > now{continue;}
            if value["state"]=="FILLING"{move_in(&mut tx,&mut value,"NEEDS_INPUT",Some("fill_outcome_unknown_reinspect_manually"),now).await?;value["lease_until"]=Value::Null;save_in(&mut tx,&value).await?;continue;}
            if value["state"]=="SUBMITTING"{move_in(&mut tx,&mut value,"SUBMISSION_UNKNOWN",Some("dispatch_outcome_unknown_no_replay"),now).await?;continue;}
            if timestamp(&value["available_at"])? > now{continue;}
            let attempts=value["attempts"].as_i64().filter(|n|*n>=0).ok_or_else(invalid)?;
            if attempts>=3{value["state"]=json!("FAILED_FINAL");value["diagnostic"]=json!("retry_limit");value["revision"]=json!(next(&value)?);save_in(&mut tx,&value).await?;events::legacy(&mut tx,&value,"retry_limit",now).await?;continue;}
            let fence=value["fence"].as_i64().filter(|n|*n>=0).and_then(|n|n.checked_add(1)).ok_or_else(invalid)?;
            let id=value["id"].as_str().and_then(|s|s.parse::<Uuid>().ok()).ok_or_else(invalid)?;value["fence"]=json!(fence);value["attempts"]=json!(attempts+1);value["lease_until"]=json!(stamp(now+chrono::Duration::seconds(90)));value["heartbeat_at"]=json!(stamp(now));save_in(&mut tx,&value).await?;return Ok(Some(Claim{id,fence}));
        }Ok(None)
    }.await;
    match result {
        Ok(value) => {
            tx.commit()
                .await
                .map_err(|_| Failure("execution_commit_outcome_unknown"))?;
            Ok(value)
        }
        Err(error) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            Err(error)
        }
    }
}
pub(crate) async fn failed(c: &mut PgConnection, claim: Claim) -> Result<()> {
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
        sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            .execute(&mut *tx)
            .await
            .map_err(db)?;
        lock(&mut tx).await?;
        let now = now(&mut tx).await?;
        let mut value = match fenced_in(&mut tx, claim, now).await {
            Ok(value) => value,
            Err(Failure("execution_lease_lost" | "automation_authority_lost")) => return Ok(()),
            Err(error) => return Err(error),
        };
        value["state"] = json!("FAILED_RETRYABLE");
        value["revision"] = json!(next(&value)?);
        value["diagnostic"] = json!("preparation_failed");
        value["lease_until"] = Value::Null;
        value["available_at"] = json!(stamp(now + chrono::Duration::seconds(60)));
        save_in(&mut tx, &value).await?;
        events::legacy(&mut tx, &value, "preparation_failed", now).await
    }
    .await;
    match result {
        Ok(()) => tx
            .commit()
            .await
            .map_err(|_| Failure("execution_commit_outcome_unknown")),
        Err(error) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            Err(error)
        }
    }
}
