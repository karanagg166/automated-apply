//! Bounded legacy private-owner commands. Preview never fetches; reset only clears selection memory.
use crate::{Failure, Result, configuration::Configuration};
use chrono::{DateTime, Duration, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Command {
    Status,
    Connections,
    Jobs,
    Preview(String),
    Conversation(Box<crate::conversation::intent::Intent>),
    Reset,
    Help,
}
impl Command {
    pub fn mutates(&self) -> bool {
        matches!(self, Self::Preview(_) | Self::Reset | Self::Conversation(_))
    }
    fn operation(&self) -> &'static str {
        match self {
            Self::Status => "health",
            Self::Connections => "connection_status",
            Self::Jobs => "get_discovery_status",
            Self::Preview(_) => "preview_application_url",
            Self::Reset | Self::Conversation(_) => "conversation",
            Self::Help => unreachable!(),
        }
    }
}
pub(crate) fn natural(text: &str) -> Option<Command> {
    if text.trim_start().starts_with('/') || text.len() > 8192 {
        return None;
    }
    let intent = crate::conversation::intent::deterministic(text);
    (intent.category != "UNKNOWN").then(|| Command::Conversation(Box::new(intent)))
}
pub fn parse(text: &str, bot: &str) -> Option<Command> {
    let mut words = text
        .split(crate::context_contract::python_space)
        .filter(|s| !s.is_empty());
    let first = words.next()?;
    let (name, mention) = first
        .split_once('@')
        .map(|(a, b)| (a, Some(b)))
        .unwrap_or((first, None));
    if !matches!(
        name,
        "/status" | "/connections" | "/jobs" | "/apply" | "/reset" | "/start"
    ) {
        return None;
    }
    if text.chars().count() > 2048 || mention.is_some_and(|s| !s.eq_ignore_ascii_case(bot)) {
        return Some(Command::Help);
    }
    let args = words.collect::<Vec<_>>();
    Some(match (name, args.as_slice()) {
        ("/status", []) => Command::Status,
        ("/connections", []) => Command::Connections,
        ("/jobs", []) => Command::Jobs,
        ("/reset", []) => Command::Reset,
        ("/apply", [url]) => crate::resources::public_https(url)
            .map(Command::Preview)
            .unwrap_or(Command::Help),
        // Legacy /start pairing-looking arguments only showed help; they granted no identity.
        ("/start", []) => Command::Help,
        ("/start", [code])
            if code.strip_prefix("aa_").is_some_and(|s| {
                s.len() == 24
                    && s.bytes()
                        .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
            }) =>
        {
            Command::Help
        }
        _ => Command::Help,
    })
}
pub fn context_key(owner: i64) -> String {
    format!(
        "telegram_context_{}",
        &format!("{:x}", Sha256::digest(owner.to_string().as_bytes()))[..24]
    )
}
fn db(_: sqlx::Error) -> Failure {
    Failure("telegram_local_database_error")
}
fn invalid() -> Failure {
    Failure("invalid_telegram_local_record")
}
async fn put(tx: &mut Transaction<'_, Postgres>, key: &str, value: &Value) -> Result<()> {
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES($1,$2,clock_timestamp(),clock_timestamp()) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=clock_timestamp() RETURNING value").bind(key).bind(value).fetch_optional(&mut **tx).await.map_err(db)?;
    if saved.as_ref() != Some(value) {
        return Err(Failure("telegram_local_write_ack_failed"));
    }
    Ok(())
}
pub(crate) async fn connections_in(
    tx: &mut Transaction<'_, Postgres>,
    config: &Configuration,
    now: DateTime<Utc>,
) -> Result<Value> {
    let mut rows = vec![
        json!({"name":"PostgreSQL","state":"current_query_succeeded","last_verification_time":now}),
        json!({"name":"Rust API","state":"not_probed_by_telegram","last_verification_time":null}),
        json!({"name":"Telegram owner","state":"current_private_update_authenticated","last_verification_time":now}),
    ];
    // Metadata projection only: no token envelopes, email identities or cached mail content.
    let mail:Vec<(String,Value)>=sqlx::query_as("SELECT key,jsonb_build_object('status',value->'status','expires_at',value->'expires_at','last_verified_at',value->'last_verified_at') FROM owner_preferences WHERE key IN ('gm54_account:1','gm54_account:2') ORDER BY key").fetch_all(&mut **tx).await.map_err(db)?;
    for slot in 1..=config.mailboxes.configured_slots() {
        let key = format!("gm54_account:{slot}");
        let value = mail.iter().find(|(k, _)| k == &key).map(|(_, v)| v);
        rows.push(json!({"name":format!("Gmail slot {slot}"),"state":value.and_then(|v|v["status"].as_str()).unwrap_or("not_connected"),"evidence":"saved_not_live_checked","last_verification_time":value.and_then(|v|v.get("last_verified_at")),"send":false}));
    }
    let profiles = crate::browser_profiles::telegram_commands::dispatch_in(
        tx,
        &crate::browser_profiles::telegram_commands::Command::Status,
        config,
        0,
        0,
    )
    .await?;
    rows.push(json!({"name":"Selected browser","state":profiles.lines().next().unwrap_or("PROFILE_OFFLINE"),"evidence":"saved_profile_heartbeat","last_verification_time":null}));
    for portal in crate::platform_sessions::listing(tx).await? {
        rows.push(json!({"name":portal["name"],"state":portal["state"],"evidence":"saved_indicator_only_identity_unverified","last_verification_time":portal["last_verification_time"]}));
    }
    Ok(json!({"connections":rows,"provider_checks_executed":false,"submitted":false}))
}
async fn execute_in(
    tx: &mut Transaction<'_, Postgres>,
    command: &Command,
    config: &Configuration,
    owner: i64,
    now: DateTime<Utc>,
) -> Result<Value> {
    match command {
        Command::Status => {
            let control = crate::lifecycle::control(tx).await?;
            Ok(
                json!({"connections":[{"name":"PostgreSQL","state":"current_query_succeeded"},{"name":"Rust API","state":"not_probed_by_telegram"}],"worker_online":control.worker_online,"mode":control.mode,"submitted":false}),
            )
        }
        Command::Connections => connections_in(tx, config, now).await,
        Command::Jobs => {
            let schedule: Option<bool> =
                sqlx::query_scalar("SELECT enabled FROM automation_schedule WHERE key='primary'")
                    .fetch_optional(&mut **tx)
                    .await
                    .map_err(db)?;
            let latest:Option<Value>=sqlx::query_scalar("SELECT jsonb_build_object('id',id,'status',CASE WHEN status='running' AND started_at< $1::timestamptz-($2::double precision*interval '1 second') THEN 'recovery_required' ELSE status END,'job_count',CASE WHEN jsonb_typeof(query_summary::jsonb->'job_ids')='array' THEN jsonb_array_length(query_summary::jsonb->'job_ids') ELSE 0 END) FROM discovery_runs ORDER BY started_at DESC,id LIMIT 1").bind(now).bind(config.discovery_timeout_seconds+120.0).fetch_optional(&mut **tx).await.map_err(db)?;
            let public = crate::discovery_schedule::policy(tx).await?;
            Ok(
                json!({"deployment_enabled":config.legacy_discovery_enabled,"schedule_enabled":schedule.unwrap_or(false),"public_feed_schedule":public,"latest":latest,"discovery_executed":false,"submitted":false}),
            )
        }
        Command::Preview(url) => crate::owner_commands::preview_application_url(tx, url).await,
        Command::Conversation(intent) => {
            crate::conversation::reply::respond(tx, config, owner, (**intent).clone(), now).await
        }
        Command::Reset => {
            let memory = json!({"conversation_id":Uuid::new_v4(),"history":[],"job_ids":[],"selected_job_id":null,"project_id":null,"clarification":null,"expires_at":now+Duration::minutes(10)});
            put(tx, &context_key(owner), &memory).await?;
            Ok(
                json!({"reply":"Previous job and project selection cleared. Start a fresh search.","status":"context_reset","conversation_id":memory["conversation_id"]}),
            )
        }
        Command::Help => unreachable!(),
    }
}
fn reply(command: &Command, result: &Value) -> Result<String> {
    let data = &result["data"];
    if result["ok"] == false {
        return Ok(format!(
            "Request denied: {}",
            result["error_code"].as_str().ok_or_else(invalid)?
        ));
    }
    Ok(match command {
        Command::Reset | Command::Conversation(_) => {
            data["reply"].as_str().ok_or_else(invalid)?.into()
        }
        Command::Preview(_) => format!(
            "URL preview saved ({}). No application submitted. Reference: {}",
            data["platform"].as_str().ok_or_else(invalid)?,
            result["correlation_id"].as_str().ok_or_else(invalid)?
        ),
        Command::Jobs => {
            let mut lines = vec![format!(
                "Discovery deployment enabled: {}; schedule enabled: {}. No discovery executed by this command.",
                data["deployment_enabled"], data["schedule_enabled"]
            )];
            if data["latest"].is_null() {
                lines.push(
                    "No saved discovery run exists; no match or suitability claim is available."
                        .into(),
                );
            } else {
                let count = data["latest"]["job_count"].as_u64().ok_or_else(invalid)?;
                lines.push(format!(
                    "Latest run {}: {}; {count} saved jobs. Suitability requires owner review.",
                    data["latest"]["id"].as_str().ok_or_else(invalid)?,
                    data["latest"]["status"].as_str().ok_or_else(invalid)?
                ));
                if count == 0 {
                    lines.push("No saved opportunities in this run. A failed or incomplete run is not a successful zero-match search.".into());
                }
            }
            lines.push(format!(
                "Saved public-feed schedule revision {}. Read-only status; no search started.",
                data["public_feed_schedule"]["revision"]
            ));
            lines.join("\n")
        }
        Command::Status | Command::Connections => {
            let mut lines = data["connections"]
                .as_array()
                .ok_or_else(invalid)?
                .iter()
                .map(|r| {
                    Ok(format!(
                        "{}: {}",
                        r["name"].as_str().ok_or_else(invalid)?,
                        r["state"].as_str().ok_or_else(invalid)?
                    ))
                })
                .collect::<Result<Vec<_>>>()?;
            if matches!(command, Command::Status) {
                lines.push(format!(
                    "Saved-review worker: {} · online={}. No application receipt asserted.",
                    data["mode"].as_str().ok_or_else(invalid)?,
                    data["worker_online"]
                ));
            } else {
                lines.push("Portal indicators and saved Gmail state do not prove current account identity or live access. No external check executed.".into());
            }
            lines.join("\n")
        }
        Command::Help => unreachable!(),
    })
}
pub(crate) async fn dispatch_in(
    tx: &mut Transaction<'_, Postgres>,
    command: &Command,
    config: &Configuration,
    owner: i64,
    chat: i64,
    update: i64,
) -> Result<String> {
    if matches!(command, Command::Help) {
        return Ok("Use /status /connections /jobs /apply <public HTTPS URL> /reset. /apply saves a URL preview only; /reset clears the bot's job/project selection. Use /agents runs for saved-review run history.".into());
    }
    let request = Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!("telegram:{chat}:{update}").as_bytes(),
    );
    let mut body = json!({"request_id":request,"command":command.operation()});
    if let Command::Preview(url) = command {
        body["url"] = json!(url);
    }
    if matches!(command, Command::Reset) {
        body["intent"] = json!({"category":"RESET_CONTEXT"});
    }
    if let Command::Conversation(intent) = command {
        body["intent"] = serde_json::to_value(intent).map_err(|_| invalid())?;
    }
    let (_, hash) = crate::browser_profiles::native_contract::parse(
        &serde_json::to_vec(&body).map_err(|_| invalid())?,
    )?;
    let key = format!("telegram:{owner}:{request}");
    let previous: Option<(String, String, String, Value)> = sqlx::query_as(
        "SELECT actor,command,payload_hash,result FROM agent_operations WHERE key=$1",
    )
    .bind(&key)
    .fetch_optional(&mut **tx)
    .await
    .map_err(db)?;
    if let Some((actor, operation, old_hash, result)) = previous {
        if actor != format!("telegram:{owner}")
            || operation != command.operation()
            || old_hash != hash
        {
            return Ok(
                "Command rejected: request_id_conflict. Retained intent is unchanged.".into(),
            );
        }
        if result["version"] != 1
            || !result["ok"].is_boolean()
            || result["request_id"] != json!(request)
            || result["correlation_id"]
                .as_str()
                .and_then(|s| s.parse::<Uuid>().ok())
                .is_none()
        {
            return Err(invalid());
        }
        return reply(command, &result).map(bounded);
    }
    if matches!(command, Command::Conversation(_)) {
        let recent: i64 = sqlx::query_scalar(
            "SELECT count(*) FROM (SELECT 1 FROM agent_operations
             WHERE actor = $1 AND created_at > clock_timestamp() - interval '1 minute'
             LIMIT 20) recent",
        )
        .bind(format!("telegram:{owner}"))
        .fetch_one(&mut **tx)
        .await
        .map_err(db)?;
        if recent >= 20 {
            return Ok("Too many requests. Please wait one minute.".into());
        }
    }
    let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut **tx)
        .await
        .map_err(db)?;
    let mut business = sqlx::Connection::begin(&mut **tx).await.map_err(db)?;
    let outcome = match execute_in(&mut business, command, config, owner, now).await {
        Ok(data) => {
            business.commit().await.map_err(db)?;
            Ok(data)
        }
        Err(error) => {
            business
                .rollback()
                .await
                .map_err(|_| Failure("telegram_local_rollback_unconfirmed"))?;
            if matches!(
                error.0,
                "connection_disabled" | "invalid_saved_platform_policy"
            ) || matches!(command, Command::Conversation(_))
                && matches!(
                    error.0,
                    "conversation_memory_review_required"
                        | "conversation_memory_saved_limit"
                        | "invalid_saved_conversation_preferences"
                        | "project_conversation_fact_review_required"
                )
            {
                Err(error)
            } else {
                return Err(error);
            }
        }
    };
    let result = match outcome {
        Ok(data) => {
            json!({"version":1,"request_id":request,"correlation_id":Uuid::new_v4(),"ok":true,"capability":if command.mutates(){"preview_only"}else{"read_only"},"error_code":null,"data":data})
        }
        Err(error) => {
            json!({"version":1,"request_id":request,"correlation_id":Uuid::new_v4(),"ok":false,"capability":"preview_only","error_code":error.0,"data":{}})
        }
    };
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO agent_operations(key,actor,command,payload_hash,result,created_at) VALUES($1,$2,$3,$4,$5,clock_timestamp()) RETURNING result").bind(&key).bind(format!("telegram:{owner}")).bind(command.operation()).bind(hash).bind(&result).fetch_optional(&mut **tx).await.map_err(db)?;
    if saved.as_ref() != Some(&result) {
        return Err(Failure("telegram_local_write_ack_failed"));
    }
    reply(command, &result).map(bounded)
}
fn bounded(response: String) -> String {
    let mut used = 0;
    response
        .chars()
        .take_while(|c| {
            used += c.len_utf16();
            used <= 3400
        })
        .collect()
}
