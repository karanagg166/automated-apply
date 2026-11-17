//! Retained public observations and monotonic provider cooldowns, never application authority.
use super::{
    access::{self, Claim},
    plan::Source,
    transport::Outcome,
};
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::PgConnection;
fn invalid() -> Failure {
    Failure("invalid_public_job_finding")
}
fn db(_: sqlx::Error) -> Failure {
    Failure("public_job_database_error")
}
fn ack() -> Failure {
    Failure("public_job_write_ack_failed")
}
fn code(value: &Value) -> Result<&str> {
    value
        .as_str()
        .filter(|s| {
            matches!(
                *s,
                "public_job_record_invalid"
                    | "public_job_inconsistent_duplicate"
                    | "public_job_batch_result_limit"
                    | "public_job_response_schema_invalid"
                    | "public_job_batch_request_limit"
                    | "public_job_batch_timeout"
                    | "public_job_transport_unconfirmed"
                    | "public_job_provider_authentication_required"
                    | "public_job_provider_rate_limited"
                    | "public_job_cooldown_requires_review"
                    | "public_job_http_unavailable"
                    | "public_job_response_limit"
                    | "public_job_json_invalid"
                    | "public_job_json_required"
                    | "public_job_original_grant_expired"
                    | "public_job_original_grant_changed"
                    | "public_job_target_denied"
                    | "invalid_public_job_request_plan"
            )
        })
        .ok_or_else(invalid)
}
fn count(value: &Value, max: u64) -> Result<u64> {
    value.as_u64().filter(|n| *n <= max).ok_or_else(invalid)
}
pub(super) fn project(
    value: &Value,
    source: Source,
    query: &Value,
    now: DateTime<Utc>,
) -> Result<Value> {
    if value.to_string().len() > 9437184
        || value["source"] != source.name()
        || value["application_dispatch"] != false
        || value["live_verified"] != false
    {
        return Err(invalid());
    }
    let at = access::time(&value["observed_at"])?;
    if at > now + chrono::Duration::minutes(5) {
        return Err(invalid());
    }
    let status = value["status"]
        .as_str()
        .filter(|s| {
            matches!(
                *s,
                "success"
                    | "partial"
                    | "no_results"
                    | "upstream_error"
                    | "authentication_required"
                    | "rate_limited"
                    | "outcome_unknown"
                    | "not_dispatched"
            )
        })
        .ok_or_else(invalid)?;
    let state = value["transport_state"]
        .as_str()
        .filter(|s| {
            matches!(
                *s,
                "completed"
                    | "upstream_error"
                    | "authentication_required"
                    | "rate_limited"
                    | "outcome_unknown"
                    | "not_dispatched"
            )
        })
        .ok_or_else(invalid)?;
    let complete = value["batch_complete"].as_bool().ok_or_else(invalid)?;
    if complete != (state == "completed") {
        return Err(invalid());
    }
    let limit = query["limit"].as_u64().ok_or_else(invalid)?;
    let rows = value["jobs"]
        .as_array()
        .filter(|a| a.len() as u64 <= limit)
        .ok_or_else(invalid)?;
    let rejected = count(&value["rejected_count"], 200)?;
    let duplicates = count(&value["duplicate_count"], 100)?;
    let attempts = count(&value["provider_http_attempts"], 110)?;
    let responses = count(&value["provider_responses_observed"], attempts)?;
    let bytes = count(&value["decoded_bytes"], 33554432)?;
    let expected = if complete {
        if rejected > 0 {
            if rows.is_empty() {
                "upstream_error"
            } else {
                "partial"
            }
        } else if rows.is_empty() {
            "no_results"
        } else {
            "success"
        }
    } else if rows.is_empty() {
        state
    } else {
        "partial"
    };
    if expected != status
        || state == "not_dispatched" && (attempts != 0 || responses != 0 || !rows.is_empty())
    {
        return Err(invalid());
    }
    let errors = value["errors"]
        .as_array()
        .filter(|a| a.len() <= 30)
        .ok_or_else(invalid)?
        .iter()
        .map(code)
        .collect::<Result<Vec<_>>>()?;
    if !complete && errors.is_empty() {
        return Err(invalid());
    }
    let cursor = match value.get("next_cursor") {
        None | Some(Value::Null) => Value::Null,
        Some(Value::String(s))
            if query["page"]
                .as_u64()
                .is_some_and(|p| p < 100 && s == (p + 1).to_string().as_str()) =>
        {
            json!(s)
        }
        _ => return Err(invalid()),
    };
    let mut jobs = Vec::new();
    for row in rows {
        let mut job = super::contract::normalize(row.clone(), at).map_err(|_| invalid())?;
        if job["source_name"] != source.name()
            || job["source_verification_status"]
                != if source == Source::HackerNews {
                    "observed"
                } else {
                    "source_reported"
                }
            || job["company_intelligence"] != json!({})
        {
            return Err(invalid());
        }
        let provenance = job["data_provenance"].as_object().ok_or_else(invalid)?;
        let mut selected = serde_json::Map::new();
        for field in [
            "adapter",
            "board_token",
            "updated_at",
            "company_name_basis",
            "publication_basis",
            "attribution",
            "attribution_url",
            "feed_delay_hours",
            "page",
            "public_posting_id",
            "story_id",
            "story_title",
        ] {
            if let Some(v) = provenance.get(field) {
                let valid = match field {
                    "page" => v.as_u64().is_some_and(|n| (1..=100).contains(&n)),
                    "feed_delay_hours" => v.as_u64() == Some(24),
                    "updated_at" => {
                        v.is_null()
                            || v.as_str().is_some_and(|s| {
                                s.len() <= 100 && DateTime::parse_from_rfc3339(s).is_ok()
                            })
                    }
                    "adapter" => {
                        v.as_str()
                            == Some(match source {
                                Source::Greenhouse => "GreenhouseAdapter",
                                Source::Lever => "LeverAdapter",
                                Source::Ashby => "AshbyAdapter",
                                Source::Smartrecruiters => "SmartRecruitersAdapter",
                                Source::Remotive => "RemotiveAdapter",
                                Source::Arbeitnow => "ArbeitnowAdapter",
                                Source::HackerNews => "HackerNewsHiringAdapter",
                            })
                    }
                    _ => v.as_str().is_some_and(|s| s.len() <= 2000),
                };
                if !valid {
                    return Err(invalid());
                }
                selected.insert(field.to_owned(), v.clone());
            }
        }
        job["data_provenance"] = Value::Object(selected);
        jobs.push(job);
    }
    Ok(
        json!({"source":source.name(),"status":status,"transport_state":state,"batch_complete":complete,"jobs":jobs,"errors":errors,"cooldown_requires_review":errors.contains(&"public_job_cooldown_requires_review"),"rejected_count":rejected,"duplicate_count":duplicates,"next_cursor":cursor,"provider_http_attempts":attempts,"provider_responses_observed":responses,"decoded_bytes":bytes,"observed_at":value["observed_at"],"application_dispatch":false,"live_verified":false}),
    )
}
pub(super) async fn retain(c: &mut PgConnection, claim: Claim, outcome: Outcome) -> Result<Value> {
    if claim.grant.is_some()
        || claim.id != outcome.request
        || claim.journal["invocation_id"] != json!(outcome.invocation)
        || claim.journal["configuration_hash"] != outcome.configuration
    {
        return Err(Failure("public_job_finding_context_changed"));
    }
    let mut tx = access::transaction(c).await?;
    let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let source = Source::parse(claim.journal["source"].as_str().ok_or_else(invalid)?)?;
    let finding = project(&outcome.finding, source, &claim.journal["query"], now)?;
    let saved = access::load_in(&mut tx, claim.id)
        .await?
        .ok_or_else(invalid)?;
    if saved != claim.journal {
        return Err(Failure("public_job_finding_context_changed"));
    }
    let mut next = claim.journal.clone();
    next["state"] = json!("finding_retained");
    next["finding_hash"] = json!(crate::python_json::digest(&finding));
    next["finding"] = finding;
    let pace: Option<DateTime<Utc>> =
        sqlx::query_scalar("SELECT next_allowed_at FROM provider_access_windows WHERE provider=$1")
            .bind(source.name())
            .fetch_optional(&mut *tx)
            .await
            .map_err(db)?;
    let pace = pace.ok_or_else(invalid)?;
    let expected = if let Some(until) = outcome.cooldown {
        if next["finding"]["transport_state"] != "rate_limited" {
            return Err(invalid());
        }
        let expected = pace.max(until);
        let updated:Option<DateTime<Utc>>=sqlx::query_scalar("UPDATE provider_access_windows SET next_allowed_at=GREATEST(next_allowed_at,$2) WHERE provider=$1 RETURNING next_allowed_at").bind(source.name()).bind(until).fetch_optional(&mut *tx).await.map_err(db)?;
        if updated != Some(expected) {
            return Err(ack());
        }
        expected
    } else {
        if next["finding"]["transport_state"] == "rate_limited" {
            return Err(invalid());
        }
        pace
    };
    let updated:Option<Value>=sqlx::query_scalar("UPDATE owner_preferences SET value=$2,updated_at=clock_timestamp() WHERE key=$1 AND value=$3 RETURNING value").bind(access::key(claim.id)).bind(&next).bind(&claim.journal).fetch_optional(&mut *tx).await.map_err(db)?;
    if updated.as_ref() != Some(&next)
        || access::load_in(&mut tx, claim.id).await?.as_ref() != Some(&next)
    {
        return Err(ack());
    }
    let actual: Option<DateTime<Utc>> =
        sqlx::query_scalar("SELECT next_allowed_at FROM provider_access_windows WHERE provider=$1")
            .bind(source.name())
            .fetch_optional(&mut *tx)
            .await
            .map_err(db)?;
    if actual != Some(expected) {
        return Err(ack());
    }
    let out = access::visible(&next, claim.id, now)?;
    tx.commit()
        .await
        .map_err(|_| Failure("public_job_commit_outcome_unknown"))?;
    Ok(out)
}
