//! One durable admission before IO. Commit loss is unknown; no browser action is replayed.
use super::{
    automatic, budgets,
    contracts::{self, Kind},
    events, filters, history, preflight, questionnaire_context, queue, queue_control,
    storage::*,
};
use crate::{Failure, Result, packet_service, private_resume};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;

pub struct Request<'a> {
    pub identity: Uuid,
    pub revision: i64,
    pub token: Uuid,
    pub binding: &'a Value,
}
pub struct Services<'a> {
    pub packets: &'a packet_service::Settings,
    pub resumes: &'a private_resume::Settings,
}
pub(crate) async fn admit_in(
    tx: &mut Transaction<'_, Postgres>,
    request: Request<'_>,
    services: Services<'_>,
) -> Result<Value> {
    let initial_now = now(tx).await?;
    let mut work = queue::leased_in(
        tx,
        request.identity,
        request.revision,
        request.token,
        request.binding,
        initial_now,
    )
    .await?;
    let execution = contracts::normalize(
        Kind::Configuration,
        get(tx, "exec_config:naukri").await?.unwrap_or(json!({})),
    )
    .map_err(|_| invalid())?;
    if execution["mode"] == "OFF" {
        return Err(Failure("execution_mode_off"));
    }
    if work["status"] != "leased" {
        return Err(Failure("queue_action_already_admitted"));
    }
    let config = queue_control::configuration(tx).await?;
    let policy = &config["policy"];
    let platform = work["platform"]
        .as_str()
        .filter(|s| *s == "naukri")
        .ok_or_else(invalid)?;
    let setting = &policy["platforms"][platform];
    let preference = super::local_policy::preference_in(tx, platform).await?;
    if preference == "disabled" || setting["enabled"] != true {
        return Err(Failure("platform_disabled"));
    }
    let operation = work["operation"].as_str().ok_or_else(invalid)?.to_owned();
    let writing = filters::WRITES.contains(&operation.as_str());
    super::read_bounds::admit(&mut work)?;
    let mut initial_packet = None;
    if writing {
        if matches!(preference, "manual_only" | "draft_only") {
            return Err(Failure("platform_policy_requires_manual_review"));
        }
        if setting["owner_submission_authorized"] != true || setting["mode"] == "PREPARE_ONLY" {
            return Err(Failure("standing_submission_scope_required"));
        }
        automatic::require_policy(tx, policy, initial_now).await?;
        if history::receipt_exists_in(tx, work["requisition"].as_str().ok_or_else(invalid)?).await?
        {
            return Err(Failure("prior_receipt_requires_reconciliation_no_replay"));
        }
        let step = work
            .get("step_fingerprint")
            .cloned()
            .unwrap_or(json!("initial"));
        let step = step
            .as_str()
            .filter(|s| !s.is_empty())
            .ok_or_else(invalid)?;
        let fingerprint = format!("{operation}:{step}");
        let actions = work["admitted_actions"].as_array().ok_or_else(invalid)?;
        if actions.iter().any(|a| a["fingerprint"] == fingerprint) {
            return Err(Failure("queue_action_replay_forbidden"));
        }
        if operation == "apply"
            && actions.iter().any(|a| {
                a["fingerprint"]
                    .as_str()
                    .is_some_and(|s| s.starts_with("apply:"))
            })
        {
            return Err(Failure("queue_apply_replay_forbidden"));
        }
        let checked_at = now(tx).await?;
        let pdf = if operation == "answer_questionnaire" {
            questionnaire_context::check_in(
                tx,
                &mut work,
                services.packets,
                services.resumes,
                true,
                checked_at,
            )
            .await?;
            if work["step_fingerprint"] != work["questionnaire"]["step_sha256"]
                || work["questionnaire_answer"]
                    .as_object()
                    .is_none_or(|o| o.is_empty())
            {
                return Err(Failure("questionnaire_reviewed_step_required"));
            }
            None
        } else {
            let (packet, pdf) = preflight::write_in(
                tx,
                &mut work,
                policy,
                services.packets,
                services.resumes,
                checked_at,
            )
            .await?;
            initial_packet = Some(packet);
            Some(pdf)
        };
        let quota_at = now(tx).await?;
        budgets::reserve_in(tx, &work, policy, quota_at).await?;
        // Time is rechecked after proof/history/locking costs, before saving any admission.
        let at = now(tx).await?;
        queue::leased_in(
            tx,
            request.identity,
            request.revision,
            request.token,
            request.binding,
            at,
        )
        .await?;
        if let Some(pdf) = pdf {
            preflight::fresh_write(&work, &pdf, at)?;
        } else {
            questionnaire_context::fresh(&work, at)?;
        }
        work["admitted_actions"]
            .as_array_mut()
            .ok_or_else(invalid)?
            .push(json!({"id":Uuid::new_v4(),"fingerprint":fingerprint,"at":stamp(at)}));
        if operation == "answer_questionnaire" {
            let mut saved = work
                .get("questionnaire_answers")
                .cloned()
                .unwrap_or(json!([]));
            saved.as_array_mut().ok_or_else(invalid)?.push(json!({"step":work["questionnaire"],"answer":work["questionnaire_answer"],"packet_revision":work["packet_revision"],"profile_version":work["profile_version"],"admitted_at":stamp(at),"state":"admitted_not_a_receipt"}));
            work["questionnaire_answers"] = saved;
        }
        if operation == "apply" {
            let packet = initial_packet.ok_or_else(invalid)?;
            let revision = next(&packet)?;
            work["packet_revision"] = json!(revision);
            work["status"] = json!("executing");
            work["revision"] = json!(next(&work)?);
            // The existing schema trigger reads this exact admission before permitting submitting.
            put(tx, &format!("apply_work:{}", request.identity), &work).await?;
            let changed:Option<(i32,String,Option<i32>)>=sqlx::query_as("UPDATE application_packets SET lifecycle_state='submitting',revision=revision+1,approved_revision=NULL,updated_at=clock_timestamp() WHERE id=$1 AND revision=$2 RETURNING revision,lifecycle_state,approved_revision").bind(packet["id"].as_str().and_then(|s|s.parse::<Uuid>().ok()).ok_or_else(invalid)?).bind(packet["revision"].as_i64().ok_or_else(invalid)?).fetch_optional(&mut **tx).await.map_err(db)?;
            if changed
                != Some((
                    i32::try_from(revision).map_err(|_| invalid())?,
                    "submitting".into(),
                    None,
                ))
            {
                return Err(Failure("execution_write_ack_failed"));
            }
            let event = Uuid::new_v4();
            let ack:Option<Uuid>=sqlx::query_scalar("INSERT INTO application_events(id,packet_id,packet_revision,event_type,previous_state,next_state,origin) VALUES($1,$2,$3,'naukri_apply_admitted',$4,'submitting','local_worker') RETURNING id").bind(event).bind(packet["id"].as_str().and_then(|s|s.parse::<Uuid>().ok()).ok_or_else(invalid)?).bind(revision).bind(packet["lifecycle_state"].as_str().ok_or_else(invalid)?).fetch_optional(&mut **tx).await.map_err(db)?;
            if ack != Some(event) {
                return Err(Failure("execution_write_ack_failed"));
            }
        }
    }
    if work["status"] != "executing" {
        let at = now(tx).await?;
        queue::leased_in(
            tx,
            request.identity,
            request.revision,
            request.token,
            request.binding,
            at,
        )
        .await?;
        work["status"] = json!("executing");
        work["revision"] = json!(next(&work)?);
    }
    let at = now(tx).await?;
    put(tx, &format!("apply_work:{}", request.identity), &work).await?;
    events::queue(tx, &work, "admitted", at).await?;
    Ok(work)
}
/// Host-internal only. The native broker must first authenticate and pin the current profile binding.
pub async fn admit(
    c: &mut PgConnection,
    request: Request<'_>,
    services: Services<'_>,
) -> Result<Value> {
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
        sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            .execute(&mut *tx)
            .await
            .map_err(db)?;
        lock(&mut tx).await?;
        admit_in(&mut tx, request, services).await
    }
    .await;
    match result {
        Ok(work) => {
            tx.commit()
                .await
                .map_err(|_| Failure("execution_commit_outcome_unknown"))?;
            Ok(work)
        }
        Err(error) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            Err(error)
        }
    }
}
