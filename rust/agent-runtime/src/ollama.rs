//! Explicit local-only structured drafts. Never starts a daemon, pulls a model or retries.
use crate::{
    Failure, Result,
    configuration::boolean,
    grounding::ModelAnswer,
    monthly,
    provider::{WritingAttempt, answer_schema, bounded_json, usage_counter, writing_payload},
};
use serde_json::{Value, json};
use sqlx::PgConnection;
use std::{collections::BTreeMap, sync::Arc, time::Duration};

pub(crate) struct OllamaModel {
    client: reqwest::Client,
    endpoint: String,
    model: String,
    requests: u32,
    input: u32,
    output: u32,
    timeout: Duration,
    pub(crate) gate: Arc<tokio::sync::Semaphore>,
}
fn number(values: &BTreeMap<String, String>, name: &str, default: u32, max: u32) -> Result<u32> {
    values
        .get(name)
        .map(|s| {
            s.parse::<u32>()
                .ok()
                .filter(|n| *n <= max)
                .ok_or(Failure("invalid_provider_configuration"))
        })
        .unwrap_or(Ok(default))
}
fn identifier(value: &str) -> Result<()> {
    if value.to_ascii_lowercase().contains("cloud") {
        return Err(Failure("cloud_model_forbidden"));
    }
    if value.is_empty()
        || value.len() > 100
        || !value.as_bytes()[0].is_ascii_alphanumeric()
        || !value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b":._-".contains(&b))
    {
        return Err(Failure("invalid_model"));
    }
    Ok(())
}
impl OllamaModel {
    pub(crate) fn for_rearrangement(
        values: &BTreeMap<String, String>,
        fixture: bool,
    ) -> Result<Self> {
        if values.get("LLM_PROVIDER").map(String::as_str) != Some("ollama")
            || !boolean(values, "OLLAMA_GENERATION_AUTHORIZED", false)?
        {
            return Err(Failure("provider_execution_not_authorized"));
        }
        let mut selected = values.clone();
        selected.insert("OLLAMA_ENABLED".into(), "true".into());
        Self::from_values(&selected, fixture)
    }
    pub(crate) fn from_values(values: &BTreeMap<String, String>, fixture: bool) -> Result<Self> {
        if !boolean(values, "OLLAMA_ENABLED", false)? {
            return Err(Failure("provider_execution_not_authorized"));
        }
        let model = values
            .get("OLLAMA_MODEL")
            .ok_or(Failure("explicit_model_required"))?
            .clone();
        identifier(&model)?;
        let endpoint = match values.get("RUST_OLLAMA_FIXTURE_ENDPOINT") {
            Some(endpoint) if fixture => {
                let u = reqwest::Url::parse(endpoint)
                    .map_err(|_| Failure("provider_fixture_endpoint_denied"))?;
                if u.scheme() != "http"
                    || u.host_str() != Some("127.0.0.1")
                    || u.port().is_none_or(|p| p < 1025)
                    || !u.username().is_empty()
                    || u.password().is_some()
                    || u.path() != "/"
                    || u.query().is_some()
                    || u.fragment().is_some()
                {
                    return Err(Failure("provider_fixture_endpoint_denied"));
                }
                endpoint.trim_end_matches('/').to_string()
            }
            None if !fixture => "http://127.0.0.1:11434".into(),
            _ => return Err(Failure("provider_fixture_endpoint_denied")),
        };
        let requests = number(values, "LLM_MONTHLY_MAX_REQUESTS", 200, 10000)?;
        let input = number(values, "LLM_MAX_INPUT_CHARS", 16000, 64000)?.min(5000);
        let output = number(values, "LLM_MAX_OUTPUT_TOKENS", 1000, 8192)?.min(256);
        let seconds = values
            .get("LLM_TIMEOUT_SECONDS")
            .map(|s| s.parse::<f64>().unwrap_or(f64::NAN))
            .unwrap_or(30.0);
        if input < 1000 || output < 64 || !seconds.is_finite() || !(1.0..=120.0).contains(&seconds)
        {
            return Err(Failure("invalid_provider_configuration"));
        }
        let timeout = Duration::from_secs_f64(seconds);
        let client = reqwest::Client::builder()
            .no_proxy()
            .retry(reqwest::retry::never())
            .redirect(reqwest::redirect::Policy::none())
            .connect_timeout(Duration::from_secs(5))
            .timeout(timeout)
            .build()
            .map_err(|_| Failure("provider_transport_configuration"))?;
        Ok(Self {
            client,
            endpoint,
            model,
            requests,
            input,
            output,
            timeout,
            gate: Arc::new(tokio::sync::Semaphore::new(1)),
        })
    }
    fn body(&self, question: &str, context: &Value, instructions: &Value) -> Result<Vec<u8>> {
        let payload = serde_json::to_string(&writing_payload(question, context, instructions))
            .map_err(|_| Failure("invalid_answer_request"))?;
        let body = json!({"model":self.model,"stream":false,"system":include_str!("../schemas/answer-system.txt"),"prompt":payload,"format":answer_schema(),"keep_alive":0,"options":{"temperature":0,"seed":0,"num_ctx":2048,"num_thread":2,"num_predict":self.output}});
        let bytes = serde_json::to_vec(&body).map_err(|_| Failure("invalid_answer_request"))?;
        if bytes.len() > self.input as usize {
            return Err(Failure("input_limit_exceeded"));
        }
        Ok(bytes)
    }
    async fn request(&self, path: &str, body: Option<Value>) -> Result<Value> {
        let url = format!("{}{path}", self.endpoint);
        let builder = if let Some(body) = body {
            self.client.post(url).json(&body)
        } else {
            self.client.get(url)
        };
        read(
            builder
                .header("Accept-Encoding", "identity")
                .send()
                .await
                .map_err(transport)?,
        )
        .await
    }
    async fn local_metadata(&self) -> Result<()> {
        let status = self.request("/api/status", None).await?;
        if status["cloud"]["disabled"] != true {
            return Err(Failure("local_model_unverified"));
        }
        let show = self
            .request("/api/show", Some(json!({"model":self.model})))
            .await?;
        if remote(&show)
            || !show["model_info"]
                .as_object()
                .is_some_and(|v| !v.is_empty())
        {
            return Err(Failure("local_model_unverified"));
        }
        Ok(())
    }
    pub(crate) async fn write_answer(
        &self,
        connection: &mut PgConnection,
        question: &str,
        context: &Value,
        instructions: &Value,
        deadline: Option<tokio::time::Instant>,
    ) -> WritingAttempt {
        self.write_mode(connection, question, context, instructions, deadline, false)
            .await
    }
    pub(crate) async fn write_rearranged(
        &self,
        connection: &mut PgConnection,
        question: &str,
        context: &Value,
        instructions: &Value,
        deadline: Option<tokio::time::Instant>,
    ) -> WritingAttempt {
        self.write_mode(connection, question, context, instructions, deadline, true)
            .await
    }
    async fn write_mode(
        &self,
        connection: &mut PgConnection,
        question: &str,
        context: &Value,
        instructions: &Value,
        deadline: Option<tokio::time::Instant>,
        rearrange: bool,
    ) -> WritingAttempt {
        let mut attempt = WritingAttempt {
            attempted: false,
            content: None,
            error: None,
            input: None,
            output: None,
            retry_after: None,
        };
        let mut reserved = None;
        let operation = async {
            let plan = if rearrange {
                Some(crate::rearranger::Plan::new(
                    question,
                    context,
                    instructions,
                )?)
            } else {
                None
            };
            let body = if let Some(plan) = &plan {
                plan.body(&self.model, self.output, self.input as usize)?
            } else {
                self.body(question, context, instructions)?
            };
            let _permit = self
                .gate
                .clone()
                .try_acquire_owned()
                .map_err(|_| Failure("provider_busy"))?;
            let key = monthly::reserve_ollama(connection, self.requests).await?;
            reserved = Some(key);
            attempt.attempted = true;
            let timeout = deadline
                .map(crate::local_fallback::remaining)
                .transpose()?
                .unwrap_or(self.timeout)
                .min(self.timeout);
            tokio::time::timeout(timeout, async {
                // Only public daemon/model metadata is sent before locality is established.
                self.local_metadata().await?;
                let response = self
                    .client
                    .post(format!(
                        "{}/api/{}",
                        self.endpoint,
                        if rearrange { "chat" } else { "generate" }
                    ))
                    .header("Content-Type", "application/json")
                    .header("Accept-Encoding", "identity")
                    .body(body)
                    .send()
                    .await
                    .map_err(transport)?;
                let value = if rearrange {
                    read_chat(response).await?
                } else {
                    read(response).await?
                };
                attempt.input = usage_counter(Some(&value), "prompt_eval_count")?;
                attempt.output = usage_counter(Some(&value), "eval_count")?;
                if attempt.input.is_some_and(|n| n > self.input)
                    || attempt.output.is_some_and(|n| n > self.output)
                {
                    return Err(Failure("provider_output_size"));
                }
                if let Some(plan) = &plan {
                    parse_chat(&value, &self.model, plan)
                } else {
                    parse(&value, &self.model)
                }
            })
            .await
            .unwrap_or(Err(Failure("timeout")))
        };
        // Do not cancel a ledger COMMIT at a network deadline: an uncertain commit
        // must never be treated as an unused request. Only transport is timed here.
        let result = operation.await;
        match result {
            Ok(content) => attempt.content = Some(content),
            Err(error) => {
                if error.0 == "rate_limited" {
                    attempt.retry_after = Some(60);
                    if let Some(key) = reserved
                        && let Err(failure) = monthly::cooldown_ollama(connection, &key).await
                    {
                        attempt.error = Some(failure);
                        return attempt;
                    }
                } else if error.0 == "provider_busy" {
                    attempt.retry_after = Some(1);
                }
                attempt.error = Some(error);
            }
        }
        attempt
    }
}
fn transport(error: reqwest::Error) -> Failure {
    Failure(if error.is_timeout() {
        "timeout"
    } else {
        "connection_error"
    })
}
fn remote(v: &Value) -> bool {
    ["remote_host", "remote_model"]
        .iter()
        .any(|k| v.get(k).is_some_and(|v| !v.is_null() && v != ""))
}
fn checked(response: reqwest::Response) -> Result<reqwest::Response> {
    match response.status().as_u16() {
        200 => {}
        300..=399 => return Err(Failure("provider_redirect_denied")),
        404 => return Err(Failure("model_unavailable")),
        429 => return Err(Failure("rate_limited")),
        _ => return Err(Failure("provider_error")),
    }
    if response
        .headers()
        .get("content-encoding")
        .is_some_and(|v| v != "identity")
    {
        return Err(Failure("provider_encoding_denied"));
    }
    Ok(response)
}
async fn read(response: reqwest::Response) -> Result<Value> {
    bounded_json(checked(response)?, "connection_error").await
}
async fn read_chat(response: reqwest::Response) -> Result<Value> {
    let mut response = checked(response)?;
    if response.content_length().is_some_and(|n| n > 65536) {
        return Err(Failure("provider_output_size"));
    }
    let mut raw = vec![];
    while let Some(chunk) = response.chunk().await.map_err(transport)? {
        if raw.len() + chunk.len() > 65536 {
            return Err(Failure("provider_output_size"));
        }
        raw.extend_from_slice(&chunk);
    }
    serde_json::from_slice(&raw).map_err(|_| Failure("invalid_provider_response"))
}
fn parse_chat(value: &Value, model: &str, plan: &crate::rearranger::Plan) -> Result<ModelAnswer> {
    if remote(value) {
        return Err(Failure("local_model_unverified"));
    }
    let message = &value["message"];
    for calls in [&value["tool_calls"], &message["tool_calls"]] {
        if !calls.is_null() && calls != &json!([]) {
            return Err(Failure("provider_tool_use_denied"));
        }
    }
    if value["done"] != true
        || value["model"] != model
        || value["done_reason"] != "stop"
        || message["role"] != "assistant"
    {
        return Err(Failure("invalid_provider_response"));
    }
    let content: Value = serde_json::from_str(
        message["content"]
            .as_str()
            .ok_or(Failure("invalid_structured_response"))?,
    )
    .map_err(|_| Failure("invalid_structured_response"))?;
    plan.accept(&content)
}
fn parse(value: &Value, model: &str) -> Result<ModelAnswer> {
    if remote(value) {
        return Err(Failure("local_model_unverified"));
    }
    if value["done"] != true
        || value["done_reason"] != "stop"
        || value["model"] != model
        || value
            .get("tool_calls")
            .is_some_and(|v| v != &json!([]) && !v.is_null())
    {
        return Err(Failure("invalid_structured_response"));
    }
    let text = value["response"]
        .as_str()
        .ok_or(Failure("invalid_structured_response"))?;
    ModelAnswer::parse(
        serde_json::from_str(text).map_err(|_| Failure("invalid_structured_response"))?,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rearranger_requires_its_explicit_permission_and_selected_local_provider() {
        let mut values = BTreeMap::from([
            ("LLM_PROVIDER".into(), "ollama".into()),
            ("OLLAMA_MODEL".into(), "fixture:local".into()),
        ]);
        assert!(OllamaModel::for_rearrangement(&values, false).is_err());
        values.insert("OLLAMA_GENERATION_AUTHORIZED".into(), "true".into());
        assert!(OllamaModel::for_rearrangement(&values, false).is_ok());
        values.insert("LLM_PROVIDER".into(), "cohere".into());
        assert!(OllamaModel::for_rearrangement(&values, false).is_err());
    }
    #[test]
    fn chat_envelope_requires_original_local_model_assistant_complete_stop_and_no_tools() {
        let context = json!({"evidence":[{"reference":{"source_type":"verified_project","source_id":"fictional:project:0"},"facts":{"contribution":"I built Rust workers."}}]});
        let plan = crate::rearranger::Plan::new(
            "Describe my project",
            &context,
            &json!({"max_characters":1000,"max_words":100,"style_instruction":"concise"}),
        )
        .unwrap();
        let base = json!({"model":"fixture:local","done":true,"done_reason":"stop","message":{"role":"assistant","content":json!({"answer":"I built Rust workers."}).to_string()}});
        assert!(parse_chat(&base, "fixture:local", &plan).is_ok());
        for (key, value) in [
            ("model", json!("another")),
            ("done", json!(false)),
            ("done_reason", json!("length")),
            ("tool_calls", json!([{}])),
            ("remote_host", json!("https://forbidden.invalid")),
        ] {
            let mut changed = base.clone();
            changed[key] = value;
            assert!(parse_chat(&changed, "fixture:local", &plan).is_err());
        }
        let mut changed = base;
        changed["message"]["role"] = json!("user");
        assert!(parse_chat(&changed, "fixture:local", &plan).is_err());
    }
    #[test]
    fn explicit_local_model_names_cannot_route_to_cloud_or_urls() {
        for name in ["qwen3:0.6b", "fixture-model", "local_model.v1"] {
            assert!(identifier(name).is_ok());
        }
        for name in [
            "",
            "Cloud:latest",
            "x-cloud",
            "https://example.com",
            "x/y",
            "x?token=1",
            "x\n",
        ] {
            assert!(identifier(name).is_err());
        }
    }
    #[test]
    fn complete_local_response_and_grounded_contract_are_required() {
        let source = json!({"source_type":"verified_project","source_id":"fictional:project:0"});
        let content = json!({"answer":"I built Rust workers.","claims":[{"text":"I built Rust workers.","quote":"I built Rust workers.","source":source}],"evidence_references":[source]});
        let base = json!({"model":"fixture","done":true,"done_reason":"stop","response":content.to_string()});
        assert!(parse(&base, "fixture").is_ok());
        for (key, value) in [
            ("model", json!("other")),
            ("done", json!(false)),
            ("done_reason", json!("length")),
            ("remote_host", json!("https://elsewhere.invalid")),
            ("remote_model", json!("cloud")),
            ("tool_calls", json!([{"name":"apply"}])),
            ("response", json!("{}")),
        ] {
            let mut changed = base.clone();
            changed[key] = value;
            assert!(parse(&changed, "fixture").is_err());
        }
    }
}
