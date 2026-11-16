//! Private-owner browser commands enqueue existing inactive-profile work; chat grants no fill approval.
use super::*;
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Command {
    Status,
    Action {
        action: String,
        packet: Uuid,
        revision: i64,
    },
    Help,
}
impl Command {
    pub fn mutates(&self) -> bool {
        matches!(self, Self::Action { .. })
    }
}
pub fn parse(text: &str, bot: &str) -> Option<Command> {
    let words = text
        .split(crate::context_contract::python_space)
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>();
    let first = *words.first()?;
    let (name, mention) = first
        .split_once('@')
        .map(|(a, b)| (a, Some(b)))
        .unwrap_or((first, None));
    if !matches!(name, "/chrome" | "/browser") {
        return None;
    }
    if text.chars().count() > 2048 || mention.is_some_and(|s| !s.eq_ignore_ascii_case(bot)) {
        return Some(Command::Help);
    }
    Some(match &words[1..] {
        ["status"] => Command::Status,
        [action, packet, revision]
            if matches!(*action, "open" | "prepare" | "pause" | "resume" | "cancel") =>
        {
            match (packet.parse::<Uuid>(), revision.parse::<i64>()) {
                (Ok(packet), Ok(revision)) if revision > 0 => Command::Action {
                    action: (*action).into(),
                    packet,
                    revision,
                },
                _ => Command::Help,
            }
        }
        _ => Command::Help,
    })
}
async fn execute_in(
    tx: &mut Transaction<'_, Postgres>,
    command: &Command,
    config: &crate::configuration::Configuration,
    update: i64,
    chat: i64,
) -> Result<String> {
    if matches!(command, Command::Help) {
        return Ok("Use /browser status or /browser open|prepare|pause|resume|cancel <packet UUID> <packet revision>. /chrome remains an alias. Filling requires fresh inspection and separate exact-field approval in the extension.".into());
    }
    let snapshot = status::snapshot(tx, &config.browser_profiles).await?;
    let data = snapshot.data;
    let selected = data["profiles"]
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .find(|p| p["selected"] == true);
    match command {
        Command::Status => {
            let mut lines = vec![if let Some(profile) = selected {
                format!(
                    "Selected browser: {} · {}",
                    string(profile, "label")?,
                    string(profile, "status")?
                )
            } else {
                "PROFILE_OFFLINE: no selected ordinary browser profile.".into()
            }];
            let recent = data["commands"]
                .as_array()
                .ok_or_else(invalid)?
                .iter()
                .filter(|c| c["actor"] == "telegram")
                .collect::<Vec<_>>();
            for command in recent.into_iter().rev().take(3) {
                lines.push(format!(
                    "{}: {} · {} · {}",
                    string(command, "id")?,
                    string(command, "action")?,
                    string(command, "state")?,
                    command["reason"]
                        .as_str()
                        .unwrap_or("no fill or submission requested")
                ));
            }
            if let Some(profile) = selected {
                let tasks:Vec<Value>=sqlx::query_scalar("SELECT value FROM owner_preferences WHERE starts_with(key,'ext_task:') AND value->'profile_binding_id'=$1 ORDER BY created_at DESC,key LIMIT 5").bind(&profile["id"]).fetch_all(&mut **tx).await.map_err(db)?;
                for task in tasks {
                    lines.push(format!("Packet {} r{}: {}; fresh field review is separate; submission unconfirmed.",string(&task,"application_id")?,number(&task,"packet_revision")?,string(&task,"state")?));
                }
            }
            Ok(lines.join("\n"))
        }
        Command::Action {
            action,
            packet,
            revision,
        } => {
            let profile = selected
                .filter(|p| p["status"] == "CONNECTED")
                .ok_or(Failure("PROFILE_OFFLINE"))?;
            let task = tasks::by_application(tx, *packet).await?;
            let nonce = Uuid::new_v5(
                &Uuid::NAMESPACE_URL,
                format!("chrome:telegram:{chat}:{update}").as_bytes(),
            );
            let request = commands::request(
                json!({"request_id":nonce,"profile_binding_id":profile["id"],"selection_version":data["selection"]["version"],"expected_profile_version":profile["version"],"application_id":packet,"packet_revision":revision,"action":action,"task_id":task["id"],"expected_task_version":task["version"]}),
            )?;
            let queued = commands::enqueue_actor(
                tx,
                &request,
                &config.browser_profiles,
                &config.packets,
                snapshot.now,
                "telegram",
            )
            .await?;
            Ok(format!(
                "Browser command {}: {} in {}. Use /browser status for its execution record. Fresh field approval remains separate; no submission requested.",
                string(&queued, "id")?,
                string(&queued, "state")?,
                string(profile, "label")?
            ))
        }
        Command::Help => unreachable!(),
    }
}
pub(crate) async fn dispatch_in(
    tx: &mut Transaction<'_, Postgres>,
    command: &Command,
    config: &crate::configuration::Configuration,
    update: i64,
    chat: i64,
) -> Result<String> {
    let mut savepoint = sqlx::Connection::begin(&mut **tx).await.map_err(db)?;
    let reply = match execute_in(&mut savepoint, command, config, update, chat).await {
        Ok(reply) => {
            savepoint.commit().await.map_err(db)?;
            reply
        }
        Err(error) => {
            savepoint
                .rollback()
                .await
                .map_err(|_| Failure("browser_profile_rollback_unconfirmed"))?;
            if tasks::owner_denial(error)
                || form_service::domain_denial(error)
                || matches!(
                    error.0,
                    "command_id_conflict"
                        | "PROFILE_COMMANDS_DISABLED"
                        | "profile_queue_full"
                        | "PROFILE_SELECTION_CONFLICT"
                        | "PROFILE_REVISION_CONFLICT"
                        | "invalid_browser_profile_request"
                )
            {
                format!(
                    "Browser command paused: {}. Review the selected profile and exact packet revision; no browser fallback.",
                    error.0
                )
            } else {
                return Err(error);
            }
        }
    };
    let mut used = 0;
    Ok(reply
        .chars()
        .take_while(|c| {
            used += c.len_utf16();
            used <= 3400
        })
        .collect())
}
