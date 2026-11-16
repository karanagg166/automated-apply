//! Stable legacy outbox identities, saved inside the caller's state transaction.
use super::storage::*;
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;

pub(super) async fn queue(
    tx: &mut Transaction<'_, Postgres>,
    work: &Value,
    event: &str,
    now: DateTime<Utc>,
) -> Result<()> {
    let identity = work["id"]
        .as_str()
        .filter(|s| s.parse::<Uuid>().is_ok())
        .ok_or_else(invalid)?;
    let revision = revision(work)?;
    let id = Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!("queue:{identity}:{revision}:{event}").as_bytes(),
    );
    let key = format!("apply_event:{id}");
    let value = json!({"id":id,"queue_id":identity,"platform":work["platform"],"stage":work["stage"],"event":event,"at":stamp(now),"delivered":false});
    insert(tx, &key, &value).await
}
async fn insert(tx: &mut Transaction<'_, Postgres>, key: &str, value: &Value) -> Result<()> {
    let ack:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value) VALUES($1,$2) ON CONFLICT(key) DO NOTHING RETURNING value").bind(key).bind(value).fetch_optional(&mut **tx).await.map_err(db)?;
    match ack {
        Some(ack) if &ack == value => Ok(()),
        None if get(tx, key).await?.as_ref() == Some(value) => Ok(()),
        _ => Err(Failure("execution_write_ack_failed")),
    }
}
pub(super) async fn legacy(
    tx: &mut Transaction<'_, Postgres>,
    intent: &Value,
    event: &str,
    now: DateTime<Utc>,
) -> Result<()> {
    let identity = intent["id"]
        .as_str()
        .filter(|s| s.parse::<Uuid>().is_ok())
        .ok_or_else(invalid)?;
    let id = Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!("{identity}:{}:{event}", revision(intent)?).as_bytes(),
    );
    insert(tx,&format!("exec_event:{id}"),&json!({"id":id,"execution_id":identity,"event":event,"state":intent["state"],"at":stamp(now),"delivered":false})).await
}
