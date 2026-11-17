//! Owner-entered listings and a terminal local discovery receipt in one transaction.
use super::{access, contract, intake, ranking, runs, scope};
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;

pub(crate) const SOURCES: &[&str] = &[
    "internshala",
    "hiringcafe",
    "simplify",
    "workday",
    "company_careers",
    "manual",
];
pub(crate) fn supports(source: &str) -> bool {
    SOURCES.contains(&source)
}
pub(super) fn key(id: Uuid) -> String {
    format!("manual_run:{}", id.simple())
}
fn db(_: sqlx::Error) -> Failure {
    Failure("discovery_run_database_error")
}
fn invalid() -> Failure {
    Failure("invalid_discovery_manual_request")
}
fn ack() -> Failure {
    Failure("discovery_run_write_ack_failed")
}

pub(super) fn validate(input: &Value) -> Result<&str> {
    let source = input["source"]
        .as_str()
        .filter(|source| supports(source))
        .ok_or_else(invalid)?;
    let count = input["manual_jobs"].as_array().ok_or_else(invalid)?.len();
    let limit = input["query"]["limit"].as_u64().ok_or_else(invalid)?;
    if input["allow_paid"] != false || count as u64 > limit {
        return Err(invalid());
    }
    Ok(source)
}

fn records(input: &Value, now: DateTime<Utc>) -> Result<(Vec<Value>, usize)> {
    let source = validate(input)?;
    let jobs = input["manual_jobs"].as_array().ok_or_else(invalid)?;
    let mut rows = Vec::with_capacity(jobs.len());
    for raw in jobs {
        if !raw.is_object() || source != "manual" && raw["source_name"] != source {
            continue;
        }
        if matches!(source, "internshala" | "hiringcafe")
            && !raw["original_url"]
                .as_str()
                .is_some_and(|url| crate::packet_platform::portal_listing(source, url.trim()))
        {
            continue;
        }
        let mut value = raw.clone();
        value["source_verification_status"] = json!("requires_review");
        value["is_confirmed_current"] = json!(false);
        value["data_provenance"] = json!({"import_mode":"manual"});
        value["company_intelligence"] = json!({});
        value["company_domain"] = Value::Null;
        // A manual observation cannot claim an existing provider's source ID or freshness.
        value["source_job_id"] = Value::Null;
        for field in ["first_observed_date", "last_observed_date", "retrieved_at"] {
            value[field] = json!(now.to_rfc3339());
        }
        if let Ok(value) = contract::normalize(value, now) {
            rows.push(value);
        }
    }
    let rejected = jobs.len() - rows.len();
    Ok((rows, rejected))
}

pub(super) fn preview_counts(input: &Value, now: DateTime<Utc>) -> Result<Value> {
    let (rows, rejected) = records(input, now)?;
    Ok(json!({"valid_records":rows.len(),"rejected_records":rejected}))
}

async fn marker(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Option<Value>> {
    let retained: Option<Option<Value>> = sqlx::query_scalar("SELECT CASE WHEN octet_length(value::text)<=4096 THEN value END FROM owner_preferences WHERE key=$1")
        .bind(key(id)).fetch_optional(&mut **tx).await.map_err(db)?;
    retained
        .map(|value| value.ok_or(Failure("invalid_discovery_manual_record")))
        .transpose()
}

fn output(row: &Value, marker: &Value, id: Uuid) -> Result<Value> {
    let invalid = Failure("invalid_discovery_manual_record");
    if row["id"] != json!(id)
        || marker["schema"] != 1
        || marker["request_id"] != json!(id)
        || marker["request_hash"] != row["request_hash"]
        || marker["row_hash"] != crate::python_json::digest(row)
        || row["source"].as_str().is_none_or(|s| !supports(s))
        || !row["provider_run_id"].is_null()
        || !matches!(
            row["status"].as_str(),
            Some("success" | "partial" | "no_results" | "manual_input_required")
        )
        || row["usage"]["provider_http_attempts"] != 0
        || row["usage"]["stage"] != "completed"
    {
        return Err(invalid);
    }
    let summary = &row["query_summary"];
    let ids = summary["job_ids"]
        .as_array()
        .filter(|ids| ids.len() <= 100)
        .ok_or(invalid)?;
    for id in ids {
        if id
            .as_str()
            .and_then(|s| s.parse::<Uuid>().ok())
            .is_none_or(|id| id.is_nil())
        {
            return Err(invalid);
        }
    }
    let n = |field: &str| {
        row["counts"][field]
            .as_u64()
            .filter(|n| *n <= 100)
            .ok_or(invalid)
    };
    let saved_count = n("inserted")? + n("updated")?;
    if saved_count != ids.len() as u64
        || n("discovered")? != saved_count + n("skipped")?
        || n("duplicate")? != n("updated")?
        || n("failed")? != 0
        || n("discovered")? + n("rejected")? > 100
        || access::time(&row["finished_at"])? < access::time(&row["started_at"])?
    {
        return Err(invalid);
    }
    let rankings = ranking::project(
        &row["rankings"],
        &json!({"job_ids":ids}),
        &summary["profile_version"],
    )?;
    Ok(
        json!({"id":id,"source":row["source"],"status":row["status"],"counts":row["counts"],"errors":row["errors"],
        "started_at":row["started_at"],"finished_at":row["finished_at"],"provider_run_id":null,
        "rankings":rankings,"job_ids":ids,"profile_version":summary["profile_version"],"usage":row["usage"],
        "original_scope_available":true,"local_intake_complete":true,"rankings_complete":true,
        "application_dispatch":false,"live_verified":false,"evidence_basis":"atomic_owner_manual_import"}),
    )
}

pub(crate) async fn read(connection: &mut PgConnection, id: Uuid) -> Result<Value> {
    let mut tx = connection.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let row = runs::row_in(&mut tx, id)
        .await?
        .ok_or(Failure("discovery_run_not_found"))?;
    let marker = marker(&mut tx, id)
        .await?
        .ok_or(Failure("discovery_run_original_scope_missing"))?;
    let result = output(&row, &marker, id)?;
    tx.commit().await.map_err(db)?;
    Ok(result)
}

pub(crate) async fn run(connection: &mut PgConnection, input: Value, id: Uuid) -> Result<Value> {
    let request = scope::normalize(input)?;
    let source = validate(&request)?;
    if id.is_nil() {
        return Err(invalid());
    }
    let hash = scope::request_hash(&request)?;
    let compat = request["idempotency_key"]
        .as_str()
        .map(str::to_owned)
        .unwrap_or_else(|| format!("native_manual_{}", id.simple()));
    let mut tx = access::transaction(connection).await?;
    if let Some(row) = runs::row_in(&mut tx, id).await? {
        if row["request_hash"] != hash {
            return Err(Failure("discovery_run_request_conflict"));
        }
        let proof = marker(&mut tx, id)
            .await?
            .ok_or(Failure("discovery_run_original_scope_missing"))?;
        let result = output(&row, &proof, id)?;
        tx.rollback().await.map_err(db)?;
        return Ok(result);
    }
    let exists: bool =
        sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM discovery_runs WHERE idempotency_key=$1)")
            .bind(&compat)
            .fetch_one(&mut *tx)
            .await
            .map_err(db)?;
    if exists {
        return Err(Failure("discovery_run_compatibility_key_conflict"));
    }
    sqlx::query("SELECT pg_advisory_xact_lock(240204)")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let started: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let now = access::time(&started)?;
    let use_profile = request["use_profile"] == true;
    let profile = crate::startup_catalog::detail::profile_in(&mut tx, use_profile).await?;
    let pin = scope::profile_pin(profile.as_ref())?;
    let effective = scope::effective_query(&request["query"], profile.as_ref())?;
    let (rows, rejected) = records(&request, now)?;
    let batch =
        intake::manual_in(&mut tx, &rows, &request["query"], &effective, now, rejected).await?;
    let ranked = ranking::rank_in(&mut tx, &batch.receipt, profile.as_ref(), now).await?;
    let ids = &batch.receipt["job_ids"];
    let status = if rejected > 0 {
        "partial"
    } else if rows.is_empty() {
        "manual_input_required"
    } else if ids.as_array().is_some_and(Vec::is_empty) {
        "no_results"
    } else {
        "success"
    };
    let finished: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let summary = json!({"explicit_query":request["query"],"effective_query":effective,"profile_version":pin["version"],"job_ids":ids});
    let row = json!({"id":id,"source":source,"request_hash":hash,"query_summary":summary,"status":status,
        "rankings":ranked.entries,"counts":batch.receipt["counts"],
        "errors":if rejected>0 {json!(["Some listing records had invalid evidence."])} else {json!([])},
        "started_at":started,"finished_at":finished,"provider_run_id":null,"idempotency_key":compat,
        "usage":{"stage":"completed","provider_http_attempts":0,"suppressed_prior_history":ranked.suppressed,"replay_authorized":false}});
    let saved: Option<Value> = sqlx::query_scalar("INSERT INTO discovery_runs AS r SELECT (jsonb_populate_record(NULL::discovery_runs,$1)).* RETURNING to_jsonb(r)")
        .bind(&row).fetch_optional(&mut *tx).await.map_err(db)?;
    if saved.as_ref() != Some(&row) {
        return Err(ack());
    }
    let proof = json!({"schema":1,"request_id":id,"request_hash":hash,"row_hash":crate::python_json::digest(&row)});
    let written: Option<Value> = sqlx::query_scalar(
        "INSERT INTO owner_preferences(key,value) VALUES($1,$2) RETURNING value",
    )
    .bind(key(id))
    .bind(&proof)
    .fetch_optional(&mut *tx)
    .await
    .map_err(db)?;
    if written.as_ref() != Some(&proof)
        || marker(&mut tx, id).await?.as_ref() != Some(&proof)
        || runs::row_in(&mut tx, id).await?.as_ref() != Some(&row)
    {
        return Err(ack());
    }
    batch.verify(&mut tx).await?;
    ranked.verify_in(&mut tx).await?;
    let current = crate::startup_catalog::detail::profile_in(&mut tx, use_profile).await?;
    if scope::profile_pin(current.as_ref())? != pin {
        return Err(ack());
    }
    let result = output(&row, &proof, id)?;
    tx.commit()
        .await
        .map_err(|_| Failure("discovery_run_commit_outcome_unknown"))?;
    Ok(result)
}
