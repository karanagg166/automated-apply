//! Trusted original-tab loss closes correlation envelopes and permits only bounded history reads.
use super::{events, notices, preflight, queue, storage::*};
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;
pub(crate) async fn report_in(
    tx: &mut Transaction<'_, Postgres>,
    id: Uuid,
    binding: &Value,
    telegram: bool,
    now: DateTime<Utc>,
) -> Result<bool> {
    let mut work = queue::load_in(tx, id).await?;
    let original = &work["form_binding"];
    if work["admitted_actions"]
        .as_array()
        .is_none_or(Vec::is_empty)
        || !original.is_object()
        || [
            "profile_binding_id",
            "browser_session_id",
            "window_id",
            "tab_id",
        ]
        .iter()
        .any(|k| original[*k] != binding[*k])
    {
        return Err(Failure("original_form_loss_binding_required"));
    }
    preflight::check_account_in(tx, &work).await.map_err(|e| {
        if matches!(
            e.0,
            "naukri_account_binding_changed" | "naukri_account_binding_context_changed"
        ) {
            Failure("form_loss_account_binding_changed")
        } else {
            e
        }
    })?;
    if work["stage"] == "SUBMITTED_CONFIRMED" || !work["form_loss_observation"].is_null() {
        return Ok(false);
    }
    if work["form_pending"] != true {
        return Err(Failure("pending_original_form_required"));
    }
    work["stage"] = json!("SUBMISSION_UNKNOWN");
    work["status"] = json!("unknown");
    work["operation"] = json!("reconcile_application");
    work["reason"] = json!("original_questionnaire_tab_unavailable_reconcile_only");
    work["revision"] = json!(next(&work)?);
    work["updated_at"] = json!(stamp(now));
    work["lease_token"] = Value::Null;
    work["lease_until"] = Value::Null;
    work["form_loss_observation"] = json!({"at":stamp(now),"source":"trusted_extension_original_tab_missing","original_tab_id":binding["tab_id"],"replay_authorized":false});
    let rows:Vec<(String,Value)>=sqlx::query_as("SELECT key,value FROM owner_preferences WHERE starts_with(key,'exec_q:') AND value->>'queue_work_id'=$1 AND value->>'state' IN ('pending','sent','delivery_unknown') ORDER BY key LIMIT 10001").bind(id.to_string()).fetch_all(&mut **tx).await.map_err(db)?;
    if rows.len() > 10000 {
        return Err(Failure("execution_active_inventory_limit"));
    }
    for (key, mut q) in rows {
        q["state"] = json!("closed_form_unavailable");
        q["closed_at"] = json!(stamp(now));
        q["reuse_approved"] = json!(false);
        put(tx, &key, &q).await?;
    }
    notices::unknown(tx, &mut work, telegram, now).await?;
    put(tx, &format!("apply_work:{id}"), &work).await?;
    events::queue(
        tx,
        &work,
        "original_form_lost_reconcile_only_no_replay",
        now,
    )
    .await?;
    Ok(true)
}
