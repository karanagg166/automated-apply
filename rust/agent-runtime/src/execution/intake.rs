//! Set-based ordinary discovery intake. Permanent work/receipt/unknown history wins over any URL slug.
use super::{filters, queue_control, storage::*};
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use std::collections::BTreeSet;
use uuid::Uuid;
pub(crate) async fn capacity_in(tx: &mut Transaction<'_, Postgres>) -> Result<i64> {
    sqlx::query_scalar("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'apply_work:') AND coalesce(value->>'stage','unknown') NOT IN ('SUBMITTED_RECORDED','SUBMITTED_CONFIRMED','FAILED_FINAL','SKIPPED') AND (coalesce(value->>'stage','unknown')!='NEEDS_INPUT' OR coalesce(value->>'status','unknown')!='waiting' OR NOT coalesce(value->>'reason'=ANY($1::text[]),false) OR value->>'packet_id' IS NOT NULL OR value->>'lease_until' IS NOT NULL OR value->'form_pending'='true'::jsonb OR coalesce(value->'admitted_actions','null'::jsonb)!='[]'::jsonb)").bind(filters::FILTER_HOLDS.to_vec()).fetch_one(&mut **tx).await.map_err(db)
}
pub(crate) async fn protected_in(
    tx: &mut Transaction<'_, Postgres>,
    requisitions: &[String],
) -> Result<BTreeSet<String>> {
    let rows:Vec<String>=sqlx::query_scalar("WITH candidates AS (SELECT j.id,j.status,to_jsonb(j)->>'application_status' AS application_status,j.discovery_metadata,(regexp_match(rtrim(j.job_url,'/'),'-([0-9]{10,20})$'))[1] AS req FROM jobs j WHERE j.source_platform='naukri') SELECT DISTINCT req FROM candidates j WHERE req=ANY($1::text[]) AND (j.status IN ('applied','submitted') OR j.application_status IN ('applied','submitted','interview','offer','applied_manually','applied_verified') OR j.discovery_metadata#>>'{data_provenance,posting_status}'='already_applied' OR EXISTS(SELECT 1 FROM application_packets p WHERE p.job_id=j.id AND p.lifecycle_state IN ('user_reported_submitted','provider_confirmed_submitted','submitting','submission_unknown'))) UNION SELECT substr(key,strpos(key,':')+1) FROM owner_preferences WHERE key=ANY($2::text[])")
        .bind(requisitions).bind(requisitions.iter().flat_map(|req|[format!("naukri_receipt:{req}"),format!("naukri_worker_receipt:{req}")]).collect::<Vec<_>>()).fetch_all(&mut **tx).await.map_err(db)?;
    Ok(rows.into_iter().collect())
}
pub(crate) async fn batch_in(
    tx: &mut Transaction<'_, Postgres>,
    urls: &[String],
    source: &str,
    now: DateTime<Utc>,
) -> Result<usize> {
    if urls.len() > 20
        || !matches!(
            source,
            "naukri_ui_search" | "saved_verified_job" | "approved_gmail_alerts"
        )
    {
        return Err(Failure("bounded_supported_queue_batch_required"));
    }
    let config = queue_control::configuration(tx).await?;
    if !config["policy"]["platforms"]["naukri"]["sources"]
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .any(|s| s == source)
    {
        return Err(Failure("queue_source_disabled"));
    }
    let mut normalized = Vec::<(String, String, Uuid)>::new();
    for raw in urls {
        let Ok(url) = filters::naukri_url(raw) else {
            continue;
        };
        let req = url.rsplit('-').next().ok_or_else(invalid)?.to_owned();
        if normalized.iter().any(|(r, _, _)| r == &req) {
            continue;
        }
        let id = Uuid::new_v5(&Uuid::NAMESPACE_URL, format!("naukri:{req}").as_bytes());
        normalized.push((req, url, id));
    }
    if normalized.is_empty() {
        return Ok(0);
    }
    let requisitions = normalized
        .iter()
        .map(|(r, _, _)| r.clone())
        .collect::<Vec<_>>();
    let protected = protected_in(tx, &requisitions).await?;
    let keys = normalized
        .iter()
        .map(|(_, _, id)| format!("apply_work:{id}"))
        .collect::<Vec<_>>();
    let existing: BTreeSet<String> = sqlx::query_scalar::<_, String>(
        "SELECT key FROM owner_preferences WHERE key=ANY($1::text[])",
    )
    .bind(keys)
    .fetch_all(&mut **tx)
    .await
    .map_err(db)?
    .into_iter()
    .collect();
    let available = config["policy"]["max_pending"]
        .as_i64()
        .ok_or_else(invalid)?
        .saturating_sub(capacity_in(tx).await?)
        .max(0) as usize;
    let mut works = vec![];
    for (req, url, id) in normalized {
        if protected.contains(&req) || existing.contains(&format!("apply_work:{id}")) {
            continue;
        }
        if works.len() >= available {
            break;
        }
        works.push(filters::initial_item(&config, &url, source, None, now)?);
    }
    if works.is_empty() {
        return Ok(0);
    }
    let records = works
        .iter()
        .map(|w| json!({"key":format!("apply_work:{}",w["id"].as_str().unwrap()),"value":w}))
        .collect::<Vec<_>>();
    let ack:Vec<(String,Value)>=sqlx::query_as("INSERT INTO owner_preferences(key,value,created_at,updated_at) SELECT key,value,$2,$2 FROM jsonb_to_recordset($1::jsonb) AS r(key text,value jsonb) ON CONFLICT(key) DO NOTHING RETURNING key,value").bind(json!(records)).bind(now).fetch_all(&mut **tx).await.map_err(db)?;
    if ack.len() != records.len()
        || records
            .iter()
            .any(|r| !ack.iter().any(|(k, v)| r["key"] == *k && r["value"] == *v))
    {
        return Err(Failure("execution_write_ack_failed"));
    }
    let events=works.iter().map(|work|{let identity=work["id"].as_str().unwrap();let revision=work["revision"].as_i64().unwrap();let id=Uuid::new_v5(&Uuid::NAMESPACE_URL,format!("queue:{identity}:{revision}:enqueued").as_bytes());json!({"key":format!("apply_event:{id}"),"value":{"id":id,"queue_id":identity,"platform":work["platform"],"stage":work["stage"],"event":"enqueued","at":stamp(now),"delivered":false}})}).collect::<Vec<_>>();
    let ack:Vec<(String,Value)>=sqlx::query_as("INSERT INTO owner_preferences(key,value) SELECT key,value FROM jsonb_to_recordset($1::jsonb) AS r(key text,value jsonb) ON CONFLICT(key) DO NOTHING RETURNING key,value").bind(json!(events)).fetch_all(&mut **tx).await.map_err(db)?;
    if ack.len() != events.len()
        || events
            .iter()
            .any(|r| !ack.iter().any(|(k, v)| r["key"] == *k && r["value"] == *v))
    {
        return Err(Failure("execution_write_ack_failed"));
    }
    Ok(works.len())
}
/// Internal bounded source intake, not a provider action. All state/events commit together.
pub async fn batch(c: &mut sqlx::PgConnection, urls: &[String], source: &str) -> Result<usize> {
    use sqlx::Connection;
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
        lock(&mut tx).await?;
        let now = now(&mut tx).await?;
        batch_in(&mut tx, urls, source, now).await
    }
    .await;
    match result {
        Ok(value) => {
            tx.commit()
                .await
                .map_err(|_| Failure("execution_commit_outcome_unknown"))?;
            Ok(value)
        }
        Err(e) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            Err(e)
        }
    }
}
