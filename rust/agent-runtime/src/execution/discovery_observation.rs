//! Bound ordinary listing reports: persist evidence and factual eligibility before preparation.
use super::{
    contracts, eligibility, events, filters, intake, listing_ingestion, preflight, queue,
    queue_control, storage::*,
};
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
fn retry_unattempted(work: &mut Value, reason: &str, now: DateTime<Utc>) -> Result<bool> {
    if work["operation"] != "inspect_job"
        || work["admitted_actions"] != json!([])
        || !work["packet_id"].is_null()
        || work["form_pending"] == true
    {
        return Ok(false);
    }
    let count = work
        .get("transport_retry_count")
        .map(|v| {
            v.as_i64()
                .filter(|n| (0..=3).contains(n))
                .ok_or_else(invalid)
        })
        .transpose()?
        .unwrap_or(0);
    let retry = if reason == "owner_platform_active" {
        true
    } else {
        matches!(
            reason,
            "backend_not_ready" | "backend_timeout" | "backend_transaction_rolled_back"
        ) && count < 3
    };
    if !retry {
        return Ok(false);
    }
    let delay = if reason == "owner_platform_active" {
        60
    } else {
        work["transport_retry_count"] = json!(count + 1);
        60 * (1i64 << count)
    };
    work["stage"] = json!("FAILED_RETRYABLE");
    work["status"] = json!("queued");
    work["reason"] = json!(reason);
    work["available_at"] = json!(stamp(now + chrono::Duration::seconds(delay)));
    Ok(true)
}
pub(crate) async fn receive_in(
    tx: &mut Transaction<'_, Postgres>,
    work: &mut Value,
    report: &Value,
    now: DateTime<Utc>,
) -> Result<()> {
    if matches!(report["kind"].as_str(), Some("needs_input" | "failed")) {
        let reason = report["reason"]
            .as_str()
            .unwrap_or("unsupported_provider_layout");
        if !retry_unattempted(work, reason, now)? {
            work["stage"] = json!("NEEDS_INPUT");
            work["status"] = json!("waiting");
            work["reason"] = json!(reason);
        }
        return Ok(());
    }
    let observed_url = report["observed_url"]
        .as_str()
        .and_then(|s| filters::naukri_url(s).ok());
    if observed_url.as_deref() != work["url"].as_str() {
        return Err(Failure("queue_document_identity_changed"));
    }
    if report["requisition"] != work["requisition"] {
        return Err(Failure("queue_requisition_changed"));
    }
    if report["stage"] == "ALREADY_APPLIED" {
        work["stage"] = json!("SKIPPED");
        work["status"] = json!("complete");
        work["reason"] = json!("provider_already_applied");
        return Ok(());
    }
    if report["kind"] != "job_facts"
        || !report["job"].is_object()
        || report["job"]["requisition"] != work["requisition"]
    {
        return Err(Failure("provider_job_facts_required"));
    }
    let observed = &report["job"];
    work["facts"] = observed.clone();
    for key in ["title", "company", "location"] {
        work[key] = observed[key].clone();
    }
    let config = queue_control::configuration(tx).await?;
    if let Some(reason) = filters::listing_exclusion(
        &work["facts"],
        &contracts::limits(&config["policy"], "naukri")?,
        now,
    )? {
        eligibility::hold(work, reason);
        if reason == "applicant_count_requires_review" {
            super::applicant_notices::required_in(tx, &config["policy"]).await?;
        }
        return Ok(());
    }
    let req = work["requisition"].as_str().ok_or_else(invalid)?.to_owned();
    if intake::protected_in(tx, &[req.clone()])
        .await?
        .contains(&req)
    {
        eligibility::hold(work, "prior_application_or_unknown_submission_no_replay");
        return Ok(());
    }
    let item = listing_ingestion::normalized(work, observed, now)?;
    // Employer/source identity rejection must not leave an orphan company or partial observation.
    let mut savepoint = sqlx::Acquire::begin(&mut *tx).await.map_err(db)?;
    let job = match listing_ingestion::save_in(&mut savepoint, &item).await {
        Ok(job) => {
            savepoint.commit().await.map_err(db)?;
            job
        }
        Err(Failure("job_identity_requires_review")) => {
            savepoint
                .rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            eligibility::hold(work, "job_identity_requires_review");
            return Ok(());
        }
        Err(error) => {
            savepoint
                .rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            return Err(error);
        }
    };
    if super::history::previously_applied_in(tx, &job).await? {
        eligibility::hold(work, "prior_application_or_unknown_submission_no_replay");
        return Ok(());
    }
    work["job_id"] = job["id"].clone();
    match preflight::eligible_in(tx, work, &config["policy"], &job, now).await {
        Ok(profile) => {
            work["stage"] = json!("ELIGIBLE");
            work["operation"] = json!("prepare");
            work["status"] = json!("queued");
            work["reason"] = Value::Null;
            work["profile_version"] = profile["version"].clone();
            events::queue(tx, work, "discovery_eligibility_verified", now).await?;
        }
        Err(error) if super::preparation::preparation_denial(error) => {
            eligibility::hold(work, error.0)
        }
        Err(error) => return Err(error),
    }
    Ok(())
}
/// Internal report transition; future native broker supplies authenticated tab-bound leases.
pub async fn observe(
    c: &mut sqlx::PgConnection,
    request: super::admission::Request<'_>,
    report: Value,
) -> Result<Value> {
    use sqlx::Connection;
    let report = crate::browser_profiles::native_contract::work_report(report)?;
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
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
        if work["status"] != "executing" || work["operation"] != "inspect_job" {
            return Err(Failure("queue_action_not_admitted"));
        }
        let config = queue_control::configuration(&mut tx).await?;
        if config["policy"]["platforms"]["naukri"]["enabled"] != true
            || super::local_policy::preference_in(&mut tx, "naukri").await? == "disabled"
        {
            return Err(Failure("platform_disabled"));
        }
        let execution = contracts::normalize(
            contracts::Kind::Configuration,
            get(&mut tx, "exec_config:naukri")
                .await?
                .unwrap_or(json!({})),
        )
        .map_err(|_| invalid())?;
        if execution["mode"] == "OFF" {
            return Err(Failure("execution_mode_off"));
        }
        receive_in(&mut tx, &mut work, &report, now).await?;
        work["revision"] = json!(next(&work)?);
        work["lease_token"] = Value::Null;
        work["lease_until"] = Value::Null;
        work["updated_at"] = json!(stamp(now));
        put(
            &mut tx,
            &format!("apply_work:{}", work["id"].as_str().ok_or_else(invalid)?),
            &work,
        )
        .await?;
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
