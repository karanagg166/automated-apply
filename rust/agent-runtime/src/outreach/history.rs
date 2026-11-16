//! Saved history only. An interrupted projection never edits or replays a historical intent.
use super::*;
pub const PATH: &str = "/api/v1/outreach/history";
#[derive(Clone, Copy)]
pub enum Route {
    History,
    Attempt(Uuid),
}
pub fn route(path: &str) -> Option<Route> {
    if path == PATH {
        return Some(Route::History);
    }
    let id = path.strip_prefix("/api/v1/outreach/send-attempts/")?;
    Some(Route::Attempt(id.parse().ok()?))
}
const ATTEMPT: &str = "jsonb_build_object('id',a.id,'draft_id',a.draft_id,'connected_account_id',a.connected_account_id,'draft_revision',a.draft_revision,'approval_hash',a.approval_hash,'actor_id',a.actor_id,'recipient_email',a.recipient_email,'sender_email',a.sender_email,'subject',a.subject,'body',a.body,'content_digest',a.content_digest,'evidence_digest',a.evidence_digest,'rfc_message_id',a.rfc_message_id,'status',a.status,'gmail_message_id',a.gmail_message_id,'gmail_thread_id',a.gmail_thread_id,'created_at',a.created_at,'attempted_at',a.attempted_at,'accepted_at',a.accepted_at,'failure_category',a.failure_category,'reconciliation_required',a.reconciliation_required,'reconciled_at',a.reconciled_at,'reconciled_by',a.reconciled_by,'reconciliation_note',a.reconciliation_note)";
const LOCAL: &str = "jsonb_build_object('id',d.id,'draft_id',d.id,'draft_revision',d.draft_revision,'subject',d.subject,'body',d.body,'recipient_email',d.recipient_email,'connected_account_id',d.connected_account_id,'sender_email',NULL,'approval_status',d.approval_status,'status',CASE WHEN d.sent_at IS NULL THEN 'not_attempted' ELSE 'legacy_sent_unverified' END,'created_at',d.created_at,'accepted_at',NULL,'recorded_sent_at',d.sent_at,'gmail_message_id',d.gmail_message_id,'gmail_thread_id',d.gmail_thread_id,'reconciliation_required',d.sent_at IS NOT NULL)";
fn stamp(value: &Value) -> Result<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(value.as_str().ok_or_else(invalid)?)
        .map(|v| v.with_timezone(&Utc))
        .map_err(|_| invalid())
}
pub fn qualify(
    mut value: Value,
    attempt: bool,
    now: DateTime<Utc>,
    settings: &Settings,
) -> Result<Value> {
    if !value.is_object() || value.to_string().len() > 262144 {
        return Err(invalid());
    }
    for key in ["id", "draft_id"] {
        value[key]
            .as_str()
            .and_then(|s| s.parse::<Uuid>().ok())
            .ok_or_else(invalid)?;
    }
    if !value["draft_revision"]
        .as_i64()
        .is_some_and(|n| (1..=i32::MAX as i64).contains(&n))
        || !value["reconciliation_required"].is_boolean()
    {
        return Err(invalid());
    }
    for (key, max) in [
        ("subject", 16384),
        ("body", 131072),
        ("recipient_email", 254),
        ("sender_email", 254),
        ("status", 50),
        ("failure_category", 64),
        ("reconciliation_note", 8000),
    ] {
        if !value[key].is_null() && !value[key].as_str().is_some_and(|s| s.len() <= max) {
            return Err(invalid());
        }
    }
    stamp(&value["created_at"])?;
    for key in [
        "attempted_at",
        "accepted_at",
        "recorded_sent_at",
        "reconciled_at",
    ] {
        if !value[key].is_null() {
            stamp(&value[key])?;
        }
    }
    let status = value["status"]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or_else(invalid)?
        .to_owned();
    value["recorded_status"] = json!(status);
    value["status_basis"] = json!("saved_record");
    if attempt && matches!(status.as_str(), "prepared" | "attempting") {
        let started = stamp(if value["attempted_at"].is_null() {
            &value["created_at"]
        } else {
            &value["attempted_at"]
        })?;
        if now.signed_duration_since(started).num_milliseconds() > settings.interrupted_after_millis
        {
            value["status"] = json!(if status == "attempting" {
                "outcome_unknown"
            } else {
                "failed_before_send"
            });
            value["failure_category"] = json!("interrupted_attempt_requires_review");
            value["reconciliation_required"] = json!(status == "attempting");
            value["status_basis"] = json!("interrupted_projection_original_record_preserved");
        }
    }
    value["sending_enabled"] = json!(false);
    value["delivery_verified"] = json!(false);
    value["acceptance_basis"] = json!(if attempt && !value["accepted_at"].is_null() {
        "saved_record_not_current_provider_verification"
    } else {
        "no_acceptance_evidence"
    });
    Ok(value)
}
pub async fn dispatch(
    c: &mut PgConnection,
    route: Route,
    method: &str,
    query: Option<&str>,
    body: &[u8],
    settings: &Settings,
) -> Result<Value> {
    if method != "GET" {
        return Err(Failure("outreach_method_not_allowed"));
    }
    if !body.is_empty() {
        return Err(Failure("invalid_outreach_query"));
    }
    let (limit, offset) = match route {
        Route::History => contract::page(query)?,
        Route::Attempt(_) => {
            if query.is_some_and(|q| !q.is_empty()) {
                return Err(Failure("invalid_outreach_query"));
            }
            (1, 0)
        }
    };
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let now: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let now = stamp(&now)?;
    let result = match route {
        Route::Attempt(id) => {
            let value:Option<Value>=sqlx::query_scalar(&format!("SELECT CASE WHEN coalesce(octet_length(a.subject),0)+coalesce(octet_length(a.body),0)+coalesce(octet_length(a.reconciliation_note),0)>262144 THEN NULL ELSE {ATTEMPT} END FROM outreach_send_attempts a WHERE a.id=$1")).bind(id).fetch_optional(&mut *tx).await.map_err(db)?;
            qualify(
                value.ok_or(Failure("outreach_send_attempt_not_found"))?,
                true,
                now,
                settings,
            )?
        }
        Route::History => {
            let timeline = "SELECT id,created_at,'attempt'::text AS kind FROM outreach_send_attempts UNION ALL SELECT d.id,d.created_at,'local'::text FROM outreach_logs d WHERE NOT EXISTS(SELECT 1 FROM outreach_send_attempts a WHERE a.draft_id=d.id)";
            let total: i64 = sqlx::query_scalar(&format!("SELECT count(*) FROM ({timeline}) t"))
                .fetch_one(&mut *tx)
                .await
                .map_err(db)?;
            let rows:Vec<(String,Value)>=sqlx::query_as(&format!("WITH page AS (SELECT * FROM ({timeline}) t ORDER BY created_at DESC,id,kind LIMIT $1 OFFSET $2) SELECT p.kind,CASE WHEN p.kind='attempt' THEN CASE WHEN coalesce(octet_length(a.subject),0)+coalesce(octet_length(a.body),0)+coalesce(octet_length(a.reconciliation_note),0)>262144 THEN NULL ELSE {ATTEMPT} END ELSE CASE WHEN coalesce(octet_length(d.subject),0)+coalesce(octet_length(d.body),0)>262144 THEN NULL ELSE {LOCAL} END END FROM page p LEFT JOIN outreach_send_attempts a ON p.kind='attempt' AND a.id=p.id LEFT JOIN outreach_logs d ON p.kind='local' AND d.id=p.id ORDER BY p.created_at DESC,p.id,p.kind")).bind(limit).bind(offset).fetch_all(&mut *tx).await.map_err(db)?;
            let mut bytes = 0;
            let mut messages = Vec::new();
            for (kind, value) in rows {
                bytes += value.to_string().len();
                if bytes > 8 * 1024 * 1024 {
                    return Err(Failure("outreach_history_projection_limit"));
                }
                messages.push(qualify(value, kind == "attempt", now, settings)?);
            }
            json!({"messages":messages,"limit":limit,"offset":offset,"total":total,"sending_enabled":false,"delivery_verified":false,"history_basis":"saved_local_records"})
        }
    };
    tx.commit()
        .await
        .map_err(|_| Failure("outreach_read_commit_failed"))?;
    Ok(result)
}
