//! Owner-only history over records from the earlier dashboard and browser executor.
use crate::{
    Failure, Result, browser_profiles,
    configuration::{Configuration, boolean},
    lifecycle, packet_service,
    provider::billing_policy,
};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use std::{collections::BTreeMap, sync::LazyLock};
use uuid::Uuid;

#[derive(Clone, Copy)]
pub(crate) enum Route {
    Campaigns,
    Campaign(Uuid),
    AgentStatus,
    Submissions,
    BrowserStatus(Uuid),
    BrowserOperation(Uuid),
}

fn canonical_id(value: &str) -> Option<Uuid> {
    let id = value.parse::<Uuid>().ok()?;
    (id.to_string() == value).then_some(id)
}

pub(crate) fn route(path: &str) -> Option<Route> {
    match path {
        "/api/v1/agent/status" => Some(Route::AgentStatus),
        "/api/v1/agent/campaigns" => Some(Route::Campaigns),
        "/api/v1/browser/submissions" => Some(Route::Submissions),
        _ => {
            if let Some(id) = path.strip_prefix("/api/v1/agent/campaigns/") {
                return canonical_id(id).map(Route::Campaign);
            }
            let tail = path.strip_prefix("/api/v1/browser-applications/")?;
            if let Some(id) = tail.strip_suffix("/operation") {
                canonical_id(id).map(Route::BrowserOperation)
            } else {
                canonical_id(tail).map(Route::BrowserStatus)
            }
        }
    }
}

pub(crate) struct Settings {
    cohere_configured: bool,
    cohere_enabled: bool,
    owner_text: bool,
    candidate_data: bool,
    cap: Option<i32>,
    model: Option<String>,
}

impl Settings {
    pub(crate) fn from_values(values: &BTreeMap<String, String>) -> Self {
        let flag = |key| boolean(values, key, false).unwrap_or(false);
        let cap = billing_policy(values).and_then(|policy| policy.maximum());
        Self {
            cohere_configured: values
                .get("COHERE_API_KEY")
                .is_some_and(|key| !key.trim().is_empty()),
            cohere_enabled: flag("COHERE_ENABLED") && flag("COHERE_EVALUATION_KEY_CONFIRMED"),
            owner_text: flag("COHERE_OWNER_TEXT_AUTHORIZED"),
            candidate_data: flag("COHERE_CANDIDATE_DATA_AUTHORIZED"),
            cap: match cap {
                Ok(cap) => Some(cap),
                Err(Failure("monthly_request_limit")) => Some(0),
                Err(_) => None,
            },
            model: values
                .get("COHERE_MODEL")
                .filter(|model| {
                    matches!(
                        model.as_str(),
                        "command-a-plus-05-2026" | "command-a-03-2025"
                    )
                })
                .cloned(),
        }
    }
}

fn db(_: sqlx::Error) -> Failure {
    Failure("dashboard_database_error")
}

const INVALID: Failure = Failure("invalid_saved_legacy_review");
const LIMIT: Failure = Failure("saved_legacy_review_limit");

#[derive(Clone, Copy)]
enum Record {
    Campaign,
    Submission,
}

impl Record {
    fn prefix(self) -> &'static str {
        match self {
            Self::Campaign => "campaign:",
            Self::Submission => "submission:",
        }
    }

    fn decode(self, key: &str, value: Option<Value>) -> Result<Value> {
        fn compile(text: &str) -> jsonschema::Validator {
            let schema: Value = serde_json::from_str(text).expect("saved review schema");
            jsonschema::draft202012::options()
                .should_validate_formats(true)
                .build(&schema)
                .expect("saved review validator")
        }
        static CAMPAIGN: LazyLock<jsonschema::Validator> =
            LazyLock::new(|| compile(include_str!("../schemas/legacy-review-campaign.json")));
        static SUBMISSION: LazyLock<jsonschema::Validator> =
            LazyLock::new(|| compile(include_str!("../schemas/legacy-review-submission.json")));
        let mut value = value.ok_or(LIMIT)?;
        let (validator, identity) = match self {
            Self::Campaign => (&*CAMPAIGN, "id"),
            Self::Submission => (&*SUBMISSION, "application_id"),
        };
        if !validator.is_valid(&value) {
            return Err(INVALID);
        }
        let key_id = key.strip_prefix(self.prefix()).and_then(canonical_id);
        if key_id.is_none() || key_id != value[identity].as_str().and_then(canonical_id) {
            return Err(INVALID);
        }
        let fields = value.as_object_mut().ok_or(INVALID)?;
        match self {
            Self::Campaign => {
                fields.entry("state").or_insert(json!("created"));
                fields.entry("message").or_insert(json!(""));
                fields.entry("reply").or_insert(json!(
                    "Accepted; pending worker execution. Zero submissions were made."
                ));
            }
            Self::Submission => {
                fields.entry("state").or_insert(json!("prepared"));
            }
        }
        Ok(value)
    }
}

async fn listing(tx: &mut Transaction<'_, Postgres>, record: Record) -> Result<Value> {
    let rows: Vec<(String, Option<Value>)> = sqlx::query_as(
        "SELECT key,
        CASE WHEN octet_length(value::text)<=262144 THEN value END FROM owner_preferences
        WHERE starts_with(key,$1) ORDER BY created_at DESC,key LIMIT 50",
    )
    .bind(record.prefix())
    .fetch_all(&mut **tx)
    .await
    .map_err(db)?;
    let rows = rows
        .into_iter()
        .map(|(key, value)| record.decode(&key, value))
        .collect::<Result<Vec<_>>>()?;
    let value = Value::Array(rows);
    if serde_json::to_vec(&value).map_err(|_| INVALID)?.len() > 2_000_000 {
        return Err(LIMIT);
    }
    Ok(value)
}

async fn campaign(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Value> {
    let key = format!("campaign:{id}");
    let row: Option<(Option<Value>,)> = sqlx::query_as("SELECT
        CASE WHEN octet_length(value::text)<=262144 THEN value END FROM owner_preferences WHERE key=$1")
        .bind(&key).fetch_optional(&mut **tx).await.map_err(db)?;
    Record::Campaign.decode(&key, row.ok_or(Failure("campaign_not_found"))?.0)
}

async fn agent_status(tx: &mut Transaction<'_, Postgres>, config: &Configuration) -> Result<Value> {
    let settings = &config.legacy_review;
    let control = lifecycle::control(tx).await?;
    let browser = browser_profiles::saved_dashboard_status(tx, &config.browser_profiles).await?;
    let selected = browser["profiles"]
        .as_array()
        .into_iter()
        .flatten()
        .find(|item| item["selected"] == true);
    let connected = selected.is_some_and(|item| item["status"] == "CONNECTED");
    let browser_ready = connected
        && config.browser_profiles.commands_enabled
        && selected.is_some_and(|item| item["commands_enabled"] == true);
    let usage: Option<(i32, i32, i32)> = sqlx::query_as("SELECT requests,input_tokens,output_tokens
        FROM llm_monthly_usage WHERE provider='cohere' AND month=to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM')")
        .fetch_optional(&mut **tx).await.map_err(db)?;
    let (requests, input, output) = usage.unwrap_or_default();
    let heartbeat: Option<String> = sqlx::query_scalar(
        "SELECT value->>'heartbeat_at'
        FROM owner_preferences WHERE key='agent_worker:primary'",
    )
    .fetch_optional(&mut **tx)
    .await
    .map_err(db)?
    .flatten();
    Ok(json!({
        "native_worker_online":control.worker_online,"native_worker_mode":control.mode,
        "worker_ready":false,"worker_last_heartbeat":heartbeat,"execution":"pending_worker_unavailable",
        "browser_worker_ready":browser_ready,"browser_last_heartbeat":selected.and_then(|item| item.get("last_heartbeat")),
        "browser_fill_enabled":config.browser_profiles.fill_enabled,
        "browser_availability":if browser_ready {"available"} else if connected {"PROFILE_COMMANDS_DISABLED"} else {"PROFILE_OFFLINE"},
        "provider":"cohere","model":settings.model,
        "state":if !settings.cohere_configured {"not_configured"} else if settings.cohere_enabled {"configured_not_live_verified"} else {"authorization_required"},
        "owner_text_authorized":settings.owner_text,"candidate_data_authorized":settings.candidate_data,
        "local_request_cap":settings.cap,"local_requests_remaining":settings.cap.map(|cap|cap.saturating_sub(requests.max(0)).max(0)),
        "provider_quota_remaining":null,"quota_scope":"local_installation_only","input_tokens":input,"output_tokens":output,
        "submissions_enabled":false,"submission_scope":"localhost_fixtures_only","email_sending_enabled":false
    }))
}

async fn browser_status(
    tx: &mut Transaction<'_, Postgres>,
    id: Uuid,
    config: &Configuration,
) -> Result<Value> {
    let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut **tx)
        .await
        .map_err(db)?;
    let packet = packet_service::read_snapshot_in(tx, id, &config.packets, now).await?;
    let row: Option<(Option<Value>,)> = sqlx::query_as("SELECT
        CASE WHEN octet_length(value::text)<=262144 THEN value END FROM owner_preferences WHERE key=$1")
        .bind(format!("browser:{id}")).fetch_optional(&mut **tx).await.map_err(db)?;
    let analysis = match row {
        None => Value::Null,
        Some((Some(value),)) if value.is_object() => value,
        Some((Some(_),)) => return Err(INVALID),
        Some((None,)) => return Err(LIMIT),
    };
    let recovery = match packet["lifecycle_state"].as_str() {
        Some("submitting" | "submission_unknown") => {
            Some("Check the saved submission receipt before taking further action.")
        }
        Some("provider_confirmed_submitted" | "user_reported_submitted") => None,
        _ if matches!(
            analysis["diagnostic"].as_str(),
            Some("network_activity_requires_takeover" | "step_started" | "step_handoff_required")
        ) =>
        {
            Some(
                "Inspect the current website manually before continuing. An earlier browser step may have been interrupted.",
            )
        }
        _ => Some("Use the connected browser to review current application fields."),
    };
    Ok(
        json!({"packet":packet,"connected":false,"manual":false,"active_operation":null,
        "cancellation_pending":false,"in_page_network_isolation":false,"page_review_required":false,
        "assets":null,"analysis":analysis,"submission_mode":"manual_handoff",
        "automated_submission_enabled":false,"real_employer_submission_enabled":false,
        "owner_consent_available":false,"opportunity_context_available":false,"company_source_urls":[],
        "execution":null,"recovery":recovery}),
    )
}

async fn operation(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Value> {
    let revision: i64 =
        sqlx::query_scalar("SELECT revision::bigint FROM application_packets WHERE id=$1")
            .bind(id)
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?
            .ok_or(Failure("packet_not_found"))?;
    Ok(json!({"packet_revision":revision,"active_operation":null,"cancellation_pending":false}))
}

pub(crate) async fn dispatch(
    connection: &mut PgConnection,
    route: Route,
    config: &Configuration,
) -> Result<Value> {
    let mut tx = connection.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let data = match route {
        Route::Campaigns => listing(&mut tx, Record::Campaign).await?,
        Route::Campaign(id) => campaign(&mut tx, id).await?,
        Route::AgentStatus => agent_status(&mut tx, config).await?,
        Route::Submissions => listing(&mut tx, Record::Submission).await?,
        Route::BrowserStatus(id) => browser_status(&mut tx, id, config).await?,
        Route::BrowserOperation(id) => operation(&mut tx, id).await?,
    };
    tx.commit().await.map_err(db)?;
    Ok(data)
}
