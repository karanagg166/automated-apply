//! Original startup parent + typed public/paid job child. Reads never reconstruct a provider invocation.
mod child;
use super::{runs, search};
use crate::{
    Failure, Result,
    job_sources::{
        self,
        plan::{Snapshot, Source},
    },
    research_contract::{self, Kind},
    source_registry::Settings,
};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;
fn invalid() -> Failure {
    Failure("invalid_startup_job_led_run")
}
fn db(_: sqlx::Error) -> Failure {
    Failure("startup_run_database_error")
}
fn ack() -> Failure {
    Failure("startup_run_write_ack_failed")
}
fn key(id: Uuid) -> String {
    format!("startup_job:{}", id.simple())
}
pub fn child_id(parent: Uuid) -> Uuid {
    Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!("automated-apply:startup-child:{parent}").as_bytes(),
    )
}
pub fn request_id(input: &Value) -> Result<Uuid> {
    let key = input["idempotency_key"]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or(Failure("startup_run_idempotency_key_required"))?;
    Ok(Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!("automated-apply:startup-discovery:{key}").as_bytes(),
    ))
}
fn input(raw: Value, now: DateTime<Utc>) -> Result<Value> {
    let v = research_contract::normalize(Kind::StartupRun, raw, now)?;
    if v["mode"] != "job_led"
        || (!child::paid(&v["source"])
            && Source::parse(v["source"].as_str().ok_or_else(invalid)?).is_err())
    {
        return Err(Failure("startup_provider_orchestration_not_implemented"));
    }
    Ok(v)
}
pub fn child_input(input: &Value, parent: Uuid) -> Result<Value> {
    job_sources::scope::normalize(
        json!({"source":input["source"],"query":input["query"],"idempotency_key":format!("startup_child_{parent}"),"allow_paid":input["allow_paid"],"use_profile":input["filters"]["use_profile"],"manual_jobs":[]}),
    )
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
async fn now(tx: &mut Transaction<'_, Postgres>) -> Result<DateTime<Utc>> {
    sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut **tx)
        .await
        .map_err(db)
}
async fn row(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Option<Value>> {
    let v:Option<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(to_jsonb(r)::text)<=4194304 THEN to_jsonb(r) ELSE NULL END FROM discovery_runs r WHERE id=$1").bind(id).fetch_optional(&mut **tx).await.map_err(db)?;
    match v {
        Some(Some(v)) => Ok(Some(v)),
        Some(None) => Err(Failure("startup_run_saved_limit")),
        None => Ok(None),
    }
}
async fn journal(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Option<Value>> {
    let v:Option<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(value::text)<=4194304 THEN value ELSE NULL END FROM owner_preferences WHERE key=$1").bind(key(id)).fetch_optional(&mut **tx).await.map_err(db)?;
    match v {
        Some(Some(v)) => Ok(Some(v)),
        Some(None) => Err(Failure("startup_run_saved_limit")),
        None => Ok(None),
    }
}
struct State {
    row: Value,
    journal: Value,
    child: Value,
}
async fn load_state(
    tx: &mut Transaction<'_, Postgres>,
    id: Uuid,
    at: DateTime<Utc>,
) -> Result<State> {
    let row = row(tx, id)
        .await?
        .ok_or(Failure("startup_catalog_run_not_found"))?;
    let journal = journal(tx, id)
        .await?
        .ok_or(Failure("startup_job_led_original_scope_missing"))?;
    let input = input(
        journal["input"].clone(),
        job_sources::access::time(&row["started_at"])?,
    )?;
    let child = child_id(id);
    let scope = child::scope(tx, &input["source"], child).await?;
    if journal["schema"] != 1
        || journal["id"] != json!(id)
        || journal["child_id"] != json!(child)
        || journal["row"] != row
        || !matches!(journal["state"].as_str(), Some("admitted" | "completed"))
        || journal["input"] != input
        || row["request_hash"] != runs::request_hash(&input)?
        || row["source"] != format!("startup_{}", input["source"].as_str().ok_or_else(invalid)?)
        || journal["profile_pin"] != scope["profile_pin"]
        || journal["child_scope_hash"] != crate::python_json::digest(&scope)
        || scope["request_hash"] != job_sources::scope::request_hash(&child_input(&input, id)?)
    {
        return Err(invalid());
    }
    let deadline = journal["timeout_seconds"]
        .as_f64()
        .filter(|n| n.is_finite() && (5.0..=180.0).contains(n))
        .ok_or_else(invalid)?;
    let child = child::read_in(tx, &input["source"], child, at).await?;
    if journal["state"] == "admitted"
        && (row["status"] != "running" || !row["finished_at"].is_null())
        || journal["state"] == "completed"
            && (child["local_intake_complete"] != true
                || child["rankings_complete"] != true
                || row["status"] != child["status"]
                || journal["child_result_hash"] != crate::python_json::digest(&child)
                || row["finished_at"].is_null())
    {
        return Err(invalid());
    }
    runs::output(&row, at, deadline)?;
    Ok(State {
        row,
        journal,
        child,
    })
}
fn output(state: &State, at: DateTime<Utc>) -> Result<Value> {
    let mut out = runs::output(
        &state.row,
        at,
        state.journal["timeout_seconds"]
            .as_f64()
            .ok_or_else(invalid)?,
    )?;
    out["child_run"] = json!({"id":state.child["id"],"status":state.child["status"],"counts":state.child["counts"],"local_intake_complete":state.child["local_intake_complete"],"rankings_complete":state.child["rankings_complete"]});
    if child::paid(&state.journal["input"]["source"]) {
        for field in ["provider_run_id", "reservation", "billing_final"] {
            out["child_run"][field] = state.child[field].clone();
        }
        out["child_run"]["usage"] = state.child["usage"].clone();
    }
    out["usage"] = json!({"stage":if state.journal["state"]=="completed"{"completed"}else if state.child["local_intake_complete"]==true && state.child["rankings_complete"]==true{"company_results_pending"}else{"child_pending"},"finding_retained":state.child["usage"]["finding_retained"]==true,"replay_authorized":false});
    out["local_intake_complete"] = json!(state.journal["state"] == "completed");
    out["application_dispatch"] = json!(false);
    out["live_verified"] = json!(false);
    Ok(out)
}
pub struct Original {
    id: Uuid,
    child: child::Original,
}
pub enum Admission {
    Retained(Value),
    Original(Box<Original>),
}
pub async fn admit(
    c: &mut PgConnection,
    settings: &Settings,
    raw: Value,
    id: Uuid,
    timeout: f64,
) -> Result<Admission> {
    admit_with_paid(c, settings, None, raw, id, timeout).await
}
pub async fn admit_with_paid(
    c: &mut PgConnection,
    settings: &Settings,
    paid: Option<&crate::apify_jobs::settings::Settings>,
    raw: Value,
    id: Uuid,
    timeout: f64,
) -> Result<Admission> {
    if !timeout.is_finite() || !(5.0..=180.0).contains(&timeout) {
        return Err(invalid());
    }
    let input = input(raw, Utc::now())?;
    let hash = runs::request_hash(&input)?;
    let mut tx = begin(c).await?;
    let at = now(&mut tx).await?;
    if let Some(row) = row(&mut tx, id).await? {
        if row["request_hash"] != hash {
            return Err(Failure("startup_run_idempotency_conflict"));
        }
        let out = output(&load_state(&mut tx, id, at).await?, at)?;
        tx.commit()
            .await
            .map_err(|_| Failure("startup_run_commit_outcome_unknown"))?;
        return Ok(Admission::Retained(out));
    }
    let compat = input["idempotency_key"]
        .as_str()
        .map(String::from)
        .unwrap_or_else(|| format!("startup_public_{}", id.simple()));
    let exists: bool =
        sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM discovery_runs WHERE idempotency_key=$1)")
            .bind(&compat)
            .fetch_one(&mut *tx)
            .await
            .map_err(db)?;
    if exists {
        return Err(Failure("startup_run_idempotency_conflict"));
    }
    let child = child::admit(
        &mut tx,
        settings,
        paid,
        child_input(&input, id)?,
        child_id(id),
        timeout,
    )
    .await?;
    let scope = child::scope(&mut tx, &input["source"], child_id(id)).await?;
    let context = if child::paid(&input["source"]) {
        scope["configuration_hash"]
            .as_str()
            .ok_or_else(invalid)?
            .to_owned()
    } else {
        Snapshot::build(
            settings,
            Source::parse(input["source"].as_str().ok_or_else(invalid)?)?,
            scope["effective_query"].clone(),
        )?
        .context()
        .to_owned()
    };
    let stamp: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let expected = json!({"id":id,"source":format!("startup_{}",input["source"].as_str().ok_or_else(invalid)?),"request_hash":hash,"query_summary":{"mode":"job_led","filters":input["filters"],"child_run_id":child_id(id),"company_ids":[],"job_ids":[]},"status":"running","rankings":[],"counts":{},"errors":[],"started_at":stamp,"finished_at":null,"provider_run_id":null,"usage":{"stage":"original_admission"},"idempotency_key":compat});
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO discovery_runs AS r(id,source,request_hash,query_summary,status,rankings,counts,errors,started_at,finished_at,provider_run_id,usage,idempotency_key) SELECT x.id,x.source,x.request_hash,x.query_summary,x.status,x.rankings,x.counts,x.errors,x.started_at,x.finished_at,x.provider_run_id,x.usage,x.idempotency_key FROM jsonb_populate_record(NULL::discovery_runs,$1) x RETURNING to_jsonb(r)").bind(&expected).fetch_optional(&mut *tx).await.map_err(db)?;
    if saved.as_ref() != Some(&expected) {
        return Err(ack());
    }
    let value = json!({"schema":1,"id":id,"child_id":child_id(id),"state":"admitted","input":input,"row":expected,"profile_pin":scope["profile_pin"],"child_scope_hash":crate::python_json::digest(&scope),"configuration_hash":context,"timeout_seconds":timeout});
    let saved: Option<Value> = sqlx::query_scalar(
        "INSERT INTO owner_preferences(key,value) VALUES($1,$2) RETURNING value",
    )
    .bind(key(id))
    .bind(&value)
    .fetch_optional(&mut *tx)
    .await
    .map_err(db)?;
    if saved.as_ref() != Some(&value)
        || journal(&mut tx, id).await?.as_ref() != Some(&value)
        || row(&mut tx, id).await?.as_ref() != Some(&expected)
    {
        return Err(ack());
    }
    child::assert_original(&mut tx, paid, &child).await?;
    let end = now(&mut tx).await?;
    load_state(&mut tx, id, end).await?;
    tx.commit()
        .await
        .map_err(|_| Failure("startup_run_commit_outcome_unknown"))?;
    Ok(Admission::Original(Box::new(Original { id, child })))
}
pub async fn read(c: &mut PgConnection, id: Uuid) -> Result<Value> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let at = now(&mut tx).await?;
    let out = output(&load_state(&mut tx, id, at).await?, at)?;
    tx.commit().await.map_err(db)?;
    Ok(out)
}
pub(crate) async fn read_in(
    tx: &mut Transaction<'_, Postgres>,
    id: Uuid,
    at: DateTime<Utc>,
) -> Result<Option<Value>> {
    if journal(tx, id).await?.is_none() {
        return Ok(None);
    }
    Ok(Some(output(&load_state(tx, id, at).await?, at)?))
}
async fn current_scope(
    tx: &mut Transaction<'_, Postgres>,
    state: &State,
    settings: &Settings,
    paid: Option<&crate::apify_jobs::settings::Settings>,
) -> Result<()> {
    let profile =
        super::detail::profile_in(tx, state.journal["input"]["filters"]["use_profile"] == true)
            .await?;
    if job_sources::scope::profile_pin(profile.as_ref())? != state.journal["profile_pin"] {
        return Err(Failure("startup_job_led_profile_changed"));
    }
    let parent = state.row["id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    if child::paid(&state.journal["input"]["source"]) {
        return crate::apify_jobs::runs::current_context_in(
            tx,
            paid.ok_or(Failure("apify_reviewed_execution_route_required"))?,
            child_id(parent),
        )
        .await;
    }
    let scope = child::scope(tx, &state.journal["input"]["source"], child_id(parent)).await?;
    let source = Source::parse(
        state.journal["input"]["source"]
            .as_str()
            .ok_or_else(invalid)?,
    )?;
    if Snapshot::build(settings, source, scope["effective_query"].clone())?.context()
        != state.journal["configuration_hash"]
            .as_str()
            .ok_or_else(invalid)?
    {
        return Err(Failure("startup_job_led_configuration_changed"));
    }
    Ok(())
}
async fn companies_in(
    tx: &mut Transaction<'_, Postgres>,
    source: &Value,
    child: Uuid,
) -> Result<Vec<Uuid>> {
    let receipt = child::receipt(tx, source, child)
        .await?
        .ok_or(Failure("startup_job_led_child_intake_missing"))?;
    let expected = receipt["company_ids_by_job"]
        .as_object()
        .ok_or_else(invalid)?;
    let ids = expected
        .keys()
        .map(|s| s.parse::<Uuid>().map_err(|_| invalid()))
        .collect::<Result<Vec<_>>>()?;
    let rows: Vec<(Uuid, Option<Uuid>)> =
        sqlx::query_as("SELECT id,company_id FROM jobs WHERE id=ANY($1) ORDER BY id LIMIT 101")
            .bind(&ids)
            .fetch_all(&mut **tx)
            .await
            .map_err(db)?;
    if rows.len() != ids.len()
        || rows
            .iter()
            .any(|(job, company)| expected.get(&job.to_string()) != Some(&json!(company)))
    {
        return Err(Failure("startup_job_led_company_attribution_changed"));
    }
    let mut companies = rows
        .into_iter()
        .map(|(_, company)| company.ok_or_else(invalid))
        .collect::<Result<Vec<_>>>()?;
    companies.sort();
    companies.dedup();
    Ok(companies)
}
pub async fn finish(
    c: &mut PgConnection,
    id: Uuid,
    settings: &Settings,
    contacts: &crate::contacts::Settings,
) -> Result<Value> {
    finish_with_paid(c, id, settings, None, contacts).await
}
pub async fn finish_with_paid(
    c: &mut PgConnection,
    id: Uuid,
    settings: &Settings,
    paid: Option<&crate::apify_jobs::settings::Settings>,
    contacts: &crate::contacts::Settings,
) -> Result<Value> {
    let mut tx = begin(c).await?;
    let at = now(&mut tx).await?;
    let state = load_state(&mut tx, id, at).await?;
    if state.journal["state"] == "completed" {
        let out = output(&state, at)?;
        tx.commit()
            .await
            .map_err(|_| Failure("startup_run_commit_outcome_unknown"))?;
        return Ok(out);
    }
    if state.child["local_intake_complete"] != true || state.child["rankings_complete"] != true {
        return Err(Failure("startup_job_led_child_incomplete"));
    }
    current_scope(&mut tx, &state, settings, paid).await?;
    let paid_ledger = if child::paid(&state.journal["input"]["source"]) {
        Some(crate::apify_jobs::runs::ledger_in(&mut tx, child_id(id)).await?)
    } else {
        None
    };
    let companies = companies_in(&mut tx, &state.journal["input"]["source"], child_id(id)).await?;
    let mut filters = state.journal["input"]["filters"].clone();
    filters["page"] = json!(1);
    filters["limit"] = json!(100);
    let selected =
        search::search_in(&mut tx, &filters, false, contacts, at, Some(&companies)).await?;
    let stamp: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp())")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let mut expected = state.row.clone();
    expected["query_summary"]["company_ids"] = json!(companies);
    expected["query_summary"]["job_ids"] = state.child["job_ids"].clone();
    expected["status"] = state.child["status"].clone();
    expected["errors"] = state.child["errors"].clone();
    expected["counts"] =
        json!({"companies_observed":companies.len(),"companies_matching":selected["total"]});
    expected["rankings"] = selected["startups"].clone();
    expected["finished_at"] = stamp;
    expected["usage"] = json!({"stage":"completed"});
    if expected.to_string().len() > 4194304 {
        return Err(Failure("startup_run_saved_limit"));
    }
    let saved:Option<Value>=sqlx::query_scalar("UPDATE discovery_runs AS r SET query_summary=$2->'query_summary',status=$2->>'status',errors=$2->'errors',counts=$2->'counts',rankings=$2->'rankings',finished_at=($2->>'finished_at')::timestamptz,usage=$2->'usage' WHERE id=$1 RETURNING to_jsonb(r)").bind(id).bind(&expected).fetch_optional(&mut *tx).await.map_err(db)?;
    if saved.as_ref() != Some(&expected) {
        return Err(ack());
    }
    let mut closed = state.journal.clone();
    closed["state"] = json!("completed");
    closed["row"] = expected.clone();
    closed["child_result_hash"] = json!(crate::python_json::digest(&state.child));
    let saved:Option<Value>=sqlx::query_scalar("UPDATE owner_preferences SET value=$2,updated_at=clock_timestamp() WHERE key=$1 AND value=$3 RETURNING value").bind(key(id)).bind(&closed).bind(&state.journal).fetch_optional(&mut *tx).await.map_err(db)?;
    if saved.as_ref() != Some(&closed)
        || journal(&mut tx, id).await?.as_ref() != Some(&closed)
        || row(&mut tx, id).await?.as_ref() != Some(&expected)
    {
        return Err(ack());
    }
    current_scope(&mut tx, &state, settings, paid).await?;
    if companies_in(&mut tx, &state.journal["input"]["source"], child_id(id)).await? != companies
        || search::search_in(&mut tx, &filters, false, contacts, at, Some(&companies)).await?
            != selected
    {
        return Err(ack());
    }
    let end = now(&mut tx).await?;
    let after = load_state(&mut tx, id, end).await?;
    if let Some(ledger) = paid_ledger {
        if crate::apify_jobs::runs::ledger_in(&mut tx, child_id(id)).await? != ledger {
            return Err(ack());
        }
    }
    if after.child != state.child || after.journal != closed || after.row != expected {
        return Err(ack());
    }
    let out = output(&after, end)?;
    tx.commit()
        .await
        .map_err(|_| Failure("startup_run_commit_outcome_unknown"))?;
    Ok(out)
}
pub struct Service<'a> {
    pub sources: &'a Settings,
    pub client: &'a job_sources::transport::Client,
    pub contacts: &'a crate::contacts::Settings,
    pub timeout_seconds: f64,
}
/// Recover only original retained child/local results. No provider client or new admission exists here.
pub async fn complete(
    c: &mut PgConnection,
    id: Uuid,
    sources: &Settings,
    paid: Option<&crate::apify_jobs::settings::Settings>,
    contacts: &crate::contacts::Settings,
) -> Result<Value> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let at = now(&mut tx).await?;
    let state = load_state(&mut tx, id, at).await?;
    let selected = output(&state, at)?;
    let source = state.journal["input"]["source"].clone();
    tx.commit().await.map_err(db)?;
    if selected["local_intake_complete"] == true || state.child["usage"]["finding_retained"] != true
    {
        return Ok(selected);
    }
    child::finish(c, sources, paid, &source, child_id(id)).await?;
    finish_with_paid(c, id, sources, paid, contacts).await
}
impl Service<'_> {
    pub async fn run(&self, c: &mut PgConnection, raw: Value, id: Uuid) -> Result<Value> {
        self.run_with_paid(c, raw, id, None, None).await
    }
    pub async fn run_with_paid(
        &self,
        c: &mut PgConnection,
        raw: Value,
        id: Uuid,
        paid: Option<&crate::apify_jobs::settings::Settings>,
        paid_client: Option<&crate::apify_jobs::transport::Client>,
    ) -> Result<Value> {
        let source = input(raw.clone(), Utc::now())?["source"].clone();
        match admit_with_paid(c, self.sources, paid, raw, id, self.timeout_seconds).await? {
            Admission::Original(original) => {
                let Original { id, child } = *original;
                child::acquire(c, paid, paid_client, self.client, child).await?;
                child::finish(c, self.sources, paid, &source, child_id(id)).await?;
                finish_with_paid(c, id, self.sources, paid, self.contacts).await
            }
            Admission::Retained(value) => {
                if value["local_intake_complete"] == true {
                    return Ok(value);
                }
                let child = child::read(c, &source, child_id(id)).await?;
                if child["usage"]["finding_retained"] != true {
                    return Ok(value);
                }
                child::finish(c, self.sources, paid, &source, child_id(id)).await?;
                finish_with_paid(c, id, self.sources, paid, self.contacts).await
            }
        }
    }
}
