//! Separate bounded preparation authority. It cannot change the application queue's submission policy.
use super::{
    contracts::{self, Kind},
    fences, review,
    storage::*,
};
use crate::{Failure, Result, resources};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;

pub(super) async fn record(tx: &mut Transaction<'_, Postgres>) -> Result<Value> {
    let value = get(tx, "naukri_automation")
        .await?
        .unwrap_or(json!({"state":"STOPPED","revision":0,"policy":null}));
    revision(&value)?;
    if !matches!(
        value["state"].as_str(),
        Some("STOPPED" | "PAUSED" | "RUNNING")
    ) {
        return Err(invalid());
    }
    Ok(value)
}
pub(super) async fn configuration(tx: &mut Transaction<'_, Postgres>) -> Result<Value> {
    contracts::normalize(
        Kind::Configuration,
        get(tx, "exec_config:naukri").await?.unwrap_or(json!({})),
    )
    .map_err(|_| invalid())
}
pub(super) async fn enabled(tx: &mut Transaction<'_, Postgres>) -> Result<()> {
    let value = record(tx).await?;
    if revision(&value)? > 0 && value["state"] != "RUNNING" {
        return Err(Failure(if value["state"] == "PAUSED" {
            "naukri_automation_paused"
        } else {
            "naukri_automation_stopped"
        }));
    }
    if configuration(tx).await?["mode"] == "OFF" {
        return Err(Failure("execution_mode_off"));
    }
    Ok(())
}
pub(super) async fn validate_in(tx: &mut Transaction<'_, Postgres>, policy: &Value) -> Result<()> {
    validate_snapshot_in(tx, policy, true).await
}
pub(super) async fn validate_read_in(
    tx: &mut Transaction<'_, Postgres>,
    policy: &Value,
) -> Result<()> {
    validate_snapshot_in(tx, policy, false).await
}
async fn validate_snapshot_in(
    tx: &mut Transaction<'_, Postgres>,
    policy: &Value,
    locked: bool,
) -> Result<()> {
    if policy["source"] == "gmail_job_alerts" {
        return Err(Failure("gmail_intake_deferred_to_phase54"));
    }
    let profile = if locked {
        super::preflight::profile_in(tx, &json!({"profile_version":policy["profile_version"]}))
            .await
            .map_err(|e| {
                if e.0 == "verified_profile_context_changed" {
                    Failure("confirmed_profile_version_required")
                } else {
                    e
                }
            })?
    } else {
        let profile = crate::profile_store::get(tx)
            .await
            .map_err(|e| {
                if e.0 == "profile_not_found" {
                    Failure("confirmed_profile_version_required")
                } else {
                    e
                }
            })?
            .value;
        let confirmation = get(tx, "phase1_profile_confirmation")
            .await?
            .unwrap_or(Value::Null);
        if profile["version"] != policy["profile_version"]
            || confirmation["profile_id"] != profile["id"]
            || confirmation["profile_version"] != profile["version"]
            || confirmation["confirmed_at"]
                .as_str()
                .is_none_or(str::is_empty)
        {
            return Err(Failure("confirmed_profile_version_required"));
        }
        profile
    };
    let rows:Vec<Value>=sqlx::query_scalar("SELECT to_jsonb(r) FROM candidate_resources r WHERE candidate_profile_id=$1 ORDER BY id LIMIT 10001").bind(profile["id"].as_str().and_then(|s|s.parse::<Uuid>().ok()).ok_or_else(invalid)?).fetch_all(&mut **tx).await.map_err(db)?;
    if rows.len() > 10000 {
        return Err(Failure("execution_active_inventory_limit"));
    }
    let rows = rows
        .into_iter()
        .map(|v| serde_json::from_value::<resources::Resource>(v).map_err(|_| invalid()))
        .collect::<Result<Vec<_>>>()?;
    let selected = resources::select_resume(&rows, None)?
        .selected
        .ok_or(Failure("approved_primary_resume_changed_or_missing"))?;
    if policy["resume_resource_id"] != selected.resource_id.to_string()
        || policy["resume_version"] != selected.resource_version
    {
        return Err(Failure("approved_primary_resume_changed_or_missing"));
    }
    if profile["verified_experience_years"]
        .as_f64()
        .is_none_or(|y| {
            policy["experience_min"].as_f64().is_none_or(|a| y < a)
                || policy["experience_max"].as_f64().is_none_or(|b| y > b)
        })
    {
        return Err(Failure("verified_experience_outside_policy"));
    }
    Ok(())
}
pub fn reason(
    job: &Value,
    decision: &Value,
    policy: &Value,
    now: DateTime<Utc>,
) -> Result<Option<String>> {
    let no = |s: &str| Ok(Some(s.to_owned()));
    if decision["state"] != "ELIGIBLE" {
        return no(decision["reason"].as_str().ok_or_else(invalid)?);
    }
    let folded = automated_apply_domain::text::folded;
    let contains = |key: &str, label: &str| {
        policy[key]
            .as_array()
            .is_some_and(|a| a.iter().any(|s| s.as_str() == Some(folded(label).as_str())))
    };
    if !contains(
        "allowed_roles",
        decision["title"].as_str().ok_or_else(invalid)?,
    ) {
        return no("role_outside_policy");
    }
    if contains(
        "excluded_companies",
        decision["employer"].as_str().unwrap_or(""),
    ) {
        return no("excluded_company");
    }
    let meta = &job["discovery_metadata"];
    let location = meta["location"]
        .as_str()
        .filter(|s| !s.is_empty())
        .or_else(|| job["location"].as_str())
        .unwrap_or("");
    if !contains("allowed_locations", location) {
        return no("location_outside_policy");
    }
    let lower = meta["experience_min_years"].as_f64();
    let upper = meta["experience_max_years"].as_f64();
    if meta["data_provenance"]["experience_requirement"] != "required"
        || lower.is_none()
        || upper.is_none()
    {
        return no("required_experience_band_unknown");
    }
    if lower.unwrap() < policy["experience_min"].as_f64().ok_or_else(invalid)?
        || upper.unwrap() > policy["experience_max"].as_f64().ok_or_else(invalid)?
    {
        return no("job_experience_band_outside_policy");
    }
    let posted = match timestamp(&meta["date_posted"]) {
        Ok(p) => p,
        Err(_) => return no("posting_date_required"),
    };
    if posted > now
        || now - posted
            > chrono::Duration::days(
                policy["max_posting_age_days"]
                    .as_i64()
                    .ok_or_else(invalid)?,
            )
    {
        return no("posting_outside_freshness_policy");
    }
    let fit = &decision["match"];
    if meta["skills_required"].as_array().is_none_or(Vec::is_empty)
        || fit["missing_skills"]
            .as_array()
            .is_none_or(|a| !a.is_empty())
        || fit["match_score"]
            .as_f64()
            .is_none_or(|s| s < policy["minimum_match_score"].as_f64().unwrap_or(101.))
        || fit["negative_factors"]
            .as_array()
            .is_none_or(|a| !a.is_empty())
    {
        return no("strict_skill_or_preference_match_required");
    }
    if fit["unknown_fields"]
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .any(|v| {
            !matches!(
                v.as_str(),
                Some("experience_suitability" | "company_size" | "salary")
            )
        })
    {
        return no("uncertain_match_requires_review");
    }
    Ok(None)
}
pub(super) async fn execution_in(
    tx: &mut Transaction<'_, Postgres>,
    intent: &Value,
    now: DateTime<Utc>,
) -> Result<Option<i64>> {
    if intent.get("automation_revision").is_none() {
        return Ok(None);
    }
    let value = record(tx).await?;
    let policy = contracts::normalize(Kind::AutomationPolicy, value["policy"].clone())
        .map_err(|_| invalid())?;
    validate_in(tx, &policy).await?;
    let id = intent["job_id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    let job: Value = sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1")
        .bind(id)
        .fetch_optional(&mut **tx)
        .await
        .map_err(db)?
        .ok_or(Failure("saved_naukri_job_required"))?;
    let decision = review::jobs_in(tx, Some(id), now)
        .await?
        .into_iter()
        .next()
        .ok_or(Failure("saved_naukri_job_required"))?;
    if let Some(reason) = reason(&job, &decision, &policy, now)? {
        return Err(policy_denial(&reason));
    }
    Ok(Some(revision(&value)?))
}
fn policy_denial(reason: &str) -> Failure {
    // Stable public codes only; never leak a malformed saved string into logs/HTTP.
    Failure(match reason {
        "role_outside_policy" => "role_outside_policy",
        "excluded_company" => "excluded_company",
        "location_outside_policy" => "location_outside_policy",
        "required_experience_band_unknown" => "required_experience_band_unknown",
        "job_experience_band_outside_policy" => "job_experience_band_outside_policy",
        "posting_date_required" => "posting_date_required",
        "posting_outside_freshness_policy" => "posting_outside_freshness_policy",
        "strict_skill_or_preference_match_required" => "strict_skill_or_preference_match_required",
        "uncertain_match_requires_review" => "uncertain_match_requires_review",
        "invalid_requisition_identity" => "invalid_requisition_identity",
        "vacancy_closed_expired_or_invalid" => "vacancy_closed_expired_or_invalid",
        "previous_application_or_owner_exclusion" => "previous_application_or_owner_exclusion",
        "required_experience_outside_verified_band" => "required_experience_outside_verified_band",
        "required_experience_unknown" => "required_experience_unknown",
        "fit_requires_owner_review" => "fit_requires_owner_review",
        "experience_suitability_unknown" => "experience_suitability_unknown",
        "confirmed_profile_required" => "confirmed_profile_required",
        "current_vacancy_requires_owner_review" => "current_vacancy_requires_owner_review",
        "closed" => "closed",
        "expired" => "expired",
        "invalid_evidence" => "invalid_evidence",
        "already_applied" => "already_applied",
        _ => "invalid_execution_saved_record",
    })
}
pub(super) async fn configure_in(
    tx: &mut Transaction<'_, Postgres>,
    data: Value,
    telegram: bool,
    now: DateTime<Utc>,
) -> Result<Value> {
    let mut value = record(tx).await?;
    if value["revision"] != data["expected_revision"] {
        return Err(Failure("automation_revision_conflict"));
    }
    validate_in(tx, &data["policy"]).await?;
    if data["policy"]["telegram_questions"] == true && !telegram {
        return Err(Failure("approved_telegram_channel_required"));
    }
    fences::legacy(tx, "global_stop", now).await?;
    value["state"] = json!("STOPPED");
    value["revision"] = json!(next(&value)?);
    value["policy"] = data["policy"].clone();
    value["next_check_at"] = Value::Null;
    put(tx, "naukri_automation", &value).await?;
    Ok(value)
}
pub(super) async fn control_in(
    tx: &mut Transaction<'_, Postgres>,
    data: Value,
    now: DateTime<Utc>,
) -> Result<Value> {
    let mut value = record(tx).await?;
    if value["revision"] != data["expected_revision"] {
        return Err(Failure("automation_revision_conflict"));
    }
    let state = if data["action"] == "start" {
        if value["policy"].is_null() {
            return Err(Failure("bounded_preparation_policy_required"));
        }
        let policy = contracts::normalize(Kind::AutomationPolicy, value["policy"].clone())
            .map_err(|_| invalid())?;
        validate_in(tx, &policy).await?;
        if value["state"] == "RUNNING" {
            return Ok(value);
        }
        let mut config = configuration(tx).await?;
        if config["mode"] == "OFF" {
            config["mode"] = json!("ON_DEMAND");
            put(tx, "exec_config:naukri", &config).await?;
        }
        "RUNNING"
    } else {
        fences::legacy(
            tx,
            if data["action"] == "stop" {
                "global_stop"
            } else {
                "owner_pause"
            },
            now,
        )
        .await?;
        if data["action"] == "pause" {
            "PAUSED"
        } else {
            "STOPPED"
        }
    };
    value["state"] = json!(state);
    value["revision"] = json!(next(&value)?);
    value["controlled_at"] = json!(stamp(now));
    for key in [
        "next_check_at",
        "source_next_at",
        "source_lease",
        "source_lease_until",
    ] {
        value[key] = Value::Null;
    }
    put(tx, "naukri_automation", &value).await?;
    Ok(value)
}
