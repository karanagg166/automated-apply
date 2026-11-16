//! Original local draft ledger. Every revision is current-fact bound; approval cannot send.
use super::context::Context;
use super::*;
use sqlx::{Postgres, Transaction};
use std::collections::BTreeSet;
pub const PATH: &str = "/api/v1/outreach/drafts";
#[derive(Clone, Copy)]
pub enum Route {
    List,
    Detail(Uuid),
    Eligibility(Uuid),
    Approve(Uuid),
    Reject(Uuid),
}
impl Route {
    pub fn accepts(self, method: &str) -> bool {
        match self {
            Self::Detail(_) => matches!(method, "GET" | "PATCH"),
            Self::Approve(_) | Self::Reject(_) => method == "POST",
            _ => method == "GET",
        }
    }
    pub fn allow(self) -> &'static str {
        match self {
            Self::Detail(_) => "GET, PATCH",
            Self::Approve(_) | Self::Reject(_) => "POST",
            _ => "GET",
        }
    }
}
pub fn route(path: &str) -> Option<Route> {
    if path == PATH {
        return Some(Route::List);
    }
    let tail = path.strip_prefix(PATH)?.strip_prefix('/')?;
    if tail == "preview" {
        return None;
    }
    let (id, action) = tail.split_once('/').unwrap_or((tail, ""));
    let id = id.parse().ok()?;
    match action {
        "" => Some(Route::Detail(id)),
        "eligibility" => Some(Route::Eligibility(id)),
        "approve" => Some(Route::Approve(id)),
        "reject" => Some(Route::Reject(id)),
        _ => None,
    }
}
pub fn sentences(text: &str) -> Result<BTreeSet<String>> {
    static SPLIT: std::sync::LazyLock<crate::legacy_regex::Regex> =
        std::sync::LazyLock::new(|| crate::legacy_regex::Regex::new(r"(?<=[.!?])\s+|\n", false));
    if text.len() > 262144 {
        return Err(invalid());
    }
    let mut output = BTreeSet::new();
    let mut start = 0;
    for found in SPLIT.find(text)? {
        let s = text[start..found.start].trim_matches(crate::context_contract::python_space);
        if !s.is_empty() {
            output.insert(s.to_owned());
        }
        start = found.end;
    }
    let last = text[start..].trim_matches(crate::context_contract::python_space);
    if !last.is_empty() {
        output.insert(last.to_owned());
    }
    Ok(output)
}
pub fn approval_digest(value: &Value) -> String {
    fingerprint(&json!([
        value["subject"],
        value["body"],
        value["recipient_email"],
        value["evidence_hash"],
        value["draft_revision"]
    ]))
}
pub(super) fn request_hash(input: &Value, origin: &str) -> String {
    let mut value = input.clone();
    value
        .as_object_mut()
        .expect("normalized input")
        .remove("idempotency_key");
    value["origin"] = json!(origin);
    fingerprint(&value)
}
async fn begin(c: &mut PgConnection) -> Result<Transaction<'_, Postgres>> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    crate::execution::lock_owner_in(&mut tx).await?;
    Ok(tx)
}
pub(super) async fn get_in(
    tx: &mut Transaction<'_, Postgres>,
    id: Uuid,
    lock: bool,
) -> Result<Value> {
    let value:Option<Value>=sqlx::query_scalar(&format!("SELECT CASE WHEN octet_length(to_jsonb(d)::text)<=18874368 THEN to_jsonb(d) ELSE NULL END FROM outreach_logs d WHERE id=$1{}",if lock{" FOR UPDATE"}else{""})).bind(id).fetch_optional(&mut **tx).await.map_err(db)?.ok_or(Failure("outreach_draft_not_found"))?;
    let value = value.ok_or_else(invalid)?;
    if !value["draft_revision"]
        .as_i64()
        .is_some_and(|n| (1..=i32::MAX as i64).contains(&n))
        || !value["generation_metadata"].is_object()
        || !value["evidence_snapshot"].is_object()
    {
        return Err(invalid());
    }
    for (key, max) in [
        ("subject", 16384),
        ("body", 131072),
        ("recipient_email", 254),
        ("approval_status", 50),
        ("created_via", 20),
    ] {
        if !value[key].is_null() && !value[key].as_str().is_some_and(|s| s.len() <= max) {
            return Err(invalid());
        }
    }
    if value["subject"].as_str().is_none() || value["body"].as_str().is_none() {
        return Err(invalid());
    }
    Ok(value)
}
async fn editable(tx: &mut Transaction<'_, Postgres>, value: &Value) -> Result<()> {
    let id = value["id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    let attempts: Vec<Uuid> = sqlx::query_scalar(
        "SELECT id FROM outreach_send_attempts WHERE draft_id=$1 ORDER BY id LIMIT 2 FOR SHARE",
    )
    .bind(id)
    .fetch_all(&mut **tx)
    .await
    .map_err(db)?;
    if !attempts.is_empty() || !value["sent_at"].is_null() {
        return Err(Failure("outreach_send_reserved_draft_immutable"));
    }
    Ok(())
}
async fn eligibility_in(
    tx: &mut Transaction<'_, Postgres>,
    value: &Value,
    settings: &crate::contacts::Settings,
    lock: bool,
) -> Result<Value> {
    let mut blockers = BTreeSet::<String>::new();
    let context = if value["contact_id"].is_null() {
        None
    } else {
        let input =
            json!({"contact_id":value["contact_id"],"job_id":value["job_id"],"use_llm":false});
        let input = contract::normalize(contract::Kind::Input, input)?;
        match Context::load_in(tx, &input, settings, lock).await {
            Ok(c) => Some(c),
            Err(e)
                if matches!(
                    e.0,
                    "outreach_contact_not_found"
                        | "outreach_contact_employer_missing"
                        | "outreach_job_employer_mismatch"
                ) =>
            {
                None
            }
            Err(e) => return Err(e),
        }
    };
    let mut warnings = Vec::new();
    let original = &value["generation_metadata"];
    if let Some(context) = context {
        blockers.extend(context.blockers.iter().map(|s| s.to_string()));
        warnings = context.warnings.clone();
        if json!(context.digest()) != value["evidence_hash"] {
            blockers.insert("material_evidence_changed_regenerate_draft".into());
        }
        if value["recipient_email"] != context.contact["email"] {
            blockers.insert("recipient_changed_or_unverified".into());
        }
        if let (Some(body), Some(subject)) = (
            original["body"].as_str().filter(|s| !s.is_empty()),
            original["subject"].as_str().filter(|s| !s.is_empty()),
        ) {
            let mut supported = sentences(body)?;
            for fact in &context.facts {
                let project = fact["facts"].get("project").unwrap_or(&fact["facts"]);
                for key in [
                    "contribution",
                    "implementation_details",
                    "engineering_challenges",
                    "solutions",
                ] {
                    if let Some(s) = project[key].as_str() {
                        supported.extend(sentences(s)?);
                    }
                }
            }
            if !sentences(value["body"].as_str().ok_or_else(invalid)?)?.is_subset(&supported)
                || value["subject"] != subject
            {
                blockers.insert("unsupported_edited_claim_requires_grounding".into());
            }
        } else {
            blockers.insert("legacy_draft_requires_regeneration".into());
        }
    } else {
        blockers.insert("contact_or_job_context_missing".into());
    }
    if value["approval_status"] == "rejected" {
        blockers.insert("draft_rejected".into());
    }
    let current = blockers.is_empty()
        && value["approval_status"] == "approved"
        && value["approved_revision"] == value["draft_revision"]
        && value["approval_hash"] == approval_digest(value);
    let references = original["evidence_references"]
        .as_array()
        .map(|v| v.iter().take(10001).cloned().collect::<Vec<_>>())
        .unwrap_or_default();
    if references.len() > 10000 {
        return Err(invalid());
    }
    // References are labels only. Stored private metadata cannot supply arbitrary response fields.
    let references = references
        .into_iter()
        .map(|r| {
            let kind = r["source_type"]
                .as_str()
                .filter(|s| s.len() <= 100)
                .ok_or_else(invalid)?;
            let id = r["source_id"]
                .as_str()
                .filter(|s| s.len() <= 300)
                .ok_or_else(invalid)?;
            Ok(json!({"source_type":kind,"source_id":id}))
        })
        .collect::<Result<Vec<_>>>()?;
    Ok(
        json!({"eligible_for_approval":blockers.is_empty(),"email_send_ready":false,"blockers":blockers,"warnings":warnings,"requires_review":true,"recipient_email":value["recipient_email"],"evidence_references":references,"approval_status":value["approval_status"],"approval_current":current,"sending_enabled":false}),
    )
}
pub(super) async fn read_in(
    tx: &mut Transaction<'_, Postgres>,
    value: &Value,
    settings: &crate::contacts::Settings,
) -> Result<Value> {
    let eligibility = eligibility_in(tx, value, settings, false).await?;
    let id = value["id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    let attempts:Vec<Value>=sqlx::query_scalar("SELECT jsonb_build_object('id',id,'status',status,'draft_revision',draft_revision) FROM outreach_send_attempts WHERE draft_id=$1 ORDER BY id LIMIT 2").bind(id).fetch_all(&mut **tx).await.map_err(db)?;
    if attempts.len() > 1 {
        return Err(invalid());
    }
    let mut output = json!({});
    for key in [
        "id",
        "job_id",
        "contact_id",
        "subject",
        "body",
        "recipient_email",
        "draft_revision",
        "approval_status",
        "approved_revision",
        "approved_at",
        "candidate_profile_version",
        "validation_status",
        "created_via",
        "last_edited_at",
        "created_at",
        "updated_at",
        "gmail_draft_id",
        "gmail_message_id",
        "sent_at",
    ] {
        output[key] = value[key].clone();
    }
    let metadata = &value["generation_metadata"]["provider_metadata"];
    let mut provider = json!({"used_llm":metadata["used_llm"].as_bool().unwrap_or(false)});
    for key in ["provider", "model"] {
        if let Some(s) = metadata[key]
            .as_str()
            .filter(|s| s.len() <= 200 && !s.chars().any(char::is_control))
        {
            provider[key] = json!(s);
        }
    }
    if let Some(usage) = metadata["usage"].as_object() {
        let mut safe = json!({});
        for key in ["input_tokens", "output_tokens"] {
            if let Some(n) = usage
                .get(key)
                .and_then(Value::as_u64)
                .filter(|n| *n <= 1_000_000_000)
            {
                safe[key] = json!(n);
            }
        }
        provider["usage"] = safe;
    }
    let attempt = attempts.first();
    output["eligibility"] = eligibility;
    output["requires_review"] = json!(true);
    output["provider_metadata"] = provider;
    output["outbound_messages_sent"] = json!(i32::from(
        attempt.is_some_and(|a| a["status"] == "accepted_by_gmail")
    ));
    output["outbound_count_basis"] = json!("saved_historical_provider_status");
    output["sending_enabled"] = json!(false);
    output["delivery_verified"] = json!(false);
    output["delivery_status"] = attempt.map(|a| a["status"].clone()).unwrap_or_else(|| {
        json!(if value["sent_at"].is_null() {
            "not_attempted"
        } else {
            "legacy_sent_unverified"
        })
    });
    output["send_attempt_id"] = attempt.map(|a| a["id"].clone()).unwrap_or(Value::Null);
    output["sent_draft_revision"] = attempt
        .map(|a| a["draft_revision"].clone())
        .unwrap_or(Value::Null);
    Ok(output)
}
async fn write_in(
    tx: &mut Transaction<'_, Postgres>,
    before: &Value,
    after: &Value,
) -> Result<Value> {
    let mut original_material = before.clone();
    let mut next_material = after.clone();
    for key in ["draft_revision", "updated_at"] {
        original_material
            .as_object_mut()
            .ok_or_else(invalid)?
            .remove(key);
        next_material
            .as_object_mut()
            .ok_or_else(invalid)?
            .remove(key);
    }
    if original_material == next_material {
        return Ok(before.clone());
    }
    let id = before["id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    let got:Option<Value>=sqlx::query_scalar("UPDATE outreach_logs d SET subject=$1::jsonb->>'subject',body=$1::jsonb->>'body',recipient_email=$1::jsonb->>'recipient_email',draft_revision=($1::jsonb->>'draft_revision')::integer,approval_status=$1::jsonb->>'approval_status',approved_at=($1::jsonb->>'approved_at')::timestamptz,approval_hash=$1::jsonb->>'approval_hash',approved_revision=($1::jsonb->>'approved_revision')::integer,last_edited_at=($1::jsonb->>'last_edited_at')::timestamptz,validation_status=$1::jsonb->>'validation_status',updated_at=($1::jsonb->>'updated_at')::timestamptz WHERE id=$2 AND draft_revision=$3 RETURNING to_jsonb(d)").bind(after).bind(id).bind(before["draft_revision"].as_i64().ok_or_else(invalid)? as i32).fetch_optional(&mut **tx).await.map_err(db)?;
    let got = got.ok_or(Failure("outreach_write_ack_failed"))?;
    let finished = now_in(tx).await?;
    let parse = |v: &Value| {
        DateTime::parse_from_rfc3339(v.as_str().ok_or_else(invalid)?)
            .map(|at| at.to_utc())
            .map_err(|_| invalid())
    };
    let lower = parse(&after["updated_at"])?;
    let upper = parse(&finished)?;
    let mut expected = after.clone();
    for key in ["updated_at", "last_edited_at"] {
        if key == "updated_at" || after[key] != before[key] {
            let at = parse(&got[key])?;
            if at < lower || at > upper {
                return Err(Failure("outreach_write_ack_failed"));
            }
            expected[key] = got[key].clone();
        }
    }
    if got != expected || get_in(tx, id, false).await? != expected {
        return Err(Failure("outreach_write_ack_failed"));
    }
    Ok(expected)
}
async fn now_in(tx: &mut Transaction<'_, Postgres>) -> Result<Value> {
    sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut **tx)
        .await
        .map_err(db)
}
pub async fn create_local(
    c: &mut PgConnection,
    input: Value,
    origin: &str,
    settings: &crate::contacts::Settings,
) -> Result<Value> {
    let input = contract::normalize(contract::Kind::Input, input)?;
    if !matches!(origin, "rest" | "mcp") {
        return Err(Failure("invalid_outreach_origin"));
    }
    if origin == "rest" && input["use_llm"] != false {
        return Err(Failure("outreach_writer_intent_required"));
    }
    let mut tx = begin(c).await?;
    let hash = request_hash(&input, origin);
    if let Some(key) = input["idempotency_key"].as_str() {
        if let Some(id) =
            sqlx::query_scalar::<_, Uuid>("SELECT id FROM outreach_logs WHERE idempotency_key=$1")
                .bind(key)
                .fetch_optional(&mut *tx)
                .await
                .map_err(db)?
        {
            let row = get_in(&mut tx, id, true).await?;
            if row["request_hash"] != hash {
                return Err(Failure("outreach_idempotency_key_conflict"));
            }
            let result = read_in(&mut tx, &row, settings).await?;
            tx.commit()
                .await
                .map_err(|_| Failure("outreach_commit_outcome_unknown"))?;
            return Ok(result);
        }
    }
    let context = Context::load_in(&mut tx, &input, settings, true).await?;
    let preview = context.preview(input.clone())?;
    if preview["status"] != "draft_ready" {
        tx.rollback().await.map_err(db)?;
        return Ok(preview);
    }
    let id = Uuid::new_v4();
    let stamp = now_in(&mut tx).await?;
    let mut metadata = preview.clone();
    metadata["max_length"] = input["max_length"].clone();
    let expected = json!({"id":id,"job_id":input["job_id"],"contact_id":input["contact_id"],"subject":preview["subject"],"body":preview["body"],"resume_version":null,"gmail_draft_id":null,"gmail_message_id":null,"gmail_thread_id":null,"approval_status":"pending_approval","approved_at":null,"sent_at":null,"connected_account_id":null,"draft_revision":1,"candidate_profile_version":context.profile["version"],"recipient_email":context.contact["email"],"evidence_snapshot":context.snapshot,"evidence_hash":context.digest(),"approval_hash":null,"approved_revision":null,"last_edited_at":null,"validation_status":"requires_review","generation_metadata":metadata,"created_via":origin,"idempotency_key":input["idempotency_key"],"request_hash":hash,"created_at":stamp,"updated_at":stamp});
    let got:Option<Value>=sqlx::query_scalar("INSERT INTO outreach_logs AS d(id,job_id,contact_id,subject,body,approval_status,draft_revision,candidate_profile_version,recipient_email,evidence_snapshot,evidence_hash,validation_status,generation_metadata,created_via,idempotency_key,request_hash,created_at,updated_at) VALUES($1,($2::jsonb->>'job_id')::uuid,($2::jsonb->>'contact_id')::uuid,$2::jsonb->>'subject',$2::jsonb->>'body','pending_approval',1,($2::jsonb->>'candidate_profile_version')::integer,$2::jsonb->>'recipient_email',$2::jsonb->'evidence_snapshot',$2::jsonb->>'evidence_hash','requires_review',$2::jsonb->'generation_metadata',$2::jsonb->>'created_via',$2::jsonb->>'idempotency_key',$2::jsonb->>'request_hash',($2::jsonb->>'created_at')::timestamptz,($2::jsonb->>'updated_at')::timestamptz) RETURNING to_jsonb(d)").bind(id).bind(&expected).fetch_optional(&mut *tx).await.map_err(db)?;
    if got.as_ref() != Some(&expected) || get_in(&mut tx, id, false).await? != expected {
        return Err(Failure("outreach_write_ack_failed"));
    }
    let result = read_in(&mut tx, &expected, settings).await?;
    tx.commit()
        .await
        .map_err(|_| Failure("outreach_commit_outcome_unknown"))?;
    Ok(result)
}
pub async fn dispatch(
    c: &mut PgConnection,
    route: Route,
    method: &str,
    query: Option<&str>,
    body: &[u8],
    settings: &crate::contacts::Settings,
) -> Result<Value> {
    if !route.accepts(method) {
        return Err(Failure("outreach_method_not_allowed"));
    }
    let read = method == "GET";
    let page = if matches!(route, Route::List) {
        contract::page(query)?
    } else {
        if query.is_some_and(|s| !s.is_empty()) {
            return Err(Failure("invalid_outreach_query"));
        }
        (20, 0)
    };
    let changes = if read {
        if !body.is_empty() {
            return Err(Failure("invalid_outreach_query"));
        }
        None
    } else {
        Some(contract::normalize(
            if method == "PATCH" {
                contract::Kind::Edit
            } else {
                contract::Kind::Decision
            },
            serde_json::from_slice(body).map_err(|_| Failure("invalid_outreach_contract"))?,
        )?)
    };
    let mut tx = if read {
        let mut tx = c.begin().await.map_err(db)?;
        sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            .execute(&mut *tx)
            .await
            .map_err(db)?;
        tx
    } else {
        begin(c).await?
    };
    let result = match route {
        Route::List => {
            let total: i64 = sqlx::query_scalar("SELECT count(*) FROM outreach_logs")
                .fetch_one(&mut *tx)
                .await
                .map_err(db)?;
            let ids: Vec<Uuid> = sqlx::query_scalar(
                "SELECT id FROM outreach_logs ORDER BY created_at DESC,id LIMIT $1 OFFSET $2",
            )
            .bind(page.0)
            .bind(page.1)
            .fetch_all(&mut *tx)
            .await
            .map_err(db)?;
            let mut output = Vec::new();
            let mut bytes = 0;
            for id in ids {
                let row = get_in(&mut tx, id, false).await?;
                let value = read_in(&mut tx, &row, settings).await?;
                bytes += value.to_string().len();
                if bytes > 8 * 1024 * 1024 {
                    return Err(Failure("outreach_draft_projection_limit"));
                }
                output.push(value);
            }
            json!({"drafts":output,"total":total,"limit":page.0,"offset":page.1})
        }
        Route::Detail(id) | Route::Eligibility(id) | Route::Approve(id) | Route::Reject(id) => {
            let before = get_in(&mut tx, id, !read).await?;
            if read {
                if matches!(route, Route::Eligibility(_)) {
                    eligibility_in(&mut tx, &before, settings, false).await?
                } else {
                    read_in(&mut tx, &before, settings).await?
                }
            } else {
                editable(&mut tx, &before).await?;
                let changes = changes.as_ref().ok_or_else(invalid)?;
                if changes["expected_revision"] != before["draft_revision"] {
                    return Err(Failure("outreach_draft_revision_conflict"));
                }
                let revision = before["draft_revision"]
                    .as_i64()
                    .and_then(|n| n.checked_add(1))
                    .filter(|n| *n <= i32::MAX as i64)
                    .ok_or_else(invalid)?;
                let mut after = before.clone();
                after["draft_revision"] = json!(revision);
                after["updated_at"] = now_in(&mut tx).await?;
                if method == "PATCH" {
                    for key in ["subject", "body", "recipient_email"] {
                        if let Some(value) = changes.get(key) {
                            after[key] = value.clone();
                        }
                    }
                    after["approval_status"] = json!("pending_approval");
                    after["validation_status"] = json!("requires_review");
                    after["last_edited_at"] = after["updated_at"].clone();
                } else if matches!(route, Route::Approve(_)) {
                    if eligibility_in(&mut tx, &before, settings, true).await?["eligible_for_approval"]
                        != true
                    {
                        return Err(Failure("outreach_draft_not_eligible"));
                    }
                    after["approval_status"] = json!("approved");
                    after["validation_status"] = json!("reviewed");
                    after["approved_at"] = after["updated_at"].clone();
                    after["approved_revision"] = json!(revision);
                    after["approval_hash"] = json!(approval_digest(&after));
                } else {
                    after["approval_status"] = json!("rejected");
                }
                if after["approval_status"] != "approved" {
                    for key in ["approved_at", "approved_revision", "approval_hash"] {
                        after[key] = Value::Null;
                    }
                }
                let after = write_in(&mut tx, &before, &after).await?;
                read_in(&mut tx, &after, settings).await?
            }
        }
    };
    tx.commit()
        .await
        .map_err(|_| Failure("outreach_commit_outcome_unknown"))?;
    Ok(result)
}
