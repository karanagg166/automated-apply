//! Saved packet preparation/inspection. No browser, model dispatch, approval or submission.
use crate::{
    Failure, Result, answer_service, packet_context,
    packet_contract::{self, Prepare},
    packet_fields,
    packet_platform::{self, Policy},
    packet_readiness::{self, Flags, Readiness, State},
    packet_record::{self, Kind},
};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;

pub struct Settings {
    pub policy: Policy,
    pub multi_select: bool,
    pub schema: String,
    pub telegram_notices: bool,
}
pub(crate) fn db(error: sqlx::Error) -> Failure {
    match error.as_database_error().and_then(|e| e.code()).as_deref() {
        Some("40001") => Failure("packet_serialization_rollback"),
        Some("23505" | "23503" | "23514") => Failure("packet_storage_conflict"),
        _ => Failure("packet_database_error"),
    }
}
fn invalid() -> Failure {
    Failure("invalid_packet_saved_record")
}
pub(crate) fn id(value: &Value) -> Result<Uuid> {
    value
        .as_str()
        .and_then(|s| s.parse().ok())
        .ok_or_else(invalid)
}
fn strings(value: &Value) -> Result<Vec<String>> {
    value
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .map(|v| v.as_str().map(str::to_owned).ok_or_else(invalid))
        .collect()
}
pub fn readiness(
    snapshot: &Value,
    fields: &[Value],
    flags: Flags,
    lifecycle: &str,
    now: DateTime<Utc>,
) -> Result<Readiness> {
    let warnings = strings(&snapshot["warnings"])?;
    let destination_warnings = strings(&snapshot["destination"]["warnings"])?;
    let fields = fields
        .iter()
        .map(|f| {
            Ok(packet_readiness::Field {
                question: f["question"].as_str().ok_or_else(invalid)?,
                required: f["required"].as_bool().ok_or_else(invalid)?,
                effective_answer: f["effective_answer"].as_str(),
                validation: match f["validation_status"].as_str() {
                    Some("draft_ready") => packet_readiness::Validation::DraftReady,
                    Some("needs_input") => packet_readiness::Validation::NeedsInput,
                    Some("file_upload_required") => {
                        packet_readiness::Validation::FileUploadRequired
                    }
                    Some("provider_unavailable") => {
                        packet_readiness::Validation::ProviderUnavailable
                    }
                    Some("validation_failed") => packet_readiness::Validation::ValidationFailed,
                    _ => return Err(invalid()),
                },
                requires_review: f["requires_review"].as_bool().ok_or_else(invalid)?,
                reviewed: f["review_status"] == "reviewed",
                answer_expires_at: packet_record::expiry(&f["provenance"]["answer_expires_at"])?,
            })
        })
        .collect::<Result<Vec<_>>>()?;
    let mut value = packet_readiness::calculate(
        packet_readiness::Snapshot {
            warnings: &warnings,
            destination_warnings: &destination_warnings,
            candidate_present: !snapshot["candidate"].is_null(),
            preparation_supported: snapshot["preparation_supported"] == true,
            destination_valid: snapshot["destination"]["valid"] == true,
            source_consistent: snapshot["destination"]["source_confidence"] == "source_consistent",
            resume_selected: !snapshot["resume"]["selected"].is_null(),
            resume_reason: snapshot["resume"]["reason"].as_str().ok_or_else(invalid)?,
        },
        &fields,
        flags,
        now,
    );
    if matches!(lifecycle, "abandoned" | "withdrawn") && !flags.submitted {
        value.state = State::ManualActionRequired;
        value.blockers = vec!["This packet is closed; no handoff is available".into()];
    }
    if lifecycle == "provider_confirmed_submitted" {
        value.state = State::CompletedVerified;
        value.warnings.retain(|w| !w.contains("self-reported"));
    }
    if matches!(lifecycle, "submitting" | "submission_unknown") {
        value.state = State::ManualActionRequired;
        value.blockers =
            vec!["Submission outcome must be reconciled; never resubmit this application".into()];
    }
    Ok(value)
}
pub(crate) async fn multi_select(
    tx: &mut Transaction<'_, Postgres>,
    request: &Prepare,
    settings: &Settings,
) -> Result<()> {
    if !request
        .questions
        .iter()
        .any(|q| q.field_type == "multi_select")
    {
        return Ok(());
    }
    if !settings.multi_select {
        return Err(Failure("packet_multi_select_unavailable"));
    }
    let available:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_constraint c JOIN pg_catalog.pg_class t ON t.oid=c.conrelid JOIN pg_catalog.pg_namespace n ON n.oid=t.relnamespace JOIN pg_catalog.pg_proc p ON p.pronamespace=n.oid WHERE n.nspname=$1 AND t.relname='application_packet_fields' AND c.conname='ck_application_fields_multi_select_v1' AND c.convalidated AND p.proname='valid_multi_select_answer' AND p.pronargs=3 AND pg_catalog.has_function_privilege(current_user,p.oid,'EXECUTE'))").bind(&settings.schema).fetch_one(&mut **tx).await.map_err(db)?;
    if available {
        Ok(())
    } else {
        Err(Failure("packet_multi_select_unavailable"))
    }
}
fn core() -> Result<Vec<packet_contract::Question>> {
    [
        ("Full name", "personal_information", "text", true),
        ("Email", "contact_information", "text", true),
        ("Phone number", "contact_information", "text", false),
        (
            "GitHub profile URL",
            "professional_profile_url",
            "url",
            false,
        ),
        (
            "LinkedIn profile URL",
            "professional_profile_url",
            "url",
            false,
        ),
        ("Portfolio URL", "professional_profile_url", "url", false),
        ("Upload resume", "resume_upload", "file", true),
    ]
    .into_iter()
    .map(|(q, c, t, r)| {
        packet_contract::question(json!({"question":q,"category":c,"field_type":t,"required":r}))
    })
    .collect()
}
async fn preview_in(
    tx: &mut Transaction<'_, Postgres>,
    job: Uuid,
    request: &Prepare,
    settings: &Settings,
    answers: &answer_service::Settings,
    now: DateTime<Utc>,
) -> Result<Value> {
    preview_context_in(tx, job, request, settings, answers, now, false).await
}
async fn preview_context_in(
    tx: &mut Transaction<'_, Postgres>,
    job: Uuid,
    request: &Prepare,
    settings: &Settings,
    answers: &answer_service::Settings,
    now: DateTime<Utc>,
    locked: bool,
) -> Result<Value> {
    multi_select(tx, request, settings).await?;
    let material = if locked {
        packet_context::load_locked_in(tx, job, request.resume_resource_id, &settings.policy)
            .await?
    } else {
        packet_context::load_in(tx, job, request.resume_resource_id, &settings.policy, now).await?
    };
    let resume = crate::resources::select_resume(&material.resources, request.resume_resource_id)?;
    let mut fields = Vec::with_capacity(7 + request.questions.len());
    for (i, question) in core()?
        .into_iter()
        .chain(request.questions.iter().cloned())
        .enumerate()
    {
        let mut field = packet_fields::build_factual_in(
            tx,
            question,
            job,
            material.profile.as_ref(),
            Some(&resume),
            if i < 7 {
                "packet_core"
            } else {
                "user_provided"
            },
            answers,
        )
        .await?;
        field["id"] = json!(Uuid::new_v4());
        fields.push(field);
    }
    let ready = readiness(
        &material.snapshot,
        &fields,
        Flags::default(),
        "created",
        now,
    )?;
    Ok(
        json!({"job_id":job,"candidate_profile_id":material.profile.as_ref().map(|p|p["id"].clone()),"candidate_profile_version":material.profile.as_ref().map(|p|p["version"].clone()),"snapshot":material.snapshot,"fields":fields,"readiness":ready,"submission_mode":"manual_handoff"}),
    )
}
pub(crate) async fn read_in(
    tx: &mut Transaction<'_, Postgres>,
    packet: Uuid,
    settings: &Settings,
    now: DateTime<Utc>,
) -> Result<Value> {
    read_context_in(tx, packet, settings, now, false, true).await
}
pub(crate) async fn read_locked_in(
    tx: &mut Transaction<'_, Postgres>,
    packet: Uuid,
    settings: &Settings,
    now: DateTime<Utc>,
) -> Result<Value> {
    read_context_in(tx, packet, settings, now, true, true).await
}
/// A repeatable-read task checkpoint is metadata only; later mutations reacquire the full fence.
pub(crate) async fn read_snapshot_in(
    tx: &mut Transaction<'_, Postgres>,
    packet: Uuid,
    settings: &Settings,
    now: DateTime<Utc>,
) -> Result<Value> {
    read_context_in(tx, packet, settings, now, false, false).await
}
async fn read_context_in(
    tx: &mut Transaction<'_, Postgres>,
    packet: Uuid,
    settings: &Settings,
    now: DateTime<Utc>,
    lock_context: bool,
    lock_parent: bool,
) -> Result<Value> {
    // Ordinary packet reads retain the parent lock. Metadata-only task checkpoints
    // use the caller's repeatable snapshot; every later mutation reacquires the full fence.
    let raw: Option<Value> = sqlx::query_scalar(if lock_parent {
        "SELECT to_jsonb(p) FROM application_packets p WHERE id=$1 FOR SHARE"
    } else {
        "SELECT to_jsonb(p) FROM application_packets p WHERE id=$1"
    })
    .bind(packet)
    .fetch_optional(&mut **tx)
    .await
    .map_err(db)?;
    let raw = raw.ok_or(Failure("packet_not_found"))?;
    let snapshot = packet_record::normalize(Kind::Snapshot, raw["snapshot"].clone())?;
    let selected = raw["resume_resource_id"]
        .as_str()
        .map(|s| s.parse().map_err(|_| invalid()))
        .transpose()?;
    let current = if lock_context {
        packet_context::load_locked_in(tx, id(&raw["job_id"])?, selected, &settings.policy).await?
    } else {
        packet_context::load_in(tx, id(&raw["job_id"])?, selected, &settings.policy, now).await?
    };
    let stale = current.snapshot["context_digest"] != snapshot["context_digest"]
        || current
            .profile
            .as_ref()
            .is_none_or(|p| p["id"] != raw["candidate_profile_id"]);
    let fields: Vec<Value> = sqlx::query_scalar(
        "SELECT to_jsonb(f) FROM application_packet_fields f WHERE packet_id=$1 ORDER BY position",
    )
    .bind(packet)
    .fetch_all(&mut **tx)
    .await
    .map_err(db)?;
    let fields = fields
        .into_iter()
        .map(|f| packet_record::normalize(Kind::Field, f))
        .collect::<Result<Vec<_>>>()?;
    let submitted: bool = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM application_submission_evidence WHERE packet_id=$1)",
    )
    .bind(packet)
    .fetch_one(&mut **tx)
    .await
    .map_err(db)?;
    let lifecycle = raw["lifecycle_state"].as_str().ok_or_else(invalid)?;
    let ready = readiness(
        &snapshot,
        &fields,
        Flags {
            stale,
            approved: !raw["approved_revision"].is_null()
                && raw["approved_revision"] == raw["revision"],
            submitted,
        },
        lifecycle,
        if lock_context { Utc::now() } else { now },
    )?;
    let mut result = json!({"snapshot":snapshot,"fields":fields,"readiness":ready,"submission_mode":"manual_handoff","review_status":if stale{"stale"}else if raw["approved_revision"].as_i64().is_some_and(|v|v!=0){"approved"}else if lifecycle=="reviewed"{"reviewed"}else{"pending"}});
    for key in [
        "id",
        "job_id",
        "candidate_profile_id",
        "candidate_profile_version",
        "platform",
        "lifecycle_state",
        "tracking_state",
        "revision",
        "approved_revision",
        "created_at",
        "updated_at",
    ] {
        result[key] = raw[key].clone();
    }
    // Validate the assembled read contract without changing effective answer bytes.
    validate_read(&result)?;
    for key in ["created_at", "updated_at"] {
        result[key] = packet_record::timestamp(&result[key], true)?;
    }
    Ok(result)
}
fn validate_read(value: &Value) -> Result<()> {
    static VALIDATOR: std::sync::LazyLock<jsonschema::Validator> = std::sync::LazyLock::new(|| {
        let schema: Value = serde_json::from_str(include_str!("../schemas/packet-read.json"))
            .expect("frozen packet read schema");
        jsonschema::draft202012::options()
            .should_validate_formats(false)
            .build(&schema)
            .expect("local packet read validator")
    });
    if VALIDATOR.is_valid(value) {
        Ok(())
    } else {
        Err(invalid())
    }
}
pub(crate) async fn create_in(
    tx: &mut Transaction<'_, Postgres>,
    job: Uuid,
    request: &Prepare,
    settings: &Settings,
    answers: &answer_service::Settings,
    now: DateTime<Utc>,
) -> Result<Value> {
    create_context_in(tx, job, request, settings, answers, now, false).await
}
/// Owner lock and a consistent snapshot must already be held. Queue preparation also
/// locks current material versions so concurrent updates cannot silently retain older facts.
pub(crate) async fn create_locked_in(
    tx: &mut Transaction<'_, Postgres>,
    job: Uuid,
    request: &Prepare,
    settings: &Settings,
    answers: &answer_service::Settings,
    now: DateTime<Utc>,
) -> Result<Value> {
    create_context_in(tx, job, request, settings, answers, now, true).await
}
async fn create_context_in(
    tx: &mut Transaction<'_, Postgres>,
    job: Uuid,
    request: &Prepare,
    settings: &Settings,
    answers: &answer_service::Settings,
    now: DateTime<Utc>,
    locked: bool,
) -> Result<Value> {
    // Fetch only identity before checking keys: replay performs no new preparation/question writes.
    let exists: bool = sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM jobs WHERE id=$1)")
        .bind(job)
        .fetch_one(&mut **tx)
        .await
        .map_err(db)?;
    if !exists {
        return Err(Failure("packet_job_not_found"));
    }
    let profile = crate::profile_store::get(tx).await.map_err(|e| {
        if e == Failure("profile_not_found") {
            Failure("packet_profile_required")
        } else {
            e
        }
    })?;
    let owner = id(&profile.value["id"])?;
    let key = request
        .idempotency_key
        .as_deref()
        .ok_or(Failure("invalid_packet_preparation"))?;
    let mut input = serde_json::to_value(request).map_err(|_| invalid())?;
    input["job_id"] = json!(job);
    let hash = crate::python_json::digest(&input);
    let rows:Vec<(Uuid,String,String)>=sqlx::query_as("SELECT id,idempotency_key,request_hash FROM application_packets WHERE idempotency_key=$1 OR (job_id=$2 AND candidate_profile_id=$3) ORDER BY id FOR SHARE").bind(key).bind(job).bind(owner).fetch_all(&mut **tx).await.map_err(db)?;
    if !rows.is_empty() {
        return replay(tx, rows, key, &hash, settings, now, locked).await;
    }
    let preview = preview_context_in(tx, job, request, settings, answers, now, locked).await?;
    let packet = Uuid::new_v4();
    let inserted:Option<Uuid>=sqlx::query_scalar("INSERT INTO application_packets(id,job_id,candidate_profile_id,candidate_profile_version,resume_resource_id,application_url,platform,lifecycle_state,tracking_state,revision,readiness_state,idempotency_key,request_hash,snapshot) VALUES($1,$2,$3,$4,$5,$6,$7,'created','not_applied',1,$8,$9,$10,$11) ON CONFLICT DO NOTHING RETURNING id")
        .bind(packet).bind(job).bind(owner).bind(preview["candidate_profile_version"].as_i64().ok_or_else(invalid)? as i32)
        .bind(preview["snapshot"]["resume"]["selected"]["resource_id"].as_str().map(|s|s.parse::<Uuid>().map_err(|_|invalid())).transpose()?)
        .bind(preview["snapshot"]["destination"]["application_url"].as_str())
        .bind(preview["snapshot"]["platform"].as_str().unwrap_or("unsupported"))
        .bind(preview["readiness"]["state"].as_str().ok_or_else(invalid)?)
        .bind(key).bind(&hash).bind(&preview["snapshot"]).fetch_optional(&mut **tx).await.map_err(db)?;
    if inserted.is_none() {
        return Err(Failure("packet_storage_conflict"));
    }
    for (position, field) in preview["fields"]
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .enumerate()
    {
        crate::packet_mutation::add_field_in(tx, packet, position, field).await?;
    }
    crate::packet_mutation::event_in(tx, packet, "packet_created", None, "created", 1).await?;
    if locked {
        read_locked_in(tx, packet, settings, now).await
    } else {
        read_in(tx, packet, settings, now).await
    }
}
async fn replay(
    tx: &mut Transaction<'_, Postgres>,
    rows: Vec<(Uuid, String, String)>,
    key: &str,
    hash: &str,
    settings: &Settings,
    now: DateTime<Utc>,
    locked: bool,
) -> Result<Value> {
    let matching = rows
        .into_iter()
        .filter(|(_, k, h)| k == key && h == hash)
        .collect::<Vec<_>>();
    if matching.len() != 1 {
        return Err(Failure("packet_idempotency_conflict"));
    }
    if locked {
        read_locked_in(tx, matching[0].0, settings, now).await
    } else {
        read_in(tx, matching[0].0, settings, now).await
    }
}

pub const LIST: &str = "/api/v1/application-packets";
pub enum Route<'a> {
    Platforms,
    Preview(&'a str),
    Create(&'a str),
    List,
    Read(&'a str),
    Readiness(&'a str),
    Events(&'a str),
    Questions(&'a str),
    Answer(&'a str, &'a str),
    Review(&'a str),
    Handoff(&'a str),
    Submission(&'a str),
    Tracking(&'a str),
}
pub fn route(path: &str) -> Option<Route<'_>> {
    if path == "/api/v1/applications/platforms" {
        return Some(Route::Platforms);
    }
    if path == LIST {
        return Some(Route::List);
    }
    if let Some(tail) = path.strip_prefix("/api/v1/jobs/") {
        let (id, action) = tail.split_once('/')?;
        if id.is_empty() {
            return None;
        }
        return match action {
            "application-preview" => Some(Route::Preview(id)),
            "application-packets" => Some(Route::Create(id)),
            _ => None,
        };
    }
    let tail = path.strip_prefix("/api/v1/application-packets/")?;
    let (id, action) = tail.split_once('/').unwrap_or((tail, ""));
    // The separately implemented intake route must never be treated as a packet UUID.
    if id.is_empty() || id == "intake" {
        return None;
    }
    match action {
        "" => Some(Route::Read(id)),
        "readiness" => Some(Route::Readiness(id)),
        "events" => Some(Route::Events(id)),
        "questions" => Some(Route::Questions(id)),
        "review" => Some(Route::Review(id)),
        "handoff" => Some(Route::Handoff(id)),
        "report-submission" => Some(Route::Submission(id)),
        "tracking" => Some(Route::Tracking(id)),
        action => action
            .strip_prefix("questions/")
            .filter(|field| !field.is_empty() && !field.contains('/'))
            .map(|field| Route::Answer(id, field)),
    }
}
#[derive(Default)]
pub struct Page {
    pub offset: i64,
    pub limit: i64,
    pub platform: Option<String>,
    pub job: Option<Uuid>,
    pub status: Option<String>,
}
impl Page {
    pub fn parse(query: Option<&str>, events: bool) -> Result<Self> {
        let mut raw = std::collections::BTreeMap::new();
        if let Some(query) = query {
            if query.len() > 4096 {
                return Err(Failure("invalid_packet_page"));
            }
            let url = reqwest::Url::parse(&format!("http://127.0.0.1/?{query}"))
                .map_err(|_| Failure("invalid_packet_page"))?;
            raw.extend(
                url.query_pairs()
                    .map(|(k, v)| (k.into_owned(), v.into_owned())),
            );
        }
        let integer = |k, default, min, max| {
            raw.get(k)
                .map(|v| {
                    crate::profile_contract::pagination_integer(json!(v), min, max)
                        .map_err(|_| Failure("invalid_packet_page"))
                })
                .unwrap_or(Ok(default))
        };
        let platform = if events {
            None
        } else {
            raw.get("platform").cloned()
        };
        if platform.as_ref().is_some_and(|s| s.chars().count() > 50) {
            return Err(Failure("invalid_packet_page"));
        }
        let status = if events {
            None
        } else {
            raw.get("status").cloned()
        };
        if status.as_deref().is_some_and(|s| {
            !matches!(
                s,
                "created"
                    | "preparing"
                    | "needs_input"
                    | "ready_for_review"
                    | "reviewed"
                    | "approved_for_manual_handoff"
                    | "external_application_opened"
                    | "user_reported_submitted"
                    | "provider_confirmed_submitted"
                    | "submitting"
                    | "submission_unknown"
                    | "withdrawn"
                    | "abandoned"
            )
        }) {
            return Err(Failure("invalid_packet_page"));
        }
        Ok(Self {
            offset: integer("offset", 0, 0, 100000)?,
            limit: integer("limit", if events { 50 } else { 25 }, 1, 100)?,
            platform,
            job: if events {
                None
            } else {
                raw.get("job_id")
                    .map(|s| s.parse().map_err(|_| Failure("invalid_packet_page")))
                    .transpose()?
            },
            status,
        })
    }
}
/// Owns one short transaction on the existing owner connection. Serialization retries are
/// bounded to confirmed rollbacks; a failed commit is an unknown outcome and is never retried.
pub async fn dispatch(
    connection: &mut PgConnection,
    method: &str,
    path: &str,
    query: Option<&str>,
    body: &[u8],
    settings: &Settings,
    answers: &answer_service::Settings,
) -> Result<(Value, bool)> {
    let route = route(path).ok_or(Failure("owner_route_not_found"))?;
    let post = matches!(route, Route::Preview(_) | Route::Create(_));
    let method_ok = match route {
        Route::Read(_) => matches!(method, "GET" | "PATCH"),
        Route::Questions(_) => method == "POST",
        Route::Review(_) => method == "POST",
        Route::Submission(_) => method == "POST",
        Route::Tracking(_) => method == "PATCH",
        Route::Answer(_, _) => method == "PATCH",
        _ => method == if post { "POST" } else { "GET" },
    };
    if !method_ok {
        return Err(Failure("packet_method_not_allowed"));
    }
    let request = if post {
        Some(packet_contract::normalize(
            serde_json::from_slice(body).map_err(|_| Failure("invalid_packet_preparation"))?,
            matches!(route, Route::Create(_)),
        )?)
    } else {
        None
    };
    let edit_kind = match route {
        Route::Read(_) if method == "PATCH" => Some(crate::packet_mutation_contract::Kind::Refresh),
        Route::Questions(_) => Some(crate::packet_mutation_contract::Kind::Questions),
        Route::Answer(_, _) => Some(crate::packet_mutation_contract::Kind::Answer),
        _ => None,
    };
    let edit = edit_kind
        .map(|kind| {
            crate::packet_mutation_contract::normalize(
                kind,
                serde_json::from_slice(body).map_err(|_| Failure("invalid_packet_edit_request"))?,
            )
        })
        .transpose()?;
    let review = if matches!(route, Route::Review(_)) {
        Some(crate::packet_review::request(
            serde_json::from_slice(body).map_err(|_| Failure("invalid_packet_review_request"))?,
        )?)
    } else {
        None
    };
    let submission = if matches!(route, Route::Submission(_)) {
        Some(crate::packet_tracking_contract::submission(
            serde_json::from_slice(body).map_err(|_| Failure("invalid_packet_tracking_request"))?,
        )?)
    } else {
        None
    };
    let tracking = if matches!(route, Route::Tracking(_)) {
        Some(crate::packet_tracking_contract::tracking(
            serde_json::from_slice(body).map_err(|_| Failure("invalid_packet_tracking_request"))?,
        )?)
    } else {
        None
    };
    let page = Page::parse(
        if matches!(route, Route::List | Route::Events(_)) {
            query
        } else {
            None
        },
        matches!(route, Route::Events(_)),
    )?;
    let parse_id = |s: &str| s.parse::<Uuid>().map_err(|_| Failure("invalid_packet_id"));
    if matches!(route, Route::Platforms) {
        return Ok((packet_platform::capabilities(), false));
    }
    for attempt in 0..2 {
        let mut tx = connection.begin().await.map_err(db)?;
        sqlx::query(
            if matches!(
                route,
                Route::Review(_) | Route::Handoff(_) | Route::Tracking(_) | Route::Submission(_)
            ) {
                "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"
            } else {
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"
            },
        )
        .execute(&mut *tx)
        .await
        .map_err(db)?;
        let now = Utc::now();
        let result=async {match route {
            Route::Preview(job)=>preview_in(&mut tx,parse_id(job)?,request.as_ref().unwrap(),settings,answers,now).await,
            Route::Create(job)=>create_in(&mut tx,parse_id(job)?,request.as_ref().unwrap(),settings,answers,now).await,
            Route::Read(packet) if method=="PATCH"=>crate::packet_mutation::run_in(&mut tx,parse_id(packet)?,edit.as_ref().unwrap(),None,settings,answers,now).await,
            Route::Read(packet)=>read_in(&mut tx,parse_id(packet)?,settings,now).await,
            Route::Questions(packet)=>crate::packet_mutation::run_in(&mut tx,parse_id(packet)?,edit.as_ref().unwrap(),None,settings,answers,now).await,
            Route::Answer(packet,field)=>crate::packet_mutation::run_in(&mut tx,parse_id(packet)?,edit.as_ref().unwrap(),Some(parse_id(field)?),settings,answers,now).await,
            Route::Review(packet)=>crate::packet_review::review_in(&mut tx,parse_id(packet)?,review.as_ref().unwrap(),settings).await,
            Route::Handoff(packet)=>crate::packet_review::handoff_in(&mut tx,parse_id(packet)?,settings).await,
            Route::Submission(packet)=>crate::packet_tracking::report_in(&mut tx,parse_id(packet)?,submission.as_ref().unwrap()).await,
            Route::Tracking(packet)=>crate::packet_tracking::track_in(&mut tx,parse_id(packet)?,tracking.as_ref().unwrap(),settings).await,
            Route::Readiness(packet)=>Ok(read_in(&mut tx,parse_id(packet)?,settings,now).await?["readiness"].clone()),
            Route::Events(packet)=>{
                let packet=parse_id(packet)?;
                let found:Option<Uuid>=sqlx::query_scalar("SELECT id FROM application_packets WHERE id=$1 FOR SHARE").bind(packet).fetch_optional(&mut *tx).await.map_err(db)?;
                if found.is_none(){return Err(Failure("packet_not_found"));}
                let rows:Vec<Value>=sqlx::query_scalar("SELECT to_jsonb(e) FROM application_events e WHERE packet_id=$1 ORDER BY packet_revision,created_at,id LIMIT $2 OFFSET $3").bind(packet).bind(page.limit).bind(page.offset).fetch_all(&mut *tx).await.map_err(db)?;
                Ok(json!(rows.into_iter().map(|e|packet_record::normalize(Kind::Event,e)).collect::<Result<Vec<_>>>()?))
            },
            Route::List=>{
                let ids:Vec<Uuid>=sqlx::query_scalar("SELECT id FROM application_packets WHERE ($1::text IS NULL OR platform=$1) AND ($2::uuid IS NULL OR job_id=$2) AND ($3::text IS NULL OR lifecycle_state=$3) ORDER BY created_at DESC,id LIMIT $4 OFFSET $5").bind(&page.platform).bind(page.job).bind(&page.status).bind(page.limit).bind(page.offset).fetch_all(&mut *tx).await.map_err(db)?;
                let mut packets=Vec::with_capacity(ids.len());
                for id in ids {packets.push(read_in(&mut tx,id,settings,now).await?);}
                Ok(json!({"packets":packets,"offset":page.offset,"limit":page.limit}))
            },
            Route::Platforms=>unreachable!(),
        }}.await;
        match result {
            Ok(value) => {
                tx.commit()
                    .await
                    .map_err(|_| Failure("packet_commit_outcome_unknown"))?;
                return Ok((value, matches!(route, Route::Create(_))));
            }
            Err(error) => {
                tx.rollback().await.map_err(db)?;
                if error == Failure("packet_serialization_rollback") && attempt == 0 {
                    continue;
                }
                return Err(error);
            }
        }
    }
    Err(Failure("packet_storage_conflict"))
}
