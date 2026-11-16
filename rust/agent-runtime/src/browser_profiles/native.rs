use super::*;
// Contains credentials: deliberately no Debug or serializer.
pub struct Command {
    pub(super) value: Value,
    pub request_id: Uuid,
    pub(super) payload_hash: String,
}
impl Command {
    pub fn parse(bytes: &[u8]) -> Result<Self> {
        let (value, payload_hash) = native_contract::parse(bytes)?;
        let request_id = value["request_id"]
            .as_str()
            .and_then(|s| s.parse().ok())
            .ok_or_else(request_error)?;
        Ok(Self {
            value,
            request_id,
            payload_hash,
        })
    }
    pub(super) fn name(&self) -> &str {
        self.value["command"].as_str().unwrap()
    }
    pub(super) fn id(&self, key: &str) -> Result<Uuid> {
        self.value[key]
            .as_str()
            .and_then(|s| s.parse().ok())
            .ok_or(Failure("profile_connection_fields_required"))
    }
}
pub(super) fn result(command: &Command, result: Result<Value>) -> Value {
    let capability = if matches!(
        command.name(),
        "inspect_form" | "prepare_form_answers" | "authorize_form" | "record_form_fill"
    ) {
        "form_fill"
    } else if matches!(
        command.name(),
        "open_application_task"
            | "get_application_task"
            | "update_application_task"
            | "ask_form_questions"
    ) {
        "extension_task"
    } else {
        "chrome_profile"
    };
    match result {
        Ok(mut data) => {
            data["submitted"] = json!(false);
            json!({"version":1,"request_id":command.request_id,"correlation_id":Uuid::new_v4(),"ok":true,"capability":capability,"error_code":null,"data":data})
        }
        Err(error) => {
            json!({"version":1,"request_id":command.request_id,"correlation_id":Uuid::new_v4(),"ok":false,"capability":capability,"error_code":error.0,"data":{}})
        }
    }
}
pub(super) fn static_read(name: &str) -> Option<Value> {
    match name {
        "health" => Some(
            json!({"connections":[{"name":"Supabase PostgreSQL","state":"CONNECTED"},{"name":"Local FastAPI","state":"CONNECTED"}],"runtime":"rust","browser_dispatch_available":false}),
        ),
        "get_agent_capabilities" => Some(
            json!({"operations":{"connect_chrome_profile":"chrome_profile","heartbeat_chrome_profile":"chrome_profile","disconnect_chrome_profile":"chrome_profile"},"submissions":false,"email_sending":false,"paid_calls":false}),
        ),
        _ => None,
    }
}
pub(super) async fn authenticate(
    tx: &mut Transaction<'_, Postgres>,
    command: &Command,
) -> Result<Value> {
    let profile = command
        .id("profile_binding_id")
        .map_err(|_| Failure("PROFILE_OFFLINE"))?;
    let row = get(tx, &format!("chr_prof:{profile}"))
        .await?
        .ok_or(Failure("PROFILE_OFFLINE"))?;
    let secret = command.value["profile_secret"]
        .as_str()
        .ok_or(Failure("PROFILE_OFFLINE"))?;
    let hash = format!("{:x}", Sha256::digest(secret.as_bytes()));
    if !bool::from(
        string(&row, "secret_hash")?
            .as_bytes()
            .ct_eq(hash.as_bytes()),
    ) {
        return Err(Failure("PROFILE_OFFLINE"));
    }
    Ok(row)
}
pub(super) async fn dispatch(
    tx: &mut Transaction<'_, Postgres>,
    command: &Command,
    settings: &Settings,
    packets: &crate::packet_service::Settings,
    forms: Option<form_service::Services<'_>>,
    now: DateTime<Utc>,
) -> Result<Value> {
    let outcome = execute(tx, command, settings, packets, forms, now).await;
    match outcome {
        Err(e)
            if !tasks::domain_denial(e)
                && !form_service::domain_denial(e)
                && !matches!(
                    e.0,
                    "profile_connection_fields_required"
                        | "PROFILE_OFFLINE"
                        | "profile_identity_conflict"
                        | "profile_limit_reached"
                        | "PROFILE_SESSION_CHANGED"
                        | "PROFILE_REVISION_CONFLICT"
                        | "browser_command_execution_unavailable"
                        | "PROFILE_NOT_SELECTED"
                        | "PROFILE_COMMANDS_DISABLED"
                        | "profile_command_revision_conflict"
                        | "profile_command_expired"
                        | "extension_task_context_stale"
                        | "packet_not_found"
                        | "stale_or_unreviewed_candidate_context"
                        | "application_not_eligible"
                        | "naukri_automation_stopped"
                        | "naukri_automation_paused"
                        | "execution_mode_off"
                        | "unverified_application_destination"
                        | "unsupported_form_adapter"
                        | "platform_fill_policy_denied"
                ) =>
        {
            Err(e)
        }
        other => Ok(result(command, other)),
    }
}
async fn execute(
    tx: &mut Transaction<'_, Postgres>,
    command: &Command,
    settings: &Settings,
    packets: &crate::packet_service::Settings,
    forms: Option<form_service::Services<'_>>,
    now: DateTime<Utc>,
) -> Result<Value> {
    let v = &command.value;
    match command.name() {
        "inspect_form" | "prepare_form_answers" | "authorize_form" | "record_form_fill" => {
            form_service::dispatch(
                tx,
                command,
                settings,
                packets,
                forms.ok_or(Failure("browser_form_inspection_unavailable"))?,
                now,
            )
            .await
        }
        "open_application_task"
        | "get_application_task"
        | "update_application_task"
        | "ask_form_questions" => tasks::dispatch(tx, command, settings, packets, forms, now).await,
        "poll_chrome_command" | "start_chrome_command" | "ack_chrome_command" => {
            commands::dispatch(tx, command, settings, packets, now).await
        }
        "connect_chrome_profile" => {
            let id = command.id("profile_binding_id")?;
            let session = command.id("browser_session_id")?;
            let secret = v["profile_secret"]
                .as_str()
                .ok_or(Failure("profile_connection_fields_required"))?;
            let label = v["profile_label"]
                .as_str()
                .ok_or(Failure("profile_connection_fields_required"))?;
            let window = v["window_id"]
                .as_i64()
                .ok_or(Failure("profile_connection_fields_required"))?;
            let hash = format!("{:x}", Sha256::digest(secret.as_bytes()));
            let key = format!("chr_prof:{id}");
            let old = get(tx, &key).await?;
            if let Some(row) = old.as_ref() {
                if !bool::from(
                    string(row, "secret_hash")?
                        .as_bytes()
                        .ct_eq(hash.as_bytes()),
                ) {
                    return Err(Failure("profile_identity_conflict"));
                }
                if row["browser_session_id"] != json!(session) || row["window_id"] != window {
                    invalidation::session_replaced(
                        tx,
                        row,
                        row["browser_session_id"] == json!(session),
                        now,
                        settings,
                    )
                    .await?;
                }
            } else if prefix(tx, "chr_prof:").await?.len() >= 8 {
                return Err(Failure("profile_limit_reached"));
            }
            invalidation::invalidate(tx, &json!(id), "profile_reconnected", now).await?;
            let version = old
                .as_ref()
                .map(|r| number(r, "version"))
                .transpose()?
                .unwrap_or(0)
                .checked_add(1)
                .ok_or_else(invalid)?;
            let row = json!({"id":id,"owner":"primary","native_host":"com.automated_apply.agent","secret_hash":hash,"label":label,"version":version,"connected":true,"browser_session_id":session,"window_id":window,"commands_enabled":false,"last_heartbeat":now.to_rfc3339()});
            put(tx, &key, &row).await?;
            Ok(json!({"profile":public(&row,&selection(tx).await?["profile_binding_id"],now)?}))
        }
        "heartbeat_chrome_profile" => {
            let mut row = authenticate(tx, command).await?;
            if row["connected"] != true {
                return Err(Failure("PROFILE_OFFLINE"));
            }
            let session = command
                .id("browser_session_id")
                .map_err(|_| Failure("PROFILE_SESSION_CHANGED"))?;
            let changed = row["browser_session_id"] != json!(session);
            let window_changed = row["window_id"] != v["window_id"];
            let enabled = v["profile_commands_enabled"] == true && settings.commands_enabled;
            if changed || row["commands_enabled"] == true && !enabled {
                invalidation::invalidate(
                    tx,
                    &row["id"],
                    if changed {
                        "browser_restart"
                    } else {
                        "profile_commands_disabled"
                    },
                    now,
                )
                .await?;
            }
            if changed || window_changed {
                invalidation::session_replaced(tx, &row, !changed, now, settings).await?;
            }
            if changed {
                for (key, mut task) in active_tasks(tx, &row["id"]).await? {
                    if task["profile_binding_id"] != row["id"] || task_terminal(&task) {
                        continue;
                    }
                    let reason = task["reason"]
                        .as_str()
                        .unwrap_or("browser_restart")
                        .to_owned();
                    task["browser_session_id"] = json!(session);
                    task["tab_id"] = Value::Null;
                    task["window_id"] = v["window_id"].clone();
                    task["tab_active"] = json!(false);
                    task["network_guard_active"] = json!(false);
                    task["plan_id"] = Value::Null;
                    task["authorization_id"] = Value::Null;
                    task["browser_connection"] = json!("disconnected");
                    if !task["counts"].is_object() {
                        return Err(invalid());
                    }
                    for key in ["completed", "ready", "existing"] {
                        task["counts"][key] = json!(0);
                    }
                    invalidation::move_task(tx, &key, task, &reason, now).await?;
                }
            }
            let increment = changed || window_changed || row["commands_enabled"] != json!(enabled);
            row["version"] = json!(
                number(&row, "version")?
                    .checked_add(i64::from(increment))
                    .ok_or_else(invalid)?
            );
            row["browser_session_id"] = json!(session);
            row["window_id"] = v["window_id"].clone();
            row["last_heartbeat"] = json!(now.to_rfc3339());
            row["commands_enabled"] = json!(enabled);
            put(tx, &format!("chr_prof:{}", string(&row, "id")?), &row).await?;
            let mut data =
                json!({"profile":public(&row,&selection(tx).await?["profile_binding_id"],now)?});
            // Actual Brave focus acceptance suspended automatic window creation.
            if v["window_id"].is_null() {
                data["background_window_allowed"] = json!(false);
            }
            Ok(data)
        }
        "disconnect_chrome_profile" => {
            authenticate(tx, command).await?;
            disconnect(
                tx,
                command.id("profile_binding_id")?,
                v["expected_profile_version"].as_i64().unwrap_or(0),
                now,
            )
            .await
        }
        "health" | "get_agent_capabilities" => {
            static_read(command.name()).ok_or(Failure("browser_command_execution_unavailable"))
        }
        _ => Err(Failure("browser_command_execution_unavailable")),
    }
}
