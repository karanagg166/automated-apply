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
    pub(super) read_only: bool,
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

#[cfg(test)]
mod read_permit_tests {
    use super::*;
    use crate::apify_jobs::{
        evidence::{ActorIdentity, Run},
        money::Usd,
        plan::{BuildReview, Plan, Policy},
    };
    use serde_json::json;
    use std::collections::BTreeMap;
    #[tokio::test(flavor = "current_thread")]
    async fn read_only_transport_permit_refuses_even_a_bound_original_abort_target_before_any_http()
    {
        let now = Utc::now();
        let plan=Plan::build("naukri",json!({"actor_id":"fictional/public-jobs","build":"1.2.3","enabled":true,"reviewed":true,"review_expires_at":(now+chrono::Duration::hours(1)).to_rfc3339(),"platform_usage_included":true,"account_spending_limit_verified":true,"schema_evidence_url":"https://actor-fixture.example/schema","pricing_evidence_url":"https://actor-fixture.example/pricing","permission_evidence_url":"https://actor-fixture.example/permission","pricing_model":"PAY_PER_EVENT","estimated_per_item_usd":0.001,"field_map":{"limit":"maxItems"}}),json!({"limit":20}),Policy{monthly:Usd::parse("2").unwrap(),cap:Usd::parse("0.100001").unwrap(),allow_paid:true,credential_present:true,reviewed_build:BuildReview::parse(&json!({"build_id":"originalBuild","schema_digest":"a".repeat(64)})).unwrap()},now).unwrap();
        let actor = ActorIdentity::parse(
            &plan,
            &json!({"data":{"id":"originalActor","username":"fictional","name":"public-jobs"}}),
        )
        .unwrap();
        let run=Run::parse(&plan,&actor,&json!({"data":{"id":"originalRun","actId":"originalActor","buildId":"originalBuild","buildNumber":"1.2.3","status":"RUNNING","defaultDatasetId":"originalDataset","startedAt":now.to_rfc3339(),"finishedAt":null,"options":{"build":"1.2.3","timeoutSecs":60,"restartOnError":false,"maxTotalChargeUsd":0.100001,"maxItems":20}}}),None,now,now).unwrap();
        let values = BTreeMap::from([
            (
                "APIFY_API_TOKEN".into(),
                "PRIVATE_FICTIONAL_READ_TOKEN_CANARY".into(),
            ),
            (
                "RUST_APIFY_EXECUTION_FIXTURE_ORIGIN".into(),
                "http://127.0.0.1:65530/v2/".into(),
            ),
        ]);
        let client = Client::from_values(&values, true).unwrap();
        let outcome = client
            .execute(Permit {
                request: Uuid::from_u128(1),
                invocation: Uuid::from_u128(2),
                sequence: 1,
                target: plan.abort(&run).unwrap(),
                credential_context: client.context.clone().unwrap(),
                expires: now + chrono::Duration::seconds(45),
                read_only: true,
            })
            .await;
        assert_eq!(outcome.code, Some("apify_execution_target_denied"));
        assert!(!outcome.attempted);
        assert!(!outcome.response_observed);
        assert!(outcome.body.is_none());
    }
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
        if permit.read_only && target.method() != "GET" {
            outcome.code = Some("apify_execution_target_denied");
            return outcome;
        }
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
