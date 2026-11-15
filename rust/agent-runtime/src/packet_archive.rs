//! Preserve the exact preceding revision before a compare-and-swap edit. No commit or approval.
use crate::{
    Failure, Result,
    packet_record::{self, Kind},
};
use chrono::{DateTime, SecondsFormat, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;

pub fn key(packet: Uuid, revision: i32) -> Result<String> {
    if revision < 1 {
        return Err(Failure("invalid_packet_saved_record"));
    }
    Ok(format!("prv:{}:{revision}", packet.simple()))
}
pub fn record(packet: &Value, fields: &[Value], now: DateTime<Utc>) -> Result<Value> {
    let fields = fields
        .iter()
        .map(|f| packet_record::normalize(Kind::Field, f.clone()))
        .collect::<Result<Vec<_>>>()?;
    let archived = json!({"packet_id":packet["id"],"revision":packet["revision"],"approved_revision":packet["approved_revision"],"lifecycle_state":packet["lifecycle_state"],"tracking_state":packet["tracking_state"],"snapshot":packet["snapshot"],"fields":fields,"archived_at":now.to_rfc3339_opts(if now.timestamp_subsec_micros()==0{SecondsFormat::Secs}else{SecondsFormat::Micros},false)});
    let mut value = archived.clone();
    value["digest"] = json!(crate::python_json::digest(&archived));
    Ok(value)
}
pub(crate) async fn advance_in(
    tx: &mut Transaction<'_, Postgres>,
    packet: &Value,
    fields: &[Value],
    expected: i32,
    now: DateTime<Utc>,
) -> Result<Value> {
    advance_mode_in(tx, packet, fields, expected, now, false).await
}
/// Tracking can carry an unchanged approval forward; content edits always clear it.
pub(crate) async fn advance_mode_in(
    tx: &mut Transaction<'_, Postgres>,
    packet: &Value,
    fields: &[Value],
    expected: i32,
    now: DateTime<Utc>,
    preserve: bool,
) -> Result<Value> {
    let packet_id = crate::packet_service::id(&packet["id"])?;
    if packet["revision"] != expected {
        return Err(Failure("packet_revision_conflict"));
    }
    let archived = record(packet, fields, now)?;
    let approved = if preserve && !packet["approved_revision"].is_null() {
        Some(expected + 1)
    } else {
        None
    };
    let lifecycle = if preserve {
        packet["lifecycle_state"]
            .as_str()
            .ok_or(Failure("invalid_packet_saved_record"))?
    } else {
        "preparing"
    };
    let updated:Option<Value>=sqlx::query_scalar("UPDATE application_packets p SET revision=$2+1,approved_revision=$4,lifecycle_state=$5,updated_at=$3::timestamptz WHERE id=$1 AND revision=$2 RETURNING to_jsonb(p)").bind(packet_id).bind(expected).bind(now.to_rfc3339()).bind(approved).bind(lifecycle).fetch_optional(&mut **tx).await.map_err(crate::packet_service::db)?;
    let updated = updated.ok_or(Failure("packet_revision_conflict"))?;
    if updated["revision"] != expected + 1
        || updated["approved_revision"] != json!(approved)
        || updated["lifecycle_state"] != lifecycle
    {
        return Err(Failure("packet_write_ack_failed"));
    }
    let available: bool = sqlx::query_scalar("SELECT to_regclass('owner_preferences') IS NOT NULL")
        .fetch_one(&mut **tx)
        .await
        .map_err(crate::packet_service::db)?;
    if available {
        let archive_key = key(packet_id, expected)?;
        let saved:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value) VALUES($1,$2) ON CONFLICT(key) DO NOTHING RETURNING value")
            .bind(&archive_key).bind(&archived).fetch_optional(&mut **tx).await.map_err(crate::packet_service::db)?;
        if let Some(saved) = saved {
            if saved != archived {
                return Err(Failure("packet_write_ack_failed"));
            }
        } else {
            let saved: Option<Value> =
                sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
                    .bind(archive_key)
                    .fetch_optional(&mut **tx)
                    .await
                    .map_err(crate::packet_service::db)?;
            let saved = saved.ok_or(Failure("packet_write_ack_failed"))?;
            // Retain the first archive's timestamp, but never silently accept a
            // suppressed insert or an unrelated/corrupt prior revision.
            for key in [
                "packet_id",
                "revision",
                "approved_revision",
                "lifecycle_state",
                "tracking_state",
                "snapshot",
                "fields",
            ] {
                if saved[key] != archived[key] {
                    return Err(Failure("packet_write_ack_failed"));
                }
            }
            let mut payload = saved.clone();
            payload
                .as_object_mut()
                .ok_or(Failure("packet_write_ack_failed"))?
                .remove("digest");
            if saved["digest"] != crate::python_json::digest(&payload) {
                return Err(Failure("packet_write_ack_failed"));
            }
        }
    }
    Ok(updated)
}
