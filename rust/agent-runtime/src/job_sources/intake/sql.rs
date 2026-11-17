//! Fixed-schema row writes, typed expectations and independent full-row acknowledgements.
use crate::{Failure, Result};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;
pub(super) fn invalid() -> Failure {
    Failure("invalid_public_job_intake")
}
pub(super) fn db(_: sqlx::Error) -> Failure {
    Failure("public_job_intake_database_error")
}
pub(super) fn ack() -> Failure {
    Failure("public_job_intake_write_ack_failed")
}
#[derive(Clone, Copy)]
pub(super) enum Table {
    Job,
    Company,
    Observation,
}
pub(super) async fn row(
    tx: &mut Transaction<'_, Postgres>,
    table: Table,
    id: Uuid,
) -> Result<Value> {
    let query = match table {
        Table::Job => {
            "SELECT CASE WHEN octet_length(to_jsonb(r)::text)<=1048576 THEN to_jsonb(r) ELSE NULL END FROM jobs r WHERE id=$1 FOR UPDATE"
        }
        Table::Company => {
            "SELECT CASE WHEN octet_length(to_jsonb(r)::text)<=1048576 THEN to_jsonb(r) ELSE NULL END FROM companies r WHERE id=$1 FOR UPDATE"
        }
        Table::Observation => {
            "SELECT CASE WHEN octet_length(to_jsonb(r)::text)<=1048576 THEN to_jsonb(r) ELSE NULL END FROM job_source_observations r WHERE id=$1 FOR UPDATE"
        }
    };
    let v: Option<Option<Value>> = sqlx::query_scalar(query)
        .bind(id)
        .fetch_optional(&mut **tx)
        .await
        .map_err(db)?;
    v.flatten().ok_or_else(ack)
}
pub(super) fn id(v: &Value) -> Result<Uuid> {
    v.as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .filter(|v| !v.is_nil())
        .ok_or_else(invalid)
}
pub(super) async fn stamp(tx: &mut Transaction<'_, Postgres>) -> Result<Value> {
    sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut **tx)
        .await
        .map_err(db)
}
// Coerce numeric scale, arrays and timestamps using the actual table composite type.
pub(super) async fn typed(
    tx: &mut Transaction<'_, Postgres>,
    table: Table,
    patch: &Value,
) -> Result<Value> {
    let query = match table {
        Table::Job => "SELECT to_jsonb(jsonb_populate_record(NULL::jobs,$1))",
        Table::Company => "SELECT to_jsonb(jsonb_populate_record(NULL::companies,$1))",
        Table::Observation => {
            "SELECT to_jsonb(jsonb_populate_record(NULL::job_source_observations,$1))"
        }
    };
    sqlx::query_scalar(query)
        .bind(patch)
        .fetch_one(&mut **tx)
        .await
        .map_err(db)
}
pub(super) async fn patch(
    tx: &mut Transaction<'_, Postgres>,
    table: Table,
    before: &Value,
    patch: Value,
) -> Result<Value> {
    let coerced = typed(tx, table, &patch).await?;
    let mut expected = before.clone();
    for k in patch.as_object().ok_or_else(invalid)?.keys() {
        expected[k] = coerced.get(k).cloned().ok_or_else(invalid)?;
    }
    Ok(expected)
}
pub(super) async fn acknowledged(
    tx: &mut Transaction<'_, Postgres>,
    table: Table,
    mut expected: Value,
    saved: Option<Value>,
    updated: bool,
) -> Result<Value> {
    let saved = saved.ok_or_else(ack)?;
    if updated && saved["updated_at"] != expected["updated_at"] {
        let bounds: Value = sqlx::query_scalar(
            "SELECT jsonb_build_array(transaction_timestamp(),clock_timestamp())",
        )
        .fetch_one(&mut **tx)
        .await
        .map_err(db)?;
        let actual = super::super::access::time(&saved["updated_at"])?;
        if actual < super::super::access::time(&bounds[0])?
            || actual > super::super::access::time(&bounds[1])?
        {
            return Err(ack());
        }
        expected["updated_at"] = saved["updated_at"].clone();
    }
    if saved != expected || row(tx, table, id(&expected["id"])?).await? != expected {
        return Err(ack());
    }
    Ok(expected)
}
pub(super) fn empty(v: &Value) -> bool {
    v.is_null() || v.as_str() == Some("")
}
pub(super) fn provenance(item: &Value, reason: &str) -> Value {
    let mut v = item["data_provenance"].clone();
    v["deduplication"] = json!(reason);
    v["quality_flags"] = item["quality_flags"].clone();
    v
}
