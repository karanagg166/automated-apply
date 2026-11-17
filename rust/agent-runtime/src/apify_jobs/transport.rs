//! Fixed official API transport. Only a durable operation admission can construct a one-use permit.
use super::plan::Target;
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use reqwest::{
    Client as Http, Url,
    header::{AUTHORIZATION, HeaderValue},
};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, time::Duration};
use uuid::Uuid;
pub struct Client {
    http: Http,
    origin: Url,
    token: Option<HeaderValue>,
    context: Option<String>,
}
pub(super) struct Permit {
    pub(super) request: Uuid,
    pub(super) invocation: Uuid,
    pub(super) sequence: u64,
    pub(super) target: Target,
    pub(super) credential_context: String,
    pub(super) expires: DateTime<Utc>,
}
pub(super) struct Outcome {
    pub(super) request: Uuid,
    pub(super) invocation: Uuid,
    pub(super) sequence: u64,
    pub(super) attempted: bool,
    pub(super) response_observed: bool,
    pub(super) body: Option<Value>,
    pub(super) code: Option<&'static str>,
    pub(super) bytes: usize,
    pub(super) cooldown: Option<DateTime<Utc>>,
}
fn invalid() -> Failure {
    Failure("invalid_apify_execution_transport")
}
impl Client {
    pub fn from_values(values: &BTreeMap<String, String>, fixture: bool) -> Result<Self> {
        let configured = values.get("RUST_APIFY_EXECUTION_FIXTURE_ORIGIN");
        if !fixture && configured.is_some() {
            return Err(Failure("apify_execution_fixture_origin_denied"));
        }
        let origin = Url::parse(
            configured
                .map(String::as_str)
                .unwrap_or("https://api.apify.com/v2/"),
        )
        .map_err(|_| Failure("apify_execution_fixture_origin_denied"))?;
        if configured.is_some()
            && (origin.scheme() != "http"
                || origin.host_str() != Some("127.0.0.1")
                || origin.port().is_none_or(|p| p < 1025)
                || origin.path() != "/v2/"
                || !origin.username().is_empty()
                || origin.password().is_some()
                || origin.query().is_some()
                || origin.fragment().is_some())
        {
            return Err(Failure("apify_execution_fixture_origin_denied"));
        }
        let raw = values
            .get("APIFY_API_TOKEN")
            .filter(|s| !s.trim().is_empty());
        let token = raw
            .map(|s| {
                if s.len() > 8192 || s.chars().any(char::is_whitespace) {
                    return Err(invalid());
                }
                let mut header =
                    HeaderValue::from_str(&format!("Bearer {s}")).map_err(|_| invalid())?;
                header.set_sensitive(true);
                Ok(header)
            })
            .transpose()?;
        let context = raw.map(|s| format!("{:x}", Sha256::digest(s.as_bytes())));
        let http = Http::builder()
            .no_proxy()
            .retry(reqwest::retry::never())
            .redirect(reqwest::redirect::Policy::none())
            .connect_timeout(Duration::from_secs(5))
            .timeout(Duration::from_secs(20))
            .pool_max_idle_per_host(1)
            .pool_idle_timeout(Duration::from_secs(15))
            .build()
            .map_err(|_| invalid())?;
        Ok(Self {
            http,
            origin,
            token,
            context,
        })
    }
    pub(super) fn matches(&self, credential: &str) -> bool {
        self.token.is_some() && self.context.as_deref() == Some(credential)
    }
    pub(super) async fn execute(&self, permit: Permit) -> Outcome {
        let mut outcome = Outcome {
            request: permit.request,
            invocation: permit.invocation,
            sequence: permit.sequence,
            attempted: false,
            response_observed: false,
            body: None,
            code: None,
            bytes: 0,
            cooldown: None,
        };
        if !self.matches(&permit.credential_context)
            || permit.request.is_nil()
            || permit.invocation.is_nil()
            || Utc::now() >= permit.expires
        {
            outcome.code = Some("apify_original_operation_expired_or_changed");
            return outcome;
        }
        let target = permit.target;
        let url = match self.origin.join(target.path()) {
            Ok(url)
                if url.origin() == self.origin.origin()
                    && url.path().starts_with(self.origin.path())
                    && url.query().is_none()
                    && url.fragment().is_none()
                    && !target.path().contains(['?', '#', '%']) =>
            {
                url
            }
            _ => {
                outcome.code = Some("apify_execution_target_denied");
                return outcome;
            }
        };
        let method = match target.method() {
            "GET" => reqwest::Method::GET,
            "POST" => reqwest::Method::POST,
            _ => {
                outcome.code = Some("apify_execution_target_denied");
                return outcome;
            }
        };
        let mut request = self
            .http
            .request(method, url)
            .query(target.query())
            .header(
                AUTHORIZATION,
                self.token.as_ref().expect("matching token").clone(),
            )
            .header("Accept", "application/json")
            .header("Cache-Control", "no-cache");
        if let Some(body) = target.body() {
            request = request.json(body);
        }
        let remaining = match (permit.expires - Utc::now()).to_std() {
            Ok(v) if !v.is_zero() => v.min(Duration::from_secs(20)),
            _ => {
                outcome.code = Some("apify_original_operation_expired_or_changed");
                return outcome;
            }
        };
        let deadline = tokio::time::Instant::now() + remaining;
        let operation = async {
            outcome.attempted = true;
            let mut response = request
                .send()
                .await
                .map_err(|_| Failure("apify_execution_transport_unconfirmed"))?;
            outcome.response_observed = true;
            match response.status().as_u16() {
                200 | 201 => {}
                401 | 403 => return Err(Failure("apify_execution_authentication_required")),
                429 => {
                    let raw = response
                        .headers()
                        .get("retry-after")
                        .and_then(|v| v.to_str().ok());
                    let now = Utc::now();
                    let until = raw
                        .and_then(|s| s.parse::<i64>().ok())
                        .filter(|n| *n >= 0)
                        .and_then(|n| chrono::Duration::try_seconds(n))
                        .and_then(|d| now.checked_add_signed(d))
                        .or_else(|| {
                            raw.and_then(|s| DateTime::parse_from_rfc2822(s).ok())
                                .map(|v| v.to_utc())
                        });
                    // Unknown or overflowing provider delays impose a qualified hold, never an early retry.
                    outcome.cooldown = Some(
                        until
                            .map(|v| v.max(now + chrono::Duration::minutes(1)))
                            .unwrap_or_else(|| {
                                DateTime::<Utc>::from_timestamp(253402300799, 0)
                                    .expect("bounded far future")
                            }),
                    );
                    return Err(Failure("apify_execution_rate_limited"));
                }
                _ => return Err(Failure("apify_execution_http_unavailable")),
            }
            if response.content_length().is_some_and(|n| n > 1048576) {
                return Err(Failure("apify_execution_response_limit"));
            }
            let content = response
                .headers()
                .get("content-type")
                .and_then(|v| v.to_str().ok())
                .unwrap_or("")
                .split(';')
                .next()
                .unwrap_or("")
                .trim()
                .to_ascii_lowercase();
            if content != "application/json"
                && !(content.starts_with("application/") && content.ends_with("+json"))
            {
                return Err(Failure("apify_execution_json_required"));
            }
            let mut bytes = Vec::new();
            while let Some(chunk) = response
                .chunk()
                .await
                .map_err(|_| Failure("apify_execution_transport_unconfirmed"))?
            {
                if bytes.len() + chunk.len() > 1048576 {
                    return Err(Failure("apify_execution_response_limit"));
                }
                bytes.extend_from_slice(&chunk);
            }
            outcome.bytes = bytes.len();
            let body: Value = serde_json::from_slice(&bytes)
                .map_err(|_| Failure("apify_execution_json_invalid"))?;
            if tokio::time::Instant::now() >= deadline {
                return Err(Failure("apify_execution_timeout"));
            }
            outcome.body = Some(body);
            Ok(())
        };
        let result = tokio::time::timeout_at(deadline, operation)
            .await
            .unwrap_or(Err(Failure("apify_execution_timeout")));
        if let Err(error) = result {
            outcome.code = Some(error.0);
            outcome.body = None;
        }
        outcome
    }
}
