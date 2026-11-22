//! Read-only projections of existing reviewed profile and saved job evidence.
//! No mailbox contents, resume decryption or application authority crosses this boundary.
use crate::{Failure, Result};
use automated_apply_domain::matching::{
    Company, DiscoveryMatch, Listing, Profile, discovery_match,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sqlx::PgConnection;
use uuid::Uuid;

#[derive(Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct ProfilePin {
    pub id: Uuid,
    pub version: i32,
}
#[derive(Deserialize)]
struct ProfileRecord {
    pub id: Uuid,
    pub version: i32,
    pub verified_skills: Vec<String>,
    pub verified_experience_years: Option<f64>,
    pub preferences: Value,
}
pub struct ReviewedProfile {
    pub pin: ProfilePin,
    pub facts: Profile,
}
#[derive(Deserialize)]
struct SavedRecord {
    pub id: Uuid,
    pub company_id: Option<Uuid>,
    pub source_platform: String,
    pub listing: Listing,
    pub company: Option<Company>,
    pub source_verification_status: String,
}
#[derive(Deserialize)]
struct RankingSnapshot {
    profile: Option<Value>,
    jobs: Vec<Value>,
    excluded_prior_or_unknown: usize,
}
#[derive(Serialize)]
pub struct SavedReference {
    pub job_id: Uuid,
    pub source_platform: String,
}
#[derive(Serialize)]
pub struct RankedJob {
    pub job_id: Uuid,
    pub company_id: Option<Uuid>,
    pub title: String,
    pub source_platform: String,
    pub source_verification_status: String,
    pub ranking: DiscoveryMatch,
}
#[derive(Serialize)]
pub struct RankedSavedJobs {
    pub profile: ProfilePin,
    pub scanned: usize,
    pub excluded_prior_or_unknown: usize,
    pub jobs: Vec<RankedJob>,
    pub scope: &'static str,
}

fn decode_profile(value: Value) -> Result<ReviewedProfile> {
    if serde_json::to_vec(&value)
        .map_err(|_| Failure("invalid_verified_context"))?
        .len()
        > 65536
    {
        return Err(Failure("verified_context_size"));
    }
    let row: ProfileRecord =
        serde_json::from_value(value).map_err(|_| Failure("invalid_verified_context"))?;
    if row.version < 1
        || row
            .verified_experience_years
            .is_some_and(|n| !n.is_finite() || !(0.0..=100.0).contains(&n))
    {
        return Err(Failure("invalid_verified_context"));
    }
    let facts:Profile=serde_json::from_value(serde_json::json!({"verified_skills":row.verified_skills,"verified_experience_years":row.verified_experience_years,"preferences":row.preferences})).map_err(|_|Failure("invalid_verified_context"))?;
    Ok(ReviewedProfile {
        pin: ProfilePin {
            id: row.id,
            version: row.version,
        },
        facts,
    })
}

pub async fn reviewed_profile(connection: &mut PgConnection) -> Result<Option<ReviewedProfile>> {
    let value:Option<Value>=sqlx::query_scalar("SELECT jsonb_build_object('id',p.id,'version',p.version,'verified_skills',p.verified_skills,'verified_experience_years',p.verified_experience_years,'preferences',p.preferences) FROM candidate_profiles p JOIN owner_preferences c ON c.key='phase1_profile_confirmation' WHERE p.singleton_key='primary' AND c.value->>'profile_id'=p.id::text AND c.value->'profile_version'=to_jsonb(p.version) AND jsonb_typeof(c.value->'confirmed_at')='string' AND NULLIF(c.value->>'confirmed_at','') IS NOT NULL LIMIT 1")
        .fetch_optional(connection).await.map_err(|_|Failure("verified_context_database_error"))?;
    value.map(decode_profile).transpose()
}

pub async fn rank_saved_naukri(
    connection: &mut PgConnection,
    expected: &ProfilePin,
    limit: usize,
) -> Result<RankedSavedJobs> {
    rank(connection, expected, Some("naukri"), None, limit).await
}

pub async fn rank_saved_jobs(
    connection: &mut PgConnection,
    expected: &ProfilePin,
    limit: usize,
) -> Result<RankedSavedJobs> {
    rank(connection, expected, None, None, limit).await
}

pub(crate) async fn job_still_rankable(
    connection: &mut PgConnection,
    expected: &ProfilePin,
    job: Uuid,
) -> Result<bool> {
    Ok(!rank_selected_job(connection, expected, job)
        .await?
        .jobs
        .is_empty())
}

pub(crate) async fn rank_selected_job(
    connection: &mut PgConnection,
    expected: &ProfilePin,
    job: Uuid,
) -> Result<RankedSavedJobs> {
    rank(connection, expected, None, Some(job), 1).await
}

async fn rank(
    connection: &mut PgConnection,
    expected: &ProfilePin,
    platform: Option<&str>,
    job: Option<Uuid>,
    limit: usize,
) -> Result<RankedSavedJobs> {
    if !(1..=10).contains(&limit) {
        return Err(Failure("invalid_saved_result_limit"));
    }
    // Confirmation, saved jobs and all replay fences share one statement/snapshot/round trip.
    let value: Value = sqlx::query_scalar(include_str!("../sql/saved_naukri.sql"))
        .bind(platform)
        .bind(job)
        .fetch_one(&mut *connection)
        .await
        .map_err(|_| Failure("saved_jobs_database_error"))?;
    if serde_json::to_vec(&value)
        .map_err(|_| Failure("invalid_saved_job"))?
        .len()
        > 8 * 1024 * 1024
    {
        return Err(Failure("saved_jobs_context_size"));
    }
    let snapshot: RankingSnapshot =
        serde_json::from_value(value).map_err(|_| Failure("invalid_saved_job"))?;
    let profile = decode_profile(snapshot.profile.ok_or(Failure("profile_review_required"))?)?;
    if &profile.pin != expected {
        return Err(Failure("verified_profile_context_changed"));
    }
    let scanned = snapshot.jobs.len() + snapshot.excluded_prior_or_unknown;
    let mut jobs = Vec::new();
    for value in snapshot.jobs {
        if serde_json::to_vec(&value)
            .map_err(|_| Failure("invalid_saved_job"))?
            .len()
            > 262144
        {
            return Err(Failure("saved_job_context_size"));
        }
        let row: SavedRecord =
            serde_json::from_value(value).map_err(|_| Failure("invalid_saved_job"))?;
        let ranking = discovery_match(&row.listing, &profile.facts, row.company.as_ref(), false);
        if !ranking.exclusion_reasons.is_empty() {
            continue;
        }
        jobs.push(RankedJob {
            job_id: row.id,
            company_id: row.company_id,
            title: row.listing.title,
            source_platform: row.source_platform,
            source_verification_status: row.source_verification_status,
            ranking,
        });
    }
    jobs.sort_by(|a, b| {
        b.ranking
            .match_score
            .total_cmp(&a.ranking.match_score)
            .then_with(|| a.job_id.cmp(&b.job_id))
    });
    jobs.truncate(limit);
    Ok(RankedSavedJobs {
        profile: profile.pin,
        scanned,
        excluded_prior_or_unknown: snapshot.excluded_prior_or_unknown,
        jobs,
        scope: if platform.is_some() {
            "saved_naukri_ranking_preview_not_application_admission"
        } else {
            "saved_jobs_ranking_preview_not_application_admission"
        },
    })
}

pub async fn search_saved_jobs(
    connection: &mut PgConnection,
    expected: &ProfilePin,
) -> Result<Vec<SavedReference>> {
    search_scoped_jobs(connection, expected, None).await
}

pub(crate) async fn search_scoped_jobs(
    connection: &mut PgConnection,
    expected: &ProfilePin,
    target: Option<Uuid>,
) -> Result<Vec<SavedReference>> {
    use sqlx::Connection;
    let mut tx = connection
        .begin()
        .await
        .map_err(|_| Failure("saved_jobs_database_error"))?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(|_| Failure("saved_jobs_database_error"))?;
    let profile = reviewed_profile(&mut tx)
        .await?
        .ok_or(Failure("profile_review_required"))?;
    if &profile.pin != expected {
        return Err(Failure("verified_profile_context_changed"));
    }
    let jobs = sqlx::query_as::<_, (Uuid, String)>(
        "SELECT id AS job_id,source_platform FROM (
            SELECT id,source_platform,created_at,
                row_number() OVER (PARTITION BY source_platform ORDER BY created_at DESC,id) AS source_position
            FROM jobs WHERE status NOT IN ('archived','applied','submitted')
                AND ($1::uuid IS NULL OR (id=$1 AND status<>'rejected'))
        ) saved ORDER BY source_position,created_at DESC,id LIMIT 10",
    )
    .bind(target)
    .fetch_all(&mut *tx)
    .await
    .map_err(|_| Failure("saved_jobs_database_error"))?;
    tx.commit()
        .await
        .map_err(|_| Failure("saved_jobs_database_error"))?;
    Ok(jobs
        .into_iter()
        .map(|(job_id, source_platform)| SavedReference {
            job_id,
            source_platform,
        })
        .collect())
}

pub async fn application_history(
    connection: &mut PgConnection,
    expected: &ProfilePin,
) -> Result<Value> {
    // One statement binds history to the current independently confirmed profile.
    let value:Value=sqlx::query_scalar("WITH reviewed AS (SELECT p.id,p.version FROM candidate_profiles p JOIN owner_preferences c ON c.key='phase1_profile_confirmation' WHERE p.singleton_key='primary' AND c.value->>'profile_id'=p.id::text AND c.value->'profile_version'=to_jsonb(p.version) AND jsonb_typeof(c.value->'confirmed_at')='string' AND NULLIF(c.value->>'confirmed_at','') IS NOT NULL) SELECT jsonb_build_object('current',EXISTS(SELECT 1 FROM reviewed WHERE id=$1 AND version=$2),'applications',COALESCE((SELECT jsonb_agg(to_jsonb(a)) FROM (SELECT job_id,lifecycle_state AS state,readiness_state AS readiness,id AS packet_id FROM application_packets WHERE candidate_profile_id=$1 AND EXISTS(SELECT 1 FROM reviewed WHERE id=$1 AND version=$2) ORDER BY created_at DESC,id LIMIT 10) a),'[]'::jsonb))")
        .bind(expected.id).bind(expected.version).fetch_one(connection).await.map_err(|_|Failure("application_history_database_error"))?;
    if value.get("current").and_then(Value::as_bool) != Some(true) {
        return Err(Failure("verified_profile_context_changed"));
    }
    Ok(serde_json::json!({"applications":value["applications"],"profile_version":expected.version}))
}
