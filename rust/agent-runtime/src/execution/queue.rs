//! Durable claims on existing work. A lease is scheduling, never Apply authority.
use super::{
    contracts::{self, Kind},
    events, filters, history, queue_control,
    storage::*,
};
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;

pub(crate) async fn load_in(tx: &mut Transaction<'_, Postgres>, identity: Uuid) -> Result<Value> {
    let work = get(tx, &format!("apply_work:{identity}"))
        .await?
        .ok_or(Failure("queue_item_not_found"))?;
    if work["id"] != identity.to_string() {
        return Err(invalid());
    }
    Ok(work)
}
pub(crate) async fn leased_in(
    tx: &mut Transaction<'_, Postgres>,
    identity: Uuid,
    expected: i64,
    token: Uuid,
    binding: &Value,
    now: DateTime<Utc>,
) -> Result<Value> {
    let work = load_in(tx, identity).await?;
    let current = queue_control::configuration(tx).await?;
    if current["state"] != "RUNNING"
        || work["policy_revision"] != current["revision"]
        || work["revision"] != expected
        || work["lease_token"] != token.to_string()
        || &work["binding"] != binding
        || !matches!(work["status"].as_str(), Some("leased" | "executing"))
        || work["lease_until"].is_null()
        || timestamp(&work["lease_until"])? <= now
    {
        return Err(Failure("queue_lease_lost"));
    }
    Ok(work)
}
pub(crate) async fn claim_in(
    tx: &mut Transaction<'_, Postgres>,
    platform: &str,
    binding: &Value,
    operations: Option<&[&str]>,
    now: DateTime<Utc>,
) -> Result<Option<Value>> {
    let current = queue_control::configuration(tx).await?;
    let policy = &current["policy"];
    let setting = &policy["platforms"][platform];
    if current["state"] != "RUNNING" || setting["enabled"] != true {
        return Ok(None);
    }
    let execution = contracts::normalize(
        Kind::Configuration,
        get(tx, "exec_config:naukri").await?.unwrap_or(json!({})),
    )
    .map_err(|_| invalid())?;
    if execution["mode"] == "OFF" {
        return Ok(None);
    }
    // Exclude all waiting/closed history in SQL. Current policy caps pending work at500.
    let mut rows:Vec<(String,Value,DateTime<Utc>)>=sqlx::query_as("SELECT key,value,created_at FROM owner_preferences WHERE starts_with(key,'apply_work:') AND value->>'platform'=$1 AND value->>'stage' NOT IN ('SUBMITTED_RECORDED','SUBMITTED_CONFIRMED','FAILED_FINAL','SKIPPED') AND value->>'status' IN ('queued','leased','executing') ORDER BY created_at,key LIMIT 10001").bind(platform).fetch_all(&mut **tx).await.map_err(db)?;
    if rows.len() > 10000 {
        return Err(Failure("execution_active_inventory_limit"));
    }
    if rows.iter().any(|(key, value, _)| {
        value["id"]
            .as_str()
            .and_then(|s| s.parse::<Uuid>().ok())
            .is_none()
            || value["id"]
                .as_str()
                .is_none_or(|id| key != &format!("apply_work:{id}"))
    }) {
        return Err(invalid());
    }
    let mut busy = false;
    for (key, work, _) in &mut rows {
        if !matches!(work["status"].as_str(), Some("leased" | "executing")) {
            continue;
        }
        let until = timestamp(&work["lease_until"])?;
        if until > now {
            busy = true;
            continue;
        }
        let uncertain = work["status"] == "executing"
            && work["operation"]
                .as_str()
                .is_some_and(|s| filters::WRITES.contains(&s));
        if work["operation"] == "apply" && !uncertain {
            work["operation"] = json!(if work["account_sha256"]
                .as_str()
                .is_some_and(|s| !s.is_empty())
            {
                "inspect_profile"
            } else {
                "inspect_application"
            });
        }
        work["stage"] = json!(if uncertain {
            "SUBMISSION_UNKNOWN"
        } else {
            "FAILED_RETRYABLE"
        });
        work["status"] = json!(if uncertain { "unknown" } else { "queued" });
        work["reason"] = json!("lease_expired");
        work["revision"] = json!(next(work)?);
        work["lease_token"] = Value::Null;
        work["lease_until"] = Value::Null;
        put(tx, key, work).await?;
        events::queue(tx, work, "lease_expired", now).await?;
    }
    // Recover all expired writes before returning, even when another lease is still live.
    if busy {
        return Ok(None);
    }
    let years = if platform == "naukri"
        && operations.is_none_or(|ops| ops.contains(&"inspect_job"))
        && rows
            .iter()
            .any(|(_, v, _)| v["operation"] == "inspect_job" && v["status"] == "queued")
    {
        sqlx::query_scalar::<_,Option<f64>>("SELECT verified_experience_years::double precision FROM candidate_profiles WHERE singleton_key='primary'").fetch_optional(&mut **tx).await.map_err(db)?.flatten()
    } else {
        None
    };
    rows.sort_by_key(|(_, v, created)| filters::inspection_order(v, *created, years, now));
    for (key, mut work, _) in rows {
        if !super::supervised_listing::permits_work(&current, &work, now)
            || work["status"] != "queued"
            || work["stage"]
                .as_str()
                .is_some_and(|s| filters::TERMINAL.contains(&s))
        {
            continue;
        }
        if timestamp(&work["available_at"])? > now {
            continue;
        }
        if let Some(source) = work["source"].as_str().filter(|s| !s.is_empty())
            && !setting["sources"]
                .as_array()
                .ok_or_else(invalid)?
                .iter()
                .any(|s| s == source)
        {
            work["stage"] = json!("SKIPPED");
            work["status"] = json!("complete");
            work["reason"] = json!("queue_source_disabled");
            work["revision"] = json!(next(&work)?);
            work["updated_at"] = json!(stamp(now));
            put(tx, &key, &work).await?;
            events::queue(tx, &work, "source_scope_revoked", now).await?;
            continue;
        }
        let operation = work["operation"].as_str().ok_or_else(invalid)?;
        if operations.is_some_and(|ops| !ops.contains(&operation)) {
            continue;
        }
        if filters::WRITES.contains(&operation)
            && (setting["owner_submission_authorized"] != true || setting["mode"] == "PREPARE_ONLY")
        {
            continue;
        }
        if !super::read_bounds::claim(&mut work)? {
            work["stage"] = json!("SUBMISSION_UNKNOWN");
            work["status"] = json!("unknown");
            work["reason"] = json!("bounded_reconciliation_exhausted");
            work["revision"] = json!(next(&work)?);
            work["lease_token"] = Value::Null;
            work["lease_until"] = Value::Null;
            put(tx, &key, &work).await?;
            events::queue(
                tx,
                &work,
                "bounded_read_reconciliation_exhausted_no_replay",
                now,
            )
            .await?;
            continue;
        }
        let attempts = work["attempts"]
            .as_i64()
            .filter(|n| *n >= 0)
            .and_then(|n| n.checked_add(1))
            .ok_or_else(invalid)?;
        work["status"] = json!("leased");
        work["revision"] = json!(next(&work)?);
        work["policy_revision"] = current["revision"].clone();
        work["binding"] = binding.clone();
        work["lease_token"] = json!(Uuid::new_v4());
        work["lease_until"] = json!(stamp(now + chrono::Duration::seconds(180)));
        work["attempts"] = json!(attempts);
        work["updated_at"] = json!(stamp(now));
        put(tx, &key, &work).await?;
        events::queue(tx, &work, "claimed", now).await?;
        return Ok(Some(work));
    }
    Ok(None)
}
/// Host-internal entry: callers authenticate the browser/preparation binding before use.
/// No native dispatch or owner HTTP route exposes this primitive by itself.
pub async fn claim(
    c: &mut PgConnection,
    platform: &str,
    binding: &Value,
    operations: Option<&[&str]>,
) -> Result<Option<Value>> {
    if platform != "naukri" || !binding.is_object() {
        return Err(Failure("invalid_execution_contract"));
    }
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
        lock(&mut tx).await?;
        let now = now(&mut tx).await?;
        claim_in(&mut tx, platform, binding, operations, now).await
    }
    .await;
    match result {
        Ok(work) => {
            tx.commit()
                .await
                .map_err(|_| Failure("execution_commit_outcome_unknown"))?;
            Ok(work)
        }
        Err(error) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            Err(error)
        }
    }
}

pub(crate) async fn enqueue_in(
    tx: &mut Transaction<'_, Postgres>,
    url: &str,
    source: &str,
    reference: Option<&str>,
    now: DateTime<Utc>,
) -> Result<Value> {
    if !matches!(
        source,
        "naukri_ui_search" | "approved_gmail_alerts" | "saved_verified_job"
    ) {
        return Err(Failure("unsupported_queue_source"));
    }
    let url = filters::naukri_url(url)?;
    let requisition = url.rsplit('-').next().ok_or_else(invalid)?;
    let id = Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!("naukri:{requisition}").as_bytes(),
    );
    let key = format!("apply_work:{id}");
    // Return the permanent identity untouched; a slug, restart or day change cannot renew it.
    if let Some(existing) = get(tx, &key).await? {
        return Ok(existing);
    }
    if history::receipt_exists_in(tx, requisition).await? {
        return Err(Failure("prior_receipt_requires_reconciliation_no_replay"));
    }
    let jobs:Vec<Value>=sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE source_platform='naukri' AND (job_url LIKE $1 OR job_url LIKE $2) ORDER BY id LIMIT 10001").bind(format!("%-{requisition}")).bind(format!("%-{requisition}/")).fetch_all(&mut **tx).await.map_err(db)?;
    if jobs.len() > 10000 {
        return Err(Failure("execution_active_inventory_limit"));
    }
    for job in jobs {
        if history::previously_applied_in(tx, &job).await? {
            return Err(Failure("prior_application_or_unknown_submission_no_replay"));
        }
    }
    let config = queue_control::configuration(tx).await?;
    let policy = &config["policy"];
    if !policy["platforms"]["naukri"]["sources"]
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .any(|s| s == source)
    {
        return Err(Failure("queue_source_disabled"));
    }
    let pending = super::intake::capacity_in(tx).await?;
    if pending >= policy["max_pending"].as_i64().ok_or_else(invalid)? {
        return Err(Failure("queue_backpressure"));
    }
    let work = filters::initial_item(&config, &url, source, reference, now)?;
    put(tx, &key, &work).await?;
    events::queue(tx, &work, "enqueued", now).await?;
    Ok(work)
}
/// Internal intake of a supported saved source, serialized with Stop and all other queue writers.
/// Neither enqueueing nor a returned permanent identity is evidence of an application.
pub async fn enqueue(
    c: &mut PgConnection,
    url: &str,
    source: &str,
    reference: Option<&str>,
) -> Result<Value> {
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
        lock(&mut tx).await?;
        let now = now(&mut tx).await?;
        enqueue_in(&mut tx, url, source, reference, now).await
    }
    .await;
    match result {
        Ok(work) => {
            tx.commit()
                .await
                .map_err(|_| Failure("execution_commit_outcome_unknown"))?;
            Ok(work)
        }
        Err(error) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            Err(error)
        }
    }
}
