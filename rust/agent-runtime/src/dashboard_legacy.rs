//! Owner-authenticated legacy dashboard, integration registry, preset, and browser asset policy reads.
//! No provider IO, browser takeover, application admission, or secret exposure occurs here.
use crate::{
    Failure, Result,
    configuration::{Configuration, boolean},
    execution,
    startup_catalog::contract::{self, Kind},
};
use chrono::{DateTime, Duration, Utc};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use std::collections::{BTreeMap, BTreeSet};

const RESTRICTED_ASSET_HOSTS: &[&str] = &[
    "linkedin.com",
    "naukri.com",
    "wellfound.com",
    "instahyre.com",
    "internshala.com",
    "accounts.google.com",
];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Route {
    Connections,
    Manifest,
    Presets,
    Integrations,
    StartupIntegrationsStatus,
    BrowserAssetPolicy,
}

pub(crate) fn route(path: &str) -> Option<Route> {
    match path {
        "/api/v1/dashboard/connections" => Some(Route::Connections),
        "/api/v1/dashboard/onboarding/manifest" => Some(Route::Manifest),
        "/api/v1/dashboard/presets" => Some(Route::Presets),
        "/api/v1/integrations" => Some(Route::Integrations),
        "/api/v1/startups/integrations/status" => Some(Route::StartupIntegrationsStatus),
        "/api/v1/browser-applications/policy" => Some(Route::BrowserAssetPolicy),
        _ => None,
    }
}

pub(crate) struct Settings {
    pub(crate) gemini_configured: bool,
    pub(crate) llm_monthly_max_requests: i64,
    pub(crate) serper_configured: bool,
    pub(crate) serper_authorized: bool,
    pub(crate) serper_monthly_limit: i64,
    pub(crate) linkedin_retention_authorized: bool,
    pub(crate) apify_token_configured: bool,
    pub(crate) apify_monthly_limit_usd: f64,
    pub(crate) gmail_sending_enabled: bool,
    pub(crate) provider_verification_ttl_hours: i64,
    pub(crate) browser_asset_origins: Vec<String>,
}

fn asset_origin(raw: &str, testing: bool) -> Result<String> {
    let invalid = || Failure("invalid_browser_asset_origin");
    if !raw.is_ascii()
        || raw.len() > 2048
        || raw.bytes().any(|b| b <= 32 || b == 127 || b == b'\\')
        || raw.contains(['?', '#'])
    {
        return Err(invalid());
    }
    let url = reqwest::Url::parse(raw).map_err(|_| invalid())?;
    let host = url.host_str().ok_or_else(invalid)?;
    if !url.username().is_empty()
        || url.password().is_some()
        || !url.query().unwrap_or("").is_empty()
        || !url.fragment().unwrap_or("").is_empty()
        || !matches!(url.path(), "" | "/")
        || url.port() == Some(0)
        || host.ends_with('.')
        || !host
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'.' || b == b'-')
        || !host.contains('.')
        || host.ends_with(".local")
        || host.ends_with(".internal")
        || host.ends_with(".localhost")
        || host.ends_with(".localdomain")
    {
        return Err(invalid());
    }
    if RESTRICTED_ASSET_HOSTS
        .iter()
        .any(|item| host == *item || host.ends_with(&format!(".{item}")))
    {
        return Err(invalid());
    }
    if let Ok(ip) = host.parse::<std::net::IpAddr>()
        && !crate::configuration::is_public_ip(ip)
        && !(testing && host == "127.0.0.1")
    {
        return Err(invalid());
    }
    let scheme = url.scheme();
    if scheme != "https" && !(testing && host == "127.0.0.1" && scheme == "http") {
        return Err(invalid());
    }
    let port = url
        .port()
        .unwrap_or(if scheme == "https" { 443 } else { 80 });
    Ok(format!("{scheme}://{host}:{port}"))
}

impl Settings {
    pub(crate) fn from_values(values: &BTreeMap<String, String>, testing: bool) -> Result<Self> {
        let present = |key: &str| values.get(key).is_some_and(|v| !v.trim().is_empty());
        let integer = |key: &str, default: &str, min: i64, max: i64| -> Result<i64> {
            values
                .get(key)
                .map(String::as_str)
                .unwrap_or(default)
                .parse::<i64>()
                .ok()
                .filter(|n| (min..=max).contains(n))
                .ok_or(Failure("invalid_dashboard_settings"))
        };
        let apify_monthly_limit_usd = values
            .get("APIFY_MONTHLY_LIMIT_USD")
            .map(String::as_str)
            .unwrap_or("0")
            .parse::<f64>()
            .ok()
            .filter(|n| n.is_finite() && *n >= 0.0)
            .ok_or(Failure("invalid_dashboard_settings"))?;
        let origins_raw = values
            .get("BROWSER_ASSET_ORIGINS")
            .map(String::as_str)
            .unwrap_or("[]");
        let parsed_origins: Vec<String> = serde_json::from_str(origins_raw)
            .map_err(|_| Failure("invalid_browser_asset_origin"))?;
        if parsed_origins.len() > 8 {
            return Err(Failure("invalid_browser_asset_origin"));
        }
        let mut normalized_origins = BTreeSet::new();
        for origin in parsed_origins {
            normalized_origins.insert(asset_origin(&origin, testing)?);
        }
        Ok(Self {
            gemini_configured: present("GEMINI_API_KEY") && present("LLM_MODEL"),
            llm_monthly_max_requests: integer("LLM_MONTHLY_MAX_REQUESTS", "200", 0, 10000)?,
            serper_configured: present("SERPER_API_KEY")
                && boolean(values, "PEOPLE_SEARCH_ENABLED", false)?,
            serper_authorized: boolean(values, "PUBLIC_SEARCH_RIGHTS_REVIEWED", false)?,
            serper_monthly_limit: integer("SERPER_MONTHLY_LIMIT", "100", 0, 9_999_999_999)?,
            linkedin_retention_authorized: boolean(
                values,
                "LINKEDIN_SEARCH_RETENTION_AUTHORIZED",
                false,
            )?,
            apify_token_configured: present("APIFY_API_TOKEN"),
            apify_monthly_limit_usd,
            gmail_sending_enabled: boolean(values, "GMAIL_SENDING_ENABLED", false)?,
            provider_verification_ttl_hours: integer(
                "PROVIDER_VERIFICATION_TTL_HOURS",
                "24",
                1,
                168,
            )?,
            browser_asset_origins: normalized_origins.into_iter().collect(),
        })
    }
}

pub(crate) fn browser_policy(settings: &Settings) -> Value {
    let data = json!({
        "origins": settings.browser_asset_origins,
        "kinds": ["font", "script", "stylesheet"],
        "max_asset_bytes": 4 * 1024 * 1024,
        "max_total_bytes": 32 * 1024 * 1024,
        "max_requests": 128,
        "max_parallel": 4,
        "phase": "initial_load_before_analysis_or_takeover",
        "credentials": false,
    });
    let canonical = serde_json::to_string(&data).expect("canonical asset policy JSON");
    let digest = format!("{:x}", Sha256::digest(canonical.as_bytes()));
    let mut out = data.as_object().cloned().unwrap_or_default();
    out.insert("digest".into(), json!(digest));
    Value::Object(out)
}

pub(crate) fn onboarding_manifest() -> Value {
    const LINKS: &[(&str, &str, &str, Option<&str>)] = &[
        ("github", "GitHub", "https://github.com/karanagg166", None),
        (
            "linkedin",
            "LinkedIn",
            "https://www.linkedin.com/in/karan-aggarwal-a13427276/",
            None,
        ),
        (
            "portfolio",
            "Portfolio",
            "https://portfolio-kappa-bay-76.vercel.app/",
            None,
        ),
        (
            "other",
            "Portfolio source",
            "https://github.com/karanagg166/PORTFOLIO",
            None,
        ),
        (
            "other",
            "Exam Arena source",
            "https://github.com/karanagg166/ExamArena",
            None,
        ),
        (
            "other",
            "Exam Arena live",
            "https://exam-arena-mu.vercel.app/",
            None,
        ),
        (
            "other",
            "Quick Clinic source",
            "https://github.com/karanagg166/Quick-Clinic",
            None,
        ),
        (
            "other",
            "Quick Clinic live",
            "https://quick-clinic-nine.vercel.app/",
            None,
        ),
        (
            "other",
            "ShopSizzle source (optional)",
            "https://github.com/karanagg166/ShopSizzle",
            Some("project_relationship_requires_review"),
        ),
        (
            "other",
            "ShopSizzle live (optional)",
            "https://shop-sizzle-seven.vercel.app/",
            Some("availability_and_project_relationship_require_review"),
        ),
        (
            "codeforces",
            "Codeforces",
            "https://codeforces.com/profile/KaranCipherKnight",
            None,
        ),
        (
            "leetcode",
            "LeetCode",
            "https://leetcode.com/u/aggarwalkaran241/",
            None,
        ),
        (
            "other",
            "CodeChef",
            "https://www.codechef.com/users/code_rush03",
            None,
        ),
        (
            "geeksforgeeks",
            "GeeksforGeeks (resume)",
            "https://www.geeksforgeeks.org/user/aggarwalkaran241/",
            Some("conflicting_gfg"),
        ),
        (
            "geeksforgeeks",
            "GeeksforGeeks (GitHub README)",
            "https://www.geeksforgeeks.org/user/aggarwalklmvk/",
            Some("conflicting_gfg"),
        ),
        (
            "other",
            "CSES (optional)",
            "https://cses.fi/user/225098",
            Some("independent_confirmation_required"),
        ),
        (
            "resume",
            "Resume short link (destination unresolved)",
            "https://url-shortner-jet-rho.vercel.app/r2wL9UE",
            Some("destination_unresolved"),
        ),
    ];
    let resources: Vec<Value> = LINKS
        .iter()
        .map(|(resource_type, label, url, issue)| {
            json!({
                "resource_type": resource_type,
                "label": label,
                "url": url,
                "status": if *issue == Some("conflicting_gfg") {
                    "conflicting"
                } else {
                    "awaiting_owner_review"
                },
                "issue": issue,
                "user_confirmed": false,
                "availability": "not_checked",
            })
        })
        .collect();
    json!({
        "resources": resources,
        "resume_status": "awaiting_upload",
        "facts_verified": false,
    })
}

pub(crate) fn dashboard_connections(config: &Configuration) -> Value {
    let apify_reviewed = config.sources.jobs(Utc::now())["sources"]
        .as_array()
        .is_some_and(|rows| {
            rows.iter().any(|row| {
                row["adapter_type"] == "apify"
                    && row["enabled"] == true
                    && row["availability"] == "available"
            })
        });
    let s = &config.dashboard_legacy;
    json!({
        "providers": [
            {
                "provider": "gemini",
                "configured": s.gemini_configured,
                "authorized": false,
                "live_verified": false,
                "capability": "grounded_answers_after_explicit_request",
                "budget": s.llm_monthly_max_requests,
                "next_action": "Configure model and key server-side; authorize each AI generation. No resume PDF is sent by onboarding.",
            },
            {
                "provider": "serper",
                "configured": s.serper_configured,
                "authorized": s.serper_authorized,
                "live_verified": false,
                "capability": "permission_reviewed_company_research",
                "budget": s.serper_monthly_limit,
                "next_action": "Review search and retention rights, cost and consent before each research run.",
            },
            {
                "provider": "apify",
                "configured": s.apify_token_configured,
                "authorized": apify_reviewed,
                "live_verified": false,
                "capability": "operator_reviewed_actor_only",
                "budget": s.apify_monthly_limit_usd,
                "next_action": "Configure an authorized actor, terms, monthly USD budget and per-run cap. No execution from this screen.",
            },
            {
                "provider": "notifications",
                "configured": true,
                "authorized": true,
                "live_verified": false,
                "capability": "in_app_only",
                "budget": 0,
                "next_action": "Save in-app preferences. External delivery is disabled.",
            },
        ]
    })
}

fn db(_: sqlx::Error) -> Failure {
    Failure("dashboard_database_error")
}

fn config_fingerprint(provider: &str, config: &Configuration) -> String {
    let mut cfg = Map::new();
    cfg.insert("adapter_version".into(), json!(1));
    if provider == "greenhouse" {
        cfg.insert(
            "boards".into(),
            config
                .sources
                .public_boards("greenhouse")
                .cloned()
                .unwrap_or_else(|| json!({})),
        );
    } else if matches!(provider, "lever" | "ashby" | "smartrecruiters") {
        cfg.insert(
            "boards".into(),
            config
                .sources
                .public_boards(provider)
                .cloned()
                .unwrap_or_else(|| json!({})),
        );
        if provider == "lever" {
            cfg.insert("region".into(), json!(config.sources.lever_region()));
        }
    }
    cfg.insert("provider".into(), json!(provider));
    let canonical = serde_json::to_string(&Value::Object(cfg)).unwrap_or_default();
    format!("{:x}", Sha256::digest(canonical.as_bytes()))
}

fn parse_rfc3339(value: &Value) -> Option<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(value.as_str()?)
        .ok()
        .map(|d| d.to_utc())
}

pub(crate) async fn startup_status_in(
    tx: &mut Transaction<'_, Postgres>,
    config: &Configuration,
    now: DateTime<Utc>,
) -> Result<Value> {
    let checks: Vec<Value> = sqlx::query_scalar(
        "SELECT DISTINCT ON (provider) jsonb_build_object(
            'id', id,
            'provider', provider,
            'operation', operation,
            'configuration_fingerprint', configuration_fingerprint,
            'state', state,
            'checked_at', checked_at,
            'finished_at', finished_at,
            'http_status', http_status,
            'result_count', result_count,
            'schema_valid', schema_valid,
            'is_live', is_live,
            'evidence_urls', evidence_urls,
            'error_category', error_category
        ) FROM provider_connection_checks ORDER BY provider, checked_at DESC, id",
    )
    .fetch_all(&mut **tx)
    .await
    .map_err(db)?;
    let by_provider: BTreeMap<String, Value> = checks
        .into_iter()
        .filter_map(|row| Some((row["provider"].as_str()?.to_owned(), row)))
        .collect();
    let windows: Vec<(String, DateTime<Utc>)> =
        sqlx::query_as("SELECT provider, next_allowed_at FROM provider_access_windows")
            .fetch_all(&mut **tx)
            .await
            .map_err(db)?;
    let windows: BTreeMap<String, DateTime<Utc>> = windows.into_iter().collect();

    let sources = config.sources.startups(now)["sources"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    let ttl = Duration::hours(config.dashboard_legacy.provider_verification_ttl_hours);
    let testing_stale = Duration::milliseconds((config.discovery_timeout_seconds * 1000.0) as i64)
        + Duration::seconds(60);

    let mut providers = Vec::with_capacity(sources.len());
    for source in sources {
        let provider_name = source["provider"].as_str().unwrap_or_default().to_owned();
        let mut state = if source["availability"] == "unsupported" {
            "unsupported"
        } else if source["configured"] != true {
            "not_configured"
        } else if source["authorized"] != true {
            "authorization_required"
        } else {
            "configured_not_tested"
        };
        let check = by_provider.get(&provider_name);
        let fresh = check.is_some_and(|c| {
            c["is_live"] == true
                && c["configuration_fingerprint"].as_str()
                    == Some(config_fingerprint(&provider_name, config).as_str())
                && parse_rfc3339(&c["finished_at"]).is_some_and(|fin| fin >= now - ttl)
        });
        if source["configured"] == true
            && source["authorized"] == true
            && let Some(c) = check
            && c["is_live"] == true
            && let Some(s) = c["state"].as_str()
        {
            state = match s {
                "live_verified" if !fresh => "configured_not_tested",
                "testing"
                    if parse_rfc3339(&c["checked_at"]).is_some_and(|t| t < now - testing_stale) =>
                {
                    "failed"
                }
                "live_verified" => "live_verified",
                "testing" => "testing",
                "failed" => "failed",
                "rate_limited" => "rate_limited",
                "authorization_required" => "authorization_required",
                "not_configured" => "not_configured",
                "configured_not_tested" => "configured_not_tested",
                "unsupported" => "unsupported",
                _ => state,
            };
        }
        let window = windows.get(&provider_name).copied();
        if let Some(c) = check
            && c["error_category"] == "local_rate_limit"
            && window.is_some_and(|next| next > now)
        {
            state = "rate_limited";
        }
        let last_check = check.map(|c| {
            json!({
                "id": c["id"],
                "provider": c["provider"],
                "operation": c["operation"],
                "state": c["state"],
                "checked_at": c["checked_at"],
                "finished_at": c["finished_at"],
                "http_status": c["http_status"],
                "result_count": c["result_count"],
                "schema_valid": c["schema_valid"],
                "is_live": c["is_live"],
                "evidence_urls": c["evidence_urls"],
                "error_category": c["error_category"],
            })
        });
        let mut entry = source.as_object().cloned().unwrap_or_default();
        entry.insert(
            "next_allowed_at".into(),
            window.map(|t| json!(t.to_rfc3339())).unwrap_or(Value::Null),
        );
        entry.insert("state".into(), json!(state));
        entry.insert(
            "live_verified".into(),
            json!(state == "live_verified" && fresh),
        );
        entry.insert("verification_fresh".into(), json!(fresh));
        entry.insert("last_check".into(), last_check.unwrap_or(Value::Null));
        providers.push(Value::Object(entry));
    }
    Ok(json!({
        "providers": providers,
        "verification_ttl_hours": config.dashboard_legacy.provider_verification_ttl_hours,
    }))
}

pub(crate) async fn integrations_in(
    tx: &mut Transaction<'_, Postgres>,
    config: &Configuration,
    now: DateTime<Utc>,
) -> Result<Value> {
    let startup_status = startup_status_in(tx, config, now).await?;
    let job_sources = config.sources.jobs(now)["sources"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    let provider_diagnostics: BTreeMap<String, Value> = startup_status["providers"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|row| Some((row["provider"].as_str()?.to_owned(), row.clone())))
        .collect();

    let mut output = Vec::new();
    for platform in [
        "linkedin",
        "naukri",
        "instahyre",
        "work_at_a_startup",
        "wellfound",
        "internshala",
        "greenhouse",
    ] {
        let source = job_sources.iter().find(|s| s["id"] == platform);
        let available = source.is_some_and(|s| s["availability"] == "available");
        let status = if platform == "internshala" {
            "manual_only"
        } else if available {
            "mock_tested_only"
        } else {
            "requires_configuration"
        };
        let li_status = if config.dashboard_legacy.serper_configured
            && config.dashboard_legacy.serper_authorized
            && config.dashboard_legacy.linkedin_retention_authorized
        {
            "mock_tested_only"
        } else {
            "requires_configuration"
        };
        let mut caps = Map::new();
        caps.insert(
            "discover_jobs".into(),
            json!(if platform == "linkedin" {
                "manual_only"
            } else {
                status
            }),
        );
        caps.insert("submit_application".into(), json!("manual_only"));
        caps.insert(
            "generate_answers".into(),
            json!(if config.dashboard_legacy.gemini_configured {
                "mock_tested_only"
            } else {
                "requires_configuration"
            }),
        );
        if matches!(platform, "work_at_a_startup" | "wellfound") {
            caps.insert("discover_companies".into(), json!("manual_only"));
        }
        if platform == "linkedin" {
            caps.insert("discover_people".into(), json!(li_status));
            caps.insert("send_email".into(), json!("unsupported"));
        }
        let diagnostic = provider_diagnostics.get(platform);
        let live_verified = diagnostic.is_some_and(|d| d["live_verified"] == true);
        if live_verified {
            caps.insert("discover_jobs".into(), json!("live_verified"));
        }
        output.push(json!({
            "platform": platform,
            "capabilities": Value::Object(caps),
            "live_verified": live_verified,
            "discovery_connection": diagnostic.cloned().unwrap_or(Value::Null),
        }));
    }

    for provider in &config.contact_enrichment.providers {
        let configured = provider.credentials_configured && provider.enabled;
        output.push(json!({
            "platform": provider.name,
            "live_verified": false,
            "capabilities": {
                "enrich_contacts": if configured { "mock_tested_only" } else { "requires_configuration" },
                "discover_people": if provider.name == "apollo" {
                    if configured { "mock_tested_only" } else { "requires_configuration" }
                } else {
                    "unsupported"
                },
                "send_email": "unsupported",
                "submit_application": "unsupported",
            },
        }));
    }

    let oauth_configured = config.mailboxes.provider().is_ok();
    let gmail =
        crate::gmail_legacy::status_in(tx, &config.gmail_accounts, oauth_configured).await?;
    let gmail_connected = gmail["status"] == "connected";
    let send_capability = if config.dashboard_legacy.gmail_sending_enabled
        && gmail["send_capability"] == "send_authorized"
    {
        "available"
    } else if !config.dashboard_legacy.gmail_sending_enabled {
        "unsupported"
    } else if gmail_connected {
        "requires_authorization"
    } else {
        "requires_configuration"
    };
    output.push(json!({
        "platform": "gmail",
        "live_verified": gmail["live_verified"],
        "connection": gmail,
        "capabilities": {
            "connect_account": if gmail_connected {
                "live_verified"
            } else if oauth_configured {
                "requires_authorization"
            } else {
                "requires_configuration"
            },
            "read_account_identity": if gmail_connected {
                "live_verified"
            } else {
                "requires_authorization"
            },
            "read_job_alerts": "unsupported",
            "create_email_draft": "unsupported",
            "prepare_local_draft": "available",
            "send_email": send_capability,
            "send_requires_owner_confirmation": true,
            "submit_application": "unsupported",
        },
    }));
    Ok(json!({
        "connectors": output,
        "startup_discovery": startup_status,
    }))
}

async fn get_presets(tx: &mut Transaction<'_, Postgres>) -> Result<Value> {
    let saved: Option<Value> =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key='startup_presets'")
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?;
    Ok(saved.unwrap_or_else(|| json!({"presets": []})))
}

async fn save_preset(connection: &mut PgConnection, body: &[u8]) -> Result<Value> {
    let invalid = || Failure("invalid_dashboard_preset");
    let raw: Value = serde_json::from_slice(body).map_err(|_| invalid())?;
    let object = raw.as_object().ok_or_else(invalid)?;
    if object.len() != 2 || !object.contains_key("name") || !object.contains_key("filters") {
        return Err(invalid());
    }
    let name = object
        .get("name")
        .and_then(Value::as_str)
        .filter(|s| (1..=80).contains(&s.chars().count()))
        .ok_or_else(invalid)?
        .to_owned();
    let filters = contract::normalize(
        Kind::Filters,
        object.get("filters").cloned().ok_or_else(invalid)?,
    )?;

    let mut tx = connection.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    execution::lock_owner_in(&mut tx).await?;
    let existing: Option<Value> = sqlx::query_scalar(
        "SELECT value FROM owner_preferences WHERE key='startup_presets' FOR UPDATE",
    )
    .fetch_optional(&mut *tx)
    .await
    .map_err(db)?;
    let mut presets: Vec<Value> = existing
        .as_ref()
        .and_then(|v| v["presets"].as_array())
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .filter(|v| v["name"].as_str() != Some(name.as_str()))
        .collect();
    presets.push(json!({"name": name, "filters": filters}));
    if presets.len() > 20 {
        return Err(Failure("dashboard_preset_limit"));
    }
    let updated = json!({"presets": presets});
    let affected = sqlx::query(
        "INSERT INTO owner_preferences (key, value, created_at, updated_at)
         VALUES ('startup_presets', $1, clock_timestamp(), clock_timestamp())
         ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = clock_timestamp()",
    )
    .bind(&updated)
    .execute(&mut *tx)
    .await
    .map_err(db)?
    .rows_affected();
    if affected != 1 {
        return Err(Failure("dashboard_write_ack_failed"));
    }
    tx.commit()
        .await
        .map_err(|_| Failure("dashboard_commit_outcome_unknown"))?;
    Ok(updated)
}

pub(crate) async fn dispatch(
    connection: &mut PgConnection,
    route: Route,
    method: &str,
    query: Option<&str>,
    body: &[u8],
    config: &Configuration,
) -> Result<Value> {
    let allowed = match route {
        Route::Presets => matches!(method, "GET" | "POST"),
        _ => method == "GET",
    };
    if !allowed {
        return Err(Failure(if matches!(route, Route::Presets) {
            "dashboard_method_not_allowed"
        } else {
            "resource_read_method_not_allowed"
        }));
    }
    if query.is_some() || (method == "GET" && !body.is_empty()) {
        return Err(Failure("invalid_dashboard_request"));
    }
    match route {
        Route::Manifest => Ok(onboarding_manifest()),
        Route::Connections => Ok(dashboard_connections(config)),
        Route::BrowserAssetPolicy => Ok(browser_policy(&config.dashboard_legacy)),
        Route::Presets if method == "POST" => save_preset(connection, body).await,
        Route::Presets | Route::StartupIntegrationsStatus | Route::Integrations => {
            let mut tx = connection.begin().await.map_err(db)?;
            sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                .execute(&mut *tx)
                .await
                .map_err(db)?;
            let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
                .fetch_one(&mut *tx)
                .await
                .map_err(db)?;
            let result = match route {
                Route::Presets => get_presets(&mut tx).await?,
                Route::StartupIntegrationsStatus => startup_status_in(&mut tx, config, now).await?,
                Route::Integrations => integrations_in(&mut tx, config, now).await?,
                _ => unreachable!(),
            };
            tx.commit().await.map_err(db)?;
            Ok(result)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn browser_asset_policy_digest_matches_canonical_default() {
        let settings = Settings::from_values(&BTreeMap::new(), true).expect("default settings");
        let policy = browser_policy(&settings);
        assert_eq!(policy["origins"], json!([]));
        assert_eq!(policy["kinds"], json!(["font", "script", "stylesheet"]));
        assert_eq!(policy["credentials"], json!(false));
        assert!(
            policy["digest"]
                .as_str()
                .is_some_and(|s| s.len() == 64 && s.bytes().all(|b| b.is_ascii_hexdigit()))
        );
    }

    #[test]
    fn browser_asset_origin_blocks_restricted_portal_hosts() {
        let mut values = BTreeMap::new();
        values.insert(
            "BROWSER_ASSET_ORIGINS".into(),
            r#"["https://static.naukri.com"]"#.into(),
        );
        assert_eq!(
            Settings::from_values(&values, false).err(),
            Some(Failure("invalid_browser_asset_origin"))
        );
    }

    #[test]
    fn onboarding_manifest_keeps_unverified_proposals() {
        let m = onboarding_manifest();
        assert_eq!(m["facts_verified"], json!(false));
        assert_eq!(m["resume_status"], json!("awaiting_upload"));
        assert_eq!(m["resources"].as_array().map(Vec::len), Some(17));
    }
}
