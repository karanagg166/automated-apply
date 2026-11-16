//! Local factual preparation of an already committed legacy claim. No browser/provider IO.
use super::{
    events, history, legacy_policy, legacy_questions,
    legacy_work::{self, Claim},
    owner_routes, preflight, review,
    storage::*,
};
use crate::{
    Failure, Result, configuration::Configuration, job_context::Reviewed, packet_contract::Prepare,
    packet_execution::Binding, packet_notice, packet_service,
};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;
fn id(value: &Value) -> Result<Uuid> {
    value
        .as_str()
        .and_then(|s| s.parse().ok())
        .ok_or_else(invalid)
}
fn waiting(field: &Value, now: DateTime<Utc>) -> Result<bool> {
    if field["field_type"] == "file" {
        return Ok(false);
    }
    Ok(
        field["required"] == true && field["effective_answer"].as_str().is_none_or(str::is_empty)
            || !field["provenance"]["answer_expires_at"].is_null()
                && timestamp(&field["provenance"]["answer_expires_at"])? <= now,
    )
}
pub(super) async fn questions_in(
    tx: &mut Transaction<'_, Postgres>,
    intent: &mut Value,
    packet: &Value,
    policy: Option<&Value>,
    config: &Configuration,
    now: DateTime<Utc>,
) -> Result<()> {
    if policy.is_none_or(|p| p["telegram_questions"] != true)
        || intent["state"] != "NEEDS_INPUT"
        || packet["readiness"]["stale"] == true
    {
        return Ok(());
    }
    let services = legacy_questions::Services {
        packets: &config.packets,
        answers: &config.answers,
        resumes: &config.resumes,
    };
    for field in packet["fields"].as_array().ok_or_else(invalid)? {
        if !waiting(field, now)? {
            continue;
        }
        let mut savepoint = sqlx::Connection::begin(&mut **tx).await.map_err(db)?;
        match legacy_questions::ask_in(
            &mut savepoint,
            id(&intent["id"])?,
            id(&field["id"])?,
            services,
            now,
        )
        .await
        {
            Ok(_) => savepoint.commit().await.map_err(db)?,
            Err(error) => {
                savepoint
                    .rollback()
                    .await
                    .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
                if super::denial(error)
                    || matches!(error.0, "missing_input_limit" | "packet_context_stale")
                {
                    intent["diagnostic"] = json!("manual_question_required");
                    legacy_work::save_in(tx, intent).await?;
                } else {
                    return Err(error);
                }
            }
        }
    }
    Ok(())
}
async fn prepare_in(
    tx: &mut Transaction<'_, Postgres>,
    claim: Claim,
    config: &Configuration,
    now: DateTime<Utc>,
) -> Result<()> {
    let mut intent = legacy_work::fenced_in(tx, claim, now).await?;
    let job: Option<Value> =
        sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1 FOR SHARE")
            .bind(id(&intent["job_id"])?)
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?;
    sqlx::query("SELECT id FROM candidate_profiles WHERE singleton_key='primary' FOR SHARE")
        .execute(&mut **tx)
        .await
        .map_err(db)?;
    let profile = match crate::profile_store::get(tx).await {
        Ok(p) => Some(p.value),
        Err(Failure("profile_not_found")) => None,
        Err(error) => return Err(error),
    };
    let Some((job, profile)) = job.zip(profile) else {
        intent["state"] = json!("NEEDS_INPUT");
        intent["diagnostic"] = json!("candidate_or_job_missing");
        intent["lease_until"] = Value::Null;
        intent["revision"] = json!(next(&intent)?);
        legacy_work::save_in(tx, &intent).await?;
        return events::legacy(tx, &intent, "candidate_or_job_missing", now).await;
    };
    let company = if job["company_id"].is_null() {
        None
    } else {
        sqlx::query_scalar("SELECT jsonb_set(to_jsonb(c),'{metadata_}',coalesce(c.metadata,'{}'::jsonb)) FROM companies c WHERE id=$1").bind(id(&job["company_id"])?).fetch_optional(&mut **tx).await.map_err(db)?
    };
    let reviewed = Reviewed::new(job.clone(), company.clone())?;
    intent["role"] = reviewed.job_view()["title"].clone();
    intent["employer"] = reviewed
        .employer()
        .map(|c| c["name"].clone())
        .unwrap_or(Value::Null);
    intent["employer_id"] = reviewed.job_view()["company_id"].clone();
    let policy = match legacy_policy::execution_in(tx, &intent, now).await {
        Ok(Some(_)) => Some(legacy_policy::record(tx).await?["policy"].clone()),
        Ok(None) => None,
        Err(error) if super::denial(error) => {
            legacy_work::save_in(tx, &intent).await?;
            let mut paused = owner_routes::intent_control_in(
                tx,
                claim.id,
                &json!({"action":"pause","expected_revision":intent["revision"]}),
                now,
            )
            .await?;
            paused["diagnostic"] = json!(error.0);
            return legacy_work::save_in(tx, &paused).await;
        }
        Err(error) => return Err(error),
    };
    if history::previously_applied_in(tx, &job).await? {
        intent["state"] = json!("REJECTED");
        intent["revision"] = json!(next(&intent)?);
        intent["diagnostic"] = json!("previous_application_or_unknown_submission");
        intent["lease_until"] = Value::Null;
        legacy_work::save_in(tx, &intent).await?;
        return events::legacy(tx, &intent, "prior_application_excluded", now).await;
    }
    if intent["state"] == "DISCOVERED" {
        legacy_work::move_in(tx, &mut intent, "MATCHED", None, now).await?;
    }
    if intent["state"] == "MATCHED" {
        let decision =
            review::decision_with_history(job, company, Some(&profile), true, false, false, now)?;
        let fit: automated_apply_domain::matching::DiscoveryMatch =
            serde_json::from_value(decision["match"].clone())
                .map_err(|_| Failure("invalid_requisition_identity"))?;
        let (state, reason) =
            review::preparation_eligibility(reviewed.job_view(), &profile, &fit, now)?;
        intent["profile_version"] = profile["version"].clone();
        intent["match"] = json!(fit);
        legacy_work::move_in(tx, &mut intent, state, Some(reason), now).await?;
    }
    if matches!(
        intent["state"].as_str(),
        Some("ELIGIBLE" | "FAILED_RETRYABLE")
    ) {
        legacy_work::move_in(tx, &mut intent, "PREPARING", None, now).await?;
    }
    let mut packet = Value::Null;
    if intent["state"] == "PREPARING" {
        let existing = if !intent["packet_id"].is_null() {
            Some(id(&intent["packet_id"])?)
        } else {
            sqlx::query_scalar(
                "SELECT id FROM application_packets WHERE job_id=$1 AND candidate_profile_id=$2",
            )
            .bind(id(&intent["job_id"])?)
            .bind(id(&profile["id"])?)
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?
        };
        packet = if let Some(existing) = existing {
            packet_service::read_locked_in(tx, existing, &config.packets, now).await?
        } else {
            packet_service::create_locked_in(
                tx,
                id(&intent["job_id"])?,
                &Prepare {
                    resume_resource_id: None,
                    questions: vec![],
                    idempotency_key: Some(format!("exec_{}", claim.id)),
                },
                &config.packets,
                &config.answers,
                now,
            )
            .await?
        };
        intent["packet_id"] = packet["id"].clone();
        intent["profile_version"] = packet["candidate_profile_version"].clone();
        let mut pdf = preflight::pdf_in(tx, &packet, &config.resumes, now).await?;
        let policy_resume_changed = policy.as_ref().is_some_and(|p| {
            packet["snapshot"]["resume"]["selected"]["resource_id"] != p["resume_resource_id"]
                || packet["snapshot"]["resume"]["selected"]["resource_version"]
                    != p["resume_version"]
        });
        if policy_resume_changed {
            pdf["state"] = json!("NEEDS_INPUT");
            pdf["reason"] = json!("policy_resume_binding_changed");
            pdf["byte_count"] = Value::Null;
            pdf["sha256"] = Value::Null;
        }
        intent["upload_preflight"] = pdf;
        if packet["readiness"]["stale"] == true || policy_resume_changed {
            legacy_work::move_in(
                tx,
                &mut intent,
                "NEEDS_INPUT",
                Some("stale_packet_or_unapproved_resume"),
                now,
            )
            .await?;
            intent["lease_until"] = Value::Null;
            return legacy_work::save_in(tx, &intent).await;
        }
        let state = if matches!(
            packet["readiness"]["state"].as_str(),
            Some("needs_input" | "needs_resume" | "needs_profile")
        ) {
            "NEEDS_INPUT"
        } else {
            "READY_FOR_REVIEW"
        };
        legacy_work::move_in(
            tx,
            &mut intent,
            state,
            packet["readiness"]["state"].as_str(),
            now,
        )
        .await?;
    }
    // The committed claim must still be current and unexpired at publication.
    let published_at = super::storage::now(tx).await?;
    if intent["fence"] != claim.fence || timestamp(&intent["lease_until"])? <= published_at {
        return Err(Failure("execution_lease_lost"));
    }
    intent["lease_until"] = Value::Null;
    intent["attempts"] = json!(0);
    legacy_work::save_in(tx, &intent).await?;
    if !packet.is_null() {
        questions_in(tx, &mut intent, &packet, policy.as_ref(), config, now).await?;
        if intent["state"] == "READY_FOR_REVIEW" {
            packet_notice::notify_in(
                tx,
                Some(&Binding {
                    key: format!("exec:{}", claim.id),
                    value: intent,
                }),
                &packet,
                config.packets.telegram_notices,
            )
            .await?;
        }
    }
    Ok(())
}
pub async fn prepare(c: &mut PgConnection, claim: Claim, config: &Configuration) -> Result<()> {
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
        sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            .execute(&mut *tx)
            .await
            .map_err(db)?;
        lock(&mut tx).await?;
        let at = now(&mut tx).await?;
        prepare_in(&mut tx, claim, config, at).await
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
