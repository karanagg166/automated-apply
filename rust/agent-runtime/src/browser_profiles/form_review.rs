//! Exact review and single-use consumption, bound to current profile/packet/evidence/PDF.
use super::form_service::{self, Services};
use super::*;
pub(super) async fn fresh(
    tx: &mut Transaction<'_, Postgres>,
    plan: &Value,
    settings: &Settings,
    packets: &crate::packet_service::Settings,
    services: Services<'_>,
) -> Result<Value> {
    let application = string(plan, "application_id")?
        .parse()
        .map_err(|_| invalid())?;
    let now = storage::now(tx).await?;
    let (packet, url) = commands::context(tx, application, settings, packets, now).await?;
    if timestamp(&plan["expires_at"])? <= now
        || packet["snapshot"]["context_digest"] != plan["context_digest"]
        || packet["revision"] != plan["packet_revision"]
        || plan["target_url"] != url
        || plan["project_digest"] != form_service::projects(tx).await?
    {
        return Err(Failure("fill_plan_stale"));
    }
    let actions = plan["actions"]
        .as_array()
        .ok_or(Failure("invalid_browser_form_record"))?;
    for action in actions {
        if action["needs_input"] == false
            && let Some(id) = action["missing_input_id"].as_str()
        {
            let saved = get(tx, &format!("needs_input:{id}"))
                .await?
                .ok_or(Failure("fill_plan_stale"))?;
            if saved["version"] != action["missing_input_version"]
                || saved["status"] != "approved"
                || saved["candidate_profile_id"] != packet["candidate_profile_id"]
            {
                return Err(Failure("fill_plan_stale"));
            }
            let request = crate::answer_contract::normalize(
                json!({"question":saved["question"],"job_id":saved["job_id"],"company_name":saved["company_name"],"job_description":saved["job_description"],"save_draft":false,"rewrite":false}),
            )?;
            let current = crate::answer_context::Stamp::load_in(tx, &request).await?;
            if saved["context_digest"] != current.missing()
                || saved["profile_version"] != current.profile_version()
            {
                return Err(Failure("fill_plan_stale"));
            }
        }
        for reference in action["evidence"]
            .as_array()
            .ok_or(Failure("invalid_browser_form_record"))?
        {
            if let Some(value) = reference
                .as_str()
                .and_then(|s| s.strip_prefix("reviewed_packet_answer:"))
            {
                let (id, revision) = value.split_once(':').ok_or(Failure("fill_plan_stale"))?;
                let field = packet["fields"]
                    .as_array()
                    .ok_or_else(invalid)?
                    .iter()
                    .find(|f| f["id"].as_str() == Some(id))
                    .ok_or(Failure("fill_plan_stale"))?;
                if field["answer_revision"].as_i64() != revision.parse().ok()
                    || action["preview_only"] != true && field["review_status"] != "reviewed"
                    || !field["provenance"]["answer_expires_at"].is_null()
                        && timestamp(&field["provenance"]["answer_expires_at"])?
                            <= storage::now(tx).await?
                {
                    return Err(Failure("fill_plan_stale"));
                }
            }
        }
    }
    let references = actions
        .iter()
        .filter_map(|a| a["safe_reference"].as_str())
        .collect::<Vec<_>>();
    if !references.is_empty() {
        let bytes = form_service::pdf(tx, &packet, services)
            .await?
            .ok_or(Failure("canonical_pdf_changed"))?;
        let expected = format!("canonical_pdf:{:x}", Sha256::digest(bytes));
        if references.iter().any(|s| *s != expected) {
            return Err(Failure("canonical_pdf_changed"));
        }
    }
    // Recheck actual time after any lock/decryption work before granting a plan.
    if timestamp(&plan["expires_at"])? <= storage::now(tx).await? {
        return Err(Failure("fill_plan_stale"));
    }
    Ok(packet)
}
pub(super) async fn review(
    tx: &mut Transaction<'_, Postgres>,
    id: Uuid,
    fields: &Value,
    settings: &Settings,
    packets: &crate::packet_service::Settings,
    services: Services<'_>,
) -> Result<Value> {
    let mut plan = form_service::load(tx, id).await?;
    fresh(tx, &plan, settings, packets, services).await?;
    let fields = fields
        .as_array()
        .filter(|v| v.len() <= 24)
        .ok_or(Failure("invalid_field_approval"))?;
    let mut seen = std::collections::HashSet::new();
    let actions = plan["actions"]
        .as_array()
        .ok_or(Failure("invalid_browser_form_record"))?;
    if plan["state"] != "preview"
        || fields.iter().any(|id| {
            !id.is_string()
                || !seen.insert(id)
                || !actions.iter().any(|a| {
                    a["field_id"] == *id
                        && a["needs_input"] == false
                        && a["preview_only"] != true
                        && a["evidence"].as_array().is_some_and(|v| !v.is_empty())
                })
        })
    {
        return Err(Failure("invalid_field_approval"));
    }
    plan["approved_fields"] = json!(fields);
    plan["state"] = json!("authorized");
    form_service::save(tx, &plan).await?;
    Ok(plan)
}
pub(super) async fn consume(
    tx: &mut Transaction<'_, Postgres>,
    id: Uuid,
    settings: &Settings,
    packets: &crate::packet_service::Settings,
    services: Services<'_>,
) -> Result<Value> {
    if !settings.fill_enabled {
        return Err(Failure("browser_fill_disabled"));
    }
    let mut plan = form_service::load(tx, id).await?;
    fresh(tx, &plan, settings, packets, services).await?;
    if plan["mode"] != "manual_extension" || plan["state"] != "authorized" {
        return Err(Failure("single_use_fill_authorization_required"));
    }
    plan["state"] = json!("consumed");
    form_service::save(tx, &plan).await?;
    fill_event(tx, &plan, "fill_authorized").await?;
    form_service::audit(tx, &plan, "fill_authorized", &json!([])).await?;
    Ok(plan)
}
pub(super) async fn fill_event(
    tx: &mut Transaction<'_, Postgres>,
    plan: &Value,
    status: &str,
) -> Result<()> {
    let packet = string(plan, "application_id")?
        .parse::<Uuid>()
        .map_err(|_| invalid())?;
    let Some(binding) = crate::packet_execution::lock_in(tx, packet).await? else {
        return Ok(());
    };
    let mut value = binding.value;
    let state = string(&value, "state")?.to_owned();
    let stopped = value["cancelled"] == true
        || matches!(
            state.as_str(),
            "REJECTED" | "FAILED_FINAL" | "SUBMITTED_CONFIRMED" | "SUBMISSION_UNKNOWN" | "PAUSED"
        );
    if value["question_only"] == true {
        if stopped {
            return Err(Failure("execution_paused_or_cancelled"));
        }
        return Ok(());
    }
    if stopped {
        if stopped && status == "fill_authorized" {
            return Err(Failure("execution_paused_or_cancelled"));
        }
        return Ok(());
    }
    let evidence = value["evidence"].as_array().ok_or_else(invalid)?.clone();
    if value["diagnostic"] == "fill_outcome_unknown_reinspect_manually"
        && status != "fill_authorized"
    {
        let mut evidence = evidence;
        evidence.push(
            json!({"plan_id":plan["id"],"status":format!("late_{status}"),"submitted":false}),
        );
        value["evidence"] = json!(evidence);
        put(tx, &binding.key, &value).await?;
        return Ok(());
    }
    let next = if status == "fill_authorized" {
        "FILLING"
    } else if status == "form_filled" {
        "READY_FOR_REVIEW"
    } else {
        "NEEDS_INPUT"
    };
    if next != state {
        let allowed = match state.as_str() {
            "PREPARING" => matches!(next, "FILLING" | "NEEDS_INPUT" | "READY_FOR_REVIEW"),
            "FILLING" => matches!(next, "NEEDS_INPUT" | "READY_FOR_REVIEW"),
            "READY_FOR_REVIEW" => matches!(next, "FILLING" | "NEEDS_INPUT"),
            _ => false,
        };
        if !allowed {
            return Err(Failure("execution_not_ready_for_fill"));
        }
        let mut history = value["history"].as_array().ok_or_else(invalid)?.clone();
        history.push(json!({"from":state,"to":next,"reason":status}));
        value["state"] = json!(next);
        value["diagnostic"] = json!(status);
        value["history"] = json!(history);
        value["revision"] = json!(
            number(&value, "revision")?
                .checked_add(1)
                .ok_or_else(invalid)?
        );
        let id = Uuid::new_v5(
            &Uuid::NAMESPACE_URL,
            format!(
                "{}:{}:state_changed",
                string(&value, "id")?,
                number(&value, "revision")?
            )
            .as_bytes(),
        );
        let now = storage::now(tx).await?;
        put(tx,&format!("exec_event:{id}"),&json!({"id":id,"execution_id":value["id"],"event":"state_changed","state":next,"at":now.to_rfc3339(),"delivered":false})).await?;
    }
    let now = storage::now(tx).await?;
    value["lease_until"] = if status == "fill_authorized" {
        json!((now + chrono::Duration::seconds(90)).to_rfc3339())
    } else {
        Value::Null
    };
    value["heartbeat_at"] = json!(now.to_rfc3339());
    let mut evidence = evidence;
    evidence.push(json!({"plan_id":plan["id"],"status":status,"submitted":false}));
    value["evidence"] = json!(evidence);
    put(tx, &binding.key, &value).await
}
pub(super) async fn attach(
    tx: &mut Transaction<'_, Postgres>,
    mut task: Value,
    mut plan: Value,
    settings: &Settings,
    packets: &crate::packet_service::Settings,
    services: Services<'_>,
) -> Result<(Value, Value)> {
    if plan["application_id"] != task["application_id"]
        || plan["target_url"] != task["current_url"]
        || !matches!(plan["state"].as_str(), Some("preview" | "read_only"))
        || !plan["extension_task_id"].is_null() && plan["extension_task_id"] != task["id"]
    {
        return Err(Failure("extension_task_plan_mismatch"));
    }
    let packet = fresh(tx, &plan, settings, packets, services).await?;
    plan["extension_task_id"] = task["id"].clone();
    if task["challenge_observed"] == true && plan["inspection"]["challenge_state"] == "NONE" {
        plan["inspection"]["challenge_state"] = json!("UNKNOWN");
        plan["state"] = json!("read_only");
    }
    form_service::save(tx, &plan).await?;
    let challenge = plan["inspection"]["challenge_state"].clone();
    let safe = matches!(
        challenge.as_str(),
        Some("NONE" | "MANUALLY_RESOLVED_AND_SITE_VERIFIED")
    );
    let actions = plan["actions"]
        .as_array()
        .ok_or(Failure("invalid_browser_form_record"))?;
    let fields = plan["inspection"]["fields"]
        .as_array()
        .ok_or(Failure("invalid_browser_form_record"))?;
    let manual = plan["inspection"]["manual_controls"]
        .as_array()
        .ok_or(Failure("invalid_browser_form_record"))?;
    let state = if !safe {
        "CHALLENGE_REQUIRED"
    } else if plan["state"] == "read_only" || actions.iter().any(|a| a["needs_input"] == true) {
        "NEEDS_INPUT"
    } else {
        "FORM_INSPECTED"
    };
    let mut revisions = json!({});
    for field in packet["fields"].as_array().ok_or_else(invalid)? {
        revisions[string(field, "id")?] = field["answer_revision"].clone();
    }
    let changes = json!({"plan_id":plan["id"],"authorization_id":null,"packet_revision":packet["revision"],"profile_version":packet["candidate_profile_version"],"context_digest":packet["snapshot"]["context_digest"],"step":fields.iter().find_map(|f|f["page_step"].as_str().filter(|s|!s.is_empty())),"challenge_state":challenge,"challenge_observed":task["challenge_observed"]==true || matches!(challenge.as_str(),Some("WIDGET_PRESENT_UNVERIFIED"|"CHALLENGE_BLOCKING")),"field_answer_revisions":revisions,"counts":{"ready":actions.iter().filter(|a|a["needs_input"]==false && a["preview_only"]!=true && a["kind"]!="file").count(),"completed":0,"missing":actions.iter().filter(|a|a["needs_input"]==true).count(),"manual":actions.iter().filter(|a|a["preview_only"]==true || a["kind"]=="file").count()+manual.iter().map(|m|m["control_id"].clone()).collect::<std::collections::HashSet<_>>().len(),"validation_errors":fields.iter().filter(|f|f["invalid"]==true).count()+manual.iter().filter(|m|m["invalid"]==true).count(),"existing":plan["inspection"]["completed_count"]},"browser_connection":"connected","tab_active":true});
    let now = storage::now(tx).await?;
    task = tasks::move_in(tx, task, state, "fresh_inspection_prepared", changes, now).await?;
    if plan["state"] == "read_only" && safe {
        task["next_action"] = json!(if plan["inspection"]["manual_reason"]
            == "verified_application_form_not_present"
        {
            "This page has no verified application form. Review the site's application step manually; no fields were filled."
        } else {
            "Complete unsupported page interactions manually. This plan is read-only; a fresh inspection and review are required."
        });
        put(tx, &format!("ext_task:{}", string(&task, "id")?), &task).await?;
    }
    Ok((task, plan))
}
