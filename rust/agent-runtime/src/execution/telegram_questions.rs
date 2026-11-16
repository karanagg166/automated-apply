//! Owner-bound prompt intents and reply correlation. Ambiguous sends never reenroll automatically.
use super::{legacy_questions, owner_questions, questionnaire_context, storage::*};
use crate::{Failure, Result, configuration::Configuration, packet_service, telegram::Settings};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;
pub(crate) struct Delivery {
    pub identity: Uuid,
    pub attempt: Uuid,
    pub text: String,
    pub binding: String,
}
fn id(value: &Value) -> Result<Uuid> {
    value
        .as_str()
        .and_then(|s| s.parse().ok())
        .ok_or_else(invalid)
}
async fn current_in(
    tx: &mut Transaction<'_, Postgres>,
    question: &Value,
    config: &Configuration,
    now: DateTime<Utc>,
) -> Result<bool> {
    if timestamp(&question["expires_at"])? <= now {
        return Ok(false);
    }
    if !question["queue_work_id"].is_null() {
        let Some(mut work) = owner_questions::current_in(tx, question).await? else {
            return Ok(false);
        };
        return match questionnaire_context::check_in(
            tx,
            &mut work,
            &config.packets,
            &config.resumes,
            false,
            now,
        )
        .await
        {
            Ok(_) => Ok(true),
            Err(error)
                if super::denial(error)
                    || matches!(
                        error.0,
                        "questionnaire_canonical_resume_changed"
                            | "packet_context_stale"
                            | "verified_profile_context_changed"
                    ) =>
            {
                Ok(false)
            }
            Err(error) => Err(error),
        };
    }
    if let Some(task) = question["extension_task_id"].as_str() {
        let value = get(
            tx,
            &format!("ext_task:{}", task.parse::<Uuid>().map_err(|_| invalid())?),
        )
        .await?;
        if value.is_none_or(|v| {
            matches!(
                v["state"].as_str(),
                Some("PAUSED" | "FAILED_FINAL" | "SUBMISSION_UNKNOWN" | "SUBMITTED_CONFIRMED")
            )
        }) {
            return Ok(false);
        }
    }
    let intent = get(tx, &format!("exec:{}", id(&question["execution_id"])?))
        .await?
        .ok_or(Failure("execution_not_found"))?;
    if intent["state"] != "NEEDS_INPUT"
        || intent["cancelled"] == true
        || intent["packet_id"] != question["packet_id"]
    {
        return Ok(false);
    }
    let packet =
        packet_service::read_locked_in(tx, id(&question["packet_id"])?, &config.packets, now)
            .await?;
    Ok(packet["revision"] == question["packet_revision"]
        && packet["candidate_profile_version"] == question["profile_version"]
        && packet["snapshot"]["context_digest"] == question["context_digest"]
        && packet["readiness"]["stale"] != true
        && !matches!(
            packet["lifecycle_state"].as_str(),
            Some(
                "user_reported_submitted"
                    | "provider_confirmed_submitted"
                    | "submitting"
                    | "submission_unknown"
                    | "withdrawn"
                    | "abandoned"
            )
        ))
}
pub(crate) async fn lock_in(tx: &mut Transaction<'_, Postgres>) -> Result<()> {
    lock(tx).await
}
pub(crate) async fn claim(
    c: &mut PgConnection,
    settings: &Settings,
    config: &Configuration,
) -> Result<Option<Delivery>> {
    let hint:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM owner_preferences WHERE starts_with(key,'exec_q:') AND value->>'state'='pending' AND value->>'delivery_error' IS DISTINCT FROM 'telegram_question_too_long_manual_required' AND CASE WHEN pg_input_is_valid(value->>'expires_at','timestamp with time zone') THEN (value->>'expires_at')::timestamptz>clock_timestamp() ELSE true END)").fetch_one(&mut *c).await.map_err(db)?;
    if !hint {
        return Ok(None);
    }
    let mut tx = c.begin().await.map_err(db)?;
    let result=async{
        sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE").execute(&mut *tx).await.map_err(db)?;lock(&mut tx).await?;crate::telegram::bound(&mut tx,settings).await?;let now=now(&mut tx).await?;
        let rows:Vec<Value>=sqlx::query_scalar("SELECT value FROM owner_preferences WHERE starts_with(key,'exec_q:') AND value->>'state'='pending' AND value->>'delivery_error' IS DISTINCT FROM 'telegram_question_too_long_manual_required' AND CASE WHEN pg_input_is_valid(value->>'expires_at','timestamp with time zone') THEN (value->>'expires_at')::timestamptz>clock_timestamp() ELSE true END ORDER BY created_at,key LIMIT 10001").fetch_all(&mut *tx).await.map_err(db)?;
        if rows.len()>10000{return Err(Failure("execution_active_inventory_limit"));}
        for mut question in rows{
            if timestamp(&question["expires_at"])?<=now||!question["delivery_lease"].is_null()&&timestamp(&question["delivery_lease"])? > now{continue;}
            if !current_in(&mut tx,&question,config,now).await?{continue;}
            let text=if question["queue_work_id"].is_null(){crate::browser_profiles::owner_question_message(&question)?}else{owner_questions::message_text(&question)?};
            if text.encode_utf16().count()>4000{question["delivery_error"]=json!("telegram_question_too_long_manual_required");put(&mut tx,&format!("exec_q:{}",id(&question["id"])?),&question).await?;continue;}
            let identity=id(&question["id"])?;let attempt=Uuid::new_v4();question["state"]=json!("delivery_unknown");question["delivery_lease"]=json!(stamp(now+chrono::Duration::seconds(60)));question["delivery_binding"]=json!(settings.binding());question["delivery_attempt"]=json!(attempt);put(&mut tx,&format!("exec_q:{identity}"),&question).await?;
            return Ok(Some(Delivery{identity,attempt,text,binding:settings.binding()}));
        }Ok(None)
    }.await;
    match result {
        Ok(value) => {
            tx.commit()
                .await
                .map_err(|_| Failure("execution_commit_outcome_unknown"))?;
            Ok(value)
        }
        Err(error) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            Err(error)
        }
    }
}
pub(crate) async fn finish(
    c: &mut PgConnection,
    settings: &Settings,
    delivery: &Delivery,
    message_id: i64,
) -> Result<()> {
    if message_id <= 0 || delivery.binding != settings.binding() {
        return Err(Failure("telegram_delivery_fence_lost"));
    }
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
        sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            .execute(&mut *tx)
            .await
            .map_err(db)?;
        lock(&mut tx).await?;
        crate::telegram::bound(&mut tx, settings).await?;
        let key = format!("exec_q:{}", delivery.identity);
        let mut question = get(&mut tx, &key)
            .await?
            .ok_or(Failure("question_not_found"))?;
        if question["delivery_attempt"] != delivery.attempt.to_string()
            || question["delivery_binding"] != delivery.binding
        {
            return Err(Failure("telegram_delivery_fence_lost"));
        }
        let mut ids = question["message_ids"]
            .as_array()
            .ok_or_else(invalid)?
            .clone();
        if !ids.iter().any(|id| id.as_i64() == Some(message_id)) {
            if ids.len() >= 50 {
                return Err(Failure("execution_active_inventory_limit"));
            }
            ids.push(json!(message_id));
        }
        question["message_ids"] = json!(ids);
        question["delivery_lease"] = Value::Null;
        if matches!(
            question["state"].as_str(),
            Some("pending" | "delivery_unknown")
        ) {
            question["state"] = json!("sent");
        }
        put(&mut tx, &key, &question).await
    }
    .await;
    match result {
        Ok(()) => tx
            .commit()
            .await
            .map_err(|_| Failure("execution_commit_outcome_unknown")),
        Err(error) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            Err(error)
        }
    }
}
pub(crate) async fn receive_in(
    tx: &mut Transaction<'_, Postgres>,
    settings: &Settings,
    config: &Configuration,
    message: &Value,
    update: i64,
    now: DateTime<Utc>,
) -> Result<Option<String>> {
    if !settings.authorized(message) {
        return Err(Failure("telegram_owner_required"));
    }
    let Some(reply) = message["reply_to_message"]["message_id"]
        .as_i64()
        .filter(|n| *n > 0)
    else {
        return Ok(None);
    };
    let rows:Vec<Value>=sqlx::query_scalar("SELECT value FROM owner_preferences WHERE starts_with(key,'exec_q:') AND (value->'message_ids' @> $1::jsonb OR value->'expired_message_ids' @> $1::jsonb) ORDER BY created_at,key LIMIT 2").bind(json!([reply])).fetch_all(&mut **tx).await.map_err(db)?;
    if rows.len() > 1 {
        return Ok(Some("Several saved questions reference that message. Answer the exact application question in the dashboard.".into()));
    }
    let Some(question) = rows.first() else {
        return Ok(None);
    };
    if question["message_ids"]
        .as_array()
        .is_none_or(|ids| !ids.iter().any(|id| id.as_i64() == Some(reply)))
    {
        return Ok(Some(
            "This question expired. Reply to the latest question message to reconfirm.".into(),
        ));
    }
    if question["delivery_binding"] != settings.binding() {
        return Ok(Some("This older prompt has no verified current delivery binding. Review and answer its application question in the dashboard.".into()));
    }
    if question["state"] == "answered" {
        return Ok(Some(
            "This question was already answered. Review its saved application before changing it."
                .into(),
        ));
    }
    if !current_in(tx, question, config, now).await? {
        return Ok(Some(
            "Application context changed or paused. Review the current question in the dashboard."
                .into(),
        ));
    }
    let answer = message["text"]
        .as_str()
        .unwrap_or("")
        .trim_matches(crate::context_contract::python_space);
    if answer.is_empty() || answer.chars().count() > 4000 {
        return Ok(Some("Answer rejected: answer_length_invalid".into()));
    }
    let data = json!({"expected_revision":question["packet_revision"],"answer":answer});
    let origin = json!({"channel":"telegram","source":"owner_telegram","owner_user_id":settings.owner_user(),"update_id":update,"reply_message_id":reply});
    let services = legacy_questions::Services {
        packets: &config.packets,
        answers: &config.answers,
        resumes: &config.resumes,
    };
    let mut savepoint = sqlx::Connection::begin(&mut **tx).await.map_err(db)?;
    match legacy_questions::answer_origin_in(
        &mut savepoint,
        id(&question["id"])?,
        &data,
        services,
        now,
        &origin,
    )
    .await
    {
        Ok(_) => {
            savepoint.commit().await.map_err(db)?;
            Ok(Some("Answer saved for this application. Reuse is OFF. Fresh account, resume, listing and form review is required before continuing.".into()))
        }
        Err(error) => {
            savepoint
                .rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            if super::denial(error)
                || matches!(
                    error.0,
                    "packet_context_stale"
                        | "packet_closed"
                        | "packet_context_changed"
                        | "packet_answer_invalid"
                )
            {
                Ok(Some(format!(
                    "Answer rejected: {}. Review the current application in the dashboard.",
                    error.0
                )))
            } else {
                Err(error)
            }
        }
    }
}
