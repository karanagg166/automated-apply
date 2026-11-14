//! The existing bounded answer request; no request-supplied trust or provider overrides.
use crate::{Failure, Result, profile_contract, resource_contract};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use uuid::Uuid;
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Generate {
    pub question: String,
    pub writing_style: String,
    pub job_id: Option<Uuid>,
    pub company_name: Option<String>,
    pub job_description: Option<String>,
    pub max_characters: usize,
    pub max_words: Option<usize>,
    pub save_draft: bool,
    pub rewrite: bool,
}
fn invalid() -> Failure {
    Failure("invalid_answer_request")
}
fn string(value: &Value, max: usize) -> Result<Value> {
    let text = value.as_str().ok_or_else(invalid)?.trim();
    if text.is_empty() || text.chars().count() > max {
        return Err(invalid());
    }
    Ok(json!(text))
}
pub fn normalize(input: Value) -> Result<Generate> {
    let body = input.as_object().ok_or_else(invalid)?;
    if body.keys().any(|key| {
        ![
            "question",
            "writing_style",
            "job_id",
            "company_name",
            "job_description",
            "max_characters",
            "max_words",
            "save_draft",
            "rewrite",
        ]
        .contains(&key.as_str())
    }) {
        return Err(invalid());
    }
    let mut value = json!({"question":string(body.get("question").ok_or_else(invalid)?,2000)?,"writing_style":"professional","job_id":null,"company_name":null,"job_description":null,"max_characters":1500,"max_words":null,"save_draft":false,"rewrite":false});
    for (key, raw) in body {
        value[key] = match key.as_str() {
            "question" => value[key].clone(),
            "writing_style" => {
                let style = raw.as_str().ok_or_else(invalid)?;
                if ![
                    "professional",
                    "conversational",
                    "technical",
                    "concise",
                    "founder_focused",
                ]
                .contains(&style)
                {
                    return Err(invalid());
                }
                json!(style)
            }
            "job_id" if raw.is_null() => Value::Null,
            "job_id" => json!(
                raw.as_str()
                    .and_then(|s| s.parse::<Uuid>().ok())
                    .ok_or_else(invalid)?
            ),
            "company_name" | "job_description" if raw.is_null() => Value::Null,
            "company_name" => string(raw, 200)?,
            "job_description" => string(raw, 10000)?,
            "max_words" if raw.is_null() => Value::Null,
            "max_words" => json!(
                profile_contract::pagination_integer(raw.clone(), 1, 1500).map_err(|_| invalid())?
            ),
            "max_characters" => json!(
                profile_contract::pagination_integer(raw.clone(), 20, 10000)
                    .map_err(|_| invalid())?
            ),
            "save_draft" | "rewrite" => resource_contract::boolean(raw).map_err(|_| invalid())?,
            _ => return Err(invalid()),
        };
    }
    serde_json::from_value(value).map_err(|_| invalid())
}
