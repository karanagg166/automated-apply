//! Direct-answer portion of the existing service. A narrative returns None for grounded composition.
use crate::{
    Failure, Result,
    answer_contract::{self, Generate},
    legacy_regex::Regex,
    link_resolver, personal_facts, profile_contract, question_classifier,
    resources::Resource,
};
use serde_json::{Value, json};
use std::{collections::BTreeMap, sync::LazyLock};

#[derive(Clone, Copy)]
pub struct Limits {
    pub characters: usize,
    pub words: Option<usize>,
}
fn count(text: &str, maximum: usize) -> Result<usize> {
    text.chars().try_fold(0usize, |n, c| {
        let digit =
            profile_contract::decimal_digit(c).ok_or(Failure("invalid_answer_limit"))? as usize;
        Ok(n.saturating_mul(10).saturating_add(digit).min(maximum))
    })
}
impl Limits {
    pub fn for_request(request: &Generate) -> Result<Self> {
        static CHARACTERS: LazyLock<Regex> =
            LazyLock::new(|| Regex::new(r"\b(\d+)\s*characters?\b", true));
        static WORDS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\b(\d+)\s*words?\b", true));
        let characters = CHARACTERS
            .first_group(&request.question, 1)?
            .map(|s| count(&s, request.max_characters))
            .transpose()?
            .unwrap_or(request.max_characters);
        let words = WORDS
            .first_group(&request.question, 1)?
            .map(|s| count(&s, request.max_words.unwrap_or(1500)))
            .transpose()?
            .or(request.max_words);
        Ok(Self { characters, words })
    }
    pub fn enforce(&self, mut value: Value) -> Value {
        if value["answer"].as_str().is_some_and(|s| {
            s.chars().count() > self.characters
                || self
                    .words
                    .is_some_and(|max| crate::grounding::words(s) > max)
        }) {
            value["answer"] = Value::Null;
            value["status"] = json!("validation_failed");
            value["requires_review"] = json!(true);
            value["error_code"] = json!("output_length_exceeded");
        }
        value
    }
}
fn number(value: &Value) -> Result<String> {
    let n = value
        .as_f64()
        .filter(|n| n.is_finite())
        .ok_or(Failure("invalid_profile_record"))?;
    let mut buffer = [0u8; 64];
    // A fixed format and bounded destination preserve Python's default six significant digits.
    let size =
        unsafe { libc::snprintf(buffer.as_mut_ptr().cast(), buffer.len(), c"%g".as_ptr(), n) };
    let size = usize::try_from(size)
        .ok()
        .filter(|n| *n < buffer.len())
        .ok_or(Failure("invalid_profile_record"))?;
    String::from_utf8(buffer[..size].to_vec()).map_err(|_| Failure("invalid_profile_record"))
}
fn field(profile: &Value, name: &str) -> Result<Option<String>> {
    let value = if [
        "notice_period_days",
        "work_authorization",
        "remote_preference",
        "minimum_salary",
    ]
    .contains(&name)
    {
        &profile["preferences"][name]
    } else {
        &profile[name]
    };
    if value.is_null() || value.as_array().is_some_and(Vec::is_empty) {
        return Ok(None);
    }
    let string = |v: &Value| {
        v.as_str()
            .map(String::from)
            .ok_or(Failure("invalid_profile_record"))
    };
    let list = || value.as_array().ok_or(Failure("invalid_profile_record"));
    Ok(Some(match name {
        "verified_skills" => list()?
            .iter()
            .map(string)
            .collect::<Result<Vec<_>>>()?
            .join(", "),
        "education" => list()?
            .iter()
            .map(|row| {
                Ok(format!(
                    "{}, {}",
                    string(&row["qualification"])?,
                    string(&row["institution"])?
                ))
            })
            .collect::<Result<Vec<_>>>()?
            .join("; "),
        "certifications" => list()?
            .iter()
            .map(|row| {
                let name = string(&row["name"])?;
                Ok(
                    if let Some(issuer) = row["issuer"].as_str().filter(|s| !s.is_empty()) {
                        format!("{name}, {issuer}")
                    } else {
                        name
                    },
                )
            })
            .collect::<Result<Vec<_>>>()?
            .join("; "),
        "verified_experience_years" => format!("{} years", number(value)?),
        "notice_period_days" => format!(
            "{} days",
            value.as_i64().ok_or(Failure("invalid_profile_record"))?
        ),
        "minimum_salary" => {
            let Some(currency) = profile["preferences"]["salary_currency"]
                .as_str()
                .filter(|s| !s.is_empty())
            else {
                return Ok(None);
            };
            format!("{} {currency}", number(value)?)
        }
        _ => string(value)?,
    }))
}
pub fn resolve(
    profile: &Value,
    resources: &[Resource],
    defaults: &BTreeMap<String, String>,
    request: &Generate,
) -> Result<Option<Value>> {
    let classification = question_classifier::classify(&request.question);
    let category = classification.question_type;
    let mut result = answer_contract::result(category, &request.writing_style);
    let factual = personal_facts::resolve(profile, &request.question, category)?;
    let mut answer = None;
    if factual.handled {
        result["question_type"] = json!(factual.category);
        answer = factual.answer;
        if answer.is_none() {
            result["missing_information"] = json!([format!(
                "Provide the exact approved {} requested by this form; no value is inferred",
                factual.field.unwrap_or("fact")
            )]);
        }
    } else if ["profile_link", "file_upload"].contains(&category) {
        result = link_resolver::resolve(profile, resources, defaults, &request.question);
        result["writing_style"] = json!(request.writing_style);
        return Ok(Some(Limits::for_request(request)?.enforce(result)));
    } else if let Some(name) = classification.field {
        static GENERIC: LazyLock<Regex> = LazyLock::new(|| {
            Regex::new(
                r"^(?:what is your |your )?(?:work )?authori[sz]ation(?: status)?[?.]?$",
                true,
            )
        });
        if category != "work_authorization" || GENERIC.is_match(&request.question)? {
            answer = field(profile, name)?;
        }
        if answer.as_ref().is_none_or(String::is_empty) {
            result["missing_information"] = json!([format!(
                "Provide the exact {} requested by this form",
                name.replace('_', " ")
            )]);
        }
    } else if ["unknown", "compensation", "work_authorization"].contains(&category) {
        let custom = link_resolver::resolve(profile, resources, defaults, &request.question);
        if custom["answer"].as_str().is_some_and(|s| !s.is_empty()) {
            result = custom;
            result["writing_style"] = json!(request.writing_style);
            return Ok(Some(Limits::for_request(request)?.enforce(result)));
        }
        result["missing_information"] =
            json!(["Provide a verified fact or clarify the question; no answer can be inferred"]);
    } else {
        return Ok(None);
    }
    if let Some(answer) = answer.filter(|s| !s.is_empty()) {
        let id = profile["id"]
            .as_str()
            .ok_or(Failure("invalid_profile_record"))?;
        result["answer"] = json!(answer);
        result["status"] = json!("draft_ready");
        result["requires_review"] = json!(false);
        result["source"] = json!("candidate_profile");
        result["confidence"] = json!(1.0);
        result["evidence_references"] = json!([{"source_type":"candidate_profile","source_id":id}]);
    }
    Ok(Some(Limits::for_request(request)?.enforce(result)))
}
