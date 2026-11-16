//! Consistent read-only legacy dashboard projection. Retained observations are not live acceptance.
use super::{
    contracts::{self, Kind},
    legacy_policy, receipts,
    storage::*,
};
use crate::{Failure, Result, configuration::Configuration, resources};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use std::collections::HashSet;
use uuid::Uuid;
async fn inventory(tx: &mut Transaction<'_, Postgres>, prefix: &str) -> Result<Vec<Value>> {
    let values:Vec<Value>=sqlx::query_scalar("SELECT value FROM owner_preferences WHERE starts_with(key,$1) ORDER BY created_at,key LIMIT 10001").bind(prefix).fetch_all(&mut **tx).await.map_err(db)?;
    if values.len() > 10000 {
        return Err(Failure("execution_active_inventory_limit"));
    }
    Ok(values)
}
pub fn capabilities() -> Value {
    serde_json::from_str(include_str!("../../schemas/naukri-capability-matrix.json"))
        .expect("frozen Naukri capabilities")
}
async fn receipt_summary(tx: &mut Transaction<'_, Postgres>, now: DateTime<Utc>) -> Result<Value> {
    let (mut recorded, mut workers, mut dispatched, mut total) = (0u64, 0u64, 0u64, 0u64);
    let mut cursor: Option<(DateTime<Utc>, String)> = None;
    loop {
        let rows:Vec<(String,Value,DateTime<Utc>)>=sqlx::query_as("SELECT key,value,created_at FROM owner_preferences WHERE (starts_with(key,'naukri_receipt:') OR starts_with(key,'naukri_worker_receipt:')) AND ($1::timestamptz IS NULL OR (created_at,key)>($1,$2)) ORDER BY created_at,key LIMIT 100").bind(cursor.as_ref().map(|c|c.0)).bind(cursor.as_ref().map(|c|c.1.as_str())).fetch_all(&mut **tx).await.map_err(db)?;
        if rows.is_empty() {
            break;
        }
        for (key, value, created) in rows {
            total += 1;
            if receipts::recorded_application(&key, &value, now) {
                recorded += 1;
            } else if receipts::worker_recorded(&key, &value, now) {
                workers += 1;
                if value["worker_dispatched"] == true {
                    dispatched += 1;
                }
            }
            cursor = Some((created, key));
        }
    }
    Ok(
        json!({"naukri_recorded":recorded+workers,"owner_authorized_software_operated_ui":recorded,"installed_recurring_worker":dispatched,"reconciled_provider_history":workers-dispatched,"employer_acknowledged":0,"records_requiring_review":total-recorded-workers,"evidence_source":"retained_operator_observations_of_naukri_application_status_ui","live_reverified_by_this_read":false}),
    )
}
pub(super) async fn status_in(
    tx: &mut Transaction<'_, Postgres>,
    config: Option<&Configuration>,
    now: DateTime<Utc>,
) -> Result<Value> {
    let value = legacy_policy::record(tx).await?;
    let records:Value=sqlx::query_scalar("SELECT coalesce(jsonb_object_agg(key,value),'{}'::jsonb) FROM owner_preferences WHERE key IN ('naukri_worker_health','chr_selection','portal_naukri','phase1_profile_confirmation','gm54_alerts:1','gm54_alerts:2','gm54_account:1','gm54_account:2')").fetch_one(&mut **tx).await.map_err(db)?;
    let heartbeat = records["naukri_worker_health"]["heartbeat_at"].clone();
    let live = !heartbeat.is_null()
        && timestamp(&heartbeat)
            .is_ok_and(|at| at <= now && now - at < chrono::Duration::seconds(30));
    let selected = &records["chr_selection"]["profile_binding_id"];
    let chrome = if let Some(raw) = selected.as_str() {
        let id = raw.parse::<Uuid>().map_err(|_| invalid())?;
        get(tx, &format!("chr_prof:{id}"))
            .await?
            .map(|v| crate::browser_profiles::public(&v, selected, now))
            .transpose()?
    } else {
        None
    };
    let decisions = inventory(tx, "nau_dec:").await?;
    let executions:Vec<Value>=sqlx::query_scalar("SELECT value FROM owner_preferences WHERE starts_with(key,'exec:') AND value->>'platform'='naukri' ORDER BY created_at,key LIMIT 10001").fetch_all(&mut **tx).await.map_err(db)?;
    if executions.len() > 10000 {
        return Err(Failure("execution_active_inventory_limit"));
    }
    let mut alerts = Vec::new();
    for alert in inventory(tx, "nau_alert:").await? {
        if alert["state"] != "EXPIRED"
            && (alert["expires_at"].is_null() || timestamp(&alert["expires_at"])? > now)
        {
            alerts.push(alert);
        }
    }
    let source = value["policy"]["source"]
        .as_str()
        .unwrap_or("saved_owner_imports");
    let mut blockers = vec![
        "naukri_browser_permission_not_verified".to_owned(),
        "naukri_submission_capability_not_verified".into(),
        "locked_screen_acceptance_not_run".into(),
    ];
    blockers.insert(
        0,
        if source == "saved_owner_imports" {
            "recurring_external_source_not_connected"
        } else {
            "gmail_intake_deferred_to_phase54"
        }
        .into(),
    );
    if !live {
        blockers.insert(0, "execution_worker_offline".into());
    }
    if chrome.as_ref().is_none_or(|c| c["status"] != "CONNECTED") {
        blockers.push("selected_chrome_profile_offline_or_missing".into());
    }
    let commands = config.is_some_and(|c| c.browser_profiles.commands_enabled);
    if !commands {
        blockers.push("chrome_command_channel_disabled".into());
    } else if chrome
        .as_ref()
        .is_some_and(|c| c["commands_enabled"] != true)
    {
        blockers.push("selected_profile_command_opt_in_required".into());
    }
    if !value["policy"].is_null() {
        let policy = contracts::normalize(Kind::AutomationPolicy, value["policy"].clone())
            .map_err(|_| invalid())?;
        if let Err(error) = legacy_policy::validate_read_in(tx, &policy).await {
            if matches!(
                error.0,
                "confirmed_profile_version_required"
                    | "approved_primary_resume_changed_or_missing"
                    | "verified_experience_outside_policy"
                    | "gmail_intake_deferred_to_phase54"
            ) {
                blockers.insert(0, error.0.into());
            } else {
                return Err(error);
            }
        }
    }
    if let Some(blocked) = value["blocked_reason"].as_str() {
        if !blockers.iter().any(|s| s == blocked) {
            blockers.insert(0, blocked.to_owned());
        }
    }
    let mut gmail = Vec::new();
    for slot in 1..=config.map_or(0, |c| c.mailboxes.configured_slots()) {
        let key = format!("gm54_alerts:{slot}");
        let account_key = format!("gm54_account:{slot}");
        let mut alert = records
            .get(&key)
            .cloned()
            .unwrap_or(json!({"version":0,"enabled":false}));
        let configured = alert["enabled"] == true;
        let enabled = configured
            && records[&account_key]["status"] == "connected"
            && records[&account_key]["generation"] == alert["generation"];
        let object = alert.as_object_mut().ok_or_else(invalid)?;
        for key in ["lease", "lease_until", "page_token"] {
            object.remove(key);
        }
        alert["enabled"] = json!(enabled);
        alert["configured_enabled"] = json!(configured);
        alert["sender"] = json!("naukrialerts@naukri.com");
        alert["sending_enabled"] = json!(false);
        alert["links_opened"] = json!(false);
        gmail.push(alert);
    }
    let active = gmail
        .iter()
        .any(|a| a["enabled"] == true && !a["last_check_at"].is_null() && a["error"].is_null());
    if active {
        blockers.retain(|s| s != "recurring_external_source_not_connected");
        blockers.insert(0, "email_candidates_require_verified_vacancy_facts".into());
    }
    let profile = match crate::profile_store::get(tx).await {
        Ok(p) => Some(p.value),
        Err(Failure("profile_not_found")) => None,
        Err(e) => return Err(e),
    };
    let confirmation = &records["phase1_profile_confirmation"];
    let confirmed = profile.as_ref().is_some_and(|p| {
        confirmation["profile_id"] == p["id"]
            && confirmation["profile_version"] == p["version"]
            && confirmation["confirmed_at"]
                .as_str()
                .is_some_and(|s| !s.is_empty())
    });
    let resume = if let Some(profile) = &profile {
        let rows:Vec<Value>=sqlx::query_scalar("SELECT to_jsonb(r) FROM candidate_resources r WHERE candidate_profile_id=$1 ORDER BY id LIMIT 10001").bind(profile["id"].as_str().and_then(|s|s.parse::<Uuid>().ok()).ok_or_else(invalid)?).fetch_all(&mut **tx).await.map_err(db)?;
        if rows.len() > 10000 {
            return Err(Failure("execution_active_inventory_limit"));
        }
        let rows = rows
            .into_iter()
            .map(|v| serde_json::from_value::<resources::Resource>(v).map_err(|_| invalid()))
            .collect::<Result<Vec<_>>>()?;
        json!(resources::select_resume(&rows, None)?.selected)
    } else {
        Value::Null
    };
    let receipt = receipt_summary(tx, now).await?;
    let packets:Value=sqlx::query_scalar("SELECT jsonb_build_object('user_reported',count(*) FILTER(WHERE p.lifecycle_state='user_reported_submitted'),'unknown',count(*) FILTER(WHERE p.lifecycle_state IN ('submitting','submission_unknown'))) FROM application_packets p JOIN jobs j ON j.id=p.job_id WHERE j.source_platform='naukri'").fetch_one(&mut **tx).await.map_err(db)?;
    let mut manual = HashSet::new();
    for d in &decisions {
        if d["state"] == "NEEDS_INPUT" {
            manual.insert(d["id"].as_str().ok_or_else(invalid)?.to_owned());
        }
    }
    for e in &executions {
        if e["state"] == "NEEDS_INPUT" {
            manual.insert(e["job_id"].as_str().ok_or_else(invalid)?.to_owned());
        }
    }
    let last = decisions
        .iter()
        .filter_map(|d| d["last_observation"].as_str())
        .max();
    let mut automation = value.clone();
    automation
        .as_object_mut()
        .ok_or_else(invalid)?
        .remove("source_lease");
    let extra = json!({"scope":"PARTIAL_PREPARATION","source":source,"alert_candidates":alerts,"gmail_alert_discovery":gmail,"job_candidate_discovery":active,"email_source_activation_available":false,"chrome_channel_available":commands,"new_vacancy_discovery":false,"worker_online":live,"worker_heartbeat_at":heartbeat,"chrome_profile":chrome,"blockers":blockers,"last_observation":last,"counts":{"alert_candidates":alerts.len(),"matching":decisions.iter().filter(|d|d["eligible"]==true).count(),"prepared":executions.iter().filter(|e|e["packet_id"].as_str().is_some_and(|s|!s.is_empty())&&e["question_only"]!=true).count(),"submitted_confirmed":receipt["naukri_recorded"],"naukri_recorded":receipt["naukri_recorded"],"installed_worker_recorded":receipt["installed_recurring_worker"],"employer_acknowledged":receipt["employer_acknowledged"],"resume_preflights_verified":executions.iter().filter(|e|e["upload_preflight"]["state"]=="PDF_VERIFIED_LOCAL").count(),"resume_preflight_needs_input":executions.iter().filter(|e|e["upload_preflight"]["state"]=="NEEDS_INPUT").count(),"user_reported":packets["user_reported"],"unknown":packets["unknown"],"failed":executions.iter().filter(|e|matches!(e["state"].as_str(),Some("FAILED_FINAL"|"FAILED_RETRYABLE"))).count(),"manual_required":manual.len()+alerts.iter().filter(|a|a["state"]=="NEEDS_INPUT").count()},"policy_context":{"profile_version":if confirmed{profile.as_ref().map(|p|p["version"].clone())}else{None},"resume":resume},"decisions":decisions,"application_receipts":receipt,"stages":{"DISCOVERY":if source=="gmail_job_alerts"{"email_candidates_require_review"}else{"external_source_blocked"},"PREPARATION":value["state"],"FIELD_FILL":"separate_review_and_permission_required","SUBMISSION":"unsupported","PROVIDER_CONFIRMED":"independent_evidence_required"}});
    for (k, v) in extra.as_object().unwrap() {
        automation[k] = v.clone();
    }
    let portal = &records["portal_naukri"];
    let account = json!({"platform":"naukri","name":"Naukri","login_url":"https://www.naukri.com/nlogin/login","state":portal.get("state").cloned().unwrap_or(json!("owner_action_required")),"last_verification_time":portal["last_verification_time"],"evidence_type":portal.get("evidence_type").cloned().unwrap_or(json!("none")),"identity_verified":false,"api_connected":false,"capabilities":["manual_handoff","url_preview","gesture_session_observation"],"submission":"unsupported","owner_acceptance_required":portal["manual_capability_accepted"]!=true});
    Ok(
        json!({"automation":automation,"capabilities":capabilities(),"configuration":legacy_policy::configuration(tx).await?,"executions":executions,"worker_requirement":"awake_local_worker_or_separately_approved_always_on_worker","submitted":false,"account_session":account}),
    )
}
