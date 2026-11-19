//! Durable owner questions. Approval binds current facts and a separate signed intent.
//! All changes, draft invalidation, history and nonce claims commit together.
use crate::{
    Failure, Result,
    answer_context::Stamp,
    answer_contract::{self, Generate},
    missing_contract::{self, Approve, Create, Edit},
    owner_proof::Proof,
    profile_store, question_classifier,
};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;

#[derive(Clone, Deserialize, Serialize)]
struct Record {
    id: String,
    candidate_profile_id: Uuid,
    question: String,
    question_category: String,
    job_id: Option<Uuid>,
    company_name: Option<String>,
    job_description: Option<String>,
    packet_id: Option<Uuid>,
    missing_information: Vec<String>,
    reason: String,
    required_input_type: String,
    created_at: String,
    status: String,
    version: u64,
    profile_version: i32,
    context_digest: String,
    answer: Option<String>,
    evidence_note: String,
    draft_id: Option<Uuid>,
    #[serde(default)]
    ever_approved: bool,
}
struct Stored {
    raw: Value,
    data: Record,
}
fn invalid() -> Failure {
    Failure("invalid_missing_input_record")
}
fn conflict() -> Failure {
    Failure("missing_input_version_conflict")
}
fn db(error: sqlx::Error) -> Failure {
    if error
        .as_database_error()
        .is_some_and(|e| matches!(e.code().as_deref(), Some("40001" | "40P01")))
    {
        conflict()
    } else {
        Failure("profile_database_error")
    }
}
fn hex(text: &str, len: usize) -> bool {
    text.len() == len
        && text
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
}
fn key(id: &str) -> Result<String> {
    if !hex(id, 32) {
        return Err(Failure("missing_input_not_found"));
    }
    Ok(format!("needs_input:{id}"))
}
fn validate(raw: Value, id: &str, profile: Uuid) -> Result<Stored> {
    if crate::python_json::serialize(&raw, true, false).len() > 512 * 1024
        || [
            "id",
            "candidate_profile_id",
            "question",
            "question_category",
            "job_id",
            "company_name",
            "job_description",
            "packet_id",
            "missing_information",
            "reason",
            "required_input_type",
            "created_at",
            "status",
            "version",
            "profile_version",
            "context_digest",
            "answer",
            "evidence_note",
            "draft_id",
        ]
        .iter()
        .any(|k| raw.get(*k).is_none())
    {
        return Err(invalid());
    }
    let data: Record = serde_json::from_value(raw.clone()).map_err(|_| invalid())?;
    if data.id != id
        || data.candidate_profile_id != profile
        || !hex(&data.context_digest, 64)
        || data.version == 0
        || data.profile_version < 1
        || !["needs_input", "draft", "approved", "review_required"].contains(&data.status.as_str())
        || !["text", "number", "choice", "evidence", "profile_edit"]
            .contains(&data.required_input_type.as_str())
        || ![
            "profile_link",
            "personal_details",
            "short_text",
            "project_explanation",
            "technical_experience",
            "motivation",
            "startup_interest",
            "work_authorization",
            "compensation",
            "file_upload",
            "unknown",
        ]
        .contains(&data.question_category.as_str())
        || data.missing_information.len() > 20
        || data
            .missing_information
            .iter()
            .any(|s| s.chars().count() > 2000)
        || data
            .answer
            .as_ref()
            .is_some_and(|s| s.chars().count() > 10000)
        || data.evidence_note.chars().count() > 2000
        || data.reason.chars().count() > 2000
        || DateTime::parse_from_rfc3339(&data.created_at).is_err()
    {
        return Err(invalid());
    }
    request(&data)?;
    Ok(Stored { raw, data })
}
fn request(data: &Record) -> Result<Generate> {
    answer_contract::normalize(json!({"question":data.question,"job_id":data.job_id,"company_name":data.company_name,"job_description":data.job_description})).map_err(|_|invalid())
}
async fn begin(
    connection: &mut PgConnection,
    read_only: bool,
) -> Result<Transaction<'_, Postgres>> {
    let mut tx = connection.begin().await.map_err(db)?;
    sqlx::query(if read_only {
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    } else {
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"
    })
    .execute(&mut *tx)
    .await
    .map_err(db)?;
    Ok(tx)
}
async fn primary(tx: &mut Transaction<'_, Postgres>, lock: bool) -> Result<Uuid> {
    if lock {
        sqlx::query_scalar(
            "SELECT id FROM candidate_profiles WHERE singleton_key='primary' FOR SHARE",
        )
        .fetch_optional(&mut **tx)
        .await
        .map_err(db)?
        .ok_or(Failure("profile_not_found"))
    } else {
        let profile = profile_store::get(tx).await?;
        profile.value["id"]
            .as_str()
            .and_then(|s| s.parse().ok())
            .ok_or(invalid())
    }
}
async fn row(
    tx: &mut Transaction<'_, Postgres>,
    id: &str,
    profile: Uuid,
    lock: bool,
) -> Result<Stored> {
    let key = key(id)?;
    let raw:Option<Value>=sqlx::query_scalar(if lock {"SELECT value FROM owner_preferences WHERE key=$1 AND value->>'candidate_profile_id'=$2 FOR UPDATE"} else {"SELECT value FROM owner_preferences WHERE key=$1 AND value->>'candidate_profile_id'=$2"}).bind(key).bind(profile.to_string()).fetch_optional(&mut **tx).await.map_err(db)?;
    validate(raw.ok_or(Failure("missing_input_not_found"))?, id, profile)
}
async fn view(tx: &mut Transaction<'_, Postgres>, stored: Stored) -> Result<Value> {
    let stamp = Stamp::load_in(tx, &request(&stored.data)?).await?;
    let stale = stored.data.context_digest != stamp.missing();
    let effective = if stale && stored.data.status == "approved" {
        "review_required"
    } else {
        &stored.data.status
    };
    let mut value = serde_json::to_value(&stored.data).map_err(|_| invalid())?;
    value["stale"] = json!(stale);
    value["effective_status"] = json!(effective);
    value["href"] = json!(format!(
        "/api/v1/application-answers/missing/{}",
        stored.data.id
    ));
    let date = DateTime::parse_from_rfc3339(&stored.data.created_at).map_err(|_| invalid())?;
    value["created_at"] = json!(date.with_timezone(&Utc).to_rfc3339_opts(
        if date.timestamp_subsec_micros() == 0 {
            SecondsFormat::Secs
        } else {
            SecondsFormat::Micros
        },
        true
    ));
    Ok(value)
}
async fn clock(tx: &mut Transaction<'_, Postgres>) -> Result<String> {
    sqlx::query_scalar("SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.US')||'+00:00'").fetch_one(&mut **tx).await.map_err(db)
}
fn page(offset: i64, limit: i64) -> Result<()> {
    if !(0..=100000).contains(&offset) || !(1..=100).contains(&limit) {
        return Err(Failure("invalid_missing_input_page"));
    }
    Ok(())
}
pub async fn read(connection: &mut PgConnection, id: &str) -> Result<Value> {
    key(id)?;
    let mut tx = begin(connection, true).await?;
    let profile = primary(&mut tx, false).await?;
    let stored = row(&mut tx, id, profile, false).await?;
    let result = view(&mut tx, stored).await?;
    tx.commit().await.map_err(db)?;
    Ok(result)
}
pub async fn list(connection: &mut PgConnection, offset: i64, limit: i64) -> Result<Value> {
    page(offset, limit)?;
    let mut tx = begin(connection, true).await?;
    let profile = primary(&mut tx, false).await?;
    let rows:Vec<Value>=sqlx::query_scalar("SELECT value FROM owner_preferences WHERE starts_with(key,'needs_input:') AND value->>'candidate_profile_id'=$1 ORDER BY created_at DESC,key OFFSET $2 LIMIT $3").bind(profile.to_string()).bind(offset).bind(limit).fetch_all(&mut *tx).await.map_err(db)?;
    let mut requests = vec![];
    for raw in rows {
        let id = raw["id"].as_str().ok_or_else(invalid)?.to_owned();
        key(&id)?;
        requests.push(view(&mut tx, validate(raw, &id, profile)?).await?);
    }
    tx.commit().await.map_err(db)?;
    Ok(json!({"requests":requests,"offset":offset,"limit":limit}))
}
/// Called by generation only after it abstains; questions confer no application authority.
pub async fn ensure_in(tx: &mut Transaction<'_, Postgres>, input: &Create) -> Result<String> {
    ensure_retryable_in(tx, input).await.map_err(|error| {
        if error == Failure("missing_input_transaction_rollback") {
            conflict()
        } else {
            error
        }
    })
}
/// Preserve a known aborted transaction for a transaction-owning caller's bounded retry.
pub(crate) async fn ensure_retryable_in(
    tx: &mut Transaction<'_, Postgres>,
    input: &Create,
) -> Result<String> {
    let checked = missing_contract::normalize_create(
        serde_json::to_value(input).map_err(|_| Failure("invalid_missing_input_request"))?,
    )?;
    let input = &checked;
    missing_contract::permitted(&input.request.question, "")?;
    let stamp = Stamp::load_in(tx, &input.request).await?;
    let profile = stamp.profile_id();
    if let Some(packet) = input.packet_id {
        let context: Option<(Uuid, Uuid)> = sqlx::query_as(
            "SELECT candidate_profile_id,job_id FROM application_packets WHERE id=$1",
        )
        .bind(packet)
        .fetch_optional(&mut **tx)
        .await
        .map_err(db)?;
        if !context.is_some_and(|(candidate, job)| {
            candidate == profile && Some(job) == input.request.job_id
        }) {
            return Err(Failure("missing_input_packet_context_mismatch"));
        }
    }
    let key = missing_contract::key_for(profile, &input.request, input.packet_id);
    if input.packet_id.is_some() {
        // Older form inspections added the packet ID after deriving an unscoped
        // key. Retain that review link only when its full saved binding matches.
        let legacy_key = missing_contract::key_for(profile, &input.request, None);
        let legacy: Option<Value> = sqlx::query_scalar(
            "SELECT value FROM owner_preferences WHERE key=$1 AND value->>'packet_id'=$2 AND NOT EXISTS (SELECT 1 FROM owner_preferences WHERE key=$3)",
        )
        .bind(&legacy_key)
        .bind(input.packet_id.map(|id| id.to_string()))
        .bind(&key)
        .fetch_optional(&mut **tx)
        .await
        .map_err(db)?;
        if let Some(legacy) = legacy {
            let legacy_id = legacy_key.trim_start_matches("needs_input:");
            let saved = validate(legacy, legacy_id, profile)?;
            if !missing_contract::matches_context(
                &saved.raw,
                profile,
                &input.request,
                input.packet_id,
            ) {
                return Err(Failure("missing_input_identity_collision"));
            }
            return Ok(legacy_id.to_owned());
        }
    }
    let id = key.trim_start_matches("needs_input:").to_owned();
    let value = json!({"id":id,"candidate_profile_id":profile,"question":input.request.question,"question_category":question_classifier::classify(&input.request.question).question_type,"job_id":input.request.job_id,"company_name":input.request.company_name,"job_description":input.request.job_description,"packet_id":input.packet_id,"missing_information":[input.missing_fact],"reason":input.reason,"required_input_type":input.required_input_type,"created_at":clock(tx).await?,"status":"needs_input","version":1,"profile_version":stamp.profile_version(),"context_digest":stamp.missing(),"answer":null,"evidence_note":"","draft_id":null});
    sqlx::query("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES($1,$2,clock_timestamp(),clock_timestamp()) ON CONFLICT(key) DO NOTHING").bind(key).bind(value).execute(&mut **tx).await.map_err(|error| {
        if error.as_database_error().is_some_and(|e| matches!(e.code().as_deref(), Some("40001" | "40P01"))) {
            Failure("missing_input_transaction_rollback")
        } else { db(error) }
    })?;
    let existing = row(tx, &id, profile, false).await?;
    if !missing_contract::matches_context(&existing.raw, profile, &input.request, input.packet_id) {
        return Err(Failure("missing_input_identity_collision"));
    }
    Ok(id)
}
pub async fn create(connection: &mut PgConnection, input: Create) -> Result<Value> {
    let mut tx = begin(connection, false).await?;
    let id = ensure_in(&mut tx, &input).await?;
    let profile = primary(&mut tx, false).await?;
    let stored = row(&mut tx, &id, profile, false).await?;
    let result = view(&mut tx, stored).await?;
    tx.commit().await.map_err(db)?;
    Ok(result)
}
async fn replace(
    tx: &mut Transaction<'_, Postgres>,
    old: &Stored,
    new: Value,
    operation: &str,
) -> Result<()> {
    let changed: Option<Value> = sqlx::query_scalar("UPDATE owner_preferences SET value=$1,updated_at=clock_timestamp() WHERE key=$2 AND value=$3 RETURNING value").bind(&new).bind(key(&old.data.id)?).bind(&old.raw).fetch_optional(&mut **tx).await.map_err(db)?;
    match changed {
        None => return Err(conflict()),
        Some(saved) if saved != new => return Err(invalid()),
        _ => {}
    }
    let audit = json!({"request_id":old.data.id,"candidate_profile_id":old.data.candidate_profile_id,"operation":operation,"version":new["version"],"previous":old.raw,"recorded_at":clock(tx).await?});
    sqlx::query("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES($1,$2,clock_timestamp(),clock_timestamp())").bind(format!("input_rev:{}",Uuid::new_v4().simple())).bind(audit).execute(&mut **tx).await.map_err(db)?;
    Ok(())
}
pub async fn edit(connection: &mut PgConnection, id: &str, input: Edit) -> Result<Value> {
    let input = missing_contract::normalize_edit(
        serde_json::to_value(input).map_err(|_| Failure("invalid_missing_input_request"))?,
    )?;
    key(id)?;
    let mut tx = begin(connection, false).await?;
    let profile = primary(&mut tx, true).await?;
    let old = row(&mut tx, id, profile, true).await?;
    if old.data.version != input.expected_version {
        return Err(conflict());
    }
    missing_contract::permitted(
        &old.data.question,
        &format!("{} {}", input.answer, input.evidence_note),
    )?;
    let stamp = Stamp::load_in(&mut tx, &request(&old.data)?).await?;
    let mut new = old.raw.clone();
    new["answer"] = json!(input.answer);
    new["evidence_note"] = json!(input.evidence_note);
    new["status"] = json!("draft");
    new["version"] = json!(old.data.version.checked_add(1).ok_or_else(conflict)?);
    new["profile_version"] = json!(stamp.profile_version());
    new["context_digest"] = json!(stamp.missing());
    new["draft_id"] = Value::Null;
    if let Some(draft) = old.data.draft_id {
        let owner: Option<Uuid> = sqlx::query_scalar(
            "SELECT candidate_profile_id FROM application_answer_drafts WHERE id=$1 FOR UPDATE",
        )
        .bind(draft)
        .fetch_optional(&mut *tx)
        .await
        .map_err(db)?;
        if owner.is_some_and(|owner| owner != profile) {
            return Err(Failure("missing_input_draft_context_mismatch"));
        }
        sqlx::query("UPDATE application_answer_drafts SET review_status='discarded',updated_at=clock_timestamp() WHERE id=$1 AND candidate_profile_id=$2").bind(draft).bind(profile).execute(&mut *tx).await.map_err(db)?;
    }
    let result = view(&mut tx, validate(new.clone(), id, profile)?).await?;
    replace(&mut tx, &old, new, "edited").await?;
    tx.commit().await.map_err(db)?;
    Ok(result)
}
pub async fn approve(
    connection: &mut PgConnection,
    id: &str,
    input: Approve,
    proof: Proof,
) -> Result<Value> {
    let input = missing_contract::normalize_approve(
        serde_json::to_value(input).map_err(|_| Failure("invalid_missing_input_request"))?,
    )?;
    key(id)?;
    let mut tx = begin(connection, false).await?;
    let profile = primary(&mut tx, true).await?;
    let old = row(&mut tx, id, profile, true).await?;
    let stamp = Stamp::load_in(&mut tx, &request(&old.data)?).await?;
    if old.data.version != input.expected_version
        || u64::try_from(stamp.profile_version()).ok() != Some(input.expected_profile_version)
    {
        return Err(conflict());
    }
    if old.data.status != "draft"
        || old.data.answer.as_ref().is_none_or(|s| s.is_empty())
        || old.data.evidence_note.is_empty()
    {
        return Err(Failure("factual_answer_and_evidence_note_required"));
    }
    if old.data.context_digest != stamp.missing() {
        return Err(Failure(
            "missing_input_context_changed_edit_before_approval",
        ));
    }
    missing_contract::permitted(
        &old.data.question,
        &format!(
            "{} {}",
            old.data.answer.as_deref().unwrap(),
            old.data.evidence_note
        ),
    )?;
    // Consume the exact route proof in the same transaction as the reviewed draft/history.
    proof
        .claim_for(
            &mut tx,
            &format!("/api/v1/application-answers/missing/{id}/approve"),
        )
        .await?;
    let draft = Uuid::new_v4();
    let saved: Value = sqlx::query_scalar("INSERT INTO application_answer_drafts(id,candidate_profile_id,job_id,question,answer,question_category,writing_style,evidence_references,candidate_profile_version,review_status,provider,model,created_at,updated_at) VALUES($1,$2,$3,$4,$5,$6,'professional','[]',$7,'reviewed',NULL,NULL,clock_timestamp(),clock_timestamp()) RETURNING to_jsonb(application_answer_drafts.*)").bind(draft).bind(profile).bind(old.data.job_id).bind(&old.data.question).bind(&old.data.answer).bind(&old.data.question_category).bind(stamp.profile_version()).fetch_one(&mut *tx).await.map_err(db)?;
    crate::answer_store::record(saved.clone(), stamp.profile_version())?;
    if saved["id"] != json!(draft)
        || saved["candidate_profile_id"] != json!(profile)
        || saved["job_id"] != json!(old.data.job_id)
        || saved["question"] != old.data.question
        || saved["answer"] != json!(old.data.answer)
        || saved["review_status"] != "reviewed"
        || saved["candidate_profile_version"] != stamp.profile_version()
    {
        return Err(Failure("missing_input_draft_context_mismatch"));
    }
    let mut new = old.raw.clone();
    new["ever_approved"] = json!(true);
    new["status"] = json!("approved");
    new["version"] = json!(old.data.version.checked_add(1).ok_or_else(conflict)?);
    new["draft_id"] = json!(draft);
    let result = view(&mut tx, validate(new.clone(), id, profile)?).await?;
    replace(&mut tx, &old, new, "approved_exact_context").await?;
    tx.commit().await.map_err(db)?;
    Ok(result)
}
pub async fn history(
    connection: &mut PgConnection,
    id: &str,
    offset: i64,
    limit: i64,
) -> Result<Value> {
    key(id)?;
    page(offset, limit)?;
    let mut tx = begin(connection, true).await?;
    let profile = primary(&mut tx, false).await?;
    row(&mut tx, id, profile, false).await?;
    let history:Vec<Value>=sqlx::query_scalar("SELECT value FROM owner_preferences WHERE starts_with(key,'input_rev:') AND value->>'request_id'=$1 AND value->>'candidate_profile_id'=$2 ORDER BY created_at DESC,key OFFSET $3 LIMIT $4").bind(id).bind(profile.to_string()).bind(offset).bind(limit).fetch_all(&mut *tx).await.map_err(db)?;
    tx.commit().await.map_err(db)?;
    Ok(json!({"history":history}))
}
/// Generation may use an approval only after comparing full identity and current facts.
pub async fn approved_in(
    tx: &mut Transaction<'_, Postgres>,
    request: &Generate,
) -> Result<Option<Value>> {
    let profile = primary(tx, false).await?;
    let key = missing_contract::key_for(profile, request, None);
    let id = key.trim_start_matches("needs_input:");
    let raw: Option<Value> = sqlx::query_scalar(
        "SELECT value FROM owner_preferences WHERE key=$1 AND value->>'candidate_profile_id'=$2",
    )
    .bind(&key)
    .bind(profile.to_string())
    .fetch_optional(&mut **tx)
    .await
    .map_err(db)?;
    let Some(raw) = raw else {
        return Ok(None);
    };
    let stored = validate(raw, id, profile)?;
    if stored.data.status != "approved"
        || !missing_contract::matches_context(&stored.raw, profile, request, None)
        || stored.data.draft_id.is_none()
        || stored
            .data
            .answer
            .as_ref()
            .is_none_or(|s| s.trim().is_empty())
        || stored.data.evidence_note.trim().is_empty()
    {
        return Ok(None);
    }
    let stamp = Stamp::load_in(tx, request).await?;
    if stored.data.context_digest != stamp.missing()
        || stored.data.profile_version != stamp.profile_version()
    {
        return Ok(None);
    }
    let draft:Option<Value>=sqlx::query_scalar("SELECT jsonb_build_object('candidate_profile_id',candidate_profile_id,'job_id',job_id,'question',question,'answer',answer,'question_category',question_category,'review_status',review_status,'candidate_profile_version',candidate_profile_version) FROM application_answer_drafts WHERE id=$1").bind(stored.data.draft_id).fetch_optional(&mut **tx).await.map_err(db)?;
    let Some(draft) = draft else {
        return Ok(None);
    };
    if draft["candidate_profile_id"] != json!(profile)
        || draft["job_id"] != json!(request.job_id)
        || draft["answer"] != json!(stored.data.answer)
        || draft["question"] != stored.data.question
        || draft["question_category"] != stored.data.question_category
        || draft["review_status"] != "reviewed"
        || draft["candidate_profile_version"] != json!(stamp.profile_version())
    {
        return Ok(None);
    }
    missing_contract::permitted(
        &stored.data.question,
        stored.data.answer.as_deref().ok_or_else(invalid)?,
    )?;
    Ok(Some(view(tx, stored).await?))
}
