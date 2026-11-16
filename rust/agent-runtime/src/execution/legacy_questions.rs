//! Owner dashboard questions share native envelopes and packet mutation guards; answers grant no fill.
use super::{
    events, filters, history, legacy_policy, owner_questions, question_answers, storage::*,
};
use crate::{
    Failure, Result, answer_service, browser_profiles, packet_mutation,
    packet_mutation_contract::Input, packet_service, private_resume,
};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;
#[derive(Clone, Copy)]
pub(super) struct Services<'a> {
    pub packets: &'a packet_service::Settings,
    pub answers: &'a answer_service::Settings,
    pub resumes: &'a private_resume::Settings,
}
fn id(value: &Value) -> Result<Uuid> {
    value
        .as_str()
        .and_then(|s| s.parse().ok())
        .ok_or_else(invalid)
}
fn closed(packet: &Value) -> bool {
    matches!(
        packet["lifecycle_state"].as_str(),
        Some(
            "user_reported_submitted"
                | "provider_confirmed_submitted"
                | "submitting"
                | "submission_unknown"
                | "withdrawn"
                | "abandoned"
        )
    )
}
async fn load_intent(tx: &mut Transaction<'_, Postgres>, identity: Uuid) -> Result<Value> {
    let value = get(tx, &format!("exec:{identity}"))
        .await?
        .ok_or(Failure("execution_not_found"))?;
    if value["id"] != identity.to_string() {
        return Err(invalid());
    }
    Ok(value)
}
async fn move_in(
    tx: &mut Transaction<'_, Postgres>,
    intent: &mut Value,
    state: &str,
    reason: &str,
    now: DateTime<Utc>,
) -> Result<()> {
    let old = intent["state"].clone();
    let mut history = intent["history"].as_array().ok_or_else(invalid)?.clone();
    if old != state && !matches!((old.as_str(), state), (Some("NEEDS_INPUT"), "PREPARING")) {
        return Err(Failure("invalid_execution_transition"));
    }
    history.push(json!({"from":old,"to":state,"reason":reason}));
    intent["history"] = json!(history);
    intent["state"] = json!(state);
    intent["revision"] = json!(next(intent)?);
    intent["diagnostic"] = json!(reason);
    put(tx, &format!("exec:{}", id(&intent["id"])?), intent).await?;
    events::legacy(tx, intent, "state_changed", now).await
}
pub(super) async fn ask_in(
    tx: &mut Transaction<'_, Postgres>,
    execution: Uuid,
    field: Uuid,
    services: Services<'_>,
    now: DateTime<Utc>,
) -> Result<Value> {
    let mut intent = load_intent(tx, execution).await?;
    if !matches!(
        intent["state"].as_str(),
        Some("NEEDS_INPUT" | "READY_FOR_REVIEW" | "FILLING")
    ) || intent["packet_id"].is_null()
    {
        return Err(Failure("execution_not_waiting_for_question"));
    }
    let packet =
        packet_service::read_locked_in(tx, id(&intent["packet_id"])?, services.packets, now)
            .await?;
    if packet["readiness"]["stale"] == true || closed(&packet) {
        return Err(Failure("packet_context_stale"));
    }
    let field = packet["fields"]
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .find(|f| f["id"] == field.to_string())
        .filter(|f| f["field_type"] != "file")
        .ok_or(Failure("answerable_packet_field_required"))?;
    browser_profiles::owner_question_envelope(
        tx,
        &packet,
        &mut intent,
        field,
        &Value::Null,
        &Value::Null,
        now,
    )
    .await
}
pub(super) async fn ask_packet_in(
    tx: &mut Transaction<'_, Postgres>,
    identity: Uuid,
    field_id: Uuid,
    expected: i64,
    services: Services<'_>,
    now: DateTime<Utc>,
) -> Result<Value> {
    let packet = packet_service::read_locked_in(tx, identity, services.packets, now).await?;
    if packet["revision"] != expected {
        return Err(Failure("packet_revision_conflict"));
    }
    let field = packet["fields"]
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .find(|f| f["id"] == field_id.to_string())
        .ok_or(Failure("missing_or_expired_answer_required"))?;
    let expired = !field["provenance"]["answer_expires_at"].is_null()
        && timestamp(&field["provenance"]["answer_expires_at"])? <= now;
    if !expired
        && (field["required"] != true
            || field["effective_answer"]
                .as_str()
                .is_some_and(|s| !s.is_empty()))
    {
        return Err(Failure("missing_or_expired_answer_required"));
    }
    crate::missing_contract::permitted(field["question"].as_str().ok_or_else(invalid)?, "")?;
    if packet["readiness"]["stale"] == true
        || closed(&packet)
        || packet["snapshot"]["destination"]["valid"] != true
    {
        return Err(Failure("packet_context_stale_or_destination_invalid"));
    }
    let job: Value = sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1")
        .bind(id(&packet["job_id"])?)
        .fetch_optional(&mut **tx)
        .await
        .map_err(db)?
        .ok_or(Failure("application_not_eligible"))?;
    if job["source_platform"] == "naukri" {
        legacy_policy::enabled(tx).await?;
    }
    if matches!(job["status"].as_str(), Some("archived" | "applied"))
        || history::previously_applied_in(tx, &job).await?
    {
        return Err(Failure("application_not_eligible"));
    }
    let url = packet["snapshot"]["destination"]["application_url"]
        .as_str()
        .ok_or(Failure("supported_ats_application_required"))?;
    let naukri = packet["platform"] == "naukri" && filters::naukri_url(url).is_ok_and(|u| u == url);
    if !naukri && crate::packet_platform::application_page(url, &services.packets.policy).is_none()
    {
        return Err(Failure("supported_ats_application_required"));
    }
    let intent = browser_profiles::owner_question_intent(tx, &packet, now).await?;
    ask_in(tx, id(&intent["id"])?, field_id, services, now).await
}
fn answer_metadata(question: &Value, expiry: &Value, answer: Option<&str>) -> Value {
    let mut metadata = json!({"telegram_question":question["id"],"answer_expires_at":expiry});
    if let Some(answer) = answer {
        metadata["interview_availability"] = if question["answer_type"] == "availability" {
            json!(answer)
        } else {
            Value::Null
        };
    }
    metadata
}
pub(super) async fn answer_in(
    tx: &mut Transaction<'_, Postgres>,
    identity: Uuid,
    data: &Value,
    services: Services<'_>,
    now: DateTime<Utc>,
) -> Result<Value> {
    let key = format!("exec_q:{identity}");
    let mut question = get(tx, &key).await?.ok_or(Failure("question_not_found"))?;
    if question["id"] != identity.to_string() {
        return Err(invalid());
    }
    if question["state"] == "answered" {
        return Err(Failure("question_already_answered"));
    }
    if data["expected_revision"] != question["packet_revision"] {
        return Err(Failure("question_revision_conflict"));
    }
    let answer = data["answer"]
        .as_str()
        .ok_or(Failure("invalid_execution_contract"))?;
    if !question["queue_work_id"].is_null() {
        owner_questions::answer_in(
            tx,
            &mut question,
            answer,
            "owner_dashboard",
            services.packets,
            services.resumes,
            now,
        )
        .await?;
        return Ok(question);
    }
    let mut intent = load_intent(tx, id(&question["execution_id"])?).await?;
    if timestamp(&question["expires_at"])? <= now
        || intent["state"] != "NEEDS_INPUT"
        || intent["cancelled"] == true
        || intent["packet_id"] != question["packet_id"]
    {
        return Err(Failure("question_expired_or_application_cancelled"));
    }
    let expiry = json!(question_answers::validate(&question, answer, now)?);
    let packet_id = id(&question["packet_id"])?;
    let packet = packet_service::read_locked_in(tx, packet_id, services.packets, now).await?;
    if packet["revision"] != data["expected_revision"]
        || packet["candidate_profile_version"] != question["profile_version"]
        || packet["snapshot"]["context_digest"] != question["context_digest"]
        || packet["readiness"]["stale"] == true
        || closed(&packet)
    {
        return Err(Failure("packet_context_stale"));
    }
    let field_id = id(&question["field_id"])?;
    let effective = question_answers::field_answer(&question, answer);
    let metadata = answer_metadata(&question, &expiry, Some(answer));
    let updated = packet_mutation::run_with_answer_metadata_in(
        tx,
        packet_id,
        &Input::Answer {
            expected_revision: i32::try_from(
                data["expected_revision"].as_i64().ok_or_else(invalid)?,
            )
            .map_err(|_| invalid())?,
            answer: effective.to_owned(),
        },
        Some(field_id),
        services.packets,
        services.answers,
        now,
        Some(&metadata),
    )
    .await?;
    let field = updated["fields"]
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .find(|f| f["id"] == field_id.to_string())
        .ok_or_else(invalid)?;
    question["state"] = json!("answered");
    question["answer_revision"] = field["answer_revision"].clone();
    question["answer"] = json!(effective);
    question["factual_context"] = json!(answer);
    question["answer_expires_at"] = expiry;
    question["provenance"] = json!({"channel":"dashboard","source":"owner_dashboard"});
    question["reuse_approved"] = json!(false);
    put(tx, &key, &question).await?;
    if intent["answer_revisions"].is_null() {
        intent["answer_revisions"] = json!({});
    }
    intent["answer_revisions"][field_id.to_string()] = field["answer_revision"].clone();
    // Bound only pending siblings in this packet and the original exact revision.
    let siblings:Vec<(String,Value)>=sqlx::query_as("SELECT key,value FROM owner_preferences WHERE starts_with(key,'exec_q:') AND key!=$1 AND value->>'packet_id'=$2 AND value->'packet_revision'=$3 AND value->>'state' IN ('pending','sent') ORDER BY created_at,key LIMIT 10001").bind(&key).bind(packet_id.to_string()).bind(&packet["revision"]).fetch_all(&mut **tx).await.map_err(db)?;
    if siblings.len() > 10000 {
        return Err(Failure("execution_active_inventory_limit"));
    }
    let waiting = !siblings.is_empty();
    for (key, mut sibling) in siblings {
        sibling["packet_revision"] = updated["revision"].clone();
        put(tx, &key, &sibling).await?;
    }
    if !waiting {
        move_in(
            tx,
            &mut intent,
            "PREPARING",
            "owner_answer_saved_fresh_review_required",
            now,
        )
        .await?;
    } else {
        put(tx, &format!("exec:{}", id(&intent["id"])?), &intent).await?;
    }
    browser_profiles::tasks::owner_answer_saved(tx, &question, &updated, waiting, now).await?;
    Ok(question)
}
pub(super) async fn approve_in(
    tx: &mut Transaction<'_, Postgres>,
    identity: Uuid,
    services: Services<'_>,
    now: DateTime<Utc>,
) -> Result<Value> {
    let key = format!("exec_q:{identity}");
    let mut question = get(tx, &key)
        .await?
        .ok_or(Failure("current_answer_required"))?;
    if question["id"] != identity.to_string() {
        return Err(invalid());
    }
    if question["state"] != "answered" || timestamp(&question["answer_expires_at"])? <= now {
        return Err(Failure("current_answer_required"));
    }
    if !question["queue_work_id"].is_null() {
        owner_questions::approve_in(tx, &mut question, services.packets, now).await?;
        return Ok(question);
    }
    let packet =
        packet_service::read_locked_in(tx, id(&question["packet_id"])?, services.packets, now)
            .await?;
    if packet["readiness"]["stale"] == true
        || packet["candidate_profile_version"] != question["profile_version"]
    {
        return Err(Failure("answer_context_stale"));
    }
    let field = packet["fields"]
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .find(|f| f["id"] == question["field_id"])
        .ok_or(Failure("answer_changed_review_again"))?;
    if field["effective_answer"] != question["answer"]
        || field["answer_revision"] != question["answer_revision"]
    {
        return Err(Failure("answer_changed_review_again"));
    }
    question["reuse_approved"] = json!(true);
    put(tx, &key, &question).await?;
    Ok(question)
}
pub(super) async fn reuse_in(
    tx: &mut Transaction<'_, Postgres>,
    source: Uuid,
    execution: Uuid,
    field_id: Uuid,
    services: Services<'_>,
    now: DateTime<Utc>,
) -> Result<Value> {
    let question = get(tx, &format!("exec_q:{source}"))
        .await?
        .ok_or(Failure("unexpired_reuse_approval_required"))?;
    if question["reuse_approved"] != true || timestamp(&question["answer_expires_at"])? <= now {
        return Err(Failure("unexpired_reuse_approval_required"));
    }
    if !question["queue_work_id"].is_null() {
        return Err(Failure("answer_reuse_context_mismatch"));
    }
    let original =
        packet_service::read_locked_in(tx, id(&question["packet_id"])?, services.packets, now)
            .await?;
    let source_field = original["fields"]
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .find(|f| f["id"] == question["field_id"]);
    if original["readiness"]["stale"] == true
        || source_field.is_none_or(|f| {
            f["effective_answer"] != question["answer"]
                || f["answer_revision"] != question["answer_revision"]
        })
    {
        return Err(Failure("source_answer_changed_review_again"));
    }
    let intent = load_intent(tx, execution).await?;
    if !matches!(
        intent["state"].as_str(),
        Some("NEEDS_INPUT" | "READY_FOR_REVIEW")
    ) {
        return Err(Failure("execution_not_waiting_for_question"));
    }
    let packet_id = id(&intent["packet_id"])?;
    let packet = packet_service::read_locked_in(tx, packet_id, services.packets, now).await?;
    let field = packet["fields"]
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .find(|f| f["id"] == field_id.to_string());
    let source_execution = load_intent(tx, id(&question["execution_id"])?).await?;
    let descriptions: Vec<(Uuid, Option<String>)> =
        sqlx::query_as("SELECT id,description FROM jobs WHERE id=ANY($1)")
            .bind(vec![
                id(&source_execution["job_id"])?,
                id(&packet["job_id"])?,
            ])
            .fetch_all(&mut **tx)
            .await
            .map_err(db)?;
    let source_description = descriptions
        .iter()
        .find(|(job, _)| {
            Some(*job)
                == source_execution["job_id"]
                    .as_str()
                    .and_then(|s| s.parse().ok())
        })
        .map(|(_, d)| d);
    let target_description = descriptions
        .iter()
        .find(|(job, _)| Some(*job) == packet["job_id"].as_str().and_then(|s| s.parse().ok()))
        .map(|(_, d)| d);
    if packet["readiness"]["stale"] == true
        || packet["candidate_profile_version"] != question["profile_version"]
        || packet["snapshot"]["company_name"] != question["employer"]
        || packet["snapshot"]["job_title"] != question["role"]
        || field.is_none_or(|f| {
            f["question"] != question["question"] || f["options"] != question["options"]
        })
        || source_description.is_none()
        || source_description != target_description
    {
        return Err(Failure("answer_reuse_context_mismatch"));
    }
    question_answers::validate(
        &question,
        question["factual_context"]
            .as_str()
            .or_else(|| question["answer"].as_str())
            .ok_or_else(invalid)?,
        now,
    )?;
    let metadata = answer_metadata(&question, &question["answer_expires_at"], None);
    packet_mutation::run_with_answer_metadata_in(
        tx,
        packet_id,
        &Input::Answer {
            expected_revision: i32::try_from(packet["revision"].as_i64().ok_or_else(invalid)?)
                .map_err(|_| invalid())?,
            answer: question["answer"].as_str().ok_or_else(invalid)?.into(),
        },
        Some(field_id),
        services.packets,
        services.answers,
        now,
        Some(&metadata),
    )
    .await?;
    packet_service::read_locked_in(tx, packet_id, services.packets, now).await
}
