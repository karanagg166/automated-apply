//! Explicit private configuration. Values and errors never implement Debug with secrets.
use crate::{Failure, Result};
use reqwest::Url;
use sha2::{Digest, Sha256};
use sqlx::{
    Connection, PgConnection,
    postgres::{PgConnectOptions, PgSslMode},
};
use std::{
    collections::BTreeMap,
    fs::File,
    io::Read,
    net::{IpAddr, SocketAddr},
    os::unix::fs::{MetadataExt, OpenOptionsExt},
    path::Path,
    time::Duration,
};

pub struct Configuration {
    options: PgConnectOptions,
    pub(crate) token: String,
    pub(crate) hosts: Vec<String>,
    pub(crate) origins: Vec<String>,
    pub(crate) require_tls: bool,
    pub(crate) trust_proxy: bool,
    pub(crate) listen: SocketAddr,
    pub(crate) local_socket: Option<std::path::PathBuf>,
    pub(crate) fixture: bool,
    pub(crate) target_identity: String,
    pub(crate) database: String,
    pub(crate) schema: String,
    pub(crate) role: String,
    pub(crate) telegram: Option<crate::telegram::Settings>,
    pub(crate) models: Option<crate::model_policy::Models>,
    pub(crate) profile_live: bool,
    pub(crate) resource_defaults: BTreeMap<String, String>,
    pub(crate) owner_signing: Option<crate::owner_proof::SigningKey>,
    pub(crate) answers: crate::answer_service::Settings,
    pub(crate) questionnaire_answers: Option<crate::answer_service::Settings>,
    pub(crate) resume_review: crate::resume_review::Settings,
    pub(crate) resumes: crate::private_resume::Settings,
    pub(crate) browser: crate::browser_inventory::Browser,
    pub(crate) browser_profiles: crate::browser_profiles::Settings,
    pub(crate) mailboxes: crate::mailboxes::Settings,
    pub(crate) gmail_accounts: crate::gmail_accounts::Settings,
    pub(crate) contacts: crate::contacts::Settings,
    pub(crate) outreach: crate::outreach::Settings,
    pub(crate) sources: crate::source_registry::Settings,
    pub(crate) apify_metadata: crate::apify_metadata::transport::Client,
    pub(crate) people_research: crate::people_research::settings::Settings,
    pub(crate) people_search_client: Option<crate::people_research::transport::Client>,
    pub(crate) contact_enrichment: crate::contacts::enrichment::Settings,
    pub(crate) contact_providers: crate::contacts::enrichment::providers::Clients,
    pub(crate) apollo_eligibility: crate::contacts::enrichment::capabilities::Eligibility,
    pub(crate) packets: crate::packet_service::Settings,
    pub(crate) legacy_discovery_enabled: bool,
    pub(crate) discovery_timeout_seconds: f64,
}
impl Configuration {
    pub fn listen(&self) -> SocketAddr {
        self.listen
    }
    pub fn local_socket(&self) -> Option<&Path> {
        self.local_socket.as_deref()
    }
    pub fn is_fixture(&self) -> bool {
        self.fixture
    }
    pub fn target_identity(&self) -> &str {
        &self.target_identity
    }
    pub fn load(path: &Path) -> Result<Self> {
        Self::from_values(&private_values(path)?)
    }
    pub fn from_values(values: &BTreeMap<String, String>) -> Result<Self> {
        let get = |key: &str, default: &str| {
            values
                .get(key)
                .cloned()
                .unwrap_or_else(|| default.to_owned())
        };
        let environment = get("ENVIRONMENT", "production");
        if !matches!(
            environment.as_str(),
            "testing" | "production" | "staging" | "development"
        ) {
            return Err(Failure("invalid_environment"));
        }
        let fixture = boolean(values, "RUST_RUNTIME_FIXTURE", false)?;
        if fixture != (environment == "testing") {
            return Err(Failure("explicit_fixture_boundary_required"));
        }
        let token = get("JOB_AGENT_API_TOKEN", "");
        let unique = token
            .chars()
            .collect::<std::collections::BTreeSet<_>>()
            .len();
        if token.len() < 32
            || token.len() > 512
            || unique < 12
            || !token.is_ascii()
            || token
                .bytes()
                .any(|c| c.is_ascii_control() || c.is_ascii_whitespace())
        {
            return Err(Failure("strong_owner_token_required"));
        }
        if !fixture
            && [
                "insecure",
                "change.this",
                "your_",
                "dummy",
                "fictional",
                "example",
                "test-secret",
            ]
            .iter()
            .any(|s| token.to_ascii_lowercase().contains(s))
        {
            return Err(Failure("strong_owner_token_required"));
        }
        let listen = get("RUST_AGENT_LISTEN", "127.0.0.1:8011")
            .parse::<SocketAddr>()
            .map_err(|_| Failure("loopback_listener_required"))?;
        if listen.ip() != IpAddr::from([127, 0, 0, 1]) || (!fixture && listen.port() < 1025) {
            return Err(Failure("loopback_listener_required"));
        }
        let original = get("DATABASE_URL", "");
        let dsn = original
            .strip_prefix("postgresql+asyncpg://")
            .map(|s| format!("postgresql://{s}"))
            .unwrap_or(original.clone());
        let url = Url::parse(&dsn).map_err(|_| Failure("explicit_postgresql_database_required"))?;
        if !matches!(url.scheme(), "postgresql" | "postgres")
            || url.host_str().is_none()
            || url.query().is_some()
            || url.fragment().is_some()
        {
            return Err(Failure("explicit_postgresql_database_required"));
        }
        // SQLx's URL parser inherits PG* options and consults ~/.pgpass for a
        // missing password. Build explicit options without reading that private file.
        if std::env::vars_os().any(|(key, _)| key.to_str().is_some_and(|key| key.starts_with("PG")))
        {
            return Err(Failure("ambient_postgresql_options_forbidden"));
        }
        let decode = |value: &str| {
            percent_encoding::percent_decode_str(value)
                .decode_utf8()
                .map(|s| s.into_owned())
                .map_err(|_| Failure("invalid_database_configuration"))
        };
        let mut options = PgConnectOptions::new_without_pgpass()
            .host(url.host_str().unwrap_or(""))
            .port(url.port().unwrap_or(5432))
            .username(&decode(url.username())?)
            .password(&decode(url.password().unwrap_or(""))?)
            .database(&decode(url.path().trim_start_matches('/'))?);
        let username = options.get_username().to_owned();
        let host = options.get_host().to_ascii_lowercase();
        let database = options
            .get_database()
            .filter(|name| {
                !name.is_empty()
                    && name.len() <= 63
                    && name.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_')
            })
            .ok_or(Failure("explicit_postgresql_database_required"))?
            .to_owned();
        if url.username().is_empty() || url.path().split('/').count() != 2 {
            return Err(Failure("explicit_postgresql_database_required"));
        }
        let schema = get("DATABASE_SCHEMA", "public");
        if !matches!(schema.as_str(), "public" | "job_agent") {
            return Err(Failure("database_application_schema_required"));
        }
        if fixture {
            let expected = format!(
                "postgresql://rust_agent_fixture@127.0.0.1:{}/rust_agent_fixture",
                options.get_port()
            );
            if original != expected || options.get_port() < 1025 || schema != "public" {
                return Err(Failure("exact_disposable_fixture_required"));
            }
            options = options.ssl_mode(PgSslMode::Disable);
        } else {
            if boolean(values, "DB_ECHO", false)? {
                return Err(Failure("database_echo_forbidden_for_real_data"));
            }
            if !boolean(values, "DB_REQUIRE_TLS", true)?
                || !boolean(values, "DB_REMOTE_ONLY", true)?
            {
                return Err(Failure("remote_postgresql_tls_required"));
            }
            if local_host(&host) {
                return Err(Failure("remote_postgresql_database_required"));
            }
            if options.get_port() == 6543 {
                return Err(Failure("use_direct_or_session_pooler_connection"));
            }
            if url.password().is_none_or(str::is_empty) {
                return Err(Failure("explicit_postgresql_database_required"));
            }
            if username.split('.').next() != Some("job_agent_runtime") {
                return Err(Failure("privileged_runtime_role_forbidden"));
            }
            if schema == "public" {
                let project = get("SUPABASE_PROJECT_REF", "luvdmwnlwaqgvfwlmlom");
                let endpoint = get("SUPABASE_URL", "");
                if project != "luvdmwnlwaqgvfwlmlom"
                    || (!endpoint.is_empty()
                        && endpoint != format!("https://{project}.supabase.co"))
                    || !(host == format!("db.{project}.supabase.co")
                        || (host.ends_with(".pooler.supabase.com")
                            && username == format!("job_agent_runtime.{project}")))
                {
                    return Err(Failure("wrong_supabase_project"));
                }
            }
            options = options.ssl_mode(PgSslMode::VerifyFull);
            if let Some(cert) = values.get("DB_SSL_ROOT_CERT").filter(|s| !s.is_empty()) {
                let path = Path::new(cert);
                if !path.is_absolute() || !path.is_file() {
                    return Err(Failure("database_tls_certificate_unavailable"));
                }
                options = options.ssl_root_cert(path);
            }
        }
        let target_identity = format!(
            "{:x}",
            Sha256::digest(format!(
                "{username}@{host}:{}/{database}/{schema}",
                options.get_port()
            ))
        );
        let role = username.split('.').next().unwrap_or("").to_owned();
        options = options.statement_cache_capacity(32).options([
            ("search_path", format!("{schema},public")),
            ("statement_timeout", "30000".into()),
            ("lock_timeout", "2000".into()),
        ]);
        let hosts = trust_list(values, "API_ALLOWED_HOSTS", false, fixture)?;
        let origins = trust_list(values, "API_ALLOWED_ORIGINS", true, fixture)?;
        let require_tls = boolean(values, "API_REQUIRE_TLS", true)?;
        if !fixture && !require_tls {
            return Err(Failure("owner_api_tls_required"));
        }
        let defaults = crate::resources::link_defaults(values)?;
        let concurrency = get("LLM_MAX_CONCURRENCY", "2")
            .parse::<usize>()
            .ok()
            .filter(|n| (1..=8).contains(n))
            .ok_or(Failure("invalid_provider_configuration"))?;
        let gate = std::sync::Arc::new(tokio::sync::Semaphore::new(concurrency.min(2)));
        let mut models = crate::model_policy::Models::from_values(values, fixture)?;
        if let Some(models) = &mut models {
            models.client.share_gate(gate.clone());
        }
        let mut answers =
            crate::answer_service::Settings::from_values(values, fixture, defaults.clone())?;
        answers.share_gate(gate.clone());
        let mut questionnaire_answers = if boolean(values, "COHERE_ENABLED", false)?
            && boolean(values, "COHERE_CANDIDATE_DATA_AUTHORIZED", false)?
        {
            let mut selected = values.clone();
            selected.insert("LLM_PROVIDER".into(), "cohere".into());
            Some(crate::answer_service::Settings::from_values(
                &selected,
                fixture,
                defaults.clone(),
            )?)
        } else {
            None
        };
        if let Some(answers) = &mut questionnaire_answers {
            answers.share_gate(gate);
        }
        Ok(Self {
            options,
            token,
            hosts,
            origins,
            require_tls,
            trust_proxy: boolean(values, "RUST_AGENT_TRUST_LOOPBACK_PROXY", false)?,
            listen,
            local_socket: values
                .get("RUST_AGENT_UNIX_SOCKET")
                .map(|raw| automated_apply_local_ipc::checked_path(raw).map_err(|e| Failure(e.0)))
                .transpose()?,
            fixture,
            target_identity,
            database,
            schema,
            role,
            telegram: crate::telegram::Settings::from_values(values, fixture)?,
            models,
            profile_live: matches!(environment.as_str(), "production" | "staging"),
            resource_defaults: defaults,
            owner_signing: crate::owner_proof::SigningKey::from_values(values)?,
            answers,
            questionnaire_answers,
            resumes: crate::private_resume::Settings::from_values(values)?,
            resume_review: crate::resume_review::Settings::from_values(values)?,
            browser: crate::browser_inventory::Browser::from_values(values)?,
            browser_profiles: crate::browser_profiles::Settings::from_values(values)?,
            mailboxes: crate::mailboxes::Settings::from_values(values, fixture)?,
            gmail_accounts: crate::gmail_accounts::Settings::from_values(values)?,
            contacts: crate::contacts::Settings::from_values(values)?,
            outreach: crate::outreach::Settings::from_values(values)?,
            sources: crate::source_registry::Settings::from_values(values)?,
            apify_metadata: crate::apify_metadata::transport::Client::from_values(values, fixture)?,
            people_research: crate::people_research::settings::Settings::from_values(values)?,
            people_search_client: crate::people_research::transport::Client::from_values(
                values, fixture,
            )?,
            contact_enrichment: crate::contacts::enrichment::Settings::from_values(values)?,
            contact_providers: crate::contacts::enrichment::providers::Clients::from_values(
                values, fixture,
            )?,
            apollo_eligibility:
                crate::contacts::enrichment::capabilities::Eligibility::from_values(values)?,
            legacy_discovery_enabled: boolean(values, "AUTOMATION_EXECUTION_ENABLED", false)?,
            discovery_timeout_seconds: get("DISCOVERY_TIMEOUT_SECONDS", "90")
                .parse::<f64>()
                .ok()
                .filter(|s| s.is_finite() && (5.0..=180.0).contains(s))
                .ok_or(Failure("invalid_discovery_timeout"))?,
            packets: crate::packet_service::Settings {
                policy: crate::packet_platform::Policy {
                    testing: fixture,
                    origins: trust_list(values, "BROWSER_ALLOWED_ORIGINS", true, fixture)?,
                },
                multi_select: boolean(values, "MULTI_SELECT_FIELDS_ENABLED", false)?,
                schema: get("DATABASE_SCHEMA", "public"),
                telegram_notices: crate::packet_notice::telegram_configured(values),
            },
        })
    }
    /// Control/execution persist; generation may hold one additional bounded API connection.
    /// Telegram has its own optional connection. No pool or overflow.
    pub async fn connect(&self, execution: bool) -> Result<PgConnection> {
        self.connect_named(if execution {
            "automated-apply:execution"
        } else {
            "automated-apply:api"
        })
        .await
    }
    pub(crate) async fn connect_telegram(&self) -> Result<PgConnection> {
        self.connect_named("automated-apply:telegram").await
    }
    pub fn telegram_enabled(&self) -> bool {
        self.telegram.is_some()
    }
    pub fn model_policy(&self) -> crate::model_policy::Policy {
        self.models
            .as_ref()
            .map(crate::model_policy::Models::policy)
            .unwrap_or(crate::model_policy::Policy::Deterministic {})
    }
    pub fn review_model(&self) -> &'static str {
        if self.models.is_some() {
            "cohere"
        } else {
            "deterministic"
        }
    }
    async fn connect_named(&self, name: &str) -> Result<PgConnection> {
        if !self.fixture {
            let addresses = tokio::time::timeout(
                Duration::from_secs(10),
                tokio::net::lookup_host((self.options.get_host(), self.options.get_port())),
            )
            .await
            .map_err(|_| Failure("database_host_unavailable"))?
            .map_err(|_| Failure("database_host_unavailable"))?
            .collect::<Vec<_>>();
            if addresses.is_empty() || addresses.iter().any(|a| !public_ip(a.ip())) {
                return Err(Failure("remote_database_dns_resolves_locally"));
            }
        }
        let options = self.options.clone().application_name(name);
        tokio::time::timeout(
            Duration::from_secs(10),
            PgConnection::connect_with(&options),
        )
        .await
        .map_err(|_| Failure("agent_database_unavailable"))?
        .map_err(|_| Failure("agent_database_unavailable"))
    }
}
pub(crate) fn boolean(values: &BTreeMap<String, String>, key: &str, default: bool) -> Result<bool> {
    match values.get(key).map(|s| s.to_ascii_lowercase()).as_deref() {
        None => Ok(default),
        Some("true" | "1" | "yes" | "on") => Ok(true),
        Some("false" | "0" | "no" | "off") => Ok(false),
        _ => Err(Failure("invalid_configuration_boolean")),
    }
}
fn trust_list(
    values: &BTreeMap<String, String>,
    key: &str,
    origin: bool,
    fixture: bool,
) -> Result<Vec<String>> {
    let list: Vec<String> = match values.get(key) {
        Some(s) => serde_json::from_str(s).map_err(|_| Failure("invalid_api_trust_list"))?,
        None if fixture && !origin => vec!["127.0.0.1".into(), "localhost".into()],
        None => vec![],
    };
    if list.len() > 32 || (!origin && list.is_empty()) {
        return Err(Failure("explicit_api_hosts_required"));
    }
    for value in &list {
        if value.is_empty()
            || value.len() > 256
            || value.contains('*')
            || value.chars().any(char::is_whitespace)
        {
            return Err(Failure("invalid_api_trust_list"));
        }
        if origin {
            let url = Url::parse(value).map_err(|_| Failure("invalid_api_trust_list"))?;
            if !matches!(url.scheme(), "http" | "https")
                || !url.username().is_empty()
                || url.password().is_some()
                || url.origin().ascii_serialization() != *value
            {
                return Err(Failure("invalid_api_trust_list"));
            }
        } else if value.contains(['/', '@', '?', '#'])
            || value.parse::<axum::http::uri::Authority>().is_err()
        {
            return Err(Failure("invalid_api_trust_list"));
        }
    }
    Ok(list)
}
fn local_host(host: &str) -> bool {
    host == "localhost"
        || host.ends_with(".localhost")
        || host.ends_with(".local")
        || host
            .trim_matches(['[', ']'])
            .parse::<IpAddr>()
            .is_ok_and(|ip| !public_ip(ip))
}
fn public_ip(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(ip) => {
            let [a, b, c, _] = ip.octets();
            !(ip.is_private()
                || ip.is_loopback()
                || ip.is_link_local()
                || ip.is_broadcast()
                || ip.is_documentation()
                || ip.is_unspecified()
                || ip.is_multicast()
                || a == 0
                || a >= 240
                || (a == 100 && (64..=127).contains(&b))
                || (a == 192 && b == 0 && c == 0)
                || (a == 192 && b == 88 && c == 99)
                || (a == 198 && (b == 18 || b == 19)))
        }
        IpAddr::V6(ip) => {
            let parts = ip.segments();
            parts[0] & 0xe000 == 0x2000
                && !(parts[0] == 0x2001 && (parts[1] < 0x0200 || parts[1] == 0x0db8))
                && parts[0] != 0x2002
        }
    }
}

/// Literal, owner-private configuration only; never consult ambient env or print values.
pub(crate) fn private_values(path: &Path) -> Result<BTreeMap<String, String>> {
    if !path.is_absolute() {
        return Err(Failure("private_configuration_required"));
    }
    let file = File::options()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC)
        .open(path)
        .map_err(|_| Failure("private_configuration_required"))?;
    let info = file
        .metadata()
        .map_err(|_| Failure("private_configuration_required"))?;
    // SAFETY: geteuid takes no arguments and has no preconditions.
    if !info.is_file()
        || info.uid() != unsafe { libc::geteuid() }
        || info.mode() & 0o077 != 0
        || info.len() > 1_048_576
    {
        return Err(Failure("private_configuration_required"));
    }
    let mut content = String::new();
    file.take(1_048_577)
        .read_to_string(&mut content)
        .map_err(|_| Failure("invalid_private_configuration"))?;
    if content.len() > 1_048_576 {
        return Err(Failure("private_configuration_required"));
    }
    // dotenvy's substitutions consult ambient environment variables. Require literal
    // values instead; URL passwords containing dollars can use percent encoding.
    if content.contains('$') {
        return Err(Failure("configuration_interpolation_forbidden"));
    }
    let mut values = BTreeMap::new();
    for item in dotenvy::from_read_iter(content.as_bytes()) {
        let (key, value) = item.map_err(|_| Failure("invalid_private_configuration"))?;
        if values.insert(key, value).is_some() {
            return Err(Failure("duplicate_configuration_key"));
        }
    }
    Ok(values)
}
#[cfg(test)]
mod questionnaire_tests {
    use super::*;
    fn values() -> BTreeMap<String, String> {
        BTreeMap::from([
            ("ENVIRONMENT".into(), "testing".into()),
            ("RUST_RUNTIME_FIXTURE".into(), "true".into()),
            (
                "DATABASE_URL".into(),
                "postgresql://rust_agent_fixture@127.0.0.1:54321/rust_agent_fixture".into(),
            ),
            (
                "JOB_AGENT_API_TOKEN".into(),
                "0123456789abcdefghijklmnopqrstuvwxyzABCDEF".into(),
            ),
            ("API_REQUIRE_TLS".into(), "false".into()),
            ("LLM_PROVIDER".into(), "gemini".into()),
            ("COHERE_MODEL".into(), "command-a-03-2025".into()),
            ("COHERE_API_KEY".into(), "fictional-fixture-key".into()),
            ("COHERE_EVALUATION_KEY_CONFIRMED".into(), "true".into()),
            ("COHERE_OWNER_TEXT_AUTHORIZED".into(), "true".into()),
            (
                "RUST_COHERE_FIXTURE_ENDPOINT".into(),
                "http://127.0.0.1:54321/v2/chat".into(),
            ),
        ])
    }
    #[test]
    fn questionnaire_cohere_scope_requires_both_saved_enable_and_candidate_consent_without_replacing_default_writer()
     {
        for (enabled, consent, ready) in [
            (false, false, false),
            (true, false, false),
            (false, true, false),
            (true, true, true),
        ] {
            let mut v = values();
            v.insert("COHERE_ENABLED".into(), enabled.to_string());
            v.insert(
                "COHERE_CANDIDATE_DATA_AUTHORIZED".into(),
                consent.to_string(),
            );
            let config = Configuration::from_values(&v).unwrap();
            assert_eq!(
                config
                    .questionnaire_answers
                    .as_ref()
                    .is_some_and(|s| s.questionnaire_cohere_ready()),
                ready
            );
            assert!(!config.answers.questionnaire_cohere_ready());
            assert_eq!(config.review_model(), "deterministic");
        }
    }
    #[test]
    fn questionnaire_scope_does_not_assume_missing_evaluation_or_owner_text_authorization() {
        for denied in [
            "COHERE_EVALUATION_KEY_CONFIRMED",
            "COHERE_OWNER_TEXT_AUTHORIZED",
        ] {
            let mut v = values();
            v.insert("COHERE_ENABLED".into(), "true".into());
            v.insert("COHERE_CANDIDATE_DATA_AUTHORIZED".into(), "true".into());
            v.insert(denied.into(), "false".into());
            let config = Configuration::from_values(&v).unwrap();
            assert!(
                !config
                    .questionnaire_answers
                    .as_ref()
                    .is_some_and(|s| s.questionnaire_cohere_ready())
            );
        }
    }
}
