//! Preserve observed unanswered Naukri questions in the existing packet checklist.
//! This bridge never queues Telegram delivery or authorizes browser work.
use super::form_service::Services;

async fn move_intent(
    tx: &mut Transaction<'_, Postgres>,
    mut value: Value,
    reason: &str,
) -> Result<Value> {
    let current = string(&value, "state")?.to_owned();
    if current != "NEEDS_INPUT" {
        if !matches!(
            current.as_str(),
            "PREPARING" | "READY_FOR_REVIEW" | "FILLING"
        ) {
            return Err(Failure("execution_not_waiting_for_question"));
        }
        let mut history = value["history"].as_array().ok_or_else(invalid)?.clone();
        history.push(json!({"from":current,"to":"NEEDS_INPUT","reason":reason}));
        value["history"] = json!(history);
        value["state"] = json!("NEEDS_INPUT");
        value["diagnostic"] = json!(reason);
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
        put(tx,&format!("exec_event:{id}"),&json!({"id":id,"execution_id":value["id"],"event":"state_changed","state":"NEEDS_INPUT","at":now.to_rfc3339(),"delivered":false})).await?;
        put(tx, &format!("exec:{}", string(&value, "id")?), &value).await?;
    }
    Ok(value)
}
pub(crate) async fn intent(
    tx: &mut Transaction<'_, Postgres>,
    packet: &Value,
    now: DateTime<Utc>,
) -> Result<Value> {
    if packet["readiness"]["stale"] == true || packet["snapshot"]["destination"]["valid"] != true {
        return Err(Failure("packet_context_stale_or_destination_invalid"));
    }
    let id = Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!("packet_questions:{}", string(packet, "id")?).as_bytes(),
    );
    let key = format!("exec:{id}");
    let url = &packet["snapshot"]["destination"]["application_url"];
    if let Some(mut value) = get(tx, &key).await? {
        if value["cancelled"] == true
            || matches!(
                value["state"].as_str(),
                Some(
                    "REJECTED"
                        | "FAILED_FINAL"
                        | "SUBMITTED_CONFIRMED"
                        | "SUBMISSION_UNKNOWN"
                        | "PAUSED"
                )
            )
        {
            return Err(Failure("application_paused_or_cancelled"));
        }
        if value["packet_id"] != packet["id"] || value["question_only"] != true {
            return Err(Failure("packet_execution_binding_conflict"));
        }
        if value["normalized_url"] != *url
            || value["profile_version"] != packet["candidate_profile_version"]
            || value["employer"] != packet["snapshot"]["company_name"]
            || value["role"] != packet["snapshot"]["job_title"]
        {
            value["normalized_url"] = url.clone();
            value["profile_version"] = packet["candidate_profile_version"].clone();
            value["employer"] = packet["snapshot"]["company_name"].clone();
            value["role"] = packet["snapshot"]["job_title"].clone();
            value["approved_answer_revisions"] = json!({});
            value["revision"] = json!(
                number(&value, "revision")?
                    .checked_add(1)
                    .ok_or_else(invalid)?
            );
            put(tx, &key, &value).await?;
        }
        if value["state"] == "PREPARING" {
            value = move_intent(tx, value, "owner_question_requested").await?;
        }
        return Ok(value);
    }
    let value = json!({"id":id,"attempt_id":Uuid::new_v4(),"job_id":packet["job_id"],"platform":packet["platform"],"role":packet["snapshot"]["job_title"],"employer":packet["snapshot"]["company_name"],"normalized_url":url,"state":"NEEDS_INPUT","revision":1,"history":[],"evidence":[],"profile_version":packet["candidate_profile_version"],"approved_answer_revisions":{},"packet_id":packet["id"],"question_only":true,"fence":0,"attempts":0,"cancelled":false,"lease_until":null,"available_at":now.to_rfc3339(),"heartbeat_at":null,"diagnostic":"waiting_for_owner_answer","created_at":now.to_rfc3339()});
    put(tx, &key, &value).await?;
    Ok(value)
}
fn answer_type(field: &Value) -> Result<&'static str> {
    static AVAILABILITY: LazyLock<crate::legacy_regex::Regex> = LazyLock::new(|| {
        crate::legacy_regex::Regex::new(r"interview|availability|available.*(?:week|date)", true)
    });
    Ok(if AVAILABILITY.is_match(string(field, "question")?)? {
        "availability"
    } else if field["options"].as_array().is_some_and(|a| !a.is_empty())
        || field["field_type"] == "yes_no"
    {
        "choice"
    } else {
        "text"
    })
}
pub(crate) fn message_text(q: &Value) -> Result<String> {
    let options = q["options"]
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .map(|v| v.as_str().ok_or_else(invalid))
        .collect::<Result<Vec<_>>>()?
        .join(" / ");
    let hint = if q["answer_type"] == "availability" {
        if options.is_empty() {
            "YYYY-MM-DDTHH:MM Area/City (for example Asia/Kolkata)".into()
        } else {
            format!("exact option + ' | ' + date/time/time zone, or No. Options: {options}")
        }
    } else if options.is_empty() {
        string(q, "answer_type")?.into()
    } else {
        options
    };
    Ok(format!(
        "{} — {}\nQuestion: {}\nApplication: {}\nPacket: {}\n{}\nExpected: {hint}\nReply to THIS message with your verified factual answer. This answers only this application; reuse needs separate approval. A fresh form review is required before filling.",
        string(q, "employer")?,
        string(q, "role")?,
        string(q, "question")?,
        string(q, "execution_id")?,
        string(q, "packet_id")?,
        string(q, "job_url")?
    ))
}
pub(crate) async fn envelope(
    tx: &mut Transaction<'_, Postgres>,
    packet: &Value,
    execution: &mut Value,
    field: &Value,
    observed: &Value,
    task: &Value,
    now: DateTime<Utc>,
) -> Result<Value> {
    crate::missing_contract::permitted(string(field, "question")?, "")?;
    let id = Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!(
            "{}:{}:{}:{}",
            string(execution, "id")?,
            string(field, "id")?,
            number(packet, "revision")?,
            string(&packet["snapshot"], "context_digest")?
        )
        .as_bytes(),
    );
    let key = format!("exec_q:{id}");
    let mut value = if let Some(mut value) = get(tx, &key).await? {
        if matches!(value["state"].as_str(), Some("pending" | "sent"))
            && timestamp(&value["expires_at"])? <= now
        {
            let mut expired = value["expired_message_ids"]
                .as_array()
                .cloned()
                .unwrap_or_default();
            expired.extend(
                value["message_ids"]
                    .as_array()
                    .ok_or_else(invalid)?
                    .iter()
                    .cloned(),
            );
            let start = expired.len().saturating_sub(50);
            value["expired_message_ids"] = json!(&expired[start..]);
            value["message_ids"] = json!([]);
            value["delivery_lease"] = Value::Null;
            value["state"] = json!("pending");
            value["expires_at"] = json!((now + chrono::Duration::days(2)).to_rfc3339());
            *execution =
                move_intent(tx, execution.clone(), "owner_reconfirmation_required").await?;
        }
        value
    } else {
        let value = json!({"id":id,"execution_id":execution["id"],"packet_id":packet["id"],"field_id":field["id"],"packet_revision":packet["revision"],"profile_version":packet["candidate_profile_version"],"context_digest":packet["snapshot"]["context_digest"],"question":field["question"],"options":field["options"],"answer_type":answer_type(field)?,"max_characters":field["max_characters"],"employer":packet["snapshot"]["company_name"],"role":packet["snapshot"]["job_title"],"job_url":execution["normalized_url"],"state":"pending","message_ids":[],"answer":null,"reuse_approved":false,"answer_expires_at":null,"expires_at":(now+chrono::Duration::days(2)).to_rfc3339(),"delivery_lease":null});
        if message_text(&value)?.chars().count() > 4000 {
            return Err(Failure("telegram_question_too_long_manual_required"));
        }
        *execution = move_intent(tx, execution.clone(), "waiting_for_owner_answer").await?;
        value
    };
    if observed.is_object() {
        value["form_kind"] = observed["kind"].clone();
        value["form_semantic_key"] = field["provenance"]["form_semantic_key"].clone();
    }
    if task.is_object() {
        value["extension_task_id"] = task["id"].clone();
    }
    put(tx, &key, &value).await?;
    Ok(value)
}

pub(super) async fn ask(
    tx: &mut Transaction<'_, Postgres>,
    task: Value,
    settings: &Settings,
    packets: &crate::packet_service::Settings,
    services: Services<'_>,
    now: DateTime<Utc>,
) -> Result<Value> {
    if task_terminal(&task)
        || matches!(
            task["state"].as_str(),
            Some("PAUSED" | "FILL_AUTHORIZED" | "FILLING")
        )
    {
        return Err(Failure("extension_task_not_waiting_for_answers"));
    }
    let mut packet = tasks::fresh(tx, &task, settings, packets, now).await?;
    let id = task["plan_id"]
        .as_str()
        .and_then(|s| s.parse().ok())
        .ok_or(Failure("fresh_form_inspection_required"))?;
    let plan = form_service::load(tx, id).await?;
    form_review::fresh(tx, &plan, settings, packets, services).await?;
    let observed = plan["inspection"]["fields"]
        .as_array()
        .ok_or(Failure("invalid_browser_form_record"))?;
    let actions = plan["actions"]
        .as_array()
        .ok_or(Failure("invalid_browser_form_record"))?;
    let mut requested = Vec::new();
    for control in observed {
        if !actions
            .iter()
            .any(|a| a["field_id"] == control["field_id"] && a["needs_input"] == true)
            || matches!(
                control["kind"].as_str(),
                Some("file" | "checkbox" | "radio")
            )
            || ["label", "group_label"].iter().any(|k| {
                control[k]
                    .as_str()
                    .is_some_and(|s| s.chars().count() >= 160)
            })
        {
            continue;
        }
        let text = tasks::field_question(control)?;
        if crate::missing_contract::permitted(&text, "").is_err() {
            continue;
        }
        let mut occurrences = 0;
        for other in observed {
            if tasks::field_question(other)? == text {
                occurrences += 1;
            }
        }
        if occurrences > 1 {
            continue;
        }
        let fields = packet["fields"].as_array().ok_or_else(invalid)?;
        let matches = fields
            .iter()
            .filter(|f| {
                f["question"] == text
                    && (f["provenance"]["form_semantic_key"].is_null()
                        || f["provenance"]["form_semantic_key"] == control["semantic_key"])
            })
            .collect::<Vec<_>>();
        if matches.len() > 1 {
            continue;
        }
        let field = if let Some(field) = matches.first() {
            if field["human_answer"]
                .as_str()
                .is_some_and(|s| !s.is_empty())
                && field["review_status"] == "reviewed"
            {
                continue;
            }
            (*field).clone()
        } else {
            let options = control["options"]
                .as_array()
                .ok_or(Failure("invalid_browser_form_record"))?;
            let question = crate::packet_contract::question(
                json!({"question":text,"field_type":if !options.is_empty() && options.len()<=50{"multiple_choice"}else{"text"},"options":if options.len()<=50{json!(options)}else{json!([])},"required":control["required"],"max_characters":control["max_length"]}),
            )?;
            let at = storage::now(tx).await?;
            packet = crate::packet_mutation::observed_question_in(
                tx,
                string(&packet, "id")?.parse().map_err(|_| invalid())?,
                number(&packet, "revision")?
                    .try_into()
                    .map_err(|_| invalid())?,
                question,
                packets,
                services.answers,
                at,
            )
            .await?;
            packet["fields"]
                .as_array()
                .ok_or_else(invalid)?
                .iter()
                .find(|f| f["question"] == text)
                .cloned()
                .ok_or_else(invalid)?
        };
        let id = string(&field, "id")?
            .parse::<Uuid>()
            .map_err(|_| invalid())?;
        let mut provenance = field["provenance"].clone();
        provenance["form_semantic_key"] = control["semantic_key"].clone();
        provenance["form_page_step"] = control["page_step"].clone();
        provenance["form_section"] = control["section"].clone();
        if provenance != field["provenance"] {
            let packet_id = string(&packet, "id")?.parse().map_err(|_| invalid())?;
            let revision = number(&packet, "revision")?
                .try_into()
                .map_err(|_| invalid())?;
            let claim =
                crate::packet_mutation::locked_in(tx, packet_id, revision, true, packets).await?;
            let at = storage::now(tx).await?;
            // The field trigger increments the parent revision when edited outside
            // a packet amendment. Archive the current revision before that edit.
            crate::packet_archive::advance_in(tx, &claim.raw, &claim.prior_fields, revision, at)
                .await?;
            let ack: Option<Value> = sqlx::query_scalar(
                "UPDATE application_packet_fields SET provenance=$2 WHERE id=$1 AND packet_id=$3 RETURNING provenance",
            )
            .bind(id)
            .bind(&provenance)
            .bind(packet_id)
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?;
            if ack.as_ref() != Some(&provenance) {
                return Err(Failure("packet_write_ack_failed"));
            }
            packet = crate::packet_mutation::finish_in(
                tx,
                packet_id,
                &packet["snapshot"],
                &claim.raw,
                "answer_edited",
                packets,
                at,
            )
            .await?;
        }
        requested.push((id, control.clone()));
    }
    let at = storage::now(tx).await?;
    packet = crate::packet_service::read_in(
        tx,
        string(&packet, "id")?.parse().map_err(|_| invalid())?,
        packets,
        at,
    )
    .await?;
    let mut envelopes = Vec::new();
    if !requested.is_empty() {
        let mut execution = intent(tx, &packet, at).await?;
        for (id, control) in requested {
            let field = packet["fields"]
                .as_array()
                .ok_or_else(invalid)?
                .iter()
                .find(|f| f["id"] == json!(id))
                .ok_or_else(invalid)?;
            let at = storage::now(tx).await?;
            envelopes
                .push(envelope(tx, &packet, &mut execution, field, &control, &task, at).await?);
        }
    }
    let mut revisions = json!({});
    for field in packet["fields"].as_array().ok_or_else(invalid)? {
        revisions[string(field, "id")?] = field["answer_revision"].clone();
    }
    let at = storage::now(tx).await?;
    let task=tasks::move_in(tx,task,"NEEDS_INPUT","owner_questions_queued",json!({"packet_revision":packet["revision"],"field_answer_revisions":revisions,"plan_id":null,"authorization_id":null}),at).await?;
    Ok(json!({"task":task,"questions":envelopes,"submitted":false}))
}
use super::*;

pub(super) async fn bridge(
    tx: &mut Transaction<'_, Postgres>,
    mut packet: Value,
    plan: &mut Value,
    packets: &crate::packet_service::Settings,
    services: Services<'_>,
) -> Result<()> {
    if packet["platform"] != "naukri" {
        return Ok(());
    }
    // An owner-selected unrelated page must not become a Naukri questionnaire.
    let original = packet["snapshot"]["original_job_url"]
        .as_str()
        .unwrap_or("");
    if !reqwest::Url::parse(original).ok().is_some_and(|u| {
        u.scheme() == "https"
            && matches!(u.host_str(), Some("naukri.com" | "www.naukri.com"))
            && u.path().starts_with("/job-listings-")
    }) {
        return Ok(());
    }
    let application = string(&packet, "id")?.parse().map_err(|_| invalid())?;
    let fields = plan["inspection"]["fields"]
        .as_array()
        .ok_or(Failure("invalid_browser_form_record"))?
        .clone();
    for field in fields {
        let unresolved = plan["actions"]
            .as_array()
            .ok_or(Failure("invalid_browser_form_record"))?
            .iter()
            .any(|a| a["field_id"] == field["field_id"] && a["needs_input"] == true);
        if field["required"] != true || !unresolved || field["kind"] == "file" {
            continue;
        }
        let question = field["group_label"]
            .as_str()
            .filter(|s| !s.is_empty())
            .or_else(|| field["label"].as_str())
            .ok_or(Failure("invalid_browser_form_input"))?;
        if crate::missing_contract::permitted(question, "").is_err() {
            continue;
        }
        if packet["fields"]
            .as_array()
            .ok_or_else(invalid)?
            .iter()
            .any(|f| f["question"] == question)
        {
            continue;
        }
        let options = field["options"]
            .as_array()
            .ok_or(Failure("invalid_browser_form_input"))?;
        let question = crate::packet_contract::question(
            json!({"question":question,"field_type":if options.is_empty(){"text"}else{"multiple_choice"},"options":options,"max_characters":field["max_length"]}),
        )?;
        let revision = number(&packet, "revision")?
            .try_into()
            .map_err(|_| invalid())?;
        let now = storage::now(tx).await?;
        packet = crate::packet_mutation::observed_question_in(
            tx,
            application,
            revision,
            question,
            packets,
            services.answers,
            now,
        )
        .await?;
    }
    plan["packet_revision"] = packet["revision"].clone();
    Ok(())
}
