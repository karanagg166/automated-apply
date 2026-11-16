//! Owner-invoked local Gmail account lifecycle. No sending or automatic account activation.
mod drafts;
mod lifecycle;
pub use drafts::{ReviewedDraft, draft_hash, expected_generation, mime_message, verified_content};
mod reading;
pub use reading::{Search, message_id};
mod alert_candidates;
pub mod alert_rules;
pub mod alerts;
pub mod routes;
mod storage;
use crate::{
    Failure, Result,
    account_tokens::TokenStore,
    configuration::boolean,
    google_oauth::{GoogleOAuth, GrantMode, TokenResponse},
};
use automated_apply_domain::text::folded;
use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use chrono::{DateTime, Duration, Utc};
use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use sqlx::{Connection, PgConnection};
use std::collections::{BTreeMap, BTreeSet};
use storage::*;
use uuid::Uuid;

pub struct Settings {
    enabled: bool,
    fixture: bool,
    read_endpoint: Option<String>,
    allowed: BTreeSet<String>,
    ttl: i64,
    drafts: bool,
    body: bool,
    store: Option<TokenStore>,
    google: Option<GoogleOAuth>,
}
impl Settings {
    pub(crate) fn alerts_available(&self) -> bool {
        self.enabled && self.body && !self.allowed.is_empty()
    }
    pub(crate) fn configured_slots(&self) -> usize {
        self.allowed.len().min(2)
    }
    pub fn from_values(values: &BTreeMap<String, String>, fixture: bool) -> Result<Self> {
        let allowed: Vec<String> = serde_json::from_str(
            values
                .get("GMAIL_LOCAL_ALLOWED_EMAILS")
                .map(String::as_str)
                .unwrap_or("[]"),
        )
        .map_err(|_| Failure("gmail_account_allowlist_invalid"))?;
        if allowed.len() > 100
            || allowed.iter().any(|s| {
                s.len() > 254
                    || s.split('@').count() != 2
                    || s.starts_with('@')
                    || s.ends_with('@')
                    || s.chars()
                        .any(|c| c.is_control() || c.is_whitespace() || "<>".contains(c))
            })
        {
            return Err(Failure("gmail_account_allowlist_invalid"));
        }
        let ttl = values
            .get("OAUTH_STATE_TTL_SECONDS")
            .map(String::as_str)
            .unwrap_or("600")
            .parse::<i64>()
            .ok()
            .filter(|n| (60..=900).contains(n))
            .ok_or(Failure("invalid_oauth_state_ttl"))?;
        if let Some(endpoint) = values.get("RUST_GMAIL_FIXTURE_ENDPOINT") {
            crate::gmail_read::ReadClient::new(
                "fictional-configuration-check",
                fixture,
                Some(endpoint),
            )?;
        }
        Ok(Self {
            fixture,
            read_endpoint: values.get("RUST_GMAIL_FIXTURE_ENDPOINT").cloned(),
            enabled: boolean(values, "GMAIL_LOCAL_ACCOUNTS_ENABLED", false)?,
            allowed: allowed.iter().map(|s| folded(s)).collect(),
            ttl,
            drafts: boolean(values, "GMAIL_DRAFTS_ENABLED", false)?,
            body: boolean(values, "GMAIL_READ_BODY_REVIEWED", false)?,
            store: TokenStore::from_values(values)?,
            google: GoogleOAuth::from_values(values, fixture)?,
        })
    }
    fn enabled(&self) -> Result<()> {
        if !self.enabled {
            return Err(Failure("gmail_local_accounts_disabled"));
        }
        if self.allowed.is_empty() {
            return Err(Failure("gmail_account_allowlist_required"));
        }
        Ok(())
    }
    fn allowed(&self, email: &str) -> bool {
        !email.is_empty() && self.allowed.contains(&folded(email))
    }
    fn store(&self) -> Result<&TokenStore> {
        self.store
            .as_ref()
            .ok_or(Failure("oauth_encryption_not_configured"))
    }
    pub fn provider(&self) -> Result<&GoogleOAuth> {
        self.google
            .as_ref()
            .ok_or(Failure("google_oauth_not_configured"))
    }
    pub fn secure_cookie(&self) -> bool {
        self.google
            .as_ref()
            .is_some_and(|g| g.redirect_uri().starts_with("https:"))
    }
    pub fn slots(&self) -> usize {
        self.allowed.len().clamp(1, 2)
    }
    pub fn ttl(&self) -> i64 {
        self.ttl
    }
}
#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq)]
pub enum Slot {
    #[serde(rename = "1")]
    One,
    #[serde(rename = "2")]
    Two,
}
impl Slot {
    pub fn parse(raw: &str) -> Result<Self> {
        match raw {
            "1" => Ok(Self::One),
            "2" => Ok(Self::Two),
            _ => Err(Failure("gmail_account_slot_invalid")),
        }
    }
    pub fn name(self) -> &'static str {
        match self {
            Self::One => "1",
            Self::Two => "2",
        }
    }
    fn other(self) -> Self {
        match self {
            Self::One => Self::Two,
            Self::Two => Self::One,
        }
    }
    fn key(self) -> String {
        format!("gm54_account:{}", self.name())
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Consent {
    pub account_consent: bool,
    pub read_and_draft_consent: bool,
}
pub fn consent(body: &[u8]) -> Result<Consent> {
    serde_json::from_slice(body).map_err(|_| Failure("invalid_gmail_consent"))
}
pub fn digest(raw: &str) -> String {
    format!("{:x}", Sha256::digest(raw.as_bytes()))
}
/// Three independent OS-backed UUIDs supply more than256 random bits. No mutable global RNG.
pub fn browser_nonce() -> String {
    let mut raw = Vec::with_capacity(48);
    for _ in 0..3 {
        raw.extend_from_slice(Uuid::new_v4().as_bytes());
    }
    URL_SAFE_NO_PAD.encode(raw)
}
fn instant(value: &Value) -> Option<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(value.as_str()?)
        .ok()
        .map(|t| t.with_timezone(&Utc))
}
fn timestamp() -> String {
    Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, false)
}
fn expires(seconds: i64) -> String {
    (Utc::now() + Duration::seconds(seconds)).to_rfc3339_opts(chrono::SecondsFormat::Micros, false)
}
fn generation(value: &Value) -> Result<i64> {
    value["generation"]
        .as_i64()
        .filter(|n| *n >= 1)
        .ok_or(Failure("invalid_gmail_account_record"))
}
fn next_generation(value: &Value) -> Result<i64> {
    value
        .get("generation")
        .map(|_| generation(value))
        .transpose()?
        .unwrap_or(0)
        .checked_add(1)
        .ok_or(Failure("invalid_gmail_account_record"))
}
fn text<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    value[key]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or(Failure("invalid_gmail_account_record"))
}
#[allow(async_fn_in_trait)]
pub trait Provider {
    fn redirect_uri(&self) -> &str;
    fn authorization_url(&self, state: &str, verifier: &str, email: Option<&str>)
    -> Result<String>;
    async fn exchange(&self, code: &str, verifier: &str) -> Result<TokenResponse>;
    async fn refresh(&self, refresh: &str) -> Result<TokenResponse>;
    async fn identity(&self, token: &str) -> Result<(String, String)>;
    async fn revoke(&self, token: &str) -> Result<()>;
}
impl Provider for GoogleOAuth {
    fn redirect_uri(&self) -> &str {
        GoogleOAuth::redirect_uri(self)
    }
    fn authorization_url(
        &self,
        state: &str,
        verifier: &str,
        email: Option<&str>,
    ) -> Result<String> {
        GoogleOAuth::authorization_url(self, state, verifier, email, GrantMode::ReadDraft)
    }
    async fn exchange(&self, code: &str, verifier: &str) -> Result<TokenResponse> {
        GoogleOAuth::exchange(self, code, verifier).await
    }
    async fn refresh(&self, refresh: &str) -> Result<TokenResponse> {
        GoogleOAuth::refresh(self, refresh).await
    }
    async fn identity(&self, token: &str) -> Result<(String, String)> {
        GoogleOAuth::identity(self, token).await
    }
    async fn revoke(&self, token: &str) -> Result<()> {
        GoogleOAuth::revoke(self, token).await
    }
}
pub struct Service<'a, P> {
    pub settings: &'a Settings,
    pub provider: &'a P,
}
// Contains a token: deliberately neither Debug nor Serialize.
pub struct Access {
    token: String,
    pub(crate) account: Value,
}
impl Access {
    pub fn token(&self) -> &str {
        &self.token
    }
    pub fn generation(&self) -> Result<i64> {
        generation(&self.account)
    }
}
impl<P: Provider> Service<'_, P> {
    pub async fn status(&self, c: &mut PgConnection, slot: Slot) -> Result<Value> {
        let value = read(c, &slot.key(), false).await?.unwrap_or(json!({}));
        if value
            .get("account_email")
            .is_some_and(|v| v.as_str().is_none_or(|email| !self.settings.allowed(email)))
        {
            return Ok(
                json!({"slot":slot.name(),"status":"not_authorized","enabled":false,"permissions":{"send":false,"read":false,"drafts":false}}),
            );
        }
        let state = value["status"].as_str().unwrap_or("not_connected");
        let health = if state == "reauthorization_required" {
            "reauthorization_required"
        } else if instant(&value["expires_at"])
            .is_some_and(|t| t <= Utc::now() + Duration::seconds(60))
        {
            "expires_soon"
        } else {
            "saved_not_live_checked"
        };
        let mut result = json!({"slot":slot.name(),"status":state,"enabled":self.settings.enabled,"scopes":value.get("scopes").cloned().unwrap_or(json!([])),"drafts_enabled":self.settings.drafts,"body_review_enabled":self.settings.body,"permissions":{"read":true,"search":true,"drafts":true,"send":false,"delete":false,"monitoring":false},"token_health":health});
        for key in [
            "account_email",
            "generation",
            "last_verified_at",
            "last_refresh_at",
            "expires_at",
        ] {
            result[key] = value.get(key).cloned().unwrap_or(Value::Null);
        }
        Ok(result)
    }
    pub async fn check(&self, c: &mut PgConnection, slot: Slot, expected: i64) -> Result<()> {
        let mut tx = c.begin().await.map_err(db)?;
        self.fence(&mut tx, slot, expected).await?;
        commit(tx).await
    }
    async fn fence(
        &self,
        c: &mut sqlx::Transaction<'_, sqlx::Postgres>,
        slot: Slot,
        expected: i64,
    ) -> Result<Value> {
        self.settings.enabled()?;
        lock(c).await?;
        let value = read(c, &slot.key(), true)
            .await?
            .ok_or(Failure("gmail_account_changed"))?;
        if value["status"] != "connected" || generation(&value)? != expected {
            return Err(Failure("gmail_account_changed"));
        }
        if !self.settings.allowed(text(&value, "account_email")?) {
            return Err(Failure("gmail_account_not_authorized"));
        }
        Ok(value)
    }
}

// Optional provider configuration never prevents reading status or locally disconnecting.
impl Provider for Settings {
    fn redirect_uri(&self) -> &str {
        self.google
            .as_ref()
            .map(GoogleOAuth::redirect_uri)
            .unwrap_or("")
    }
    fn authorization_url(
        &self,
        state: &str,
        verifier: &str,
        email: Option<&str>,
    ) -> Result<String> {
        self.provider()?
            .authorization_url(state, verifier, email, GrantMode::ReadDraft)
    }
    async fn exchange(&self, code: &str, verifier: &str) -> Result<TokenResponse> {
        self.provider()?.exchange(code, verifier).await
    }
    async fn refresh(&self, refresh: &str) -> Result<TokenResponse> {
        self.provider()?.refresh(refresh).await
    }
    async fn identity(&self, token: &str) -> Result<(String, String)> {
        self.provider()?.identity(token).await
    }
    async fn revoke(&self, token: &str) -> Result<()> {
        self.provider()?.revoke(token).await
    }
}
