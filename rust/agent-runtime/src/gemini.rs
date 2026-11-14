//! Opt-in Gemini GenerateContent, without SDK retries, URL retrieval or tool dispatch.
use crate::{
    Failure, Result,
    configuration::boolean,
    grounding::ModelAnswer,
    monthly,
    provider::{WritingAttempt, answer_schema, bounded_json, usage_counter, writing_payload},
};
use regex::Regex;
use serde_json::{Value, json};
use sqlx::PgConnection;
use std::{
    collections::BTreeMap,
    sync::{Arc, LazyLock},
    time::{Duration, SystemTime},
};

pub(crate) struct GeminiModel {
    client: reqwest::Client,
    key: String,
    endpoint: String,
    requests: u32,
    approved: u32,
    input: u32,
    output: u32,
    pub(crate) gate: Arc<tokio::sync::Semaphore>,
}
fn number(
    values: &BTreeMap<String, String>,
    name: &str,
    default: u32,
    maximum: u32,
) -> Result<u32> {
    values
        .get(name)
        .map(|s| {
            s.parse::<u32>()
                .ok()
                .filter(|n| *n <= maximum)
                .ok_or(Failure("invalid_provider_configuration"))
        })
        .unwrap_or(Ok(default))
}
fn model_identifier(value: &str) -> Result<&str> {
    static MODEL: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"^(?:models/)?gemini-[A-Za-z0-9][A-Za-z0-9._-]{0,119}$").unwrap()
    });
    if !MODEL.is_match(value) {
        return Err(Failure("model_unavailable"));
    }
    Ok(value.strip_prefix("models/").unwrap_or(value))
}
impl GeminiModel {
    pub(crate) fn from_values(values: &BTreeMap<String, String>, fixture: bool) -> Result<Self> {
        let key = values
            .get("GEMINI_API_KEY")
            .filter(|s| {
                !s.trim().is_empty()
                    && s.len() <= 1024
                    && !s.chars().any(|c| c.is_control() || c.is_whitespace())
            })
            .ok_or(Failure("llm_not_configured"))?
            .clone();
        let model = model_identifier(
            values
                .get("LLM_MODEL")
                .ok_or(Failure("llm_not_configured"))?,
        )?;
        let approved = number(values, "GEMINI_APPROVED_MONTHLY_REQUESTS", 0, 10000)?;
        if !boolean(values, "GEMINI_ENABLED", false)? || approved == 0 {
            return Err(Failure("provider_permission_required"));
        }
        if !boolean(values, "GEMINI_CANDIDATE_DATA_AUTHORIZED", false)? {
            return Err(Failure("candidate_cloud_authorization_required"));
        }
        let requests = number(values, "LLM_MONTHLY_MAX_REQUESTS", 200, 10000)?;
        let input = number(values, "LLM_MAX_INPUT_CHARS", 16000, 64000)?;
        let output = number(values, "LLM_MAX_OUTPUT_TOKENS", 1000, 8192)?;
        if input < 1000 || output < 64 {
            return Err(Failure("invalid_provider_configuration"));
        }
        let timeout = values
            .get("LLM_TIMEOUT_SECONDS")
            .map(|s| s.parse::<f64>().unwrap_or(f64::NAN))
            .unwrap_or(30.0);
        if !timeout.is_finite() || !(1.0..=120.0).contains(&timeout) {
            return Err(Failure("invalid_provider_configuration"));
        }
        let path = format!("/v1beta/models/{model}:generateContent");
        let endpoint = match values.get("RUST_GEMINI_FIXTURE_ENDPOINT") {
            Some(endpoint) if fixture => {
                let url = reqwest::Url::parse(endpoint)
                    .map_err(|_| Failure("provider_fixture_endpoint_denied"))?;
                if url.scheme() != "http"
                    || url.host_str() != Some("127.0.0.1")
                    || url.port().is_none_or(|p| p < 1025)
                    || !url.username().is_empty()
                    || url.password().is_some()
                    || url.path() != path
                    || url.query().is_some()
                    || url.fragment().is_some()
                {
                    return Err(Failure("provider_fixture_endpoint_denied"));
                }
                endpoint.clone()
            }
            None if !fixture => format!("https://generativelanguage.googleapis.com{path}"),
            _ => return Err(Failure("provider_fixture_endpoint_denied")),
        };
        let client = reqwest::Client::builder()
            .no_proxy()
            .retry(reqwest::retry::never())
            .redirect(reqwest::redirect::Policy::none())
            .connect_timeout(Duration::from_secs(5))
            .timeout(Duration::from_secs_f64(timeout.min(30.0)))
            .build()
            .map_err(|_| Failure("provider_transport_configuration"))?;
        Ok(Self {
            client,
            key,
            endpoint,
            requests,
            approved,
            input,
            output,
            gate: Arc::new(tokio::sync::Semaphore::new(1)),
        })
    }
    fn body(&self, question: &str, context: &Value, instructions: &Value) -> Result<Vec<u8>> {
        let payload = serde_json::to_string(&writing_payload(question, context, instructions))
            .map_err(|_| Failure("invalid_answer_request"))?;
        let body = json!({"systemInstruction":{"parts":[{"text":include_str!("../schemas/answer-system.txt")}]},"contents":[{"role":"user","parts":[{"text":payload}]}],"generationConfig":{"temperature":0.2,"maxOutputTokens":self.output,"candidateCount":1,"responseMimeType":"application/json","responseJsonSchema":answer_schema()}});
        let bytes = serde_json::to_vec(&body).map_err(|_| Failure("invalid_answer_request"))?;
        if bytes.len() > self.input as usize {
            return Err(Failure("input_limit_exceeded"));
        }
        Ok(bytes)
    }
    pub(crate) async fn write_answer(
        &self,
        connection: &mut PgConnection,
        question: &str,
        context: &Value,
        instructions: &Value,
    ) -> WritingAttempt {
        let mut attempt = WritingAttempt {
            attempted: false,
            content: None,
            error: None,
            input: None,
            output: None,
            retry_after: None,
        };
        let result = async {
            let body = self.body(question, context, instructions)?;
            let _permit = self
                .gate
                .clone()
                .try_acquire_owned()
                .map_err(|_| Failure("provider_busy"))?;
            let month = monthly::reserve_gemini(connection, self.requests, self.approved).await?;
            attempt.attempted = true;
            let response = self
                .client
                .post(&self.endpoint)
                .header("x-goog-api-key", &self.key)
                .header("Content-Type", "application/json")
                .body(body)
                .send()
                .await
                .map_err(|e| {
                    Failure(if e.is_timeout() {
                        "timeout"
                    } else {
                        "connection_error"
                    })
                })?;
            let status = response.status().as_u16();
            if status != 200 {
                let delay = response
                    .headers()
                    .get("retry-after")
                    .and_then(|s| s.to_str().ok())
                    .and_then(|s| retry_after(s, SystemTime::now()));
                if status == 429
                    || (matches!(status, 500 | 502 | 503 | 504) && delay.is_some_and(|n| n > 2))
                {
                    let seconds = delay.unwrap_or(60);
                    monthly::cooldown(connection, &month, seconds).await?;
                    attempt.retry_after = Some(seconds);
                }
                return Err(Failure(match status {
                    400 => "invalid_provider_request",
                    401 | 403 => "provider_authentication",
                    404 => "model_unavailable",
                    429 => "rate_limited",
                    _ => "provider_error",
                }));
            }
            let value = bounded_json(response, "connection_error").await?;
            let usage = value.get("usageMetadata");
            attempt.input = usage_counter(usage, "promptTokenCount")?;
            let candidate = usage_counter(usage, "candidatesTokenCount")?;
            let thinking = usage_counter(usage, "thoughtsTokenCount")?;
            attempt.output = match (candidate, thinking) {
                (None, None) => None,
                (a, b) => Some(
                    a.unwrap_or(0)
                        .checked_add(b.unwrap_or(0))
                        .ok_or(Failure("invalid_structured_response"))?,
                ),
            };
            monthly::tokens(connection, &month, attempt.input, attempt.output).await?;
            if attempt.input.is_some_and(|n| n > self.input)
                || attempt.output.is_some_and(|n| n > self.output)
            {
                return Err(Failure("provider_usage_exceeds_reservation"));
            }
            parse(&value)
        }
        .await;
        match result {
            Ok(content) => attempt.content = Some(content),
            Err(error) => {
                if error.0 == "provider_busy" {
                    attempt.retry_after = Some(1);
                } else if error.0 == "rate_limited" && attempt.retry_after.is_none() {
                    attempt.retry_after =
                        monthly::gemini_retry_after(connection).await.ok().flatten();
                }
                attempt.error = Some(error);
            }
        }
        attempt
    }
}
fn retry_after(value: &str, now: SystemTime) -> Option<u32> {
    let value = value.trim();
    if let Ok(number) = value.parse::<f64>() {
        return number
            .is_finite()
            .then(|| number.clamp(0.0, 31536000.0).ceil() as u32);
    }
    chrono::DateTime::parse_from_rfc2822(value)
        .ok()
        .map(|deadline| {
            let now = chrono::DateTime::<chrono::Utc>::from(now);
            let millis = deadline.signed_duration_since(now).num_milliseconds();
            (millis.max(0) as u64).div_ceil(1000).min(31536000) as u32
        })
}
fn parse(value: &Value) -> Result<ModelAnswer> {
    let invalid = || Failure("invalid_structured_response");
    if value["promptFeedback"]
        .get("blockReason")
        .is_some_and(|v| !v.is_null() && v != "BLOCK_REASON_UNSPECIFIED")
    {
        return Err(invalid());
    }
    let candidates = value["candidates"]
        .as_array()
        .filter(|s| s.len() == 1)
        .ok_or_else(invalid)?;
    let candidate = &candidates[0];
    if candidate["finishReason"] != "STOP"
        || candidate["content"]["role"] != "model"
        || candidate["safetyRatings"]
            .as_array()
            .is_some_and(|r| r.iter().any(|v| v["blocked"] == true))
    {
        return Err(invalid());
    }
    let parts = candidate["content"]["parts"]
        .as_array()
        .filter(|p| !p.is_empty() && p.len() <= 16)
        .ok_or_else(invalid)?;
    let mut text = String::new();
    for part in parts {
        let part = part.as_object().ok_or_else(invalid)?;
        if part
            .keys()
            .any(|k| !matches!(k.as_str(), "text" | "thought" | "thoughtSignature"))
        {
            return Err(invalid());
        }
        if part.get("thought").is_some_and(|v| v != false) {
            return Err(invalid());
        }
        text.push_str(
            part.get("text")
                .and_then(Value::as_str)
                .ok_or_else(invalid)?,
        );
    }
    ModelAnswer::parse(serde_json::from_str(&text).map_err(|_| invalid())?).map_err(|_| invalid())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn model_names_cannot_change_destination_or_path() {
        for name in [
            "gemini-fixture",
            "models/gemini-fixture",
            "gemini-2.5-flash",
        ] {
            assert!(model_identifier(name).is_ok());
        }
        for name in [
            "https://attacker.invalid",
            "gemini-../other",
            "gemini-x?key=secret",
            "gemini-x\n",
            "models/models/gemini-x",
            "",
        ] {
            assert!(model_identifier(name).is_err());
        }
    }
    #[test]
    fn retry_after_honors_seconds_dates_and_bounded_invalid_input() {
        let now = SystemTime::UNIX_EPOCH + Duration::from_secs(1445412479);
        for (raw, expected) in [
            ("0", Some(0)),
            ("1.2", Some(2)),
            ("-1", Some(0)),
            ("inf", None),
            ("NaN", None),
            ("garbage", None),
            ("Wed, 21 Oct 2015 07:28:00 GMT", Some(1)),
            ("9999999999999999", Some(31536000)),
        ] {
            assert_eq!(retry_after(raw, now), expected, "{raw}");
        }
    }
    fn response() -> Value {
        let source = json!({"source_type":"verified_project","source_id":"fictional:project:0"});
        let content = json!({"answer":"I built Rust workers.","claims":[{"text":"I built Rust workers.","quote":"I built Rust workers.","source":source}],"evidence_references":[source]});
        json!({"candidates":[{"finishReason":"STOP","content":{"role":"model","parts":[{"text":content.to_string()}]}}]})
    }
    #[test]
    fn only_one_complete_model_text_result_is_accepted() {
        assert!(parse(&response()).is_ok());
        for reason in ["MAX_TOKENS", "SAFETY", "RECITATION", "CONTINUATION", ""] {
            let mut v = response();
            v["candidates"][0]["finishReason"] = json!(reason);
            assert!(parse(&v).is_err());
        }
        for parts in [
            json!([]),
            json!([{"functionCall":{"name":"apply"}}]),
            json!([{"text":"{}","thought":true}]),
            json!([{"text":"{}","inlineData":{}}]),
        ] {
            let mut v = response();
            v["candidates"][0]["content"]["parts"] = parts;
            assert!(parse(&v).is_err());
        }
        let mut v = response();
        v["promptFeedback"] = json!({"blockReason":"SAFETY"});
        assert!(parse(&v).is_err());
        let mut v = response();
        v["candidates"][0]["safetyRatings"] = json!([{"blocked":true}]);
        assert!(parse(&v).is_err());
        let mut v = response();
        v["candidates"] = json!([v["candidates"][0], v["candidates"][0]]);
        assert!(parse(&v).is_err());
    }
}
