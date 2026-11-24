//! Ordinary dashboard polling never takes the execution owner lock.
use super::*;
use crate::browser_inventory::Browser;

pub(crate) async fn tool_readiness(
    connection: &mut PgConnection,
    browser: Browser,
    settings: &Settings,
) -> Result<Value> {
    let mut inventory = browser.inventory();
    if browser != Browser::Brave || inventory["installed"] != true {
        return Ok(inventory);
    }
    let saved: Value = sqlx::query_scalar(include_str!("../../sql/browser_tool_readiness.sql"))
        .fetch_one(connection)
        .await
        .map_err(db)?;
    describe_native_profile(
        &mut inventory,
        &saved,
        settings.native_enabled && settings.commands_enabled,
    )?;
    Ok(inventory)
}

fn describe_native_profile(
    inventory: &mut Value,
    saved: &Value,
    channel_enabled: bool,
) -> Result<()> {
    let selection = &saved["selection"]["profile_binding_id"];
    let pin = &saved["pin"];
    let profile = &saved["profile"];
    if !selection
        .as_str()
        .is_some_and(|id| id.parse::<Uuid>().is_ok())
        || pin["profile_binding_id"] != *selection
        || pin["browser"] != "brave"
        || pin["verified_via"] != "owner_reviewed_dedicated_brave_profile"
        || profile["id"] != *selection
    {
        return Ok(());
    }
    let now = timestamp(&saved["at"])?;
    let connected = online(profile, now)?;
    let account = &saved["account"];
    let account_bound = account["profile_binding_id"] == *selection && account["approved"] == true;
    let commands_enabled = channel_enabled && profile["commands_enabled"] == true;
    inventory["native_profile"] = json!({
        "connected": connected,
        "account_bound": account_bound,
        "commands_enabled": commands_enabled,
    });
    inventory["blocker"] = json!(if profile["window_id"].is_null()
        && heartbeat_current(profile, now)?
    {
        "selected_browser_profile_window_missing"
    } else if !connected {
        "selected_browser_profile_offline"
    } else if !account_bound {
        "naukri_account_binding_required"
    } else if !commands_enabled {
        "selected_browser_profile_commands_disabled"
    } else {
        "fresh_browser_operation_validation_required"
    });
    Ok(())
}

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

#[cfg(test)]
mod tests {
    use super::*;

    const BINDING: &str = "98cf4ce0-519a-48f5-a490-a161a400e523";

    fn saved() -> Value {
        json!({
            "at": "2026-11-23T12:00:00Z",
            "selection": {"profile_binding_id": BINDING},
            "pin": {"profile_binding_id": BINDING, "browser": "brave",
                    "verified_via": "owner_reviewed_dedicated_brave_profile"},
            "profile": {"id": BINDING, "connected": true, "commands_enabled": true,
                        "window_id": 7, "last_heartbeat": "2026-11-23T11:59:50Z"},
            "account": {"profile_binding_id": BINDING, "approved": true, "account_sha256": "private"},
        })
    }

    #[test]
    fn tool_readiness_reports_bound_profile_without_granting_dispatch() {
        let mut inventory = Browser::Brave.inventory();
        describe_native_profile(&mut inventory, &saved(), false).unwrap();
        assert_eq!(
            inventory["blocker"],
            "selected_browser_profile_commands_disabled"
        );
        assert_eq!(
            inventory["native_profile"],
            json!({"connected":true,"account_bound":true,"commands_enabled":false})
        );
        describe_native_profile(&mut inventory, &saved(), true).unwrap();
        assert_eq!(
            inventory["blocker"],
            "fresh_browser_operation_validation_required"
        );
        assert_eq!(inventory["native_profile"]["commands_enabled"], true);
        assert_eq!(inventory["application_dispatch"], false);
        assert_eq!(inventory["ready"], false);
        assert!(!inventory.to_string().contains(BINDING));
        assert!(!inventory.to_string().contains("private"));
    }

    #[test]
    fn tool_readiness_requires_matching_account_and_current_browser() {
        let mut inventory = Browser::Brave.inventory();
        let mut evidence = saved();
        evidence["account"]["profile_binding_id"] = json!(Uuid::nil());
        describe_native_profile(&mut inventory, &evidence, true).unwrap();
        assert_eq!(inventory["blocker"], "naukri_account_binding_required");
        assert_eq!(inventory["native_profile"]["account_bound"], false);
        evidence["profile"]["last_heartbeat"] = json!("2026-11-23T11:58:20Z");
        describe_native_profile(&mut inventory, &evidence, true).unwrap();
        assert_eq!(inventory["blocker"], "selected_browser_profile_offline");
        assert_eq!(inventory["native_profile"]["connected"], false);
    }

    #[test]
    fn tool_readiness_does_not_claim_another_browsers_pin() {
        let mut inventory = Browser::Brave.inventory();
        let before = inventory.clone();
        let mut evidence = saved();
        evidence["pin"]["browser"] = json!("chrome");
        describe_native_profile(&mut inventory, &evidence, true).unwrap();
        assert_eq!(inventory, before);
    }

    #[test]
    fn tool_readiness_distinguishes_windowless_from_stale_or_disconnected() {
        let mut inventory = Browser::Brave.inventory();
        let mut evidence = saved();
        evidence["profile"]["window_id"] = Value::Null;
        describe_native_profile(&mut inventory, &evidence, true).unwrap();
        assert_eq!(
            inventory["blocker"],
            "selected_browser_profile_window_missing"
        );
        assert_eq!(inventory["native_profile"]["connected"], false);
        assert_eq!(inventory["application_dispatch"], false);
        assert_eq!(inventory["ready"], false);

        for heartbeat in ["2026-11-23T11:58:20Z", "2026-11-23T12:01:00Z"] {
            evidence["profile"]["last_heartbeat"] = json!(heartbeat);
            describe_native_profile(&mut inventory, &evidence, true).unwrap();
            assert_eq!(inventory["blocker"], "selected_browser_profile_offline");
        }
        evidence["profile"]["last_heartbeat"] = saved()["profile"]["last_heartbeat"].clone();
        evidence["profile"]["connected"] = json!(false);
        describe_native_profile(&mut inventory, &evidence, true).unwrap();
        assert_eq!(inventory["blocker"], "selected_browser_profile_offline");
    }
}
