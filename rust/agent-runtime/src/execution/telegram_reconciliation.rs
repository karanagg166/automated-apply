//! Owner-reported prompt delivery findings. They never resend, renew context or prove an application.
use super::storage::*;
use crate::{Failure, Result, telegram::Settings};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;
pub fn normalize(mut value: Value) -> Result<Value> {
    let invalid = || Failure("invalid_execution_contract");
    let map = value.as_object().ok_or_else(invalid)?;
    if map.len() < 2
        || map.len() > 3
        || map.keys().any(|k| {
            !matches!(
                k.as_str(),
                "expected_delivery_attempt" | "outcome" | "message_id"
            )
        })
    {
        return Err(invalid());
    }
    let attempt = map
        .get("expected_delivery_attempt")
        .and_then(Value::as_str)
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    let message = map.get("message_id").unwrap_or(&Value::Null);
    match map.get("outcome").and_then(Value::as_str) {
        Some("sent") if message.as_i64().is_some_and(|n| n > 0 && n < i64::MAX) => {}
        Some("not_sent") if message.is_null() => {}
        _ => return Err(invalid()),
    }
    value["expected_delivery_attempt"] = json!(attempt);
    if value.get("message_id").is_none() {
        value["message_id"] = Value::Null;
    }
    Ok(value)
}
fn view(q: &Value) -> Value {
    json!({"question_id":q["id"],"state":q["state"],"delivery_attempt":q["delivery_attempt"],"reconciliation":q["delivery_reconciliation"],"message_ids":q["message_ids"],"resend_scheduled":false,"application_receipt":false,"submitted":false})
}
pub(super) async fn reconcile_in(
    tx: &mut Transaction<'_, Postgres>,
    identity: Uuid,
    input: &Value,
    settings: &Settings,
    now: DateTime<Utc>,
) -> Result<Value> {
    crate::telegram::bound(tx, settings).await?;
    let key = format!("exec_q:{identity}");
    let mut question = get(tx, &key).await?.ok_or(Failure("question_not_found"))?;
    if question["id"] != json!(identity) {
        return Err(invalid());
    }
    if question["delivery_binding"] != settings.binding() {
        return Err(Failure("telegram_delivery_binding_required"));
    }
    if question["delivery_attempt"] != input["expected_delivery_attempt"] {
        return Err(Failure("telegram_delivery_attempt_conflict"));
    }
    if !question["delivery_reconciliation"].is_null() {
        if question["delivery_reconciliation"]["input"] == *input {
            return Ok(view(&question));
        }
        return Err(Failure("telegram_delivery_already_resolved"));
    }
    if question["state"] != "delivery_unknown" {
        return Err(Failure("telegram_delivery_already_resolved"));
    }
    if !question["delivery_lease"].is_null() && timestamp(&question["delivery_lease"])? > now {
        return Err(Failure("telegram_delivery_lease_active"));
    }
    let mut ids = question["message_ids"]
        .as_array()
        .ok_or_else(invalid)?
        .clone();
    if input["outcome"] == "sent" {
        let message = input["message_id"].as_i64().ok_or_else(invalid)?;
        let conflicts:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM owner_preferences WHERE starts_with(key,'exec_q:') AND key!=$1 AND (value->'message_ids' @> $2::jsonb OR value->'expired_message_ids' @> $2::jsonb))").bind(&key).bind(json!([message])).fetch_one(&mut **tx).await.map_err(db)?;
        if conflicts {
            return Err(Failure("telegram_delivery_message_conflict"));
        }
        if !ids.contains(&json!(message)) {
            if ids.len() >= 50 {
                return Err(Failure("execution_active_inventory_limit"));
            }
            ids.push(json!(message));
        }
        question["state"] = json!("sent");
    } else {
        if !ids.is_empty() {
            return Err(Failure("telegram_delivery_message_conflict"));
        }
        question["state"] = json!("delivery_not_sent");
    }
    question["message_ids"] = json!(ids);
    question["delivery_lease"] = Value::Null;
    question["delivery_reconciliation"] = json!({"input":input,"at":stamp(now),"source":"owner_dashboard","evidence":"owner_reported_delivery_only","provider_receipt_verified":false,"resend_scheduled":false});
    put(tx, &key, &question).await?;
    Ok(view(&question))
}
