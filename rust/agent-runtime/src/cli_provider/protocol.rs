//! Every CLI frame is untrusted; successful text is still subject to grounding later.
use crate::{Failure, Result, grounding::ModelAnswer, provider::usage_counter};
use serde_json::Value;

pub(super) fn truthy(value: Option<&Value>) -> bool {
    value.is_some_and(|v| match v {
        Value::Null => false,
        Value::Bool(v) => *v,
        Value::String(v) => !v.is_empty(),
        Value::Array(v) => !v.is_empty(),
        Value::Object(v) => !v.is_empty(),
        Value::Number(v) => v.as_f64() != Some(0.0),
    })
}
#[derive(Default)]
pub(super) struct Stream {
    pub(super) initialized: bool,
    result: Option<Value>,
}
pub(super) struct Answer {
    pub(super) content: ModelAnswer,
    pub(super) input: Option<u32>,
    pub(super) output: Option<u32>,
}
impl Stream {
    /// Returns true only for the sole verified no-tools initialization frame.
    pub(super) fn frame(&mut self, raw: &[u8], prompt_sent: bool) -> Result<bool> {
        let value: Value =
            serde_json::from_slice(raw).map_err(|_| Failure("invalid_provider_stream"))?;
        let fields = value
            .as_object()
            .ok_or(Failure("invalid_provider_stream"))?;
        if self.result.is_some() {
            return Err(Failure("invalid_provider_stream"));
        }
        match fields.get("event").and_then(Value::as_str) {
            Some("init") => {
                if self.initialized {
                    return Err(Failure("invalid_provider_stream"));
                }
                let init = value["init"]
                    .as_object()
                    .ok_or(Failure("provider_init_unverified"))?;
                if init
                    .get("tools")
                    .and_then(Value::as_array)
                    .is_none_or(|a| !a.is_empty())
                {
                    return Err(Failure("provider_tool_use_denied"));
                }
                self.initialized = true;
                Ok(true)
            }
            Some("step_update") => {
                if !self.initialized {
                    return Err(Failure("provider_init_unverified"));
                }
                let step = value["step_update"]
                    .as_object()
                    .ok_or(Failure("invalid_provider_stream"))?;
                if matches!(
                    step.get("step_type").and_then(Value::as_str),
                    Some("tool_call" | "tool" | "run_command")
                ) || ["subagent_info", "tool_info", "tool_name"]
                    .iter()
                    .any(|k| truthy(step.get(*k)))
                {
                    return Err(Failure("provider_tool_use_denied"));
                }
                Ok(false)
            }
            Some("result") => {
                let result = value["result"]
                    .as_object()
                    .ok_or(Failure("invalid_provider_stream"))?;
                if !self.initialized || !prompt_sent {
                    let error = result
                        .get("error")
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .to_ascii_lowercase();
                    return Err(Failure(
                        if error.contains("authentication required")
                            || error.contains("login required")
                        {
                            "provider_authentication"
                        } else {
                            "provider_init_unverified"
                        },
                    ));
                }
                self.result = Some(value["result"].clone());
                Ok(false)
            }
            _ => Err(Failure("invalid_provider_stream")),
        }
    }
    pub(super) fn finish(self) -> Result<Answer> {
        if !self.initialized {
            return Err(Failure("provider_init_unverified"));
        }
        let value = self.result.ok_or(Failure("invalid_structured_response"))?;
        if value.get("status").is_some_and(|v| v != "SUCCESS")
            || value
                .get("num_turns")
                .is_some_and(|v| v.as_u64() != Some(1))
            || ["is_error", "tool_calls", "permission_denials"]
                .iter()
                .any(|k| truthy(value.get(*k)))
        {
            return Err(Failure("provider_permission_or_execution_error"));
        }
        let selected = value
            .get("structured_output")
            .or_else(|| value.get("response"))
            .or_else(|| value.get("result"))
            .unwrap_or(&value);
        let selected = if let Some(s) = selected.as_str() {
            serde_json::from_str(s).map_err(|_| Failure("invalid_structured_response"))?
        } else {
            selected.clone()
        };
        let usage = value.get("usage").filter(|v| !v.is_null());
        if usage.is_some_and(|v| !v.is_object()) {
            return Err(Failure("invalid_structured_response"));
        }
        for key in ["thinking_tokens", "cache_read_tokens", "total_tokens"] {
            usage_counter(usage, key)?;
        }
        Ok(Answer {
            content: ModelAnswer::parse(selected)
                .map_err(|_| Failure("invalid_structured_response"))?,
            input: usage_counter(usage, "input_tokens")?,
            output: usage_counter(usage, "output_tokens")?,
        })
    }
}
pub(super) fn exit_error(raw: &[u8]) -> Failure {
    let text = String::from_utf8_lossy(raw).to_ascii_lowercase();
    Failure(if text.contains("invalid --json-schema") {
        "cli_schema_rejected"
    } else if text.contains("authentication required") || text.contains("login required") {
        "provider_authentication"
    } else if text.contains("quota") || text.contains("429") {
        "rate_limited"
    } else if text.contains("unknown flag") || text.contains("flag provided but not defined") {
        "unsupported_cli_argument"
    } else {
        "cli_nonzero_exit"
    })
}
