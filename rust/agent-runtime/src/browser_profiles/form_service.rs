//! Transactional native form preparation. No browser or provider IO is performed here.
use super::*;
use crate::{packet_contract, packet_fields, profile_store, project_context, resources};
use automated_apply_domain::text::folded;
#[derive(Clone, Copy)]
pub struct Services<'a> {
    pub answers: &'a crate::answer_service::Settings,
    pub resumes: &'a crate::private_resume::Settings,
}
pub(super) async fn listing(tx: &mut Transaction<'_, Postgres>) -> Result<Value> {
    let values:Vec<Value>=sqlx::query_scalar("SELECT value FROM owner_preferences WHERE starts_with(key,'fill_plan:') ORDER BY created_at DESC,key LIMIT 20").fetch_all(&mut **tx).await.map_err(db)?;
    Ok(json!(
        values
            .into_iter()
            .map(|v| forms::normalize(forms::Kind::Plan, v)
                .map_err(|_| Failure("invalid_browser_form_record")))
            .collect::<Result<Vec<_>>>()?
    ))
}
pub(super) async fn load(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Value> {
    let raw = get(tx, &format!("fill_plan:{id}"))
        .await?
        .ok_or(Failure("fill_plan_not_found"))?;
    forms::normalize(forms::Kind::Plan, raw).map_err(|_| Failure("invalid_browser_form_record"))
}
pub(super) async fn save(tx: &mut Transaction<'_, Postgres>, plan: &Value) -> Result<()> {
    put(tx, &format!("fill_plan:{}", string(plan, "id")?), plan).await
}
pub(super) async fn audit(
    tx: &mut Transaction<'_, Postgres>,
    plan: &Value,
    event: &str,
    results: &Value,
) -> Result<()> {
    let id = string(plan, "id")?;
    let key = format!("browser:{id}:{event}");
    let hash = crate::python_json::digest(&json!([id, event]));
    let value = json!({"plan_id":plan["id"],"application_id":plan["application_id"],"status":event,"fields":results,"submitted":false});
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO agent_operations(key,actor,command,payload_hash,result,created_at) VALUES($1,'owner:primary',$2,$3,$4,clock_timestamp()) RETURNING result").bind(key).bind(format!("browser:{event}")).bind(hash).bind(&value).fetch_optional(&mut **tx).await.map_err(db)?;
    if saved.as_ref() != Some(&value) {
        return Err(Failure("browser_profile_write_ack_failed"));
    }
    Ok(())
}
pub(crate) async fn projects(tx: &mut Transaction<'_, Postgres>) -> Result<String> {
    let records:Vec<(String,Value)>=sqlx::query_as("SELECT key,value FROM owner_preferences WHERE key='candidate_configuration_v1' OR starts_with(key,'candidate_project-') OR starts_with(key,'document_project-') ORDER BY key LIMIT 10001").fetch_all(&mut **tx).await.map_err(db)?;
    if records.len() > 10000 {
        return Err(Failure("browser_profile_inventory_limit"));
    }
    project_context::Snapshot::from_records(&records.into_iter().collect())?.browser_digest()
}
pub(super) async fn pdf(
    tx: &mut Transaction<'_, Postgres>,
    packet: &Value,
    services: Services<'_>,
) -> Result<Option<Vec<u8>>> {
    let selected = &packet["snapshot"]["resume"]["selected"];
    if selected.is_null() || selected["confirmed"] != true {
        return Ok(None);
    }
    let resource = selected["resource_id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or(Failure("canonical_pdf_changed"))?;
    let row:Option<(Vec<u8>,String)>=sqlx::query_as("SELECT p.ciphertext,p.sha256 FROM candidate_resources r JOIN private_resumes p ON r.url='private-resume:'||p.id::text AND p.resource_id=r.id WHERE r.id=$1 AND r.candidate_profile_id=$2 AND r.user_confirmed AND r.source_type='private_upload' AND p.confirmed").bind(resource).bind(string(packet,"candidate_profile_id")?.parse::<Uuid>().map_err(|_|invalid())?).fetch_optional(&mut **tx).await.map_err(db)?;
    row.map(|(raw, hash)| services.resumes.verified(&raw, &hash))
        .transpose()
}
pub(super) async fn inspect(
    tx: &mut Transaction<'_, Postgres>,
    application: Uuid,
    inspection: Value,
    settings: &Settings,
    packets: &crate::packet_service::Settings,
    services: Services<'_>,
) -> Result<Value> {
    let inspection = forms::normalize(forms::Kind::Inspection, inspection)?;
    let now = storage::now(tx).await?;
    let (packet, url) = commands::context(tx, application, settings, packets, now).await?;
    let readonly = inspection["state"] == "manual_required"
        || !matches!(
            inspection["challenge_state"].as_str(),
            Some("NONE" | "MANUALLY_RESOLVED_AND_SITE_VERIFIED")
        );
    if inspection["url"] != url
        || !matches!(
            inspection["state"].as_str(),
            Some("ready" | "validation_errors")
        ) && !readonly
    {
        return Err(Failure("manual_intervention_or_redirect"));
    }
    let profile = profile_store::get(tx).await?.value;
    let job = string(&packet, "job_id")?
        .parse::<Uuid>()
        .map_err(|_| invalid())?;
    let resources:Vec<Value>=sqlx::query_scalar("SELECT to_jsonb(r) FROM candidate_resources r WHERE candidate_profile_id=$1 ORDER BY id LIMIT 10001").bind(string(&profile,"id")?.parse::<Uuid>().map_err(|_|invalid())?).fetch_all(&mut **tx).await.map_err(db)?;
    if resources.len() > 10000 {
        return Err(Failure("browser_profile_inventory_limit"));
    }
    let resources = resources
        .into_iter()
        .map(|v| serde_json::from_value::<resources::Resource>(v).map_err(|_| invalid()))
        .collect::<Result<Vec<_>>>()?;
    let selected = packet["snapshot"]["resume"]["selected"]["resource_id"]
        .as_str()
        .map(|s| s.parse::<Uuid>().map_err(|_| invalid()))
        .transpose()?;
    let resume = resources::select_resume(&resources, selected)?;
    let mut plan = json!({"version":1,"id":Uuid::new_v4(),"application_id":application,"job_id":job,"mode":"manual_extension","target_url":url,"inspection":inspection,"context_digest":packet["snapshot"]["context_digest"],"packet_revision":packet["revision"],"project_digest":projects(tx).await?,"actions":[],"approved_fields":[],"expires_at":(now+chrono::Duration::minutes(10)).to_rfc3339(),"state":if readonly{"read_only"}else{"preview"}});
    let mut actions = Vec::new();
    let fields = plan["inspection"]["fields"]
        .as_array()
        .ok_or(Failure("invalid_browser_form_input"))?
        .clone();
    let packet_fields = packet["fields"].as_array().ok_or_else(invalid)?;
    for field in fields {
        let mut action = json!({"job_id":job,"application_id":application,"target_url":url,"field_id":field["field_id"],"kind":field["kind"],"candidate_version":profile["version"],"preview_only":field["preview_only"],"value":null,"evidence":[],"requires_review":false,"needs_input":true});
        if !forms::label_permitted(&field, &plan["inspection"])? {
            actions.push(action);
            continue;
        }
        let label = field["label"].as_str().unwrap_or("");
        let kind = field["kind"]
            .as_str()
            .ok_or(Failure("invalid_browser_form_input"))?;
        if kind == "file" {
            static RESUME: LazyLock<crate::legacy_regex::Regex> =
                LazyLock::new(|| crate::legacy_regex::Regex::new(r"\b(?:resume|cv)\b", true));
            static COVER: LazyLock<crate::legacy_regex::Regex> =
                LazyLock::new(|| crate::legacy_regex::Regex::new("cover letter", true));
            if RESUME.is_match(&format!(
                "{} {label}",
                field["section"].as_str().unwrap_or("")
            ))? && !COVER.is_match(label)?
                && let Some(bytes) = pdf(tx, &packet, services).await?
            {
                action["safe_reference"] =
                    json!(format!("canonical_pdf:{:x}", Sha256::digest(bytes)));
                action["evidence"] = json!([format!(
                    "candidate_resource:{}",
                    string(&packet["snapshot"]["resume"]["selected"], "resource_id")?
                )]);
                action["needs_input"] = json!(false);
            }
            actions.push(action);
            continue;
        }
        if forms::inert_label(label)? {
            actions.push(action);
            continue;
        }
        let mut question = tasks::field_question(&field)?;
        static NAME: LazyLock<crate::legacy_regex::Regex> =
            LazyLock::new(|| crate::legacy_regex::Regex::new(r"\Aname[\s:*]*\z", true));
        if NAME.is_match(&question)? {
            question = "Full name".into();
        }
        let options = field["options"]
            .as_array()
            .ok_or(Failure("invalid_browser_form_input"))?;
        let q = packet_contract::question(
            json!({"question":question,"field_type":if kind=="select" && options.len()<=50{"multiple_choice"}else if kind=="textarea"{"textarea"}else{"text"},"required":field["required"],"max_characters":field["max_length"],"options":if kind=="select" && options.len()<=50{json!(options)}else{json!([])}}),
        )?;
        let mut matching = Vec::new();
        for saved in packet_fields {
            if folded(string(saved, "question")?.trim()) != folded(question.trim())
                || !field["semantic_key"].is_null()
                    && !saved["provenance"]["form_semantic_key"].is_null()
                    && saved["provenance"]["form_semantic_key"] != field["semantic_key"]
                || !saved["provenance"]["form_semantic_key"].is_null()
                    && saved["provenance"]["form_semantic_key"] != field["semantic_key"]
                || saved["human_answer"].as_str().is_none_or(str::is_empty)
                || saved["validation_status"] != "draft_ready"
            {
                continue;
            }
            if !saved["provenance"]["answer_expires_at"].is_null()
                && timestamp(&saved["provenance"]["answer_expires_at"])? <= now
            {
                continue;
            }
            if packet_fields::value_error(&q, saved["human_answer"].as_str())?.is_none() {
                matching.push(saved);
            }
        }
        if matching.len() > 1 {
            actions.push(action);
            continue;
        }
        if let Some(saved) = matching.first() {
            action["value"] = saved["human_answer"].clone();
            action["evidence"] = json!([format!(
                "reviewed_packet_answer:{}:{}",
                string(saved, "id")?,
                number(saved, "answer_revision")?
            )]);
            action["requires_review"] = json!(true);
            action["needs_input"] = json!(false);
            if saved["review_status"] != "reviewed" {
                action["preview_only"] = json!(true);
                actions.push(action);
                continue;
            }
        } else {
            static HISTORY: LazyLock<crate::legacy_regex::Regex> = LazyLock::new(|| {
                crate::legacy_regex::Regex::new(
                    r"employment|work experience|education|previous employer|experience [0-9]",
                    true,
                )
            });
            if HISTORY.is_match(field["section"].as_str().unwrap_or(""))? {
                actions.push(action);
                continue;
            }
            let prepared = packet_fields::prepare_generation(
                q.clone(),
                job,
                Some(&profile),
                Some(&resume),
                "user_provided",
                false,
            )?;
            let built = if let Some(request) = prepared.resolution.as_ref() {
                let result = crate::answer_service::form_in(
                    tx,
                    request.clone(),
                    services.answers,
                    application,
                )
                .await?;
                packet_fields::resolved(prepared, &result, &profile)?
            } else {
                prepared.field
            };
            if let Some(id) = built["provenance"]["missing_input_id"].as_str() {
                let key = format!("needs_input:{id}");
                if let Some(missing) = get(tx, &key).await? {
                    action["missing_input_id"] = json!(id);
                    action["missing_input_version"] = missing["version"].clone();
                }
            }
            if built["validation_status"] == "draft_ready"
                && built["effective_answer"]
                    .as_str()
                    .is_some_and(|s| !s.is_empty())
            {
                action["value"] = built["effective_answer"].clone();
                action["requires_review"] = built["requires_review"].clone();
                let refs = built["provenance"]["evidence_references"]
                    .as_array()
                    .ok_or_else(invalid)?;
                let mut evidence = refs
                    .iter()
                    .map(|r| {
                        Ok(format!(
                            "{}:{}",
                            string(r, "source_type")?,
                            string(r, "source_id")?
                        ))
                    })
                    .collect::<Result<Vec<_>>>()?;
                if evidence.is_empty() && built["provenance"]["source"] != "missing" {
                    evidence.push(format!(
                        "{}:{}",
                        string(&built["provenance"], "source")?,
                        string(&profile, "id")?
                    ));
                }
                action["evidence"] = json!(evidence);
            }
        }
        if let Some(value) = action["value"].as_str() {
            action["value"] = json!(forms::control_value(
                &field,
                value,
                action["evidence"].as_array().is_some_and(|v| !v.is_empty())
            )?);
        }
        if action["value"].as_str().is_some_and(|s| !s.is_empty())
            && action["evidence"].as_array().is_some_and(|v| !v.is_empty())
        {
            action["needs_input"] = json!(false);
            if !action["evidence"]
                .as_array()
                .unwrap()
                .iter()
                .any(|v| v.as_str().is_some_and(|s| s.starts_with("owner_answer:")))
            {
                action["missing_input_id"] = Value::Null;
                action["missing_input_version"] = Value::Null;
            }
        }
        actions.push(action);
    }
    plan["actions"] = json!(actions);
    super::form_questions::bridge(tx, packet.clone(), &mut plan, packets, services).await?;
    let plan = forms::normalize(forms::Kind::Plan, plan)?;
    save(tx, &plan).await?;
    audit(tx, &plan, "form_inspected", &json!([])).await?;
    Ok(plan)
}
pub(super) async fn prepare_page(
    tx: &mut Transaction<'_, Postgres>,
    inspection: &Value,
    title: Option<&str>,
    settings: &Settings,
    packets: &crate::packet_service::Settings,
    services: Services<'_>,
) -> Result<Value> {
    let profile = profile_store::get(tx).await?.value;
    let confirmation = get(tx, "phase1_profile_confirmation")
        .await?
        .unwrap_or(Value::Null);
    if confirmation["profile_id"] != profile["id"]
        || confirmation["profile_version"] != profile["version"]
        || confirmation["confirmed_at"]
            .as_str()
            .is_none_or(str::is_empty)
    {
        return Err(Failure("profile_review_required"));
    }
    let url = inspection["url"]
        .as_str()
        .and_then(|s| crate::packet_platform::manual_page(s, &packets.policy))
        .ok_or(Failure("unsupported_application_form"))?;
    if !matches!(
        inspection["state"].as_str(),
        Some("ready" | "validation_errors" | "manual_required")
    ) {
        return Err(Failure("unsupported_application_form"));
    }
    let job: Option<Uuid> = sqlx::query_scalar("SELECT id FROM jobs WHERE job_url=$1 FOR UPDATE")
        .bind(&url)
        .fetch_optional(&mut **tx)
        .await
        .map_err(db)?;
    let job = if let Some(id) = job {
        id
    } else {
        let id = Uuid::new_v4();
        let label = title
            .filter(|s| !s.is_empty())
            .map(str::to_owned)
            .unwrap_or_else(|| url.rsplit('/').next().unwrap_or("Application").to_owned());
        let ack:Option<Uuid>=sqlx::query_scalar("INSERT INTO jobs(id,title,job_url,application_url,source_platform,source_verification_status,discovery_metadata) VALUES($1,$2,$3,$3,'owner_extension','owner_selected','{\"capture\":\"explicit_extension_gesture\",\"employer_identity_verified\":false}') ON CONFLICT DO NOTHING RETURNING id").bind(id).bind(label).bind(&url).fetch_optional(&mut **tx).await.map_err(db)?;
        ack.ok_or(Failure("application_page_conflict"))?
    };
    let owner = string(&profile, "id")?
        .parse::<Uuid>()
        .map_err(|_| invalid())?;
    let job_state: (String, Option<String>) =
        sqlx::query_as("SELECT status,application_url FROM jobs WHERE id=$1")
            .bind(job)
            .fetch_one(&mut **tx)
            .await
            .map_err(db)?;
    if matches!(job_state.0.as_str(), "applied" | "archived")
        || job_state.1.as_deref() != Some(url.as_str())
    {
        return Err(Failure("application_not_eligible"));
    }
    let existing: Option<Uuid> = sqlx::query_scalar(
        "SELECT id FROM application_packets WHERE job_id=$1 AND candidate_profile_id=$2",
    )
    .bind(job)
    .bind(owner)
    .fetch_optional(&mut **tx)
    .await
    .map_err(db)?;
    let id = if let Some(id) = existing {
        id
    } else {
        let input = packet_contract::normalize(
            json!({"idempotency_key":format!("extension_{}_{}",owner.simple(),job.simple())}),
            true,
        )?;
        let now = storage::now(tx).await?;
        let packet =
            crate::packet_service::create_in(tx, job, &input, packets, services.answers, now)
                .await?;
        string(&packet, "id")?.parse().map_err(|_| invalid())?
    };
    inspect(tx, id, inspection.clone(), settings, packets, services).await
}
pub(super) async fn dispatch(
    tx: &mut Transaction<'_, Postgres>,
    command: &native::Command,
    settings: &Settings,
    packets: &crate::packet_service::Settings,
    services: Services<'_>,
    now: DateTime<Utc>,
) -> Result<Value> {
    let v = &command.value;
    let extension = settings
        .extension
        .as_deref()
        .ok_or(Failure("extension_identity_not_authorized"))?;
    let key = format!("manual_form:{extension}:{}", command.request_id);
    let hash = command.payload_hash.clone();
    let previous: Option<String> =
        sqlx::query_scalar("SELECT payload_hash FROM agent_operations WHERE key=$1")
            .bind(&key)
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?;
    if let Some(previous) = previous {
        return Err(Failure(if previous == hash {
            "form_request_already_consumed"
        } else {
            "native_request_conflict"
        }));
    }
    if command.name() == "record_form_fill" {
        native::authenticate(tx, command).await?;
    } else {
        commands::require_profile(tx, command, now).await?;
    }
    let mut nested = sqlx::Connection::begin(&mut **tx).await.map_err(db)?;
    let operation = async {
        if matches!(command.name(), "authorize_form" | "record_form_fill") && !settings.fill_enabled
        {
            return Err(Failure("manual_form_not_authorized"));
        }
        if command.name() == "record_form_fill" {
            let data = form_receipts::record(&mut nested, command, v["receipt"].clone()).await?;
            if !v["chrome_command_id"].is_null() {
                let at = storage::now(&mut nested).await?;
                commands::require_profile(&mut nested, command, at).await?;
            }
            return Ok(data);
        }
        let mut task = if let Some(id) = v["task_id"].as_str() {
            let task = tasks::load(
                &mut nested,
                id.parse().map_err(|_| Failure("extension_task_required"))?,
            )
            .await?;
            tasks::bound(&task, v, command.name() == "inspect_form")?;
            if command.name() == "authorize_form" && task["plan_id"] != v["plan_id"] {
                return Err(Failure("extension_task_plan_mismatch"));
            }
            Some(task)
        } else {
            None
        };
        let mut plan = match command.name() {
            "prepare_form_answers" => {
                if task.is_some() {
                    return Err(Failure("bound_task_requires_saved_application_inspection"));
                }
                let observation =
                    forms::normalize(forms::Kind::Inspection, v["inspection"].clone())?;
                prepare_page(
                    &mut nested,
                    &observation,
                    v["title"].as_str(),
                    settings,
                    packets,
                    services,
                )
                .await?
            }
            "inspect_form" => {
                let application = command
                    .id("application_id")
                    .map_err(|_| Failure("application_and_inspection_required"))?;
                if task
                    .as_ref()
                    .is_some_and(|t| t["application_id"] != json!(application))
                {
                    return Err(Failure("extension_task_plan_mismatch"));
                }
                inspect(
                    &mut nested,
                    application,
                    v["inspection"].clone(),
                    settings,
                    packets,
                    services,
                )
                .await?
            }
            "authorize_form" => {
                let id = command
                    .id("plan_id")
                    .map_err(|_| Failure("plan_required"))?;
                let current = load(&mut nested, id).await?;
                if current["profile_binding_id"] != v["profile_binding_id"]
                    || current["browser_session_id"] != v["browser_session_id"]
                    || current["tab_id"].is_null()
                    || current["tab_id"] != v["tab_id"]
                {
                    return Err(Failure("extension_tab_binding_mismatch"));
                }
                if !current["extension_task_id"].is_null()
                    && task
                        .as_ref()
                        .is_none_or(|t| t["id"] != current["extension_task_id"])
                {
                    return Err(Failure("extension_task_required"));
                }
                if let Some(value) = task.as_ref() {
                    let at = storage::now(&mut nested).await?;
                    tasks::fresh(&mut nested, value, settings, packets, at).await?;
                    if !matches!(
                        value["state"].as_str(),
                        Some("FORM_INSPECTED" | "NEEDS_INPUT" | "ANSWERS_REVIEWED")
                    ) {
                        return Err(Failure("extension_task_not_ready_for_review"));
                    }
                    if !matches!(
                        value["challenge_state"].as_str(),
                        Some("NONE" | "MANUALLY_RESOLVED_AND_SITE_VERIFIED")
                    ) {
                        return Err(Failure("challenge_fresh_review_required"));
                    }
                }
                form_review::review(
                    &mut nested,
                    id,
                    &v["field_ids"],
                    settings,
                    packets,
                    services,
                )
                .await?;
                let mut plan =
                    form_review::consume(&mut nested, id, settings, packets, services).await?;
                if let Some(value) = task.take() {
                    plan["extension_authorization_id"] = json!(command.request_id);
                    save(&mut nested, &plan).await?;
                    let at = storage::now(&mut nested).await?;
                    let value = tasks::move_in(
                        &mut nested,
                        value,
                        "ANSWERS_REVIEWED",
                        "exact_fields_reviewed",
                        json!({}),
                        at,
                    )
                    .await?;
                    let value = tasks::move_in(
                        &mut nested,
                        value,
                        "FILL_AUTHORIZED",
                        "single_use_authorization",
                        json!({"authorization_id":command.request_id}),
                        at,
                    )
                    .await?;
                    task = Some(
                        tasks::move_in(
                            &mut nested,
                            value,
                            "FILLING",
                            "approved_fill_pending_receipt",
                            json!({}),
                            at,
                        )
                        .await?,
                    );
                }
                plan
            }
            _ => return Err(Failure("browser_form_inspection_unavailable")),
        };
        if matches!(command.name(), "inspect_form" | "prepare_form_answers") {
            if let Some(value) = task.take() {
                let (value, attached) =
                    form_review::attach(&mut nested, value, plan, settings, packets, services)
                        .await?;
                task = Some(value);
                plan = attached;
            }
            if v["tab_id"].is_null() {
                return Err(Failure("extension_tab_binding_mismatch"));
            }
            plan["profile_binding_id"] = v["profile_binding_id"].clone();
            plan["browser_session_id"] = v["browser_session_id"].clone();
            plan["tab_id"] = v["tab_id"].clone();
            save(&mut nested, &plan).await?;
        }
        if !v["chrome_command_id"].is_null() {
            let at = storage::now(&mut nested).await?;
            commands::require_profile(&mut nested, command, at).await?;
        }
        let mut data = json!({"plan":plan,"submitted":false});
        if let Some(task) = task {
            data["task"] = task;
        }
        Ok(data)
    }
    .await;
    match operation {
        Ok(value) => {
            let saved:Option<Value>=sqlx::query_scalar("INSERT INTO agent_operations(key,actor,command,payload_hash,result,created_at) VALUES($1,$2,$3,$4,'{\"status\":\"processed\",\"submitted\":false}',clock_timestamp()) RETURNING result").bind(key).bind(format!("chrome:{extension}")).bind(command.name()).bind(hash).fetch_optional(&mut *nested).await.map_err(db)?;
            if saved != Some(json!({"status":"processed","submitted":false})) {
                nested
                    .rollback()
                    .await
                    .map_err(|_| Failure("browser_profile_rollback_unconfirmed"))?;
                return Err(Failure("browser_profile_write_ack_failed"));
            }
            nested.commit().await.map_err(db)?;
            Ok(value)
        }
        Err(e) => {
            nested
                .rollback()
                .await
                .map_err(|_| Failure("browser_profile_rollback_unconfirmed"))?;
            if e == Failure("profile_command_expired") {
                let row = native::authenticate(tx, command).await?;
                let selected = selection(tx).await?;
                let at = storage::now(tx).await?;
                invalidation::expire(tx, Some((&row, &selected)), at).await?;
            }
            Err(e)
        }
    }
}
pub(crate) fn domain_denial(e: Failure) -> bool {
    matches!(
        e.0,
        "invalid_browser_form_input"
            | "fill_plan_not_found"
            | "fill_plan_stale"
            | "canonical_pdf_changed"
            | "invalid_field_approval"
            | "browser_fill_disabled"
            | "single_use_fill_authorization_required"
            | "execution_paused_or_cancelled"
            | "execution_not_ready_for_fill"
            | "extension_task_plan_mismatch"
            | "invalid_fill_receipt"
            | "manual_form_not_authorized"
            | "bound_task_requires_saved_application_inspection"
            | "application_and_inspection_required"
            | "plan_required"
            | "extension_task_not_ready_for_review"
            | "challenge_fresh_review_required"
            | "native_request_conflict"
            | "profile_review_required"
            | "unsupported_application_form"
            | "application_page_conflict"
            | "manual_intervention_or_redirect"
    )
}
