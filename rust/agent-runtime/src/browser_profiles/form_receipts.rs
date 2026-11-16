//! Late receipts retain original provenance and cannot revive a transferred or paused task.
use super::*;
use super::{form_review, form_service};
pub(super) async fn record(
    tx: &mut Transaction<'_, Postgres>,
    command: &native::Command,
    receipt: Value,
) -> Result<Value> {
    let receipt = forms::normalize(forms::Kind::Receipt, receipt)?;
    let id = string(&receipt, "plan_id")?
        .parse::<Uuid>()
        .map_err(|_| Failure("invalid_fill_receipt"))?;
    let mut plan = form_service::load(tx, id).await?;
    let v = &command.value;
    if plan["profile_binding_id"] != v["profile_binding_id"]
        || plan["browser_session_id"] != v["browser_session_id"]
        || plan["tab_id"].is_null()
        || plan["tab_id"] != v["tab_id"]
    {
        return Err(Failure("extension_tab_binding_mismatch"));
    }
    let mut task = if plan["extension_task_id"].is_null() {
        None
    } else {
        if v["task_id"] != plan["extension_task_id"] {
            return Err(Failure("extension_task_required"));
        }
        let task = tasks::load(
            tx,
            string(&plan, "extension_task_id")?
                .parse()
                .map_err(|_| invalid())?,
        )
        .await?;
        if task["profile_binding_id"] != v["profile_binding_id"]
            || task["browser_session_id"] != v["browser_session_id"]
            || task["tab_id"] != v["tab_id"]
        {
            None
        } else {
            Some(task)
        }
    };
    if let Some(task) = task.as_ref()
        && task["state"] == "FILLING"
        && (task["version"] != v["expected_task_version"] || task["plan_id"] != plan["id"])
    {
        return Err(Failure("extension_task_revision_conflict"));
    }
    let status = forms::receipt_status(&plan, &receipt)?;
    if status != "already_recorded" {
        plan["state"] = json!("finished");
        form_service::save(tx, &plan).await?;
        form_review::fill_event(tx, &plan, status).await?;
        form_service::audit(tx, &plan, status, &receipt["results"]).await?;
        let key = format!("ext_receipt:{id}");
        if get(tx, &key).await?.is_none() {
            let mut value = receipt.clone();
            for(k,x)in json!({"application_id":plan["application_id"],"profile_binding_id":plan["profile_binding_id"],"browser_session_id":plan["browser_session_id"],"tab_id":plan["tab_id"],"packet_revision":plan["packet_revision"],"recorded_at":storage::now(tx).await?.to_rfc3339(),"submitted":false}).as_object().unwrap(){value[k]=x.clone();}
            put(tx, &key, &value).await?;
        }
    }
    let historical = !plan["extension_task_id"].is_null() && task.is_none();
    if status != "already_recorded"
        && let Some(current) = task.take()
    {
        let verified = receipt["verification_method"] == "retained_after_blur";
        let results = receipt["results"]
            .as_array()
            .ok_or(Failure("invalid_fill_receipt"))?;
        let completed = if verified {
            results.iter().filter(|r| r["status"] == "filled").count()
        } else {
            0
        };
        let mut receipts = current["verified_receipts"]
            .as_array()
            .ok_or_else(invalid)?
            .clone();
        let version = plan["actions"]
            .as_array()
            .and_then(|a| a.first())
            .map(|a| a["candidate_version"].clone())
            .unwrap_or_else(|| current["profile_version"].clone());
        receipts.push(json!({"plan_id":plan["id"],"authorization_id":plan["extension_authorization_id"],"profile_binding_id":plan["profile_binding_id"],"browser_session_id":plan["browser_session_id"],"tab_id":plan["tab_id"],"document_id":plan["inspection"]["document_id"],"packet_revision":plan["packet_revision"],"profile_version":version,"results":results,"verification_method":receipt["verification_method"],"network_guard_active":receipt["network_guard_active"],"state":status,"recorded_at":storage::now(tx).await?.to_rfc3339(),"submitted":false}));
        let start = receipts.len().saturating_sub(50);
        let mut counts = current["counts"].clone();
        counts["completed"] = json!(completed);
        counts["validation_errors"] = json!(
            results
                .iter()
                .filter(|r| r["status"] == "validation_error")
                .count()
        );
        let mut next = string(&current, "state")?.to_owned();
        if next == "FILLING" {
            next = if verified && completed > 0 && status == "form_filled" {
                "FILLED_VERIFIED"
            } else {
                "NEEDS_INPUT"
            }
            .into();
            let manual = plan["inspection"]["manual_controls"]
                .as_array()
                .ok_or(Failure("invalid_browser_form_record"))?
                .iter()
                .any(|m| m["required"] == true);
            if verified
                && status == "form_filled"
                && plan["inspection"]["has_next"] == false
                && !manual
            {
                next = "READY_FOR_SUBMISSION".into();
            }
        }
        let reason = if current["state"] == "PAUSED"
            && matches!(
                current["reason"].as_str(),
                Some("owner_pause" | "global_stop")
            ) {
            string(&current, "reason")?
        } else if verified {
            "fill_receipt_saved"
        } else {
            "fill_unverified_manual_required"
        }
        .to_owned();
        let now = storage::now(tx).await?;
        task = Some(
            tasks::move_in(
                tx,
                current,
                &next,
                &reason,
                json!({"verified_receipts":&receipts[start..],"counts":counts}),
                now,
            )
            .await?,
        );
    }
    let mut data = json!({"status":if historical{"historical_receipt_recorded"}else{status},"submitted":false});
    if historical {
        data["historical_profile_receipt"] = json!(true);
        data["original_profile_binding_id"] = plan["profile_binding_id"].clone();
    }
    if let Some(task) = task {
        data["task"] = task;
    }
    Ok(data)
}
