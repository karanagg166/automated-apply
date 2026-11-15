//! Closed GET-only Gmail transport. Account consent/retention are enforced by the service caller.
use crate::{Failure, Result};
use reqwest::{
    Client, Url,
    header::{AUTHORIZATION, HeaderValue},
};
use serde_json::Value;
use std::time::Duration;
const MAX_BYTES: usize = 1024 * 1024;
pub struct ReadClient {
    http: Client,
    base: Url,
    authorization: HeaderValue,
}
impl ReadClient {
    pub fn new(token: &str, fixture: bool, endpoint: Option<&str>) -> Result<Self> {
        if token.is_empty()
            || token.len() > 16384
            || !token.bytes().all(|b| (33..=126).contains(&b))
        {
            return Err(Failure("gmail_read_permission_required"));
        }
        let base = match (fixture, endpoint) {
            (false, None) => Url::parse("https://gmail.googleapis.com/gmail/v1/users/me/")
                .map_err(|_| Failure("gmail_read_transport_or_response_error"))?,
            (true, Some(value)) => {
                let url =
                    Url::parse(value).map_err(|_| Failure("gmail_fixture_endpoint_denied"))?;
                if url.scheme() != "http"
                    || url.host_str() != Some("127.0.0.1")
                    || url.port().is_none_or(|p| p < 1025)
                    || url.path() != "/"
                    || !url.username().is_empty()
                    || url.password().is_some()
                    || url.query().is_some()
                    || url.fragment().is_some()
                {
                    return Err(Failure("gmail_fixture_endpoint_denied"));
                }
                url
            }
            _ => return Err(Failure("gmail_fixture_endpoint_denied")),
        };
        let mut authorization = HeaderValue::from_str(&format!("Bearer {token}"))
            .map_err(|_| Failure("gmail_read_permission_required"))?;
        authorization.set_sensitive(true);
        let http = Client::builder()
            .no_proxy()
            .redirect(reqwest::redirect::Policy::none())
            .retry(reqwest::retry::never())
            .connect_timeout(Duration::from_secs(5))
            .timeout(Duration::from_secs(15))
            .build()
            .map_err(|_| Failure("gmail_read_transport_or_response_error"))?;
        Ok(Self {
            http,
            base,
            authorization,
        })
    }
    async fn get(&self, path: &str, params: Vec<(&str, String)>) -> Result<Value> {
        let work = async {
            let target = self
                .base
                .join(path)
                .map_err(|_| Failure("gmail_read_operation_denied"))?;
            let mut response = self
                .http
                .get(target)
                .header(AUTHORIZATION, self.authorization.clone())
                .query(&params)
                .send()
                .await
                .map_err(|_| Failure("gmail_read_transport_or_response_error"))?;
            match response.status().as_u16() {
                401 | 403 => return Err(Failure("gmail_read_permission_required")),
                429 => return Err(Failure("gmail_read_rate_limited")),
                200 => {}
                _ => return Err(Failure("gmail_read_upstream_error")),
            }
            if response
                .content_length()
                .is_some_and(|n| n > MAX_BYTES as u64)
            {
                return Err(Failure("gmail_read_response_limit"));
            }
            let mut bytes = Vec::new();
            while let Some(chunk) = response
                .chunk()
                .await
                .map_err(|_| Failure("gmail_read_transport_or_response_error"))?
            {
                if bytes.len() + chunk.len() > MAX_BYTES {
                    return Err(Failure("gmail_read_response_limit"));
                }
                bytes.extend_from_slice(&chunk);
            }
            let value: Value = serde_json::from_slice(&bytes)
                .map_err(|_| Failure("gmail_read_transport_or_response_error"))?;
            if !value.is_object() {
                return Err(Failure("gmail_read_invalid_response"));
            }
            Ok(value)
        };
        tokio::time::timeout(Duration::from_secs(20), work)
            .await
            .map_err(|_| Failure("gmail_read_transport_or_response_error"))?
    }
    pub async fn messages(
        &self,
        labels: &[String],
        query: Option<&str>,
        page: Option<&str>,
        limit: i64,
    ) -> Result<Value> {
        let mut params = vec![("maxResults", limit.clamp(1, 25).to_string())];
        params.extend(labels.iter().map(|label| ("labelIds", label.clone())));
        if let Some(query) = query.filter(|s| !s.is_empty()) {
            params.push(("q", query.into()));
        }
        if let Some(page) = page.filter(|s| !s.is_empty()) {
            params.push(("pageToken", page.into()));
        }
        self.get("messages", params).await
    }
    pub async fn message(&self, id: &str, body: bool) -> Result<Value> {
        if id.is_empty()
            || id.len() > 200
            || !id
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
        {
            return Err(Failure("gmail_message_id_invalid"));
        }
        if [
            "send",
            "modify",
            "trash",
            "untrash",
            "delete",
            "import",
            "insert",
            "batchDelete",
            "batchModify",
        ]
        .contains(&id)
        {
            return Err(Failure("gmail_read_operation_denied"));
        }
        let mut params = vec![("format", if body { "full" } else { "metadata" }.into())];
        params.extend(
            [
                "From",
                "Subject",
                "Date",
                "To",
                "Message-ID",
                "Authentication-Results",
            ]
            .into_iter()
            .map(|header| ("metadataHeaders", header.into())),
        );
        self.get(&format!("messages/{id}"), params).await
    }
}
