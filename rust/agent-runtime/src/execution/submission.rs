//! Ordinary-UI state observations and independent history receipts. No browser/provider calls.
use super::{events, filters, notices, preflight, queue_control, receipts, storage::*};
use crate::{Failure, Result, packet_service, private_resume};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;
pub const PROFILE_URL: &str = "https://www.naukri.com/mnjuser/profile";
pub const HISTORY_URL: &str = "https://www.naukri.com/myapply/historypage";
pub const READS: &[&str] = &[
    "inspect_profile",
    "inspect_application",
    "reconcile_application",
    "verify_account",
];
pub fn receipt_request_hash(receipt: &Value) -> String {
    format!(
        "{:x}",
        Sha256::digest(crate::python_json::serialize(receipt, false, true).as_bytes())
    )
}
pub fn browser_url(work: &Value) -> Result<&str> {
    match work["operation"].as_str() {
        Some("inspect_profile" | "verify_account") => Ok(PROFILE_URL),
        Some("reconcile_application") => Ok(HISTORY_URL),
        _ => work["url"].as_str().ok_or_else(invalid),
    }
}
pub fn account_observation(work: &Value) -> Value {
    let proof = &work["account_observation"];
    if work["binding"].as_object().is_some_and(|o| !o.is_empty())
        && proof["account_sha256"] == work["account_sha256"]
        && proof["binding"] == work["binding"]
        && proof["work_id"] == work["id"]
        && proof["source"] == "profile_ui"
    {
        proof.clone()
    } else {
        Value::Null
    }
}
pub fn descriptor(work: &Value) -> Value {
    json!({"expected_account_sha256":work["account_sha256"],"expected_resume_sha256":work["upload_preflight"]["sha256"],"account_observation":account_observation(work),"expected_title":work["title"],"expected_company":work["company"],"document_id":work["document_id"],"control_sha256":work["control_sha256"],"permit_expires_at":work["permit_expires_at"]})
}
fn retain_account(work: &mut Value, observation: &Value, now: DateTime<Utc>) {
    work["account_observation"] = json!({"source":"profile_ui","work_id":work["id"],"account_sha256":observation["account_sha256"],"profile_document_id":observation["document_id"],"observed_at":stamp(now),"binding":work["binding"]});
}
pub(crate) async fn recover_unknown_in(
    tx: &mut Transaction<'_, Postgres>,
    telegram: bool,
    now: DateTime<Utc>,
) -> Result<()> {
    if queue_control::configuration(tx).await?["state"] != "RUNNING" {
        return Ok(());
    }
    let rows:Vec<(String,Value)>=sqlx::query_as("SELECT key,value FROM owner_preferences WHERE starts_with(key,'apply_work:') AND value->>'platform'='naukri' AND value->>'stage' NOT IN ('SUBMITTED_RECORDED','SUBMITTED_CONFIRMED','FAILED_FINAL','SKIPPED') AND value->>'status'='unknown' ORDER BY created_at,key LIMIT 10001").fetch_all(&mut **tx).await.map_err(db)?;
    if rows.len() > 10000 {
        return Err(Failure("execution_active_inventory_limit"));
    }
    for (key, mut work) in rows {
        if super::read_bounds::exhausted(&work)? {
            if notices::unknown(tx, &mut work, telegram, now).await? {
                put(tx, &key, &work).await?;
            }
            continue;
        }
        if work["account_sha256"].as_str().is_none_or(str::is_empty) {
            continue;
        }
        work["operation"] = json!("reconcile_application");
        work["status"] = json!("queued");
        work["stage"] = json!("SUBMISSION_UNKNOWN");
        work["revision"] = json!(next(&work)?);
        work["lease_token"] = Value::Null;
        work["lease_until"] = Value::Null;
        work["available_at"] = json!(stamp(now + chrono::Duration::seconds(60)));
        put(tx, &key, &work).await?;
        events::queue(tx, &work, "read_only_reconciliation_scheduled", now).await?;
    }
    Ok(())
}
pub(crate) async fn receive_in(
    tx: &mut Transaction<'_, Postgres>,
    work: &mut Value,
    report: &Value,
    packets: &packet_service::Settings,
    resumes: &private_resume::Settings,
    now: DateTime<Utc>,
) -> Result<bool> {
    let operation = work["operation"].as_str().ok_or_else(invalid)?.to_owned();
    super::read_bounds::report(work)?;
    if matches!(report["kind"].as_str(), Some("needs_input" | "failed")) {
        let uncertain = operation == "apply"
            || work["admitted_actions"]
                .as_array()
                .is_some_and(|a| !a.is_empty());
        work["stage"] = json!(if uncertain {
            "SUBMISSION_UNKNOWN"
        } else {
            "BLOCKED_PLATFORM"
        });
        work["status"] = json!(if uncertain { "unknown" } else { "waiting" });
        work["reason"] = report
            .get("reason")
            .filter(|s| s.as_str().is_some_and(|s| !s.is_empty()))
            .cloned()
            .unwrap_or(json!("provider_execution_unconfirmed"));
        return Ok(false);
    }
    let observation = &report["execution"];
    if report["kind"] != "execution_observation" || !observation.is_object() {
        return Err(Failure("execution_observation_required"));
    }
    if report["observed_url"].as_str() != Some(browser_url(work)?) {
        return Err(Failure("queue_document_identity_changed"));
    }
    if report["requisition"] != work["requisition"] {
        return Err(Failure("queue_requisition_changed"));
    }
    if observation["account_sha256"] != work["account_sha256"] {
        return Err(Failure("provider_account_identity_changed"));
    }
    preflight::check_account_in(tx, work).await?;
    if operation == "verify_account" {
        if observation["state"] != "PROFILE_OBSERVED" {
            return Err(Failure("provider_account_profile_observation_required"));
        }
        retain_account(work, observation, now);
        work["operation"] = json!("reconcile_application");
        work["status"] = json!("leased");
        return Ok(true);
    }
    if operation == "inspect_profile" {
        if observation["state"] != "PROFILE_VERIFIED" {
            return Err(Failure("provider_resume_observation_required"));
        }
        let packet_id = work["packet_id"]
            .as_str()
            .and_then(|s| s.parse::<Uuid>().ok())
            .ok_or_else(invalid)?;
        let packet = packet_service::read_locked_in(tx, packet_id, packets, now).await?;
        let checked = preflight::pdf_in(tx, &packet, resumes, now).await?;
        if checked["state"] != "PDF_VERIFIED_LOCAL"
            || observation["resume_sha256"] != checked["sha256"]
            || observation["resume_bytes"] != checked["byte_count"]
        {
            return Err(Failure("provider_saved_resume_differs_from_canonical_pdf"));
        }
        work["facts"]["provider_resume_source"] = json!("profile_download_ui");
        work["facts"]["provider_resume_checked_at"] = json!(stamp(now));
        work["facts"]["provider_resume_sha256"] = checked["sha256"].clone();
        retain_account(work, observation, now);
        work["operation"] = json!("inspect_application");
        work["status"] = json!("leased");
        work["stage"] = json!("READY_TO_APPLY");
        return Ok(true);
    }
    if operation == "inspect_application" {
        if !preflight::account_current(work, now) {
            return Err(Failure("fresh_provider_account_observation_required"));
        }
        if observation["title"] != work["title"] || observation["company"] != work["company"] {
            return Err(Failure("provider_job_or_company_changed"));
        }
        if observation["state"] == "APPLIED" {
            work["stage"] = json!("VERIFYING");
            work["status"] = json!("queued");
            work["operation"] = json!("reconcile_application");
            work["reason"] = json!("already_applied_reconcile_only");
            return Ok(false);
        }
        if observation["state"] != "NOT_APPLIED"
            || observation["control_sha256"]
                .as_str()
                .is_none_or(str::is_empty)
            || !report["job"].is_object()
        {
            return Err(Failure("supported_direct_apply_control_required"));
        }
        let fresh = &report["job"];
        if fresh["requisition"] != work["requisition"]
            || fresh["title"] != work["title"]
            || fresh["company"] != work["company"]
        {
            return Err(Failure("provider_job_or_company_changed"));
        }
        if fresh
            .as_object()
            .ok_or_else(invalid)?
            .iter()
            .any(|(key, value)| {
                !matches!(
                    key.as_str(),
                    "evidence_sha256" | "applicants_min" | "applicants_max"
                ) && work["facts"][key] != *value
            })
        {
            work["stage"] = json!("NEEDS_INPUT");
            work["status"] = json!("waiting");
            work["reason"] = json!("listing_changed_refresh_packet_required");
            return Ok(false);
        }
        for (key, value) in fresh.as_object().ok_or_else(invalid)? {
            work["facts"][key] = value.clone();
        }
        work["facts"]["prior_status"] = json!("NOT_APPLIED");
        work["facts"]["prior_status_checked_at"] = json!(stamp(now));
        let job_id = work["job_id"]
            .as_str()
            .and_then(|s| s.parse::<Uuid>().ok())
            .ok_or_else(invalid)?;
        let job: Value = sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1")
            .bind(job_id)
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?
            .ok_or(Failure("queue_job_identity_changed"))?;
        let config = queue_control::configuration(tx).await?;
        if super::supervised_listing::scoped(&config)
            && !super::supervised_listing::allows_applicants(work)
        {
            super::eligibility::hold(work, "applicant_count_requires_review");
            return Ok(false);
        }
        preflight::eligible_in(tx, work, &config, &job, now).await?;
        work["operation"] = json!("apply");
        work["status"] = json!("leased");
        work["stage"] = json!("READY_TO_APPLY");
        work["document_id"] = observation["document_id"].clone();
        work["control_sha256"] = observation["control_sha256"].clone();
        return Ok(true);
    }
    if operation == "apply" {
        if observation["document_id"] != work["document_id"] {
            return Err(Failure("queue_document_identity_changed"));
        }
        if !matches!(
            observation["state"].as_str(),
            Some("CLICKED" | "QUESTIONNAIRE")
        ) {
            return Err(Failure("apply_action_observation_required"));
        }
        if observation["title"] != work["title"] || observation["company"] != work["company"] {
            return Err(Failure("provider_job_or_company_changed"));
        }
        let admission =
            receipts::apply_admission(work).ok_or(Failure("apply_action_observation_required"))?;
        work["apply_dispatch_observation"] = json!({
            "admission_id":admission["id"],"document_id":observation["document_id"],
            "state":observation["state"],"account_sha256":observation["account_sha256"],
            "profile_binding_id":work["binding"]["profile_binding_id"],
            "evidence_sha256":observation["evidence_sha256"],"observed_at":stamp(now),
        });
        if observation["state"] == "QUESTIONNAIRE" {
            work["stage"] = json!("QUESTIONS");
            work["status"] = json!("queued");
            work["operation"] = json!("inspect_questionnaire");
            work["reason"] = Value::Null;
            work["form_pending"] = json!(true);
            work["form_binding"] = work["binding"].clone();
        } else {
            work["stage"] = json!("VERIFYING");
            work["status"] = json!("queued");
            work["operation"] = json!("reconcile_application");
            work["reason"] = json!("provider_confirmation_pending");
        }
        return Ok(false);
    }
    if operation != "reconcile_application" || observation["state"] != "APPLICATION_SENT" {
        return Err(Failure("persistent_provider_application_status_required"));
    }
    if !preflight::account_current(work, now) {
        return Err(Failure("fresh_provider_account_observation_required"));
    }
    if observation["title"] != work["title"] || observation["company"] != work["company"] {
        return Err(Failure("provider_receipt_identity_changed"));
    }
    if work["confirmation_observation"].is_null() {
        work["confirmation_observation"] = json!({"document_id":observation["document_id"],"evidence_sha256":observation["evidence_sha256"],"observed_at":stamp(now)});
        work["stage"] = json!("VERIFYING");
        work["status"] = json!("queued");
        work["reason"] = json!("provider_history_reload_required");
        return Ok(false);
    }
    if work["confirmation_observation"]["document_id"] == observation["document_id"]
        || timestamp(&work["confirmation_observation"]["observed_at"])? >= now
    {
        return Err(Failure("independent_history_reload_required"));
    }
    confirm_in(tx, work, observation, packets.telegram_notices, now).await?;
    Ok(false)
}

pub(crate) async fn confirm_in(
    tx: &mut Transaction<'_, Postgres>,
    work: &mut Value,
    observation: &Value,
    telegram: bool,
    now: DateTime<Utc>,
) -> Result<()> {
    let requisition = work["requisition"].as_str().ok_or_else(invalid)?;
    let key = format!("naukri_worker_receipt:{requisition}");
    if get(tx, &key).await?.is_some() {
        return Err(Failure("existing_worker_receipt_requires_review"));
    }
    let packet_id = work["packet_id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    let existing_evidence: bool = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM application_submission_evidence WHERE packet_id=$1)",
    )
    .bind(packet_id)
    .fetch_one(&mut **tx)
    .await
    .map_err(db)?;
    let dispatched = !existing_evidence
        && receipts::dispatch_bound(work, &work["confirmation_observation"])
        && work["apply_dispatch_observation"]["document_id"] != observation["document_id"];
    let receipt = json!({"requisition":work["requisition"],"queue_id":work["id"],"account_sha256":work["account_sha256"],"status":"Application Sent","account_observation":account_observation(work),"confirmation_source":"naukri_application_status_ui","operation_mode":"recurring_worker_ui","observed_at":stamp(now),"persistent_after_reload":true,"first_observation":work["confirmation_observation"],"second_observation":observation,"worker_dispatched":dispatched,"apply_dispatch_observation":dispatched.then(|| work["apply_dispatch_observation"].clone())});
    if !receipts::worker_recorded(&key, &receipt, now) {
        return Err(Failure("persistent_provider_application_status_required"));
    }
    // New receipts require actual native document identities; legacy readers remain compatible.
    for doc in [
        &receipt["first_observation"]["document_id"],
        &receipt["second_observation"]["document_id"],
    ] {
        if doc.as_str().is_none_or(|s| {
            !(16..=100).contains(&s.len())
                || !s
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'-'))
        }) {
            return Err(Failure("independent_history_reload_required"));
        }
    }
    preflight::check_account_in(tx, work).await?;
    let job_id = work["job_id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    let packet: Value =
        sqlx::query_scalar("SELECT to_jsonb(p) FROM application_packets p WHERE id=$1 FOR UPDATE")
            .bind(packet_id)
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?
            .ok_or_else(invalid)?;
    if packet["job_id"] != work["job_id"]
        || packet["candidate_profile_id"] != work["candidate_profile_id"]
        || packet["candidate_profile_version"] != work["profile_version"]
    {
        return Err(Failure("queue_packet_context_changed"));
    }
    let job: Value = sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1 FOR UPDATE")
        .bind(job_id)
        .fetch_optional(&mut **tx)
        .await
        .map_err(db)?
        .ok_or_else(invalid)?;
    if job["source_platform"] != "naukri"
        || filters::naukri_url(job["job_url"].as_str().ok_or_else(invalid)?)?
            .rsplit('-')
            .next()
            != Some(requisition)
    {
        return Err(Failure("queue_job_identity_changed"));
    }
    let ack:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value) VALUES($1,$2) ON CONFLICT(key) DO NOTHING RETURNING value").bind(&key).bind(&receipt).fetch_optional(&mut **tx).await.map_err(db)?;
    if ack.as_ref() != Some(&receipt) {
        return Err(Failure("execution_write_ack_failed"));
    }
    let mut metadata = job["discovery_metadata"].clone();
    if metadata.is_null() {
        metadata = json!({});
    }
    if !metadata.is_object() {
        return Err(invalid());
    }
    metadata["already_applied"] = json!(true);
    let ack:Option<(String,Value)>=sqlx::query_as("UPDATE jobs SET status='applied',discovery_metadata=$2,updated_at=clock_timestamp() WHERE id=$1 RETURNING status,discovery_metadata").bind(job_id).bind(&metadata).fetch_optional(&mut **tx).await.map_err(db)?;
    if ack != Some(("applied".into(), metadata)) {
        return Err(Failure("execution_write_ack_failed"));
    }
    if dispatched {
        let revision = next(&packet)?;
        let evidence = Uuid::new_v4();
        let idempotency = format!("naukri-worker-{}", work["id"].as_str().ok_or_else(invalid)?);
        let ack:Option<Uuid>=sqlx::query_scalar("INSERT INTO application_submission_evidence(id,packet_id,packet_revision,confirmation_source,receipt_reference,evidence_confidence,human_confirmed,idempotency_key,request_hash) VALUES($1,$2,$3,'naukri_status_ui',$4,'provider_ui_persistent',false,$5,$6) RETURNING id").bind(evidence).bind(packet_id).bind(revision).bind(&key).bind(idempotency).bind(receipt_request_hash(&receipt)).fetch_optional(&mut **tx).await.map_err(db)?;
        if ack != Some(evidence) {
            return Err(Failure("execution_write_ack_failed"));
        }
        let ack:Option<(i32,String,String,String,Option<i32>)>=sqlx::query_as("UPDATE application_packets SET revision=revision+1,approved_revision=NULL,lifecycle_state='provider_confirmed_submitted',tracking_state='applied_verified',readiness_state='completed_verified',updated_at=clock_timestamp() WHERE id=$1 AND revision=$2 RETURNING revision,lifecycle_state,tracking_state,readiness_state,approved_revision").bind(packet_id).bind(packet["revision"].as_i64().ok_or_else(invalid)?).fetch_optional(&mut **tx).await.map_err(db)?;
        if ack
            != Some((
                i32::try_from(revision).map_err(|_| invalid())?,
                "provider_confirmed_submitted".into(),
                "applied_verified".into(),
                "completed_verified".into(),
                None,
            ))
        {
            return Err(Failure("execution_write_ack_failed"));
        }
        let event = Uuid::new_v4();
        let ack:Option<Uuid>=sqlx::query_scalar("INSERT INTO application_events(id,packet_id,packet_revision,event_type,previous_state,next_state,evidence_id,origin) VALUES($1,$2,$3,'naukri_persistent_ui_confirmed',$4,'provider_confirmed_submitted',$5,'local_worker') RETURNING id").bind(event).bind(packet_id).bind(revision).bind(packet["lifecycle_state"].as_str().ok_or_else(invalid)?).bind(evidence).fetch_optional(&mut **tx).await.map_err(db)?;
        if ack != Some(event) {
            return Err(Failure("execution_write_ack_failed"));
        }
    }
    // Reconciled historical UI evidence cannot assert a worker-dispatched canonical packet.
    work["form_pending"] = json!(false);
    work["stage"] = json!("SUBMITTED_CONFIRMED");
    work["status"] = json!("complete");
    work["operation"] = Value::Null;
    work["reason"] = Value::Null;
    work["receipt_source"] = json!("naukri_application_status_ui");
    work["submission_mode"] = json!(if dispatched {
        "recurring_worker_ui"
    } else {
        "reconciled_provider_history"
    });
    notices::save(tx, work, false, telegram).await?;
    events::queue(tx, work, "provider_submission_confirmed", now).await
}

/// Internal host observer, never a native/owner endpoint on its own. The broker authenticates
/// the browser binding; this entry validates the native DTO and exact durable lease again.
pub async fn observe(
    c: &mut sqlx::PgConnection,
    request: super::admission::Request<'_>,
    report: Value,
    services: super::admission::Services<'_>,
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
        let mut work = super::queue::leased_in(
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
        let continuing = receive_in(
            &mut tx,
            &mut work,
            &report,
            services.packets,
            services.resumes,
            now,
        )
        .await?;
        work["revision"] = json!(next(&work)?);
        work["updated_at"] = json!(stamp(now));
        if !continuing {
            work["lease_token"] = Value::Null;
            work["lease_until"] = Value::Null;
        }
        put(&mut tx, &format!("apply_work:{}", request.identity), &work).await?;
        events::queue(&mut tx, &work, "browser_execution_observed", now).await?;
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
        Err(error) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            Err(error)
        }
    }
}
/// Read-only reconciliation scheduling; spent admissions and uncertainty are retained.
pub async fn recover_unknown(c: &mut sqlx::PgConnection, telegram: bool) -> Result<()> {
    use sqlx::Connection;
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
        lock(&mut tx).await?;
        let now = now(&mut tx).await?;
        recover_unknown_in(&mut tx, telegram, now).await
    }
    .await;
    match result {
        Ok(()) => {
            tx.commit()
                .await
                .map_err(|_| Failure("execution_commit_outcome_unknown"))?;
            Ok(())
        }
        Err(error) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            Err(error)
        }
    }
}
