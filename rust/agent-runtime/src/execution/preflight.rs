//! Current factual, account and encrypted-PDF checks. No provider IO or submission authority.
use super::{automatic, eligibility, filters, history, storage::*};
use crate::{Failure, Result, packet_service, private_resume, resources};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use sqlx::{Postgres, Transaction};
use std::sync::LazyLock;
use uuid::Uuid;

pub(crate) async fn profile_in(tx: &mut Transaction<'_, Postgres>, work: &Value) -> Result<Value> {
    // Keep a canonical correction from committing inside an admitted current-fact transaction.
    sqlx::query("SELECT id FROM candidate_profiles WHERE singleton_key='primary' FOR SHARE")
        .execute(&mut **tx)
        .await
        .map_err(db)?;
    let profile = crate::profile_store::get(tx)
        .await
        .map_err(|error| {
            if error.0 == "profile_not_found" {
                Failure("verified_profile_context_changed")
            } else {
                error
            }
        })?
        .value;
    let confirmation = get(tx, "phase1_profile_confirmation")
        .await?
        .unwrap_or(Value::Null);
    if confirmation["profile_id"] != profile["id"]
        || confirmation["profile_version"] != profile["version"]
        || confirmation["confirmed_at"]
            .as_str()
            .is_none_or(str::is_empty)
        || !work["profile_version"].is_null() && profile["version"] != work["profile_version"]
    {
        return Err(Failure("verified_profile_context_changed"));
    }
    Ok(profile)
}
pub(crate) async fn eligible_in(
    tx: &mut Transaction<'_, Postgres>,
    work: &mut Value,
    policy: &Value,
    job: &Value,
    now: DateTime<Utc>,
) -> Result<Value> {
    let profile = profile_in(tx, work).await?;
    let company = if job["company_id"].is_null() {
        None
    } else {
        let id = job["company_id"]
            .as_str()
            .and_then(|s| s.parse::<Uuid>().ok())
            .ok_or_else(invalid)?;
        sqlx::query_scalar("SELECT jsonb_set(to_jsonb(c),'{metadata_}',coalesce(c.metadata,'{}'::jsonb)) FROM companies c WHERE id=$1").bind(id).fetch_optional(&mut **tx).await.map_err(db)?
    };
    eligibility::check(work, policy, job.clone(), company, &profile, now)?;
    Ok(profile)
}
pub(crate) fn account_current(work: &Value, now: DateTime<Utc>) -> bool {
    let proof = &work["account_observation"];
    static DOCUMENT: LazyLock<regex::Regex> = LazyLock::new(|| {
        regex::Regex::new(r"^[A-Za-z0-9_-]{16,100}$").expect("fixed document identity")
    });
    proof.is_object()
        && work["binding"].as_object().is_some_and(|o| !o.is_empty())
        && proof["account_sha256"] == work["account_sha256"]
        && proof["binding"] == work["binding"]
        && proof["work_id"] == work["id"]
        && proof["source"] == "profile_ui"
        && proof["profile_document_id"]
            .as_str()
            .is_some_and(|s| DOCUMENT.is_match(s))
        && timestamp(&proof["observed_at"])
            .is_ok_and(|at| at <= now && now - at <= chrono::Duration::minutes(2))
}
pub(crate) async fn pdf_in(
    tx: &mut Transaction<'_, Postgres>,
    packet: &Value,
    resumes: &private_resume::Settings,
    now: DateTime<Utc>,
) -> Result<Value> {
    let selected = &packet["snapshot"]["resume"]["selected"];
    let mut metadata = json!({"state":"NEEDS_INPUT","reason":"confirmed_primary_resume_required","checked_at":stamp(now),"packet_id":packet["id"],"packet_revision":packet["revision"],"context_digest":packet["snapshot"]["context_digest"],"job_id":packet["job_id"],"candidate_profile_version":packet["candidate_profile_version"],"resource_id":selected["resource_id"],"resource_version":selected["resource_version"],"byte_count":null,"sha256":null,"browser_action_admitted":false,"maximum_bytes":2_000_000,"required_media_type":"application/pdf"});
    let denied = |mut metadata: Value, reason: &str| {
        metadata["reason"] = json!(reason);
        metadata
    };
    if packet["readiness"]["stale"] == true {
        return Ok(denied(metadata, "packet_context_stale"));
    }
    if selected.is_null() || selected["confirmed"] != true {
        return Ok(metadata);
    }
    let owner = packet["candidate_profile_id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    let rows:Vec<Value>=sqlx::query_scalar("SELECT to_jsonb(r) FROM candidate_resources r WHERE candidate_profile_id=$1 ORDER BY id LIMIT 10001").bind(owner).fetch_all(&mut **tx).await.map_err(db)?;
    if rows.len() > 10000 {
        return Err(Failure("execution_active_inventory_limit"));
    }
    let resources = rows
        .into_iter()
        .map(|r| serde_json::from_value::<resources::Resource>(r).map_err(|_| invalid()))
        .collect::<Result<Vec<_>>>()?;
    let current = resources::select_resume(&resources, None)?.selected;
    let Some(current) = current else {
        return Ok(metadata);
    };
    if selected["resource_id"] != current.resource_id.to_string() {
        return Ok(metadata);
    }
    if selected["resource_version"] != current.resource_version {
        return Ok(denied(metadata, "resume_revision_changed"));
    }
    let resource = resources
        .iter()
        .find(|r| r.id == current.resource_id)
        .ok_or_else(invalid)?;
    if resource.source_type != "private_upload" {
        return Ok(denied(metadata, "canonical_private_pdf_required"));
    }
    let raw:Option<(Vec<u8>,String)>=sqlx::query_as("SELECT p.ciphertext,p.sha256 FROM private_resumes p WHERE p.resource_id=$1 AND p.confirmed AND $2='private-resume:'||p.id::text").bind(current.resource_id).bind(&resource.url).fetch_optional(&mut **tx).await.map_err(db)?;
    let Some((ciphertext, digest)) = raw else {
        return Ok(denied(metadata, "canonical_pdf_unavailable_or_invalid"));
    };
    let raw = match resumes.verified(&ciphertext, &digest) {
        Ok(raw) => raw,
        Err(error) => {
            return Ok(denied(
                metadata,
                if error.0 == "resume_encryption_unavailable" {
                    "resume_decryption_key_unavailable"
                } else {
                    "canonical_pdf_unavailable_or_invalid"
                },
            ));
        }
    };
    if raw.len() > 2_000_000 {
        return Ok(denied(metadata, "pdf_exceeds_conservative_naukri_limit"));
    }
    metadata["state"] = json!("PDF_VERIFIED_LOCAL");
    metadata["reason"] = json!("canonical_private_pdf_verified");
    metadata["byte_count"] = json!(raw.len());
    metadata["sha256"] = json!(format!("{:x}", Sha256::digest(raw)));
    Ok(metadata)
}
pub(crate) async fn write_in(
    tx: &mut Transaction<'_, Postgres>,
    work: &mut Value,
    policy: &Value,
    packets: &packet_service::Settings,
    resumes: &private_resume::Settings,
    now: DateTime<Utc>,
) -> Result<(Value, Value)> {
    let job = work["job_id"].as_str().and_then(|s| s.parse::<Uuid>().ok());
    let packet = work["packet_id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok());
    let Some((job_id, packet_id)) = job.zip(packet) else {
        return Err(Failure("prepared_application_required"));
    };
    check_account_in(tx, work).await?;
    // Lock packet material through the established owner-before-packet/context path.
    let packet = packet_service::read_locked_in(tx, packet_id, packets, now).await?;
    let job: Value = sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1")
        .bind(job_id)
        .fetch_optional(&mut **tx)
        .await
        .map_err(db)?
        .ok_or(Failure("prior_application_or_unknown_submission_no_replay"))?;
    if history::previously_applied_in(tx, &job).await? {
        return Err(Failure("prior_application_or_unknown_submission_no_replay"));
    }
    let normalized = filters::naukri_url(job["job_url"].as_str().ok_or_else(invalid)?)?;
    if job["source_platform"] != work["platform"]
        || normalized.rsplit('-').next() != work["requisition"].as_str()
    {
        return Err(Failure("queue_job_identity_changed"));
    }
    let profile = eligible_in(tx, work, policy, &job, now).await?;
    let checked = timestamp(&work["facts"]["prior_status_checked_at"]);
    if checked.is_err()
        || checked.is_ok_and(|at| at > now || now - at > chrono::Duration::minutes(2))
        || work["facts"]["prior_status"] != "NOT_APPLIED"
    {
        return Err(Failure("fresh_provider_application_status_required"));
    }
    if packet["job_id"] != work["job_id"] {
        return Err(Failure("queue_packet_job_mismatch"));
    }
    if packet["candidate_profile_id"] != profile["id"]
        || packet["revision"] != work["packet_revision"]
        || packet["readiness"]["stale"] == true
    {
        return Err(Failure("queue_packet_context_changed"));
    }
    let pdf = pdf_in(tx, &packet, resumes, now).await?;
    if pdf["state"] != "PDF_VERIFIED_LOCAL" {
        return Err(Failure(match pdf["reason"].as_str() {
            Some("packet_context_stale") => "packet_context_stale",
            Some("confirmed_primary_resume_required") => "confirmed_primary_resume_required",
            Some("resume_revision_changed") => "resume_revision_changed",
            Some("canonical_private_pdf_required") => "canonical_private_pdf_required",
            Some("resume_decryption_key_unavailable") => "resume_decryption_key_unavailable",
            Some("pdf_exceeds_conservative_naukri_limit") => {
                "pdf_exceeds_conservative_naukri_limit"
            }
            _ => "canonical_pdf_unavailable_or_invalid",
        }));
    }
    fresh_write(work, &pdf, now)?;
    Ok((packet, pdf))
}

pub(crate) async fn check_account_in(
    tx: &mut Transaction<'_, Postgres>,
    work: &Value,
) -> Result<()> {
    let account = automatic::account(tx).await?;
    if account["candidate_profile_id"] != work["candidate_profile_id"]
        || !work["binding"]["profile_binding_id"].is_null()
            && account["profile_binding_id"] != work["binding"]["profile_binding_id"]
    {
        return Err(Failure("naukri_account_binding_context_changed"));
    }
    if account["revision"] != work["account_binding_revision"]
        || account["account_sha256"] != work["account_sha256"]
    {
        return Err(Failure("naukri_account_binding_changed"));
    }
    Ok(())
}
pub(crate) fn fresh_write(work: &Value, pdf: &Value, now: DateTime<Utc>) -> Result<()> {
    let checked = timestamp(&work["facts"]["prior_status_checked_at"]);
    if checked.is_err()
        || checked.is_ok_and(|at| at > now || now - at > chrono::Duration::minutes(2))
        || work["facts"]["prior_status"] != "NOT_APPLIED"
    {
        return Err(Failure("fresh_provider_application_status_required"));
    }
    if !account_current(work, now) {
        return Err(Failure("fresh_provider_account_observation_required"));
    }
    let checked = timestamp(&work["facts"]["provider_resume_checked_at"]);
    if checked.is_err()
        || checked.is_ok_and(|at| at > now || now - at > chrono::Duration::minutes(2))
        || work["facts"]["provider_resume_sha256"] != pdf["sha256"]
        || work["facts"]["provider_resume_source"] != "profile_download_ui"
    {
        return Err(Failure("fresh_provider_resume_binding_required"));
    }
    Ok(())
}
