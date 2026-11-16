//! Durable task ownership and recovery. A task observation cannot grant a fill or submission.
use super::*;
pub fn next_action(state: &str) -> Result<&'static str> {
    Ok(match state {
        "PACKET_READY" => "Inspect this application step and review its answers.",
        "FORM_INSPECTED" => "Prepare and review answers for this step.",
        "NEEDS_INPUT" => "Answer the saved questions, then inspect and review this step again.",
        "ANSWERS_REVIEWED" => "Authorize the exact reviewed fields in the extension.",
        "FILL_AUTHORIZED" => "Fill only the approved fields in the bound tab.",
        "FILLING" => "Wait for retained-value verification, or pause to take over.",
        "FILLED_VERIFIED" => "Review the retained values and remaining manual fields on the site.",
        "READY_FOR_SUBMISSION" => {
            "Review the complete application on the site; submission is owner-operated."
        }
        "PAUSED" => "Resume, inspect the current step and authorize fresh fields.",
        "FAILED_RETRYABLE" => {
            "Check the connection and current tab, then resume with a fresh inspection."
        }
        "FAILED_FINAL" => "This task was cancelled or ended. Open a new reviewed task if needed.",
        "CHALLENGE_REQUIRED" => {
            "Complete the challenge manually. Fresh site verification, inspection and review are required."
        }
        "SUBMISSION_UNKNOWN" => "Check the employer receipt manually. Do not retry submission.",
        "SUBMITTED_CONFIRMED" => "Check the independently confirmed submission receipt.",
        _ => return Err(invalid()),
    })
}
pub fn navigation(value: &Value, url: &str) -> Option<String> {
    let u = reqwest::Url::parse(url).ok()?;
    if u.scheme() != "https"
        || !u.username().is_empty()
        || u.password().is_some()
        || u.fragment().is_some()
        || value["target_url"].as_str() != Some(url)
    {
        return None;
    }
    Some(url.to_owned())
}
pub fn field_question(field: &Value) -> Result<String> {
    let question = field["group_label"]
        .as_str()
        .filter(|s| !s.is_empty())
        .or_else(|| field["label"].as_str())
        .ok_or_else(invalid)?;
    let mut parts = Vec::new();
    for part in [
        field["page_step"].as_str(),
        field["section"].as_str(),
        Some(question),
    ]
    .into_iter()
    .flatten()
    {
        if !part.is_empty() && !parts.contains(&part) {
            parts.push(part);
        }
    }
    Ok(parts.join(": "))
}
pub fn validate(mut value: Value) -> Result<Value> {
    static MODEL: LazyLock<Value> = LazyLock::new(|| {
        serde_json::from_str(include_str!("../../schemas/extension-task.json"))
            .expect("frozen task contract")
    });
    static SCHEMA: LazyLock<jsonschema::Validator> = LazyLock::new(|| {
        let schema: Value = serde_json::from_str(include_str!("../../schemas/extension-task.json"))
            .expect("frozen task contract");
        jsonschema::draft202012::options()
            .should_validate_formats(true)
            .build(&schema)
            .expect("task DTO validator")
    });
    fn defaults(root: &Value, schema: &Value, value: &mut Value) {
        if let Some(reference) = schema["$ref"].as_str() {
            if let Some(schema) = reference.strip_prefix('#').and_then(|p| root.pointer(p)) {
                defaults(root, schema, value);
            }
            return;
        }
        if let (Some(properties), Some(object)) =
            (schema["properties"].as_object(), value.as_object_mut())
        {
            for (key, shape) in properties {
                if !object.contains_key(key)
                    && let Some(default) = shape.get("default")
                {
                    object.insert(key.clone(), default.clone());
                }
                if let Some(item) = object.get_mut(key) {
                    defaults(root, shape, item);
                }
            }
        }
    }
    defaults(&MODEL, &MODEL, &mut value);
    if !SCHEMA.is_valid(&value) {
        return Err(Failure("invalid_browser_task_record"));
    }
    Ok(value)
}
pub(super) fn identity(application: Uuid) -> Uuid {
    Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!("extension_task:{application}").as_bytes(),
    )
}
fn task_id(command: &native::Command) -> Result<Uuid> {
    command
        .id("task_id")
        .map_err(|_| Failure("extension_task_required"))
}
pub(super) async fn load(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Value> {
    let value = get(tx, &format!("ext_task:{id}"))
        .await?
        .ok_or(Failure("extension_task_not_found"))?;
    validate(value)
}
pub(super) async fn by_application(
    tx: &mut Transaction<'_, Postgres>,
    application: Uuid,
) -> Result<Value> {
    get(tx, &format!("ext_task:{}", identity(application)))
        .await?
        .map(validate)
        .transpose()
        .map(|v| v.unwrap_or(Value::Null))
}
pub(super) async fn listing(tx: &mut Transaction<'_, Postgres>) -> Result<Value> {
    prefix(tx, "ext_task:")
        .await?
        .into_iter()
        .rev()
        .map(|(_, v)| validate(v))
        .collect::<Result<Vec<_>>>()
        .map(|v| json!(v))
}
pub(super) async fn move_in(
    tx: &mut Transaction<'_, Postgres>,
    value: Value,
    state: &str,
    reason: &str,
    changes: Value,
    now: DateTime<Utc>,
) -> Result<Value> {
    move_reason_in(tx, value, state, Some(reason), changes, now).await
}
async fn move_reason_in(
    tx: &mut Transaction<'_, Postgres>,
    mut value: Value,
    state: &str,
    reason: Option<&str>,
    changes: Value,
    now: DateTime<Utc>,
) -> Result<Value> {
    for (k, v) in changes.as_object().ok_or_else(invalid)? {
        value[k] = v.clone();
    }
    value["state"] = json!(state);
    value["reason"] = json!(reason);
    value["next_action"] = json!(next_action(state)?);
    value["updated_at"] = json!(now.to_rfc3339());
    value["version"] = json!(
        number(&value, "version")?
            .checked_add(1)
            .ok_or_else(invalid)?
    );
    let value = validate(value)?;
    let id = string(&value, "id")?;
    let version = number(&value, "version")?;
    put(tx, &format!("ext_task:{id}"), &value).await?;
    let key = format!("extension:{id}:{version}");
    let hash = format!(
        "{:x}",
        Sha256::digest(format!("{id}:{version}:{}", reason.unwrap_or("None")).as_bytes())
    );
    let audit = json!({"task_id":value["id"],"application_id":value["application_id"],"state":state,"reason":reason,"version":version,"submitted":false});
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO agent_operations(key,actor,command,payload_hash,result,created_at) VALUES($1,'owner:primary',$2,$3,$4,clock_timestamp()) RETURNING result").bind(key).bind(format!("extension_task:{}",state.to_ascii_lowercase())).bind(hash).bind(&audit).fetch_optional(&mut **tx).await.map_err(db)?;
    if saved.as_ref() != Some(&audit) {
        return Err(Failure("browser_profile_write_ack_failed"));
    }
    Ok(value)
}
pub(super) async fn fresh(
    tx: &mut Transaction<'_, Postgres>,
    value: &Value,
    settings: &Settings,
    packets: &crate::packet_service::Settings,
    now: DateTime<Utc>,
) -> Result<Value> {
    let application = string(value, "application_id")?
        .parse()
        .map_err(|_| invalid())?;
    let (packet, url) = commands::context(tx, application, settings, packets, now).await?;
    current_task(value, &packet, &url)?;
    Ok(packet)
}
fn current_task(value: &Value, packet: &Value, url: &str) -> Result<()> {
    if packet["revision"] != value["packet_revision"]
        || packet["candidate_profile_version"] != value["profile_version"]
        || packet["snapshot"]["context_digest"] != value["context_digest"]
        || value["target_url"] != url
    {
        return Err(Failure("extension_task_context_stale"));
    }
    Ok(())
}
pub(super) async fn read_without_owner(
    c: &mut PgConnection,
    command: &native::Command,
    settings: &Settings,
    packets: &crate::packet_service::Settings,
) -> Result<Option<Value>> {
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
        sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            .execute(&mut *tx)
            .await
            .map_err(db)?;
        let now = storage::now(&mut tx).await?;
        commands::read_profile(&mut tx, command, now).await?;
        let value = load(&mut tx, task_id(command)?).await?;
        if value["profile_binding_id"] != command.value["profile_binding_id"] {
            return Err(Failure("PROFILE_NOT_SELECTED"));
        }
        if value["state"] == "FILLING" {
            return Ok(None);
        }
        let key = format!(
            "extension_request:{}:{}",
            settings
                .extension
                .as_deref()
                .ok_or(Failure("extension_identity_not_authorized"))?,
            command.request_id
        );
        let consumed: bool =
            sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM agent_operations WHERE key=$1)")
                .bind(key)
                .fetch_one(&mut *tx)
                .await
                .map_err(db)?;
        if consumed {
            return Err(Failure("form_request_already_consumed"));
        }
        if !command.value["expected_task_version"].is_null() {
            bound(&value, &command.value, true)?;
            let application = string(&value, "application_id")?
                .parse()
                .map_err(|_| invalid())?;
            let (packet, url) =
                commands::read_context(&mut tx, application, settings, packets, now).await?;
            current_task(&value, &packet, &url)?;
        }
        Ok(Some(json!({"task":value,"submitted":false})))
    }
    .await;
    match result {
        Ok(v) => {
            tx.commit()
                .await
                .map_err(|_| Failure("browser_profile_commit_outcome_unknown"))?;
            Ok(v)
        }
        Err(e) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("browser_profile_rollback_unconfirmed"))?;
            Err(e)
        }
    }
}
async fn unclaimed(
    tx: &mut Transaction<'_, Postgres>,
    id: &Value,
    session: &Value,
    tab: &Value,
) -> Result<()> {
    let exists:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM owner_preferences WHERE starts_with(key,'ext_task:') AND value->'id'<>$1 AND (value->>'state' IS NULL OR value->>'state' NOT IN ('FAILED_FINAL','SUBMISSION_UNKNOWN','SUBMITTED_CONFIRMED')) AND value->'browser_session_id'=$2 AND value->'tab_id'=$3)").bind(id).bind(session).bind(tab).fetch_one(&mut **tx).await.map_err(db)?;
    if exists {
        return Err(Failure("extension_tab_already_owned"));
    }
    Ok(())
}
fn zero_counts() -> Value {
    json!({"ready":0,"completed":0,"missing":0,"manual":0,"validation_errors":0,"existing":0})
}
fn answer_revisions(packet: &Value) -> Result<Value> {
    let fields = packet["fields"].as_array().ok_or_else(invalid)?;
    let mut result = json!({});
    for field in fields {
        result[string(field, "id")?] = field["answer_revision"].clone();
    }
    Ok(result)
}
async fn create(
    tx: &mut Transaction<'_, Postgres>,
    command: &native::Command,
    settings: &Settings,
    packets: &crate::packet_service::Settings,
    now: DateTime<Utc>,
) -> Result<Value> {
    let v = &command.value;
    let session = command
        .id("browser_session_id")
        .map_err(|_| Failure("browser_session_required"))?;
    let application = command
        .id("application_id")
        .map_err(|_| Failure("application_id_required"))?;
    let (packet, url) = commands::context(tx, application, settings, packets, now).await?;
    let id = identity(application);
    let key = format!("ext_task:{id}");
    if let Some(old) = get(tx, &key).await? {
        let mut old = validate(old)?;
        if !v["expected_task_version"].is_null() && v["expected_task_version"] != old["version"] {
            return Err(Failure("extension_task_revision_conflict"));
        }
        if task_terminal(&old) {
            return Err(Failure("extension_task_terminal"));
        }
        if old["profile_binding_id"] != v["profile_binding_id"] {
            if old["state"] != "PAUSED" {
                return Err(Failure("PROFILE_NOT_SELECTED"));
            }
            let paused = matches!(old["reason"].as_str(), Some("owner_pause" | "global_stop"));
            let state = if paused { "PAUSED" } else { "PACKET_READY" };
            let reason = if paused {
                string(&old, "reason")?.to_owned()
            } else {
                "owner_profile_transfer".into()
            };
            old=move_in(tx,old,state,&reason,json!({"profile_binding_id":v["profile_binding_id"],"browser_session_id":session,"window_id":v["window_id"],"tab_id":null,"tab_active":false,"plan_id":null,"authorization_id":null,"network_guard_active":false,"browser_connection":"unverified","counts":zero_counts(),"step":null,"challenge_state":"UNKNOWN"}),now).await?;
        }
        if old["browser_session_id"] != json!(session) {
            return Err(Failure("extension_task_recovery_required"));
        }
        if old["packet_revision"] != packet["revision"]
            || old["profile_version"] != packet["candidate_profile_version"]
            || old["context_digest"] != packet["snapshot"]["context_digest"]
        {
            if !old["tab_id"].is_null()
                || old["network_guard_active"] == true
                || old["target_url"] != url
                || !matches!(
                    old["state"].as_str(),
                    Some("PACKET_READY" | "NEEDS_INPUT" | "PAUSED" | "FAILED_RETRYABLE")
                )
            {
                return Err(Failure("extension_task_context_stale"));
            }
            let paused = old["state"] == "PAUSED"
                && matches!(old["reason"].as_str(), Some("owner_pause" | "global_stop"));
            let reason = if paused {
                string(&old, "reason")?.to_owned()
            } else {
                "packet_changed_fresh_inspection_required".into()
            };
            old=move_in(tx,old,if paused{"PAUSED"}else{"PACKET_READY"},&reason,json!({"packet_revision":packet["revision"],"profile_version":packet["candidate_profile_version"],"context_digest":packet["snapshot"]["context_digest"],"field_answer_revisions":answer_revisions(&packet)?,"plan_id":null,"authorization_id":null,"step":null,"tab_active":false,"browser_connection":"unverified","counts":zero_counts()}),now).await?;
        }
        return Ok(old);
    }
    let exists:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM owner_preferences WHERE starts_with(key,'ext_task:') AND value->'job_id'=$1 AND (value->>'state' IS NULL OR value->>'state' NOT IN ('FAILED_FINAL','SUBMISSION_UNKNOWN','SUBMITTED_CONFIRMED')))").bind(&packet["job_id"]).fetch_one(&mut **tx).await.map_err(db)?;
    if exists {
        return Err(Failure("extension_job_already_owned"));
    }
    if !v["tab_id"].is_null() {
        unclaimed(tx, &json!(id), &json!(session), &v["tab_id"]).await?;
    }
    let value = validate(
        json!({"id":id,"version":1,"application_id":application,"job_id":packet["job_id"],"company_name":packet["snapshot"]["company_name"],"job_title":packet["snapshot"]["job_title"],"packet_revision":packet["revision"],"profile_version":packet["candidate_profile_version"],"context_digest":packet["snapshot"]["context_digest"],"target_url":url,"current_url":url,"browser_session_id":session,"profile_binding_id":v["profile_binding_id"],"window_id":v["window_id"],"tab_id":v["tab_id"],"state":"PACKET_READY","challenge_state":"UNKNOWN","step":null,"plan_id":null,"authorization_id":null,"field_answer_revisions":answer_revisions(&packet)?,"verified_receipts":[],"network_guard_active":false,"reason":null,"next_action":next_action("PACKET_READY")?,"mode":"ASSISTED_FILL","capabilities":{"preview":true,"assisted_fill":settings.fill_enabled,"reviewed_submission":false,"unattended_approved":false},"counts":zero_counts(),"browser_connection":if v["tab_id"].is_null(){"unverified"}else{"connected"},"tab_active":!v["tab_id"].is_null(),"challenge_observed":false,"updated_at":now.to_rfc3339()}),
    )?;
    put(tx, &key, &value).await?;
    Ok(value)
}
pub(super) fn bound(value: &Value, v: &Value, allow_background: bool) -> Result<()> {
    if value["profile_binding_id"] != v["profile_binding_id"] {
        return Err(Failure("PROFILE_NOT_SELECTED"));
    }
    if value["version"] != v["expected_task_version"] {
        return Err(Failure("extension_task_revision_conflict"));
    }
    if v["browser_session_id"].is_null()
        || v["browser_session_id"] != value["browser_session_id"]
        || v["tab_id"].is_null()
        || v["tab_id"] != value["tab_id"]
        || v["window_id"].is_null()
        || v["window_id"] != value["window_id"]
    {
        return Err(Failure("extension_tab_binding_mismatch"));
    }
    let focus = allow_background
        && value["state"] == "PAUSED"
        && matches!(
            value["reason"].as_str(),
            Some("focus_lost" | "active_tab_changed")
        );
    if task_terminal(value) || value["state"] == "PAUSED" && !focus {
        return Err(Failure("extension_task_paused_or_cancelled"));
    }
    Ok(())
}
pub(super) async fn control(
    tx: &mut Transaction<'_, Postgres>,
    value: Value,
    action: &str,
    version: i64,
    settings: &Settings,
    packets: &crate::packet_service::Settings,
    now: DateTime<Utc>,
) -> Result<Value> {
    if value["version"] != version {
        return Err(Failure("extension_task_revision_conflict"));
    }
    if task_terminal(&value) {
        return Err(Failure("extension_task_terminal"));
    }
    let state = match action {
        "resume" => {
            fresh(tx, &value, settings, packets, now).await?;
            if value["tab_id"].is_null() {
                "PAUSED"
            } else {
                "PACKET_READY"
            }
        }
        "cancel" => "FAILED_FINAL",
        "pause" => "PAUSED",
        _ => return Err(request_error()),
    };
    let connection = if action == "resume" && !value["tab_id"].is_null() {
        "connected"
    } else if value["tab_id"].is_null() {
        "disconnected"
    } else {
        "paused"
    };
    move_in(
        tx,
        value,
        state,
        &format!("owner_{action}"),
        json!({"browser_connection":connection,"plan_id":null,"authorization_id":null}),
        now,
    )
    .await
}
async fn update(
    tx: &mut Transaction<'_, Postgres>,
    command: &native::Command,
    settings: &Settings,
    packets: &crate::packet_service::Settings,
    forms: Option<form_service::Services<'_>>,
    now: DateTime<Utc>,
) -> Result<Value> {
    let v = &command.value;
    let mut value = load(tx, task_id(command)?).await?;
    if value["profile_binding_id"] != v["profile_binding_id"] {
        return Err(Failure("PROFILE_NOT_SELECTED"));
    }
    if value["version"] != v["expected_task_version"] {
        return Err(Failure("extension_task_revision_conflict"));
    }
    let event = v["task_event"]
        .as_str()
        .ok_or(Failure("extension_task_event_required"))?;
    if matches!(event, "recover" | "recovered" | "worker_restart") && value["state"] == "FILLING" {
        let mut receipts = value["verified_receipts"]
            .as_array()
            .ok_or_else(invalid)?
            .clone();
        receipts.push(json!({"plan_id":value["plan_id"],"authorization_id":value["authorization_id"],"packet_revision":value["packet_revision"],"profile_version":value["profile_version"],"verification_method":"unknown","state":"manual_required","results":[],"reason":event,"recorded_at":now.to_rfc3339(),"submitted":false}));
        let start = receipts.len().saturating_sub(50);
        value["verified_receipts"] = json!(&receipts[start..]);
    }
    if matches!(event, "recover" | "recovered") {
        if v["browser_session_id"].is_null() || task_terminal(&value) {
            return Err(Failure("extension_task_terminal"));
        }
        let reason = if value["state"] == "PAUSED"
            && matches!(
                value["reason"].as_str(),
                Some("owner_pause" | "global_stop")
            ) {
            string(&value, "reason")?
        } else {
            "browser_restart_fresh_inspection_required"
        }
        .to_owned();
        return move_in(tx,value,"PAUSED",&reason,json!({"browser_session_id":v["browser_session_id"],"tab_id":null,"tab_active":false,"browser_connection":"disconnected","plan_id":null,"authorization_id":null,"network_guard_active":false}),now).await;
    }
    if v["browser_session_id"] != value["browser_session_id"] {
        return Err(Failure("extension_tab_binding_mismatch"));
    }
    if event == "guard_released" {
        if v["tab_id"].is_null() || v["tab_id"] != value["tab_id"] {
            return Err(Failure("extension_tab_binding_mismatch"));
        }
        let reason = if value["state"] == "PAUSED"
            && matches!(
                value["reason"].as_str(),
                Some("owner_pause" | "global_stop")
            ) {
            string(&value, "reason")?
        } else {
            "owner_returned_browser_control"
        }
        .to_owned();
        let state = if task_terminal(&value) {
            string(&value, "state")?
        } else {
            "PAUSED"
        }
        .to_owned();
        return move_in(
            tx,
            value,
            &state,
            &reason,
            json!({"network_guard_active":false,"plan_id":null,"authorization_id":null}),
            now,
        )
        .await;
    }
    if task_terminal(&value) {
        return Err(Failure("extension_task_terminal"));
    }
    if event == "bind" {
        if v["tab_id"].is_null() {
            return Err(Failure("extension_tab_required"));
        }
        fresh(tx, &value, settings, packets, now).await?;
        if value["state"] == "PAUSED"
            && matches!(
                value["reason"].as_str(),
                Some("owner_pause" | "global_stop")
            )
        {
            return Err(Failure("extension_task_paused_or_cancelled"));
        }
        if !value["tab_id"].is_null() && value["tab_id"] != v["tab_id"] {
            return Err(Failure("extension_tab_already_bound"));
        }
        if v["observed_url"].as_str().is_some_and(|s| !s.is_empty())
            && v["observed_url"] != value["target_url"]
        {
            return Err(Failure("extension_destination_mismatch"));
        }
        unclaimed(tx, &value["id"], &v["browser_session_id"], &v["tab_id"]).await?;
        let target = value["target_url"].clone();
        return move_in(tx,value,"PACKET_READY","tab_bound_fresh_inspection_required",json!({"tab_id":v["tab_id"],"window_id":v["window_id"],"current_url":target,"tab_active":true,"browser_connection":"connected","plan_id":null,"authorization_id":null}),now).await;
    }
    if event == "worker_restart" {
        let reason = if value["state"] == "PAUSED"
            && matches!(
                value["reason"].as_str(),
                Some("owner_pause" | "global_stop")
            ) {
            string(&value, "reason")?
        } else {
            "worker_restart_fresh_inspection_required"
        }
        .to_owned();
        return move_in(
            tx,
            value,
            "PAUSED",
            &reason,
            json!({"plan_id":null,"authorization_id":null,"browser_connection":"paused"}),
            now,
        )
        .await;
    }
    if matches!(event, "pause" | "paused" | "cancel" | "resume") {
        let version = number(&value, "version")?;
        return control(
            tx,
            value,
            if event == "paused" { "pause" } else { event },
            version,
            settings,
            packets,
            now,
        )
        .await;
    }
    if v["tab_id"].is_null() || v["tab_id"] != value["tab_id"] {
        return Err(Failure("extension_tab_binding_mismatch"));
    }
    if event == "guard_installed" {
        let state = string(&value, "state")?.to_owned();
        return move_in(
            tx,
            value,
            &state,
            "tab_network_guard_installed",
            json!({"network_guard_active":true}),
            now,
        )
        .await;
    }
    if matches!(
        event,
        "navigation"
            | "refresh"
            | "refreshed"
            | "focus_lost"
            | "active_tab_changed"
            | "tab_closed"
            | "network_timeout"
    ) {
        let url = v["observed_url"]
            .as_str()
            .filter(|s| !s.is_empty())
            .unwrap_or(string(&value, "current_url")?);
        let destination = navigation(&value, url);
        let reason = if value["state"] == "PAUSED"
            && (matches!(
                value["reason"].as_str(),
                Some("owner_pause" | "global_stop")
            ) || matches!(event, "focus_lost" | "active_tab_changed"))
        {
            value["reason"].as_str().map(str::to_owned)
        } else {
            Some(
                if event == "navigation" && destination.is_none() {
                    "unexpected_navigation"
                } else {
                    event
                }
                .to_owned(),
            )
        };
        let current = destination
            .map(Value::String)
            .unwrap_or_else(|| value["current_url"].clone());
        if matches!(event, "focus_lost" | "active_tab_changed")
            && value["state"] == "PAUSED"
            && value["reason"] == json!(reason)
            && value["tab_active"] == false
            && value["browser_connection"] == "paused"
            && value["plan_id"].is_null()
            && value["authorization_id"].is_null()
            && current == value["current_url"]
        {
            return Ok(value);
        }
        let tab = if event == "tab_closed" {
            Value::Null
        } else {
            value["tab_id"].clone()
        };
        let guard = event != "tab_closed" && value["network_guard_active"] == true;
        return move_reason_in(tx,value,if event=="network_timeout"{"FAILED_RETRYABLE"}else{"PAUSED"},reason.as_deref(),json!({"current_url":current,"tab_id":tab,"tab_active":false,"browser_connection":if event=="tab_closed"{"disconnected"}else{"paused"},"plan_id":null,"authorization_id":null,"network_guard_active":guard}),now).await;
    }
    if event == "fill_started" {
        if value["state"] == "FILLING"
            && !v["plan_id"].is_null()
            && v["plan_id"] == value["plan_id"]
        {
            return Ok(value);
        }
        if value["state"] != "FILL_AUTHORIZED"
            || v["plan_id"].is_null()
            || v["plan_id"] != value["plan_id"]
        {
            return Err(Failure("extension_task_not_authorized"));
        }
        return move_in(
            tx,
            value,
            "FILLING",
            "approved_fill_started",
            json!({}),
            now,
        )
        .await;
    }
    if event == "inspection_prepared" {
        if value["state"] == "PAUSED" {
            return Err(Failure("extension_task_paused_or_cancelled"));
        }
        let plan = form_service::load(
            tx,
            command
                .id("plan_id")
                .map_err(|_| Failure("plan_required"))?,
        )
        .await?;
        let (task, _) = form_review::attach(
            tx,
            value,
            plan,
            settings,
            packets,
            forms.ok_or(Failure("browser_form_inspection_unavailable"))?,
        )
        .await?;
        return Ok(task);
    }
    Err(Failure(if event == "fill_finished" {
        "verified_fill_receipt_required"
    } else if event == "inspection_prepared" {
        "browser_form_inspection_unavailable"
    } else {
        "extension_task_event_required"
    }))
}
pub(super) async fn dispatch(
    tx: &mut Transaction<'_, Postgres>,
    command: &native::Command,
    settings: &Settings,
    packets: &crate::packet_service::Settings,
    forms: Option<form_service::Services<'_>>,
    now: DateTime<Utc>,
) -> Result<Value> {
    commands::require_profile(tx, command, now).await?;
    let extension = settings
        .extension
        .as_deref()
        .ok_or(Failure("extension_identity_not_authorized"))?;
    let key = format!("extension_request:{extension}:{}", command.request_id);
    let consumed: bool =
        sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM agent_operations WHERE key=$1)")
            .bind(&key)
            .fetch_one(&mut **tx)
            .await
            .map_err(db)?;
    if consumed {
        return Err(Failure("form_request_already_consumed"));
    }
    let mut savepoint = sqlx::Connection::begin(&mut **tx).await.map_err(db)?;
    let operation=async{
        let mut questions=None;
        let value=match command.name() {
            "ask_form_questions"=>{let task=load(&mut savepoint,task_id(command)?).await?;bound(&task,&command.value,false)?;let data=form_questions::ask(&mut savepoint,task,settings,packets,forms.ok_or(Failure("browser_form_inspection_unavailable"))?,now).await?;questions=Some(data["questions"].clone());data["task"].clone()},
            "open_application_task"=>create(&mut savepoint,command,settings,packets,now).await?,
            "update_application_task"=>update(&mut savepoint,command,settings,packets,forms,now).await?,
            "get_application_task"=>{let mut value=load(&mut savepoint,task_id(command)?).await?;if value["profile_binding_id"]!=command.value["profile_binding_id"]{return Err(Failure("PROFILE_NOT_SELECTED"));}
                if !command.value["expected_task_version"].is_null(){bound(&value,&command.value,true)?;fresh(&mut savepoint,&value,settings,packets,now).await?;}
                if value["state"]=="FILLING" {match fresh(&mut savepoint,&value,settings,packets,now).await {Ok(_)=>{},Err(e) if domain_denial(e)=>{value=move_in(&mut savepoint,value,"PAUSED","candidate_or_packet_changed_during_fill",json!({"plan_id":null,"authorization_id":null,"browser_connection":"paused"}),now).await?;},Err(e)=>return Err(e)}}value},
            _=>return Err(Failure("browser_form_inspection_unavailable")),
        };
        if !command.value["chrome_command_id"].is_null() {let fresh=storage::now(&mut savepoint).await?;commands::require_profile(&mut savepoint,command,fresh).await?;}
        if command.name()!="get_application_task" {
            let hash=format!("{:x}",Sha256::digest(command.value.to_string().as_bytes()));let audit=json!({"task_id":value["id"],"submitted":false});
            let saved:Option<Value>=sqlx::query_scalar("INSERT INTO agent_operations(key,actor,command,payload_hash,result,created_at) VALUES($1,$2,$3,$4,$5,clock_timestamp()) RETURNING result").bind(&key).bind(format!("chrome:{extension}")).bind(command.name()).bind(hash).bind(&audit).fetch_optional(&mut *savepoint).await.map_err(db)?;if saved.as_ref()!=Some(&audit){return Err(Failure("browser_profile_write_ack_failed"));}
        }
        let mut data=json!({"task":value,"submitted":false});if let Some(questions)=questions{data["questions"]=questions;}Ok(data)
    }.await;
    match operation {
        Ok(value) => {
            savepoint.commit().await.map_err(db)?;
            Ok(value)
        }
        Err(e) => {
            savepoint
                .rollback()
                .await
                .map_err(|_| Failure("browser_profile_rollback_unconfirmed"))?;
            if e == Failure("profile_command_expired") {
                let row = native::authenticate(tx, command).await?;
                let selected = selection(tx).await?;
                let fresh = storage::now(tx).await?;
                invalidation::expire(tx, Some((&row, &selected)), fresh).await?;
            }
            Err(e)
        }
    }
}
pub(super) fn domain_denial(e: Failure) -> bool {
    matches!(
        e.0,
        "extension_task_required"
            | "extension_task_not_waiting_for_answers"
            | "fresh_form_inspection_required"
            | "packet_context_stale_or_destination_invalid"
            | "application_paused_or_cancelled"
            | "execution_not_waiting_for_question"
            | "telegram_question_too_long_manual_required"
            | "extension_task_not_found"
            | "extension_task_revision_conflict"
            | "extension_task_terminal"
            | "extension_task_recovery_required"
            | "extension_task_context_stale"
            | "extension_job_already_owned"
            | "extension_tab_already_owned"
            | "extension_tab_binding_mismatch"
            | "extension_task_paused_or_cancelled"
            | "extension_task_event_required"
            | "extension_tab_required"
            | "extension_tab_already_bound"
            | "extension_destination_mismatch"
            | "extension_task_not_authorized"
            | "verified_fill_receipt_required"
            | "browser_form_inspection_unavailable"
            | "browser_session_required"
            | "application_id_required"
            | "form_request_already_consumed"
            | "PROFILE_OFFLINE"
            | "PROFILE_NOT_SELECTED"
            | "PROFILE_SESSION_CHANGED"
            | "profile_command_expired"
            | "stale_or_unreviewed_candidate_context"
            | "application_not_eligible"
            | "naukri_automation_paused"
            | "naukri_automation_stopped"
            | "execution_mode_off"
            | "unverified_application_destination"
            | "unsupported_form_adapter"
            | "platform_fill_policy_denied"
    )
}
pub(crate) fn owner_denial(e: Failure) -> bool {
    domain_denial(e)
}
