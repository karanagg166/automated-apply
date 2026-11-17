//! One authenticated native gesture and its replay record commit together.
use super::*;

type Operation = (String, String, String, Option<Value>);

async fn existing(tx: &mut Transaction<'_, Postgres>, key: &str) -> Result<Option<Operation>> {
    sqlx::query_as(
        "SELECT actor,command,payload_hash,CASE WHEN octet_length(result::text) <= 8192 THEN result END
         FROM agent_operations WHERE key=$1",
    ).bind(key).fetch_optional(&mut **tx).await.map_err(db)
}

fn replay(command: &native::Command, result: Value) -> Result<Value> {
    let correlation = result["correlation_id"]
        .as_str()
        .and_then(|id| id.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    if result["request_id"] != json!(command.request_id)
        || result["version"] != 1
        || result["capability"] != "preview_only"
    {
        return Err(invalid());
    }
    let data = match result["ok"].as_bool() {
        Some(true) if result["error_code"].is_null() => {
            crate::platform_sessions::observation_payload(&result["data"])?
        }
        Some(false) if result["error_code"] == "unsupported_platform_observation" => json!({}),
        _ => return Err(invalid()),
    };
    Ok(
        json!({"version":1,"request_id":command.request_id,"correlation_id":correlation,
        "ok":result["ok"],"error_code":result["error_code"],"capability":"preview_only","data":data}),
    )
}

pub(super) async fn dispatch(
    tx: &mut Transaction<'_, Postgres>,
    command: &native::Command,
    settings: &Settings,
    now: DateTime<Utc>,
) -> Result<Value> {
    let Some(extension) = settings
        .extension
        .as_deref()
        .filter(|_| settings.native_enabled)
    else {
        return Ok(native::result(
            command,
            Err(Failure("extension_identity_required")),
        ));
    };
    let actor = format!("chrome:{extension}");
    let key = format!("{actor}:{}", command.request_id);
    let name = command.name();
    let hash = &command.payload_hash;
    if let Some((old_actor, old_name, old_hash, previous)) = existing(tx, &key).await? {
        if old_actor != actor || old_name != name || &old_hash != hash {
            let mut result = native::result(command, Err(Failure("request_id_conflict")));
            result["capability"] = json!("denied");
            return Ok(result);
        }
        return replay(command, previous.ok_or_else(invalid)?);
    }
    let (observation, result) = match crate::platform_sessions::observe(
        tx,
        command.value["url"].as_str(),
        command.value["observation"].as_str(),
        now,
    )
    .await
    {
        Ok((key, value, data)) => (Some((key, value)), native::result(command, Ok(data))),
        Err(error) if error.0 == "unsupported_platform_observation" => {
            (None, native::result(command, Err(error)))
        }
        Err(error) => return Err(error),
    };
    let target = (actor, name.to_owned(), hash.clone(), Some(result.clone()));
    let saved: Option<Operation> = sqlx::query_as(
        "INSERT INTO agent_operations(key,actor,command,payload_hash,result) VALUES($1,$2,$3,$4,$5)
         ON CONFLICT(key) DO NOTHING RETURNING actor,command,payload_hash,result",
    )
    .bind(&key)
    .bind(&target.0)
    .bind(name)
    .bind(hash)
    .bind(&result)
    .fetch_optional(&mut **tx)
    .await
    .map_err(db)?;
    if saved.as_ref() != Some(&target) || existing(tx, &key).await?.as_ref() != Some(&target) {
        return Err(Failure("platform_session_write_ack_failed"));
    }
    if let Some((key, value)) = observation {
        crate::platform_sessions::verify_saved(tx, &key, &value).await?;
    }
    Ok(result)
}
