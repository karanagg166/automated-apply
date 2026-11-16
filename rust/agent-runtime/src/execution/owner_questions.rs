//! Durable per-application owner questions and explicit exact-scope reuse. No Telegram/network IO.
use super::{
    events, question_answers, questionnaire_context, questionnaire_steps, queue, queue_control,
    storage::*,
};
use crate::{Failure, Result, packet_service, private_resume};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;
pub const PREFIX: &str = "exec_q:";
pub fn message_text(question: &Value) -> Result<String> {
    let label = |key: &str| question[key].as_str().ok_or_else(invalid);
    let options: Vec<String> =
        serde_json::from_value(question["options"].clone()).map_err(|_| invalid())?;
    let hint = if options.is_empty() {
        label("answer_type")?.to_owned()
    } else {
        options.join(" / ")
    };
    let text = format!(
        "{} — {}\nQuestion: {}\n{}\nExpected: {hint}\nReply to THIS message with your verified factual answer. It applies only to this application; reuse is OFF. The worker will refresh the account, resume, listing and original form before continuing. It will not repeat Apply.",
        label("employer")?,
        label("role")?,
        label("question")?,
        label("job_url")?
    );
    if text.chars().count() > 4000 {
        return Err(Failure("telegram_question_too_long_manual_required"));
    }
    Ok(text)
}
pub(crate) async fn ask_in(
    tx: &mut Transaction<'_, Postgres>,
    work: &Value,
    now: DateTime<Utc>,
) -> Result<Value> {
    let step = &work["questionnaire"];
    let text = step["question"].as_str().ok_or_else(invalid)?;
    crate::missing_contract::permitted(text, "")?;
    if step["answer_kind"] == "file" {
        return Err(Failure(
            "questionnaire_supported_resume_attachment_required",
        ));
    }
    let identity = Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!(
            "queue_question:{}:{}:{}",
            work["id"].as_str().ok_or_else(invalid)?,
            work["packet_revision"].as_i64().ok_or_else(invalid)?,
            step["step_sha256"].as_str().ok_or_else(invalid)?
        )
        .as_bytes(),
    );
    let key = format!("{PREFIX}{identity}");
    if let Some(existing) = get(tx, &key).await? {
        if existing["id"] != identity.to_string()
            || existing["queue_work_id"] != work["id"]
            || existing["step_sha256"] != step["step_sha256"]
        {
            return Err(invalid());
        }
        return Ok(existing);
    }
    let value = json!({"id":identity,"queue_work_id":work["id"],"execution_id":work["id"],"packet_id":work["packet_id"],"packet_revision":work["packet_revision"],"profile_version":work["profile_version"],"step_sha256":step["step_sha256"],"question":text,"options":step["options"],"answer_type":if step["options"].as_array().is_some_and(|a|!a.is_empty()){"choice"}else{"text"},"max_characters":step["max_characters"],"employer":work["company"],"role":work["title"],"job_url":work["url"],"state":"pending","delivery_lease":null,"message_ids":[],"expired_message_ids":[],"expires_at":stamp(now+chrono::Duration::days(2)),"reuse_approved":false,"reuse_key":questionnaire_steps::reuse_key(work,step)});
    message_text(&value)?;
    let ack:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value) VALUES($1,$2) ON CONFLICT(key) DO NOTHING RETURNING value").bind(&key).bind(&value).fetch_optional(&mut **tx).await.map_err(db)?;
    if ack.as_ref() != Some(&value) {
        return Err(Failure("execution_write_ack_failed"));
    }
    Ok(value)
}
pub(crate) async fn current_in(
    tx: &mut Transaction<'_, Postgres>,
    question: &Value,
) -> Result<Option<Value>> {
    let id = question["queue_work_id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    let work = match queue::load_in(tx, id).await {
        Ok(v) => v,
        Err(Failure("queue_item_not_found")) => return Ok(None),
        Err(e) => return Err(e),
    };
    let config = queue_control::configuration(tx).await?;
    if config["state"] != "RUNNING"
        || work["stage"] != "NEEDS_INPUT"
        || work["status"] != "waiting"
        || work["questionnaire"]["step_sha256"] != question["step_sha256"]
        || work["packet_id"] != question["packet_id"]
        || work["packet_revision"] != question["packet_revision"]
        || work["profile_version"] != question["profile_version"]
    {
        return Ok(None);
    }
    Ok(Some(work))
}
pub(crate) async fn answer_in(
    tx: &mut Transaction<'_, Postgres>,
    question: &mut Value,
    answer: &str,
    source: &str,
    packets: &packet_service::Settings,
    resumes: &private_resume::Settings,
    now: DateTime<Utc>,
) -> Result<Value> {
    if !matches!(source, "owner_dashboard" | "owner_telegram") {
        return Err(Failure("owner_answer_channel_required"));
    }
    if question["state"] == "answered" {
        return Err(Failure("question_already_answered"));
    }
    if !matches!(question["state"].as_str(), Some("pending" | "sent"))
        || timestamp(&question["expires_at"])? <= now
    {
        return Err(Failure("question_expired_or_application_cancelled"));
    }
    let mut work = current_in(tx, question)
        .await?
        .ok_or(Failure("questionnaire_question_context_changed"))?;
    let step = &work["questionnaire"];
    if step["question"] != question["question"]
        || step["options"] != question["options"]
        || step["max_characters"] != question["max_characters"]
        || step["answer_kind"] == "file"
    {
        return Err(Failure("questionnaire_question_context_changed"));
    }
    let expiry = question_answers::validate(question, answer, now)?;
    questionnaire_context::check_in(tx, &mut work, packets, resumes, false, now).await?;
    question["state"] = json!("answered");
    question["answer"] = json!(answer);
    question["answer_expires_at"] = json!(expiry);
    question["reuse_approved"] = json!(false);
    question["provenance"] = json!({"source":source,"application_only":true});
    work["questionnaire_answer"] = json!({"answer":answer,"source":source,"question_id":question["id"],"answer_expires_at":expiry,"step_sha256":question["step_sha256"]});
    work["stage"] = json!("QUESTIONS");
    work["status"] = json!("queued");
    work["operation"] = json!("refresh_questionnaire_profile");
    work["reason"] = Value::Null;
    work["revision"] = json!(next(&work)?);
    work["available_at"] = json!(stamp(now));
    work["updated_at"] = json!(stamp(now));
    put(
        tx,
        &format!("{PREFIX}{}", question["id"].as_str().ok_or_else(invalid)?),
        question,
    )
    .await?;
    put(
        tx,
        &format!("apply_work:{}", work["id"].as_str().ok_or_else(invalid)?),
        &work,
    )
    .await?;
    events::queue(
        tx,
        &work,
        "questionnaire_owner_answer_saved_refresh_required",
        now,
    )
    .await?;
    Ok(work)
}
pub async fn answer_dashboard(
    c: &mut sqlx::PgConnection,
    id: Uuid,
    expected_packet_revision: i64,
    answer: &str,
    packets: &packet_service::Settings,
    resumes: &private_resume::Settings,
) -> Result<Value> {
    use sqlx::Connection;
    let answer = answer.trim_matches(crate::context_contract::python_space);
    if answer.chars().count() > 4000 {
        return Err(Failure("answer_length_invalid"));
    }
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
        sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            .execute(&mut *tx)
            .await
            .map_err(db)?;
        lock(&mut tx).await?;
        let now = now(&mut tx).await?;
        let mut question = get(&mut tx, &format!("{PREFIX}{id}"))
            .await?
            .ok_or(Failure("question_not_found"))?;
        if question["id"] != id.to_string() {
            return Err(invalid());
        }
        if question["packet_revision"] != expected_packet_revision {
            return Err(Failure("question_revision_conflict"));
        }
        answer_in(
            &mut tx,
            &mut question,
            answer,
            "owner_dashboard",
            packets,
            resumes,
            now,
        )
        .await?;
        Ok(question)
    }
    .await;
    match result {
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
pub(crate) async fn approve_in(
    tx: &mut Transaction<'_, Postgres>,
    question: &mut Value,
    packets: &packet_service::Settings,
    now: DateTime<Utc>,
) -> Result<()> {
    if question["state"] != "answered" || timestamp(&question["answer_expires_at"])? <= now {
        return Err(Failure("current_answer_required"));
    }
    let packet_id = question["packet_id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    let packet = packet_service::read_locked_in(tx, packet_id, packets, now).await?;
    if packet["readiness"]["stale"] == true
        || packet["candidate_profile_version"] != question["profile_version"]
    {
        return Err(Failure("answer_context_stale"));
    }
    let mut key = question["reuse_key"]
        .as_str()
        .ok_or_else(invalid)?
        .to_owned();
    if let Some(hash) = key.strip_prefix("apply_answer_bank:") {
        if hash.len() != 64
            || !hash
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            return Err(Failure("answer_context_stale"));
        }
        use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
        let bytes = (0..64)
            .step_by(2)
            .map(|i| u8::from_str_radix(&hash[i..i + 2], 16).map_err(|_| invalid()))
            .collect::<Result<Vec<_>>>()?;
        key = format!("aa_ans:{}", URL_SAFE_NO_PAD.encode(bytes));
    }
    if key.len() != 50
        || !key.starts_with("aa_ans:")
        || !key.as_bytes()[7..]
            .iter()
            .all(|b| b.is_ascii_alphanumeric() || matches!(*b, b'_' | b'-'))
    {
        return Err(Failure("answer_context_stale"));
    }
    let answer = question["answer"].as_str().ok_or_else(invalid)?;
    question_answers::validate(question, answer, now)?;
    question["reuse_key"] = json!(key);
    question["reuse_approved"] = json!(true);
    put(
        tx,
        &format!("{PREFIX}{}", question["id"].as_str().ok_or_else(invalid)?),
        question,
    )
    .await?;
    put(tx,&key,&json!({"answer":question["answer"],"question_id":question["id"],"profile_version":question["profile_version"],"answer_expires_at":question["answer_expires_at"]})).await
}
pub async fn approve_reuse(
    c: &mut sqlx::PgConnection,
    id: Uuid,
    packets: &packet_service::Settings,
) -> Result<Value> {
    use sqlx::Connection;
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
        sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            .execute(&mut *tx)
            .await
            .map_err(db)?;
        lock(&mut tx).await?;
        let now = now(&mut tx).await?;
        let mut question = get(&mut tx, &format!("{PREFIX}{id}"))
            .await?
            .ok_or(Failure("question_not_found"))?;
        if question["id"] != id.to_string() || question["queue_work_id"].is_null() {
            return Err(Failure("questionnaire_question_context_changed"));
        }
        approve_in(&mut tx, &mut question, packets, now).await?;
        Ok(question)
    }
    .await;
    match result {
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
/// Internal grounded preparation calls this only after proving the original submitting context.
pub async fn ask(
    c: &mut sqlx::PgConnection,
    identity: Uuid,
    packets: &packet_service::Settings,
    resumes: &private_resume::Settings,
) -> Result<Value> {
    use sqlx::Connection;
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
        sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            .execute(&mut *tx)
            .await
            .map_err(db)?;
        lock(&mut tx).await?;
        let now = now(&mut tx).await?;
        let mut work = queue::load_in(&mut tx, identity).await?;
        let config = queue_control::configuration(&mut tx).await?;
        if config["state"] != "RUNNING"
            || work["stage"] != "NEEDS_INPUT"
            || work["status"] != "waiting"
            || work["reason"] != "questionnaire_verified_answer_required"
        {
            return Err(Failure("questionnaire_question_context_changed"));
        }
        questionnaire_context::check_in(&mut tx, &mut work, packets, resumes, false, now).await?;
        ask_in(&mut tx, &work, now).await
    }
    .await;
    match result {
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
