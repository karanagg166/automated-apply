//! Owner history summarizes the retained receipt without replaying private inputs.
use super::*;
use chrono::{DateTime, Utc};

fn tag(value: &Value) -> Option<&str> {
    value.as_str().filter(|text| {
        (1..=80).contains(&text.len())
            && text
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-'))
    })
}
fn receipt_summary(receipt: Option<Value>) -> Value {
    let Some(receipt) = receipt else {
        return json!({"data":{"status":"details_omitted"}});
    };
    let mut summary = serde_json::Map::new();
    if receipt["version"] == 1 {
        summary.insert("version".into(), json!(1));
    }
    for key in ["request_id", "correlation_id"] {
        if let Some(id) = receipt[key].as_str().and_then(|id| id.parse::<Uuid>().ok()) {
            summary.insert(key.into(), json!(id));
        }
    }
    if let Some(ok) = receipt["ok"].as_bool() {
        summary.insert("ok".into(), json!(ok));
        summary.insert("error_code".into(), json!(tag(&receipt["error_code"])));
    }
    if let Some(capability) = tag(&receipt["capability"]) {
        summary.insert("capability".into(), json!(capability));
    }
    let detail = receipt
        .get("data")
        .filter(|data| data.is_object())
        .unwrap_or(&receipt);
    let mut data = serde_json::Map::new();
    for key in [
        "status",
        "state",
        "platform",
        "readiness",
        "lifecycle_state",
        "observation",
        "reason",
    ] {
        if let Some(value) = tag(&detail[key]) {
            data.insert(key.into(), json!(value));
        }
    }
    for key in [
        "job_id",
        "packet_id",
        "run_id",
        "task_id",
        "application_id",
        "plan_id",
    ] {
        if let Some(id) = detail[key].as_str().and_then(|id| id.parse::<Uuid>().ok()) {
            data.insert(key.into(), json!(id));
        }
    }
    for key in [
        "submitted",
        "executed",
        "page_inspected",
        "discovery_executed",
        "deployment_enabled",
        "schedule_enabled",
        "identity_verified",
        "api_connected",
    ] {
        if let Some(value) = detail[key].as_bool() {
            data.insert(key.into(), json!(value));
        }
    }
    summary.insert("data".into(), Value::Object(data));
    Value::Object(summary)
}

pub(super) async fn listing(connection: &mut PgConnection) -> Result<Value> {
    let rows: Vec<(String, String, DateTime<Utc>, Option<Value>)> = sqlx::query_as(
        "SELECT command,actor,created_at,CASE WHEN octet_length(result::text)<=32768 THEN result END
         FROM agent_operations ORDER BY created_at DESC,key DESC LIMIT 50",
    ).fetch_all(connection).await.map_err(db)?;
    Ok(json!(rows.into_iter().map(|(command,actor,created_at,result)| {
        json!({"command":command,"actor":actor,"created_at":created_at,"result":receipt_summary(result)})
    }).collect::<Vec<_>>()))
}
