//! Fixed Google OAuth endpoints and strict token/identity results. Sending is not a grant mode.
use crate::{Failure, Result, context_contract::python_space};
use automated_apply_domain::text::folded;
use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use reqwest::{
    Client, Method, Url,
    header::{AUTHORIZATION, HeaderValue},
};
use serde::Deserialize;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    time::Duration,
};
pub const METADATA: &str = "https://www.googleapis.com/auth/gmail.metadata";
pub const READ: &str = "https://www.googleapis.com/auth/gmail.readonly";
pub const COMPOSE: &str = "https://www.googleapis.com/auth/gmail.compose";
const EMAIL: &str = "https://www.googleapis.com/auth/userinfo.email";
#[derive(Clone, Copy)]
pub enum GrantMode {
    Metadata,
    Read,
    Compose,
    ReadDraft,
}
pub fn scopes(mode: GrantMode) -> BTreeSet<String> {
    let mut set = BTreeSet::from(["openid".into(), EMAIL.into()]);
    match mode {
        GrantMode::Metadata => {
            set.insert(METADATA.into());
        }
        GrantMode::Read => {
            set.insert(READ.into());
        }
        GrantMode::Compose => {
            set.insert(COMPOSE.into());
        }
        GrantMode::ReadDraft => {
            set.insert(READ.into());
            set.insert(COMPOSE.into());
        }
    }
    set
}
pub fn normalized_scopes(raw: &Value) -> Result<BTreeSet<String>> {
    Ok(raw
        .as_str()
        .ok_or(Failure("missing_granted_scopes"))?
        .split(python_space)
        .filter(|s| !s.is_empty())
        .map(|s| if s == "email" { EMAIL.into() } else { s.into() })
        .collect())
}
#[derive(Deserialize)]
pub struct TokenResponse {
    pub(crate) access_token: String,
    pub(crate) refresh_token: Option<String>,
    pub(crate) token_type: String,
    pub(crate) expires_in: i64,
    pub(crate) scope: Option<String>,
}
impl TokenResponse {
    pub fn parse(raw: Value) -> Result<Self> {
        let result: Self =
            serde_json::from_value(raw).map_err(|_| Failure("invalid_token_response"))?;
        if result.access_token.is_empty()
            || result.access_token.chars().count() > 16384
            || result
                .refresh_token
                .as_ref()
                .is_some_and(|t| t.is_empty() || t.chars().count() > 16384)
            || !result.token_type.eq_ignore_ascii_case("bearer")
            || !(1..=86400).contains(&result.expires_in)
        {
            return Err(Failure("invalid_token_response"));
        }
        Ok(result)
    }
    pub fn granted_scopes(&self) -> Result<Option<BTreeSet<String>>> {
        self.scope
            .as_ref()
            .map(|s| normalized_scopes(&Value::String(s.clone())))
            .transpose()
    }
    pub fn has_refresh_token(&self) -> bool {
        self.refresh_token.is_some()
    }
    pub fn expires_in(&self) -> i64 {
        self.expires_in
    }
    pub fn access(&self) -> &str {
        &self.access_token
    }
    pub fn refresh(&self) -> Option<&str> {
        self.refresh_token.as_deref()
    }
}
#[derive(Clone, Copy)]
enum Endpoint {
    Token,
    Userinfo,
    Profile,
    Revoke,
}
pub struct GoogleOAuth {
    client: Client,
    id: String,
    secret: String,
    redirect: String,
    fixture: Option<Url>,
}
fn redirect(value: &str) -> Result<()> {
    let url = Url::parse(value).map_err(|_| Failure("invalid_google_redirect"))?;
    // Preserve the legacy exact raw callback path; URL parsing normalizes dot segments.
    let raw_path = value
        .split_once("://")
        .and_then(|(_, rest)| rest.split_once('/'))
        .map(|(_, path)| format!("/{path}"));
    if !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
        || url.path() != "/api/v1/integrations/gmail/oauth/callback"
        || raw_path.as_deref() != Some("/api/v1/integrations/gmail/oauth/callback")
    {
        return Err(Failure("invalid_google_redirect"));
    }
    if url.scheme() == "https" && url.host_str().is_some() {
        return Ok(());
    }
    let authority = value
        .split_once("://")
        .map(|(_, rest)| rest.split('/').next().unwrap_or(""))
        .unwrap_or("");
    let host = if authority.starts_with('[') {
        authority
            .split(']')
            .next()
            .unwrap_or("")
            .trim_start_matches('[')
    } else {
        authority.split(':').next().unwrap_or("")
    };
    if url.scheme() != "http"
        || !["localhost", "127.0.0.1", "::1"].contains(&host.to_ascii_lowercase().as_str())
    {
        return Err(Failure("invalid_google_redirect"));
    }
    Ok(())
}
impl GoogleOAuth {
    pub fn from_values(values: &BTreeMap<String, String>, fixture: bool) -> Result<Option<Self>> {
        let callback = values.get("GMAIL_REDIRECT_URI").filter(|s| !s.is_empty());
        if let Some(uri) = callback {
            redirect(uri)?;
        }
        let (Some(id), Some(secret), Some(callback)) = (
            values.get("GMAIL_CLIENT_ID").filter(|s| !s.is_empty()),
            values.get("GMAIL_CLIENT_SECRET").filter(|s| !s.is_empty()),
            callback,
        ) else {
            return Ok(None);
        };
        let alternate = values.get("RUST_GOOGLE_FIXTURE_ENDPOINT");
        let endpoint = match (fixture, alternate) {
            (false, None) => None,
            (true, Some(raw)) => {
                let url = Url::parse(raw).map_err(|_| Failure("google_fixture_endpoint_denied"))?;
                if url.scheme() != "http"
                    || url.host_str() != Some("127.0.0.1")
                    || url.port().is_none_or(|p| p < 1025)
                    || url.path() != "/"
                    || !url.username().is_empty()
                    || url.password().is_some()
                    || url.query().is_some()
                    || url.fragment().is_some()
                {
                    return Err(Failure("google_fixture_endpoint_denied"));
                }
                Some(url)
            }
            _ => return Err(Failure("google_fixture_endpoint_denied")),
        };
        let client = Client::builder()
            .no_proxy()
            .redirect(reqwest::redirect::Policy::none())
            .retry(reqwest::retry::never())
            .connect_timeout(Duration::from_secs(5))
            .timeout(Duration::from_secs(15))
            .build()
            .map_err(|_| Failure("google_transport_or_response_error"))?;
        Ok(Some(Self {
            client,
            id: id.clone(),
            secret: secret.clone(),
            redirect: callback.clone(),
            fixture: endpoint,
        }))
    }
    pub fn redirect_uri(&self) -> &str {
        &self.redirect
    }
    pub fn authorization_url(
        &self,
        state: &str,
        verifier: &str,
        email: Option<&str>,
        mode: GrantMode,
    ) -> Result<String> {
        let mut url = Url::parse("https://accounts.google.com/o/oauth2/v2/auth")
            .map_err(|_| Failure("google_oauth_not_configured"))?;
        let scope = scopes(mode).into_iter().collect::<Vec<_>>().join(" ");
        let challenge = URL_SAFE_NO_PAD.encode(Sha256::digest(verifier.as_bytes()));
        {
            let mut query = url.query_pairs_mut();
            query.extend_pairs([
                ("client_id", self.id.as_str()),
                ("redirect_uri", &self.redirect),
                ("response_type", "code"),
                ("scope", &scope),
                ("state", state),
                ("access_type", "offline"),
                ("prompt", "consent select_account"),
            ]);
            if let Some(email) = email.filter(|s| !s.is_empty()) {
                query.append_pair("login_hint", email);
            }
            query.extend_pairs([
                ("include_granted_scopes", "false"),
                ("code_challenge", &challenge),
                ("code_challenge_method", "S256"),
            ]);
        }
        Ok(url.into())
    }
    async fn request(
        &self,
        endpoint: Endpoint,
        form: Option<Vec<(&str, &str)>>,
        token: Option<&str>,
    ) -> Result<Value> {
        let (method, production, path) = match endpoint {
            Endpoint::Token => (Method::POST, "https://oauth2.googleapis.com/token", "token"),
            Endpoint::Revoke => (
                Method::POST,
                "https://oauth2.googleapis.com/revoke",
                "revoke",
            ),
            Endpoint::Userinfo => (
                Method::GET,
                "https://openidconnect.googleapis.com/v1/userinfo",
                "userinfo",
            ),
            Endpoint::Profile => (
                Method::GET,
                "https://gmail.googleapis.com/gmail/v1/users/me/profile",
                "profile",
            ),
        };
        let target = if let Some(base) = &self.fixture {
            base.join(path)
                .map_err(|_| Failure("google_fixture_endpoint_denied"))?
        } else {
            Url::parse(production).map_err(|_| Failure("google_oauth_not_configured"))?
        };
        let mut request = self.client.request(method, target);
        if let Some(form) = form {
            request = request.form(&form);
        }
        if let Some(token) = token {
            let mut header = HeaderValue::from_str(&format!("Bearer {token}"))
                .map_err(|_| Failure("google_transport_or_response_error"))?;
            header.set_sensitive(true);
            request = request.header(AUTHORIZATION, header);
        }
        let work = async {
            let mut response = request
                .send()
                .await
                .map_err(|_| Failure("google_transport_or_response_error"))?;
            let status = response.status().as_u16();
            if response.content_length().is_some_and(|n| n > 1024 * 1024) {
                return Err(Failure("google_response_limit"));
            }
            let mut bytes = Vec::new();
            while let Some(chunk) = response
                .chunk()
                .await
                .map_err(|_| Failure("google_transport_or_response_error"))?
            {
                if bytes.len() + chunk.len() > 1024 * 1024 {
                    return Err(Failure("google_response_limit"));
                }
                bytes.extend_from_slice(&chunk);
            }
            if status != 200 {
                if matches!(endpoint, Endpoint::Token)
                    && status == 400
                    && serde_json::from_slice::<Value>(&bytes)
                        .ok()
                        .is_some_and(|v| v["error"] == "invalid_grant")
                {
                    return Err(Failure("credential_revoked_or_code_invalid"));
                }
                return Err(Failure("google_request_failed"));
            }
            let value: Value = if bytes.is_empty() {
                serde_json::json!({})
            } else {
                serde_json::from_slice(&bytes)
                    .map_err(|_| Failure("google_transport_or_response_error"))?
            };
            if !value.is_object() {
                return Err(Failure("invalid_google_response"));
            }
            Ok(value)
        };
        tokio::time::timeout(Duration::from_secs(20), work)
            .await
            .map_err(|_| Failure("google_transport_or_response_error"))?
    }
    pub async fn exchange(&self, code: &str, verifier: &str) -> Result<TokenResponse> {
        TokenResponse::parse(
            self.request(
                Endpoint::Token,
                Some(vec![
                    ("client_id", &self.id),
                    ("client_secret", &self.secret),
                    ("redirect_uri", &self.redirect),
                    ("grant_type", "authorization_code"),
                    ("code", code),
                    ("code_verifier", verifier),
                ]),
                None,
            )
            .await?,
        )
    }
    pub async fn refresh(&self, refresh: &str) -> Result<TokenResponse> {
        TokenResponse::parse(
            self.request(
                Endpoint::Token,
                Some(vec![
                    ("client_id", &self.id),
                    ("client_secret", &self.secret),
                    ("grant_type", "refresh_token"),
                    ("refresh_token", refresh),
                ]),
                None,
            )
            .await?,
        )
    }
    pub async fn identity(&self, token: &str) -> Result<(String, String)> {
        let identity = self.request(Endpoint::Userinfo, None, Some(token)).await?;
        let subject = identity["sub"]
            .as_str()
            .filter(|s| !s.is_empty() && s.chars().count() <= 255)
            .ok_or(Failure("identity_verification_failed"))?;
        if identity["email_verified"] != true {
            return Err(Failure("identity_verification_failed"));
        }
        let email = identity["email"]
            .as_str()
            .ok_or(Failure("identity_verification_failed"))?;
        let profile = self.request(Endpoint::Profile, None, Some(token)).await?;
        if profile["emailAddress"]
            .as_str()
            .is_none_or(|p| folded(p) != folded(email))
        {
            return Err(Failure("gmail_identity_mismatch"));
        }
        Ok((subject.into(), folded(email)))
    }
    pub async fn revoke(&self, token: &str) -> Result<()> {
        self.request(Endpoint::Revoke, Some(vec![("token", token)]), None)
            .await?;
        Ok(())
    }
}
