//! Private answer fingerprints, scoped to one repeatable-read profile/job/evidence snapshot.
//! Kept separate from factual/link resolution so those requests need no full evidence scan.
use crate::{
    Failure, Result,
    answer_contract::Generate,
    evidence_retrieval::{self, Evidence},
    job_context::Reviewed,
    profile_store, project_context, question_classifier,
};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;

pub struct Stamp {
    profile_id: Uuid,
    profile_version: i32,
    generation: String,
    missing: String,
    evidence: String,
    job: Option<String>,
}
fn db(_: sqlx::Error) -> Failure {
    Failure("profile_database_error")
}
impl Stamp {
    pub fn profile_id(&self) -> Uuid {
        self.profile_id
    }
    pub fn profile_version(&self) -> i32 {
        self.profile_version
    }
    pub fn generation(&self) -> &str {
        &self.generation
    }
    pub fn missing(&self) -> &str {
        &self.missing
    }
    pub(crate) fn evidence(&self) -> &str {
        &self.evidence
    }
    pub(crate) fn job(&self) -> Option<&str> {
        self.job.as_deref()
    }
    pub async fn load(connection: &mut PgConnection, request: &Generate) -> Result<Self> {
        let mut tx = connection.begin().await.map_err(db)?;
        sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            .execute(&mut *tx)
            .await
            .map_err(db)?;
        let stamp = Self::load_in(&mut tx, request).await?;
        tx.commit().await.map_err(db)?;
        Ok(stamp)
    }
    pub async fn load_in(tx: &mut Transaction<'_, Postgres>, request: &Generate) -> Result<Self> {
        let isolation: String =
            sqlx::query_scalar("SELECT current_setting('transaction_isolation')")
                .fetch_one(&mut **tx)
                .await
                .map_err(db)?;
        if !matches!(isolation.as_str(), "repeatable read" | "serializable") {
            return Err(Failure("answer_context_snapshot_required"));
        }
        let profile = profile_store::get(tx).await?;
        let id = profile.value["id"]
            .as_str()
            .and_then(|s| s.parse::<Uuid>().ok())
            .ok_or(Failure("invalid_profile_record"))?;
        let job = if let Some(job_id) = request.job_id {
            // Fingerprints also serve historical missing-input reads. A deleted or
            // corrected job must make that approval stale, without hiding the request.
            // Generation validates the incoming description/company separately.
            Reviewed::load_in(tx, job_id)
                .await?
                .map(|job| job.digest())
                .transpose()?
        } else {
            None
        };
        // Include unconfirmed rows too: editing/confirmation changes must invalidate approvals.
        let evidence:Vec<Value>=sqlx::query_scalar("SELECT jsonb_build_array(id,title,content,project,user_confirmed) FROM candidate_evidence WHERE candidate_profile_id=$1 ORDER BY id LIMIT 10001").bind(id).fetch_all(&mut **tx).await.map_err(db)?;
        if evidence.len() > 10000 {
            return Err(Failure("answer_evidence_snapshot_limit"));
        }
        let evidence = crate::python_json::digest(
            &json!({"profile_id":id,"version":profile.version,"evidence":evidence}),
        );
        let category = question_classifier::classify(&request.question).question_type;
        let projects = if matches!(category, "project_explanation" | "technical_experience") {
            let available: bool =
                sqlx::query_scalar("SELECT to_regclass('owner_preferences') IS NOT NULL")
                    .fetch_one(&mut **tx)
                    .await
                    .map_err(db)?;
            if available {
                project_context::Snapshot::load_in(tx)
                    .await?
                    .answer_evidence(&request.question, category)?
            } else {
                vec![]
            }
        } else {
            vec![]
        };
        let mut career = profile.value;
        for meta in ["id", "singleton_key", "version", "created_at", "updated_at"] {
            career
                .as_object_mut()
                .ok_or(Failure("invalid_profile_record"))?
                .remove(meta);
        }
        let generation = crate::python_json::digest(
            &json!({"profile":career,"profile_id":id,"profile_version":profile.version,"evidence":evidence,"projects":projects,"job":job}),
        );
        let missing = crate::python_json::digest(
            &json!({"sources":generation,"company_name":request.company_name,"job_description":request.job_description}),
        );
        Ok(Self {
            profile_id: id,
            profile_version: profile.version,
            generation,
            missing,
            evidence,
            job,
        })
    }
}
/// Rank the entire confirmed inventory before bounding candidates, matching the existing SQL.
pub async fn relevant_evidence(
    tx: &mut Transaction<'_, Postgres>,
    profile: Uuid,
    question: &str,
) -> Result<Vec<Evidence>> {
    if question.chars().count() > 2000 {
        return Err(Failure("verified_evidence_limit"));
    }
    let words = evidence_retrieval::tokens(question)
        .into_iter()
        .take(25)
        .collect::<Vec<_>>();
    let rows:Vec<Value>=sqlx::query_scalar("SELECT jsonb_build_object('id',e.id,'title',e.title,'content',e.content,'user_confirmed',e.user_confirmed,'project',e.project) FROM candidate_evidence e WHERE e.candidate_profile_id=$1 AND e.user_confirmed IS TRUE ORDER BY (SELECT count(*) FROM unnest($2::text[]) word WHERE strpos(lower(e.title||' '||e.content||' '||COALESCE(e.project::text,'')),word)>0) DESC,e.updated_at DESC,e.id LIMIT 100").bind(profile).bind(words).fetch_all(&mut **tx).await.map_err(db)?;
    rows.into_iter()
        .map(|v| serde_json::from_value(v).map_err(|_| Failure("invalid_verified_context")))
        .collect()
}
