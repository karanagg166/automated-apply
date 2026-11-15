//! Owner-reviewed browser commands are leased once. A lost lease is never redelivered.
use super::*;
use serde::{Deserialize, Serialize};
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Input {
    request_id: Uuid,
    profile_binding_id: Uuid,
    selection_version: i64,
    expected_profile_version: i64,
    application_id: Uuid,
    packet_revision: i64,
    action: String,
    #[serde(default)]
    task_id: Option<Uuid>,
    #[serde(default)]
    expected_task_version: Option<i64>,
}
pub fn request(mut input: Value) -> Result<Input> {
    let object = input.as_object_mut().ok_or_else(request_error)?;
    for key in [
        "selection_version",
        "expected_profile_version",
        "packet_revision",
        "expected_task_version",
    ] {
        if let Some(value) = object.get_mut(key)
            && !(key == "expected_task_version" && value.is_null())
        {
            *value = json!(expected(value, 1)?);
        }
    }
    let input: Input = serde_json::from_value(input).map_err(|_| request_error())?;
    if !matches!(
        input.action.as_str(),
        "open" | "prepare" | "pause" | "resume" | "cancel"
    ) {
        return Err(request_error());
    }
    Ok(input)
}
pub fn payload_hash(input: &Input) -> String {
    // Declaration order and UTF-8 match the existing Pydantic model_dump_json recipe.
    format!(
        "{:x}",
        Sha256::digest(serde_json::to_vec(input).expect("bounded command input"))
    )
}
pub(super) async fn enqueue(
    tx: &mut Transaction<'_, Postgres>,
    input: &Input,
    settings: &Settings,
    packets: &crate::packet_service::Settings,
    now: DateTime<Utc>,
) -> Result<Value> {
    let key = format!("chr_cmd:{}", input.request_id);
    let hash = payload_hash(input);
    if let Some(previous) = get(tx, &key).await? {
        if previous["payload_hash"] != hash {
            return Err(Failure("command_id_conflict"));
        }
        return Ok(previous);
    }
    let selected = selection(tx).await?;
    if let Some(fixed) = get(tx, "chr_fixed_profile").await?
        && fixed["profile_binding_id"] != json!(input.profile_binding_id)
    {
        return Err(Failure("PROFILE_OFFLINE"));
    }
    if selected["version"] != input.selection_version
        || selected["profile_binding_id"] != json!(input.profile_binding_id)
    {
        return Err(Failure("PROFILE_SELECTION_CONFLICT"));
    }
    let profile = get(tx, &format!("chr_prof:{}", input.profile_binding_id))
        .await?
        .ok_or(Failure("PROFILE_OFFLINE"))?;
    if !online(&profile, now)? {
        invalidation::invalidate(tx, &profile["id"], "PROFILE_OFFLINE", now).await?;
        return Err(Failure("PROFILE_OFFLINE"));
    }
    if profile["version"] != input.expected_profile_version {
        return Err(Failure("PROFILE_REVISION_CONFLICT"));
    }
    if !settings.commands_enabled || profile["commands_enabled"] != true {
        return Err(Failure("PROFILE_COMMANDS_DISABLED"));
    }
    let (packet, destination) = context(tx, input.application_id, settings, packets, now).await?;
    if packet["revision"] != input.packet_revision {
        return Err(Failure("extension_task_context_stale"));
    }
    if input.action != "open" {
        let task = input.task_id.ok_or(Failure("extension_task_required"))?;
        let task = get(tx, &format!("ext_task:{task}"))
            .await?
            .ok_or(Failure("extension_task_not_found"))?;
        if task["application_id"] != json!(input.application_id)
            || task["profile_binding_id"] != json!(input.profile_binding_id)
            || task["version"] != json!(input.expected_task_version)
        {
            return Err(Failure("extension_task_revision_conflict"));
        }
    }
    let pending:i64=sqlx::query_scalar("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'chr_cmd:') AND (value->>'state' IS NULL OR value->>'state' NOT IN ('completed','failed','expired','cancelled','outcome_unknown'))").fetch_one(&mut **tx).await.map_err(db)?;
    if pending >= 20 {
        return Err(Failure("profile_queue_full"));
    }
    let mut value = serde_json::to_value(input).map_err(|_| request_error())?;
    for (key,item) in json!({"id":input.request_id,"version":1,"payload_hash":hash,"actor":"owner","state":"queued","reason":null,"browser_session_id":profile["browser_session_id"],"destination":destination,"expires_at":(now+chrono::Duration::seconds(120)).to_rfc3339(),"lease_expires_at":null,"lease_token":null,"submitted":false}).as_object().unwrap() {value[key]=item.clone();}
    put(tx, &key, &value).await?;
    Ok(value)
}
pub(super) async fn require_profile(
    tx: &mut Transaction<'_, Postgres>,
    command: &native::Command,
    now: DateTime<Utc>,
) -> Result<Value> {
    check_profile(tx, command, now, false).await
}
pub(super) async fn read_profile(
    tx: &mut Transaction<'_, Postgres>,
    command: &native::Command,
    now: DateTime<Utc>,
) -> Result<Value> {
    check_profile(tx, command, now, true).await
}
async fn check_profile(
    tx: &mut Transaction<'_, Postgres>,
    command: &native::Command,
    now: DateTime<Utc>,
    read_only: bool,
) -> Result<Value> {
    let row = native::authenticate(tx, command).await?;
    if let Some(fixed) = get(tx, "chr_fixed_profile").await?
        && fixed["profile_binding_id"] != row["id"]
    {
        return Err(Failure("PROFILE_OFFLINE"));
    }
    if !online(&row, now)? {
        if !read_only {
            invalidation::invalidate(tx, &row["id"], "PROFILE_OFFLINE", now).await?;
        }
        return Err(Failure("PROFILE_OFFLINE"));
    }
    let selected = selection(tx).await?;
    if selected["profile_binding_id"] != row["id"] {
        return Err(Failure("PROFILE_NOT_SELECTED"));
    }
    if command.value["browser_session_id"] != row["browser_session_id"] {
        return Err(Failure("PROFILE_SESSION_CHANGED"));
    }
    if !command.value["chrome_command_id"].is_null()
        && !matches!(
            command.name(),
            "connect_chrome_profile"
                | "heartbeat_chrome_profile"
                | "disconnect_chrome_profile"
                | "poll_chrome_command"
                | "start_chrome_command"
                | "ack_chrome_command"
        )
    {
        let id = command
            .id("chrome_command_id")
            .map_err(|_| Failure("profile_command_expired"))?;
        let lease = get(tx, &format!("chr_cmd:{id}"))
            .await?
            .ok_or(Failure("profile_command_expired"))?;
        let v = &command.value;
        if lease["state"] != "executing"
            || lease["version"] != v["expected_command_version"]
            || lease["lease_token"].is_null()
            || lease["lease_token"] != v["command_lease_token"]
            || lease["profile_binding_id"] != row["id"]
            || lease["browser_session_id"] != row["browser_session_id"]
            || lease["selection_version"] != selected["version"]
            || lease["expected_profile_version"] != row["version"]
            || timestamp(&lease["expires_at"])? <= now
            || timestamp(&lease["lease_expires_at"])? <= now
            || !v["application_id"].is_null() && lease["application_id"] != v["application_id"]
            || lease["action"] == "prepare" && lease["task_id"] != v["task_id"]
        {
            return Err(Failure("profile_command_expired"));
        }
    }
    Ok(row)
}
pub(super) async fn dispatch(
    tx: &mut Transaction<'_, Postgres>,
    command: &native::Command,
    settings: &Settings,
    packets: &crate::packet_service::Settings,
    now: DateTime<Utc>,
) -> Result<Value> {
    let row = require_profile(tx, command, now).await?;
    if !settings.commands_enabled || row["commands_enabled"] != true {
        return Err(Failure("PROFILE_COMMANDS_DISABLED"));
    }
    let selected = selection(tx).await?;
    invalidation::expire(tx, Some((&row, &selected)), now).await?;
    let rows = active_commands(tx, Some(&row["id"])).await?;
    if command.name() == "poll_chrome_command" {
        let busy = rows.iter().any(|(_, v)| {
            v["profile_binding_id"] == row["id"]
                && matches!(v["state"].as_str(), Some("leased" | "executing"))
        });
        if busy {
            return Ok(json!({"command":null}));
        }
        let mut pending = rows
            .into_iter()
            .filter(|(_, v)| v["profile_binding_id"] == row["id"] && v["state"] == "queued")
            .map(|(k, v)| Ok((timestamp(&v["expires_at"])?, k, v)))
            .collect::<Result<Vec<_>>>()?;
        pending.sort_by(|a, b| (&a.0, &a.1).cmp(&(&b.0, &b.1)));
        let Some((_, key, mut value)) = pending.into_iter().next() else {
            return Ok(json!({"command":null}));
        };
        value["state"] = json!("leased");
        value["version"] = json!(
            number(&value, "version")?
                .checked_add(1)
                .ok_or_else(invalid)?
        );
        value["lease_token"] = json!(Uuid::new_v4());
        value["lease_expires_at"] = json!((now + chrono::Duration::seconds(90)).to_rfc3339());
        put(tx, &key, &value).await?;
        return Ok(json!({"command":value}));
    }
    let v = &command.value;
    let key = format!(
        "chr_cmd:{}",
        command
            .id("chrome_command_id")
            .map_err(|_| Failure("profile_command_revision_conflict"))?
    );
    let mut value = get(tx, &key)
        .await?
        .ok_or(Failure("profile_command_revision_conflict"))?;
    if value["profile_binding_id"] != row["id"]
        || value["lease_token"].is_null()
        || value["lease_token"] != v["command_lease_token"]
        || value["version"] != v["expected_command_version"]
    {
        return Err(Failure("profile_command_revision_conflict"));
    }
    if command.name() == "start_chrome_command" {
        if value["state"] != "leased" {
            return Err(Failure("profile_command_expired"));
        }
        let application = string(&value, "application_id")?
            .parse()
            .map_err(|_| invalid())?;
        let (packet, destination) = context(tx, application, settings, packets, now).await?;
        if packet["revision"] != value["packet_revision"] || value["destination"] != destination {
            return Err(Failure("extension_task_context_stale"));
        }
        let fresh = storage::now(tx).await?;
        if !online(&row, fresh)? {
            invalidation::invalidate(tx, &row["id"], "PROFILE_OFFLINE", fresh).await?;
            return Err(Failure("PROFILE_OFFLINE"));
        }
        if timestamp(&value["expires_at"])? <= fresh
            || timestamp(&value["lease_expires_at"])? <= fresh
        {
            invalidation::expire(tx, Some((&row, &selected)), fresh).await?;
            return Err(Failure("profile_command_expired"));
        }
        value["state"] = json!("executing");
    } else {
        if !matches!(value["state"].as_str(), Some("leased" | "executing")) {
            return Err(Failure("profile_command_expired"));
        }
        value["state"] = v
            .get("command_outcome")
            .filter(|v| !v.is_null())
            .cloned()
            .unwrap_or(json!("outcome_unknown"));
        value["reason"] = v["command_error"].clone();
    }
    value["version"] = json!(
        number(&value, "version")?
            .checked_add(1)
            .ok_or_else(invalid)?
    );
    put(tx, &key, &value).await?;
    Ok(json!({"command":value}))
}
pub(super) async fn context(
    tx: &mut Transaction<'_, Postgres>,
    application: Uuid,
    browser: &Settings,
    settings: &crate::packet_service::Settings,
    now: DateTime<Utc>,
) -> Result<(Value, String)> {
    context_in(tx, application, browser, settings, now, true).await
}
pub(super) async fn read_context(
    tx: &mut Transaction<'_, Postgres>,
    application: Uuid,
    browser: &Settings,
    settings: &crate::packet_service::Settings,
    now: DateTime<Utc>,
) -> Result<(Value, String)> {
    context_in(tx, application, browser, settings, now, false).await
}
async fn context_in(
    tx: &mut Transaction<'_, Postgres>,
    application: Uuid,
    browser: &Settings,
    settings: &crate::packet_service::Settings,
    now: DateTime<Utc>,
    locked: bool,
) -> Result<(Value, String)> {
    let packet = if locked {
        crate::packet_service::read_locked_in(tx, application, settings, now).await?
    } else {
        crate::packet_service::read_snapshot_in(tx, application, settings, now).await?
    };
    let row:Option<(Value,Option<Value>,Value,Option<Value>)>=sqlx::query_as("SELECT to_jsonb(p),to_jsonb(c),to_jsonb(j),(SELECT value FROM owner_preferences WHERE key='phase1_profile_confirmation') FROM application_packets p JOIN jobs j ON j.id=p.job_id LEFT JOIN candidate_profiles c ON c.singleton_key='primary' WHERE p.id=$1").bind(application).fetch_optional(&mut **tx).await.map_err(db)?;
    let (stored, profile, job, confirmation) = row.ok_or(Failure("packet_not_found"))?;
    let profile = profile.ok_or(Failure("stale_or_unreviewed_candidate_context"))?;
    let confirmation = confirmation.unwrap_or(Value::Null);
    if confirmation["profile_id"] != profile["id"]
        || confirmation["profile_version"] != profile["version"]
        || !confirmation["confirmed_at"]
            .as_str()
            .is_some_and(|s| !s.is_empty())
        || packet["candidate_profile_id"] != profile["id"]
        || packet["candidate_profile_version"] != profile["version"]
        || packet["readiness"]["stale"] == true
        || matches!(
            stored["lifecycle_state"].as_str(),
            Some(
                "abandoned"
                    | "withdrawn"
                    | "user_reported_submitted"
                    | "provider_confirmed_submitted"
                    | "submitting"
                    | "submission_unknown"
            )
        )
    {
        return Err(Failure("stale_or_unreviewed_candidate_context"));
    }
    if matches!(job["status"].as_str(), Some("applied" | "archived")) {
        return Err(Failure("application_not_eligible"));
    }
    if job["source_platform"] == "naukri" {
        let automation = get(tx, "naukri_automation")
            .await?
            .unwrap_or(json!({"revision":0,"state":"STOPPED"}));
        if number(&automation, "revision")? > 0 && automation["state"] != "RUNNING" {
            return Err(Failure(match automation["state"].as_str() {
                Some("PAUSED") => "naukri_automation_paused",
                _ => "naukri_automation_stopped",
            }));
        }
        if get(tx, "exec_config:naukri")
            .await?
            .is_some_and(|v| v["mode"] == "OFF")
        {
            return Err(Failure("execution_mode_off"));
        }
        if crate::packet_platform::posting_unavailable(&job, now.date_naive())?
            || previously_applied(tx, &job).await?
        {
            return Err(Failure("application_not_eligible"));
        }
    }
    if browser.fixture_origin.is_none() && packet["snapshot"]["destination"]["valid"] != true {
        return Err(Failure("unverified_application_destination"));
    }
    let destination = if let Some(origin) = browser.fixture_origin.as_deref() {
        let url = job["application_url"]
            .as_str()
            .ok_or(Failure("unsupported_form_adapter"))?;
        let u = reqwest::Url::parse(url).map_err(|_| Failure("unsupported_form_adapter"))?;
        if u.scheme() != "http"
            || u.host_str() != Some("127.0.0.1")
            || u.origin().ascii_serialization() != origin
            || !u.username().is_empty()
            || u.password().is_some()
        {
            return Err(Failure("unsupported_form_adapter"));
        }
        url.to_owned()
    } else {
        packet["snapshot"]["destination"]["application_url"]
            .as_str()
            .and_then(|s| crate::packet_platform::manual_page(s, &settings.policy))
            .ok_or(Failure("unsupported_form_adapter"))?
    };
    let platform = page_kind(&destination)?;
    let policy: Option<Value> =
        sqlx::query_scalar("SELECT preferences FROM agent_policies WHERE key='primary'")
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?;
    if let Some(policy) = policy {
        let platforms = policy["platforms"].as_object().ok_or_else(invalid)?;
        let preference = platforms
            .get(platform)
            .unwrap_or(&policy["default"])
            .as_str()
            .ok_or_else(invalid)?;
        if !matches!(
            preference,
            "approve" | "automatic_preferred" | "draft_only" | "manual_only" | "disabled"
        ) {
            return Err(invalid());
        }
        if matches!(preference, "disabled" | "manual_only" | "draft_only")
            || policy["default"] == "disabled" && !platforms.contains_key(platform)
        {
            return Err(Failure("platform_fill_policy_denied"));
        }
    } else if matches!(platform, "gmail" | "linkedin") {
        return Err(Failure("platform_fill_policy_denied"));
    }
    Ok((packet, destination))
}
fn page_kind(url: &str) -> Result<&'static str> {
    let u = reqwest::Url::parse(url).map_err(|_| invalid())?;
    let host = u.host_str().ok_or_else(invalid)?;
    if host == "docs.google.com" && u.path().starts_with("/forms/") || host == "forms.gle" {
        return Ok("google_forms");
    }
    for (domain, kind) in [
        ("naukri.com", "naukri"),
        ("wellfound.com", "wellfound"),
        ("instahyre.com", "instahyre"),
        ("workatastartup.com", "work_at_a_startup"),
        ("internshala.com", "internshala"),
        ("linkedin.com", "linkedin"),
    ] {
        if host == domain || host.ends_with(&format!(".{domain}")) {
            return Ok(kind);
        }
    }
    Ok("employer_forms")
}
async fn previously_applied(tx: &mut Transaction<'_, Postgres>, job: &Value) -> Result<bool> {
    if job["discovery_metadata"]["data_provenance"]["posting_status"] == "already_applied"
        || matches!(
            job["application_status"].as_str(),
            Some(
                "applied"
                    | "submitted"
                    | "interview"
                    | "offer"
                    | "applied_manually"
                    | "applied_verified"
            )
        )
        || matches!(job["status"].as_str(), Some("applied" | "submitted"))
    {
        return Ok(true);
    }
    let url = string(job, "job_url")?;
    let requisition = string(job, "job_url")?
        .trim_end_matches('/')
        .rsplit('-')
        .next()
        .filter(|s| (10..=20).contains(&s.len()) && s.bytes().all(|b| b.is_ascii_digit()))
        .ok_or(Failure("application_not_eligible"))?;
    let recorded: bool =
        sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM owner_preferences WHERE key=$1 OR key=$2)")
            .bind(format!("naukri_receipt:{requisition}"))
            .bind(format!("naukri_worker_receipt:{requisition}"))
            .fetch_one(&mut **tx)
            .await
            .map_err(db)?;
    if recorded {
        return Ok(true);
    }
    let work = Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!("naukri:{requisition}").as_bytes(),
    );
    let quarantined:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM owner_preferences WHERE key=$1 AND (value->>'status'='unknown' OR value->>'stage'='SUBMISSION_UNKNOWN' OR coalesce(value->'form_loss_observation','null'::jsonb)<>'null'::jsonb))").bind(format!("apply_work:{work}")).fetch_one(&mut **tx).await.map_err(db)?;
    if quarantined {
        return Ok(true);
    }
    let previous:Vec<(Uuid,String)>=sqlx::query_as("SELECT j.id,j.job_url FROM application_packets p JOIN jobs j ON j.id=p.job_id WHERE p.lifecycle_state IN ('user_reported_submitted','provider_confirmed_submitted','submitting','submission_unknown') AND (j.id=$1 OR j.source_platform='naukri') ORDER BY j.id LIMIT 10001").bind(string(job,"id")?.parse::<Uuid>().map_err(|_|invalid())?).fetch_all(&mut **tx).await.map_err(db)?;
    if previous.len() > 10000 {
        return Err(Failure("browser_profile_inventory_limit"));
    }
    Ok(previous.iter().any(|(id, prior)| {
        json!(id) == job["id"]
            || prior == url
            || prior.trim_end_matches('/').rsplit('-').next() == Some(requisition)
    }))
}
