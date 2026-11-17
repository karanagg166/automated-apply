//! Fixed GET-only metadata transport. No execution or private storage API exists here.
use crate::{Failure, Result};
use chrono::Utc;
use reqwest::{
    Client as Http, Url,
    header::{AUTHORIZATION, HeaderValue},
};
use serde_json::Value;
use std::{collections::BTreeMap, time::Duration};

pub struct Client {
    http: Http,
    base: Url,
    token: Option<HeaderValue>,
}
impl Client {
    pub fn from_values(values: &BTreeMap<String, String>, fixture: bool) -> Result<Self> {
        let configured = values.get("RUST_APIFY_METADATA_FIXTURE_ORIGIN");
        if !fixture && configured.is_some() {
            return Err(Failure("apify_metadata_fixture_origin_denied"));
        }
        let base = Url::parse(
            configured
                .map(String::as_str)
                .unwrap_or("https://api.apify.com/v2/"),
        )
        .map_err(|_| Failure("apify_metadata_fixture_origin_denied"))?;
        if configured.is_some()
            && (base.scheme() != "http"
                || base.host_str() != Some("127.0.0.1")
                || base.port().is_none_or(|p| p < 1025)
                || base.path() != "/v2/"
                || !base.username().is_empty()
                || base.password().is_some()
                || base.query().is_some()
                || base.fragment().is_some())
        {
            return Err(Failure("apify_metadata_fixture_origin_denied"));
        }
        let token = values
            .get("APIFY_API_TOKEN")
            .filter(|s| !s.trim().is_empty())
            .map(|s| {
                if s.len() > 8192 || s.chars().any(char::is_whitespace) {
                    return Err(Failure("invalid_apify_metadata_settings"));
                }
                let mut header = HeaderValue::from_str(&format!("Bearer {s}"))
                    .map_err(|_| Failure("invalid_apify_metadata_settings"))?;
                header.set_sensitive(true);
                Ok(header)
            })
            .transpose()?;
        let http = Http::builder()
            .no_proxy()
            .retry(reqwest::retry::never())
            .redirect(reqwest::redirect::Policy::none())
            .connect_timeout(Duration::from_secs(5))
            .timeout(Duration::from_secs(15))
            .pool_max_idle_per_host(1)
            .pool_idle_timeout(Duration::from_secs(15))
            .build()
            .map_err(|_| Failure("invalid_apify_metadata_settings"))?;
        Ok(Self { http, base, token })
    }
    pub fn token_configured(&self) -> bool {
        self.token.is_some()
    }
    async fn get(
        &self,
        path: &str,
        query: &[(&str, String)],
        authenticated: bool,
    ) -> Result<Value> {
        let url = self
            .base
            .join(path)
            .map_err(|_| Failure("apify_metadata_path_invalid"))?;
        if url.origin() != self.base.origin() || !url.path().starts_with(self.base.path()) {
            return Err(Failure("apify_metadata_path_invalid"));
        }
        let mut request = self
            .http
            .get(url)
            .query(query)
            .header("Accept", "application/json")
            .header("Cache-Control", "no-cache");
        if authenticated {
            request = request.header(
                AUTHORIZATION,
                self.token
                    .as_ref()
                    .ok_or(Failure("apify_local_token_not_configured"))?
                    .clone(),
            );
        }
        let work = async {
            let mut response = request
                .send()
                .await
                .map_err(|_| Failure("apify_metadata_transport_error"))?;
            match response.status().as_u16() {
                200 => {}
                401 | 403 => return Err(Failure("apify_metadata_authentication_required")),
                429 => return Err(Failure("apify_metadata_rate_limited")),
                _ => return Err(Failure("apify_metadata_http_unavailable")),
            }
            if response.content_length().is_some_and(|n| n > 1048576) {
                return Err(Failure("apify_metadata_response_limit"));
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
                return Err(Failure("apify_metadata_json_required"));
            }
            let mut bytes = Vec::new();
            while let Some(chunk) = response
                .chunk()
                .await
                .map_err(|_| Failure("apify_metadata_transport_error"))?
            {
                if bytes.len() + chunk.len() > 1048576 {
                    return Err(Failure("apify_metadata_response_limit"));
                }
                bytes.extend_from_slice(&chunk);
            }
            serde_json::from_slice(&bytes).map_err(|_| Failure("apify_metadata_json_invalid"))
        };
        tokio::time::timeout(Duration::from_secs(15), work)
            .await
            .map_err(|_| Failure("apify_metadata_timeout"))?
    }
    pub async fn actor(&self, actor_id: &str) -> Result<Value> {
        let safe = crate::apify_config::safe_actor(actor_id)?;
        let work = async {
            let payload = self.get(&format!("actors/{safe}"), &[], false).await?;
            let document = self
                .get(
                    &format!("actors/{safe}/builds/default/openapi.json"),
                    &[],
                    false,
                )
                .await?;
            super::actor(actor_id, &payload, &document, Utc::now())
        };
        tokio::time::timeout(Duration::from_secs(20), work)
            .await
            .map_err(|_| Failure("apify_metadata_timeout"))?
    }
    pub async fn account(&self) -> Result<Value> {
        if self.token.is_none() {
            return Err(Failure("apify_local_token_not_configured"));
        }
        let work = async {
            let limits = self.get("users/me/limits", &[], true).await?;
            let usage = self.get("users/me/usage/monthly", &[], true).await?;
            super::account(&limits, &usage, Utc::now())
        };
        tokio::time::timeout(Duration::from_secs(20), work)
            .await
            .map_err(|_| Failure("apify_metadata_timeout"))?
    }
    pub async fn discover(&self, query: &str, limit: usize) -> Result<Vec<Value>> {
        if !(1..=100).contains(&query.chars().count()) || !(1..=20).contains(&limit) {
            return Err(Failure("apify_store_query_invalid"));
        }
        let payload = self
            .get(
                "store",
                &[("search", query.into()), ("limit", limit.to_string())],
                false,
            )
            .await?;
        super::store(&payload, limit)
    }
}
