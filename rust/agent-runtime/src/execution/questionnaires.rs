//! Transactional original-form reports. Scope/PDF/account checks precede every transition.
use super::{events, questionnaire_context, questionnaire_steps as steps, queue, storage::*};
use crate::{Failure, Result, packet_service, private_resume};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
pub(crate) async fn receive_in(
    tx: &mut Transaction<'_, Postgres>,
    work: &mut Value,
    report: &Value,
    packets: &packet_service::Settings,
    resumes: &private_resume::Settings,
    now: DateTime<Utc>,
) -> Result<bool> {
    questionnaire_context::check_in(tx, work, packets, resumes, false, now).await?;
    let refresh = work["operation"] == "refresh_questionnaire_job"
        && report["stage"] != "ALREADY_APPLIED"
        && !matches!(report["kind"].as_str(), Some("needs_input" | "failed"));
    steps::transition(work, report, now)?;
    if refresh {
        questionnaire_context::check_in(tx, work, packets, resumes, false, now).await?;
    }
    Ok(work["status"] == "leased"
        && work["operation"]
            .as_str()
            .is_some_and(|s| steps::OPERATIONS.contains(&s)))
}
pub async fn observe(
    c: &mut sqlx::PgConnection,
    request: super::admission::Request<'_>,
    report: Value,
    packets: &packet_service::Settings,
    resumes: &private_resume::Settings,
) -> Result<Value> {
    use sqlx::Connection;
    let report = crate::browser_profiles::native_contract::work_report(report)?;
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
        sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            .execute(&mut *tx)
            .await
            .map_err(db)?;
        lock(&mut tx).await?;
        let now = now(&mut tx).await?;
        let mut work = queue::leased_in(
            &mut tx,
            request.identity,
            request.revision,
            request.token,
            request.binding,
            now,
        )
        .await?;
        if work["status"] != "executing" {
            return Err(Failure("queue_action_not_admitted"));
        }
        let continuing = receive_in(&mut tx, &mut work, &report, packets, resumes, now).await?;
        work["revision"] = json!(next(&work)?);
        work["updated_at"] = json!(stamp(now));
        if !continuing {
            work["lease_token"] = Value::Null;
            work["lease_until"] = Value::Null;
        }
        put(
            &mut tx,
            &format!("apply_work:{}", work["id"].as_str().ok_or_else(invalid)?),
            &work,
        )
        .await?;
        events::queue(&mut tx, &work, "questionnaire_browser_observed", now).await?;
        Ok(work)
    }
    .await;
    match result {
        Ok(work) => {
            tx.commit()
                .await
                .map_err(|_| Failure("execution_commit_outcome_unknown"))?;
            Ok(work)
        }
        Err(e) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            Err(e)
        }
    }
}
