//! Local operator control for one supervised Naukri listing that shows 100+ applicants.
use super::{
    automatic, broker, budgets, contracts, events, filters, history, intake, preflight, queue,
    queue_control, storage::*,
};
use crate::{Failure, Result, browser_inventory::Browser, configuration::Configuration};
use chrono::{DateTime, Duration, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, Postgres, Transaction};
use std::{borrow::Cow, path::Path};
use uuid::Uuid;

const SCOPE: &str = "supervised_100_plus";

pub(super) fn scoped(config: &Value) -> bool {
    config.get(SCOPE).is_some()
}

pub(super) fn work_key(config: &Value) -> Result<Option<String>> {
    if !scoped(config) {
        return Ok(None);
    }
    let id = saved_uuid(&config[SCOPE]["work_id"])?;
    Ok(Some(format!("apply_work:{id}")))
}

pub(super) fn clear(config: &mut Value) -> Result<()> {
    config.as_object_mut().ok_or_else(invalid)?.remove(SCOPE);
    Ok(())
}

pub(super) fn permits_work(config: &Value, work: &Value, at: DateTime<Utc>) -> bool {
    !scoped(config)
        || (config["state"] == "RUNNING"
            && config["policy"]["platforms"]["naukri"]["mode"] == "SUPERVISED"
            && work["platform"] == "naukri"
            && work["id"].is_string()
            && work["id"] == config[SCOPE]["work_id"]
            && timestamp(&config[SCOPE]["expires_at"]).is_ok_and(|expires| at < expires))
}

pub(super) fn allows_applicants(work: &Value) -> bool {
    work["facts"]["applicants_min"] == 100 && work["facts"]["applicants_max"].is_null()
}

pub(super) fn require_write(config: &Value, work: &Value, at: DateTime<Utc>) -> Result<()> {
    if scoped(config) && !(permits_work(config, work, at) && allows_applicants(work)) {
        return Err(Failure("supervised_listing_scope_mismatch"));
    }
    Ok(())
}

pub(super) fn policy_for_work<'a>(
    config: &'a Value,
    work: &Value,
    at: DateTime<Utc>,
) -> Result<Cow<'a, Value>> {
    let policy = &config["policy"];
    if !scoped(config) || !permits_work(config, work, at) || !allows_applicants(work) {
        return Ok(Cow::Borrowed(policy));
    }
    let limits = contracts::limits(policy, "naukri")?;
    if limits["applicant_limit"] != 1000 || limits["unknown_applicants"] != "needs_review" {
        return Err(Failure("supervised_listing_applicant_rule_changed"));
    }
    let mut policy = policy.clone();
    let setting = &mut policy["platforms"]["naukri"];
    setting["applicants_mode"] = json!("custom");
    setting["limits"]["applicant_limit"] = limits["applicant_limit"].clone();
    setting["limits"]["unknown_applicants"] = json!("allow_lower_bound");
    Ok(Cow::Owned(policy))
}

pub async fn start(config: &Path, revision: i64, listing: &str) -> Result<()> {
    run(config, revision, Request::Start(listing)).await
}

pub async fn resume(config: &Path, revision: i64, work_id: Uuid, work_revision: i64) -> Result<()> {
    run(config, revision, Request::Resume(work_id, work_revision)).await
}

enum Request<'a> {
    Start(&'a str),
    Resume(Uuid, i64),
}

async fn run(config: &Path, revision: i64, request: Request<'_>) -> Result<()> {
    let config = Configuration::load(config)?;
    if config.browser != Browser::Brave
        || !config.browser_profiles.native_enabled
        || !config.browser_profiles.commands_enabled
    {
        return Err(Failure("brave_native_runtime_required"));
    }
    let mut connection = config.connect(false).await?;
    crate::server::readiness(&mut connection, &config).await?;
    let mut tx = connection.begin().await.map_err(db)?;
    lock(&mut tx).await?;
    let saved = match request {
        Request::Start(listing) => start_in(&mut tx, revision, listing).await,
        Request::Resume(id, work_revision) => {
            resume_in(&mut tx, &config, revision, id, work_revision).await
        }
    };
    let result = match saved {
        Ok(saved) => {
            tx.commit()
                .await
                .map_err(|_| Failure("execution_commit_outcome_unknown"))?;
            saved
        }
        Err(error) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            return Err(error);
        }
    };
    println!("{result}");
    Ok(())
}

async fn stopped_context(
    tx: &mut Transaction<'_, Postgres>,
    revision: i64,
    at: DateTime<Utc>,
) -> Result<(Value, Value)> {
    let config = queue_control::configuration(tx).await?;
    if config["revision"] != revision {
        return Err(Failure("queue_policy_revision_conflict"));
    }
    let setting = &config["policy"]["platforms"]["naukri"];
    let limits = contracts::limits(&config["policy"], "naukri")?;
    if scoped(&config)
        || config["state"] != "STOPPED"
        || setting["mode"] != "SUPERVISED"
        || setting["enabled"] != true
        || setting["owner_submission_authorized"] != true
        || setting["hourly_submission_cap"] != 1
        || limits["applicant_limit"] != 1000
        || limits["unknown_applicants"] != "needs_review"
        || config["policy"]["platforms"]
            .as_object()
            .ok_or_else(invalid)?
            .iter()
            .any(|(name, policy)| name != "naukri" && policy["enabled"] == true)
        || crate::lifecycle::control(tx).await?.mode != crate::lifecycle::Mode::Stopped
        || get(tx, "naukri_automation")
            .await?
            .is_some_and(|legacy| legacy["state"] != "STOPPED")
    {
        return Err(Failure("stopped_supervised_listing_policy_required"));
    }
    queue_control::require_start(tx, &config, at).await?;
    let totals = budgets::totals_in(tx, "naukri", at).await?;
    let cap = setting["supervised_submission_cap"]
        .as_i64()
        .ok_or_else(invalid)?;
    if totals["lifetime_apply"] != cap - 1 || totals["hourly_work"] != 0 {
        return Err(Failure("one_supervised_listing_allowance_required"));
    }

    let account = automatic::account(tx).await?;
    let selection = get(tx, "chr_selection").await?.unwrap_or(Value::Null);
    let pin = get(tx, "chr_fixed_profile").await?.unwrap_or(Value::Null);
    let binding = selection["profile_binding_id"]
        .as_str()
        .ok_or_else(invalid)?;
    let profile = get(tx, &format!("chr_prof:{binding}"))
        .await?
        .unwrap_or(Value::Null);
    if account["profile_binding_id"] != binding
        || pin["profile_binding_id"] != binding
        || pin["browser"] != "brave"
        || pin["verified_via"] != "owner_reviewed_dedicated_brave_profile"
        || profile["id"] != binding
        || profile["commands_enabled"] != true
        || crate::browser_profiles::public(&profile, &json!(binding), at)?["status"] != "CONNECTED"
    {
        return Err(Failure("current_supervised_brave_binding_required"));
    }

    Ok((config, account))
}

async fn start_in(
    tx: &mut Transaction<'_, Postgres>,
    revision: i64,
    listing: &str,
) -> Result<Value> {
    let at = now(tx).await?;
    let (config, account) = stopped_context(tx, revision, at).await?;
    let setting = &config["policy"]["platforms"]["naukri"];
    let url = filters::naukri_url(listing)?;
    let requisition = url.rsplit('-').next().ok_or_else(invalid)?;
    if intake::protected_in(tx, &[requisition.to_owned()])
        .await?
        .contains(requisition)
    {
        return Err(Failure("prior_application_or_unknown_submission_no_replay"));
    }
    let mut work = queue::enqueue_in(tx, &url, "naukri_ui_search", None, at).await?;
    if work["url"] != url
        || !matches!(
            work["stage"].as_str(),
            Some("DISCOVERED" | "NEEDS_INPUT" | "PAUSED")
        )
        || !matches!(work["status"].as_str(), Some("waiting" | "queued"))
        || work["admitted_actions"] != json!([])
        || !work["packet_id"].is_null()
        || !work["lease_until"].is_null()
        || work["form_pending"] == true
        || !setting["sources"]
            .as_array()
            .ok_or_else(invalid)?
            .contains(&work["source"])
    {
        return Err(Failure("untouched_supervised_listing_required"));
    }
    let current_profile = preflight::profile_in(tx, &work).await?;
    if current_profile["id"] != account["candidate_profile_id"] {
        return Err(Failure("naukri_account_binding_context_changed"));
    }
    work["stage"] = json!("DISCOVERED");
    work["operation"] = json!("inspect_job");
    work["profile_version"] = Value::Null;
    let config = opened(config, &work["id"], now(tx).await?)?;
    save(tx, config, work, "supervised_100_plus_listing_started", at).await
}

fn saved_uuid(value: &Value) -> Result<Uuid> {
    value
        .as_str()
        .and_then(|s| s.parse().ok())
        .ok_or_else(invalid)
}

fn interrupted_pre_apply_read(work: &Value, at: DateTime<Utc>) -> bool {
    let paused = &work["paused_context"];
    let operation = work["operation"].as_str();
    let lease_interrupted = matches!(
        paused["status"].as_str(),
        Some("queued" | "leased" | "executing")
    ) && (paused["stage"] == "READY_TO_APPLY"
        || paused["stage"] == "FAILED_RETRYABLE" && paused["reason"] == "lease_expired");
    let read_blocked = paused["status"] == "waiting"
        && paused["stage"] == "BLOCKED_PLATFORM"
        && (paused["reason"] == "backend_timeout"
            || operation == Some("inspect_application")
                && (paused["reason"] == "backend_not_ready"
                    || paused["reason"] == "provider_account_identity_unverified"
                        && work["account_observation"].is_object()
                        && !preflight::account_current(work, at)));
    work["stage"] == "PAUSED"
        && work["status"] == "waiting"
        && work["reason"] == "global_stop"
        && matches!(operation, Some("inspect_profile" | "inspect_application"))
        && paused["operation"] == work["operation"]
        && (lease_interrupted || read_blocked)
}

fn has_write_evidence(work: &Value) -> bool {
    work["admitted_actions"] != json!([])
        || !matches!(work.get("form_pending"), None | Some(Value::Bool(false)))
        || !work["questionnaire_answers"].is_null() && work["questionnaire_answers"] != json!([])
        || !work["questionnaire_steps"].is_null() && work["questionnaire_steps"] != 0
        || [
            "form_binding",
            "form_loss_observation",
            "questionnaire",
            "questionnaire_answer",
            "questionnaire_document_id",
            "questionnaire_completion_observation",
            "apply_dispatch_observation",
            "confirmation_observation",
            "receipt_source",
            "submission_mode",
            "permit_expires_at",
        ]
        .iter()
        .any(|field| !work[*field].is_null())
}

fn require_fresh_profile_read(work: &mut Value) {
    work["operation"] = json!("inspect_profile");
    for field in [
        "binding",
        "account_observation",
        "document_id",
        "control_sha256",
    ] {
        work[field] = Value::Null;
    }
    for field in [
        "prior_status",
        "prior_status_checked_at",
        "provider_resume_checked_at",
        "provider_resume_sha256",
        "provider_resume_source",
    ] {
        work["facts"][field] = Value::Null;
    }
}

fn is_unadmitted_scoped_read(config: &Value, work: &Value, at: DateTime<Utc>) -> bool {
    scoped(config)
        && permits_work(config, work, at)
        && matches!(
            work["stage"].as_str(),
            Some("READY_TO_APPLY" | "FAILED_RETRYABLE")
        )
        && work["packet_id"].is_string()
        && work["facts"].is_object()
        && !has_write_evidence(work)
}

pub(super) fn rewind_expired_application_read(config: &Value, work: &mut Value, at: DateTime<Utc>) {
    if work["operation"] == "inspect_application" && is_unadmitted_scoped_read(config, work, at) {
        // A new lease owns a different tab. The old account and résumé proof
        // cannot follow it, even if their timestamps would still be fresh.
        require_fresh_profile_read(work);
    }
}

pub(super) fn retry_pre_apply_transport(
    config: &Value,
    work: &mut Value,
    report: &Value,
    at: DateTime<Utc>,
) -> bool {
    let marker = match (
        work["operation"].as_str(),
        work["status"].as_str(),
        report["reason"].as_str(),
    ) {
        (Some("inspect_profile"), Some("executing"), Some("backend_timeout")) => {
            "supervised_profile_transport_retry_used"
        }
        (
            Some("inspect_application"),
            Some("leased" | "executing"),
            Some("backend_timeout" | "backend_not_ready"),
        ) => "supervised_application_read_retry_used",
        _ => return false,
    };
    if !is_unadmitted_scoped_read(config, work, at) || work.get(marker).is_some() {
        return false;
    }
    // An acknowledged abandon still owns the exact old lease. Successful
    // finish would have changed its revision, so no result can be replayed.
    require_fresh_profile_read(work);
    work[marker] = json!(true);
    work["stage"] = json!("FAILED_RETRYABLE");
    work["status"] = json!("queued");
    work["reason"] = report["reason"].clone();
    true
}

async fn require_unadmitted_history(
    tx: &mut Transaction<'_, Postgres>,
    work_id: Uuid,
    requisition: &str,
    job: &Value,
) -> Result<()> {
    let reserved: bool = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM owner_preferences
          WHERE starts_with(key,'apply_budget:naukri:')
          AND (jsonb_typeof(value->'reservations') IS DISTINCT FROM 'array'
               OR (value->'reservations') ? $1))",
    )
    .bind(work_id.to_string())
    .fetch_one(&mut **tx)
    .await
    .map_err(db)?;
    let prior_work: bool = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM owner_preferences
          WHERE starts_with(key,'apply_work:') AND key<>$1
          AND (value->>'requisition'=$2 OR value->>'url' ~ $3))",
    )
    .bind(format!("apply_work:{work_id}"))
    .bind(requisition)
    .bind(format!("-{requisition}/?([?#].*)?$"))
    .fetch_one(&mut **tx)
    .await
    .map_err(db)?;
    let prior_submission: bool = sqlx::query_scalar(
        "SELECT EXISTS(
           SELECT 1 FROM application_packets p JOIN jobs j ON j.id=p.job_id
           WHERE j.source_platform='naukri' AND j.job_url ~ $1
             AND (EXISTS(SELECT 1 FROM application_events e WHERE e.packet_id=p.id
                         AND e.event_type IN ('naukri_apply_admitted',
                             'naukri_persistent_ui_confirmed','user_reported_submission'))
                  OR EXISTS(SELECT 1 FROM application_submission_evidence s WHERE s.packet_id=p.id))
         ) OR EXISTS(
           SELECT 1 FROM owner_preferences o JOIN jobs j ON j.id::text=o.value->>'job_id'
           WHERE starts_with(o.key,'exec:') AND j.source_platform='naukri' AND j.job_url ~ $1
             AND (o.value->>'state' IN ('SUBMITTING','SUBMISSION_UNKNOWN','SUBMITTED_CONFIRMED')
                  OR o.value->>'paused_state' IN ('SUBMITTING','SUBMISSION_UNKNOWN','SUBMITTED_CONFIRMED'))
         ) OR EXISTS(
           SELECT 1 FROM owner_preferences o
             JOIN application_packets p ON p.id::text=o.value->>'application_id'
             JOIN jobs j ON j.id=p.job_id
           WHERE starts_with(o.key,'ext_task:') AND j.source_platform='naukri' AND j.job_url ~ $1
             AND (o.value->>'state' IN ('FORM_INSPECTED','ANSWERS_REVIEWED','FILL_AUTHORIZED',
                                      'FILLING','SUBMISSION_UNKNOWN','SUBMITTED_CONFIRMED')
                  OR o.value->'verified_receipts' NOT IN ('[]'::jsonb,'null'::jsonb))
         )",
    )
    .bind(format!("-{requisition}/?([?#].*)?$"))
    .fetch_one(&mut **tx)
    .await
    .map_err(db)?;
    if reserved
        || prior_work
        || prior_submission
        || intake::protected_in(tx, &[requisition.to_owned()])
            .await?
            .contains(requisition)
        || history::previously_applied_in(tx, job).await?
    {
        return Err(Failure("prior_application_or_unknown_submission_no_replay"));
    }
    Ok(())
}

async fn resume_in(
    tx: &mut Transaction<'_, Postgres>,
    runtime: &Configuration,
    queue_revision: i64,
    work_id: Uuid,
    work_revision: i64,
) -> Result<Value> {
    let at = now(tx).await?;
    let (config, account) = stopped_context(tx, queue_revision, at).await?;
    let mut work = queue::load_in(tx, work_id).await?;
    if revision(&work)? != work_revision {
        return Err(Failure("queue_work_revision_conflict"));
    }
    if !interrupted_pre_apply_read(&work, at)
        || work["platform"] != "naukri"
        || !work["lease_token"].is_null()
        || !work["lease_until"].is_null()
        || has_write_evidence(&work)
        || !allows_applicants(&work)
        || !config["policy"]["platforms"]["naukri"]["sources"]
            .as_array()
            .ok_or_else(invalid)?
            .contains(&work["source"])
    {
        return Err(Failure("interrupted_prepared_supervised_listing_required"));
    }
    if broker::busy_in(tx, at).await? {
        return Err(Failure("naukri_browser_lane_busy"));
    }
    let url = filters::naukri_url(work["url"].as_str().ok_or_else(invalid)?)?;
    let req = url.rsplit('-').next().ok_or_else(invalid)?;
    if work["url"] != url
        || work["requisition"] != req
        || work_id != Uuid::new_v5(&Uuid::NAMESPACE_URL, format!("naukri:{req}").as_bytes())
    {
        return Err(Failure("queue_job_identity_changed"));
    }
    preflight::check_account_in(tx, &work).await?;
    let packet_id = saved_uuid(&work["packet_id"])?;
    let job_id = saved_uuid(&work["job_id"])?;
    let packet = crate::packet_service::read_locked_in(tx, packet_id, &runtime.packets, at).await?;
    let job: Value = sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1")
        .bind(job_id)
        .fetch_optional(&mut **tx)
        .await
        .map_err(db)?
        .ok_or(Failure("queue_job_identity_changed"))?;
    if job["source_platform"] != "naukri"
        || filters::naukri_url(job["job_url"].as_str().ok_or_else(invalid)?)? != url
    {
        return Err(Failure("queue_job_identity_changed"));
    }
    require_unadmitted_history(tx, work_id, req, &job).await?;
    if packet["id"] != work["packet_id"]
        || packet["job_id"] != work["job_id"]
        || packet["platform"] != work["platform"]
        || packet["revision"] != work["packet_revision"]
        || packet["candidate_profile_id"] != account["candidate_profile_id"]
        || packet["candidate_profile_version"] != work["profile_version"]
        || packet["lifecycle_state"] != "created"
        || packet["tracking_state"] != "not_applied"
        || packet["readiness"]["stale"] != false
        || matches!(
            packet["readiness"]["state"].as_str(),
            Some("needs_input" | "needs_resume" | "needs_profile")
        )
    {
        return Err(Failure("queue_packet_context_changed"));
    }
    let pdf = preflight::pdf_in(tx, &packet, &runtime.resumes, at).await?;
    if pdf["state"] != "PDF_VERIFIED_LOCAL" {
        return Err(Failure("canonical_pdf_unavailable_or_invalid"));
    }
    let at = now(tx).await?;
    let config = opened(config, &work["id"], at)?;
    let profile = preflight::eligible_in(tx, &mut work, &config, &job, at).await?;
    if profile["id"] != packet["candidate_profile_id"]
        || profile["version"] != packet["candidate_profile_version"]
    {
        return Err(Failure("verified_profile_context_changed"));
    }
    work["stage"] = json!("READY_TO_APPLY");
    work["upload_preflight"] = pdf;
    require_fresh_profile_read(&mut work);
    save(
        tx,
        config,
        work,
        "supervised_100_plus_prepared_listing_resumed",
        at,
    )
    .await
}

fn opened(mut config: Value, work_id: &Value, at: DateTime<Utc>) -> Result<Value> {
    config["revision"] = json!(next(&config)?);
    config["state"] = json!("RUNNING");
    config[SCOPE] = json!({"work_id":work_id,"expires_at":stamp(at + Duration::minutes(15))});
    Ok(config)
}

async fn save(
    tx: &mut Transaction<'_, Postgres>,
    config: Value,
    mut work: Value,
    event: &str,
    at: DateTime<Utc>,
) -> Result<Value> {
    work["revision"] = json!(next(&work)?);
    work["policy_revision"] = config["revision"].clone();
    work["status"] = json!("queued");
    work["available_at"] = json!(stamp(at));
    work["updated_at"] = json!(stamp(at));
    work["reason"] = Value::Null;
    let work_id = work["id"].as_str().ok_or_else(invalid)?;
    put(tx, "application_queue_policy", &config).await?;
    put(tx, &format!("apply_work:{work_id}"), &work).await?;
    events::queue(tx, &work, event, at).await?;
    Ok(
        json!({"state":config["state"],"revision":config["revision"],"scope":config[SCOPE],"application_dispatched":false}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn timeout_retry_is_once_and_never_retries_a_provider_write() {
        let at = Utc::now();
        let deadline = at + Duration::minutes(15);
        let config = json!({
            "state":"RUNNING",
            "policy":{"platforms":{"naukri":{"mode":"SUPERVISED"}}},
            SCOPE:{"work_id":"fixture-work","expires_at":stamp(deadline)}
        });
        let work = json!({
            "id":"fixture-work","platform":"naukri","packet_id":"fixture-packet",
            "operation":"inspect_profile","stage":"READY_TO_APPLY","status":"executing",
            "admitted_actions":[],"facts":{}
        });
        let timeout = json!({"reason":"backend_timeout"});
        let mut expired = work.clone();
        assert!(!retry_pre_apply_transport(
            &config,
            &mut expired,
            &timeout,
            deadline
        ));
        for (field, evidence) in [
            ("id", json!("other-work")),
            ("operation", json!("apply")),
            ("status", json!("leased")),
            ("form_pending", json!(true)),
            ("admitted_actions", json!([{"id":"earlier-admission"}])),
        ] {
            let mut changed = work.clone();
            changed[field] = evidence;
            let before = changed.clone();
            assert!(!retry_pre_apply_transport(
                &config,
                &mut changed,
                &timeout,
                at
            ));
            assert_eq!(changed, before);
        }
        let mut retry = work;
        assert!(retry_pre_apply_transport(&config, &mut retry, &timeout, at));
        assert_eq!(retry["status"], "queued");
        assert_eq!(retry["packet_id"], "fixture-packet");
        assert!(!retry_pre_apply_transport(
            &config, &mut retry, &timeout, at
        ));
    }

    #[test]
    fn interrupted_application_read_discards_tab_bound_proof_before_recovery() {
        let at = Utc::now();
        let config = json!({
            "state":"RUNNING",
            "policy":{"platforms":{"naukri":{"mode":"SUPERVISED"}}},
            SCOPE:{"work_id":"fixture-work","expires_at":stamp(at + Duration::minutes(10))}
        });
        let work = json!({
            "id":"fixture-work","platform":"naukri","packet_id":"fixture-packet",
            "operation":"inspect_application","stage":"READY_TO_APPLY","status":"leased",
            "admitted_actions":[],"account_sha256":"fixture-hash",
            "binding":{"tab_id":50},
            "account_observation":{"source":"profile_ui","binding":{"tab_id":50},
                "account_sha256":"fixture-hash","work_id":"fixture-work",
                "profile_document_id":"old_profile_document","observed_at":stamp(at)},
            "facts":{"applicants_min":100,"provider_resume_checked_at":stamp(at),"prior_status":"NOT_APPLIED"}
        });
        let mut transport = work.clone();
        assert!(retry_pre_apply_transport(
            &config,
            &mut transport,
            &json!({"reason":"backend_not_ready"}),
            at
        ));
        assert_eq!(transport["operation"], "inspect_profile");
        assert_eq!(transport["status"], "queued");
        assert_eq!(transport["supervised_application_read_retry_used"], true);
        let mut expired = work.clone();
        rewind_expired_application_read(&config, &mut expired, at);
        for reset in [&transport, &expired] {
            assert_eq!(reset["operation"], "inspect_profile");
            assert_eq!(reset["packet_id"], "fixture-packet");
            assert_eq!(reset["admitted_actions"], json!([]));
            assert!(reset["account_observation"].is_null());
            assert!(reset["facts"]["provider_resume_checked_at"].is_null());
            assert!(reset["facts"]["prior_status"].is_null());
            assert_eq!(reset["facts"]["applicants_min"], 100);
        }
        let mut paused = work;
        paused["stage"] = json!("PAUSED");
        paused["status"] = json!("waiting");
        paused["reason"] = json!("global_stop");
        paused["paused_context"] = json!({"operation":"inspect_application","status":"waiting",
            "stage":"BLOCKED_PLATFORM","reason":"provider_account_identity_unverified"});
        assert!(!interrupted_pre_apply_read(&paused, at));
        paused["binding"]["tab_id"] = json!(51);
        assert!(interrupted_pre_apply_read(&paused, at));
        paused["paused_context"]["reason"] = json!("provider_challenge_requires_owner");
        assert!(!interrupted_pre_apply_read(&paused, at));
    }

    #[test]
    fn exception_is_bound_to_exact_work_evidence_and_deadline() {
        let at = DateTime::parse_from_rfc3339("2026-11-24T03:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let deadline = at + Duration::minutes(15);
        let mut config = json!({
            "state":"RUNNING",
            "policy":{"platforms":{"naukri":{
                "mode":"SUPERVISED", "applicants_mode":"global", "age_mode":"global", "cap_mode":"global"
            }},"global_limits":{
                "applicant_limit":1000,"unknown_applicants":"needs_review",
                "daily_cap":4,"max_job_age_days":14,"minimum_match_score":50
            }},
            SCOPE:{"work_id":"fixture-work","expires_at":stamp(deadline)}
        });
        let mut work = json!({
            "id":"fixture-work","platform":"naukri",
            "facts":{"applicants_min":100,"applicants_max":null,"posted_at":stamp(at - Duration::days(2))}
        });
        let temporary = policy_for_work(&config, &work, at).unwrap();
        let temporary = contracts::limits(&temporary, "naukri").unwrap();
        assert_eq!(temporary["unknown_applicants"], "allow_lower_bound");
        assert_eq!(temporary["applicant_limit"], 1000);
        assert_eq!(temporary["max_job_age_days"], 14);
        assert_eq!(temporary["minimum_match_score"], 50);
        assert_eq!(
            filters::listing_exclusion(&work["facts"], &temporary, at).unwrap(),
            None
        );
        assert_eq!(
            config["policy"]["global_limits"]["unknown_applicants"],
            "needs_review"
        );
        work["facts"]["posted_at"] = json!(stamp(at - Duration::days(15)));
        assert_eq!(
            filters::listing_exclusion(&work["facts"], &temporary, at).unwrap(),
            Some("posting_outside_age_limit")
        );
        assert!(require_write(&config, &work, at).is_ok());
        assert!(require_write(&config, &work, deadline).is_err());
        for value in [json!(null), json!(10), json!(1000)] {
            work["facts"]["applicants_min"] = value;
            assert_eq!(
                policy_for_work(&config, &work, at).unwrap().as_ref(),
                &config["policy"]
            );
            assert!(require_write(&config, &work, at).is_err());
        }
        work["facts"]["applicants_min"] = json!(100);
        work["facts"]["applicants_max"] = json!(100);
        assert!(require_write(&config, &work, at).is_err());
        work["facts"]["applicants_max"] = Value::Null;
        work["id"] = json!("unrelated-work");
        assert!(!permits_work(&config, &work, at));
        assert!(require_write(&config, &work, at).is_err());
        clear(&mut config).unwrap();
        assert_eq!(
            contracts::limits(&policy_for_work(&config, &work, at).unwrap(), "naukri").unwrap()["unknown_applicants"],
            "needs_review"
        );
    }
}
