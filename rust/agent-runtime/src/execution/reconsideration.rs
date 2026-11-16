//! Retained facts can request only a fresh ordinary listing read, never packet preparation or Apply.
use super::{
    contracts, eligibility, events, filters, intake, preflight, queue_control, storage::*,
};
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;
pub const KEY: &str = "apply_filter_recheck";
/// Public for policy regression fixtures. No database/browser authority is conveyed.
pub fn untouched(work: &Value) -> bool {
    matches!(work["status"].as_str(), Some("waiting" | "complete"))
        && work["admitted_actions"] == json!([])
        && ["packet_id", "lease_until"]
            .iter()
            .all(|k| work[*k].is_null())
        && work["form_pending"] != true
        && work["facts"].as_object().is_some_and(|o| !o.is_empty())
}
async fn run_in(tx: &mut Transaction<'_, Postgres>, now: DateTime<Utc>) -> Result<bool> {
    let Some(mut marker) = get(tx, KEY).await? else {
        return Ok(false);
    };
    if marker["status"] != "pending"
        || !marker["retry_after"].is_null() && timestamp(&marker["retry_after"])? > now
    {
        return Ok(false);
    }
    marker["id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    for key in ["checked", "fresh_reads"] {
        if marker[key].as_i64().is_none_or(|n| n < 0) {
            return Err(invalid());
        }
    }
    let config = queue_control::configuration(tx).await?;
    let setting = &config["policy"]["platforms"]["naukri"];
    if config["state"] != "RUNNING" || setting["enabled"] != true {
        return Ok(false);
    }
    let profile = match preflight::profile_in(tx, &json!({})).await {
        Ok(p) => p,
        Err(Failure("verified_profile_context_changed")) => return Ok(false),
        Err(e) => return Err(e),
    };
    let cursor = marker["cursor"].as_str();
    if !marker["cursor"].is_null() && cursor.is_none() {
        return Err(invalid());
    }
    let rows:Vec<(String,Value)>=sqlx::query_as("SELECT key,value FROM owner_preferences WHERE starts_with(key,'apply_work:') AND value->>'platform'='naukri' AND value->>'stage' IN ('SKIPPED','NEEDS_INPUT') AND value->>'reason'=ANY($1::text[]) AND ($2::text IS NULL OR key>$2) ORDER BY key LIMIT 10").bind(filters::FILTER_HOLDS.to_vec()).bind(cursor).fetch_all(&mut **tx).await.map_err(db)?;
    if rows.is_empty() {
        marker["status"] = json!("complete");
        marker["completed_at"] = json!(stamp(now));
        put(tx, KEY, &marker).await?;
        return Ok(false);
    }
    let mut requisitions = vec![];
    for (key, v) in &rows {
        let id = v["id"]
            .as_str()
            .and_then(|s| s.parse::<Uuid>().ok())
            .ok_or_else(invalid)?;
        if key != &format!("apply_work:{id}") {
            return Err(invalid());
        }
        requisitions.push(
            v["requisition"]
                .as_str()
                .filter(|s| s.len() >= 10 && s.len() <= 20 && s.bytes().all(|b| b.is_ascii_digit()))
                .ok_or_else(invalid)?
                .to_owned(),
        );
    }
    let protected = intake::protected_in(tx, &requisitions).await?;
    let mut pending = intake::capacity_in(tx).await?;
    let mut changed = false;
    for (key, before) in rows {
        if !untouched(&before)
            || protected.contains(before["requisition"].as_str().unwrap())
            || !setting["sources"]
                .as_array()
                .ok_or_else(invalid)?
                .iter()
                .any(|s| s == &before["source"])
        {
            marker["cursor"] = json!(key);
            continue;
        }
        let mut work = before.clone();
        work["profile_version"] = Value::Null;
        let effective = contracts::limits(&config["policy"], "naukri")?;
        let mut reason = filters::listing_exclusion(&work["facts"], &effective, now)?;
        if reason.is_none() {
            let job = work["job_id"].as_str().and_then(|s| s.parse::<Uuid>().ok());
            let job: Option<Value> = match job {
                Some(id) => sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1")
                    .bind(id)
                    .fetch_optional(&mut **tx)
                    .await
                    .map_err(db)?,
                None => None,
            };
            if let Some(job) = job {
                let company = if let Some(id) = job["company_id"].as_str() {
                    let id = id.parse::<Uuid>().map_err(|_| invalid())?;
                    sqlx::query_scalar("SELECT jsonb_set(to_jsonb(c),'{metadata_}',coalesce(c.metadata,'{}'::jsonb)) FROM companies c WHERE id=$1").bind(id).fetch_optional(&mut **tx).await.map_err(db)?
                } else {
                    None
                };
                if let Err(error) =
                    eligibility::check(&mut work, &config["policy"], job, company, &profile, now)
                {
                    if !filters::FILTER_HOLDS.contains(&error.0)
                        && error.0 != "vacancy_closed_expired_or_invalid"
                    {
                        return Err(error);
                    }
                    reason = Some(error.0);
                }
            } else {
                let band = work["facts"]["experience_min"]
                    .as_f64()
                    .zip(work["facts"]["experience_max"].as_f64())
                    .zip(profile["verified_experience_years"].as_f64());
                reason = match band {
                    None => Some("verified_experience_requirements_required"),
                    Some(((lo, hi), years))
                        if !lo.is_finite() || !hi.is_finite() || !years.is_finite() =>
                    {
                        return Err(invalid());
                    }
                    Some(((lo, hi), years)) if years < lo || years > hi => {
                        Some("required_experience_outside_verified_band")
                    }
                    _ => None,
                };
            }
        }
        if reason.is_none()
            && !filters::uses_capacity(&before)
            && pending
                >= config["policy"]["max_pending"]
                    .as_i64()
                    .ok_or_else(invalid)?
        {
            marker["retry_after"] = json!(stamp(now + chrono::Duration::seconds(60)));
            break;
        }
        marker["cursor"] = json!(key);
        if let Some(reason) = reason {
            eligibility::hold(&mut work, reason);
        } else {
            work["stage"] = json!("DISCOVERED");
            work["status"] = json!("queued");
            work["operation"] = json!("inspect_job");
            work["reason"] = Value::Null;
            work["binding"] = Value::Null;
            work["lease_token"] = Value::Null;
            work["lease_until"] = Value::Null;
            work["available_at"] = json!(stamp(now));
            work.as_object_mut()
                .ok_or_else(invalid)?
                .remove("paused_context");
            marker["fresh_reads"] = json!(
                marker["fresh_reads"]
                    .as_i64()
                    .unwrap()
                    .checked_add(1)
                    .ok_or_else(invalid)?
            );
        }
        pending +=
            i64::from(filters::uses_capacity(&work)) - i64::from(filters::uses_capacity(&before));
        work["revision"] = json!(next(&before)?);
        work["policy_revision"] = config["revision"].clone();
        work["updated_at"] = json!(stamp(now));
        work["last_filter_recheck"] = json!({"request_id":marker["id"],"profile_version":profile["version"],"policy_revision":config["revision"],"retained_facts_only":true});
        put(tx, &key, &work).await?;
        events::queue(tx, &work, "owner_filter_change_rechecked", now).await?;
        marker["checked"] = json!(
            marker["checked"]
                .as_i64()
                .unwrap()
                .checked_add(1)
                .ok_or_else(invalid)?
        );
        changed = true;
    }
    put(tx, KEY, &marker).await?;
    Ok(changed)
}
/// Skip a contended owner fence so discovery/Stop and in-flight forms have priority.
pub async fn tick(c: &mut sqlx::PgConnection) -> Result<bool> {
    use sqlx::Connection;
    let hint: Option<Value> =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
            .bind(KEY)
            .fetch_optional(&mut *c)
            .await
            .map_err(db)?;
    if hint.as_ref().is_none_or(|v| v["status"] != "pending") {
        return Ok(false);
    }
    let mut tx = c.begin().await.map_err(db)?;
    let result=async{
        let acquired:Option<String>=sqlx::query_scalar("SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE SKIP LOCKED").fetch_optional(&mut *tx).await.map_err(db)?;
        if acquired.is_none(){let exists:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM owner_preferences WHERE key='agent_conversation:primary')").fetch_one(&mut *tx).await.map_err(db)?;if exists{return Ok(false);}lock(&mut tx).await?;}else if !crate::owner_fence::advance_in(&mut tx).await.map_err(db)?{return Err(Failure("execution_write_ack_failed"));}
        let now=now(&mut tx).await?;run_in(&mut tx,now).await
    }.await;
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
