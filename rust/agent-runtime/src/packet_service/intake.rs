//! Owner-pasted official pages produce local drafts using the saved packet service.
use super::{Settings, create_locked_in, db};
use crate::{Failure, Result, answer_service, execution, packet_contract, packet_platform};
use automated_apply_domain::text::folded;
use chrono::{DateTime, Utc};
use serde::Deserialize;
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;

const INVALID: Failure = Failure("invalid_packet_intake");
const CONFLICT: Failure = Failure("packet_intake_context_conflict");

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Input {
    application_url: String,
    company_name: String,
    job_title: String,
    idempotency_key: String,
    resume_resource_id: Option<Uuid>,
}

pub(super) struct Intake {
    url: String,
    company: String,
    title: String,
    preparation: packet_contract::Prepare,
}

impl Intake {
    pub(super) fn parse(body: &[u8], policy: &packet_platform::Policy) -> Result<Self> {
        let input: Input = serde_json::from_slice(body).map_err(|_| INVALID)?;
        let label = |value: String| {
            let value = value.trim();
            if !(1..=200).contains(&value.chars().count()) || value.chars().any(char::is_control) {
                return Err(INVALID);
            }
            Ok(value.to_owned())
        };
        let url = input.application_url.trim();
        if !(10..=2048).contains(&url.len()) || url.chars().any(char::is_control) {
            return Err(INVALID);
        }
        let url = packet_platform::manual_page(url, policy)
            .ok_or(Failure("invalid_packet_intake_destination"))?;
        let preparation = packet_contract::normalize(
            json!({
                "idempotency_key":input.idempotency_key,"resume_resource_id":input.resume_resource_id,
            }),
            true,
        )?;
        Ok(Self {
            url,
            company: label(input.company_name)?,
            title: label(input.job_title)?,
            preparation,
        })
    }
}

async fn saved_job(tx: &mut Transaction<'_, Postgres>, request: &Intake) -> Result<Option<Uuid>> {
    let rows: Vec<(Uuid, String, String, Option<String>)> = sqlx::query_as(
        "SELECT j.id,j.title,j.status,c.name FROM jobs j LEFT JOIN companies c ON c.id=j.company_id
         WHERE j.job_url=$1 OR j.application_url=$1 ORDER BY j.id LIMIT 2",
    )
    .bind(&request.url)
    .fetch_all(&mut **tx)
    .await
    .map_err(db)?;
    match rows.as_slice() {
        [] => Ok(None),
        [(job, title, status, company)]
            if title == &request.title && company.as_deref() == Some(request.company.as_str()) =>
        {
            if matches!(status.as_str(), "archived" | "applied" | "rejected") {
                let replay: bool = sqlx::query_scalar(
                    "SELECT EXISTS(SELECT 1 FROM application_packets
                    WHERE job_id=$1 AND idempotency_key=$2)",
                )
                .bind(job)
                .bind(request.preparation.idempotency_key.as_deref())
                .fetch_one(&mut **tx)
                .await
                .map_err(db)?;
                if !replay {
                    return Err(CONFLICT);
                }
            }
            Ok(Some(*job))
        }
        _ => Err(CONFLICT),
    }
}

async fn create_job(tx: &mut Transaction<'_, Postgres>, request: &Intake) -> Result<Uuid> {
    let identity = crate::python_json::digest(&json!({
        "company":folded(&request.company),"title":folded(&request.title),
    }));
    let exists: bool = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM jobs j LEFT JOIN companies c ON c.id=j.company_id
         WHERE j.content_identity=$1 OR (lower(j.title)=lower($2) AND lower(c.name)=lower($3)))",
    )
    .bind(&identity)
    .bind(&request.title)
    .bind(&request.company)
    .fetch_one(&mut **tx)
    .await
    .map_err(db)?;
    if exists {
        return Err(CONFLICT);
    }
    let companies: Vec<Uuid> =
        sqlx::query_scalar("SELECT id FROM companies WHERE name=$1 ORDER BY id LIMIT 2")
            .bind(&request.company)
            .fetch_all(&mut **tx)
            .await
            .map_err(db)?;
    let company = match companies.as_slice() {
        [company] => *company,
        [] => sqlx::query_scalar("INSERT INTO companies(id,name) VALUES ($1,$2) RETURNING id")
            .bind(Uuid::new_v4())
            .bind(&request.company)
            .fetch_one(&mut **tx)
            .await
            .map_err(db)?,
        _ => return Err(CONFLICT),
    };
    let job = sqlx::query_scalar("INSERT INTO jobs(id,company_id,title,job_url,application_url,source_platform,
        status,skills_required,is_remote,remote_type,canonical_key,content_identity,source_verification_status,discovery_metadata)
        VALUES ($1,$2,$3,$4,$4,'owner_extension','discovered',ARRAY[]::text[],false,'unknown',$4,$5,'owner_selected',$6)
        ON CONFLICT DO NOTHING RETURNING id")
        .bind(Uuid::new_v4()).bind(company).bind(&request.title).bind(&request.url).bind(&identity)
        .bind(json!({"capture":"owner_pasted_application_url","employer_identity_verified":false}))
        .fetch_optional(&mut **tx).await.map_err(db)?;
    job.ok_or(CONFLICT)
}

pub(super) async fn prepare_in(
    tx: &mut Transaction<'_, Postgres>,
    request: &Intake,
    settings: &Settings,
    answers: &answer_service::Settings,
    now: DateTime<Utc>,
) -> Result<Value> {
    execution::lock_owner_with_error_in(tx, db).await?;
    let job = match saved_job(tx, request).await? {
        Some(job) => job,
        None => create_job(tx, request).await?,
    };
    let packet = create_locked_in(tx, job, &request.preparation, settings, answers, now).await?;
    let snapshot = &packet["snapshot"];
    if snapshot["destination"]["application_url"].as_str() != Some(request.url.as_str())
        || snapshot["job_title"].as_str() != Some(request.title.as_str())
        || snapshot["company_name"].as_str() != Some(request.company.as_str())
    {
        return Err(CONFLICT);
    }
    Ok(packet)
}
