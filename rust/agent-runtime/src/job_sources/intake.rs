//! Local-only ingestion of an original retained owner run. No transport, queue or application calls.
mod company;
mod jobs;
mod observations;
mod sql;
use super::{
    access,
    plan::{Snapshot, Source},
    runs, scope,
};
use crate::{Failure, Result, source_registry::Settings};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sql::{Table, ack, db, id, invalid};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use std::collections::BTreeMap;
use uuid::Uuid;
fn key(id: Uuid) -> String {
    format!("public_ingest:{}", id.simple())
}
async fn saved_in(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Option<Value>> {
    let value:Option<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(value::text)<=262144 THEN value ELSE NULL END FROM owner_preferences WHERE key=$1").bind(key(id)).fetch_optional(&mut **tx).await.map_err(db)?;
    match value {
        Some(Some(v)) => Ok(Some(v)),
        Some(None) => Err(Failure("public_job_intake_saved_limit")),
        None => Ok(None),
    }
}
fn retained(value: &Value, state: &runs::State, id: Uuid) -> Result<Value> {
    if state.child["state"] != "finding_retained"
        || value["schema"] != 1
        || value["request_id"] != json!(id)
        || value["scope_hash"] != state.journal["scope_hash"]
        || value["finding_hash"] != state.child["finding_hash"]
        || value["configuration_hash"] != state.child["configuration_hash"]
        || value["receipt_hash"] != crate::python_json::digest(&value["receipt"])
    {
        return Err(Failure("public_job_intake_receipt_conflict"));
    }
    let v = &value["receipt"];
    if v["request_id"] != json!(id)
        || v["local_intake_complete"] != true
        || v["provider_calls"] != 0
        || v["application_dispatch"] != false
        || v["live_verified"] != false
        || v["rankings_complete"] != false
        || v["source"] != state.row["source"]
        || v["observed_at"] != state.child["finding"]["observed_at"]
        || v["provider_status"] != state.child["finding"]["status"]
        || v["provider_batch_complete"] != state.child["finding"]["batch_complete"]
        || v["evidence_basis"] != "atomic_local_sql_from_original_retained_finding"
        || v["job_ids"]
            .as_array()
            .is_none_or(|a| a.len() > 100 || a.iter().any(|v| sql::id(v).is_err()))
        || !v["counts"].is_object()
        || !v["exclusions"].is_array()
    {
        return Err(invalid());
    }
    let observed = access::time(&v["observed_at"])?;
    let ingested = access::time(&v["ingested_at"])?;
    if ingested < observed || ingested - observed > chrono::Duration::hours(24) {
        return Err(invalid());
    }
    let mut counts = json!({});
    for field in [
        "discovered",
        "inserted",
        "updated",
        "duplicate",
        "rejected",
        "skipped",
        "failed",
    ] {
        let n = v["counts"][field]
            .as_u64()
            .filter(|n| *n <= if field == "rejected" { 200 } else { 100 })
            .ok_or_else(invalid)?;
        counts[field] = json!(n);
    }
    let n = |field: &str| counts[field].as_u64().expect("validated count");
    if n("failed") != 0
        || n("duplicate") != n("updated")
        || n("discovered") != n("inserted") + n("updated") + n("skipped")
        || v["job_ids"].as_array().ok_or_else(invalid)?.len() as u64 != n("inserted") + n("updated")
        || n("discovered")
            != state.child["finding"]["jobs"]
                .as_array()
                .ok_or_else(invalid)?
                .len() as u64
        || v["exclusions"].as_array().ok_or_else(invalid)?.len() as u64 != n("skipped")
        || v["counts"]["rejected"] != state.child["finding"]["rejected_count"]
    {
        return Err(invalid());
    }
    let mut indices = std::collections::BTreeSet::new();
    let mut exclusions = Vec::new();
    for exclusion in v["exclusions"].as_array().ok_or_else(invalid)? {
        let index = exclusion["index"]
            .as_u64()
            .filter(|i| *i < n("discovered") && indices.insert(*i))
            .ok_or_else(invalid)?;
        let code = exclusion["code"]
            .as_str()
            .filter(|s| {
                matches!(
                    *s,
                    "published_before_query_window"
                        | "explicit_keyword_mismatch"
                        | "explicit_location_mismatch"
                        | "explicit_employment_mismatch"
                        | "explicit_remote_mismatch"
                )
            })
            .ok_or_else(invalid)?;
        exclusions.push(json!({"index":index,"code":code}));
    }
    let unique = v["job_ids"]
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .map(|v| v.as_str().ok_or_else(invalid))
        .collect::<Result<std::collections::BTreeSet<_>>>()?;
    let companies = v["company_ids_by_job"]
        .as_object()
        .filter(|m| m.len() == unique.len() && m.len() <= 100)
        .ok_or_else(invalid)?;
    let mut selected = json!({});
    for (job, company) in companies {
        if !unique.contains(job.as_str()) || sql::id(&json!(job)).is_err() {
            return Err(invalid());
        }
        selected[job] = json!(sql::id(company)?);
    }
    // Closed projection prevents extra private journal fields from reaching owner responses.
    Ok(
        json!({"request_id":id,"counts":counts,"job_ids":v["job_ids"],"company_ids_by_job":selected,"exclusions":exclusions,"observed_at":v["observed_at"],"ingested_at":v["ingested_at"],"source":v["source"],"provider_status":v["provider_status"],"provider_batch_complete":v["provider_batch_complete"],"local_intake_complete":true,"rankings_complete":false,"provider_calls":0,"application_dispatch":false,"live_verified":false,"evidence_basis":"atomic_local_sql_from_original_retained_finding"}),
    )
}
struct Batch {
    receipt: Value,
    companies: BTreeMap<Uuid, Value>,
    jobs: BTreeMap<Uuid, Value>,
    observations: BTreeMap<Uuid, Value>,
}
impl Batch {
    async fn verify(&self, tx: &mut Transaction<'_, Postgres>) -> Result<()> {
        for (table, rows) in [
            (Table::Company, &self.companies),
            (Table::Job, &self.jobs),
            (Table::Observation, &self.observations),
        ] {
            for (id, expected) in rows {
                if sql::row(tx, table, *id).await? != *expected {
                    return Err(ack());
                }
            }
        }
        Ok(())
    }
}
async fn batch_in(
    tx: &mut Transaction<'_, Postgres>,
    state: &runs::State,
    id: Uuid,
    now: DateTime<Utc>,
) -> Result<Batch> {
    // Consume the same closed, normalized projection used by saved reads, never raw journal extras.
    let finding = access::visible(&state.child, id, now)?;
    let mut batch = Batch {
        receipt: json!({}),
        companies: BTreeMap::new(),
        jobs: BTreeMap::new(),
        observations: BTreeMap::new(),
    };
    let rows = finding["jobs"]
        .as_array()
        .filter(|a| a.len() <= 100)
        .ok_or_else(invalid)?;
    let mut inventory = jobs::Inventory::new();
    let mut inserted = 0;
    let mut updated = 0;
    let mut ids = Vec::new();
    let mut excluded = Vec::new();
    for (index, item) in rows.iter().enumerate() {
        if let Some(code) = super::filters::exclusion(
            item,
            &state.journal["scope"]["explicit_query"],
            &state.journal["scope"]["effective_query"],
            now,
        )? {
            excluded.push(json!({"index":index,"code":code}));
            continue;
        }
        let (mut prior, observation, mut reason) = jobs::resolve(tx, &mut inventory, item).await?;
        let prior_company = prior
            .as_ref()
            .filter(|v| !v["company_id"].is_null())
            .map(|v| id_from(&v["company_id"]))
            .transpose()?;
        let company = company::resolve(tx, item, prior_company).await?;
        let company_id = id_from(&company["id"])?;
        if prior.is_none() {
            prior = jobs::content(tx, item, company_id).await?;
            if prior.is_some() {
                reason = "content_identity";
            }
        }
        let (job, created) = jobs::save(tx, item, company_id, prior).await?;
        let job_id = id_from(&job["id"])?;
        let observation = observations::save(tx, item, job_id, observation, reason).await?;
        inventory.remember(item["canonical_url"].as_str().ok_or_else(invalid)?, job_id);
        batch.companies.insert(company_id, company);
        batch.jobs.insert(job_id, job);
        batch
            .observations
            .insert(id_from(&observation["id"])?, observation);
        if created {
            inserted += 1
        } else {
            updated += 1
        };
        ids.push(job_id);
    }
    let rejected = finding["rejected_count"].as_u64().ok_or_else(invalid)?;
    let companies = batch
        .jobs
        .iter()
        .map(|(id, job)| (id.to_string(), job["company_id"].clone()))
        .collect::<serde_json::Map<_, _>>();
    batch.receipt = json!({"request_id":id,"counts":{"discovered":rows.len(),"inserted":inserted,"updated":updated,"duplicate":updated,"rejected":rejected,"skipped":excluded.len(),"failed":0},"job_ids":ids,"company_ids_by_job":companies,"exclusions":excluded,"observed_at":finding["observed_at"],"ingested_at":sql::stamp(tx).await?,"source":state.row["source"],"provider_status":finding["status"],"provider_batch_complete":finding["batch_complete"],"local_intake_complete":true,"rankings_complete":false,"provider_calls":0,"application_dispatch":false,"live_verified":false,"evidence_basis":"atomic_local_sql_from_original_retained_finding"});
    batch.verify(tx).await?;
    Ok(batch)
}
fn id_from(v: &Value) -> Result<Uuid> {
    id(v)
}
pub(super) async fn context_in(
    tx: &mut Transaction<'_, Postgres>,
    state: &runs::State,
    settings: &Settings,
    now: DateTime<Utc>,
) -> Result<()> {
    access::visible(&state.child, id(&state.child["request_id"])?, now)?;
    if state.child["state"] != "finding_retained" {
        return Err(Failure("public_job_intake_finding_missing"));
    }
    let at = access::time(&state.child["finding"]["observed_at"])?;
    if at > now || now - at > chrono::Duration::hours(24) {
        return Err(Failure("public_job_intake_finding_expired"));
    }
    let source = Source::parse(state.row["source"].as_str().ok_or_else(invalid)?)?;
    let snapshot = Snapshot::build(
        settings,
        source,
        state.journal["scope"]["effective_query"].clone(),
    )?;
    if state.child["configuration_hash"] != snapshot.context() {
        return Err(Failure("public_job_intake_configuration_changed"));
    }
    let profile = crate::startup_catalog::detail::profile_in(
        tx,
        state.journal["scope"]["use_profile"] == true,
    )
    .await?;
    if scope::profile_pin(profile.as_ref())? != state.journal["scope"]["profile_pin"] {
        return Err(Failure("public_job_intake_profile_changed"));
    }
    Ok(())
}
pub(super) struct Completion {
    pub(super) receipt: Value,
    journal: Value,
    batch: Option<Batch>,
    pace: Option<Option<Value>>,
}
impl Completion {
    pub(super) async fn verify_in(
        &self,
        tx: &mut Transaction<'_, Postgres>,
        state: &runs::State,
        settings: &Settings,
        request: Uuid,
        now: DateTime<Utc>,
    ) -> Result<()> {
        if saved_in(tx, request).await?.as_ref() != Some(&self.journal)
            || retained(&self.journal, state, request)? != self.receipt
        {
            return Err(ack());
        }
        if let Some(batch) = &self.batch {
            batch.verify(tx).await?;
            context_in(tx, state, settings, now).await?;
        }
        if let Some(pace) = &self.pace {
            let after: Option<Value> = sqlx::query_scalar(
                "SELECT to_jsonb(next_allowed_at) FROM provider_access_windows WHERE provider=$1",
            )
            .bind(state.row["source"].as_str())
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?;
            if &after != pace {
                return Err(ack());
            }
        }
        Ok(())
    }
}
pub(super) async fn complete_in(
    tx: &mut Transaction<'_, Postgres>,
    state: &runs::State,
    settings: &Settings,
    request: Uuid,
    now: DateTime<Utc>,
) -> Result<Completion> {
    access::visible(&state.child, request, now)?;
    if let Some(saved) = saved_in(tx, request).await? {
        return Ok(Completion {
            receipt: retained(&saved, state, request)?,
            journal: saved,
            batch: None,
            pace: None,
        });
    }
    context_in(tx, state, settings, now).await?;
    sqlx::query("SELECT pg_advisory_xact_lock(240204)")
        .execute(&mut **tx)
        .await
        .map_err(db)?;
    let pace: Option<Value> = sqlx::query_scalar(
        "SELECT to_jsonb(next_allowed_at) FROM provider_access_windows WHERE provider=$1",
    )
    .bind(state.row["source"].as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(db)?;
    let batch = batch_in(tx, state, request, now).await?;
    let expected = json!({"schema":1,"request_id":request,"scope_hash":state.journal["scope_hash"],"finding_hash":state.child["finding_hash"],"configuration_hash":state.child["configuration_hash"],"receipt":batch.receipt,"receipt_hash":crate::python_json::digest(&batch.receipt)});
    let saved: Option<Value> = sqlx::query_scalar(
        "INSERT INTO owner_preferences(key,value) VALUES($1,$2) RETURNING value",
    )
    .bind(key(request))
    .bind(&expected)
    .fetch_optional(&mut **tx)
    .await
    .map_err(db)?;
    if saved.as_ref() != Some(&expected) {
        return Err(ack());
    }
    let completion = Completion {
        receipt: retained(&expected, state, request)?,
        journal: expected,
        batch: Some(batch),
        pace: Some(pace),
    };
    completion
        .verify_in(tx, state, settings, request, now)
        .await?;
    Ok(completion)
}
pub(super) async fn read_in(
    tx: &mut Transaction<'_, Postgres>,
    state: &runs::State,
    request: Uuid,
) -> Result<Option<Value>> {
    saved_in(tx, request)
        .await?
        .map(|v| retained(&v, state, request))
        .transpose()
}
/// Retry completes only local SQL over the original finding; completed replay returns its immutable receipt.
/// Parent rankings/finalization are separate and cannot be inferred from this receipt.
pub async fn ingest_retained(
    c: &mut PgConnection,
    settings: &Settings,
    request: Uuid,
) -> Result<Value> {
    let mut tx = access::transaction(c).await?;
    let state = runs::state_in(&mut tx, request).await?;
    let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let completion = complete_in(&mut tx, &state, settings, request, now).await?;
    let after = runs::state_in(&mut tx, request).await?;
    if after.row != state.row || after.journal != state.journal || after.child != state.child {
        return Err(ack());
    }
    let end: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    completion
        .verify_in(&mut tx, &state, settings, request, end)
        .await?;
    tx.commit()
        .await
        .map_err(|_| Failure("public_job_intake_commit_outcome_unknown"))?;
    Ok(completion.receipt)
}
/// Read only the retained local receipt. Current configuration/profile is not substituted for original scope.
pub async fn read(c: &mut PgConnection, request: Uuid) -> Result<Option<Value>> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let state = runs::state_in(&mut tx, request).await?;
    let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    access::visible(&state.child, request, now)?;
    let out = saved_in(&mut tx, request)
        .await?
        .map(|v| retained(&v, &state, request))
        .transpose()?;
    tx.commit().await.map_err(db)?;
    Ok(out)
}
