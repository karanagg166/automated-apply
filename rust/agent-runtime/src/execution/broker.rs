//! Authenticated native callers use these transaction-local operations; no browser/model IO.
use super::{
    admission, automatic,
    contracts::{self, Kind},
    discovery_observation, events, form_loss, preflight, profile_sync_work, questionnaire_context,
    questionnaire_steps, questionnaires, queue, queue_control, queue_status, search,
    storage::*,
    submission,
};
use crate::{Failure, Result, packet_service, private_resume};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;
pub(crate) const COMMANDS: &[&str] = &[
    "naukri_queue_status",
    "naukri_queue_control",
    "poll_naukri_work",
    "bind_naukri_work",
    "admit_naukri_work",
    "check_naukri_work",
    "finish_naukri_work",
    "abandon_naukri_work",
];
pub(crate) struct Services<'a> {
    pub packets: &'a packet_service::Settings,
    pub resumes: &'a private_resume::Settings,
    pub telegram: bool,
}
pub(crate) async fn status_in(tx: &mut Transaction<'_, Postgres>) -> Result<Value> {
    let data = queue_status::listing(
        tx,
        super::queue_page::Page {
            platform: Some("naukri".into()),
            limit: 5,
            ..Default::default()
        },
    )
    .await?;
    Ok(
        json!({"queue":{"state":data["configuration"]["state"],"revision":data["configuration"]["revision"],"counts":data["counts"],"total":data["total"],"consumer":data["consumer"]},"submitted":false}),
    )
}
pub(crate) async fn control_in(
    tx: &mut Transaction<'_, Postgres>,
    command: &Value,
    now: DateTime<Utc>,
) -> Result<Value> {
    if command["queue_action"].is_null() || command["expected_queue_revision"].is_null() {
        return Err(Failure("queue_control_fields_required"));
    }
    let input = contracts::normalize(
        Kind::Control,
        json!({"action":command["queue_action"],"expected_revision":command["expected_queue_revision"]}),
    )?;
    queue_control::control(tx, input, now).await?;
    status_in(tx).await
}
pub(crate) async fn scope_in(tx: &mut Transaction<'_, Postgres>) -> Result<()> {
    let execution = contracts::normalize(
        Kind::Configuration,
        get(tx, "exec_config:naukri").await?.unwrap_or(json!({})),
    )
    .map_err(|_| invalid())?;
    if execution["mode"] == "OFF" {
        return Err(Failure("execution_mode_off"));
    }
    if super::local_policy::preference_in(tx, "naukri").await? == "disabled" {
        return Err(Failure("platform_disabled"));
    }
    Ok(())
}
fn operation(work: &Value) -> Result<&str> {
    work["operation"]
        .as_str()
        .filter(|s| {
            matches!(*s, "inspect_job" | "search_jobs" | "apply")
                || submission::READS.contains(s)
                || questionnaire_steps::OPERATIONS.contains(s)
                || profile_sync_work::OPERATIONS.contains(s)
        })
        .ok_or(Failure("background_submission_executor_pending"))
}
pub(crate) fn transport(work: &Value) -> Result<Value> {
    let operation = work["operation"].as_str().ok_or_else(invalid)?;
    if !matches!(operation, "prepare" | "prepare_questionnaire") && self::operation(work).is_err() {
        return Err(Failure("background_submission_executor_pending"));
    }
    let mut value = serde_json::Map::new();
    for key in [
        "id",
        "revision",
        "lease_token",
        "lease_until",
        "operation",
        "url",
        "requisition",
        "binding",
        "stage",
        "status",
    ] {
        value.insert(key.into(), work[key].clone());
    }
    value.insert(
        "form_pending".into(),
        work.get("form_pending").cloned().unwrap_or(json!(false)),
    );
    if questionnaire_steps::OPERATIONS.contains(&operation) {
        value.insert(
            "target_url".into(),
            if operation == "refresh_questionnaire_profile" {
                json!(submission::PROFILE_URL)
            } else {
                work["url"].clone()
            },
        );
        value.insert("execution".into(), questionnaire_steps::descriptor(work));
    } else if profile_sync_work::OPERATIONS.contains(&operation) {
        value.insert("target_url".into(), work["url"].clone());
        value.insert("execution".into(), profile_sync_work::descriptor(work));
    } else if submission::READS.contains(&operation) || operation == "apply" {
        value.insert("target_url".into(), json!(submission::browser_url(work)?));
        value.insert("execution".into(), submission::descriptor(work));
    }
    Ok(Value::Object(value))
}
fn response(work: Option<&Value>, continuing: Option<bool>) -> Result<Value> {
    let mut value = json!({"work":work.map(transport).transpose()?,"submitted":false});
    if let Some(continuing) = continuing {
        value["continue"] = json!(continuing);
    }
    Ok(value)
}
pub(crate) async fn busy_in(
    tx: &mut Transaction<'_, Postgres>,
    now: DateTime<Utc>,
) -> Result<bool> {
    let legacy:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM owner_preferences WHERE (starts_with(key,'chr_cmd:') AND (value->>'state' IS NULL OR value->>'state' NOT IN ('completed','failed','expired','cancelled','outcome_unknown'))) OR (starts_with(key,'ext_task:') AND value->>'state' IN ('FORM_INSPECTED','ANSWERS_REVIEWED','FILL_AUTHORIZED','FILLING')))").fetch_one(&mut **tx).await.map_err(db)?;
    if legacy {
        return Ok(true);
    }
    let leases:Vec<Value>=sqlx::query_scalar("SELECT value->'lease_until' FROM owner_preferences WHERE ((starts_with(key,'apply_work:') AND value->>'stage' NOT IN ('SUBMITTED_RECORDED','SUBMITTED_CONFIRMED','FAILED_FINAL','SKIPPED') AND value->>'status' IN ('leased','executing')) OR key IN ('apply_search:naukri','apply_profile_sync:naukri')) AND value->'lease_until' IS NOT NULL AND value->'lease_until'<>'null'::jsonb LIMIT 10001").fetch_all(&mut **tx).await.map_err(db)?;
    if leases.len() > 10000 {
        return Err(Failure("execution_active_inventory_limit"));
    }
    for lease in leases {
        if timestamp(&lease)? > now {
            return Ok(true);
        }
    }
    Ok(false)
}
async fn maintenance_in(
    tx: &mut Transaction<'_, Postgres>,
    command: &Value,
    binding: &Value,
    now: DateTime<Utc>,
) -> Result<Option<Value>> {
    let Some(mut value) = get(tx, "naukri_extension_maintenance").await? else {
        return Ok(None);
    };
    // Automatic manager/WebUI navigation remains suspended after actual focus failure.
    if value["kind"] != "open_naukri_profile_setup" {
        return Ok(None);
    }
    let valid = timestamp(&value["expires_at"])
        .is_ok_and(|at| at > now && at - now <= chrono::Duration::minutes(2));
    let id = value["request_id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok());
    if !valid || id.is_none() || value["request_id"] != id.unwrap().to_string() {
        return Ok(None);
    }
    let mut neutral = binding.clone();
    neutral["tab_id"] = Value::Null;
    let config = queue_control::configuration(tx).await?;
    if value["binding"] != neutral || config["policy"]["platforms"]["naukri"]["enabled"] != true {
        return Ok(None);
    }
    let account = automatic::account(tx).await?;
    if value["account_binding_revision"] != account["revision"]
        || value["candidate_profile_id"] != account["candidate_profile_id"]
    {
        return Err(Failure("profile_setup_account_context_changed"));
    }
    if !command["tab_id"].is_null() {
        if command["tab_id"].as_i64().is_none_or(|n| n <= 0)
            || command["work_id"] != value["request_id"]
            || !value["opened_tab_id"].is_null() && value["opened_tab_id"] != command["tab_id"]
        {
            return Err(Failure("profile_setup_ack_context_changed"));
        }
        let report = &command["work_report"];
        if !report.is_null()
            && (report["kind"] != "needs_input" || report["reason"] != "owner_tab_active")
        {
            return Err(Failure("profile_setup_ack_report_invalid"));
        }
        value["opened_tab_id"] = command["tab_id"].clone();
        value["owner_adopted"] = json!(value["owner_adopted"] == true || !report.is_null());
        if value["opened_at"].is_null() {
            value["opened_at"] = json!(stamp(now));
        }
        put(tx, "naukri_extension_maintenance", &value).await?;
        return Ok(Some(
            json!({"work":null,"maintenance_recorded":true,"submitted":false}),
        ));
    }
    if !value["opened_tab_id"].is_null() {
        return Ok(Some(
            json!({"work":null,"maintenance_recorded":true,"submitted":false}),
        ));
    }
    Ok(Some(
        json!({"work":null,"maintenance":{"kind":value["kind"],"request_id":value["request_id"],"expires_at":value["expires_at"]},"submitted":false}),
    ))
}
pub(crate) async fn poll_in(
    tx: &mut Transaction<'_, Postgres>,
    command: &Value,
    binding: &Value,
    services: &Services<'_>,
    now: DateTime<Utc>,
) -> Result<Value> {
    scope_in(tx).await?;
    if command["work_report"]["kind"] == "needs_input"
        && command["work_report"]["reason"] == "original_questionnaire_tab_unavailable"
    {
        let id = command["work_id"]
            .as_str()
            .and_then(|s| s.parse::<Uuid>().ok())
            .ok_or(Failure("original_form_loss_binding_required"))?;
        if binding["tab_id"].as_i64().is_none_or(|n| n <= 0) {
            return Err(Failure("original_form_loss_binding_required"));
        }
        let changed = form_loss::report_in(tx, id, binding, services.telegram, now).await?;
        return Ok(
            json!({"work":null,"form_loss_recorded":true,"state_changed":changed,"submitted":false}),
        );
    }
    let config = queue_control::configuration(tx).await?;
    if config["state"] == "STOPPED"
        && let Some(value) = maintenance_in(tx, command, binding, now).await?
    {
        return Ok(value);
    }
    if !binding["tab_id"].is_null() {
        return Err(Failure("queue_poll_without_tab_required"));
    }
    if config["state"] != "RUNNING" || config["policy"]["platforms"]["naukri"]["enabled"] != true {
        return response(None, None);
    }
    let busy = busy_in(tx, now).await?;
    let mut work = None;
    if !busy {
        let naukri = &config["policy"]["platforms"]["naukri"];
        let supervised =
            naukri["mode"] == "SUPERVISED" && naukri["owner_submission_authorized"] == true;
        submission::recover_unknown_in(tx, services.telegram, now).await?;
        work = queue::claim_in(
            tx,
            "naukri",
            binding,
            Some(questionnaire_steps::OPERATIONS),
            now,
        )
        .await?;
        // A supervised session should service its existing application work
        // before routine profile and search leases take the only browser lane.
        if work.is_none() && supervised {
            work = claim_application_read(tx, binding, now).await?;
        }
        if work.is_none() && !super::supervised_listing::scoped(&config) {
            work = profile_sync_work::work_in(tx, binding, services.resumes, now).await?;
        }
        if work.is_none() && !super::supervised_listing::scoped(&config) {
            work = search::work_in(tx, binding, now).await?;
        }
        if work.is_none() && !supervised {
            work = claim_application_read(tx, binding, now).await?;
        }
    }
    put(tx,"apply_consumer:naukri",&json!({"last_poll_at":stamp(now),"profile_binding_id":binding["profile_binding_id"],"busy":busy,"capability":"ordinary_ui_direct_apply_candidate"})).await?;
    response(work.as_ref(), None)
}

async fn claim_application_read(
    tx: &mut Transaction<'_, Postgres>,
    binding: &Value,
    now: DateTime<Utc>,
) -> Result<Option<Value>> {
    let mut operations = submission::READS.to_vec();
    operations.push("inspect_job");
    let mut work = queue::claim_in(tx, "naukri", binding, Some(&operations), now).await?;
    if let Some(value) = &mut work
        && value["operation"] == "reconcile_application"
        && !preflight::account_current(value, now)
    {
        value["operation"] = json!("verify_account");
        value["revision"] = json!(next(value)?);
        put(
            tx,
            &format!("apply_work:{}", value["id"].as_str().ok_or_else(invalid)?),
            value,
        )
        .await?;
    }
    Ok(work)
}

async fn load_in(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<(String, Value)> {
    for key in [profile_sync_work::WORK, search::WORK] {
        if let Some(work) = get(tx, key).await?
            && work["id"] == id.to_string()
        {
            return Ok((key.into(), work));
        }
    }
    Ok((format!("apply_work:{id}"), queue::load_in(tx, id).await?))
}
async fn checked_in(
    tx: &mut Transaction<'_, Postgres>,
    command: &Value,
    binding: &Value,
    now: DateTime<Utc>,
) -> Result<(String, Value)> {
    let id = command["work_id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or(Failure("queue_lease_fields_required"))?;
    if command["expected_work_revision"]
        .as_i64()
        .is_none_or(|n| n <= 0)
        || command["work_lease_token"]
            .as_str()
            .and_then(|s| s.parse::<Uuid>().ok())
            .is_none()
    {
        return Err(Failure("queue_lease_fields_required"));
    }
    let (key, work) = load_in(tx, id).await?;
    let config = queue_control::configuration(tx).await?;
    if config["state"] != "RUNNING"
        || config["policy"]["platforms"]["naukri"]["enabled"] != true
        || work["id"] != id.to_string()
        || work["policy_revision"] != config["revision"]
        || work["revision"] != command["expected_work_revision"]
        || work["lease_token"] != command["work_lease_token"]
        || &work["binding"] != binding
        || !matches!(work["status"].as_str(), Some("leased" | "executing"))
        || work["lease_until"].is_null()
        || timestamp(&work["lease_until"])? <= now
    {
        return Err(Failure("queue_lease_lost"));
    }
    operation(&work)?;
    Ok((key, work))
}
pub(crate) async fn step_in(
    tx: &mut Transaction<'_, Postgres>,
    command: &Value,
    binding: &Value,
    services: &Services<'_>,
    now: DateTime<Utc>,
) -> Result<Value> {
    scope_in(tx).await?;
    let name = command["command"].as_str().ok_or_else(invalid)?;
    if binding["tab_id"].as_i64().is_none_or(|n| n <= 0) {
        return Err(Failure("queue_tab_binding_required"));
    }
    if name == "bind_naukri_work" {
        let mut unbound = binding.clone();
        unbound["tab_id"] = Value::Null;
        let (key, mut work) = checked_in(tx, command, &unbound, now).await?;
        if work["form_pending"] == true
            && work["form_loss_observation"].is_null()
            && questionnaire_steps::OPERATIONS.contains(&operation(&work)?)
            && [
                "profile_binding_id",
                "browser_session_id",
                "window_id",
                "tab_id",
            ]
            .iter()
            .any(|k| work["form_binding"][*k] != binding[*k])
        {
            return Err(Failure("questionnaire_original_browser_context_required"));
        }
        work["binding"] = binding.clone();
        work["revision"] = json!(next(&work)?);
        put(tx, &key, &work).await?;
        return response(Some(&work), None);
    }
    let (key, mut work) = checked_in(tx, command, binding, now).await?;
    let op = operation(&work)?.to_owned();
    if name == "check_naukri_work" {
        if profile_sync_work::OPERATIONS.contains(&op.as_str()) {
            profile_sync_work::check_in(tx, &work, now).await?;
        } else if questionnaire_steps::OPERATIONS.contains(&op.as_str()) {
            let writing = op == "answer_questionnaire" && work["status"] == "executing";
            questionnaire_context::check_in(
                tx,
                &mut work,
                services.packets,
                services.resumes,
                writing,
                now,
            )
            .await?;
        } else if op == "apply" && work["status"] == "executing" {
            preflight::admitted_apply_in(tx, &mut work, services.packets, services.resumes, now)
                .await?;
        } else if submission::READS.contains(&op.as_str()) {
            preflight::check_account_in(tx, &work).await?;
        }
        return response(Some(&work), None);
    }
    if name == "admit_naukri_work" {
        if work["status"] != "leased" {
            return Err(Failure("queue_action_already_admitted"));
        }
        if profile_sync_work::OPERATIONS.contains(&op.as_str()) {
            work = profile_sync_work::admit_in(tx, work, now).await?;
        } else if matches!(op.as_str(), "apply" | "answer_questionnaire") {
            let id = work["id"]
                .as_str()
                .and_then(|s| s.parse().ok())
                .ok_or_else(invalid)?;
            let revision = revision(&work)?;
            let token = work["lease_token"]
                .as_str()
                .and_then(|s| s.parse().ok())
                .ok_or_else(invalid)?;
            work = admission::admit_in(
                tx,
                admission::Request {
                    identity: id,
                    revision,
                    token,
                    binding,
                },
                admission::Services {
                    packets: services.packets,
                    resumes: services.resumes,
                },
            )
            .await?;
            work["permit_expires_at"] = json!(stamp(
                super::storage::now(tx).await? + chrono::Duration::seconds(2)
            ));
        } else {
            if submission::READS.contains(&op.as_str()) {
                preflight::check_account_in(tx, &work).await?;
            }
            if questionnaire_steps::OPERATIONS.contains(&op.as_str()) {
                questionnaire_context::check_in(
                    tx,
                    &mut work,
                    services.packets,
                    services.resumes,
                    false,
                    now,
                )
                .await?;
            }
            match super::read_bounds::admit(&mut work) {
                Ok(()) => {}
                Err(Failure("bounded_reconciliation_exhausted")) => {
                    work["stage"] = json!("SUBMISSION_UNKNOWN");
                    work["status"] = json!("unknown");
                    work["reason"] = json!("bounded_reconciliation_exhausted");
                    work["revision"] = json!(next(&work)?);
                    work["lease_token"] = Value::Null;
                    work["lease_until"] = Value::Null;
                    super::notices::unknown(tx, &mut work, services.telegram, now).await?;
                    put(tx, &key, &work).await?;
                    events::queue(
                        tx,
                        &work,
                        "bounded_read_reconciliation_exhausted_no_replay",
                        now,
                    )
                    .await?;
                    return response(None, Some(false));
                }
                Err(e) => return Err(e),
            }
            work["status"] = json!("executing");
            work["revision"] = json!(next(&work)?);
        }
        put(tx, &key, &work).await?;
        return response(Some(&work), None);
    }
    if !matches!(name, "finish_naukri_work" | "abandon_naukri_work") {
        return Err(Failure("background_operation_not_supported"));
    }
    if command["work_report"].is_null() {
        return Err(Failure("queue_observation_required"));
    }
    if name == "finish_naukri_work" && work["status"] != "executing" {
        return Err(Failure("queue_action_not_admitted"));
    }
    let mut report = command["work_report"].clone();
    if name == "abandon_naukri_work" {
        report["kind"] = json!("failed");
        report["execution"] = Value::Null;
    }
    let continuing = if profile_sync_work::OPERATIONS.contains(&op.as_str()) {
        profile_sync_work::receive_in(tx, &mut work, &report, services.resumes, now).await?
    } else if questionnaire_steps::OPERATIONS.contains(&op.as_str()) {
        questionnaires::receive_in(
            tx,
            &mut work,
            &report,
            services.packets,
            services.resumes,
            now,
        )
        .await?
    } else if submission::READS.contains(&op.as_str()) || op == "apply" {
        submission::receive_in(
            tx,
            &mut work,
            &report,
            services.packets,
            services.resumes,
            now,
        )
        .await?
    } else if op == "search_jobs" {
        search::receive_in(tx, &mut work, &report, now).await?;
        false
    } else {
        discovery_observation::receive_in(tx, &mut work, &report, now).await?;
        false
    };
    work["revision"] = json!(next(&work)?);
    work["updated_at"] = json!(stamp(now));
    if questionnaire_steps::OPERATIONS.contains(&op.as_str()) {
        events::queue(tx, &work, "questionnaire_browser_observed", now).await?;
    } else if submission::READS.contains(&op.as_str()) || op == "apply" {
        events::queue(tx, &work, "browser_execution_observed", now).await?;
    }
    if !continuing {
        work["lease_token"] = Value::Null;
        work["lease_until"] = Value::Null;
    }
    put(tx, &key, &work).await?;
    response(Some(&work), Some(continuing))
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn native_transport_redacts_local_history_and_answer_until_the_exact_answer_is_admitted() {
        let mut work = json!({"id":Uuid::new_v4(),"revision":7,"operation":"inspect_job","status":"leased","url":"https://www.naukri.com/job-listings-fictional-123456789012","facts":{"mail_body":"PRIVATE_MAIL_CANARY","candidate_phone":"PRIVATE_PHONE_CANARY"},"source_reference":"PRIVATE_SOURCE_CANARY","profile_secret":"PRIVATE_SECRET_CANARY","ciphertext":"PRIVATE_PDF_CANARY","questionnaire":{"document_id":Uuid::new_v4(),"step_sha256":"a".repeat(64)},"questionnaire_answer":{"answer":"PRIVATE_SCOPED_ANSWER_CANARY"}});
        for op in [
            "inspect_job",
            "prepare",
            "prepare_questionnaire",
            "inspect_questionnaire",
        ] {
            work["operation"] = json!(op);
            let value = transport(&work).unwrap();
            assert!(!value.to_string().contains("PRIVATE_"));
        }
        work["operation"] = json!("answer_questionnaire");
        assert!(!transport(&work).unwrap().to_string().contains("PRIVATE_"));
        work["status"] = json!("executing");
        let value = transport(&work).unwrap();
        assert_eq!(
            value["execution"]["questionnaire"]["answer"],
            "PRIVATE_SCOPED_ANSWER_CANARY"
        );
        for secret in [
            "PRIVATE_MAIL_CANARY",
            "PRIVATE_PHONE_CANARY",
            "PRIVATE_SOURCE_CANARY",
            "PRIVATE_SECRET_CANARY",
            "PRIVATE_PDF_CANARY",
        ] {
            assert!(!value.to_string().contains(secret));
        }
    }
}
