//! Continue only the original admitted Apply, with its current packet and original document binding.
use super::{
    contracts::{self, Kind},
    history, preflight, queue_control,
    storage::*,
};
use crate::{Failure, Result, packet_service, private_resume};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;
pub(crate) fn fresh(work: &Value, now: DateTime<Utc>) -> Result<()> {
    let answer = &work["questionnaire_answer"];
    if !answer["answer_expires_at"].is_null() && timestamp(&answer["answer_expires_at"])? <= now {
        return Err(Failure("questionnaire_answer_expired"));
    }
    if !preflight::account_current(work, now)
        || timestamp(&work["facts"]["provider_resume_checked_at"])
            .ok()
            .is_none_or(|at| at > now || now - at > chrono::Duration::minutes(2))
    {
        return Err(Failure("questionnaire_fresh_profile_observation_required"));
    }
    if !work["form_binding"].is_object()
        || [
            "profile_binding_id",
            "browser_session_id",
            "window_id",
            "tab_id",
        ]
        .iter()
        .any(|k| work["binding"][k] != work["form_binding"][k])
    {
        return Err(Failure("questionnaire_original_browser_context_required"));
    }
    Ok(())
}
pub(crate) async fn check_in(
    tx: &mut Transaction<'_, Postgres>,
    work: &mut Value,
    packets: &packet_service::Settings,
    resumes: &private_resume::Settings,
    writing: bool,
    now: DateTime<Utc>,
) -> Result<(Value, Value)> {
    let config = queue_control::configuration(tx).await?;
    let setting = &config["policy"]["platforms"]["naukri"];
    let execution = contracts::normalize(
        Kind::Configuration,
        get(tx, "exec_config:naukri").await?.unwrap_or(json!({})),
    )
    .map_err(|_| invalid())?;
    if config["state"] != "RUNNING"
        || setting["enabled"] != true
        || setting["owner_submission_authorized"] != true
        || setting["mode"] == "PREPARE_ONLY"
        || execution["mode"] == "OFF"
    {
        return Err(Failure("standing_submission_scope_required"));
    }
    preflight::check_account_in(tx, work).await?;
    if !work["admitted_actions"].as_array().is_some_and(|actions| {
        actions.iter().any(|a| {
            a["fingerprint"]
                .as_str()
                .is_some_and(|s| s.starts_with("apply:"))
        })
    }) {
        return Err(Failure("questionnaire_requires_original_apply_admission"));
    }
    if history::receipt_exists_in(tx, work["requisition"].as_str().ok_or_else(invalid)?).await? {
        return Err(Failure("prior_receipt_requires_reconciliation_no_replay"));
    }
    let packet_id = work["packet_id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    let packet = packet_service::read_locked_in(tx, packet_id, packets, now).await?;
    if packet["lifecycle_state"] != "submitting"
        || packet["revision"] != work["packet_revision"]
        || packet["candidate_profile_version"] != work["profile_version"]
        || packet["readiness"]["stale"] == true
    {
        return Err(Failure("questionnaire_packet_context_changed"));
    }
    let job_id = packet["job_id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    let job: Value = sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1")
        .bind(job_id)
        .fetch_optional(&mut **tx)
        .await
        .map_err(db)?
        .ok_or(Failure("questionnaire_job_context_changed"))?;
    if matches!(
        job["status"].as_str(),
        Some("applied" | "submitted" | "archived")
    ) || job["job_url"] != work["url"]
    {
        return Err(Failure("questionnaire_job_context_changed"));
    }
    let profile = preflight::eligible_in(tx, work, &config["policy"], &job, now).await?;
    let checked = preflight::pdf_in(tx, &packet, resumes, now).await?;
    if checked["state"] != "PDF_VERIFIED_LOCAL"
        || checked["sha256"] != work["upload_preflight"]["sha256"]
    {
        return Err(Failure("questionnaire_canonical_resume_changed"));
    }
    if writing {
        fresh(work, now)?;
        super::questionnaire_answer_context::verify_in(tx, work, &profile).await?;
        let answer = &work["questionnaire_answer"];
        if let Some(id) = answer["question_id"].as_str().filter(|s| !s.is_empty()) {
            id.parse::<Uuid>().map_err(|_| invalid())?;
            let question = get(tx, &format!("exec_q:{id}"))
                .await?
                .ok_or(Failure("questionnaire_owner_answer_changed"))?;
            if question["state"] != "answered"
                || question["answer"] != answer["answer"]
                || question["profile_version"] != work["profile_version"]
                || answer["source"] == "owner_approved_reuse" && question["reuse_approved"] != true
            {
                return Err(Failure("questionnaire_owner_answer_changed"));
            }
        }
        if let Some(digest) = answer["project_digest"].as_str().filter(|s| !s.is_empty())
            && crate::browser_profiles::form_service::projects(tx).await? != digest
        {
            return Err(Failure("questionnaire_grounded_context_changed"));
        }
    }
    Ok((packet, profile))
}
