//! Explicit cached-feed intake. No network, employer inference or application authority.
use crate::{
    Failure, Result,
    public_discovery::{Batch, Platform},
};
use chrono::{DateTime, Utc};
use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use sqlx::{Connection, PgConnection};
use uuid::Uuid;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Input {
    pub batch_token: Uuid,
}
pub fn request(bytes: &[u8]) -> Result<Input> {
    serde_json::from_slice(bytes).map_err(|_| Failure("invalid_feed_ingestion_request"))
}
pub fn route(path: &str) -> Option<&str> {
    path.strip_prefix("/api/v1/rust-agent/platforms/")?
        .strip_suffix("/ingest")
        .filter(|s| !s.is_empty() && !s.contains('/'))
}
fn db(_: sqlx::Error) -> Failure {
    Failure("public_feed_database_error")
}

pub async fn ingest(c: &mut PgConnection, platform: Platform, input: Input) -> Result<Value> {
    let mut tx = c.begin().await.map_err(db)?;
    // Same transaction-scoped identity lock as legacy ingestion, never a second pool.
    sqlx::query("SELECT pg_advisory_xact_lock(240204)")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let ledger = format!(
        "public_feed_ingest:{}:{}",
        platform.name(),
        input.batch_token
    );
    if let Some(prior) =
        sqlx::query_scalar::<_, Value>("SELECT value FROM owner_preferences WHERE key=$1")
            .bind(&ledger)
            .fetch_optional(&mut *tx)
            .await
            .map_err(db)?
    {
        tx.commit()
            .await
            .map_err(|_| Failure("public_feed_commit_outcome_unknown"))?;
        return Ok(prior);
    }
    let cache: Option<Value> =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1 FOR UPDATE")
            .bind(format!("public_feed:{}", platform.name()))
            .fetch_optional(&mut *tx)
            .await
            .map_err(db)?;
    let cache = cache.ok_or(Failure("feed_batch_unavailable"))?;
    if cache["state"] != "completed" || cache["token"] != json!(input.batch_token) {
        return Err(Failure("feed_batch_changed"));
    }
    let now = Utc::now();
    let fetched = cache["fetched_at"]
        .as_i64()
        .ok_or(Failure("feed_batch_invalid"))?;
    let ttl = match platform {
        Platform::Himalayas => 86400,
        Platform::WeWorkRemotely => 1800,
    };
    if fetched > now.timestamp() || now.timestamp().saturating_sub(fetched) >= ttl {
        return Err(Failure("feed_batch_stale"));
    }
    let batch: Batch = serde_json::from_value(cache["batch"].clone())
        .map_err(|_| Failure("feed_batch_invalid"))?;
    if batch.platform.name() != platform.name() || batch.jobs.len() > 20 {
        return Err(Failure("feed_batch_invalid"));
    }
    let mut ids = Vec::new();
    let mut inserted = 0;
    let mut duplicates = 0;
    let mut expired = 0;
    for job in batch.jobs {
        crate::public_discovery::validate_saved_job(platform, &job)?;
        if job.source_id.chars().count() > 255 {
            return Err(Failure("feed_batch_invalid"));
        }
        if let Some(expiry) = &job.expires_at {
            let expiry =
                DateTime::parse_from_rfc3339(expiry).map_err(|_| Failure("feed_batch_invalid"))?;
            if expiry <= now {
                expired += 1;
                continue;
            }
        }
        let identity = format!("{:x}", Sha256::digest(format!("id::{}", job.source_id)));
        let observed: Option<Uuid> = sqlx::query_scalar(
            "SELECT job_id FROM job_source_observations WHERE source=$1 AND identity_key=$2",
        )
        .bind(platform.name())
        .bind(&identity)
        .fetch_optional(&mut *tx)
        .await
        .map_err(db)?;
        let id = if let Some(id) = observed {
            let exists: Option<Uuid> =
                sqlx::query_scalar("SELECT id FROM jobs WHERE id=$1 FOR UPDATE")
                    .bind(id)
                    .fetch_optional(&mut *tx)
                    .await
                    .map_err(db)?;
            exists.ok_or(Failure("feed_identity_conflict"))?
        } else {
            let candidates: Vec<Uuid> = sqlx::query_scalar(
                "SELECT id FROM jobs WHERE job_url=$1 OR canonical_key=$1 LIMIT 2 FOR UPDATE",
            )
            .bind(&job.source_url)
            .fetch_all(&mut *tx)
            .await
            .map_err(db)?;
            if candidates.len() > 1 {
                return Err(Failure("feed_identity_conflict"));
            }
            if let Some(id) = candidates.first() {
                *id
            } else {
                let id = Uuid::new_v4();
                let description = (!job.description_truncated).then_some(job.description.as_str());
                let metadata = json!({"source_name":platform.name(),"source_job_id":job.source_id,"company_name":job.company_name,"original_url":job.application_url,"source_updated_at":job.source_updated_at,"expires_at":job.expires_at,"location_restrictions":job.location_restrictions,"timezone_restrictions":job.timezone_restrictions,"description_preview":job.description,"description_truncated":job.description_truncated,"applicant_count":null,"eligibility_verified":false,"application_dispatch":false});
                let saved:Option<Uuid>=sqlx::query_scalar("INSERT INTO jobs(id,title,job_url,canonical_key,application_url,source_platform,status,description,skills_required,remote_type,is_remote,source_verification_status,date_posted,discovery_metadata) VALUES($1,$2,$3,$3,$4,$5,'discovered',$6,ARRAY[]::text[],'unknown',false,'source_reported',$7::text::timestamptz,$8) RETURNING id")
                    .bind(id).bind(&job.title).bind(&job.source_url).bind(&job.application_url).bind(platform.name()).bind(description).bind(&job.published_at).bind(metadata).fetch_optional(&mut *tx).await.map_err(db)?;
                if saved != Some(id) {
                    return Err(Failure("feed_ingestion_write_ack_failed"));
                }
                inserted += 1;
                id
            }
        };
        let provenance = json!({"method":"official_public_feed","application_url":job.application_url,"description_truncated":job.description_truncated,"eligibility_verified":false});
        let saved:Option<Uuid>=sqlx::query_scalar("INSERT INTO job_source_observations(id,job_id,source,identity_key,source_job_id,original_url,provenance,verification_status) VALUES($1,$2,$3,$4,$5,$6,$7,'source_reported') ON CONFLICT(source,identity_key) DO UPDATE SET last_observed_at=GREATEST(job_source_observations.last_observed_at,EXCLUDED.last_observed_at) WHERE job_source_observations.job_id=EXCLUDED.job_id RETURNING job_id")
            .bind(Uuid::new_v4()).bind(id).bind(platform.name()).bind(identity).bind(&job.source_id).bind(&job.application_url).bind(provenance).fetch_optional(&mut *tx).await.map_err(db)?;
        if saved != Some(id) {
            return Err(Failure("feed_ingestion_write_ack_failed"));
        }
        ids.push(id);
    }
    duplicates += ids.len() - inserted;
    let result = json!({"platform":platform,"batch_token":input.batch_token,"job_ids":ids,"inserted_count":inserted,"duplicate_count":duplicates,"expired_count":expired,"application_dispatch":false,"eligibility_verified":false});
    let saved: Option<Value> = sqlx::query_scalar(
        "INSERT INTO owner_preferences(key,value) VALUES($1,$2) RETURNING value",
    )
    .bind(ledger)
    .bind(&result)
    .fetch_optional(&mut *tx)
    .await
    .map_err(db)?;
    if saved != Some(result.clone()) {
        return Err(Failure("feed_ingestion_write_ack_failed"));
    }
    tx.commit()
        .await
        .map_err(|_| Failure("public_feed_commit_outcome_unknown"))?;
    Ok(result)
}
