//! Existence blocks replay even when retained receipt bytes are damaged or unconfirmed.
use super::{filters, storage::*};
use crate::{Failure, Result};
use serde_json::Value;
use sqlx::{Postgres, Transaction};
use uuid::Uuid;
pub(crate) async fn receipt_exists_in(
    tx: &mut Transaction<'_, Postgres>,
    requisition: &str,
) -> Result<bool> {
    sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM owner_preferences WHERE key IN ($1,$2))")
        .bind(format!("naukri_receipt:{requisition}"))
        .bind(format!("naukri_worker_receipt:{requisition}"))
        .fetch_one(&mut **tx)
        .await
        .map_err(db)
}
pub(crate) async fn provider_applied_in(
    tx: &mut Transaction<'_, Postgres>,
    job: &Value,
) -> Result<bool> {
    if job["source_platform"] == "naukri"
        && job["discovery_metadata"]["data_provenance"]["posting_status"] == "already_applied"
        || matches!(
            job["application_status"].as_str(),
            Some(
                "applied"
                    | "submitted"
                    | "interview"
                    | "offer"
                    | "applied_manually"
                    | "applied_verified"
            )
        )
        || matches!(job["status"].as_str(), Some("applied" | "submitted"))
    {
        return Ok(true);
    }
    let id = job["id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    let packet:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM application_packets WHERE job_id=$1 AND lifecycle_state IN ('user_reported_submitted','provider_confirmed_submitted','submitting','submission_unknown'))").bind(id).fetch_one(&mut **tx).await.map_err(db)?;
    if packet {
        return Ok(true);
    }
    if job["source_platform"] != "naukri" {
        return Ok(false);
    }
    let url = filters::naukri_url(
        job["job_url"]
            .as_str()
            .ok_or(Failure("naukri_job_url_required"))?,
    )?;
    let requisition = url.rsplit('-').next().ok_or_else(invalid)?;
    if receipt_exists_in(tx, requisition).await? {
        return Ok(true);
    }
    let urls:Vec<String>=sqlx::query_scalar("SELECT DISTINCT j.job_url FROM jobs j JOIN application_packets p ON p.job_id=j.id WHERE j.source_platform='naukri' AND p.lifecycle_state IN ('user_reported_submitted','provider_confirmed_submitted','submitting','submission_unknown') AND j.job_url ~ $1").bind(format!("-{requisition}/?([?#].*)?$")).fetch_all(&mut **tx).await.map_err(db)?;
    Ok(urls.iter().any(|raw| {
        filters::naukri_url(raw)
            .ok()
            .is_some_and(|u| u.rsplit('-').next() == Some(requisition))
    }))
}

pub(crate) async fn previously_applied_in(
    tx: &mut Transaction<'_, Postgres>,
    job: &Value,
) -> Result<bool> {
    if provider_applied_in(tx, job).await? {
        return Ok(true);
    }
    let retained_mail:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM owner_preferences WHERE starts_with(key,'gmail_application:'))").fetch_one(&mut **tx).await.map_err(db)?;
    if retained_mail {
        let at = now(tx).await?;
        let history = super::reviewed_history::load_in(tx, at).await?;
        if !history.is_empty() {
            let company = if job["company_id"].is_null() {
                None
            } else {
                let id = job["company_id"]
                    .as_str()
                    .and_then(|s| s.parse::<Uuid>().ok())
                    .ok_or_else(invalid)?;
                sqlx::query_scalar("SELECT jsonb_set(to_jsonb(c),'{metadata_}',coalesce(c.metadata,'{}'::jsonb)) FROM companies c WHERE id=$1").bind(id).fetch_optional(&mut **tx).await.map_err(db)?
            };
            let reviewed = crate::job_context::Reviewed::new(job.clone(), company)?;
            if super::reviewed_history::previously_applied(
                reviewed.job_view(),
                reviewed.employer(),
                &history,
            ) {
                return Ok(true);
            }
        }
    }
    Ok(false)
}
