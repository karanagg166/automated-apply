//! Approved saved-source intake and local factual preparation. No provider/model/browser IO.
use super::{
    automatic, eligibility, events, filters, history, preflight, queue, queue_control, storage::*,
};
use crate::{Failure, Result, answer_service, packet_contract, packet_service, private_resume};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;
pub struct Services<'a> {
    pub packets: &'a packet_service::Settings,
    pub answers: &'a answer_service::Settings,
    pub resumes: &'a private_resume::Settings,
}
fn ready(config: &Value) -> bool {
    config["state"] == "RUNNING" && config["policy"]["platforms"]["naukri"]["enabled"] == true
}
fn preparation_denial(error: Failure) -> bool {
    matches!(
        error.0,
        "prior_application_or_unknown_submission_no_replay"
            | "verified_profile_context_changed"
            | "vacancy_closed_expired_or_invalid"
            | "advertised_experience_outside_platform_preferences"
            | "salary_comparison_requires_review"
            | "advertised_salary_outside_platform_preferences"
            | "verified_experience_requirements_required"
            | "required_experience_outside_verified_band"
            | "posting_outside_age_limit"
            | "posting_age_requires_review"
            | "posting_timestamp_unknown"
            | "applicant_limit_reached"
            | "applicant_count_unknown_skip"
            | "applicant_count_requires_review"
            | "current_profile_preferences_or_required_skills_exclude_job"
            | "minimum_match_score_required"
            | "uncertain_job_requirements_require_review"
            | "packet_context_stale"
            | "confirmed_primary_resume_required"
            | "resume_revision_changed"
            | "canonical_private_pdf_required"
            | "resume_decryption_key_unavailable"
            | "pdf_exceeds_conservative_naukri_limit"
            | "canonical_pdf_unavailable_or_invalid"
            | "packet_factual_input_required"
            | "approved_naukri_account_binding_required"
            | "naukri_account_binding_context_changed"
    )
}
fn pdf_denial(pdf: &Value) -> Failure {
    Failure(match pdf["reason"].as_str() {
        Some("packet_context_stale") => "packet_context_stale",
        Some("confirmed_primary_resume_required") => "confirmed_primary_resume_required",
        Some("resume_revision_changed") => "resume_revision_changed",
        Some("canonical_private_pdf_required") => "canonical_private_pdf_required",
        Some("resume_decryption_key_unavailable") => "resume_decryption_key_unavailable",
        Some("pdf_exceeds_conservative_naukri_limit") => "pdf_exceeds_conservative_naukri_limit",
        _ => "canonical_pdf_unavailable_or_invalid",
    })
}
pub(crate) async fn prepare_in(
    tx: &mut Transaction<'_, Postgres>,
    services: Services<'_>,
    now: DateTime<Utc>,
) -> Result<bool> {
    let config = queue_control::configuration(tx).await?;
    if !ready(&config) {
        return Ok(false);
    }
    let setting = &config["policy"]["platforms"]["naukri"];
    let automatic = matches!(setting["mode"].as_str(), Some("AUTOMATIC" | "SUPERVISED"))
        && setting["owner_submission_authorized"] == true;
    if automatic {
        let waiting:Option<(String,Value)>=sqlx::query_as("SELECT key,value FROM owner_preferences WHERE starts_with(key,'apply_work:') AND value->>'platform'='naukri' AND value->>'stage'='READY_TO_APPLY' AND value->>'status'='waiting' AND value->'admitted_actions'='[]'::jsonb ORDER BY created_at,key LIMIT 1").fetch_optional(&mut **tx).await.map_err(db)?;
        if let Some((key, mut work)) = waiting {
            work["operation"] = json!("prepare");
            work["status"] = json!("queued");
            work["reason"] = Value::Null;
            work["revision"] = json!(next(&work)?);
            put(tx, &key, &work).await?;
            events::queue(tx, &work, "standing_policy_requires_fresh_preparation", now).await?;
        }
    }
    let Some(mut work) = queue::claim_in(
        tx,
        "naukri",
        &json!({"worker":"local_preparation"}),
        Some(&["prepare"]),
        now,
    )
    .await?
    else {
        return Ok(false);
    };
    let result=async {
        let job_id=work["job_id"].as_str().and_then(|s|s.parse::<Uuid>().ok()).ok_or(Failure("prior_application_or_unknown_submission_no_replay"))?;
        let job:Value=sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1").bind(job_id).fetch_optional(&mut **tx).await.map_err(db)?.ok_or(Failure("prior_application_or_unknown_submission_no_replay"))?;
        if history::previously_applied_in(tx,&job).await?{return Err(Failure("prior_application_or_unknown_submission_no_replay"));}
        let profile=preflight::eligible_in(tx,&mut work,&config["policy"],&job,now).await?;
        work["stage"]=json!("ELIGIBLE");work["profile_version"]=profile["version"].clone();work["revision"]=json!(next(&work)?);events::queue(tx,&work,"eligibility_verified",now).await?;
        work["stage"]=json!("PREPARING");work["revision"]=json!(next(&work)?);events::queue(tx,&work,"preparing",now).await?;
        let candidate=profile["id"].as_str().and_then(|s|s.parse::<Uuid>().ok()).ok_or_else(invalid)?;
        let existing:Option<Uuid>=sqlx::query_scalar("SELECT id FROM application_packets WHERE job_id=$1 AND candidate_profile_id=$2").bind(job_id).bind(candidate).fetch_optional(&mut **tx).await.map_err(db)?;
        let packet=if let Some(id)=existing {packet_service::read_locked_in(tx,id,services.packets,now).await?}else{let request=packet_contract::normalize(json!({"idempotency_key":format!("queue_{}",work["id"].as_str().ok_or_else(invalid)?)}),true)?;packet_service::create_locked_in(tx,job_id,&request,services.packets,services.answers,now).await?};
        let checked=preflight::pdf_in(tx,&packet,services.resumes,now).await?;work["packet_id"]=packet["id"].clone();work["packet_revision"]=packet["revision"].clone();work["upload_preflight"]=checked.clone();if checked["state"]!="PDF_VERIFIED_LOCAL"{return Err(pdf_denial(&checked));}
        if matches!(packet["readiness"]["state"].as_str(),Some("needs_input"|"needs_resume"|"needs_profile")){return Err(Failure("packet_factual_input_required"));}
        let account=automatic::account(tx).await?;if account["candidate_profile_id"]!=profile["id"]{return Err(Failure("naukri_account_binding_context_changed"));}
        work["stage"]=json!("READY_TO_APPLY");work["reason"]=if automatic{Value::Null}else{json!("automatic_submission_scope_required")};work["status"]=json!(if automatic{"queued"}else{"waiting"});work["operation"]=json!("inspect_profile");work["candidate_profile_id"]=profile["id"].clone();work["account_binding_revision"]=account["revision"].clone();work["account_sha256"]=account["account_sha256"].clone();Ok(())
    }.await;
    match result {
        Ok(()) => {}
        Err(error) if preparation_denial(error) => eligibility::hold(&mut work, error.0),
        Err(error) => return Err(error),
    }
    let now = super::storage::now(tx).await?;
    work["lease_token"] = Value::Null;
    work["lease_until"] = Value::Null;
    work["updated_at"] = json!(stamp(now));
    work["revision"] = json!(next(&work)?);
    put(
        tx,
        &format!("apply_work:{}", work["id"].as_str().ok_or_else(invalid)?),
        &work,
    )
    .await?;
    events::queue(tx, &work, "preparation_finished", now).await?;
    Ok(true)
}
/// Idle preparation does not acquire the owner lock. The hint grants no authority;
/// all mutable policy and claims are reread after the lock before local work starts.
pub async fn prepare_one(c: &mut PgConnection, services: Services<'_>) -> Result<bool> {
    let hint:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM owner_preferences WHERE starts_with(key,'apply_work:') AND value->>'platform'='naukri' AND value->>'stage' NOT IN ('SUBMITTED_RECORDED','SUBMITTED_CONFIRMED','FAILED_FINAL','SKIPPED') AND ((value->>'operation'='prepare' AND value->>'status'='queued') OR (value->>'stage'='READY_TO_APPLY' AND value->>'status'='waiting' AND value->'admitted_actions'='[]'::jsonb) OR (value->>'status' IN ('leased','executing') AND CASE WHEN pg_input_is_valid(value->>'lease_until','timestamp with time zone') THEN (value->>'lease_until')::timestamptz<=clock_timestamp() ELSE true END)))").fetch_one(&mut *c).await.map_err(db)?;
    if !hint {
        return Ok(false);
    }
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
        lock(&mut tx).await?;
        let now = now(&mut tx).await?;
        prepare_in(&mut tx, services, now).await
    }
    .await;
    match result {
        Ok(done) => {
            tx.commit()
                .await
                .map_err(|_| Failure("execution_commit_outcome_unknown"))?;
            Ok(done)
        }
        Err(error) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            Err(error)
        }
    }
}

pub(crate) async fn seed_in(tx: &mut Transaction<'_, Postgres>, now: DateTime<Utc>) -> Result<u64> {
    let config = queue_control::configuration(tx).await?;
    if !ready(&config) {
        return Ok(0);
    }
    let sources = config["policy"]["platforms"]["naukri"]["sources"]
        .as_array()
        .ok_or_else(invalid)?;
    let mut added = 0;
    for source in ["approved_gmail_alerts", "saved_verified_job"] {
        if !sources.iter().any(|s| s == source) {
            continue;
        }
        let cursor_key = format!("apply_source:{source}");
        let cursor = get(tx, &cursor_key).await?;
        let after = cursor
            .as_ref()
            .map(|c| timestamp(&c["updated_at"]))
            .transpose()?;
        let identity = cursor
            .as_ref()
            .map(|c| c["id"].as_str().ok_or_else(invalid))
            .transpose()?;
        if source == "saved_verified_job" && identity.is_some_and(|s| s.parse::<Uuid>().is_err()) {
            return Err(invalid());
        }
        // Only the fixed projection is loaded: never alert contents, resume bytes or raw mailbox data.
        let records: Vec<Value> = if source == "approved_gmail_alerts" {
            sqlx::query_scalar("SELECT jsonb_build_object('id',key,'url',value->'url','permitted',value->>'source'='gmail_job_alerts' AND value->>'account_id'='local:1','updated_at',updated_at) FROM owner_preferences WHERE starts_with(key,'nau_alert:') AND ($1::timestamptz IS NULL OR updated_at>$1 OR (updated_at=$1 AND key>$2)) ORDER BY updated_at,key LIMIT 10").bind(after).bind(identity).fetch_all(&mut **tx).await.map_err(db)?
        } else {
            sqlx::query_scalar("SELECT jsonb_build_object('id',id,'url',job_url,'permitted',true,'updated_at',updated_at) FROM jobs WHERE source_platform='naukri' AND ($1::timestamptz IS NULL OR updated_at>$1 OR (updated_at=$1 AND id>$2::uuid)) ORDER BY updated_at,id LIMIT 10").bind(after).bind(identity).fetch_all(&mut **tx).await.map_err(db)?
        };
        for record in records {
            let id = record["id"].as_str().ok_or_else(invalid)?;
            if record["permitted"] == true
                && let Some(url) = record["url"].as_str()
            {
                match filters::naukri_url(url) {
                    Ok(normalized) => {
                        let requisition = normalized.rsplit('-').next().ok_or_else(invalid)?;
                        let work_id = Uuid::new_v5(
                            &Uuid::NAMESPACE_URL,
                            format!("naukri:{requisition}").as_bytes(),
                        );
                        let before = get(tx, &format!("apply_work:{work_id}")).await?.is_some();
                        match queue::enqueue_in(tx, &normalized, source, Some(id), now).await {
                            Ok(_) => added += u64::from(!before),
                            Err(Failure("queue_backpressure")) => return Ok(added),
                            Err(Failure(
                                "prior_receipt_requires_reconciliation_no_replay"
                                | "prior_application_or_unknown_submission_no_replay",
                            )) => {}
                            Err(error) => return Err(error),
                        }
                    }
                    Err(Failure(
                        "public_https_job_url_required"
                        | "naukri_job_url_required"
                        | "naukri_posting_path_required",
                    )) => {}
                    Err(error) => return Err(error),
                }
            }
            // Unsupported or already-applied input stays in its original source; only the cursor advances.
            put(
                tx,
                &cursor_key,
                &json!({"updated_at":record["updated_at"],"id":id}),
            )
            .await?;
        }
    }
    Ok(added)
}
/// Consume at most ten records per enabled saved source. Owner/queue state is reread
/// after the common lock; this source never queries a mailbox or a remote portal.
pub async fn seed_saved_sources(c: &mut PgConnection) -> Result<u64> {
    let hint: Option<Value> = sqlx::query_scalar(
        "SELECT value FROM owner_preferences WHERE key='application_queue_policy'",
    )
    .fetch_optional(&mut *c)
    .await
    .map_err(db)?;
    if !hint.as_ref().is_some_and(ready) {
        return Ok(0);
    }
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
        lock(&mut tx).await?;
        let now = now(&mut tx).await?;
        seed_in(&mut tx, now).await
    }
    .await;
    match result {
        Ok(count) => {
            tx.commit()
                .await
                .map_err(|_| Failure("execution_commit_outcome_unknown"))?;
            Ok(count)
        }
        Err(error) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            Err(error)
        }
    }
}
