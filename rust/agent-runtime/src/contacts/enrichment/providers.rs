//! Fixed provider transports. Billable requests consume a committed one-time dispatch grant.
use super::*;
use reqwest::{
    Client as Http, Method, Url,
    header::{HeaderName, HeaderValue},
};
use sha2::{Digest, Sha256};
use std::time::Duration;
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Name {
    Apollo,
    SignalHire,
}
impl Name {
    pub fn parse(raw: &str) -> Result<Self> {
        match raw {
            "apollo" => Ok(Self::Apollo),
            "signalhire" => Ok(Self::SignalHire),
            _ => Err(Failure("invalid_contact_provider")),
        }
    }
    pub fn name(self) -> &'static str {
        match self {
            Self::Apollo => "apollo",
            Self::SignalHire => "signalhire",
        }
    }
}
#[derive(Debug)]
pub struct Error {
    pub state: &'static str,
    pub code: &'static str,
    pub retry_after_seconds: Option<i64>,
}
impl Error {
    fn new(state: &'static str, code: &'static str) -> Self {
        Self {
            state,
            code,
            retry_after_seconds: None,
        }
    }
}
pub type Remote<T> = std::result::Result<T, Error>;
pub struct Clients {
    apollo: Option<Client>,
    signalhire: Option<Client>,
}
impl Clients {
    pub fn from_values(values: &BTreeMap<String, String>, fixture: bool) -> Result<Self> {
        for key in [
            "RUST_CONTACT_APOLLO_FIXTURE_ENDPOINT",
            "RUST_CONTACT_SIGNALHIRE_FIXTURE_ENDPOINT",
        ] {
            if !fixture && values.contains_key(key) {
                return Err(Failure("contact_fixture_endpoint_denied"));
            }
        }
        let settings = Settings::from_values(values)?;
        let timeout = values
            .get("CONTACT_PROVIDER_TIMEOUT_SECONDS")
            .map(String::as_str)
            .unwrap_or("20")
            .parse::<f64>()
            .ok()
            .filter(|n| n.is_finite() && (1.0..=60.0).contains(n))
            .ok_or(Failure("invalid_contact_provider_settings"))?;
        let build = |name: Name| -> Result<Option<Client>> {
            let config = settings
                .providers
                .iter()
                .find(|p| p.name == name.name())
                .expect("fixed provider");
            if !config.enabled || !config.credentials_configured {
                return Ok(None);
            }
            let key = values
                .get(&format!("{}_API_KEY", name.name().to_ascii_uppercase()))
                .ok_or(Failure("contact_provider_not_configured"))?;
            let endpoint = values
                .get(&format!(
                    "RUST_CONTACT_{}_FIXTURE_ENDPOINT",
                    name.name().to_ascii_uppercase()
                ))
                .map(String::as_str);
            Client::new(
                name,
                key,
                Duration::from_secs_f64(timeout),
                fixture,
                endpoint,
            )
            .map(Some)
        };
        Ok(Self {
            apollo: build(Name::Apollo)?,
            signalhire: build(Name::SignalHire)?,
        })
    }
    pub fn get(&self, name: &str) -> Result<&Client> {
        match Name::parse(name)? {
            Name::Apollo => self.apollo.as_ref(),
            Name::SignalHire => self.signalhire.as_ref(),
        }
        .ok_or(Failure("contact_provider_not_configured"))
    }
}
pub struct Client {
    http: Http,
    base: Url,
    name: Name,
    key: HeaderValue,
    key_hash: String,
    timeout: Duration,
}
impl Client {
    fn new(
        name: Name,
        key: &str,
        timeout: Duration,
        fixture: bool,
        endpoint: Option<&str>,
    ) -> Result<Self> {
        if key.is_empty() || key.len() > 4096 || !key.bytes().all(|b| (33..=126).contains(&b)) {
            return Err(Failure("invalid_contact_provider_settings"));
        }
        let base = match (fixture, endpoint) {
            (false, None) => Url::parse(match name {
                Name::Apollo => "https://api.apollo.io/api/v1/",
                Name::SignalHire => "https://www.signalhire.com/api/v1/",
            })
            .map_err(|_| Failure("invalid_contact_provider_settings"))?,
            (true, Some(raw)) => {
                let url =
                    Url::parse(raw).map_err(|_| Failure("contact_fixture_endpoint_denied"))?;
                if url.scheme() != "http"
                    || url.host_str() != Some("127.0.0.1")
                    || url.port().is_none_or(|p| p < 1025)
                    || url.path() != "/"
                    || !url.username().is_empty()
                    || url.password().is_some()
                    || url.query().is_some()
                    || url.fragment().is_some()
                {
                    return Err(Failure("contact_fixture_endpoint_denied"));
                }
                url
            }
            _ => return Err(Failure("contact_fixture_endpoint_denied")),
        };
        let mut header =
            HeaderValue::from_str(key).map_err(|_| Failure("invalid_contact_provider_settings"))?;
        header.set_sensitive(true);
        let http = Http::builder()
            .no_proxy()
            .retry(reqwest::retry::never())
            .redirect(reqwest::redirect::Policy::none())
            .connect_timeout(Duration::from_secs(5).min(timeout))
            .timeout(timeout)
            .pool_max_idle_per_host(1)
            .pool_idle_timeout(Duration::from_secs(15))
            .build()
            .map_err(|_| Failure("invalid_contact_provider_settings"))?;
        Ok(Self {
            http,
            base,
            name,
            key: header,
            key_hash: format!("{:x}", Sha256::digest(key.as_bytes())),
            timeout,
        })
    }
    pub fn provider(&self) -> &'static str {
        self.name.name()
    }
    async fn request(
        &self,
        method: Method,
        path: &str,
        body: Option<Value>,
        billable: bool,
    ) -> Remote<Reply> {
        let unknown = || {
            Error::new(
                if billable {
                    "billing_uncertain"
                } else {
                    "failed"
                },
                if billable {
                    "contact_provider_request_unconfirmed"
                } else {
                    "contact_provider_metadata_unavailable"
                },
            )
        };
        let work = async {
            let header = HeaderName::from_static(match self.name {
                Name::Apollo => "x-api-key",
                Name::SignalHire => "apikey",
            });
            let mut request = self
                .http
                .request(method, self.base.join(path).map_err(|_| unknown())?)
                .header(header, self.key.clone())
                .header("Accept", "application/json")
                .header("Cache-Control", "no-cache");
            if let Some(body) = body {
                request = request.json(&body);
            }
            let mut response = request.send().await.map_err(|_| unknown())?;
            let status = response.status().as_u16();
            let retry = response
                .headers()
                .get("retry-after")
                .and_then(|v| v.to_str().ok())
                .and_then(|s| {
                    s.parse::<i64>().ok().or_else(|| {
                        DateTime::parse_from_rfc2822(s)
                            .ok()
                            .map(|at| (at.with_timezone(&Utc) - Utc::now()).num_seconds())
                    })
                })
                .unwrap_or(60)
                .clamp(1, 86400);
            if status >= 300 {
                return Ok(Reply {
                    status,
                    body: Value::Null,
                    retry,
                });
            }
            if response.content_length().is_some_and(|n| n > 1048576) {
                return Err(unknown());
            }
            let mut bytes = Vec::new();
            while let Some(chunk) = response.chunk().await.map_err(|_| unknown())? {
                if bytes.len() + chunk.len() > 1048576 {
                    return Err(unknown());
                }
                bytes.extend_from_slice(&chunk);
            }
            let body = if bytes.is_empty() {
                Value::Null
            } else {
                serde_json::from_slice(&bytes).map_err(|_| unknown())?
            };
            Ok(Reply {
                status,
                body,
                retry,
            })
        };
        tokio::time::timeout(self.timeout, work)
            .await
            .map_err(|_| unknown())?
    }
    pub async fn introspect(
        &self,
        operation: capabilities::Operation,
        cost: i64,
        eligibility: &capabilities::Eligibility,
    ) -> Remote<LiveProof> {
        if !(0..=100).contains(&cost) {
            return Err(Error::new("failed", "invalid_contact_lookup_cost"));
        }
        let (finding, remaining, requests) = match self.name {
            Name::Apollo => {
                eligibility
                    .require(operation, Utc::now())
                    .map_err(|e| Error::new("authorization_required", e.0))?;
                let health = self
                    .request(Method::GET, "auth/health", None, false)
                    .await?
                    .success()?;
                if health["healthy"] != true || health["is_logged_in"] != true {
                    return Err(Error::new(
                        "authorization_required",
                        "contact_provider_authentication_required",
                    ));
                }
                let stats = self
                    .request(
                        Method::POST,
                        "usage_stats/api_usage_stats",
                        Some(json!({"endpoints":[operation.endpoint()]})),
                        false,
                    )
                    .await?
                    .success()?;
                let credits = self
                    .request(
                        Method::POST,
                        "usage_stats/credit_usage_stats",
                        Some(json!({})),
                        false,
                    )
                    .await?
                    .success()?;
                let finding = capabilities::preflight(
                    eligibility,
                    operation,
                    &health,
                    &stats,
                    &credits,
                    cost,
                    Utc::now(),
                )
                .map_err(|e| {
                    Error::new(
                        match e.0 {
                            "contact_provider_cooling_down" => "rate_limited",
                            "contact_provider_budget_exhausted" => "budget_exhausted",
                            _ => "authorization_required",
                        },
                        e.0,
                    )
                })?;
                let remaining = finding["credits"]["remaining"].as_u64().ok_or(Error::new(
                    "authorization_required",
                    "contact_apollo_capability_evidence_required",
                ))?;
                (finding, remaining, 3)
            }
            Name::SignalHire => {
                if operation != capabilities::Operation::Enrich {
                    return Err(Error::new(
                        "unsupported_operation",
                        "contact_signalhire_search_unsupported",
                    ));
                }
                let body = self
                    .request(Method::GET, "credits", None, false)
                    .await?
                    .success()?;
                let remaining = match &body["credits"] {
                    Value::Number(n) if !n.is_f64() => n.as_u64(),
                    _ => None,
                }
                .ok_or(Error::new(
                    "authorization_required",
                    "contact_signalhire_credit_evidence_required",
                ))?;
                if remaining < cost as u64 {
                    return Err(Error::new(
                        "budget_exhausted",
                        "contact_provider_budget_exhausted",
                    ));
                }
                (
                    json!({"provider":"signalhire","operation":"enrich_person","credits_remaining":remaining,"mailbox_verified":false}),
                    remaining,
                    1,
                )
            }
        };
        let observed_at = Utc::now();
        let expires_at = if self.name == Name::Apollo {
            eligibility
                .deadline(operation, observed_at)
                .map_err(|e| Error::new("authorization_required", e.0))?
                .min(observed_at + chrono::Duration::seconds(60))
        } else {
            observed_at + chrono::Duration::seconds(60)
        };
        Ok(LiveProof {
            provider: self.name,
            operation,
            cost,
            key_hash: self.key_hash.clone(),
            observed_at,
            expires_at,
            remaining,
            finding,
            requests,
        })
    }
    pub async fn execute(&self, grant: super::dispatch::Grant) -> Outcome {
        let invocation = grant.invocation();
        let reservation = grant.reservation().to_owned();
        let provider = grant.provider().to_owned();
        let request_hash = format!(
            "{:x}",
            Sha256::digest(grant.request().to_string().as_bytes())
        );
        let mut outcome = self.execute_inner(grant).await;
        let result_hash = format!(
            "{:x}",
            Sha256::digest(outcome.snapshot().to_string().as_bytes())
        );
        outcome.binding = Some(Binding {
            invocation,
            reservation,
            provider,
            request_hash,
            result_hash,
        });
        outcome
    }
    async fn execute_inner(&self, grant: super::dispatch::Grant) -> Outcome {
        if grant.provider() != self.provider()
            || grant.key_hash() != self.key_hash
            || Utc::now() >= grant.deadline()
        {
            return Outcome::error(Error::new(
                "failed",
                "contact_provider_dispatch_context_changed",
            ));
        }
        let request = grant.request();
        let operation = grant.operation();
        let (method, path, body) = match (self.name, operation) {
            (Name::Apollo, capabilities::Operation::Search) => (
                Method::POST,
                "mixed_people/api_search",
                json!({"q_organization_domains_list":[request["company_domain"]],"person_titles":request["target_roles"],"page":1,"per_page":request["max_people"]}),
            ),
            (Name::Apollo, capabilities::Operation::Enrich) => (
                Method::POST,
                "people/match",
                json!({"domain":request["company_domain"],"name":request["full_name"],"linkedin_url":request["linkedin_url"],"reveal_personal_emails":false,"reveal_phone_number":false,"run_waterfall_email":false,"run_waterfall_phone":false}),
            ),
            (Name::SignalHire, capabilities::Operation::Enrich) => (
                Method::POST,
                "candidate/search",
                json!({"items":[request["linkedin_url"]],"withoutWaterfall":true}),
            ),
            _ => {
                return Outcome::error(Error::new(
                    "unsupported_operation",
                    "contact_provider_operation_unsupported",
                ));
            }
        };
        let reply = match self.request(method, path, Some(body), true).await {
            Ok(r) => r,
            Err(e) => return Outcome::error(e),
        };
        if reply.status >= 300 {
            return Outcome::error(reply.error());
        }
        let mut result = Outcome {
            binding: None,
            state: "completed",
            observations: Vec::new(),
            provider_run_id: None,
            credits_used: None,
            retry_after_seconds: None,
            error_code: None,
            outcome_unknown: false,
        };
        let parsed = match (self.name, operation) {
            (Name::Apollo, capabilities::Operation::Search) => {
                if reply.status != 200 {
                    return Outcome::unknown("contact_provider_response_unconfirmed");
                }
                let Some(people) = reply.body["people"].as_array() else {
                    return Outcome::unknown("contact_provider_response_unconfirmed");
                };
                let maximum = request["max_people"].as_u64().unwrap_or(0) as usize;
                let mut seen = BTreeSet::new();
                let mut observations = Vec::new();
                for raw in people.iter().take(maximum) {
                    match person::apollo(raw, request) {
                        Ok(Some(p)) => {
                            let key = p["linkedin_url"]
                                .as_str()
                                .or_else(|| p["provider_person_id"].as_str())
                                .or_else(|| p["full_name"].as_str())
                                .unwrap_or("")
                                .to_owned();
                            if seen.insert(key) {
                                observations.push(p);
                            }
                        }
                        Ok(None) => {}
                        Err(e) => return Outcome::unknown(e.0),
                    }
                }
                result.credits_used = Some(0);
                Ok(observations)
            }
            (Name::Apollo, capabilities::Operation::Enrich) => {
                if reply.status != 200 || reply.body.get("person").is_none() {
                    return Outcome::unknown("contact_provider_response_unconfirmed");
                }
                if reply.body["person"].is_null() {
                    Ok(Vec::new())
                } else {
                    person::apollo(&reply.body["person"], request).map(|p| p.into_iter().collect())
                }
            }
            (Name::SignalHire, capabilities::Operation::Enrich) => {
                if reply.status == 204 {
                    result.state = "running";
                    result.outcome_unknown = true;
                    result.error_code = Some("contact_signalhire_async_unconfirmed");
                    return result;
                }
                if reply.status == 201 {
                    let id = match &reply.body["requestId"] {
                        Value::String(s) => Some(s.clone()),
                        Value::Number(n) if !n.is_f64() => Some(n.to_string()),
                        _ => None,
                    };
                    let Some(id) = id.filter(|s| {
                        !s.is_empty() && s.len() <= 255 && !s.chars().any(char::is_control)
                    }) else {
                        return Outcome::unknown("contact_provider_response_unconfirmed");
                    };
                    result.state = "queued";
                    result.provider_run_id = Some(id);
                    result.outcome_unknown = true;
                    result.error_code = Some("contact_signalhire_async_unconfirmed");
                    return result;
                }
                if reply.status != 200 {
                    return Outcome::unknown("contact_provider_response_unconfirmed");
                }
                let Some(entries) = reply.body.as_array().filter(|e| e.len() <= 1) else {
                    return Outcome::unknown("contact_provider_response_unconfirmed");
                };
                if entries.is_empty() {
                    Ok(Vec::new())
                } else {
                    let entry = &entries[0];
                    if entry["item"] != request["linkedin_url"] {
                        return Outcome::unknown("contact_provider_identifier_mismatch");
                    }
                    match entry["status"].as_str() {
                        Some("success") => person::signalhire(&entry["candidate"], request)
                            .map(|p| p.into_iter().collect()),
                        Some("failed") => Ok(Vec::new()),
                        Some("credits_are_over") => {
                            return Outcome::error(Error::new(
                                "budget_exhausted",
                                "contact_provider_budget_exhausted",
                            ));
                        }
                        Some("duplicate_query") => {
                            result.state = "running";
                            result.outcome_unknown = true;
                            result.error_code = Some("contact_provider_duplicate_query");
                            return result;
                        }
                        _ => return Outcome::unknown("contact_provider_response_unconfirmed"),
                    }
                }
            }
            _ => return Outcome::unknown("contact_provider_operation_unsupported"),
        };
        match parsed {
            Ok(observations) => {
                if observations.is_empty() {
                    result.state = "not_found";
                }
                result.observations = observations;
                result
            }
            Err(e) => Outcome::unknown(e.0),
        }
    }
}
struct Reply {
    status: u16,
    body: Value,
    retry: i64,
}
impl Reply {
    fn error(&self) -> Error {
        let (state, code) = match self.status {
            401 | 403 => (
                "authorization_required",
                "contact_provider_authentication_required",
            ),
            402 => ("budget_exhausted", "contact_provider_budget_exhausted"),
            404 => ("not_found", "contact_provider_not_found"),
            429 => ("rate_limited", "contact_provider_rate_limited"),
            _ => ("billing_uncertain", "contact_provider_request_unconfirmed"),
        };
        Error {
            state,
            code,
            retry_after_seconds: (self.status == 429).then_some(self.retry),
        }
    }
    fn success(self) -> Remote<Value> {
        if self.status == 200 {
            Ok(self.body)
        } else {
            let mut error = self.error();
            if error.state == "billing_uncertain" {
                error.state = "failed";
                error.code = "contact_provider_metadata_unavailable";
            }
            Err(error)
        }
    }
}
/// Single-use metadata evidence; only a fixed client can construct it after actual HTTP.
pub struct LiveProof {
    provider: Name,
    operation: capabilities::Operation,
    cost: i64,
    key_hash: String,
    observed_at: DateTime<Utc>,
    expires_at: DateTime<Utc>,
    remaining: u64,
    finding: Value,
    requests: u8,
}
impl LiveProof {
    pub fn finding(&self) -> Value {
        let mut result = self.finding.clone();
        result["provider_requests_performed"] = json!(self.requests);
        result["observed_at"] = json!(self.observed_at);
        result["expires_at"] = json!(self.expires_at);
        result["source"] = json!("fixed_provider_metadata_endpoints");
        result["lookup_authorized"] = json!(false);
        result
    }
    pub(super) fn check(
        &self,
        client: &Client,
        operation: capabilities::Operation,
        cost: i64,
        now: DateTime<Utc>,
    ) -> Result<()> {
        if self.provider != client.name
            || self.key_hash != client.key_hash
            || self.operation != operation
            || self.cost != cost
            || now < self.observed_at - chrono::Duration::seconds(2)
            || now >= self.expires_at
            || cost < 0
            || self.remaining < cost as u64
        {
            return Err(Failure("contact_provider_capability_context_changed"));
        }
        Ok(())
    }
    pub(super) fn key_hash(&self) -> &str {
        &self.key_hash
    }
    pub(super) fn deadline(&self) -> DateTime<Utc> {
        self.expires_at
    }
}
pub(super) struct Binding {
    pub invocation: Uuid,
    pub reservation: String,
    pub provider: String,
    pub request_hash: String,
    result_hash: String,
}
pub struct Outcome {
    binding: Option<Binding>,
    pub state: &'static str,
    pub observations: Vec<Value>,
    pub provider_run_id: Option<String>,
    pub credits_used: Option<u64>,
    pub retry_after_seconds: Option<i64>,
    pub error_code: Option<&'static str>,
    pub outcome_unknown: bool,
}
impl Outcome {
    pub(super) fn snapshot(&self) -> Value {
        json!({"state":self.state,"observations":self.observations,"provider_run_id":self.provider_run_id,"credits_used":self.credits_used,"retry_after_seconds":self.retry_after_seconds,"error_code":self.error_code,"outcome_unknown":self.outcome_unknown})
    }
    pub(super) fn binding(&self) -> Result<&Binding> {
        let binding = self
            .binding
            .as_ref()
            .ok_or(Failure("contact_provider_result_binding_required"))?;
        let hash = format!(
            "{:x}",
            Sha256::digest(self.snapshot().to_string().as_bytes())
        );
        if hash != binding.result_hash {
            return Err(Failure("contact_provider_result_changed"));
        }
        Ok(binding)
    }

    fn unknown(code: &'static str) -> Self {
        Self::error(Error::new("billing_uncertain", code))
    }
    fn error(error: Error) -> Self {
        Self {
            binding: None,
            state: error.state,
            observations: Vec::new(),
            provider_run_id: None,
            credits_used: None,
            retry_after_seconds: error.retry_after_seconds,
            error_code: Some(error.code),
            outcome_unknown: matches!(error.state, "billing_uncertain" | "queued" | "running"),
        }
    }
}

#[cfg(test)]
mod tests;
