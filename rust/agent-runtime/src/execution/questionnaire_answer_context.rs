//! Recheck newly generated answer evidence at queue handoff and again before answer admission.
use super::storage::*;
use crate::{
    Failure, Result, answer_context::Stamp, answer_contract, answer_direct, resource_store,
};
use serde_json::Value;
use sqlx::{Postgres, Transaction};
pub(crate) async fn verify_in(
    tx: &mut Transaction<'_, Postgres>,
    work: &Value,
    profile: &Value,
) -> Result<()> {
    let answer = &work["questionnaire_answer"];
    if answer["context_generation"].is_null() {
        return Ok(());
    } // Existing owner-correlated legacy records keep their original checks.
    let request = answer_contract::normalize(answer["request"].clone())?;
    if request.question
        != work["questionnaire"]["question"]
            .as_str()
            .ok_or_else(invalid)?
        || serde_json::json!(request.job_id) != work["job_id"]
    {
        return Err(Failure("questionnaire_grounded_context_changed"));
    }
    let stamp = Stamp::load_in(tx, &request).await?;
    if answer["context_generation"] != stamp.generation() {
        return Err(Failure("questionnaire_grounded_context_changed"));
    }
    let source = answer["resolved_source"].as_str().ok_or_else(invalid)?;
    let current = match source {
        "candidate_profile" | "candidate_resource" => {
            let resources = resource_store::resolution_resources(tx, stamp.profile_id()).await?;
            answer_direct::resolve(profile, &resources, &Default::default(), &request)?
        }
        "owner_approved_exact_context" => crate::missing_store::approved_in(tx, &request).await?,
        "approved_answer" => {
            crate::answer_reuse::reuse_in(
                tx,
                profile,
                &request,
                crate::question_classifier::classify(&request.question).question_type,
                answer_direct::Limits::for_request(&request)?,
                answer["opportunity_enabled"] == true,
            )
            .await?
        }
        "cohere" => return Ok(()),
        _ => return Err(Failure("questionnaire_grounded_context_changed")),
    }
    .ok_or(Failure("questionnaire_grounded_context_changed"))?;
    if current["answer"] != answer["answer"] {
        return Err(Failure("questionnaire_grounded_context_changed"));
    }
    if source == "approved_answer" && current["reused_draft_id"] != answer["reused_draft_id"] {
        return Err(Failure("questionnaire_grounded_context_changed"));
    }
    if source == "owner_approved_exact_context" && current["id"] != answer["missing_input_id"] {
        return Err(Failure("questionnaire_grounded_context_changed"));
    }
    Ok(())
}
