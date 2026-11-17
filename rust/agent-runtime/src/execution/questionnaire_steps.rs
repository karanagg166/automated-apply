//! Original-document questionnaire transitions. A prepared answer is never an Apply or receipt.
use super::{storage::*, submission};
use crate::{Failure, Result, legacy_regex::Regex};
use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::sync::LazyLock;
pub const READS: &[&str] = &[
    "inspect_questionnaire",
    "refresh_questionnaire_profile",
    "refresh_questionnaire_job",
];
pub const OPERATIONS: &[&str] = &[
    "inspect_questionnaire",
    "refresh_questionnaire_profile",
    "refresh_questionnaire_job",
    "answer_questionnaire",
];
pub fn step_hash(work: &Value, step: &Value) -> String {
    let data = json!([
        work["url"],
        step["question"],
        step["answer_kind"],
        step["options"]
    ]);
    format!(
        "{:x}",
        Sha256::digest(crate::python_json::serialize(&data, true, false))
    )
}
pub fn reuse_key(work: &Value, step: &Value) -> String {
    let kind =
        crate::question_classifier::classify(step["question"].as_str().unwrap_or("")).question_type;
    let mut scope = vec![
        work["candidate_profile_id"].clone(),
        work["profile_version"].clone(),
        step["question"].clone(),
        step["answer_kind"].clone(),
        step["options"].clone(),
    ];
    if !matches!(
        kind,
        "personal_details" | "profile_link" | "work_authorization"
    ) {
        let mut facts = serde_json::Map::new();
        for key in [
            "title",
            "company",
            "description",
            "location",
            "skills",
            "experience_min",
            "experience_max",
            "salary_min",
            "salary_max",
        ] {
            facts.insert(key.into(), work["facts"][key].clone());
        }
        scope.push(Value::Object(facts));
    }
    format!(
        "aa_ans:{}",
        URL_SAFE_NO_PAD.encode(Sha256::digest(crate::python_json::serialize(
            &json!(scope),
            false,
            false
        )))
    )
}
pub fn descriptor(work: &Value) -> Value {
    let mut value = json!({"expected_account_sha256":work["account_sha256"],"expected_resume_sha256":work["upload_preflight"]["sha256"],"account_observation":submission::account_observation(work),"expected_title":work["title"],"expected_company":work["company"]});
    if let Some(document) = completion_document(work) {
        value["completion_document_id"] = json!(document);
    }
    if work["operation"] == "answer_questionnaire" && work["status"] == "executing" {
        value["questionnaire"] = json!({"document_id":work["questionnaire"]["document_id"],"step_sha256":work["questionnaire"]["step_sha256"],"answer":work["questionnaire_answer"]["answer"],"permit_expires_at":work["permit_expires_at"]});
    }
    value
}

fn completion_document(work: &Value) -> Option<&str> {
    let document = work["questionnaire_document_id"].as_str()?;
    (work["operation"] == "inspect_questionnaire"
        && work["form_pending"] == true
        && work["form_loss_observation"].is_null()
        && work["form_binding"].is_object()
        && [
            "profile_binding_id",
            "browser_session_id",
            "window_id",
            "tab_id",
        ]
        .iter()
        .all(|key| {
            !work["binding"][*key].is_null() && work["binding"][*key] == work["form_binding"][*key]
        })
        && work["questionnaire_steps"]
            .as_u64()
            .is_some_and(|n| (1..=20).contains(&n))
        && !work["document_id"].is_null()
        && document.parse::<uuid::Uuid>().is_ok_and(|id| !id.is_nil()))
    .then_some(document)
}
/// Pure post-context transition, consuming an already validated native report. No authority checks here.
pub fn transition(work: &mut Value, report: &Value, now: DateTime<Utc>) -> Result<()> {
    let operation = work["operation"].as_str().ok_or_else(invalid)?.to_owned();
    if !OPERATIONS.contains(&operation.as_str()) {
        return Err(Failure("questionnaire_operation_unsupported"));
    }
    if matches!(report["kind"].as_str(), Some("failed" | "needs_input")) {
        work["stage"] = json!("SUBMISSION_UNKNOWN");
        work["status"] = json!("unknown");
        work["reason"] = report
            .get("reason")
            .filter(|s| s.is_string())
            .cloned()
            .unwrap_or(json!("questionnaire_unconfirmed"));
        return Ok(());
    }
    if operation == "refresh_questionnaire_profile" {
        let observed = &report["execution"];
        if report["kind"] != "execution_observation"
            || observed["state"] != "PROFILE_VERIFIED"
            || observed["account_sha256"] != work["account_sha256"]
            || observed["resume_sha256"] != work["upload_preflight"]["sha256"]
            || observed["resume_bytes"] != work["upload_preflight"]["byte_count"]
            || report["observed_url"] != submission::PROFILE_URL
        {
            return Err(Failure("questionnaire_profile_observation_required"));
        }
        work["account_observation"] = json!({"source":"profile_ui","work_id":work["id"],"account_sha256":observed["account_sha256"],"profile_document_id":observed["document_id"],"observed_at":stamp(now),"binding":work["binding"]});
        work["facts"]["provider_resume_checked_at"] = json!(stamp(now));
        work["facts"]["provider_resume_sha256"] = observed["resume_sha256"].clone();
        work["facts"]["provider_resume_source"] = json!("profile_download_ui");
        work["operation"] = json!("refresh_questionnaire_job");
        work["status"] = json!("leased");
        work["stage"] = json!("QUESTIONS");
        return Ok(());
    }
    if report["observed_url"] != work["url"] || report["requisition"] != work["requisition"] {
        return Err(Failure("questionnaire_job_context_changed"));
    }
    if operation == "refresh_questionnaire_job" {
        if report["stage"] == "ALREADY_APPLIED" {
            work["stage"] = json!("VERIFYING");
            work["status"] = json!("queued");
            work["operation"] = json!("reconcile_application");
            work["reason"] = json!("questionnaire_already_applied_reconcile_only");
            return Ok(());
        }
        if report["kind"] != "job_facts" || !report["job"].is_object() {
            return Err(Failure("questionnaire_fresh_job_facts_required"));
        }
        for field in [
            "requisition",
            "title",
            "company",
            "description",
            "location",
            "skills",
            "experience_min",
            "experience_max",
            "remote_type",
            "employment_type",
            "salary_min",
            "salary_max",
            "salary_currency",
            "salary_period",
        ] {
            if report["job"][field] != work["facts"][field] {
                return Err(Failure("questionnaire_job_requirements_changed"));
            }
        }
        for (k, v) in report["job"].as_object().unwrap() {
            work["facts"][k] = v.clone();
        }
        work["operation"] = json!("inspect_questionnaire");
        work["status"] = json!("leased");
        work["stage"] = json!("QUESTIONS");
        return Ok(());
    }
    if operation == "inspect_questionnaire" {
        if report["kind"] == "execution_observation" {
            let provider = &report["execution"];
            if completion_document(work).is_none_or(|document| report["document_id"] != document)
                || provider["state"] != "APPLIED"
                || provider["document_id"] != work["document_id"]
                || provider["account_sha256"] != work["account_sha256"]
                || provider["title"] != work["title"]
                || provider["company"] != work["company"]
            {
                return Err(Failure("questionnaire_completion_observation_mismatch"));
            }
            work["questionnaire_completion_observation"] = json!({
                "document_id": report["document_id"], "listing_document_id": provider["document_id"],
                "evidence_sha256": provider["evidence_sha256"], "observed_at": stamp(now),
            });
            work["stage"] = json!("VERIFYING");
            work["status"] = json!("queued");
            work["operation"] = json!("reconcile_application");
            work["reason"] = json!("questionnaire_applied_status_history_required");
            return Ok(());
        }
        let step = &report["questionnaire"];
        if report["kind"] != "questionnaire" || !step.is_object() {
            return Err(Failure("questionnaire_observation_required"));
        }
        if step["step_sha256"] != step_hash(work, step) {
            return Err(Failure("questionnaire_step_evidence_changed"));
        }
        static IDENTITY: LazyLock<Regex> = LazyLock::new(|| {
            Regex::new(
                r"\b(email|e-mail|login|password|otp|consent|terms and conditions)\b",
                true,
            )
        });
        let question = step["question"].as_str().ok_or_else(invalid)?;
        if IDENTITY.is_match(question)? {
            work["stage"] = json!("NEEDS_INPUT");
            work["status"] = json!("waiting");
            work["reason"] = json!("questionnaire_identity_or_consent_requires_manual_review");
            return Ok(());
        }
        if !work["questionnaire_document_id"].is_null()
            && work["questionnaire_document_id"] != step["document_id"]
        {
            return Err(Failure("questionnaire_original_document_required"));
        }
        work["questionnaire_document_id"] = step["document_id"].clone();
        if crate::missing_contract::permitted(question, "").is_err() {
            work["stage"] = json!("NEEDS_INPUT");
            work["status"] = json!("waiting");
            work["reason"] = json!("questionnaire_sensitive_input_requires_manual_review");
            return Ok(());
        }
        let count = work
            .get("questionnaire_steps")
            .map(|n| n.as_i64().filter(|n| *n >= 0).ok_or_else(invalid))
            .transpose()?
            .unwrap_or(0);
        if count >= 20 {
            return Err(Failure("questionnaire_step_limit_reached"));
        }
        if work["admitted_actions"]
            .as_array()
            .ok_or_else(invalid)?
            .iter()
            .any(|a| {
                a["fingerprint"]
                    == format!(
                        "answer_questionnaire:{}",
                        step["step_sha256"].as_str().unwrap()
                    )
            })
        {
            work["stage"] = json!("NEEDS_INPUT");
            work["status"] = json!("waiting");
            work["reason"] = json!("questionnaire_same_step_after_answer_requires_review");
            return Ok(());
        }
        work["questionnaire"] = step.clone();
        if let Some(answer) = work.get("questionnaire_answer").filter(|v| v.is_object()) {
            if answer["step_sha256"] != step["step_sha256"]
                || !answer["answer_expires_at"].is_null()
                    && timestamp(&answer["answer_expires_at"])? <= now
            {
                work.as_object_mut()
                    .ok_or_else(invalid)?
                    .remove("questionnaire_answer");
            } else {
                work["stage"] = json!("QUESTIONS");
                work["status"] = json!("leased");
                work["operation"] = json!("answer_questionnaire");
                work["reason"] = Value::Null;
                work["step_fingerprint"] = step["step_sha256"].clone();
                return Ok(());
            }
        }
        work["stage"] = json!("QUESTIONS");
        work["status"] = json!("queued");
        work["operation"] = json!("prepare_questionnaire");
        work["reason"] = Value::Null;
        return Ok(());
    }
    let step = &work["questionnaire"];
    if report["kind"] != "questionnaire_answer_attempted"
        || report["document_id"] != step["document_id"]
        || report["step_sha256"] != step["step_sha256"]
    {
        return Err(Failure("questionnaire_answer_observation_required"));
    }
    let count = work
        .get("questionnaire_steps")
        .map(|v| {
            v.as_i64()
                .filter(|n| (0..20).contains(n))
                .ok_or_else(invalid)
        })
        .transpose()?
        .unwrap_or(0);
    work["stage"] = json!("QUESTIONS");
    work["status"] = json!("queued");
    work["operation"] = json!("inspect_questionnaire");
    work["reason"] = Value::Null;
    work["questionnaire_steps"] = json!(count + 1);
    work.as_object_mut()
        .ok_or_else(invalid)?
        .remove("questionnaire_answer");
    Ok(())
}
