//! Official MCP SDK over bounded stdio. The local API remains the authority boundary.
use crate::{
    Failure, Result,
    configuration::{Configuration, private_values},
};
use rmcp::{
    ErrorData, ServerHandler, ServiceExt,
    model::*,
    service::{RequestContext, RoleServer},
    transport::{async_rw::AsyncRwTransport, io::stdio},
};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{path::Path, time::Duration};
use tokio::sync::Semaphore;
use uuid::Uuid;

pub struct Bridge {
    token: String,
    endpoint: String,
    http: reqwest::Client,
    requests: Semaphore,
    telegram: bool,
}
impl Bridge {
    pub fn load(path: &Path) -> Result<Self> {
        let config = Configuration::from_values(&private_values(path)?)?;
        if config.listen().port() < 1025 {
            return Err(Failure("invalid_mcp_api_endpoint"));
        }
        if config.require_tls && config.local_socket.is_none() {
            return Err(Failure("mcp_private_socket_required"));
        }
        let mut builder = reqwest::Client::builder()
            .no_proxy()
            .retry(reqwest::retry::never())
            .redirect(reqwest::redirect::Policy::none())
            .connect_timeout(Duration::from_secs(3))
            .timeout(Duration::from_secs(15));
        if let Some(path) = &config.local_socket {
            builder = builder.unix_socket(path.as_path());
        }
        let http = builder
            .build()
            .map_err(|_| Failure("mcp_transport_unavailable"))?;
        let telegram = config.telegram_enabled();
        Ok(Self {
            endpoint: format!("http://{}", config.listen()),
            token: config.token,
            http,
            requests: Semaphore::new(2),
            telegram,
        })
    }
    pub fn catalog(&self) -> Vec<Tool> {
        let empty = json!({"type":"object","properties":{},"additionalProperties":false});
        let search = json!({"type":"object","properties":{"limit":{"type":"integer","minimum":1,"maximum":50,"default":20}},"additionalProperties":false});
        let mut list = vec![
            definition(
                "runtime_status",
                "Read runtime controls and explicit adapter availability.",
                empty.clone(),
                true,
            ),
            definition(
                "browser_readiness",
                "Inspect selected Brave, Edge or Safari without launching a browser.",
                empty.clone(),
                true,
            ),
            definition(
                "naukri_saved_jobs",
                "Read saved Naukri jobs only; this does not discover or apply live.",
                search.clone(),
                true,
            ),
            definition(
                "instahyre_saved_jobs",
                "Read saved Instahyre jobs only; this does not establish a working live adapter.",
                search.clone(),
                true,
            ),
            definition(
                "application_history",
                "Read current confirmed profile application history; no replay.",
                empty.clone(),
                true,
            ),
            definition(
                "telegram_status",
                "Read owner-only Telegram configuration status without credentials.",
                empty,
                true,
            ),
            definition(
                "match_saved_job",
                "Score a saved job against the current profile; no profile override or write.",
                json!({"type":"object","properties":{"job_id":{"type":"string","format":"uuid"}},"required":["job_id"],"additionalProperties":false}),
                true,
            ),
        ];
        for (name, description) in [
            (
                "himalayas_discover",
                "Read the cached, attributed first page of the official Himalayas public API. At most one fetch per day; no account or application action.",
            ),
            (
                "we_work_remotely_discover",
                "Read the cached, attributed official We Work Remotely RSS feed. At most one fetch per 30 minutes; no account or application action.",
            ),
        ] {
            list.push(definition(name,description,json!({"type":"object","properties":{"limit":{"type":"integer","minimum":1,"maximum":20,"default":20}},"additionalProperties":false}),true));
        }
        for name in ["himalayas_ingest", "we_work_remotely_ingest"] {
            list.push(definition(name,"Explicitly save a completed public feed batch as unverified discovered jobs; never apply or overwrite owner decisions.",json!({"type":"object","properties":{"batch_token":{"type":"string","format":"uuid"}},"required":["batch_token"],"additionalProperties":false}),false));
        }
        for name in [
            "internshala_saved_jobs",
            "wellfound_saved_jobs",
            "ycombinator_saved_jobs",
            "hiringcafe_saved_jobs",
            "himalayas_saved_jobs",
            "we_work_remotely_saved_jobs",
        ] {
            list.push(definition(name,"Read saved platform jobs only. Saved records do not establish live account, application or receipt verification.",search.clone(),true));
        }
        if self.telegram {
            list.push(definition("telegram_notify_run","Queue one fixed notice per existing run for the paired owner. No recipient or text input.",json!({"type":"object","properties":{"run_id":{"type":"string","format":"uuid"}},"required":["run_id"],"additionalProperties":false}),false))
        }
        list
    }
    pub async fn call(&self, name: &str, args: Value) -> Result<Value> {
        let _permit = self
            .requests
            .try_acquire()
            .map_err(|_| Failure("mcp_request_busy"))?;
        if name == "telegram_notify_run" && !self.telegram {
            return Err(Failure("telegram_adapter_not_enabled"));
        }
        let (method, path, body) = operation(name, args)?;
        let mut request = self
            .http
            .request(method, format!("{}{}", self.endpoint, path))
            .bearer_auth(&self.token);
        if let Some(body) = body {
            request = request.json(&body)
        }
        let mut response = request
            .send()
            .await
            .map_err(|_| Failure("mcp_api_unavailable"))?;
        if !response.status().is_success() {
            return Err(Failure(match response.status().as_u16() {
                401 | 403 => "mcp_api_authorization_denied",
                404 => "mcp_resource_unavailable",
                409 | 428 => "mcp_current_review_required",
                429 => "mcp_api_busy",
                _ => "mcp_api_unavailable",
            }));
        }
        let mut bytes = Vec::new();
        while let Some(chunk) = response
            .chunk()
            .await
            .map_err(|_| Failure("mcp_response_invalid"))?
        {
            if bytes.len() + chunk.len() > 262144 {
                return Err(Failure("mcp_response_too_large"));
            }
            bytes.extend_from_slice(&chunk);
        }
        serde_json::from_slice(&bytes).map_err(|_| Failure("mcp_response_invalid"))
    }
}
fn definition(name: &'static str, description: &'static str, schema: Value, read: bool) -> Tool {
    let mut tool = Tool::new(name, description, schema.as_object().unwrap().clone());
    tool.annotations = Some(
        ToolAnnotations::new()
            .read_only(read)
            .destructive(false)
            .idempotent(true)
            .open_world(!read),
    );
    tool
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Empty {}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Search {
    #[serde(default = "default_limit")]
    limit: u8,
}
fn default_limit() -> u8 {
    20
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Job {
    job_id: Uuid,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Run {
    run_id: Uuid,
}
fn decode<T: serde::de::DeserializeOwned>(value: Value) -> Result<T> {
    serde_json::from_value(value).map_err(|_| Failure("invalid_tool_arguments"))
}
fn operation(name: &str, args: Value) -> Result<(reqwest::Method, String, Option<Value>)> {
    use reqwest::Method;
    if matches!(name, "himalayas_ingest" | "we_work_remotely_ingest") {
        let input: crate::feed_ingestion::Input = decode(args)?;
        let platform = if name == "himalayas_ingest" {
            "himalayas"
        } else {
            "we_work_remotely"
        };
        return Ok((
            Method::POST,
            format!("/api/v1/rust-agent/platforms/{platform}/ingest"),
            Some(json!({"batch_token":input.batch_token})),
        ));
    }
    if matches!(name, "himalayas_discover" | "we_work_remotely_discover") {
        let input: Search = decode(args)?;
        if !(1..=20).contains(&input.limit) {
            return Err(Failure("invalid_tool_arguments"));
        }
        let platform = if name == "himalayas_discover" {
            "himalayas"
        } else {
            "we_work_remotely"
        };
        return Ok((
            Method::POST,
            format!("/api/v1/rust-agent/platforms/{platform}/discover"),
            Some(json!({"limit":input.limit})),
        ));
    }
    if matches!(
        name,
        "naukri_saved_jobs"
            | "instahyre_saved_jobs"
            | "internshala_saved_jobs"
            | "wellfound_saved_jobs"
            | "ycombinator_saved_jobs"
            | "hiringcafe_saved_jobs"
            | "himalayas_saved_jobs"
            | "we_work_remotely_saved_jobs"
    ) {
        let input: Search = decode(args)?;
        if !(1..=50).contains(&input.limit) {
            return Err(Failure("invalid_tool_arguments"));
        }
        let platform = name
            .strip_suffix("_saved_jobs")
            .ok_or(Failure("unknown_mcp_tool"))?;
        return Ok((
            Method::POST,
            format!("/api/v1/rust-agent/platforms/{platform}/saved-jobs"),
            Some(json!({"limit":input.limit})),
        ));
    }
    if name == "match_saved_job" {
        let input: Job = decode(args)?;
        return Ok((
            Method::POST,
            format!("/api/v1/jobs/{}/match", input.job_id),
            Some(json!({})),
        ));
    }
    if name == "telegram_notify_run" {
        let input: Run = decode(args)?;
        return Ok((
            Method::POST,
            format!("/api/v1/rust-agent/runs/{}/notify-telegram", input.run_id),
            Some(json!({})),
        ));
    }
    let _: Empty = decode(args)?;
    let tail = match name {
        "runtime_status" => "capabilities",
        "browser_readiness" => "browser",
        "application_history" => "application-history",
        "telegram_status" => "telegram",
        _ => return Err(Failure("unknown_mcp_tool")),
    };
    Ok((Method::GET, format!("/api/v1/rust-agent/{tail}"), None))
}
impl ServerHandler for Bridge {
    fn get_info(&self) -> ServerConfig {
        let mut config = ServerConfig::default();
        config.capabilities = ServerCapabilities::builder().enable_tools().build();
        config.server_info =
            Implementation::new("automated-apply-tools", env!("CARGO_PKG_VERSION"));
        config.instructions=Some("Saved data and bounded owner tools. Availability never authorizes applications, paid providers, account changes or uncertain-action replay.".into());
        config
    }
    async fn list_tools(
        &self,
        _: Option<PaginatedRequestParams>,
        _: RequestContext<RoleServer>,
    ) -> std::result::Result<ListToolsResult, ErrorData> {
        Ok(ListToolsResult {
            tools: self.catalog(),
            ..Default::default()
        })
    }
    fn get_tool(&self, name: &str) -> Option<Tool> {
        self.catalog().into_iter().find(|tool| tool.name == name)
    }
    async fn call_tool(
        &self,
        request: CallToolRequestParams,
        _: RequestContext<RoleServer>,
    ) -> std::result::Result<CallToolResponse, ErrorData> {
        let args = Value::Object(request.arguments.unwrap_or_default());
        let result =
            match tokio::time::timeout(Duration::from_secs(20), self.call(&request.name, args))
                .await
            {
                Ok(Ok(value)) => CallToolResult::structured(value),
                Ok(Err(error)) => CallToolResult::structured_error(json!({"code":error.0})),
                Err(_) => CallToolResult::structured_error(
                    json!({"code":"mcp_outcome_unknown_do_not_replay"}),
                ),
            };
        Ok(result.into())
    }
}
pub async fn serve(path: &Path) -> Result<()> {
    let bridge = Bridge::load(path)?;
    let (read, write) = stdio();
    let transport =
        AsyncRwTransport::<RoleServer, _, _>::new(read, write).with_max_line_length(65536);
    let service = bridge
        .serve(transport)
        .await
        .map_err(|_| Failure("mcp_initialization_failed"))?;
    service
        .waiting()
        .await
        .map_err(|_| Failure("mcp_transport_failed"))?;
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn tools_never_accept_urls_recipients_text_or_policy_overrides() {
        for (name, args) in [
            ("naukri_saved_jobs", json!({"limit":51})),
            ("instahyre_saved_jobs", json!({"limit":0})),
            ("runtime_status", json!({"url":"https://example.com"})),
            (
                "telegram_notify_run",
                json!({"run_id":Uuid::new_v4(),"text":"injected"}),
            ),
            ("match_saved_job", json!({"job_id":"../../control"})),
            ("submit_application", json!({})),
        ] {
            assert!(operation(name, args).is_err());
        }
        let (_, path, body) = operation("instahyre_saved_jobs", json!({})).unwrap();
        assert_eq!(path, "/api/v1/rust-agent/platforms/instahyre/saved-jobs");
        assert_eq!(body, Some(json!({"limit":20})));
        let (_, _, body) = operation("match_saved_job", json!({"job_id":Uuid::new_v4()})).unwrap();
        assert_eq!(body, Some(json!({})));
    }
}
