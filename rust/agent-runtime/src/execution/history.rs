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
pub(crate) async fn previously_applied_in(
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
