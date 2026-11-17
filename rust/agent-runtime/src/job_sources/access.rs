//! Original public batch admission. Saved state never reconstructs a transport invocation.
use super::plan::{Snapshot, Source};
use crate::{Failure, Result, source_registry::Settings};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;
fn db(_: sqlx::Error) -> Failure {
    Failure("public_job_database_error")
}
fn invalid() -> Failure {
    Failure("invalid_public_job_batch")
}
fn ack() -> Failure {
    Failure("public_job_write_ack_failed")
}
pub(super) fn key(id: Uuid) -> String {
    format!("public_jobs:{}", id.simple())
}
pub(crate) fn time(value: &Value) -> Result<DateTime<Utc>> {
    value
        .as_str()
        .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
        .map(|v| v.to_utc())
        .ok_or_else(invalid)
}
pub(super) async fn transaction(c: &mut PgConnection) -> Result<Transaction<'_, Postgres>> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    crate::execution::lock_owner_in(&mut tx).await?;
    Ok(tx)
}
pub(super) async fn load_in(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Option<Value>> {
    let value:Option<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(value::text)<=9437184 THEN value ELSE NULL END FROM owner_preferences WHERE key=$1").bind(key(id)).fetch_optional(&mut **tx).await.map_err(db)?;
    match value {
        Some(Some(v)) => Ok(Some(v)),
        Some(None) => Err(Failure("public_job_saved_batch_limit")),
        None => Ok(None),
    }
}
pub struct Claim {
    pub(super) id: Uuid,
    pub(super) journal: Value,
    pub(super) grant: Option<Grant>,
}
impl Claim {
    pub fn request_id(&self) -> Uuid {
        self.id
    }
}
/// No Clone, Serialize, Debug or public constructor. Only original admission owns this value.
pub(super) struct Grant {
    pub(super) id: Uuid,
    pub(super) invocation: Uuid,
    pub(super) snapshot: Snapshot,
    pub(super) expires: DateTime<Utc>,
}
pub enum Admission {
    Retained(Value),
    Original(Box<Claim>),
}
fn request_hash(source: Source, query: &Value) -> String {
    crate::python_json::digest(&json!({"source":source.name(),"query":query}))
}
pub fn visible(journal: &Value, id: Uuid, now: DateTime<Utc>) -> Result<Value> {
    if journal["schema"] != 1
        || journal["request_id"] != json!(id)
        || journal["batch_admissions"] != 1
        || !matches!(
            journal["state"].as_str(),
            Some("dispatch_admitted" | "finding_retained")
        )
    {
        return Err(invalid());
    }
    let source =
        Source::parse(journal["source"].as_str().ok_or_else(invalid)?).map_err(|_| invalid())?;
    let query = super::contract::query(journal["query"].clone()).map_err(|_| invalid())?;
    if query != journal["query"] || journal["input_hash"] != request_hash(source, &query) {
        return Err(invalid());
    }
    let started = time(&journal["started_at"])?;
    let expires = time(&journal["expires_at"])?;
    let access = time(&journal["access_window_until"])?;
    let invocation = journal["invocation_id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    if started > now
        || expires <= started
        || expires > started + chrono::Duration::seconds(75)
        || access != started + chrono::Duration::seconds(source.interval_seconds())
        || invocation.is_nil()
        || journal["configuration_hash"]
            .as_str()
            .is_none_or(|s| s.len() != 64 || !s.bytes().all(|b| b.is_ascii_hexdigit()))
    {
        return Err(invalid());
    }
    if journal["state"] == "finding_retained" {
        if journal["finding_hash"] != crate::python_json::digest(&journal["finding"]) {
            return Err(invalid());
        }
        let mut out = super::findings::project(&journal["finding"], source, &query, now)?;
        out["request_id"] = json!(id);
        out["query"] = query;
        out["recorded_state"] = json!("finding_retained");
        out["batch_admissions"] = json!(1);
        out["provider_response_retained"] = json!(
            out["provider_responses_observed"]
                .as_u64()
                .is_some_and(|n| n > 0)
        );
        out["finding_retained"] = json!(true);
        out["replay_authorized"] = json!(false);
        out["writes_to_job_queue"] = json!(0);
        out["evidence_basis"] = json!("retained_public_discovery_finding");
        return Ok(out);
    }
    Ok(
        json!({"request_id":id,"source":source.name(),"query":query,"recorded_state":"dispatch_admitted","status":if now>=expires{"outcome_unknown"}else{"pending"},"batch_admissions":1,"provider_http_calls":null,"provider_response_retained":false,"started_at":journal["started_at"],"expires_at":journal["expires_at"],"replay_authorized":false,"writes_to_job_queue":0,"application_dispatch":false,"live_verified":false,"evidence_basis":"original_batch_admission_not_provider_response"}),
    )
}
pub async fn admit(
    c: &mut PgConnection,
    settings: &Settings,
    source: Source,
    query: Value,
    id: Uuid,
) -> Result<Admission> {
    let query = super::contract::query(query)?;
    let mut tx = transaction(c).await?;
    let admission = admit_in(&mut tx, settings, source, query, id, None).await?;
    tx.commit()
        .await
        .map_err(|_| Failure("public_job_commit_outcome_unknown"))?;
    Ok(admission)
}
pub(super) async fn admit_in(
    tx: &mut Transaction<'_, Postgres>,
    settings: &Settings,
    source: Source,
    query: Value,
    id: Uuid,
    expires_cap: Option<DateTime<Utc>>,
) -> Result<Admission> {
    let query = super::contract::query(query)?;
    let hash = request_hash(source, &query);
    let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut **tx)
        .await
        .map_err(db)?;
    if let Some(saved) = load_in(tx, id).await? {
        if saved["input_hash"] != hash {
            return Err(Failure("public_job_request_conflict"));
        }
        let out = visible(&saved, id, now)?;
        return Ok(Admission::Retained(out));
    }
    let snapshot = Snapshot::build(settings, source, query.clone())?;
    let expires = (now + chrono::Duration::seconds(75))
        .min(expires_cap.unwrap_or(now + chrono::Duration::seconds(75)));
    if expires <= now {
        return Err(Failure("public_job_original_grant_expired"));
    }
    let next = now + chrono::Duration::seconds(source.interval_seconds());
    let saved:Option<DateTime<Utc>>=sqlx::query_scalar("INSERT INTO provider_access_windows(provider,next_allowed_at) VALUES($1,$2) ON CONFLICT(provider) DO UPDATE SET next_allowed_at=EXCLUDED.next_allowed_at WHERE provider_access_windows.next_allowed_at<=$3 RETURNING next_allowed_at").bind(source.name()).bind(next).bind(now).fetch_optional(&mut **tx).await.map_err(db)?;
    if saved.is_none() {
        return Err(Failure("public_job_source_rate_limited"));
    }
    if saved != Some(next) {
        return Err(ack());
    }
    let invocation = Uuid::new_v4();
    let journal = json!({"schema":1,"request_id":id,"source":source.name(),"query":query,"input_hash":hash,"configuration_hash":snapshot.context(),"invocation_id":invocation,"state":"dispatch_admitted","batch_admissions":1,"started_at":now.to_rfc3339(),"expires_at":expires.to_rfc3339(),"access_window_until":next.to_rfc3339()});
    visible(&journal, id, now)?;
    let saved: Option<Value> = sqlx::query_scalar(
        "INSERT INTO owner_preferences(key,value) VALUES($1,$2) RETURNING value",
    )
    .bind(key(id))
    .bind(&journal)
    .fetch_optional(&mut **tx)
    .await
    .map_err(db)?;
    if saved.as_ref() != Some(&journal) {
        return Err(ack());
    }
    let pace: Option<DateTime<Utc>> =
        sqlx::query_scalar("SELECT next_allowed_at FROM provider_access_windows WHERE provider=$1")
            .bind(source.name())
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?;
    if pace != Some(next) || load_in(tx, id).await?.as_ref() != Some(&journal) {
        return Err(ack());
    }
    Ok(Admission::Original(Box::new(Claim {
        id,
        journal,
        grant: Some(Grant {
            id,
            invocation,
            snapshot,
            expires,
        }),
    })))
}
pub(super) async fn assert_original_in(
    tx: &mut Transaction<'_, Postgres>,
    claim: &Claim,
) -> Result<()> {
    if claim.grant.is_none() || load_in(tx, claim.id).await?.as_ref() != Some(&claim.journal) {
        return Err(ack());
    }
    let next: Option<DateTime<Utc>> =
        sqlx::query_scalar("SELECT next_allowed_at FROM provider_access_windows WHERE provider=$1")
            .bind(claim.journal["source"].as_str().ok_or_else(invalid)?)
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?;
    if next != Some(time(&claim.journal["access_window_until"])?) {
        return Err(ack());
    }
    Ok(())
}
pub async fn read(c: &mut PgConnection, id: Uuid) -> Result<Value> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let journal = load_in(&mut tx, id)
        .await?
        .ok_or(Failure("public_job_request_not_found"))?;
    let out = visible(&journal, id, now)?;
    tx.commit().await.map_err(db)?;
    Ok(out)
}
