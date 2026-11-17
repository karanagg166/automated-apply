use crate::{Failure, Result, legacy_regex::Regex};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::sync::LazyLock;
use uuid::Uuid;
mod parser;
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Intent {
    pub category: String,
    pub company: Option<String>,
    pub role: Option<String>,
    pub location: Option<String>,
    pub skills: Vec<String>,
    pub remote: bool,
    pub startup: bool,
    pub days: Option<u16>,
    pub not_applied: bool,
    pub url: Option<String>,
    pub selection: Option<u8>,
    pub job_id: Option<Uuid>,
    pub connection: Option<String>,
    pub subject: Option<String>,
    pub project_rank: Option<u8>,
    pub follow_up: Option<String>,
    pub max_words: u16,
    pub max_characters: u16,
}
struct Contract {
    schema: Value,
    validator: jsonschema::Validator,
}
fn contract() -> &'static Contract {
    static VALUE: LazyLock<Contract> = LazyLock::new(|| {
        let schema: Value =
            serde_json::from_str(include_str!("../../schemas/conversation-intent.json"))
                .expect("frozen intent schema");
        let validator = jsonschema::draft202012::options()
            .build(&schema)
            .expect("intent validator");
        Contract { schema, validator }
    });
    &VALUE
}
fn invalid() -> Failure {
    Failure("invalid_conversation_intent")
}
pub fn normalize(mut value: Value) -> Result<Intent> {
    if value.to_string().len() > 4096 {
        return Err(invalid());
    }
    let contract = contract();
    let fields = value.as_object_mut().ok_or_else(invalid)?;
    for (key, property) in contract.schema["properties"]
        .as_object()
        .expect("intent properties")
    {
        if let Some(default) = property.get("default") {
            fields.entry(key.clone()).or_insert(default.clone());
        }
    }
    fields.entry("skills").or_insert(json!([]));
    for key in ["remote", "startup", "not_applied"] {
        if let Some(value) = fields.get_mut(key) {
            *value = crate::resource_contract::boolean(value).map_err(|_| invalid())?;
        }
    }
    for (key, min, max) in [
        ("days", 1, 365),
        ("selection", 1, 10),
        ("project_rank", 1, 30),
        ("max_words", 1, 500),
        ("max_characters", 1, 3500),
    ] {
        if let Some(value) = fields.get_mut(key).filter(|v| !v.is_null()) {
            *value = json!(
                crate::profile_contract::pagination_integer(value.clone(), min, max)
                    .map_err(|_| invalid())?
            );
        }
    }
    if let Some(value) = fields.get_mut("url").filter(|v| !v.is_null()) {
        *value = json!(
            value
                .as_str()
                .and_then(crate::resources::public_https)
                .ok_or_else(invalid)?
        );
    }
    if !contract.validator.is_valid(&value) {
        return Err(invalid());
    }
    let intent: Intent = serde_json::from_value(value).map_err(|_| invalid())?;
    static LABEL: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\A[\w .+#&/-]{1,100}\z", false));
    for label in intent
        .company
        .iter()
        .chain(intent.role.iter())
        .chain(intent.location.iter())
        .chain(intent.skills.iter())
    {
        if !LABEL.is_match(label)? {
            return Err(invalid());
        }
    }
    if (intent.selection.is_some() || intent.job_id.is_some()) && intent.category != "SHOW_JOB"
        || intent.url.is_some() && intent.category != "PREPARE_APPLICATION"
        || intent.category == "PREPARE_APPLICATION"
            && intent.url.is_none()
            && intent.company.is_none()
    {
        return Err(invalid());
    }
    Ok(intent)
}
impl Intent {
    pub fn routing_category(&self) -> &str {
        match self.category.as_str() {
            "HELP" => "GENERAL_CHAT",
            "UNKNOWN" => "UNSUPPORTED_ACTION",
            "FIND_JOBS" => "JOB_DISCOVERY",
            "FILTER_JOBS" => "JOB_FILTERING",
            "SHOW_JOB" | "RESET_CONTEXT" => "FOLLOW_UP",
            "PREPARE_APPLICATION" | "ANSWER_PREPARATION" | "GMAIL_DRAFT_PREVIEW" => {
                "APPLICATION_PREPARATION"
            }
            "FOUNDER_RESEARCH_PREVIEW" => "FOUNDER_RESEARCH",
            _ => &self.category,
        }
    }
}
pub fn deterministic(text: &str) -> Intent {
    parser::parse(text)
        .unwrap_or_else(|_| normalize(json!({"category":"UNKNOWN"})).expect("unknown intent"))
}
pub fn unsafe_request(text: &str) -> Result<bool> {
    parser::unsafe_request(text)
}
