//! Owner-only evidence projection. Connection status never initiates a provider action.
mod evidence;
mod legacy;
use crate::{Failure, Result, configuration::Configuration};
use chrono::{DateTime, Utc};
use serde::Serialize;
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection};
use std::collections::BTreeMap;
use std::path::PathBuf;

pub(crate) const PATH: &str = "/api/v1/local-agent/connections";

pub(crate) struct Settings {
    agy: bool,
    ollama: bool,
    gemini: bool,
    cohere: bool,
    evidence_dir: Option<PathBuf>,
    project_ref: String,
}
impl Settings {
    pub(crate) fn from_values(values: &BTreeMap<String, String>) -> Self {
        let present = |key| {
            values
                .get(key)
                .is_some_and(|value| !value.trim().is_empty())
        };
        let enabled = |key| {
            values
                .get(key)
                .is_some_and(|value| matches!(value.as_str(), "true" | "1"))
        };
        Self {
            agy: present("AGY_EXECUTABLE") || enabled("AGY_ENABLED"),
            ollama: enabled("OLLAMA_ENABLED") || enabled("OLLAMA_GENERATION_AUTHORIZED"),
            gemini: present("GEMINI_API_KEY"),
            cohere: present("COHERE_API_KEY"),
            evidence_dir: values
                .get("RUST_CONNECTION_EVIDENCE_DIR")
                .map(PathBuf::from)
                .filter(|path| path.is_absolute()),
            project_ref: values
                .get("SUPABASE_PROJECT_REF")
                .cloned()
                .unwrap_or_else(|| "luvdmwnlwaqgvfwlmlom".to_owned()),
        }
    }
}

#[derive(Serialize)]
struct Row {
    name: String,
    group: &'static str,
    configuration_status: &'static str,
    state: String,
    identity_verification: &'static str,
    capability_verification: &'static str,
    capabilities: Value,
    last_verification_time: Option<DateTime<Utc>>,
    actual_evidence_type: String,
    blocker: Option<&'static str>,
    latest_error_category: Option<&'static str>,
    owner_authorization_required: bool,
    may_consume_paid_credits: bool,
    safe_next_action: &'static str,
    help_url: Option<String>,
    platform: Option<String>,
}
impl Row {
    fn new(
        name: impl Into<String>,
        group: &'static str,
        configured: bool,
        next: &'static str,
    ) -> Self {
        Self {
            name: name.into(),
            group,
            configuration_status: if configured {
                "configured"
            } else {
                "not_configured"
            },
            state: if configured {
                "credentials_configured"
            } else {
                "not_configured"
            }
            .into(),
            identity_verification: "unverified",
            capability_verification: "unverified",
            capabilities: json!([]),
            last_verification_time: None,
            actual_evidence_type: "configuration_inspection".into(),
            blocker: None,
            latest_error_category: None,
            owner_authorization_required: false,
            may_consume_paid_credits: false,
            safe_next_action: next,
            help_url: None,
            platform: None,
        }
    }
    fn evidence(&mut self, state: &str, basis: &str, time: Option<DateTime<Utc>>) {
        self.state = state.into();
        self.actual_evidence_type = basis.into();
        self.last_verification_time = time;
    }
}

fn db(_: sqlx::Error) -> Failure {
    Failure("connection_report_database_error")
}
fn stored_time(value: &Value) -> Option<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(value.as_str()?)
        .ok()
        .map(|value| value.to_utc())
}

pub(crate) async fn dispatch(
    connection: &mut PgConnection,
    method: &str,
    body: &[u8],
    config: &Configuration,
) -> Result<Value> {
    if method != "GET" {
        return Err(Failure("connection_report_method_not_allowed"));
    }
    if !body.is_empty() {
        return Err(Failure("invalid_connection_report_request"));
    }
    snapshot(connection, config).await
}

pub(crate) async fn snapshot(
    connection: &mut PgConnection,
    config: &Configuration,
) -> Result<Value> {
    let mut snapshot = connection.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *snapshot)
        .await
        .map_err(db)?;
    let rows = report(&mut snapshot, config).await?;
    snapshot.commit().await.map_err(db)?;
    Ok(json!(rows))
}

async fn report(connection: &mut PgConnection, config: &Configuration) -> Result<Vec<Row>> {
    let (now, database, schema, role): (DateTime<Utc>, String, Option<String>, String) = sqlx::query_as(
        "SELECT clock_timestamp(),current_database()::text,current_schema()::text,current_user::text",
    ).fetch_one(&mut *connection).await.map_err(db)?;
    if database != config.database
        || schema.as_deref() != Some(config.schema.as_str())
        || role != config.role
    {
        return Err(Failure("agent_database_target_mismatch"));
    }
    let real = !config.fixture;
    let mut database = Row::new(
        "Supabase PostgreSQL",
        "core",
        true,
        "Review the configured database and the restricted runtime role.",
    );
    database.evidence(
        if real {
            "capability_verified"
        } else {
            "degraded"
        },
        if real {
            "configured_role_tls_query"
        } else {
            "disposable_test"
        },
        Some(now),
    );
    database.identity_verification = if real {
        "pinned_runtime_database_role"
    } else {
        "test_database_only"
    };
    database.capability_verification = if real {
        "current_query_succeeded"
    } else {
        "test_only"
    };
    database.capabilities = json!(["persistence", "private_sql"]);
    database.owner_authorization_required = !real;

    let mut api = Row::new(
        "Rust API",
        "core",
        true,
        "Use the local dashboard for owner commands.",
    );
    api.evidence(
        "capability_verified",
        "current_authenticated_api_request",
        Some(now),
    );
    api.identity_verification = "owner_bearer_verified";
    api.capability_verification = "current_request";
    api.capabilities = json!(["owner_api"]);
    let mut rows = vec![database, api];
    rows.extend(legacy::core(&config.connection_settings));
    rows.extend(evidence::browser(connection, config, now).await?);
    rows.push(evidence::telegram(connection, config, now).await?);
    rows.extend(evidence::candidate(connection, config, now).await?);

    for portal in crate::platform_sessions::listing(connection).await? {
        let time = stored_time(&portal["last_verification_time"]);
        let mut row = Row::new(
            portal["name"].as_str().unwrap_or_default(),
            "platforms",
            time.is_some(),
            "Sign in in your browser, then use Check this portal session in the extension.",
        );
        row.evidence(
            portal["state"].as_str().unwrap_or("owner_action_required"),
            portal["evidence_type"].as_str().unwrap_or("none"),
            time,
        );
        row.identity_verification = "account_identity_unverified";
        row.capability_verification = "manual_handoff_available";
        row.capabilities = portal["capabilities"].clone();
        row.platform = portal["platform"].as_str().map(str::to_owned);
        row.help_url = portal["login_url"].as_str().map(str::to_owned);
        row.owner_authorization_required = portal["owner_acceptance_required"] == true;
        if row.owner_authorization_required {
            row.blocker = Some("manual_handoff_acceptance_pending");
        }
        rows.push(row);
    }
    let mut linkedin = Row::new(
        "LinkedIn",
        "platforms",
        false,
        "Open the job portal for manual review.",
    );
    linkedin.state = "manual_only".into();
    linkedin.capabilities = json!(["manual_handoff", "url_preview"]);
    linkedin.help_url = Some("https://www.linkedin.com/jobs/".into());
    rows.push(linkedin);

    let boards = ["greenhouse", "lever", "ashby", "smartrecruiters"]
        .iter()
        .any(|source| {
            config
                .sources
                .public_boards(source)
                .and_then(Value::as_object)
                .is_some_and(|boards| !boards.is_empty())
        });
    let mut feeds = Row::new(
        "Public job sources",
        "platforms",
        boards,
        "Review saved boards and the public discovery schedule.",
    );
    feeds.capabilities = json!(["public_read_adapters"]);
    rows.push(feeds);
    rows.extend(evidence::gmail(connection, config, now).await?);
    let settings = &config.connection_settings;
    for (name, configured, paid, actions) in [
        (
            "AGY CLI",
            settings.agy,
            true,
            json!(["structured_answer_configuration"]),
        ),
        (
            "Ollama",
            settings.ollama,
            false,
            json!(["local_generation_if_model_installed"]),
        ),
        (
            "Gemini",
            settings.gemini,
            true,
            json!(["structured_answers"]),
        ),
        (
            "Cohere",
            settings.cohere,
            true,
            json!(["structured_answers"]),
        ),
        (
            "Apify",
            config.apify_metadata.token_configured(),
            true,
            json!(["actor_metadata", "job_discovery_requires_budget"]),
        ),
    ] {
        let mut row = Row::new(
            name,
            "ai",
            configured,
            "Review deployment authorization and the saved provider budget.",
        );
        row.capabilities = actions;
        row.may_consume_paid_credits = paid;
        row.blocker = Some(if configured {
            "current_provider_capability_unverified"
        } else {
            "provider_configuration_required"
        });
        if name == "AGY CLI" {
            legacy::agy(&mut row, settings);
        }
        rows.push(row);
    }
    for p in &config.contact_enrichment.providers {
        let mut row = Row::new(
            if p.name == "apollo" {
                "Apollo"
            } else {
                "SignalHire"
            },
            "ai",
            p.credentials_configured,
            "Review contact evidence and enrichment permissions in the dashboard.",
        );
        row.capabilities = json!(["cached_contacts", "enrichment_requires_approval"]);
        row.may_consume_paid_credits = true;
        row.blocker = Some(if p.enabled {
            "provider_entitlement_unverified"
        } else {
            "enrichment_disabled"
        });
        rows.push(row);
    }
    let mut deterministic = Row::new(
        "Deterministic answers",
        "ai",
        true,
        "Review answers against the saved evidence in the application packet.",
    );
    deterministic.evidence("capability_verified", "existing_local_implementation", None);
    deterministic.capability_verification = "local_only";
    deterministic.capabilities = json!(["grounded_deterministic_answers"]);
    rows.push(deterministic);
    Ok(rows)
}
