//! Closed in-app preferences. External channels remain disabled; this never schedules delivery.
use crate::{Failure, Result};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use std::io::Read;

pub(crate) const PATH: &str = "/api/v1/dashboard/notification-preferences";
fn invalid() -> Failure {
    Failure("invalid_notification_preferences")
}
fn timezone(key: &str) -> bool {
    // Match ZoneInfo's normalized relative keys against the Mac/system TZif database.
    // Never consult a user-supplied TZPATH or read a path outside these fixed public roots.
    if key.is_empty()
        || key.starts_with('/')
        || key.split('/').any(|s| matches!(s, "" | "." | ".."))
    {
        return false;
    }
    [
        "/usr/share/zoneinfo",
        "/usr/lib/zoneinfo",
        "/usr/share/lib/zoneinfo",
        "/etc/zoneinfo",
    ]
    .iter()
    .any(|root| {
        let mut header = [0; 4];
        std::fs::File::open(std::path::Path::new(root).join(key))
            .and_then(|mut f| f.read_exact(&mut header))
            .is_ok()
            && &header == b"TZif"
    })
}
pub fn normalize(input: Value) -> Result<Value> {
    let mut output = json!({"in_app":true,"paused":false,"daily_digest":true,"minimum_job_score":75,"minimum_startup_score":70,"automation_failures":true,"quiet_start":22,"quiet_end":8,"timezone":"Asia/Kolkata","browser_push":false,"telegram":false,"whatsapp":false});
    let body = input
        .as_object()
        .filter(|b| b.keys().all(|k| output.get(k).is_some()))
        .ok_or_else(invalid)?;
    for (key, value) in body {
        output[key] = match key.as_str() {
            "in_app" | "paused" | "daily_digest" | "automation_failures" => {
                crate::resource_contract::boolean(value).map_err(|_| invalid())?
            }
            "minimum_job_score" | "minimum_startup_score" | "quiet_start" | "quiet_end" => json!(
                crate::profile_contract::pagination_integer(
                    value.clone(),
                    0,
                    if key.starts_with("quiet_") { 23 } else { 100 }
                )
                .map_err(|_| invalid())?
            ),
            "timezone" => {
                let key = value
                    .as_str()
                    .filter(|s| s.chars().count() <= 100 && timezone(s))
                    .ok_or_else(invalid)?;
                json!(key)
            }
            "browser_push" | "telegram" | "whatsapp"
                if value == false || value.as_f64() == Some(0.0) =>
            {
                json!(false)
            }
            _ => return Err(invalid()),
        };
    }
    Ok(output)
}
pub(crate) async fn load_in(tx: &mut Transaction<'_, Postgres>) -> Result<Value> {
    let raw: Option<Value> =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key='notifications'")
            .fetch_optional(&mut **tx)
            .await
            .map_err(|_| Failure("profile_database_error"))?;
    normalize(raw.unwrap_or(json!({})))
        .map_err(|_| Failure("invalid_saved_notification_preferences"))
}
pub(crate) async fn dispatch(
    connection: &mut PgConnection,
    method: &str,
    body: &[u8],
) -> Result<Value> {
    if !matches!(method, "GET" | "PUT") {
        return Err(Failure("notification_preferences_method_not_allowed"));
    }
    let input = if method == "PUT" {
        Some(normalize(
            serde_json::from_slice(body).map_err(|_| invalid())?,
        )?)
    } else {
        None
    };
    let mut tx = connection
        .begin()
        .await
        .map_err(|_| Failure("profile_database_error"))?;
    let result = if let Some(input) = input {
        let stored:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value) VALUES('notifications',$1) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=clock_timestamp() RETURNING value").bind(&input).fetch_optional(&mut *tx).await.map_err(|_|Failure("profile_database_error"))?;
        if stored != Some(input.clone()) {
            tx.rollback()
                .await
                .map_err(|_| Failure("profile_database_error"))?;
            return Err(Failure("notification_preferences_write_ack_failed"));
        }
        input
    } else {
        load_in(&mut tx).await?
    };
    tx.commit()
        .await
        .map_err(|_| Failure("notification_preferences_outcome_unknown"))?;
    Ok(result)
}
