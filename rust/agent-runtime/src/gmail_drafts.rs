//! Fixed Gmail draft-only transport. POST outcomes are never retried or called confirmed here.
use crate::{Failure, Result, mailboxes::message_id};
use reqwest::{
    Client, Method, Url,
    header::{AUTHORIZATION, HeaderValue},
};
use serde_json::{Value, json};
use std::time::Duration;
pub struct DraftClient {
    http: Client,
    base: Url,
    authorization: HeaderValue,
}
impl DraftClient {
    pub fn new(token: &str, fixture: bool, endpoint: Option<&str>) -> Result<Self> {
        if token.is_empty()
            || token.len() > 16384
            || !token.bytes().all(|c| (33..=126).contains(&c))
        {
            return Err(Failure("gmail_read_permission_required"));
        }
        let base = match (fixture, endpoint) {
            (false, None) => Url::parse("https://gmail.googleapis.com/gmail/v1/users/me/")
                .map_err(|_| Failure("gmail_draft_read_failed"))?,
            (true, Some(raw)) => {
                let url = Url::parse(raw).map_err(|_| Failure("gmail_fixture_endpoint_denied"))?;
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
            .map_err(|_| Failure("gmail_draft_read_failed"))?;
        Ok(Self {
            http,
            base,
            authorization,
        })
    }
    async fn request(
        &self,
        method: Method,
        path: &str,
        query: Vec<(&str, String)>,
        body: Option<Value>,
    ) -> Result<Value> {
        let invalid = Failure(if method == Method::POST {
            "gmail_draft_request_unconfirmed"
        } else {
            "gmail_draft_read_failed"
        });
        let work = async {
            let mut request = self
                .http
                .request(method, self.base.join(path).map_err(|_| invalid)?)
                .header(AUTHORIZATION, self.authorization.clone())
                .query(&query);
            if let Some(body) = body {
                request = request.json(&body);
            }
            let mut response = request.send().await.map_err(|_| invalid)?;
            if !matches!(response.status().as_u16(), 200 | 201) {
                return Err(invalid);
            }
            if response.content_length().is_some_and(|size| size > 1048576) {
                return Err(Failure("gmail_draft_response_limit"));
            }
            let mut bytes = Vec::new();
            while let Some(chunk) = response.chunk().await.map_err(|_| invalid)? {
                if bytes.len() + chunk.len() > 1048576 {
                    return Err(Failure("gmail_draft_response_limit"));
                }
                bytes.extend_from_slice(&chunk);
            }
            let value: Value = serde_json::from_slice(&bytes).map_err(|_| invalid)?;
            if !value.is_object() {
                return Err(Failure("gmail_draft_response_invalid"));
            }
            Ok(value)
        };
        tokio::time::timeout(Duration::from_secs(20), work)
            .await
            .map_err(|_| invalid)?
    }
    pub async fn list(&self, query: Option<&str>, limit: u8) -> Result<Value> {
        if limit == 0
            || limit > 10
            || query.is_some_and(|s| s.len() > 500 || !s.starts_with("rfc822msgid:"))
        {
            return Err(Failure("gmail_mailbox_operation_denied"));
        }
        let mut params = vec![("maxResults", limit.to_string())];
        if let Some(query) = query {
            params.push(("q", query.into()));
        }
        self.request(Method::GET, "drafts", params, None).await
    }
    pub async fn get(&self, id: &str) -> Result<Value> {
        message_id(id)?;
        self.request(
            Method::GET,
            &format!("drafts/{id}"),
            vec![("format", "full".into())],
            None,
        )
        .await
    }
    pub async fn create(&self, raw: &[u8]) -> Result<Value> {
        if raw.len() > 80000 {
            return Err(Failure("gmail_draft_request_limit"));
        }
        self.request(
            Method::POST,
            "drafts",
            vec![],
            Some(json!({"message":{"raw":crate::mail_evidence::encoded(raw)}})),
        )
        .await
    }
}
