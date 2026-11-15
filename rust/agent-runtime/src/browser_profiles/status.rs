//! Ordinary dashboard polling never takes the execution owner lock.
use super::*;
pub(super) struct Snapshot {
    pub data: Value,
    pub offline: Vec<Value>,
    pub expired: bool,
    pub now: DateTime<Utc>,
}
pub(super) async fn snapshot(
    tx: &mut Transaction<'_, Postgres>,
    settings: &Settings,
) -> Result<Snapshot> {
    let value: Value = sqlx::query_scalar(include_str!("../../sql/browser_profile_status.sql"))
        .fetch_one(&mut **tx)
        .await
        .map_err(db)?;
    let now = timestamp(&value["at"])?;
    let selection = &value["selection"];
    number(selection, "version")?;
    if !selection["profile_binding_id"].is_null() {
        string(selection, "profile_binding_id")?
            .parse::<Uuid>()
            .map_err(|_| invalid())?;
    }
    let profiles = value["profiles"].as_array().ok_or_else(invalid)?;
    let tasks = value["active_tasks"].as_array().ok_or_else(invalid)?;
    let commands = value["active_commands"].as_array().ok_or_else(invalid)?;
    if profiles.len() > 8 || tasks.len() > 10000 || commands.len() > 10000 {
        return Err(Failure("browser_profile_inventory_limit"));
    }
    let offline = profiles
        .iter()
        .filter_map(|p| match online(p, now) {
            Err(e) => Some(Err(e)),
            Ok(false)
                if tasks.contains(&p["id"])
                    || commands.iter().any(|v| v["profile_binding_id"] == p["id"]) =>
            {
                Some(Ok(p["id"].clone()))
            }
            _ => None,
        })
        .collect::<Result<Vec<_>>>()?;
    let mut expired = false;
    for command in commands {
        expired |= timestamp(&command["expires_at"])? <= now;
    }
    let profiles = profiles
        .iter()
        .map(|p| public(p, &selection["profile_binding_id"], now))
        .collect::<Result<Vec<_>>>()?;
    Ok(Snapshot {
        data: json!({"selection":selection,"profiles":profiles,"commands":value["commands"],"receipts":value["receipts"],"channel_available":settings.commands_enabled}),
        offline,
        expired,
        now,
    })
}
