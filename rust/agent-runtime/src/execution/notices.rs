//! Transactional owner inbox/legacy Telegram outbox only. No transport or recipient argument.
use super::{queue_control, storage::*};
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;
pub(super) async fn save(
    tx: &mut Transaction<'_, Postgres>,
    work: &Value,
    unknown: bool,
    telegram_available: bool,
) -> Result<Vec<&'static str>> {
    let config = queue_control::configuration(tx).await?;
    let policy = &config["policy"];
    if policy["notify_submitted"] != true {
        return Ok(vec![]);
    }
    let prefs = crate::notification_preferences::load_in(tx).await?;
    let id = work["id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    let packet = work["packet_id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    let label = |key: &str| work[key].as_str().ok_or_else(invalid);
    let role = label("title")?;
    let employer = label("company")?;
    let key = format!(
        "naukri-{}:{id}",
        if unknown { "unknown" } else { "confirmed" }
    );
    let title = if unknown {
        "Naukri submission remains unconfirmed"
    } else {
        "Naukri application confirmed"
    };
    let body = if unknown {
        format!(
            "{role} at {employer}: bounded account/history checks did not verify a sent receipt. This attempt is quarantined and Apply will not be repeated."
        )
    } else {
        format!("{role} at {employer}: Application Sent persisted after a separate history reload.")
    };
    let mut channels = vec![];
    if prefs["paused"] != true && prefs["in_app"] == true {
        let id = Uuid::new_v4();
        let inserted:Option<Uuid>=sqlx::query_scalar("INSERT INTO owner_notifications(id,dedup_key,kind,title,body,href) VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(dedup_key) DO NOTHING RETURNING id").bind(id).bind(&key).bind(if unknown{"application_submission_unknown"}else{"application_submitted"}).bind(title).bind(&body).bind(format!("/applications/{packet}")).fetch_optional(&mut **tx).await.map_err(db)?;
        if inserted.is_none() {
            let exists: bool = sqlx::query_scalar(
                "SELECT EXISTS(SELECT 1 FROM owner_notifications WHERE dedup_key=$1)",
            )
            .bind(&key)
            .fetch_one(&mut **tx)
            .await
            .map_err(db)?;
            if !exists {
                return Err(Failure("execution_write_ack_failed"));
            }
        } else if inserted != Some(id) {
            return Err(Failure("execution_write_ack_failed"));
        }
        channels.push("in_app");
    }
    // Preserve the existing opt-in queue preference, independent from paused in-app notices.
    if policy["platforms"]["naukri"]["notify_telegram"] == true && telegram_available {
        let digest = Sha256::digest(key.as_bytes());
        let prefix = digest
            .iter()
            .take(8)
            .fold(0u64, |n, b| (n << 8) | u64::from(*b))
            >> 4;
        let update = -i64::try_from(prefix).map_err(|_| invalid())? - (1i64 << 61);
        let reply = format!("{title}: {body}");
        let inserted:Option<i64>=sqlx::query_scalar("INSERT INTO agent_telegram_deliveries(update_id,state,reply) VALUES($1,'pending',$2) ON CONFLICT(update_id) DO NOTHING RETURNING update_id").bind(update).bind(&reply).fetch_optional(&mut **tx).await.map_err(db)?;
        if inserted.is_none() {
            let existing: Option<String> = sqlx::query_scalar(
                "SELECT reply FROM agent_telegram_deliveries WHERE update_id=$1",
            )
            .bind(update)
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?;
            if existing.as_deref() != Some(reply.as_str()) {
                return Err(Failure("execution_write_ack_failed"));
            }
        } else if inserted != Some(update) {
            return Err(Failure("execution_write_ack_failed"));
        }
        channels.push("telegram_outbox");
    }
    Ok(channels)
}
pub(super) async fn unknown(
    tx: &mut Transaction<'_, Postgres>,
    work: &mut Value,
    telegram: bool,
    now: DateTime<Utc>,
) -> Result<bool> {
    if !work["uncertain_outcome_notice"].is_null()
        || work["status"] != "unknown"
        || work["stage"] != "SUBMISSION_UNKNOWN"
        || work["admitted_actions"]
            .as_array()
            .is_none_or(Vec::is_empty)
    {
        return Ok(false);
    }
    let attempts = |key: &str| work[key].as_i64().unwrap_or(0);
    if attempts("reconciliation_attempts").max(attempts("account_recheck_attempts")) < 3 {
        return Ok(false);
    }
    let channels = save(tx, work, true, telegram).await?;
    if channels.is_empty() {
        return Ok(false);
    }
    work["uncertain_outcome_notice"] = json!({"at":stamp(now),"channels":channels,"dedup_key":format!("naukri-unknown:{}",work["id"].as_str().ok_or_else(invalid)?),"verified_submission":false});
    Ok(true)
}
