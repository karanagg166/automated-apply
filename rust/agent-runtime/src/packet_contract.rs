//! Owner preparation inputs. Neither an input field nor an idempotency key grants approval.
use crate::{Failure, Result, profile_contract, resource_contract};
use automated_apply_domain::text::folded;
use serde::Serialize;
use serde_json::{Map, Value};
use std::collections::HashSet;
use std::sync::LazyLock;
use uuid::Uuid;

pub const CATEGORIES: &[&str] = &[
    "personal_information",
    "contact_information",
    "professional_profile_url",
    "education",
    "experience",
    "technical_skills",
    "resume_upload",
    "salary",
    "notice_period",
    "work_authorization",
    "project_explanation",
    "motivation",
    "free_text",
    "multiple_choice",
    "yes_no",
    "unknown",
];
pub const FIELD_TYPES: &[&str] = &[
    "text",
    "textarea",
    "url",
    "file",
    "multiple_choice",
    "yes_no",
    "multi_select",
];
#[derive(Clone, Serialize)]
pub struct Question {
    pub question: String,
    pub category: String,
    pub field_type: String,
    pub required: bool,
    pub max_characters: usize,
    pub max_words: Option<usize>,
    pub constraints: Option<String>,
    pub options: Vec<String>,
    pub writing_style: String,
}
#[derive(Clone, Serialize)]
pub struct Prepare {
    pub resume_resource_id: Option<Uuid>,
    pub questions: Vec<Question>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub idempotency_key: Option<String>,
}
fn invalid() -> Failure {
    Failure("invalid_packet_preparation")
}
fn object(input: &Value, allowed: &[&str]) -> Result<Map<String, Value>> {
    let value = input.as_object().ok_or_else(invalid)?;
    if value.keys().any(|k| !allowed.contains(&k.as_str())) {
        return Err(invalid());
    }
    Ok(value.clone())
}
fn string(value: &Value, min: usize, max: usize) -> Result<String> {
    let s = value.as_str().ok_or_else(invalid)?.trim();
    if !(min..=max).contains(&s.chars().count()) {
        return Err(invalid());
    }
    Ok(s.into())
}
fn choice(body: &Map<String, Value>, key: &str, default: &str, allowed: &[&str]) -> Result<String> {
    let s = body
        .get(key)
        .map(|v| v.as_str().ok_or_else(invalid))
        .transpose()?
        .unwrap_or(default);
    if !allowed.contains(&s) {
        return Err(invalid());
    }
    Ok(s.into())
}
pub fn question(input: Value) -> Result<Question> {
    let body = object(
        &input,
        &[
            "question",
            "category",
            "field_type",
            "required",
            "max_characters",
            "max_words",
            "constraints",
            "options",
            "writing_style",
        ],
    )?;
    let text = string(body.get("question").ok_or_else(invalid)?, 1, 2000)?;
    let category = choice(&body, "category", "unknown", CATEGORIES)?;
    let field_type = choice(&body, "field_type", "text", FIELD_TYPES)?;
    let style = choice(
        &body,
        "writing_style",
        "professional",
        &[
            "professional",
            "conversational",
            "technical",
            "concise",
            "founder_focused",
        ],
    )?;
    let required = body
        .get("required")
        .map(resource_contract::boolean)
        .transpose()
        .map_err(|_| invalid())?
        .and_then(|v| v.as_bool())
        .unwrap_or(true);
    let count = |key: &str, max: i64| -> Result<Option<usize>> {
        body.get(key)
            .filter(|v| !v.is_null())
            .map(|v| {
                profile_contract::pagination_integer(v.clone(), 1, max)
                    .map(|n| n as usize)
                    .map_err(|_| invalid())
            })
            .transpose()
    };
    if body.get("max_characters").is_some_and(Value::is_null) {
        return Err(invalid());
    }
    let max_characters = count("max_characters", 10000)?.unwrap_or(1500);
    let max_words = count("max_words", 1500)?;
    let constraints = body
        .get("constraints")
        .filter(|v| !v.is_null())
        .map(|v| string(v, 1, 1000))
        .transpose()?;
    let options = match body.get("options") {
        None => vec![],
        Some(Value::Array(options)) if options.len() <= 50 => options
            .iter()
            .map(|v| string(v, 1, 200))
            .collect::<Result<Vec<_>>>()?,
        _ => return Err(invalid()),
    };
    let mut seen = HashSet::new();
    if options.iter().any(|s| !seen.insert(folded(s))) {
        return Err(invalid());
    }
    let multi = matches!(
        field_type.as_str(),
        "multiple_choice" | "yes_no" | "multi_select"
    );
    if multi == options.is_empty()
        || field_type == "multi_select"
            && options.iter().any(|s| {
                s.trim_matches(crate::context_contract::python_space)
                    .is_empty()
            })
    {
        return Err(invalid());
    }
    Ok(Question {
        question: text,
        category,
        field_type,
        required,
        max_characters,
        max_words,
        constraints,
        options,
        writing_style: style,
    })
}
pub fn normalize(input: Value, create: bool) -> Result<Prepare> {
    let allowed = if create {
        &["resume_resource_id", "questions", "idempotency_key"][..]
    } else {
        &["resume_resource_id", "questions"][..]
    };
    let body = object(&input, allowed)?;
    let resume_resource_id = body
        .get("resume_resource_id")
        .filter(|v| !v.is_null())
        .map(|v| {
            v.as_str()
                .and_then(|s| s.parse::<Uuid>().ok())
                .ok_or_else(invalid)
        })
        .transpose()?;
    let questions = match body.get("questions") {
        None => vec![],
        Some(Value::Array(questions)) if questions.len() <= 50 => questions
            .iter()
            .map(|v| question(v.clone()))
            .collect::<Result<Vec<_>>>()?,
        _ => return Err(invalid()),
    };
    let idempotency_key = if create {
        let key = string(body.get("idempotency_key").ok_or_else(invalid)?, 8, 100)?;
        if !key
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
        {
            return Err(invalid());
        }
        Some(key)
    } else {
        None
    };
    Ok(Prepare {
        resume_resource_id,
        questions,
        idempotency_key,
    })
}

/// Generated/loaded field data crosses the same closed structural boundary as legacy DTOs.
pub(crate) fn validate_field(value: &Value) -> Result<()> {
    static FIELD: LazyLock<jsonschema::Validator> = LazyLock::new(|| {
        let schema: Value = serde_json::from_str(include_str!("../schemas/packet-field.json"))
            .expect("frozen packet field schema");
        jsonschema::draft202012::options()
            .should_validate_formats(false)
            .build(&schema)
            .expect("local packet field validator")
    });
    if FIELD.is_valid(value) {
        Ok(())
    } else {
        Err(Failure("invalid_packet_field_record"))
    }
}
