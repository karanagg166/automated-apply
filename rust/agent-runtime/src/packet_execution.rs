//! Existing legacy execution-owner fence for packet review. Never creates/starts execution.
use crate::{Failure, Result, packet_service};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;

pub struct Binding {
    pub key: String,
    pub value: Value,
}
pub async fn lock_in(tx: &mut Transaction<'_, Postgres>, packet: Uuid) -> Result<Option<Binding>> {
    let available: bool = sqlx::query_scalar("SELECT to_regclass('owner_preferences') IS NOT NULL")
        .fetch_one(&mut **tx)
        .await
        .map_err(packet_service::db)?;
    if !available {
        return Ok(None);
    }
    let rows:Vec<(String,Value)>=sqlx::query_as("SELECT key,value FROM owner_preferences WHERE starts_with(key,'exec:') AND value->>'packet_id'=$1 LIMIT 2").bind(packet.to_string()).fetch_all(&mut **tx).await.map_err(packet_service::db)?;
    if rows.is_empty() {
        return Ok(None);
    }
    // A duplicate/incorrect binding cannot safely choose which execution receives review.
    if rows.len() != 1 {
        return Err(Failure("packet_execution_binding_conflict"));
    }
    let (key, first) = &rows[0];
    let execution = packet_service::id(&first["id"])?;
    if *key != format!("exec:{execution}") {
        return Err(Failure("packet_execution_binding_conflict"));
    }
    let owned: Option<String> = sqlx::query_scalar(
        "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
    )
    .fetch_optional(&mut **tx)
    .await
    .map_err(packet_service::db)?;
    if owned.is_none() {
        sqlx::query("INSERT INTO owner_preferences(key,value) VALUES('agent_conversation:primary','{}') ON CONFLICT(key) DO NOTHING").execute(&mut **tx).await.map_err(packet_service::db)?;
        let locked: Option<String> = sqlx::query_scalar(
            "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
        )
        .fetch_optional(&mut **tx)
        .await
        .map_err(packet_service::db)?;
        if locked.is_none() {
            return Err(Failure("packet_write_ack_failed"));
        }
    }
    let current: Option<Value> =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1 FOR UPDATE")
            .bind(key)
            .fetch_optional(&mut **tx)
            .await
            .map_err(packet_service::db)?;
    let current = current.ok_or(Failure("packet_execution_binding_conflict"))?;
    if current["id"] != json!(execution) || current["packet_id"] != json!(packet) {
        return Err(Failure("packet_execution_binding_conflict"));
    }
    Ok(Some(Binding {
        key: key.clone(),
        value: current,
    }))
}
pub async fn reviewed_in(
    tx: &mut Transaction<'_, Postgres>,
    binding: &mut Binding,
    fields: &[Value],
) -> Result<()> {
    let revisions = fields
        .iter()
        .filter(|f| f["review_status"] == "reviewed")
        .map(|f| {
            let id = packet_service::id(&f["id"])?;
            let revision = f["answer_revision"]
                .as_i64()
                .filter(|n| *n >= 1)
                .ok_or(Failure("invalid_packet_saved_record"))?;
            Ok((id.to_string(), json!(revision)))
        })
        .collect::<Result<serde_json::Map<String, Value>>>()?;
    let mut value = binding.value.clone();
    value["approved_answer_revisions"] = Value::Object(revisions);
    let saved:Option<Value>=sqlx::query_scalar("UPDATE owner_preferences SET value=$2,updated_at=clock_timestamp() WHERE key=$1 AND value=$3 RETURNING value").bind(&binding.key).bind(&value).bind(&binding.value).fetch_optional(&mut **tx).await.map_err(packet_service::db)?;
    if saved != Some(value.clone()) {
        return Err(Failure("packet_write_ack_failed"));
    }
    binding.value = value;
    Ok(())
}
