//! Authenticated dashboard commands over saved data and local drafts.
use super::{Stored, ack, db, invalid, lookup};
use crate::{
    Failure, Result,
    configuration::Configuration,
    conversation::{intent, memory::Scope, reply},
};
use serde::Deserialize;
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;

const ACTOR: &str = "owner:primary";
const COMMAND: &str = "dashboard_conversation";
const RETRY: Failure = Failure("dashboard_command_retry");
const UNKNOWN: Failure = Failure("local_command_outcome_unknown");

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Input {
    request_id: Uuid,
    text: String,
}

fn transaction_error(error: sqlx::Error) -> Failure {
    match error.as_database_error().and_then(|e| e.code()).as_deref() {
        Some("40001" | "40P01" | "55P03") => RETRY,
        _ => db(error),
    }
}

fn valid_receipt(output: &Value, id: Uuid) -> bool {
    let data = &output["data"];
    output["version"] == 1
        && output["request_id"] == json!(id)
        && output["ok"] == true
        && output["capability"] == "preview_only"
        && output["error_code"].is_null()
        && output["correlation_id"]
            .as_str()
            .and_then(|id| id.parse::<Uuid>().ok())
            .is_some_and(|id| !id.is_nil())
        && data["submitted"] == false
        && data["status"].is_string()
        && data["reply"].is_string()
        && data.get("packet_id").is_none_or(|id| {
            id.as_str()
                .and_then(|id| id.parse::<Uuid>().ok())
                .is_some_and(|id| !id.is_nil())
        })
}

async fn record_in(
    tx: &mut Transaction<'_, Postgres>,
    input: &Input,
    config: &Configuration,
) -> Result<Value> {
    crate::execution::lock_owner_with_error_in(tx, transaction_error).await?;
    let key = format!("{ACTOR}:{COMMAND}:{}", input.request_id);
    let hash = crate::python_json::digest(&json!({"text": input.text}));
    if let Some((actor, command, old_hash, output)) = lookup(tx, &key).await? {
        if actor != ACTOR || command != COMMAND || old_hash != hash {
            return Err(Failure("request_id_conflict"));
        }
        return output
            .filter(|value| valid_receipt(value, input.request_id))
            .ok_or(Failure("invalid_local_command_record"));
    }
    let now = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut **tx)
        .await
        .map_err(transaction_error)?;
    let data = reply::respond(
        tx,
        config,
        Scope::Dashboard,
        intent::deterministic(&input.text),
        now,
    )
    .await?;
    let output = json!({
        "version":1,"request_id":input.request_id,"correlation_id":Uuid::new_v4(),
        "ok":true,"capability":"preview_only","error_code":null,"data":data,
    });
    if !valid_receipt(&output, input.request_id) {
        return Err(ack());
    }
    if output.to_string().len() > 120000 {
        return Err(Failure("local_command_result_limit"));
    }
    let expected = (ACTOR.into(), COMMAND.into(), hash, Some(output.clone()));
    let written: Option<Stored> = sqlx::query_as(
        "INSERT INTO agent_operations(key,actor,command,payload_hash,result)
         VALUES($1,$2,$3,$4,$5) RETURNING actor,command,payload_hash,result",
    )
    .bind(&key)
    .bind(&expected.0)
    .bind(&expected.1)
    .bind(&expected.2)
    .bind(&output)
    .fetch_optional(&mut **tx)
    .await
    .map_err(transaction_error)?;
    if written.as_ref() != Some(&expected) || lookup(tx, &key).await?.as_ref() != Some(&expected) {
        return Err(ack());
    }
    Ok(output)
}

pub(super) async fn dispatch(
    connection: &mut PgConnection,
    body: &[u8],
    config: &Configuration,
) -> Result<Value> {
    let mut input: Input = serde_json::from_slice(body).map_err(|_| invalid())?;
    input.text = input.text.trim().to_owned();
    if input.request_id.is_nil()
        || !(1..=2000).contains(&input.text.chars().count())
        || input
            .text
            .chars()
            .any(|c| c.is_control() && !matches!(c, '\n' | '\r' | '\t'))
    {
        return Err(invalid());
    }
    for attempt in 0..3 {
        let mut tx = connection.begin().await.map_err(db)?;
        sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            .execute(&mut *tx)
            .await
            .map_err(db)?;
        match record_in(&mut tx, &input, config).await {
            Ok(output) => {
                tx.commit().await.map_err(|_| UNKNOWN)?;
                return Ok(output);
            }
            Err(error) => {
                tx.rollback().await.map_err(|_| UNKNOWN)?;
                if error != RETRY || attempt == 2 {
                    return Err(error);
                }
            }
        }
    }
    Err(RETRY)
}
