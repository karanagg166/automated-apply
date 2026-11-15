//! Local checklist fields are never observed portal IDs. Narrative generation is explicit.
use crate::{
    Failure, Result,
    answer_contract::Generate,
    answer_direct::Limits,
    context_contract::python_space,
    packet_contract::Question,
    question_classifier,
    resources::{self, ResumeSelection},
};
use automated_apply_domain::text::{folded, lowered};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;

pub struct Prepared {
    pub field: Value,
    pub resolution: Option<Generate>,
}
fn invalid() -> Failure {
    Failure("invalid_packet_field_record")
}
fn narrative(category: &str) -> bool {
    matches!(
        category,
        "project_explanation"
            | "technical_experience"
            | "short_text"
            | "motivation"
            | "startup_interest"
    )
}
fn provenance(origin: &str) -> Value {
    json!({"origin":origin,"source":"missing","resolver":"needs_input","evidence_references":[],"interview_availability":null,"telegram_owner_update":null,"telegram_question":null,"form_semantic_key":null,"form_page_step":null,"form_section":null,"answer_expires_at":null,"answer_draft_id":null,"missing_input_id":null,"resource_id":null,"provider":null,"model":null,"error_code":null})
}
fn generate(question: &Question, job_id: Uuid) -> Generate {
    Generate {
        question: question.question.clone(),
        writing_style: question.writing_style.clone(),
        job_id: Some(job_id),
        company_name: None,
        job_description: None,
        max_characters: question.max_characters,
        max_words: question.max_words,
        save_draft: false,
        rewrite: false,
    }
}
fn missing(field: &mut Value, text: &str) {
    field["missing_information"] = json!([text]);
}
fn verified_choices(question: &str, profile: &Value) -> std::collections::HashSet<String> {
    let title = lowered(question.trim_matches(python_space))
        .split(python_space)
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join(" ");
    let title = title.trim_end_matches([' ', '*', '?', '.', ':']);
    let title = [
        "(select all that apply)",
        "(choose all that apply)",
        "(check all that apply)",
    ]
    .iter()
    .find_map(|suffix| title.strip_suffix(suffix))
    .unwrap_or(title)
    .trim_matches(python_space);
    if ![
        "skills",
        "technical skills",
        "select technical skills",
        "select your technical skills",
        "select all technical skills that apply",
        "which technical skills do you have",
        "programming languages",
    ]
    .contains(&title)
    {
        return Default::default();
    }
    profile["verified_skills"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .map(folded)
        .collect()
}
pub fn value_error(question: &Question, answer: Option<&str>) -> Result<Option<&'static str>> {
    let Some(answer) = answer.filter(|s| !s.trim_matches(python_space).is_empty()) else {
        return Ok(Some("Provide a nonblank answer"));
    };
    let limits = Limits::for_request(&generate(question, Uuid::nil()))?;
    if answer.chars().count() > limits.characters
        || limits
            .words
            .is_some_and(|n| crate::grounding::words(answer) > n)
    {
        return Ok(Some(
            "Answer exceeds the form length limit; edit it without changing its meaning",
        ));
    }
    if question.field_type == "multi_select" {
        let Ok(value) = serde_json::from_str::<Value>(answer) else {
            return Ok(Some("Supply a JSON array of exact displayed options"));
        };
        let Some(options) = value.as_array() else {
            return Ok(Some(
                "Select distinct exact form options; required sets cannot be empty",
            ));
        };
        let mut seen = std::collections::HashSet::new();
        if options.len() > 50
            || question.required && options.is_empty()
            || options.iter().any(|v| {
                v.as_str()
                    .is_none_or(|s| !question.options.iter().any(|o| o == s) || !seen.insert(s))
            })
        {
            return Ok(Some(
                "Select distinct exact form options; required sets cannot be empty",
            ));
        }
    } else if !question.options.is_empty() && !question.options.iter().any(|s| s == answer) {
        return Ok(Some("Answer must exactly match a supplied form option"));
    }
    if question.field_type == "url" && resources::public_https(answer).is_none() {
        return Ok(Some("Provide a valid public HTTPS URL"));
    }
    Ok(None)
}
pub fn prepare(
    question: Question,
    job: Uuid,
    profile: Option<&Value>,
    resume: Option<&ResumeSelection>,
    origin: &str,
) -> Result<Prepared> {
    prepare_mode(question, job, profile, resume, origin, false, false)
}
pub fn prepare_generation(
    question: Question,
    job: Uuid,
    profile: Option<&Value>,
    resume: Option<&ResumeSelection>,
    origin: &str,
    rewrite: bool,
) -> Result<Prepared> {
    prepare_mode(question, job, profile, resume, origin, true, rewrite)
}
fn prepare_mode(
    question: Question,
    job: Uuid,
    profile: Option<&Value>,
    resume: Option<&ResumeSelection>,
    origin: &str,
    explicit: bool,
    rewrite: bool,
) -> Result<Prepared> {
    if !matches!(origin, "packet_core" | "user_provided") {
        return Err(invalid());
    }
    let classification = question_classifier::classify(&question.question);
    let mut field = json!(question);
    let category = classification
        .field
        .and_then(|name| match name {
            "email" | "phone" => Some("contact_information"),
            "full_name" => Some("personal_information"),
            "education" => Some("education"),
            "verified_experience_years" => Some("experience"),
            "verified_skills" => Some("technical_skills"),
            "notice_period_days" => Some("notice_period"),
            "minimum_salary" => Some("salary"),
            "work_authorization" => Some("work_authorization"),
            _ => None,
        })
        .unwrap_or(match classification.question_type {
            "profile_link" => "professional_profile_url",
            "file_upload" => "resume_upload",
            "project_explanation" => "project_explanation",
            "technical_experience" => "experience",
            "short_text" => "free_text",
            "motivation" | "startup_interest" => "motivation",
            "work_authorization" => "work_authorization",
            "compensation" => "salary",
            _ => "unknown",
        });
    if question.category == "unknown" {
        field["category"] = json!(category);
    }
    field["id"] = json!(Uuid::new_v4());
    field["proposed_answer"] = Value::Null;
    field["human_answer"] = Value::Null;
    field["effective_answer"] = Value::Null;
    field["provenance"] = provenance(origin);
    field["validation_status"] = json!("needs_input");
    field["review_status"] = json!("pending");
    field["answer_revision"] = json!(1);
    field["requires_review"] = json!(true);
    field["missing_information"] = json!([]);
    let mut out = Prepared {
        field,
        resolution: None,
    };
    let field = &mut out.field;
    if question.field_type == "file"
        || classification.question_type == "file_upload" && question.field_type != "multi_select"
    {
        field["validation_status"] = json!("file_upload_required");
        field["provenance"]["resolver"] = json!("manual_upload");
        field["requires_review"] = json!(false);
        missing(
            field,
            "manual_resume_upload_required: select and upload the actual file on the official website",
        );
        return Ok(out);
    }
    let Some(profile) = profile else {
        missing(field, "Save the candidate profile first");
        return Ok(out);
    };
    if question.field_type == "multi_select" {
        let facts = verified_choices(&question.question, profile);
        let selected = question
            .options
            .iter()
            .filter(|s| facts.contains(&folded(s)))
            .cloned()
            .collect::<Vec<_>>();
        field["provenance"]["resolver"] = json!("deterministic");
        if selected.is_empty() {
            missing(
                field,
                "Choose and review the actual options; unknown choices are not verified negative facts",
            );
            return Ok(out);
        }
        let answer = crate::python_json::serialize(&json!(selected), true, false);
        if let Some(error) = value_error(&question, Some(&answer))? {
            field["validation_status"] = json!("validation_failed");
            missing(field, error);
            return Ok(out);
        }
        field["proposed_answer"] = json!(answer);
        field["effective_answer"] = field["proposed_answer"].clone();
        field["validation_status"] = json!("draft_ready");
        field["provenance"]["source"] = json!("candidate_profile");
        field["provenance"]["evidence_references"] =
            json!([{"source_type":"candidate_profile","source_id":profile["id"]}]);
        return Ok(out);
    }
    if classification.question_type == "profile_link"
        && crate::link_resolver::resource_types(&question.question)
            == std::collections::HashSet::from(["resume"])
        && let Some(resume) = resume
    {
        if let Some(selected) = &resume.selected {
            field["provenance"] = provenance(origin);
            field["provenance"]["source"] = json!("candidate_resource");
            field["provenance"]["resolver"] = json!("deterministic");
            field["provenance"]["resource_id"] = json!(selected.resource_id);
            if let Some(error) = value_error(&question, selected.url.as_deref())? {
                field["validation_status"] = json!("validation_failed");
                missing(field, error);
            } else {
                field["proposed_answer"] = json!(selected.url);
                field["effective_answer"] = json!(selected.url);
                field["validation_status"] = json!("draft_ready");
                field["requires_review"] = json!(false);
            }
        } else {
            missing(field, resume.reason);
        }
        return Ok(out);
    }
    let narrative = narrative(classification.question_type);
    if narrative && !explicit {
        field["provenance"]["resolver"] = json!("grounded_answer_service");
        missing(
            field,
            "Generate a grounded draft explicitly or enter your own factual answer, then review it",
        );
        return Ok(out);
    }
    let mut request = generate(&question, job);
    request.max_characters = request.max_characters.max(20);
    request.save_draft = explicit && narrative;
    request.rewrite = rewrite;
    if explicit
        && narrative
        && let Some(constraints) = &question.constraints
    {
        request.question = format!("{}\nForm constraints: {constraints}", question.question);
        if request.question.chars().count() > 2000 {
            field["validation_status"] = json!("validation_failed");
            missing(
                field,
                "Combined question and constraints exceed the supported input limit",
            );
            return Ok(out);
        }
    }
    out.resolution = Some(request);
    Ok(out)
}
pub fn resolved(mut prepared: Prepared, result: &Value, profile: &Value) -> Result<Value> {
    let request = prepared.resolution.take().ok_or_else(invalid)?;
    let category = question_classifier::classify(&request.question).question_type;
    let field = &mut prepared.field;
    if result["source"] == "environment_default" {
        missing(
            field,
            "Confirm and save this profile link before using it in an application",
        );
        return Ok(prepared.field);
    }
    field["validation_status"] = result["status"].clone();
    field["missing_information"] = result["missing_information"].clone();
    field["requires_review"] = json!(narrative(category) || result["requires_review"] == true);
    field["proposed_answer"] = result["answer"].clone();
    let origin = field["provenance"]["origin"]
        .as_str()
        .ok_or_else(invalid)?
        .to_owned();
    let mut p = provenance(&origin);
    p["source"] =
        if result["used_llm"] == true && result["answer"].as_str().is_some_and(|s| !s.is_empty()) {
            result["provider"].clone()
        } else if result["source"] == "owner_approved_exact_context" {
            json!("approved_answer")
        } else if matches!(
            result["source"].as_str(),
            Some(
                "candidate_profile"
                    | "candidate_resource"
                    | "approved_answer"
                    | "deterministic_extractive"
            )
        ) {
            result["source"].clone()
        } else {
            json!("missing")
        };
    p["resolver"] = json!(if narrative(category) {
        "grounded_answer_service"
    } else {
        "deterministic"
    });
    p["evidence_references"] = result["evidence_references"].clone();
    p["answer_draft_id"] = result["draft_id"].clone();
    p["missing_input_id"] = result["missing_input_id"].clone();
    p["provider"] = result["provider"].clone();
    p["model"] = result["model"].clone();
    p["error_code"] = result["error_code"].clone();
    if result["answer"].as_str().is_some_and(|s| !s.is_empty())
        && result["source"] == "candidate_profile"
        && p["evidence_references"]
            .as_array()
            .is_some_and(Vec::is_empty)
    {
        p["evidence_references"] =
            json!([{"source_type":"candidate_profile","source_id":profile["id"]}]);
    }
    field["provenance"] = p;
    if result["error_code"].as_str().is_some_and(|s| !s.is_empty())
        && field["missing_information"]
            .as_array()
            .is_some_and(Vec::is_empty)
    {
        missing(
            field,
            &format!(
                "Answer generation requires attention: {}; correct inputs/configuration or supply and review a factual answer",
                result["error_code"].as_str().unwrap()
            ),
        );
    }
    if let Some(answer) = result["answer"].as_str().filter(|s| !s.is_empty()) {
        let mut source = field.as_object().ok_or_else(invalid)?.clone();
        source.retain(|k, _| {
            [
                "question",
                "category",
                "field_type",
                "required",
                "max_characters",
                "max_words",
                "constraints",
                "options",
                "writing_style",
            ]
            .contains(&k.as_str())
        });
        let question = crate::packet_contract::question(Value::Object(source))?;
        if let Some(error) = value_error(&question, Some(answer))? {
            field["proposed_answer"] = Value::Null;
            field["validation_status"] = json!("validation_failed");
            missing(field, error);
        }
    }
    field["effective_answer"] = field["proposed_answer"].clone();
    crate::packet_contract::validate_field(field)?;
    Ok(prepared.field)
}
/// Uses the packet caller's transaction throughout; never invokes the public generation lifecycle.
pub async fn build_factual_in(
    tx: &mut Transaction<'_, Postgres>,
    question: Question,
    job: Uuid,
    profile: Option<&Value>,
    resume: Option<&ResumeSelection>,
    origin: &str,
    settings: &crate::answer_service::Settings,
) -> Result<Value> {
    let prepared = prepare(question, job, profile, resume, origin)?;
    if let Some(request) = &prepared.resolution {
        let result = crate::answer_service::factual_in(tx, request.clone(), settings).await?;
        resolved(prepared, &result, profile.ok_or_else(invalid)?)
    } else {
        Ok(prepared.field)
    }
}
