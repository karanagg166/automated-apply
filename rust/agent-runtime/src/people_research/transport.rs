//! One fixed search-index POST consumes an opaque original grant. Result URLs are never fetched.
use super::{runs::Grant, settings::Settings};
use crate::{Failure, Result};
use chrono::Utc;
use reqwest::{Client as Http, Url, header::HeaderValue};
use serde_json::Value;
use std::{collections::BTreeMap, time::Duration};
pub struct Client {
    http: Http,
    endpoint: Url,
    key: HeaderValue,
    context: String,
}
pub(super) struct Outcome {
    pub(super) request: uuid::Uuid,
    pub(super) invocation: uuid::Uuid,
    pub(super) state: &'static str,
    pub(super) code: Option<&'static str>,
    pub(super) people: Vec<Value>,
    pub(super) errors: Vec<&'static str>,
    pub(super) retry: Option<i64>,
    pub(super) attempted: bool,
    pub(super) response_observed: bool,
}
impl Client {
    pub fn from_values(values: &BTreeMap<String, String>, fixture: bool) -> Result<Option<Self>> {
        let endpoint = values.get("RUST_PEOPLE_SEARCH_FIXTURE_ENDPOINT");
        if !fixture && endpoint.is_some() {
            return Err(Failure("public_research_fixture_endpoint_denied"));
        }
        let endpoint = match (fixture, endpoint) {
            (false, None) | (true, None) => Url::parse("https://google.serper.dev/search")
                .map_err(|_| Failure("invalid_public_research_settings"))?,
            (true, Some(raw)) => {
                let url = Url::parse(raw)
                    .map_err(|_| Failure("public_research_fixture_endpoint_denied"))?;
                if url.scheme() != "http"
                    || url.host_str() != Some("127.0.0.1")
                    || url.port().is_none_or(|p| p < 1025)
                    || url.path() != "/search"
                    || !url.username().is_empty()
                    || url.password().is_some()
                    || url.query().is_some()
                    || url.fragment().is_some()
                {
                    return Err(Failure("public_research_fixture_endpoint_denied"));
                }
                url
            }
            _ => return Err(Failure("public_research_fixture_endpoint_denied")),
        };
        let settings = Settings::from_values(values)?;
        let Some(key) = settings.key.as_ref().filter(|_| settings.enabled) else {
            return Ok(None);
        };
        let mut key =
            HeaderValue::from_str(key).map_err(|_| Failure("invalid_public_research_settings"))?;
        key.set_sensitive(true);
        let http = Http::builder()
            .no_proxy()
            .retry(reqwest::retry::never())
            .redirect(reqwest::redirect::Policy::none())
            .connect_timeout(Duration::from_secs(5))
            .timeout(Duration::from_secs(15))
            .pool_max_idle_per_host(1)
            .pool_idle_timeout(Duration::from_secs(15))
            .build()
            .map_err(|_| Failure("invalid_public_research_settings"))?;
        Ok(Some(Self {
            http,
            endpoint,
            key,
            context: settings.context,
        }))
    }
    pub(super) async fn execute(&self, grant: Grant) -> Outcome {
        let mut outcome = Outcome {
            request: grant.id,
            invocation: grant.invocation,
            state: "outcome_unknown",
            code: Some("public_research_original_dispatch_unconfirmed"),
            people: Vec::new(),
            errors: Vec::new(),
            retry: None,
            attempted: false,
            response_observed: false,
        };
        let now = Utc::now();
        if grant.context != self.context
            || now >= grant.deadline
            || grant.body["q"].as_str().is_none_or(|s| s.len() > 8192)
            || !grant.body["num"]
                .as_u64()
                .is_some_and(|n| (1..=20).contains(&n))
        {
            outcome.state = "not_dispatched";
            outcome.code = Some("public_research_original_grant_expired_or_changed");
            return outcome;
        }
        let expected = super::rules::query(&grant.input, now)
            .map(|q| serde_json::json!({"q":q,"num":grant.input["limit"]}));
        if expected.as_ref() != Ok(&grant.body) {
            outcome.state = "not_dispatched";
            outcome.code = Some("public_research_original_grant_changed");
            return outcome;
        }
        let remaining = (grant.deadline - now)
            .to_std()
            .unwrap_or_default()
            .min(Duration::from_secs(15));
        let request = self
            .http
            .post(self.endpoint.clone())
            .header("X-API-KEY", self.key.clone())
            .header("Accept", "application/json")
            .header("Cache-Control", "no-cache")
            .json(&grant.body)
            .timeout(remaining);
        let work = async {
            outcome.attempted = true;
            let mut response = match request.send().await {
                Ok(response) => response,
                Err(_) => return,
            };
            outcome.response_observed = true;
            let status = response.status().as_u16();
            if status == 429 {
                outcome.state = "rate_limited";
                outcome.code = Some("public_research_rate_limited");
                outcome.retry = Some(
                    response
                        .headers()
                        .get("retry-after")
                        .and_then(|v| v.to_str().ok())
                        .and_then(|s| {
                            s.parse::<i64>().ok().or_else(|| {
                                chrono::DateTime::parse_from_rfc2822(s)
                                    .ok()
                                    .map(|at| (at.to_utc() - Utc::now()).num_seconds())
                            })
                        })
                        .unwrap_or(60)
                        .clamp(1, 86400),
                );
                return;
            }
            if matches!(status, 401 | 403) {
                outcome.state = "authentication_required";
                outcome.code = Some("public_research_provider_authentication_required");
                return;
            }
            if status != 200 {
                outcome.state = "upstream_error";
                outcome.code = Some("public_research_http_unavailable");
                return;
            }
            if response.content_length().is_some_and(|n| n > 1048576) {
                outcome.code = Some("public_research_response_limit");
                return;
            }
            let mut bytes = Vec::new();
            loop {
                match response.chunk().await {
                    Ok(Some(chunk)) => {
                        if bytes.len() + chunk.len() > 1048576 {
                            outcome.code = Some("public_research_response_limit");
                            return;
                        }
                        bytes.extend_from_slice(&chunk);
                    }
                    Ok(None) => break,
                    Err(_) => return,
                }
            }
            let payload: Value = match serde_json::from_slice(&bytes) {
                Ok(v) => v,
                Err(_) => {
                    outcome.code = Some("public_research_invalid_provider_response");
                    return;
                }
            };
            let Some(records) = payload.get("organic").filter(|v| v.is_array()) else {
                outcome.code = Some("public_research_invalid_provider_response");
                return;
            };
            let now = Utc::now();
            let parsed = if grant.input["research_mode"] == "official_company" {
                grant
                    .permission
                    .as_ref()
                    .ok_or(Failure("public_research_permission_required"))
                    .and_then(|permission| {
                        super::rules::official_people(records, &grant.input, now, permission)
                    })
            } else {
                super::rules::public_profiles(records, &grant.input, now)
            };
            let parsed = match parsed {
                Ok(v) => v,
                Err(_) => {
                    outcome.code = Some("public_research_invalid_provider_response");
                    return;
                }
            };
            let Some(people) = parsed["people"].as_array() else {
                outcome.code = Some("public_research_invalid_provider_response");
                return;
            };
            let people = if grant.input["research_mode"] == "public_profiles" {
                match super::rules::unique_people(people.clone(), now) {
                    Ok(v) => v,
                    Err(_) => {
                        outcome.code = Some("public_research_invalid_provider_response");
                        return;
                    }
                }
            } else {
                people.clone()
            };
            let errors = parsed["errors"]
                .as_array()
                .map(|a| {
                    a.iter()
                        .map(|_| "public_search_record_invalid")
                        .collect::<Vec<_>>()
                })
                .unwrap_or_default();
            outcome.state = if !errors.is_empty() {
                "partial"
            } else if people.is_empty() {
                "no_results"
            } else {
                "success"
            };
            outcome.code = None;
            outcome.people = people;
            outcome.errors = errors;
        };
        let _ = tokio::time::timeout(remaining, work).await;
        outcome
    }
}
