//! Transactional preparation notices. No network transport, application action or arbitrary recipient.
use crate::{
    Failure, Result, notification_preferences,
    packet_execution::Binding,
    packet_readiness::{Flags, State},
    packet_service,
};
use chrono::{DateTime, Utc};
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use sqlx::{Postgres, Transaction};
use std::collections::BTreeMap;
use uuid::Uuid;

#[derive(Serialize)]
pub struct Notice {
    pub notification: Value,
    pub telegram: Option<Value>,
}
fn invalid() -> Failure {
    Failure("invalid_packet_notice_state")
}
pub fn telegram_configured(values: &BTreeMap<String, String>) -> bool {
    let token = values.get("TELEGRAM_BOT_TOKEN").filter(|s| !s.is_empty());
    let owner = |key| {
        values
            .get(key)
            .and_then(|s| s.parse::<i64>().ok())
            .is_some_and(|n| n > 0 && n < (1_i64 << 52))
    };
    token.is_some() && owner("TELEGRAM_OWNER_CHAT_ID") && owner("TELEGRAM_OWNER_USER_ID")
}
fn basic(
    packet: &Value,
    execution: Option<&Value>,
    automation: &Value,
    configuration: Option<&Value>,
) -> Result<bool> {
    if packet["platform"] != "naukri"
        || packet["readiness"]["stale"] == true
        || matches!(
            packet["lifecycle_state"].as_str(),
            Some(
                "user_reported_submitted"
                    | "provider_confirmed_submitted"
                    | "submitting"
                    | "submission_unknown"
                    | "withdrawn"
                    | "abandoned"
            )
        )
        || !matches!(
            packet["readiness"]["state"].as_str(),
            Some("needs_review" | "ready_for_manual_handoff")
        )
        || packet["snapshot"]["destination"]["valid"] != true
    {
        return Ok(false);
    }
    if let Some(execution) = execution {
        let state = execution["state"].as_str().ok_or_else(invalid)?;
        let platform = execution["platform"].as_str().ok_or_else(invalid)?;
        if platform != "naukri"
            || matches!(
                state,
                "REJECTED"
                    | "FAILED_FINAL"
                    | "SUBMITTED_CONFIRMED"
                    | "SUBMISSION_UNKNOWN"
                    | "PAUSED"
            )
            || execution["cancelled"] == true
        {
            return Ok(false);
        }
        if !execution["cancelled"].is_null() && !execution["cancelled"].is_boolean() {
            return Err(invalid());
        }
    }
    let revision = automation["revision"]
        .as_i64()
        .filter(|n| *n >= 0)
        .ok_or_else(invalid)?;
    let state = automation["state"]
        .as_str()
        .filter(|s| matches!(*s, "RUNNING" | "PAUSED" | "STOPPED"))
        .ok_or_else(invalid)?;
    if !automation["policy"].is_null() && !automation["policy"].is_object() {
        return Err(invalid());
    }
    if let Some(configuration) = configuration
        && (!configuration.is_object()
            || (!configuration["mode"].is_null()
                && !configuration["mode"].as_str().is_some_and(|s| {
                    matches!(
                        s,
                        "OFF" | "ON_DEMAND" | "WATCH_AND_NOTIFY" | "AUTO_APPLY_WHEN_AUTHORIZED"
                    )
                })))
    {
        return Err(invalid());
    }
    if revision != 0 && state != "RUNNING" || configuration.is_some_and(|c| c["mode"] == "OFF") {
        return Ok(false);
    }
    Ok(true)
}
pub fn propose(
    packet: &Value,
    execution: Option<&Value>,
    automation: &Value,
    configuration: Option<&Value>,
    prefs: &Value,
    telegram_available: bool,
    now: DateTime<Utc>,
) -> Result<Option<Notice>> {
    if !basic(packet, execution, automation, configuration)?
        || prefs["paused"] == true
        || prefs["in_app"] != true
    {
        return Ok(None);
    }
    let fields = packet["fields"].as_array().ok_or_else(invalid)?;
    let candidate = packet_service::readiness(
        &packet["snapshot"],
        fields,
        Flags {
            approved: true,
            ..Default::default()
        },
        "created",
        now,
    )?;
    if !matches!(
        candidate.state,
        State::NeedsReview | State::ReadyForManualHandoff
    ) {
        return Ok(None);
    }
    let approved = packet["readiness"]["state"] == "ready_for_manual_handoff";
    if approved && packet["approved_revision"] != packet["revision"] {
        return Ok(None);
    }
    let id = packet_service::id(&packet["id"])?;
    let revision = packet["revision"]
        .as_i64()
        .filter(|r| *r >= 1)
        .ok_or_else(invalid)?;
    let phase = if approved {
        "manual_handoff"
    } else {
        "owner_review"
    };
    let key = format!("naukri-packet:{id}:{revision}:{phase}");
    let title = format!(
        "Naukri application ready for {}",
        if approved {
            "manual Apply"
        } else {
            "owner review"
        }
    );
    let role = packet["snapshot"]["job_title"]
        .as_str()
        .ok_or_else(invalid)?;
    let company = packet["snapshot"]["company_name"]
        .as_str()
        .filter(|s| !s.is_empty())
        .unwrap_or("saved employer");
    let body = format!(
        "{role} at {company}. Packet revision {revision}: saved resume and answers {}Verify the live vacancy, saved Naukri resume and any actual questions. Apply is owner-operated and may submit immediately or follow the company. No application has been sent.",
        if approved {
            "reviewed. "
        } else {
            "prepared; review required. "
        }
    );
    let telegram = if telegram_available
        && execution.is_some_and(|e| {
            automation["state"] == "RUNNING" && e["automation_revision"] == automation["revision"]
        })
        && automation["policy"]["telegram_questions"] == true
    {
        let digest = format!("{:x}", Sha256::digest(key.as_bytes()));
        let prefix = i64::from_str_radix(&digest[..15], 16).map_err(|_| invalid())?;
        Some(
            json!({"update_id":-prefix-(1_i64<<61),"state":"pending","reply":format!("{title}: {body} Open Automated Apply → Applications → {id}")}),
        )
    } else {
        None
    };
    Ok(Some(Notice {
        notification: json!({"dedup_key":key,"kind":"application_ready","title":title,"body":body,"href":format!("/applications/{id}")}),
        telegram,
    }))
}
pub async fn notify_in(
    tx: &mut Transaction<'_, Postgres>,
    execution: Option<&Binding>,
    packet: &Value,
    telegram_available: bool,
) -> Result<bool> {
    if packet["platform"] != "naukri" {
        return Ok(false);
    }
    let available: bool = sqlx::query_scalar("SELECT to_regclass('owner_preferences') IS NOT NULL")
        .fetch_one(&mut **tx)
        .await
        .map_err(packet_service::db)?;
    if !available {
        return Ok(false);
    }
    let rows:Vec<(String,Value)>=sqlx::query_as("SELECT key,value FROM owner_preferences WHERE key IN ('naukri_automation','exec_config:naukri')").fetch_all(&mut **tx).await.map_err(packet_service::db)?;
    let values = rows.into_iter().collect::<BTreeMap<_, _>>();
    let automation = values
        .get("naukri_automation")
        .cloned()
        .unwrap_or(json!({"revision":0,"state":"STOPPED"}));
    let configuration = values.get("exec_config:naukri");
    let execution = execution.map(|b| &b.value);
    if !basic(packet, execution, &automation, configuration)? {
        return Ok(false);
    }
    let prefs = notification_preferences::load_in(tx).await?;
    let Some(notice) = propose(
        packet,
        execution,
        &automation,
        configuration,
        &prefs,
        telegram_available,
        Utc::now(),
    )?
    else {
        return Ok(false);
    };
    let row = &notice.notification;
    let id = Uuid::new_v4();
    let inserted:Option<Uuid>=sqlx::query_scalar("INSERT INTO owner_notifications(id,dedup_key,kind,title,body,href) VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(dedup_key) DO NOTHING RETURNING id").bind(id).bind(row["dedup_key"].as_str().ok_or_else(invalid)?).bind(row["kind"].as_str().ok_or_else(invalid)?).bind(row["title"].as_str().ok_or_else(invalid)?).bind(row["body"].as_str().ok_or_else(invalid)?).bind(row["href"].as_str().ok_or_else(invalid)?).fetch_optional(&mut **tx).await.map_err(packet_service::db)?;
    if inserted.is_none() {
        let exists: bool = sqlx::query_scalar(
            "SELECT EXISTS(SELECT 1 FROM owner_notifications WHERE dedup_key=$1)",
        )
        .bind(row["dedup_key"].as_str().ok_or_else(invalid)?)
        .fetch_one(&mut **tx)
        .await
        .map_err(packet_service::db)?;
        if exists {
            return Ok(false);
        }
        return Err(Failure("packet_write_ack_failed"));
    }
    if inserted != Some(id) {
        return Err(Failure("packet_write_ack_failed"));
    }
    let delivery = Uuid::new_v4();
    let inserted:Option<Uuid>=sqlx::query_scalar("INSERT INTO notification_deliveries(id,notification_id,channel,status,attempt_count) VALUES($1,$2,'in_app','available_in_app',1) ON CONFLICT(notification_id,channel) DO NOTHING RETURNING id").bind(delivery).bind(id).fetch_optional(&mut **tx).await.map_err(packet_service::db)?;
    if inserted != Some(delivery) {
        return Err(Failure("packet_write_ack_failed"));
    }
    if let Some(telegram) = notice.telegram {
        let update = telegram["update_id"].as_i64().ok_or_else(invalid)?;
        let inserted:Option<i64>=sqlx::query_scalar("INSERT INTO agent_telegram_deliveries(update_id,state,reply) VALUES($1,'pending',$2) ON CONFLICT(update_id) DO NOTHING RETURNING update_id").bind(update).bind(telegram["reply"].as_str().ok_or_else(invalid)?).fetch_optional(&mut **tx).await.map_err(packet_service::db)?;
        if inserted != Some(update) {
            let exists: bool = sqlx::query_scalar(
                "SELECT EXISTS(SELECT 1 FROM agent_telegram_deliveries WHERE update_id=$1)",
            )
            .bind(update)
            .fetch_one(&mut **tx)
            .await
            .map_err(packet_service::db)?;
            if !exists {
                return Err(Failure("packet_write_ack_failed"));
            }
        }
        // Bind only this newly generated typed notice. Historical pending rows
        // without a current bound outbox are never imported or replayed.
        let available:bool=sqlx::query_scalar("SELECT to_regclass('rust_telegram_runtime') IS NOT NULL AND to_regclass('rust_telegram_outbox') IS NOT NULL").fetch_one(&mut **tx).await.map_err(packet_service::db)?;
        if available && inserted == Some(update) {
            let binding: Option<String> =
                sqlx::query_scalar("SELECT binding FROM rust_telegram_runtime WHERE key='primary'")
                    .fetch_optional(&mut **tx)
                    .await
                    .map_err(packet_service::db)?;
            if let Some(binding) = binding {
                let id = Uuid::new_v5(
                    &Uuid::NAMESPACE_URL,
                    format!("packet_notice:{update}").as_bytes(),
                );
                let reply = telegram["reply"].as_str().ok_or_else(invalid)?;
                if reply.encode_utf16().count() > 3500 {
                    return Err(Failure("telegram_reply_size"));
                }
                let ack:Option<Uuid>=sqlx::query_scalar("INSERT INTO rust_telegram_outbox(id,update_id,binding,reply,state) VALUES($1,$2,$3,$4,'pending') ON CONFLICT(id) DO UPDATE SET id=EXCLUDED.id WHERE rust_telegram_outbox.update_id=EXCLUDED.update_id AND rust_telegram_outbox.binding=EXCLUDED.binding AND rust_telegram_outbox.reply=EXCLUDED.reply RETURNING id").bind(id).bind(update).bind(binding).bind(reply).fetch_optional(&mut **tx).await.map_err(packet_service::db)?;
                if ack != Some(id) {
                    return Err(Failure("packet_write_ack_failed"));
                }
            }
        }
    }
    Ok(true)
}
