//! Grounded original-step preparation on the generation connection; no owner lock survives model IO.
use super::{
    events, owner_questions, questionnaire_context, questionnaire_steps, queue, storage::*,
};
use crate::{
    Failure, Result, answer_context, answer_service, packet_contract, packet_fields,
    packet_service, private_resume,
};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;
pub struct Services<'a> {
    pub packets: &'a packet_service::Settings,
    pub answers: &'a answer_service::Settings,
    pub narratives: Option<&'a answer_service::Settings>,
    pub resumes: &'a private_resume::Settings,
}
struct Initial {
    work: Value,
    profile: Value,
    prepared: Option<packet_fields::Prepared>,
    field: Option<Value>,
    cached: Option<Value>,
    projects: String,
    request: Option<crate::answer_contract::Generate>,
    generation: Option<String>,
    remote: bool,
}
fn narrative(question: &str) -> bool {
    matches!(
        crate::question_classifier::classify(question).question_type,
        "project_explanation"
            | "technical_experience"
            | "short_text"
            | "motivation"
            | "startup_interest"
    )
}
async fn cached_in(
    tx: &mut Transaction<'_, Postgres>,
    work: &Value,
    now: chrono::DateTime<chrono::Utc>,
) -> Result<Option<Value>> {
    let key = questionnaire_steps::reuse_key(work, &work["questionnaire"]);
    let Some(bank) = get(tx, &key).await? else {
        return Ok(None);
    };
    if timestamp(&bank["answer_expires_at"])? <= now
        || bank["profile_version"] != work["profile_version"]
    {
        return Ok(None);
    }
    let id = bank["question_id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    let Some(q) = get(tx, &format!("exec_q:{id}")).await? else {
        return Ok(None);
    };
    if q["reuse_approved"] != true
        || q["state"] != "answered"
        || q["answer"] != bank["answer"]
        || q["profile_version"] != work["profile_version"]
        || q["answer_expires_at"] != bank["answer_expires_at"]
        || q["reuse_key"] != key
    {
        return Ok(None);
    }
    let answer = bank["answer"].as_str().ok_or_else(invalid)?;
    let envelope = json!({"question":work["questionnaire"]["question"],"options":work["questionnaire"]["options"],"answer_type":if work["questionnaire"]["options"].as_array().is_some_and(|a|!a.is_empty()){"choice"}else{"text"},"max_characters":work["questionnaire"]["max_characters"]});
    super::question_answers::validate(&envelope, answer, now)?;
    Ok(Some(
        json!({"answer":answer,"evidence":[{"source_type":"owner_answer","source_id":id}],"source":"owner_approved_reuse","step_sha256":work["questionnaire"]["step_sha256"],"question_id":id,"answer_expires_at":bank["answer_expires_at"]}),
    ))
}
async fn initial_in(
    tx: &mut Transaction<'_, Postgres>,
    services: &Services<'_>,
) -> Result<Option<Initial>> {
    lock(tx).await?;
    let now = now(tx).await?;
    let Some(mut work) = queue::claim_in(
        tx,
        "naukri",
        &json!({"worker":"questionnaire_preparation"}),
        Some(&["prepare_questionnaire"]),
        now,
    )
    .await?
    else {
        return Ok(None);
    };
    let (_, profile) = questionnaire_context::check_in(
        tx,
        &mut work,
        services.packets,
        services.resumes,
        false,
        now,
    )
    .await?;
    let projects = crate::browser_profiles::form_service::projects(tx).await?;
    let cached = cached_in(tx, &work, now).await?;
    let mut initial = Initial {
        work,
        profile,
        prepared: None,
        field: None,
        cached,
        projects,
        request: None,
        generation: None,
        remote: false,
    };
    if initial.cached.is_some() || initial.work["questionnaire"]["answer_kind"] == "file" {
        return Ok(Some(initial));
    }
    let step = &initial.work["questionnaire"];
    crate::missing_contract::permitted(step["question"].as_str().ok_or_else(invalid)?, "")?;
    let remote = narrative(step["question"].as_str().unwrap())
        && services
            .narratives
            .is_some_and(|s| s.questionnaire_cohere_ready());
    let question = packet_contract::question(
        json!({"question":step["question"],"field_type":if step["options"].as_array().is_some_and(|v|!v.is_empty()){"multiple_choice"}else{"text"},"options":step["options"],"required":true,"max_characters":step["max_characters"]}),
    )?;
    let job = initial.work["job_id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    let resources = crate::resource_store::resolution_resources(
        tx,
        initial.profile["id"]
            .as_str()
            .unwrap()
            .parse::<Uuid>()
            .map_err(|_| invalid())?,
    )
    .await?;
    let resume = crate::resources::select_resume(&resources, None)?;
    let mut prepared = packet_fields::prepare_generation(
        question,
        job,
        Some(&initial.profile),
        Some(&resume),
        "user_provided",
        remote,
    )?;
    if let Some(request) = prepared.resolution.clone() {
        let request = crate::job_context::Reviewed::load_in(tx, job)
            .await?
            .ok_or(Failure("questionnaire_job_context_changed"))?
            .bind_request(&request)?;
        let stamp = answer_context::Stamp::load_in(tx, &request).await?;
        initial.generation = Some(stamp.generation().into());
        initial.request = Some(request.clone());
        prepared.resolution = Some(request.clone());
        if remote {
            initial.prepared = Some(prepared);
        } else {
            let result = answer_service::form_in(tx, request, services.answers).await?;
            initial.field = Some(packet_fields::resolved(
                prepared,
                &result,
                &initial.profile,
            )?);
        }
    } else {
        initial.field = Some(prepared.field);
    }
    initial.remote = remote;
    Ok(Some(initial))
}
fn chosen(initial: &Initial, field: Option<&Value>, opportunity: bool) -> Result<Option<Value>> {
    if let Some(cached) = &initial.cached {
        return Ok(Some(cached.clone()));
    }
    let Some(field) = field else {
        return Ok(None);
    };
    let p = &field["provenance"];
    let text = initial.work["questionnaire"]["question"]
        .as_str()
        .ok_or_else(invalid)?;
    let allowed = matches!(
        p["source"].as_str(),
        Some(
            "candidate_profile"
                | "candidate_resource"
                | "approved_answer"
                | "owner_approved_exact_context"
                | "cohere"
        )
    );
    let category = crate::question_classifier::classify(text).question_type;
    let source = if p["source"] == "approved_answer" && !p["missing_input_id"].is_null() {
        "owner_approved_exact_context"
    } else {
        p["source"].as_str().unwrap_or("")
    };
    if field["validation_status"] != "draft_ready"
        || field["effective_answer"].as_str().is_none_or(str::is_empty)
        || !allowed
        || p["evidence_references"]
            .as_array()
            .is_none_or(Vec::is_empty)
        || narrative(text)
            && !matches!(
                source,
                "approved_answer" | "owner_approved_exact_context" | "cohere"
            )
    {
        return Ok(None);
    }
    let answer = field["effective_answer"].as_str().unwrap();
    initial.work["questionnaire"]["options"]
        .as_array()
        .ok_or_else(invalid)?;
    if !initial.work["questionnaire"]["options"]
        .as_array()
        .unwrap()
        .is_empty()
        && !initial.work["questionnaire"]["options"]
            .as_array()
            .unwrap()
            .iter()
            .any(|o| o == answer)
    {
        return Ok(None);
    }
    let mut value = json!({"answer":answer,"evidence":p["evidence_references"],"source":"grounded_saved_context","step_sha256":initial.work["questionnaire"]["step_sha256"],"project_digest":initial.projects,"question_id":null,"answer_expires_at":null,"resolved_source":source,"request":initial.request,"context_generation":initial.generation,"opportunity_enabled":opportunity,"missing_input_id":p["missing_input_id"]});
    if category == "personal_details" && p["source"] == "candidate_profile" {
        value["canonical_fact"] = json!(true);
    }
    if source == "approved_answer" {
        value["reused_draft_id"] = p["answer_draft_id"].clone();
    }
    Ok(Some(value))
}
async fn finish_in(
    tx: &mut Transaction<'_, Postgres>,
    initial: &Initial,
    field: Option<&Value>,
    services: &Services<'_>,
) -> Result<bool> {
    lock(tx).await?;
    let now = now(tx).await?;
    let id = initial.work["id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    let mut work = queue::load_in(tx, id).await?;
    if work["revision"] != initial.work["revision"]
        || work["lease_token"] != initial.work["lease_token"]
        || work["status"] != "leased"
        || work["lease_until"].is_null()
        || timestamp(&work["lease_until"])? <= now
    {
        return Ok(false);
    }
    questionnaire_context::check_in(
        tx,
        &mut work,
        services.packets,
        services.resumes,
        false,
        now,
    )
    .await?;
    if crate::browser_profiles::form_service::projects(tx).await? != initial.projects {
        return Err(Failure("questionnaire_grounded_context_changed"));
    }
    let opportunity = if initial.remote {
        services.narratives.unwrap().opportunity
    } else {
        services.answers.opportunity
    };
    let answer = chosen(initial, field, opportunity)?;
    work["lease_token"] = Value::Null;
    work["lease_until"] = Value::Null;
    work["revision"] = json!(next(&work)?);
    work["updated_at"] = json!(stamp(now));
    if let Some(answer) = answer {
        if initial.cached.is_some() && cached_in(tx, &work, now).await?.as_ref() != Some(&answer) {
            return Err(Failure("questionnaire_owner_answer_changed"));
        }
        work["questionnaire_answer"] = answer;
        super::questionnaire_answer_context::verify_in(tx, &work, &initial.profile).await?;
        work["operation"] = json!("refresh_questionnaire_profile");
        work["stage"] = json!("QUESTIONS");
        work["status"] = json!("queued");
        work["reason"] = Value::Null;
    } else {
        work["stage"] = json!("NEEDS_INPUT");
        work["status"] = json!("waiting");
        work["reason"] = json!("questionnaire_verified_answer_required");
        if work["questionnaire"]["answer_kind"] == "file" {
            work["reason"] = json!("questionnaire_supported_resume_attachment_required");
        } else if field.is_some_and(|f| {
            f["provenance"]["source"] == "candidate_profile"
                && crate::question_classifier::classify(
                    work["questionnaire"]["question"].as_str().unwrap(),
                )
                .question_type
                    == "personal_details"
                && f["validation_status"] != "draft_ready"
        }) {
            work["reason"] = json!("questionnaire_saved_fact_does_not_fit_controls");
        } else {
            owner_questions::ask_in(tx, &work, now).await?;
        }
    }
    put(tx, &format!("apply_work:{id}"), &work).await?;
    events::queue(tx, &work, "questionnaire_preparation_finished", now).await?;
    Ok(true)
}
/// Run on the separately bounded generation connection. The caller must not hold its control mutex.
pub async fn prepare_one(generation: &mut PgConnection, services: Services<'_>) -> Result<bool> {
    let pending:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM owner_preferences WHERE starts_with(key,'apply_work:') AND value->>'operation'='prepare_questionnaire' AND value->>'status'='queued')").fetch_one(&mut *generation).await.map_err(db)?;
    if !pending {
        return Ok(false);
    }
    let mut tx = generation.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let initial = match initial_in(&mut tx, &services).await {
        Ok(v) => {
            tx.commit()
                .await
                .map_err(|_| Failure("execution_commit_outcome_unknown"))?;
            v
        }
        Err(e) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            return Err(e);
        }
    };
    let Some(initial) = initial else {
        return Ok(false);
    };
    let generated = if let Some(prepared) = &initial.prepared {
        let request = prepared.resolution.as_ref().ok_or_else(invalid)?;
        let result = answer_service::generate(
            generation,
            json!(request),
            services
                .narratives
                .filter(|s| s.questionnaire_cohere_ready())
                .ok_or(Failure("candidate_cloud_authorization_required"))?,
        )
        .await?;
        Some(packet_fields::resolved(
            packet_fields::Prepared {
                field: prepared.field.clone(),
                resolution: Some(request.clone()),
            },
            &result,
            &initial.profile,
        )?)
    } else {
        None
    };
    let field = generated.as_ref().or(initial.field.as_ref());
    let mut tx = generation.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    match finish_in(&mut tx, &initial, field, &services).await {
        Ok(value) => {
            tx.commit()
                .await
                .map_err(|_| Failure("execution_commit_outcome_unknown"))?;
            Ok(value)
        }
        Err(e) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            Err(e)
        }
    }
}
