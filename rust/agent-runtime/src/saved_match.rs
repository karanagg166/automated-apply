//! Owner-only saved-profile relevance. No score/profile/history persistence or admission.
use crate::{Failure, Result, profile_store};
use automated_apply_domain::matching::{Listing, Profile, base_match};
use serde_json::{Value, json};
use sqlx::PgConnection;
use uuid::Uuid;

pub async fn calculate(connection: &mut PgConnection, id: Uuid) -> Result<Value> {
    // Preserve the legacy order: unknown job is reported before missing profile.
    let listing = load_job(connection, id).await?;
    let saved = profile_store::get(connection).await?;
    evaluate(listing, saved.value, id)
}
/// The separate saved-data GET validates the profile before looking up the job.
pub async fn read_calculate(connection: &mut PgConnection, id: Uuid) -> Result<Value> {
    let saved = profile_store::get(connection).await?;
    let listing = load_job(connection, id).await?;
    evaluate(listing, saved.value, id)
}
async fn load_job(connection: &mut PgConnection, id: Uuid) -> Result<Listing> {
    let job:Option<Value>=sqlx::query_scalar("SELECT jsonb_build_object('title',title,'description',description,'skills_required',COALESCE(skills_required,ARRAY[]::text[]),'location',location,'is_remote',COALESCE(is_remote,false),'experience_level',experience_level) FROM jobs WHERE id=$1")
        .bind(id).fetch_optional(&mut *connection).await.map_err(|_|Failure("saved_jobs_database_error"))?;
    serde_json::from_value(job.ok_or(Failure("job_not_found"))?)
        .map_err(|_| Failure("invalid_saved_job_record"))
}
fn evaluate(listing: Listing, saved: Value, id: Uuid) -> Result<Value> {
    // The pure scorer consumes only verified skills, experience and search preferences.
    let profile: Profile =
        serde_json::from_value(saved).map_err(|_| Failure("invalid_profile_record"))?;
    let result = base_match(&listing, &profile);
    let mut output = serde_json::to_value(result).map_err(|_| Failure("invalid_match_result"))?;
    output
        .as_object_mut()
        .ok_or(Failure("invalid_match_result"))?
        .insert("job_id".into(), json!(id));
    Ok(output)
}
