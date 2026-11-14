//! Existing owner draft listing/review. Reviewing text grants no application admission.
use crate::{Failure, Result};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::Deserialize;
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Row};
use uuid::Uuid;
#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ReviewStatus {
    Draft,
    Reviewed,
    Discarded,
}
impl ReviewStatus {
    fn value(&self) -> &'static str {
        match self {
            Self::Draft => "draft",
            Self::Reviewed => "reviewed",
            Self::Discarded => "discarded",
        }
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Review {
    pub review_status: ReviewStatus,
}
fn invalid() -> Failure {
    Failure("invalid_answer_draft_record")
}
fn db(_: sqlx::Error) -> Failure {
    Failure("profile_database_error")
}
fn text(value: &Value) -> Result<String> {
    Ok(value.as_str().ok_or_else(invalid)?.trim().into())
}
pub fn record(row: Value, version: i32) -> Result<Value> {
    if [
        "id",
        "candidate_profile_id",
        "job_id",
        "question",
        "answer",
        "question_category",
        "writing_style",
        "provider",
        "model",
        "evidence_references",
        "candidate_profile_version",
        "review_status",
        "created_at",
        "updated_at",
    ]
    .iter()
    .any(|key| row.get(*key).is_none())
    {
        return Err(invalid());
    }
    let mut out = json!({});
    for key in ["id", "candidate_profile_id"] {
        out[key] = json!(
            row[key]
                .as_str()
                .and_then(|s| s.parse::<Uuid>().ok())
                .ok_or_else(invalid)?
        );
    }
    out["job_id"] = if row["job_id"].is_null() {
        Value::Null
    } else {
        json!(
            row["job_id"]
                .as_str()
                .and_then(|s| s.parse::<Uuid>().ok())
                .ok_or_else(invalid)?
        )
    };
    for key in [
        "question",
        "answer",
        "question_category",
        "writing_style",
        "review_status",
    ] {
        out[key] = json!(text(&row[key])?);
    }
    if ![
        "profile_link",
        "personal_details",
        "short_text",
        "project_explanation",
        "technical_experience",
        "motivation",
        "startup_interest",
        "work_authorization",
        "compensation",
        "file_upload",
        "unknown",
    ]
    .contains(&row["question_category"].as_str().unwrap())
        || ![
            "professional",
            "conversational",
            "technical",
            "concise",
            "founder_focused",
        ]
        .contains(&row["writing_style"].as_str().unwrap())
        || !["draft", "reviewed", "discarded"].contains(&row["review_status"].as_str().unwrap())
    {
        return Err(invalid());
    }
    for key in ["provider", "model"] {
        out[key] = if row[key].is_null() {
            Value::Null
        } else {
            json!(text(&row[key])?)
        };
    }
    let original = row["candidate_profile_version"]
        .as_i64()
        .ok_or_else(invalid)?;
    out["candidate_profile_version"] = json!(original);
    out["stale"] = json!(original != i64::from(version));
    let mut references = Vec::new();
    for item in row["evidence_references"].as_array().ok_or_else(invalid)? {
        let object = item.as_object().ok_or_else(invalid)?;
        if object.len() != 2 {
            return Err(invalid());
        }
        let kind = item["source_type"].as_str().ok_or_else(invalid)?;
        if ![
            "owner_answer",
            "verified_project",
            "verified_role",
            "candidate_evidence",
            "candidate_profile",
            "candidate_preferences",
            "project_context",
            "opportunity_job",
            "opportunity_company",
        ]
        .contains(&kind)
        {
            return Err(invalid());
        }
        let id = text(&item["source_id"])?;
        if id.is_empty() || id.chars().count() > 100 {
            return Err(invalid());
        }
        references.push(json!({"source_type":kind,"source_id":id}));
    }
    out["evidence_references"] = json!(references);
    for key in ["created_at", "updated_at"] {
        let at = row[key]
            .as_str()
            .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
            .ok_or_else(invalid)?;
        out[key] = json!(at.with_timezone(&Utc).to_rfc3339_opts(
            if at.timestamp_subsec_micros() == 0 {
                SecondsFormat::Secs
            } else {
                SecondsFormat::Micros
            },
            true
        ));
    }
    Ok(out)
}
pub async fn list(connection: &mut PgConnection, offset: i64, limit: i64) -> Result<Value> {
    let mut transaction = connection.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *transaction)
        .await
        .map_err(db)?;
    let profile =
        sqlx::query("SELECT id,version FROM candidate_profiles WHERE singleton_key='primary'")
            .fetch_optional(&mut *transaction)
            .await
            .map_err(db)?
            .ok_or(Failure("profile_not_found"))?;
    let id: Uuid = profile.try_get("id").map_err(db)?;
    let version: i32 = profile.try_get("version").map_err(db)?;
    let rows:Vec<Value>=sqlx::query_scalar("SELECT to_jsonb(d) FROM (SELECT id,candidate_profile_id,job_id,question,answer,question_category,writing_style,provider,model,evidence_references,candidate_profile_version,review_status,created_at,updated_at FROM application_answer_drafts WHERE candidate_profile_id=$1 ORDER BY created_at DESC,id OFFSET $2 LIMIT $3) d").bind(id).bind(offset).bind(limit).fetch_all(&mut *transaction).await.map_err(db)?;
    let result = rows
        .into_iter()
        .map(|row| record(row, version))
        .collect::<Result<Vec<_>>>()?;
    transaction.commit().await.map_err(db)?;
    Ok(json!(result))
}
pub async fn review(connection: &mut PgConnection, id: Uuid, input: Review) -> Result<Value> {
    let mut transaction = connection.begin().await.map_err(db)?;
    // Pin the profile until the review commits. A concurrent correction cannot sneak past it.
    let profile = sqlx::query(
        "SELECT id,version FROM candidate_profiles WHERE singleton_key='primary' FOR SHARE",
    )
    .fetch_optional(&mut *transaction)
    .await
    .map_err(db)?
    .ok_or(Failure("profile_not_found"))?;
    let profile_id: Uuid = profile.try_get("id").map_err(db)?;
    let version: i32 = profile.try_get("version").map_err(db)?;
    let saved:i32=sqlx::query_scalar("SELECT candidate_profile_version FROM application_answer_drafts WHERE id=$1 AND candidate_profile_id=$2 FOR UPDATE").bind(id).bind(profile_id).fetch_optional(&mut *transaction).await.map_err(db)?.ok_or(Failure("answer_draft_not_found"))?;
    if matches!(input.review_status, ReviewStatus::Reviewed) && saved != version {
        return Err(Failure("answer_draft_stale"));
    }
    let row:Value=sqlx::query_scalar("UPDATE application_answer_drafts SET review_status=$3,updated_at=clock_timestamp() WHERE id=$1 AND candidate_profile_id=$2 RETURNING to_jsonb(application_answer_drafts.*)").bind(id).bind(profile_id).bind(input.review_status.value()).fetch_one(&mut *transaction).await.map_err(db)?;
    let result = record(row, version)?;
    transaction.commit().await.map_err(db)?;
    Ok(result)
}
