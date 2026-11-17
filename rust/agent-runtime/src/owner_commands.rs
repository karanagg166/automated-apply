//! Local owner commands and limited extension previews over the existing receipt ledger.
mod history;
use crate::{Failure, Result, configuration::Configuration};
use serde::Deserialize;
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection};
use uuid::Uuid;

#[derive(Clone, Copy)]
pub(crate) enum Route {
    Command,
    History,
}
impl Route {
    pub(crate) fn method(self) -> &'static str {
        match self {
            Self::Command => "POST",
            Self::History => "GET",
        }
    }
}
pub(crate) fn route(path: &str) -> Option<Route> {
    match path {
        "/api/v1/local-agent/commands" => Some(Route::Command),
        "/api/v1/local-agent/history" => Some(Route::History),
        _ => None,
    }
}

fn db(_: sqlx::Error) -> Failure {
    Failure("local_command_database_error")
}
fn invalid() -> Failure {
    Failure("invalid_local_command")
}
fn ack() -> Failure {
    Failure("local_command_write_ack_failed")
}

struct Command {
    id: Uuid,
    input: Value,
    hash: String,
}
impl Command {
    fn parse(body: &[u8]) -> Result<Self> {
        let (input, hash) =
            crate::browser_profiles::native_contract::parse(body).map_err(|_| invalid())?;
        let id = input["request_id"]
            .as_str()
            .and_then(|id| id.parse().ok())
            .ok_or_else(invalid)?;
        Ok(Self { id, input, hash })
    }
    fn name(&self) -> &str {
        self.input["command"]
            .as_str()
            .expect("validated command name")
    }
}

pub(crate) async fn dispatch(
    connection: &mut PgConnection,
    route: Route,
    method: &str,
    body: &[u8],
    config: &Configuration,
) -> Result<Value> {
    if method != route.method() {
        return Err(Failure("local_command_method_not_allowed"));
    }
    match route {
        Route::Command => record(connection, &Command::parse(body)?, "owner:primary", config).await,
        Route::History if body.is_empty() => history::listing(connection).await,
        Route::History => Err(invalid()),
    }
}

// The caller has already authenticated the extension header on its native endpoint.
pub(crate) async fn dispatch_extension(
    connection: &mut PgConnection,
    body: &[u8],
    config: &Configuration,
) -> Option<Result<Value>> {
    #[derive(Deserialize)]
    struct Name<'a> {
        #[serde(borrow)]
        command: std::borrow::Cow<'a, str>,
    }
    let header: Name<'_> = serde_json::from_slice(body).ok()?;
    if !matches!(
        header.command.as_ref(),
        "preview_application_url" | "connection_status"
    ) {
        return None;
    }
    let command = match Command::parse(body) {
        Ok(command) => command,
        Err(error) => return Some(Err(error)),
    };
    let Some(extension) = config
        .browser_profiles
        .extension
        .as_deref()
        .filter(|_| config.browser_profiles.native_enabled)
    else {
        return Some(Err(Failure("extension_identity_not_authorized")));
    };
    Some(record(connection, &command, &format!("chrome:{extension}"), config).await)
}

fn capability(name: &str) -> &'static str {
    match name {
        "health" | "connection_status" | "get_agent_capabilities" | "get_application_policy" => {
            "read_only"
        }
        "preview_application_url"
        | "preview_job_filters"
        | "get_discovery_status"
        | "conversation"
        | "observe_platform_session" => "preview_only",
        "inspect_form" | "prepare_form_answers" | "authorize_form" | "record_form_fill" => {
            "form_fill"
        }
        "open_application_task"
        | "get_application_task"
        | "update_application_task"
        | "ask_form_questions" => "extension_task",
        "naukri_queue_status" | "naukri_queue_control" => "naukri_queue_controls",
        "poll_naukri_work"
        | "bind_naukri_work"
        | "admit_naukri_work"
        | "finish_naukri_work"
        | "abandon_naukri_work"
        | "check_naukri_work" => "naukri_background_read",
        _ => "chrome_profile",
    }
}

fn result(command: &Command, capability: &str, outcome: Result<Value>) -> Value {
    let (ok, error, data) = match outcome {
        Ok(data) => (true, None, data),
        Err(error) => (false, Some(error.0), json!({})),
    };
    json!({"version":1,"request_id":command.id,"correlation_id":Uuid::new_v4(),"ok":ok,
        "capability":capability,"error_code":error,"data":data})
}

pub(crate) async fn preview_application_url(
    connection: &mut PgConnection,
    url: &str,
) -> Result<Value> {
    let url = crate::resources::public_https(url).ok_or_else(invalid)?;
    let platform = crate::browser_profiles::commands::page_kind(&url)?;
    let preference = crate::platform_policy::preference_in(connection, platform).await?;
    if preference == "disabled" {
        return Err(Failure("connection_disabled"));
    }
    Ok(
        json!({"url":url,"platform":platform,"policy":{"preference":preference,
        "preview_allowed":true,"submission_allowed":false,"email_send_allowed":false,"paid_calls_allowed":false,
        "capability":"url_preview","reason":"phase1_preview_only"},"status":"preview_saved","page_inspected":false,"submitted":false}),
    )
}

async fn execute(
    connection: &mut PgConnection,
    command: &Command,
    config: &Configuration,
) -> Result<Value> {
    match command.name() {
        "health" => {
            crate::server::readiness(connection, config).await?;
            Ok(
                json!({"connections":[{"name":"Supabase PostgreSQL","state":if config.fixture {"degraded"} else {"capability_verified"}},
                {"name":"Rust API","state":"capability_verified"}],"endpoint":format!("http://{}",config.listen())}),
            )
        }
        "connection_status" => {
            let snapshot = crate::connection_report::snapshot(connection, config).await?;
            let rows = snapshot
                .as_array()
                .ok_or(Failure("invalid_local_command_record"))?;
            let rows: Vec<_> = rows.iter().map(|row| json!({"name":row["name"],"state":row["state"],"last_verification_time":row["last_verification_time"]})).collect();
            Ok(json!({"connections":rows}))
        }
        "get_agent_capabilities" => {
            let operations: serde_json::Map<_, _> = [
                "health",
                "connection_status",
                "get_agent_capabilities",
                "get_application_policy",
                "preview_application_url",
                "preview_job_filters",
                "get_discovery_status",
                "conversation",
                "observe_platform_session",
            ]
            .into_iter()
            .map(|name| (name.to_owned(), json!(capability(name))))
            .collect();
            Ok(
                json!({"operations":operations,"submissions":false,"email_sending":false,"paid_calls":false}),
            )
        }
        "get_application_policy" => crate::platform_policy::view(connection).await,
        "preview_application_url" => {
            let url = command.input["url"]
                .as_str()
                .ok_or(Failure("url_required"))?;
            preview_application_url(connection, url).await
        }
        "preview_job_filters" => {
            let mut snapshot = connection.begin().await.map_err(db)?;
            sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                .execute(&mut *snapshot)
                .await
                .map_err(db)?;
            let preferences = crate::conversation::preferences::read(&mut snapshot).await?;
            let preset: Option<Option<Value>> = sqlx::query_scalar(
                "SELECT CASE WHEN octet_length(value::text)<=16384 THEN value END
                FROM owner_preferences WHERE key='startup_presets'",
            )
            .fetch_optional(&mut *snapshot)
            .await
            .map_err(db)?;
            let presets = match preset {
                Some(Some(value)) => json!([{"key":"startup_presets","value":value}]),
                None => json!([]),
                Some(None) => return Err(Failure("local_command_result_limit")),
            };
            snapshot.commit().await.map_err(db)?;
            Ok(json!({"preferences":preferences,"saved_presets":presets,"executed":false}))
        }
        "get_discovery_status" => {
            let ready: bool =
                sqlx::query_scalar("SELECT to_regclass('automation_schedule') IS NOT NULL")
                    .fetch_one(&mut *connection)
                    .await
                    .map_err(db)?;
            let enabled: Option<bool> = if ready {
                sqlx::query_scalar("SELECT enabled FROM automation_schedule WHERE key='primary'")
                    .fetch_optional(connection)
                    .await
                    .map_err(db)?
            } else {
                None
            };
            Ok(
                json!({"deployment_enabled":config.legacy_discovery_enabled,"schedule_enabled":enabled.unwrap_or(false),"discovery_executed":false}),
            )
        }
        "conversation" => Err(Failure("telegram_identity_required")),
        "inspect_form" | "prepare_form_answers" | "authorize_form" | "record_form_fill" => {
            Err(Failure("manual_form_not_authorized"))
        }
        _ => Err(Failure("extension_identity_required")),
    }
}

type Stored = (String, String, String, Option<Value>);
async fn lookup(connection: &mut PgConnection, key: &str) -> Result<Option<Stored>> {
    sqlx::query_as("SELECT actor,command,payload_hash,CASE WHEN octet_length(result::text)<=131072 THEN result END
         FROM agent_operations WHERE key=$1").bind(key).fetch_optional(connection).await.map_err(db)
}

fn replay(command: &Command, actor: &str, previous: Stored) -> Result<Value> {
    if previous.0 != actor || previous.1 != command.name() || previous.2 != command.hash {
        return Ok(result(
            command,
            "denied",
            Err(Failure("request_id_conflict")),
        ));
    }
    let invalid = Failure("invalid_local_command_record");
    let value = previous.3.ok_or(invalid)?;
    let ok = value["ok"].as_bool().ok_or(invalid)?;
    if value["version"] != 1
        || value["request_id"] != json!(command.id)
        || value["correlation_id"]
            .as_str()
            .and_then(|id| id.parse::<Uuid>().ok())
            .is_none()
        || value["capability"] != capability(command.name())
        || !value["data"].is_object()
        || ok != value["error_code"].is_null()
        || (!ok && !value["error_code"].is_string())
    {
        return Err(invalid);
    }
    Ok(value)
}

async fn record(
    connection: &mut PgConnection,
    command: &Command,
    actor: &str,
    config: &Configuration,
) -> Result<Value> {
    let key = format!("{actor}:{}", command.id);
    if let Some(previous) = lookup(connection, &key).await? {
        return replay(command, actor, previous);
    }
    let data = execute(connection, command, config).await;
    if let Err(error) = data.as_ref()
        && !matches!(
            error.0,
            "connection_disabled"
                | "url_required"
                | "manual_form_not_authorized"
                | "extension_identity_required"
                | "telegram_identity_required"
        )
    {
        return Err(*error);
    }
    let output = result(command, capability(command.name()), data);
    if output.to_string().len() > 120000 {
        return Err(Failure("local_command_result_limit"));
    }
    let mut tx = connection.begin().await.map_err(db)?;
    let after: Option<Stored> = sqlx::query_as(
        "INSERT INTO agent_operations(key,actor,command,payload_hash,result) VALUES($1,$2,$3,$4,$5)
         ON CONFLICT(key) DO NOTHING RETURNING actor,command,payload_hash,result",
    )
    .bind(&key)
    .bind(actor)
    .bind(command.name())
    .bind(&command.hash)
    .bind(&output)
    .fetch_optional(&mut *tx)
    .await
    .map_err(db)?;
    let retained = lookup(&mut tx, &key).await?;
    if after.is_none() {
        tx.rollback().await.map_err(db)?;
        return replay(command, actor, retained.ok_or_else(ack)?);
    }
    let expected = (
        actor.to_owned(),
        command.name().to_owned(),
        command.hash.clone(),
        Some(output.clone()),
    );
    if after.as_ref() != Some(&expected) || retained.as_ref() != Some(&expected) {
        tx.rollback().await.map_err(db)?;
        return Err(ack());
    }
    tx.commit()
        .await
        .map_err(|_| Failure("local_command_outcome_unknown"))?;
    Ok(output)
}
