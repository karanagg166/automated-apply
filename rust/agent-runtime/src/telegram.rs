//! Official Bot API transport and owner-only commands. No arbitrary method, recipient or text.
use crate::{Failure, Result, contracts::State, lifecycle::Mode};
use serde_json::{Value, json};
use std::{collections::BTreeMap, time::Duration};
use uuid::Uuid;

#[derive(Clone)]
pub struct Settings {
    token: String,
    user: i64,
    chat: i64,
    endpoint: String,
    fixture: bool,
}
impl Settings {
    pub(crate) fn owner_user(&self) -> i64 {
        self.user
    }
    pub fn from_values(values: &BTreeMap<String, String>, fixture: bool) -> Result<Option<Self>> {
        let enabled = values
            .get("RUST_TELEGRAM_ENABLED")
            .map(String::as_str)
            .unwrap_or("false");
        if matches!(enabled, "false" | "0") {
            return Ok(None);
        }
        if !matches!(enabled, "true" | "1") {
            return Err(Failure("invalid_telegram_configuration"));
        }
        let token = values
            .get("TELEGRAM_BOT_TOKEN")
            .ok_or(Failure("telegram_not_configured"))?
            .to_owned();
        let (number, secret) = token
            .split_once(':')
            .ok_or(Failure("telegram_not_configured"))?;
        if number.is_empty()
            || !number.bytes().all(|b| b.is_ascii_digit())
            || number.parse::<i64>().ok().filter(|n| *n > 0).is_none()
            || !(20..=100).contains(&secret.len())
            || !secret
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
        {
            return Err(Failure("telegram_not_configured"));
        }
        let id = |key| {
            values
                .get(key)
                .and_then(|s| s.parse::<i64>().ok())
                .filter(|n| *n > 0 && *n < (1i64 << 52))
                .ok_or(Failure("telegram_owner_binding_required"))
        };
        let mut endpoint = "https://api.telegram.org".to_owned();
        if fixture && !values.contains_key("RUST_TELEGRAM_FIXTURE_ENDPOINT") {
            return Err(Failure("telegram_fixture_endpoint_required"));
        }
        if let Some(alternate) = values.get("RUST_TELEGRAM_FIXTURE_ENDPOINT") {
            let url = reqwest::Url::parse(alternate)
                .map_err(|_| Failure("telegram_fixture_endpoint_denied"))?;
            if !fixture
                || url.scheme() != "http"
                || url.host_str() != Some("127.0.0.1")
                || url.port().is_none_or(|p| p < 1025)
                || !url.username().is_empty()
                || url.password().is_some()
                || url.path() != "/"
                || url.query().is_some()
                || url.fragment().is_some()
            {
                return Err(Failure("telegram_fixture_endpoint_denied"));
            }
            endpoint = alternate.trim_end_matches('/').to_owned();
        }
        Ok(Some(Self {
            token,
            user: id("TELEGRAM_OWNER_USER_ID")?,
            chat: id("TELEGRAM_OWNER_CHAT_ID")?,
            endpoint,
            fixture,
        }))
    }
    pub fn authorized(&self, message: &Value) -> bool {
        message
            .get("chat")
            .and_then(|c| c.get("type"))
            .and_then(Value::as_str)
            == Some("private")
            && message
                .get("chat")
                .and_then(|c| c.get("id"))
                .and_then(Value::as_i64)
                == Some(self.chat)
            && message
                .get("from")
                .and_then(|c| c.get("id"))
                .and_then(Value::as_i64)
                == Some(self.user)
            && message
                .get("from")
                .and_then(|c| c.get("is_bot"))
                .and_then(Value::as_bool)
                == Some(false)
            && ["forward_origin", "forward_date", "sender_chat"]
                .iter()
                .all(|key| message.get(key).is_none_or(Value::is_null))
    }
    pub fn binding(&self) -> String {
        use sha2::{Digest, Sha256};
        format!(
            "{:x}",
            Sha256::digest(format!(
                "{}:{}:{}",
                self.token.split(':').next().unwrap_or(""),
                self.user,
                self.chat
            ))
        )
    }
}
#[derive(Clone, Copy, PartialEq, Eq)]
pub struct Error {
    pub code: &'static str,
    pub retry_after: Duration,
}
impl Error {
    fn new(code: &'static str) -> Self {
        Self {
            code,
            retry_after: Duration::ZERO,
        }
    }
}
impl std::fmt::Debug for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("TelegramError")
            .field("code", &self.code)
            .field("retry_after", &self.retry_after)
            .finish()
    }
}
type BotResult<T> = std::result::Result<T, Error>;
pub struct Identity {
    pub id: i64,
    pub username: String,
}
pub struct Bot {
    settings: Settings,
    client: reqwest::Client,
}
pub enum Notice {
    AgentUpdate { id: Uuid },
    Help,
    Pong,
    Status { mode: Mode, online: bool },
    Run { id: Uuid, state: State },
    Unavailable,
}
impl Notice {
    pub fn text(&self) -> String {
        match self {
            Self::AgentUpdate{id}=>format!("Agent update recorded for run {id}. Check the dashboard for its current status; this message is not an application receipt."),
        Self::Help=>"/ping /status /connections /jobs /reset /apply <public HTTPS URL>. /apply saves a preview only; /reset clears bot selection context. /agents review|runs|start|pause|stop controls saved review. /naukri status|queue|find|add|apply|pause|resume|cancel|automation retains saved controls and limits; its apply command prepares saved jobs. /browser status|open|prepare|pause|resume|cancel uses the selected ordinary profile; /chrome is an alias. Field filling needs separate extension approval. Natural conversation remains in migration. These commands never click Apply.".into(),
        Self::Pong=>"pong — your authorized private message reached the Rust worker.".into(),
        Self::Status{mode,online}=>format!("Rust saved-review agents: {}; worker {}. Application dispatch remains unavailable.",match mode{Mode::Running=>"RUNNING",Mode::Paused=>"PAUSED",Mode::Stopped=>"STOPPED"},if *online{"online"}else{"offline"}),
        Self::Run{id,state}=>format!("Saved-review run {id}: {}. Workflow status is not an application receipt.",serde_json::to_value(state).unwrap().as_str().unwrap()),
        Self::Unavailable=>"Command unavailable or not migrated. Inspect the dashboard before retrying; no new action is authorized by this reply.".into(),
    }
    }
}
impl Bot {
    pub fn new(settings: Settings) -> Result<Self> {
        let client = reqwest::Client::builder()
            .no_proxy()
            .retry(reqwest::retry::never())
            .redirect(reqwest::redirect::Policy::none())
            .timeout(Duration::from_secs(40))
            .connect_timeout(Duration::from_secs(10))
            .pool_max_idle_per_host(1)
            .build()
            .map_err(|_| Failure("telegram_client_unavailable"))?;
        Ok(Self { settings, client })
    }
    async fn call(&self, method: &'static str, payload: Value) -> BotResult<Value> {
        if !matches!(
            method,
            "getMe" | "getWebhookInfo" | "getUpdates" | "sendMessage"
        ) {
            return Err(Error::new("telegram_capability_denied"));
        }
        let url = format!(
            "{}/bot{}/{method}",
            self.settings.endpoint, self.settings.token
        );
        let mut response = self
            .client
            .post(url)
            .json(&payload)
            .send()
            .await
            .map_err(|_| Error::new("telegram_network_or_response_error"))?;
        let status = response.status().as_u16();
        if response.content_length().is_some_and(|n| n > 1_048_576) {
            return Err(Error::new("telegram_response_size"));
        }
        let mut bytes = Vec::new();
        while let Some(chunk) = response
            .chunk()
            .await
            .map_err(|_| Error::new("telegram_network_or_response_error"))?
        {
            if bytes.len().saturating_add(chunk.len()) > 1_048_576 {
                return Err(Error::new("telegram_response_size"));
            }
            bytes.extend_from_slice(&chunk);
        }
        if matches!(status, 401 | 404) {
            return Err(Error::new("telegram_authentication_failed"));
        }
        let body: Value = serde_json::from_slice(&bytes)
            .map_err(|_| Error::new("telegram_network_or_response_error"))?;
        if status == 409 {
            let webhook = body
                .get("description")
                .and_then(Value::as_str)
                .is_some_and(|s| s.to_ascii_lowercase().contains("webhook"));
            return Err(Error::new(if webhook {
                "telegram_webhook_conflict_owner_approval_required"
            } else {
                "telegram_polling_conflict"
            }));
        }
        if status == 429
            && body.get("ok") == Some(&Value::Bool(false))
            && body.get("error_code").and_then(Value::as_i64) == Some(429)
        {
            let delay = body
                .get("parameters")
                .and_then(|p| p.get("retry_after"))
                .and_then(Value::as_u64)
                .filter(|n| (1..=86400).contains(n))
                .ok_or_else(|| Error::new("telegram_rate_limit_requires_reconciliation"))?;
            return Err(Error {
                code: "telegram_rate_limited",
                retry_after: Duration::from_secs(delay),
            });
        }
        if status != 200 {
            return Err(Error::new("telegram_transport_error"));
        }
        if body.get("ok") != Some(&Value::Bool(true)) {
            return Err(Error::new("telegram_api_error"));
        }
        body.get("result")
            .cloned()
            .ok_or_else(|| Error::new("telegram_network_or_response_error"))
    }
    pub async fn verify(&self) -> BotResult<Identity> {
        let me = self.call("getMe", json!({})).await?;
        let id = me
            .get("id")
            .and_then(Value::as_i64)
            .filter(|n| *n > 0)
            .ok_or_else(|| Error::new("telegram_identity_invalid"))?;
        let username = me
            .get("username")
            .and_then(Value::as_str)
            .filter(|s| {
                !s.is_empty()
                    && s.len() <= 64
                    && s.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_')
            })
            .ok_or_else(|| Error::new("telegram_identity_invalid"))?
            .to_owned();
        if me.get("is_bot") != Some(&Value::Bool(true))
            || self
                .settings
                .token
                .split(':')
                .next()
                .and_then(|s| s.parse::<i64>().ok())
                != Some(id)
        {
            return Err(Error::new("telegram_identity_invalid"));
        }
        let webhook = self.call("getWebhookInfo", json!({})).await?;
        match webhook.get("url").and_then(Value::as_str) {
            Some("") => {}
            Some(_) => {
                return Err(Error::new(
                    "telegram_webhook_conflict_owner_approval_required",
                ));
            }
            None => return Err(Error::new("telegram_webhook_status_invalid")),
        }
        Ok(Identity { id, username })
    }
    pub async fn updates(&self, offset: i64, pending: bool) -> BotResult<Vec<Value>> {
        if offset < 0 {
            return Err(Error::new("invalid_update_id"));
        }
        let value=self.call("getUpdates",json!({"offset":offset,"timeout":if pending{0}else{25},"limit":20,"allowed_updates":["message"]})).await?;
        let updates = value
            .as_array()
            .filter(|rows| rows.len() <= 20)
            .ok_or_else(|| Error::new("telegram_updates_response_invalid"))?;
        let mut previous = None;
        for update in updates {
            let id = update
                .get("update_id")
                .and_then(Value::as_i64)
                .filter(|n| *n >= 0 && *n < i64::MAX)
                .ok_or_else(|| Error::new("telegram_updates_response_invalid"))?;
            if previous.is_some_and(|p| p >= id) {
                return Err(Error::new("telegram_updates_response_invalid"));
            }
            previous = Some(id);
        }
        Ok(updates.clone())
    }
    pub async fn send(&self, notice: &Notice) -> BotResult<i64> {
        self.send_text(&notice.text()).await
    }
    async fn send_text(&self, text: &str) -> BotResult<i64> {
        self.send_checked(text, false).await
    }
    async fn send_question(&self, text: &str) -> BotResult<i64> {
        self.send_checked(text, true).await
    }
    async fn send_checked(&self, text: &str, question: bool) -> BotResult<i64> {
        if text.is_empty() || text.encode_utf16().count() > if question { 4000 } else { 3500 } {
            return Err(Error::new("telegram_reply_size"));
        }
        let mut payload = json!({"chat_id":self.settings.chat,"text":text,"link_preview_options":{"is_disabled":true}});
        if question {
            payload["reply_markup"] = json!({"force_reply":true,"selective":true});
        }
        let result = self.call("sendMessage", payload).await?;
        if result
            .get("chat")
            .and_then(|c| c.get("id"))
            .and_then(Value::as_i64)
            != Some(self.settings.chat)
            || result
                .get("chat")
                .and_then(|c| c.get("type"))
                .and_then(Value::as_str)
                != Some("private")
        {
            return Err(Error::new("telegram_send_receipt_invalid"));
        }
        result
            .get("message_id")
            .and_then(Value::as_i64)
            .filter(|n| *n > 0)
            .ok_or_else(|| Error::new("telegram_send_receipt_invalid"))
    }
}

use crate::{
    contracts::{Authority, Effect, Limits, Observation, ToolName},
    knowledge_tools::KnowledgeTools,
    lifecycle,
    postgres::Store,
    runner::Tools,
    worker::Wake,
};
use sqlx::{Connection, PgConnection, Row};

pub async fn initialize(
    connection: &mut PgConnection,
    settings: &Settings,
    identity: &Identity,
) -> Result<()> {
    let mut tx = connection.begin().await.map_err(db)?;
    sqlx::query("SELECT pg_advisory_xact_lock(166001,51)")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    sqlx::query("INSERT INTO agent_telegram_state(key,next_update_id,evidence_type)VALUES('primary',0,'unverified')ON CONFLICT(key)DO NOTHING").execute(&mut *tx).await.map_err(db)?;
    let state = sqlx::query(
        "SELECT bot_id,next_update_id FROM agent_telegram_state WHERE key='primary' FOR UPDATE",
    )
    .fetch_one(&mut *tx)
    .await
    .map_err(db)?;
    if state
        .get::<Option<String>, _>("bot_id")
        .is_some_and(|id| id != identity.id.to_string())
    {
        return Err(Failure("telegram_bot_identity_changed"));
    }
    if state.get::<i64, _>("next_update_id") < 0 {
        return Err(Failure("invalid_update_id"));
    }
    let binding = settings.binding();
    sqlx::query("INSERT INTO rust_telegram_runtime(key,binding)VALUES('primary',$1)ON CONFLICT(key)DO NOTHING").bind(&binding).execute(&mut *tx).await.map_err(db)?;
    let saved: String = sqlx::query_scalar(
        "SELECT binding FROM rust_telegram_runtime WHERE key='primary' FOR UPDATE",
    )
    .fetch_one(&mut *tx)
    .await
    .map_err(db)?;
    if saved != binding {
        return Err(Failure("telegram_owner_binding_changed"));
    }
    sqlx::query("UPDATE agent_telegram_state SET bot_id=$1,evidence_type=$2,last_error=NULL WHERE key='primary'").bind(identity.id.to_string()).bind(if settings.fixture{"simulated_transport"}else{"live_poll"}).execute(&mut *tx).await.map_err(db)?;
    tx.commit().await.map_err(db)
}
pub(crate) async fn bound(connection: &mut PgConnection, settings: &Settings) -> Result<()> {
    let valid:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM rust_telegram_runtime r,agent_telegram_state s WHERE r.key='primary' AND s.key='primary' AND r.binding=$1 AND s.bot_id=$2 AND s.evidence_type=$3)").bind(settings.binding()).bind(settings.token.split(':').next().unwrap_or("")).bind(if settings.fixture{"simulated_transport"}else{"live_poll"}).fetch_one(connection).await.map_err(db)?;
    if !valid {
        return Err(Failure("telegram_owner_binding_changed"));
    }
    Ok(())
}
enum Command {
    Help,
    Ping,
    Status,
    Review,
    Runs,
    Run(Uuid),
    Control(Mode),
    Unavailable,
}
fn command(text: &str, username: &str) -> Command {
    if text.chars().count() > 2048 {
        return Command::Unavailable;
    }
    let mut words = text.split_whitespace().collect::<Vec<_>>();
    let Some(first) = words.first() else {
        return Command::Unavailable;
    };
    let (name, mention) = first
        .split_once('@')
        .map(|(a, b)| (a, Some(b)))
        .unwrap_or((first, None));
    if mention.is_some_and(|m| !m.eq_ignore_ascii_case(username)) {
        return Command::Unavailable;
    }
    words[0] = name;
    match words.as_slice() {
        ["/start"] | ["/help"] => Command::Help,
        ["/ping"] => Command::Ping,
        ["/status"] | ["/agents"] | ["/agents", "status"] => Command::Status,
        ["/jobs"] | ["/agents", "runs"] => Command::Runs,
        ["/agents", "review"] => Command::Review,
        ["/agents", "start"] => Command::Control(Mode::Running),
        ["/agents", "pause"] => Command::Control(Mode::Paused),
        ["/agents", "stop"] => Command::Control(Mode::Stopped),
        ["/agents", "run", id] => id.parse().map(Command::Run).unwrap_or(Command::Unavailable),
        _ => Command::Unavailable,
    }
}
/// Update offset, saved command intent, legacy reply and bound outbox commit together.
/// Unbound historical pending replies are not imported or replayed.
pub async fn receive(
    connection: &mut PgConnection,
    settings: &Settings,
    identity: &Identity,
    update: &Value,
    wake: &Wake,
) -> Result<bool> {
    receive_configured(connection, settings, identity, update, wake, None).await
}
pub async fn receive_configured(
    connection: &mut PgConnection,
    settings: &Settings,
    identity: &Identity,
    update: &Value,
    wake: &Wake,
    config: Option<&crate::configuration::Configuration>,
) -> Result<bool> {
    let id = update
        .get("update_id")
        .and_then(Value::as_i64)
        .filter(|n| *n >= 0 && *n < i64::MAX)
        .ok_or(Failure("invalid_update_id"))?;
    let mut tx = connection.begin().await.map_err(db)?;
    let owner_reply = config.is_some()
        && settings.authorized(&update["message"])
        && update["message"]["reply_to_message"]["message_id"]
            .as_i64()
            .is_some_and(|n| n > 0);
    let local_command = if config.is_some() && settings.authorized(&update["message"]) {
        crate::execution::telegram_commands::parse(
            update["message"]["text"].as_str().unwrap_or(""),
            &identity.username,
        )
    } else {
        None
    };
    let browser_command = if config.is_some() && settings.authorized(&update["message"]) {
        crate::browser_profiles::telegram_commands::parse(
            update["message"]["text"].as_str().unwrap_or(""),
            &identity.username,
        )
    } else {
        None
    };
    let owner_command = if config.is_some() && settings.authorized(&update["message"]) {
        crate::telegram_local::parse(
            update["message"]["text"].as_str().unwrap_or(""),
            &identity.username,
        )
    } else {
        None
    };
    if owner_reply
        || local_command.is_some()
        || browser_command.is_some()
        || owner_command.is_some()
    {
        sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            .execute(&mut *tx)
            .await
            .map_err(db)?;
        if owner_reply
            || local_command
                .as_ref()
                .is_some_and(|command| command.mutates())
            || browser_command
                .as_ref()
                .is_some_and(|command| command.mutates())
            || owner_command
                .as_ref()
                .is_some_and(|command| command.mutates())
        {
            crate::execution::telegram_questions::lock_in(&mut tx).await?;
        }
    }
    bound(&mut tx, settings).await?;
    let offset: i64 = sqlx::query_scalar(
        "SELECT next_update_id FROM agent_telegram_state WHERE key='primary' FOR UPDATE",
    )
    .fetch_one(&mut *tx)
    .await
    .map_err(db)?;
    if id < offset {
        return Ok(false);
    }
    let mut control_changed = false;
    let mut intake = false;
    let authorized = update
        .get("message")
        .is_some_and(|message| settings.authorized(message));
    if authorized {
        let text = update["message"]
            .get("text")
            .and_then(Value::as_str)
            .unwrap_or("");
        let correlated = if owner_reply {
            let now: chrono::DateTime<chrono::Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
                .fetch_one(&mut *tx)
                .await
                .map_err(db)?;
            crate::execution::telegram_questions::receive_in(
                &mut tx,
                settings,
                config.unwrap(),
                &update["message"],
                id,
                now,
            )
            .await?
        } else {
            None
        };
        let reply = if let Some(reply) = correlated {
            intake = true;
            reply
        } else if let Some(command) = local_command.as_ref() {
            let now: chrono::DateTime<chrono::Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
                .fetch_one(&mut *tx)
                .await
                .map_err(db)?;
            let reply = crate::execution::telegram_commands::dispatch_in(
                &mut tx,
                command,
                config.unwrap(),
                now,
            )
            .await?;
            intake = command.mutates();
            reply
        } else if let Some(command) = browser_command.as_ref() {
            let reply = crate::browser_profiles::telegram_commands::dispatch_in(
                &mut tx,
                command,
                config.unwrap(),
                id,
                settings.chat,
            )
            .await?;
            intake = command.mutates();
            reply
        } else if let Some(command) = owner_command.as_ref() {
            crate::telegram_local::dispatch_in(
                &mut tx,
                command,
                config.unwrap(),
                settings.owner_user(),
                settings.chat,
                id,
            )
            .await?
        } else {
            let notice = match command(text, &identity.username) {
                Command::Help => Notice::Help,
                Command::Ping => Notice::Pong,
                Command::Unavailable => Notice::Unavailable,
                Command::Status => {
                    let c = lifecycle::control(&mut tx).await?;
                    Notice::Status {
                        mode: c.mode,
                        online: c.worker_online,
                    }
                }
                Command::Control(mode) => {
                    let c = lifecycle::control(&mut tx).await?;
                    let next = lifecycle::set_control(&mut tx, c.revision, mode).await?;
                    control_changed = true;
                    Notice::Status {
                        mode: next.mode,
                        online: next.worker_online,
                    }
                }
                Command::Review => {
                    let key = Uuid::new_v5(
                        &Uuid::NAMESPACE_URL,
                        format!("telegram:{}:{id}", settings.chat).as_bytes(),
                    );
                    let run = lifecycle::intake_policy(
                        &mut tx,
                        key,
                        Limits::default(),
                        Some(crate::model_policy::Policy::Deterministic {}),
                    )
                    .await?;
                    intake = true;
                    Notice::Run {
                        id: run.run.id,
                        state: run.run.state,
                    }
                }
                Command::Runs => {
                    let rows = lifecycle::listing(&mut tx).await?;
                    if let Some(first) = rows.first() {
                        let runid = first["id"]
                            .as_str()
                            .and_then(|s| s.parse::<Uuid>().ok())
                            .ok_or(Failure("invalid_agent_record"))?;
                        let run = lifecycle::load(&mut tx, runid).await?;
                        Notice::Run {
                            id: run.run.id,
                            state: run.run.state,
                        }
                    } else {
                        Notice::Unavailable
                    }
                }
                Command::Run(id) => match lifecycle::load(&mut tx, id).await {
                    Ok(run) => Notice::Run {
                        id: run.run.id,
                        state: run.run.state,
                    },
                    Err(Failure("agent_run_not_found")) => Notice::Unavailable,
                    Err(error) => return Err(error),
                },
            };
            notice.text()
        };
        sqlx::query(
            "INSERT INTO agent_telegram_deliveries(update_id,reply,state)VALUES($1,$2,'pending')",
        )
        .bind(id)
        .bind(&reply)
        .execute(&mut *tx)
        .await
        .map_err(db)?;
        sqlx::query("INSERT INTO rust_telegram_outbox(id,update_id,binding,reply,state)VALUES($1,$2,$3,$4,'pending')").bind(Uuid::new_v4()).bind(id).bind(settings.binding()).bind(&reply).execute(&mut *tx).await.map_err(db)?;
    }
    sqlx::query("UPDATE agent_telegram_state SET next_update_id=$1,last_poll_at=clock_timestamp(),last_error=NULL WHERE key='primary'").bind(id+1).execute(&mut *tx).await.map_err(db)?;
    tx.commit().await.map_err(db)?;
    if control_changed {
        wake.controls_changed();
    } else if intake {
        wake.work_available();
    }
    Ok(authorized)
}
pub struct Delivery {
    pub id: Uuid,
    pub text: String,
    update: Option<i64>,
}
pub async fn claim_delivery(
    connection: &mut PgConnection,
    settings: &Settings,
) -> Result<Option<Delivery>> {
    let mut tx = connection.begin().await.map_err(db)?;
    bound(&mut tx, settings).await?;
    let available:bool=sqlx::query_scalar("SELECT next_request_at<=clock_timestamp() FROM rust_telegram_runtime WHERE key='primary' FOR UPDATE").fetch_one(&mut *tx).await.map_err(db)?;
    if !available {
        return Ok(None);
    }
    let row=sqlx::query("SELECT o.id,o.reply,o.update_id FROM rust_telegram_outbox o LEFT JOIN agent_telegram_deliveries d ON d.update_id=o.update_id WHERE o.binding=$1 AND o.state='pending' AND (o.update_id IS NULL OR d.state='pending') ORDER BY o.created_at,o.id FOR UPDATE OF o SKIP LOCKED LIMIT 1").bind(settings.binding()).fetch_optional(&mut *tx).await.map_err(db)?;
    let Some(row) = row else {
        return Ok(None);
    };
    let id = row.get("id");
    let update: Option<i64> = row.get("update_id");
    sqlx::query("UPDATE rust_telegram_outbox SET state='sending',attempted_at=clock_timestamp() WHERE id=$1").bind(id).execute(&mut *tx).await.map_err(db)?;
    if let Some(update) = update {
        let n=sqlx::query("UPDATE agent_telegram_deliveries SET state='sending' WHERE update_id=$1 AND state='pending'").bind(update).execute(&mut *tx).await.map_err(db)?.rows_affected();
        if n != 1 {
            return Err(Failure("telegram_delivery_fence_lost"));
        }
    }
    sqlx::query("UPDATE rust_telegram_runtime SET next_request_at=GREATEST(next_request_at,clock_timestamp()+interval '1 second'),updated_at=clock_timestamp() WHERE key='primary'").execute(&mut *tx).await.map_err(db)?;
    tx.commit().await.map_err(db)?;
    Ok(Some(Delivery {
        id,
        text: row.get("reply"),
        update,
    }))
}
pub async fn finish_delivery(
    connection: &mut PgConnection,
    settings: &Settings,
    delivery: &Delivery,
    result: BotResult<i64>,
) -> Result<()> {
    let mut tx = connection.begin().await.map_err(db)?;
    bound(&mut tx, settings).await?;
    let (state, receipt, delay) = match result {
        Ok(receipt) if receipt > 0 => ("sent", Some(receipt), 1i64),
        Err(error)
            if error.code == "telegram_rate_limited"
                && error.retry_after.as_secs() > 0
                && error.retry_after.as_secs() <= 86400 =>
        {
            ("pending", None, error.retry_after.as_secs() as i64)
        }
        _ => return Ok(()), // Ambiguous network/response outcomes remain sending; never replay.
    };
    let n=sqlx::query("UPDATE rust_telegram_outbox SET state=$1,receipt_message_id=$2 WHERE id=$3 AND binding=$4 AND state='sending'").bind(state).bind(receipt).bind(delivery.id).bind(settings.binding()).execute(&mut *tx).await.map_err(db)?.rows_affected();
    if n != 1 {
        return Err(Failure("telegram_delivery_fence_lost"));
    }
    if let Some(update) = delivery.update {
        let n = sqlx::query(
            "UPDATE agent_telegram_deliveries SET state=$1 WHERE update_id=$2 AND state='sending'",
        )
        .bind(state)
        .bind(update)
        .execute(&mut *tx)
        .await
        .map_err(db)?
        .rows_affected();
        if n != 1 {
            return Err(Failure("telegram_delivery_fence_lost"));
        }
    }
    sqlx::query("UPDATE rust_telegram_runtime SET next_request_at=GREATEST(next_request_at,clock_timestamp()+$1*interval '1 second'),updated_at=clock_timestamp() WHERE key='primary'").bind(delay).execute(&mut *tx).await.map_err(db)?;
    tx.commit().await.map_err(db)
}
pub async fn enqueue(
    connection: &mut PgConnection,
    settings: &Settings,
    effect: Uuid,
    notice: Notice,
) -> Result<()> {
    bound(connection, settings).await?;
    let row=sqlx::query("INSERT INTO rust_telegram_outbox(id,binding,reply,state)VALUES($1,$2,$3,'pending')ON CONFLICT(id)DO UPDATE SET id=EXCLUDED.id WHERE rust_telegram_outbox.binding=EXCLUDED.binding AND rust_telegram_outbox.reply=EXCLUDED.reply RETURNING id").bind(effect).bind(settings.binding()).bind(notice.text()).fetch_optional(connection).await.map_err(db)?;
    if row.is_none() {
        return Err(Failure("telegram_effect_conflict"));
    }
    Ok(())
}
/// Compose actual read tools with a bound notification queue; no model-supplied text or chat.
pub struct RuntimeTools {
    pub knowledge: KnowledgeTools,
    pub telegram: Option<Settings>,
    pub run_id: Uuid,
}
impl Tools for RuntimeTools {
    async fn authority(
        &mut self,
        call: &crate::contracts::ToolCall,
        store: &mut Store<'_>,
    ) -> Result<Authority> {
        if call.name == ToolName::NotifyTelegram {
            let settings = self
                .telegram
                .as_ref()
                .ok_or(Failure("telegram_adapter_not_enabled"))?;
            bound(store.connection, settings).await?;
            return Ok(Authority {
                telegram_paired: true,
                ..Authority::default()
            });
        }
        self.knowledge.authority(call, store).await
    }
    async fn execute(&mut self, effect: &Effect, store: &mut Store<'_>) -> Result<Observation> {
        if effect.call.name == ToolName::NotifyTelegram {
            let settings = self
                .telegram
                .as_ref()
                .ok_or(Failure("telegram_adapter_not_enabled"))?;
            enqueue(
                store.connection,
                settings,
                effect.id,
                Notice::AgentUpdate { id: self.run_id },
            )
            .await?;
            return Ok(Observation {
                jobs: vec![],
                evidence: vec![],
                data: json!({"notification_id":effect.id,"delivery_state":"pending","scope":"owner_notification_queued_not_sent"}),
            });
        }
        self.knowledge.execute(effect, store).await
    }
}
fn db(_: sqlx::Error) -> Failure {
    Failure("telegram_database_error")
}

pub struct Relay {
    bot: Bot,
    identity: Identity,
    connection: PgConnection,
}
async fn preflight(connection: &mut PgConnection, settings: &Settings) -> Result<()> {
    let mut tx = connection.begin().await.map_err(db)?;
    sqlx::query("SELECT pg_advisory_xact_lock(166001,51)")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let pin: Option<String> =
        sqlx::query_scalar("SELECT bot_id FROM agent_telegram_state WHERE key='primary'")
            .fetch_optional(&mut *tx)
            .await
            .map_err(db)?
            .flatten();
    if pin.is_some_and(|id| Some(id.as_str()) != settings.token.split(':').next()) {
        return Err(Failure("telegram_bot_identity_changed"));
    }
    sqlx::query("INSERT INTO rust_telegram_runtime(key,binding)VALUES('primary',$1)ON CONFLICT(key)DO NOTHING").bind(settings.binding()).execute(&mut *tx).await.map_err(db)?;
    let binding: String = sqlx::query_scalar(
        "SELECT binding FROM rust_telegram_runtime WHERE key='primary' FOR UPDATE",
    )
    .fetch_one(&mut *tx)
    .await
    .map_err(db)?;
    if binding != settings.binding() {
        return Err(Failure("telegram_owner_binding_changed"));
    }
    tx.commit().await.map_err(db)
}
async fn remaining(connection: &mut PgConnection) -> Result<Duration> {
    let seconds:f64=sqlx::query_scalar("SELECT GREATEST(0,EXTRACT(EPOCH FROM next_request_at-clock_timestamp()))::double precision FROM rust_telegram_runtime WHERE key='primary'").fetch_one(connection).await.map_err(db)?;
    if !seconds.is_finite() || seconds > 86401.0 {
        return Err(Failure("telegram_cooldown_requires_reconciliation"));
    }
    Ok(Duration::from_secs_f64(seconds.max(0.0)))
}
async fn cooldown(connection: &mut PgConnection, delay: Duration) -> Result<()> {
    let seconds = i64::try_from(delay.as_secs())
        .ok()
        .filter(|n| (1..=86400).contains(n))
        .ok_or(Failure("telegram_cooldown_requires_reconciliation"))?;
    sqlx::query("UPDATE rust_telegram_runtime SET next_request_at=GREATEST(next_request_at,clock_timestamp()+$1*interval '1 second'),updated_at=clock_timestamp() WHERE key='primary'").bind(seconds).execute(connection).await.map_err(db)?;
    Ok(())
}
pub async fn prepare(config: &crate::configuration::Configuration) -> Result<Option<Relay>> {
    let Some(settings) = config.telegram.clone() else {
        return Ok(None);
    };
    let mut connection = config.connect_telegram().await?;
    preflight(&mut connection, &settings).await?;
    if !remaining(&mut connection).await?.is_zero() {
        return Err(Failure("telegram_cooldown_active"));
    }
    let bot = Bot::new(settings)?;
    let identity = match bot.verify().await {
        Ok(identity) => identity,
        Err(error) => {
            if error.code == "telegram_rate_limited" {
                cooldown(&mut connection, error.retry_after).await?;
            }
            return Err(Failure(error.code));
        }
    };
    initialize(&mut connection, &bot.settings, &identity).await?;
    Ok(Some(Relay {
        bot,
        identity,
        connection,
    }))
}
impl Relay {
    async fn cycle(
        &mut self,
        config: &crate::configuration::Configuration,
        wake: &Wake,
        shutdown: &tokio_util::sync::CancellationToken,
        backoff: &mut crate::recovery::Backoff,
    ) -> Result<()> {
        loop {
            let wait = remaining(&mut self.connection).await?;
            if !wait.is_zero() {
                tokio::select! {biased;_=shutdown.cancelled()=>return Ok(()),_=tokio::time::sleep(wait)=>{}}
            }
            let offset: i64 = sqlx::query_scalar(
                "SELECT next_update_id FROM agent_telegram_state WHERE key='primary'",
            )
            .fetch_one(&mut self.connection)
            .await
            .map_err(db)?;
            let pending:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM rust_telegram_outbox WHERE state='pending' AND binding=$1) OR EXISTS(SELECT 1 FROM owner_preferences WHERE starts_with(key,'exec_q:') AND value->>'state'='pending' AND value->>'delivery_error' IS DISTINCT FROM 'telegram_question_too_long_manual_required' AND CASE WHEN pg_input_is_valid(value->>'expires_at','timestamp with time zone') THEN (value->>'expires_at')::timestamptz>clock_timestamp() ELSE true END)").bind(self.bot.settings.binding()).fetch_one(&mut self.connection).await.map_err(db)?;
            let updates = self.bot.updates(offset, pending).await;
            let updates = match updates {
                Ok(updates) => updates,
                Err(error) => return self.transport_error(error).await,
            };
            let mut empty = updates.is_empty();
            for update in updates {
                receive_configured(
                    &mut self.connection,
                    &self.bot.settings,
                    &self.identity,
                    &update,
                    wake,
                    Some(config),
                )
                .await?;
            }
            sqlx::query("UPDATE agent_telegram_state SET last_poll_at=clock_timestamp(),last_error=NULL WHERE key='primary'").execute(&mut self.connection).await.map_err(db)?;
            if let Some(question) = crate::execution::telegram_questions::claim(
                &mut self.connection,
                &self.bot.settings,
                config,
            )
            .await?
            {
                let result = self.bot.send_question(&question.text).await;
                match result {
                    Ok(message) => {
                        crate::execution::telegram_questions::finish(
                            &mut self.connection,
                            &self.bot.settings,
                            &question,
                            message,
                        )
                        .await?;
                        cooldown(&mut self.connection, Duration::from_secs(1)).await?;
                    }
                    Err(error) => return self.transport_error(error).await,
                }
                backoff.reset();
                empty = false;
                let wait = remaining(&mut self.connection).await?;
                if !wait.is_zero() {
                    tokio::select! {biased;_=shutdown.cancelled()=>return Ok(()),_=tokio::time::sleep(wait)=>{}}
                }
            }

            if let Some(delivery) = claim_delivery(&mut self.connection, &self.bot.settings).await?
            {
                let result = self.bot.send_text(&delivery.text).await;
                finish_delivery(&mut self.connection, &self.bot.settings, &delivery, result)
                    .await?;
                if let Err(error) = result {
                    return self.transport_error(error).await;
                }
            } else if empty {
                tokio::select! {biased;_=shutdown.cancelled()=>return Ok(()),_=tokio::time::sleep(Duration::from_secs(1))=>{}}
            }
            backoff.reset();
        }
    }
    async fn transport_error(&mut self, error: Error) -> Result<()> {
        if error.code == "telegram_rate_limited" {
            cooldown(&mut self.connection, error.retry_after).await?;
        }
        sqlx::query("UPDATE agent_telegram_state SET last_error=$1 WHERE key='primary'")
            .bind(error.code)
            .execute(&mut self.connection)
            .await
            .map_err(db)?;
        Err(Failure(error.code))
    }
    pub async fn run(
        mut self,
        config: &crate::configuration::Configuration,
        wake: Wake,
        shutdown: tokio_util::sync::CancellationToken,
    ) -> Result<()> {
        let mut backoff = crate::recovery::Backoff::default();
        loop {
            let result = tokio::select! {biased;_=shutdown.cancelled()=>Ok(()),result=self.cycle(config,&wake,&shutdown,&mut backoff)=>result};
            match result {
                Ok(()) => {
                    crate::recovery::close(self.connection).await;
                    return Ok(());
                }
                Err(error) if crate::recovery::database_failure(error) => {
                    crate::recovery::close(self.connection).await;
                    loop {
                        backoff.failed();
                        tokio::select! {biased;_=shutdown.cancelled()=>return Ok(()),_=tokio::time::sleep(backoff.remaining())=>{}}
                        let next = tokio::select! {biased;_=shutdown.cancelled()=>return Ok(()),next=config.connect_telegram()=>next};
                        match next {
                            Ok(mut next) => {
                                match initialize(&mut next, &self.bot.settings, &self.identity)
                                    .await
                                {
                                    Ok(()) => {
                                        self.connection = next;
                                        break;
                                    }
                                    Err(error) => {
                                        crate::recovery::close(next).await;
                                        if !crate::recovery::database_failure(error) {
                                            return Err(error);
                                        }
                                    }
                                }
                            }
                            Err(error) => {
                                if !crate::recovery::database_failure(error) {
                                    return Err(error);
                                }
                            }
                        }
                    }
                }
                Err(error)
                    if matches!(
                        error.0,
                        "telegram_network_or_response_error"
                            | "telegram_transport_error"
                            | "telegram_rate_limited"
                    ) =>
                {
                    backoff.failed();
                    tokio::select! {biased;_=shutdown.cancelled()=>{crate::recovery::close(self.connection).await;return Ok(());},_=tokio::time::sleep(backoff.remaining())=>{}}
                }
                Err(error) => {
                    crate::recovery::close(self.connection).await;
                    return Err(error);
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{
        extract::{Request, State as WebState},
        response::{IntoResponse, Response},
    };
    use std::sync::{
        Arc,
        atomic::{AtomicU8, Ordering},
    };
    use tokio::sync::Mutex;
    use tokio_util::sync::CancellationToken;
    fn values(endpoint: &str) -> BTreeMap<String, String> {
        BTreeMap::from([
            ("RUST_TELEGRAM_ENABLED".into(), "true".into()),
            (
                "TELEGRAM_BOT_TOKEN".into(),
                "123:abcdefghijklmnopqrstuvwx".into(),
            ),
            ("TELEGRAM_OWNER_USER_ID".into(), "11".into()),
            ("TELEGRAM_OWNER_CHAT_ID".into(), "22".into()),
            ("RUST_TELEGRAM_FIXTURE_ENDPOINT".into(), endpoint.into()),
        ])
    }
    struct Fake {
        mode: AtomicU8,
        calls: Mutex<Vec<(String, Value)>>,
        redirect: String,
    }
    async fn respond(WebState(state): WebState<Arc<Fake>>, request: Request) -> Response {
        let path = request.uri().path().to_owned();
        let method = path.rsplit('/').next().unwrap().to_owned();
        let body = axum::body::to_bytes(request.into_body(), 65536)
            .await
            .unwrap();
        let payload = serde_json::from_slice(&body).unwrap();
        state.calls.lock().await.push((path, payload));
        let mode = state.mode.load(Ordering::SeqCst);
        if mode == 1 {
            return (
                axum::http::StatusCode::FOUND,
                [("location", state.redirect.as_str())],
                axum::Json(json!({"ok":false})),
            )
                .into_response();
        }
        if mode == 2 {
            return vec![b'x'; 1_048_577].into_response();
        }
        if mode == 3 {
            return (
                axum::http::StatusCode::TOO_MANY_REQUESTS,
                axum::Json(json!({"ok":false,"error_code":429,"parameters":{"retry_after":600}})),
            )
                .into_response();
        }
        let result = match method.as_str() {
            "getMe" => json!({"id":123,"is_bot":true,"username":"fictional_bot"}),
            "getWebhookInfo" => {
                json!({"url":if mode==4{"https://existing.example.net/webhook"}else{""}})
            }
            "getUpdates" => {
                if mode == 6 {
                    json!([{"update_id":1},{"update_id":1}])
                } else {
                    json!([])
                }
            }
            "sendMessage" => {
                json!({"message_id":44,"chat":{"id":if mode==5{99}else{22},"type":"private"}})
            }
            _ => Value::Null,
        };
        axum::Json(json!({"ok":true,"result":result})).into_response()
    }
    async fn fake() -> (
        Bot,
        Arc<Fake>,
        CancellationToken,
        tokio::task::JoinHandle<()>,
    ) {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let endpoint = format!("http://{}", listener.local_addr().unwrap());
        let state = Arc::new(Fake {
            mode: AtomicU8::new(0),
            calls: Mutex::new(vec![]),
            redirect: format!("{endpoint}/redirect-target"),
        });
        let stop = CancellationToken::new();
        let shutdown = stop.clone();
        let router = axum::Router::new()
            .fallback(respond)
            .with_state(state.clone());
        let server = tokio::spawn(async move {
            axum::serve(listener, router)
                .with_graceful_shutdown(shutdown.cancelled_owned())
                .await
                .unwrap();
        });
        (
            Bot::new(
                Settings::from_values(&values(&endpoint), true)
                    .unwrap()
                    .unwrap(),
            )
            .unwrap(),
            state,
            stop,
            server,
        )
    }
    #[test]
    fn owner_messages_require_private_exact_integer_ids_and_no_forwarding() {
        let settings = Settings::from_values(&values("http://127.0.0.1:54321"), true)
            .unwrap()
            .unwrap();
        let good = json!({"chat":{"type":"private","id":22},"from":{"id":11,"is_bot":false},"text":"/ping"});
        assert!(settings.authorized(&good));
        for bad in [
            json!({"chat":{"type":"group","id":22},"from":{"id":11,"is_bot":false}}),
            json!({"chat":{"type":"private","id":22},"from":{"id":true,"is_bot":false}}),
            json!({"chat":{"type":"private","id":22},"from":{"id":11,"is_bot":true}}),
            json!({"chat":{"type":"private","id":22},"from":{"id":11,"is_bot":false},"forward_date":1}),
        ] {
            assert!(!settings.authorized(&bad));
        }
        assert!(matches!(
            command("/agents@another_bot start", "fictional_bot"),
            Command::Unavailable
        ));
        assert!(matches!(
            command("/agents@FICTIONAL_BOT review", "fictional_bot"),
            Command::Review
        ));
    }
    #[test]
    fn fixture_endpoints_and_tokens_cannot_select_production_or_inject_paths() {
        let mut configured = values("http://127.0.0.1:54321");
        assert!(Settings::from_values(&configured, false).is_err());
        configured.insert(
            "RUST_TELEGRAM_FIXTURE_ENDPOINT".into(),
            "https://api.telegram.org".into(),
        );
        assert!(Settings::from_values(&configured, true).is_err());
        configured = values("http://127.0.0.1:54321");
        configured.insert(
            "TELEGRAM_BOT_TOKEN".into(),
            "123:abcdefghijklmnop/other".into(),
        );
        assert!(Settings::from_values(&configured, true).is_err());
        configured = values("http://127.0.0.1:54321");
        configured.remove("RUST_TELEGRAM_FIXTURE_ENDPOINT");
        assert!(Settings::from_values(&configured, true).is_err());
    }
    #[tokio::test(flavor = "current_thread")]
    async fn actual_transport_verifies_bot_and_sends_only_bound_notice() {
        let (bot, state, stop, server) = fake().await;
        assert_eq!(bot.verify().await.unwrap().id, 123);
        assert_eq!(bot.send(&Notice::Pong).await.unwrap(), 44);
        let calls = state.calls.lock().await;
        assert_eq!(calls.len(), 3);
        assert_eq!(calls[2].1["chat_id"], 22);
        assert!(
            calls[2].1["link_preview_options"]["is_disabled"]
                .as_bool()
                .unwrap()
        );
        assert!(calls[2].1.get("parse_mode").is_none());
        drop(calls);
        stop.cancel();
        server.await.unwrap();
    }
    #[tokio::test(flavor = "current_thread")]
    async fn redirect_oversize_and_bad_send_receipt_are_not_retried_or_leaked() {
        for (mode, code) in [
            (1, "telegram_transport_error"),
            (2, "telegram_response_size"),
            (5, "telegram_send_receipt_invalid"),
        ] {
            let (bot, state, stop, server) = fake().await;
            state.mode.store(mode, Ordering::SeqCst);
            let error = bot.send(&Notice::Pong).await.unwrap_err();
            assert_eq!(error.code, code);
            assert!(!format!("{error:?}").contains("abcdefghijkl"));
            assert_eq!(state.calls.lock().await.len(), 1);
            stop.cancel();
            server.await.unwrap();
        }
    }
    #[tokio::test(flavor = "current_thread")]
    async fn official_rate_limit_is_honored_without_capping_it_down() {
        let (bot, state, stop, server) = fake().await;
        state.mode.store(3, Ordering::SeqCst);
        let error = bot.send(&Notice::Pong).await.unwrap_err();
        assert_eq!(error.code, "telegram_rate_limited");
        assert_eq!(error.retry_after, Duration::from_secs(600));
        stop.cancel();
        server.await.unwrap();
    }
    #[tokio::test(flavor = "current_thread")]
    async fn existing_webhook_and_malformed_update_order_are_refused() {
        let (bot, state, stop, server) = fake().await;
        state.mode.store(4, Ordering::SeqCst);
        assert_eq!(
            bot.verify().await.err().unwrap().code,
            "telegram_webhook_conflict_owner_approval_required"
        );
        state.mode.store(6, Ordering::SeqCst);
        assert_eq!(
            bot.updates(0, false).await.err().unwrap().code,
            "telegram_updates_response_invalid"
        );
        assert_eq!(
            bot.updates(-1, false).await.err().unwrap().code,
            "invalid_update_id"
        );
        assert!(
            state
                .calls
                .lock()
                .await
                .iter()
                .all(|(path, _)| !path.contains("deleteWebhook") && !path.contains("setWebhook"))
        );
        stop.cancel();
        server.await.unwrap();
    }
}
