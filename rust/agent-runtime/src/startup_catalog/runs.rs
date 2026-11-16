//! Original manual discovery-run admission. Retained state cannot reconstruct an invocation.
use super::{identity, search, shortlist};
use crate::{
    Failure, Result,
    research_contract::{self, Kind},
};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;
fn db(_: sqlx::Error) -> Failure {
    Failure("startup_run_database_error")
}
fn invalid() -> Failure {
    Failure("invalid_startup_run_record")
}
fn ack() -> Failure {
    Failure("startup_run_write_ack_failed")
}
fn conflict() -> Failure {
    Failure("startup_run_invocation_conflict")
}
fn time(v: &Value) -> Result<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(v.as_str().ok_or_else(invalid)?)
        .map(|t| t.to_utc())
        .map_err(|_| invalid())
}
fn journal_key(id: Uuid) -> String {
    format!("startup_run:{}", id.simple())
}
pub fn request_hash(input: &Value) -> Result<String> {
    let mut value = input.clone();
    let fields = value.as_object_mut().ok_or_else(invalid)?;
    fields.remove("idempotency_key");
    let source = fields
        .get("source")
        .and_then(Value::as_str)
        .ok_or_else(invalid)?;
    fields.insert("source".into(), json!(format!("startup_{source}")));
    Ok(identity::content_hash(&value))
}
pub struct Invocation {
    id: Uuid,
    journal: Value,
    input: Value,
    original: Value,
}
pub enum Admission {
    Retained(Value),
    Original(Box<Invocation>),
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
async fn clock(tx: &mut Transaction<'_, Postgres>) -> Result<Value> {
    sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut **tx)
        .await
        .map_err(db)
}
async fn row_in(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Value> {
    let value:Option<Value>=sqlx::query_scalar("SELECT CASE WHEN octet_length(to_jsonb(r)::text)<=4194304 THEN to_jsonb(r) ELSE NULL END FROM discovery_runs r WHERE id=$1 FOR UPDATE").bind(id).fetch_optional(&mut **tx).await.map_err(db)?.ok_or(Failure("startup_catalog_run_not_found"))?;
    value.ok_or_else(invalid)
}
pub fn output(row: &Value, now: DateTime<Utc>, timeout: f64) -> Result<Value> {
    if !timeout.is_finite() || !(1.0..=3600.0).contains(&timeout) || !row.is_object() {
        return Err(invalid());
    }
    let id = row["id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    let source = row["source"]
        .as_str()
        .filter(|s| s.starts_with("startup_") && s.len() <= 100)
        .ok_or_else(invalid)?;
    let started = time(&row["started_at"])?;
    if !row["finished_at"].is_null() {
        time(&row["finished_at"])?;
    }
    let recorded = row["status"]
        .as_str()
        .filter(|s| s.len() <= 50)
        .ok_or_else(invalid)?;
    let expired = recorded == "running"
        && now.signed_duration_since(started).num_milliseconds() as f64
            > (timeout + 120.0) * 1000.0;
    let mut counts = json!({});
    for key in [
        "companies_observed",
        "companies_matching",
        "inserted",
        "duplicates",
        "rejected",
    ] {
        if let Some(value) = row["counts"].get(key) {
            if !value.as_u64().is_some_and(|n| n <= 10000000) {
                return Err(invalid());
            }
            counts[key] = value.clone();
        }
    }
    let rankings = row["rankings"]
        .as_array()
        .filter(|a| a.len() <= 100)
        .ok_or_else(invalid)?
        .iter()
        .map(shortlist::public_snapshot)
        .collect::<Result<Vec<_>>>()?;
    let errors = if expired {
        vec![json!("startup_run_recovery_required")]
    } else {
        row["errors"]
            .as_array()
            .filter(|a| a.len() <= 100)
            .ok_or_else(invalid)?
            .iter()
            .map(|v| {
                if v.as_str().is_some_and(|s| {
                    s.len() <= 100
                        && s.bytes()
                            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'_')
                }) {
                    v.clone()
                } else {
                    json!("startup_saved_error_requires_review")
                }
            })
            .collect::<Vec<_>>()
    };
    let mut query = json!({});
    let summary = &row["query_summary"];
    if let Some(mode) = summary["mode"]
        .as_str()
        .filter(|s| matches!(*s, "company_first" | "job_led"))
    {
        query["mode"] = json!(mode);
    }
    for key in ["company_ids", "job_ids"] {
        if let Some(values) = summary[key].as_array() {
            if values.len() > 10000 {
                return Err(invalid());
            }
            query[key] = json!(
                values
                    .iter()
                    .map(|v| v
                        .as_str()
                        .and_then(|s| s.parse::<Uuid>().ok())
                        .ok_or_else(invalid))
                    .collect::<Result<Vec<_>>>()?
            );
        }
    }
    if !summary["filters"].is_null() {
        query["filters"] =
            super::contract::normalize(super::contract::Kind::Filters, summary["filters"].clone())
                .map_err(|_| invalid())?;
    }
    if !summary["child_run_id"].is_null() {
        query["child_run_id"] = json!(
            summary["child_run_id"]
                .as_str()
                .and_then(|s| s.parse::<Uuid>().ok())
                .ok_or_else(invalid)?
        );
    }
    Ok(
        json!({"id":id,"source":source,"status":if expired{"recovery_required"}else{recorded},"recorded_status":recorded,"counts":counts,"errors":errors,"started_at":row["started_at"],"finished_at":row["finished_at"],"provider_run_id":null,"usage":{},"rankings":rankings,"job_ids":query.get("job_ids").cloned().unwrap_or(json!([])),"query":query,"provider_calls_performed_by_read":0,"evidence_basis":"retained_run_not_new_execution"}),
    )
}
pub async fn admit_manual(c: &mut PgConnection, input: Value, timeout: f64) -> Result<Admission> {
    let mut tx = begin(c).await?;
    let at = clock(&mut tx).await?;
    let now = time(&at)?;
    let input = research_contract::normalize(Kind::StartupRun, input, now)?;
    if input["source"] != "manual" || input["mode"] != "company_first" {
        return Err(Failure("startup_manual_run_required"));
    }
    let hash = request_hash(&input)?;
    let key = input["idempotency_key"]
        .as_str()
        .ok_or(Failure("startup_run_idempotency_key_required"))?;
    if let Some(id) =
        sqlx::query_scalar::<_, Uuid>("SELECT id FROM discovery_runs WHERE idempotency_key=$1")
            .bind(key)
            .fetch_optional(&mut *tx)
            .await
            .map_err(db)?
    {
        let row = row_in(&mut tx, id).await?;
        if row["request_hash"] != hash || row["source"] != "startup_manual" {
            return Err(Failure("startup_run_idempotency_conflict"));
        }
        let result = output(&row, now, timeout)?;
        tx.commit()
            .await
            .map_err(|_| Failure("startup_run_commit_outcome_unknown"))?;
        return Ok(Admission::Retained(result));
    }
    let id = Uuid::new_v4();
    let expected = json!({"id":id,"source":"startup_manual","request_hash":hash,"query_summary":input["query"],"status":"running","rankings":[],"counts":{},"errors":[],"started_at":at,"finished_at":null,"provider_run_id":null,"usage":{},"idempotency_key":key});
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO discovery_runs AS r(id,source,request_hash,query_summary,status,rankings,counts,errors,started_at,finished_at,provider_run_id,usage,idempotency_key) SELECT x.id,x.source,x.request_hash,x.query_summary,x.status,x.rankings,x.counts,x.errors,x.started_at,x.finished_at,x.provider_run_id,x.usage,x.idempotency_key FROM jsonb_populate_record(NULL::discovery_runs,$1) x ON CONFLICT DO NOTHING RETURNING to_jsonb(r)").bind(&expected).fetch_optional(&mut *tx).await.map_err(db)?;
    if saved.as_ref() != Some(&expected) || row_in(&mut tx, id).await? != expected {
        return Err(ack());
    }
    let journal = json!({"schema":1,"id":id,"token":Uuid::new_v4(),"state":"admitted","request_hash":hash,"input":input,"started_at":at,"expires_at":(now+chrono::Duration::seconds(180)).to_rfc3339(),"provider_admissions":0});
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES($1,$2,clock_timestamp(),clock_timestamp()) ON CONFLICT DO NOTHING RETURNING value").bind(journal_key(id)).bind(&journal).fetch_optional(&mut *tx).await.map_err(db)?;
    let actual: Option<Value> =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
            .bind(journal_key(id))
            .fetch_optional(&mut *tx)
            .await
            .map_err(db)?;
    if saved.as_ref() != Some(&journal) || actual.as_ref() != Some(&journal) {
        return Err(ack());
    }
    tx.commit()
        .await
        .map_err(|_| Failure("startup_run_commit_outcome_unknown"))?;
    Ok(Admission::Original(Box::new(Invocation {
        id,
        journal,
        input,
        original: expected,
    })))
}
pub async fn complete_manual(
    c: &mut PgConnection,
    invocation: Invocation,
    settings: &crate::contacts::Settings,
    timeout: f64,
) -> Result<Value> {
    let mut tx = begin(c).await?;
    let journal:Option<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(value::text)<=2097152 THEN value ELSE NULL END FROM owner_preferences WHERE key=$1 FOR UPDATE").bind(journal_key(invocation.id)).fetch_optional(&mut *tx).await.map_err(db)?;
    if journal.flatten().as_ref() != Some(&invocation.journal)
        || row_in(&mut tx, invocation.id).await? != invocation.original
    {
        return Err(conflict());
    }
    let at = clock(&mut tx).await?;
    let now = time(&at)?;
    if now > time(&invocation.journal["expires_at"])? {
        return Err(Failure("startup_run_invocation_expired"));
    }
    sqlx::query("SELECT pg_advisory_xact_lock(240204)")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let mut ids = Vec::new();
    for item in invocation.input["companies"]
        .as_array()
        .ok_or_else(invalid)?
    {
        let result = identity::ingest_in(&mut tx, item.clone(), Some(invocation.id)).await?;
        ids.push(
            result["company_id"]
                .as_str()
                .and_then(|s| s.parse::<Uuid>().ok())
                .ok_or_else(invalid)?,
        );
    }
    ids.sort();
    ids.dedup();
    let mut filters = invocation.input["filters"].clone();
    filters["page"] = json!(1);
    filters["limit"] = json!(100);
    let search = search::search_in(&mut tx, &filters, false, settings, now, Some(&ids)).await?;
    let finished = clock(&mut tx).await?;
    if time(&finished)? > time(&invocation.journal["expires_at"])? {
        return Err(Failure("startup_run_invocation_expired"));
    }
    let mut expected = invocation.original;
    expected["query_summary"] = json!({"mode":"company_first","filters":invocation.input["filters"],"child_run_id":null,"company_ids":ids});
    expected["status"] = json!(if ids.is_empty() {
        "manual_input_required"
    } else {
        "success"
    });
    expected["counts"] =
        json!({"companies_observed":ids.len(),"companies_matching":search["total"]});
    expected["rankings"] = search["startups"].clone();
    expected["finished_at"] = finished.clone();
    let saved:Option<Value>=sqlx::query_scalar("UPDATE discovery_runs r SET query_summary=$1::jsonb->'query_summary',status=$1::jsonb->>'status',counts=$1::jsonb->'counts',rankings=$1::jsonb->'rankings',finished_at=($1::jsonb->>'finished_at')::timestamptz WHERE id=$2 AND status='running' RETURNING to_jsonb(r)").bind(&expected).bind(invocation.id).fetch_optional(&mut *tx).await.map_err(db)?;
    if saved.as_ref() != Some(&expected) || row_in(&mut tx, invocation.id).await? != expected {
        return Err(ack());
    }
    let mut closed = invocation.journal;
    closed["state"] = json!("completed");
    closed["finished_at"] = finished;
    closed["run_hash"] = json!(identity::content_hash(&expected));
    let saved:Option<Value>=sqlx::query_scalar("UPDATE owner_preferences SET value=$1,updated_at=clock_timestamp() WHERE key=$2 RETURNING value").bind(&closed).bind(journal_key(invocation.id)).fetch_optional(&mut *tx).await.map_err(db)?;
    let actual: Option<Value> =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
            .bind(journal_key(invocation.id))
            .fetch_optional(&mut *tx)
            .await
            .map_err(db)?;
    if saved.as_ref() != Some(&closed) || actual.as_ref() != Some(&closed) {
        return Err(ack());
    }
    let result = output(&expected, time(&expected["finished_at"])?, timeout)?;
    tx.commit()
        .await
        .map_err(|_| Failure("startup_run_commit_outcome_unknown"))?;
    Ok(result)
}
pub async fn run_manual(
    c: &mut PgConnection,
    input: Value,
    settings: &crate::contacts::Settings,
    timeout: f64,
) -> Result<Value> {
    match admit_manual(c, input, timeout).await? {
        Admission::Retained(value) => Ok(value),
        Admission::Original(invocation) => complete_manual(c, *invocation, settings, timeout).await,
    }
}
pub async fn read(c: &mut PgConnection, id: Uuid, timeout: f64) -> Result<Value> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let row:Option<Value>=sqlx::query_scalar("SELECT CASE WHEN octet_length(to_jsonb(r)::text)<=4194304 THEN to_jsonb(r) ELSE NULL END FROM discovery_runs r WHERE id=$1 AND starts_with(source,'startup_')").bind(id).fetch_optional(&mut *tx).await.map_err(db)?.ok_or(Failure("startup_catalog_run_not_found"))?;
    let at = clock(&mut tx).await?;
    let result = output(&row.ok_or_else(invalid)?, time(&at)?, timeout)?;
    tx.commit().await.map_err(db)?;
    Ok(result)
}
