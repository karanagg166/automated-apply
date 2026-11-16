//! Read-only owner-import review; saved facts and retained evidence confer no browser authority.
use super::{filters, storage::*};
use crate::{Failure, Result, job_context::Reviewed};
use automated_apply_domain::matching::{self, Company, Listing, Profile};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use std::collections::HashSet;
use uuid::Uuid;

pub fn vacancy(job: &Value, now: DateTime<Utc>) -> Result<&'static str> {
    let evidence = &job["discovery_metadata"]["data_provenance"];
    if let Some(deadline) = evidence["valid_through"].as_str() {
        let Ok(date) = chrono::NaiveDate::parse_from_str(deadline, "%Y-%m-%d") else {
            return Ok("invalid_evidence");
        };
        if date < now.date_naive() {
            return Ok("expired");
        }
    }
    if crate::packet_platform::posting_unavailable(job, now.date_naive())? {
        return Ok("closed");
    }
    if evidence["posting_status"] == "already_applied" {
        return Ok("already_applied");
    }
    let Ok(observed) = timestamp(&evidence["owner_observed_at"]) else {
        return Ok("unverified");
    };
    if observed > now + chrono::Duration::minutes(5) {
        return Ok("unverified");
    }
    if now - observed > chrono::Duration::hours(24) {
        return Ok("stale");
    }
    Ok(if evidence["posting_status"] == "active" {
        "owner_observed_active"
    } else {
        "unverified"
    })
}
pub fn decision(
    job: Value,
    company: Option<Value>,
    profile: Option<&Value>,
    confirmed: bool,
    prior: bool,
    now: DateTime<Utc>,
) -> Result<Value> {
    if job["job_url"]
        .as_str()
        .is_none_or(|u| filters::naukri_url(u).is_err())
    {
        return Ok(
            json!({"id":job["id"],"title":job["title"],"job_url":job["job_url"],"employer":null,"state":"REJECTED","reason":"invalid_requisition_identity","match":null,"submission_allowed":false}),
        );
    }
    let reviewed = Reviewed::new(job, company)?;
    let job = reviewed.job_view();
    let currentness = if prior {
        "already_applied"
    } else {
        vacancy(job, now)?
    };
    let mut view = job.clone();
    if job["discovery_metadata"]["source_name"] == "naukri" {
        view["is_remote"] = json!(view["remote_type"] == "remote");
        view["date_posted"] =
            if crate::packet_context::date_present(&job["discovery_metadata"]["date_posted"]) {
                job["discovery_metadata"]["date_posted"].clone()
            } else {
                Value::Null
            };
    }
    for key in ["salary_min", "salary_max"] {
        if let Some(raw) = view[key].as_str() {
            view[key] = json!(
                raw.parse::<f64>()
                    .ok()
                    .filter(|n| n.is_finite())
                    .ok_or_else(invalid)?
            );
        }
    }
    if view["skills_required"].is_null() {
        view["skills_required"] = json!([]);
    }
    if view["remote_type"].is_null() {
        view["remote_type"] = json!("unknown");
    }
    if view["is_remote"].is_null() {
        view["is_remote"] = json!(false);
    }
    let fit = if let Some(profile) = profile {
        let listing: Listing = serde_json::from_value(view).map_err(|_| invalid())?;
        let candidate: Profile = serde_json::from_value(profile.clone()).map_err(|_| invalid())?;
        let company = reviewed.employer().map(|c| Company {
            name: c["name"].as_str().unwrap_or("").into(),
            domain: c["domain"].as_str().map(str::to_owned),
            startup_stage: c["metadata_"]["startup_discovery"]["stage"]
                .as_str()
                .map(str::to_owned),
            startup_source: c["metadata_"]["startup_discovery"]["source"]
                .as_str()
                .map(str::to_owned),
        });
        Some(matching::discovery_match(
            &listing,
            &candidate,
            company.as_ref(),
            false,
        ))
    } else {
        None
    };
    let (mut state, mut reason) = ("NEEDS_INPUT", "candidate_profile_missing");
    if let Some(fit) = &fit {
        let required =
            job["discovery_metadata"]["data_provenance"]["experience_requirement"] == "required";
        let lower = job["discovery_metadata"]["experience_min_years"].as_f64();
        let upper = job["discovery_metadata"]["experience_max_years"].as_f64();
        let years = profile.and_then(|p| p["verified_experience_years"].as_f64());
        (state, reason) = if crate::packet_platform::posting_unavailable(job, now.date_naive())? {
            ("REJECTED", "vacancy_closed_expired_or_invalid")
        } else if !fit.exclusion_reasons.is_empty() {
            ("REJECTED", "previous_application_or_owner_exclusion")
        } else if required
            && lower
                .zip(years)
                .is_some_and(|(l, y)| y < l || upper.is_some_and(|u| y > u))
        {
            ("REJECTED", "required_experience_outside_verified_band")
        } else if required && (lower.is_none() || years.is_none()) {
            ("NEEDS_INPUT", "required_experience_unknown")
        } else if fit.matched_skills.is_empty()
            || fit.match_score < 50.
            || !fit.missing_skills.is_empty()
        {
            ("NEEDS_INPUT", "fit_requires_owner_review")
        } else if lower.is_none() || years.is_none() {
            ("NEEDS_INPUT", "experience_suitability_unknown")
        } else {
            ("ELIGIBLE", "preparation_only_owner_review_required")
        };
    }
    if !confirmed {
        (state, reason) = ("NEEDS_INPUT", "confirmed_profile_required");
    }
    if matches!(
        currentness,
        "closed" | "expired" | "invalid_evidence" | "already_applied"
    ) {
        (state, reason) = ("REJECTED", currentness);
    } else if state == "ELIGIBLE" && currentness != "owner_observed_active" {
        (state, reason) = ("NEEDS_INPUT", "current_vacancy_requires_owner_review");
    }
    Ok(
        json!({"id":job["id"],"title":job["title"],"job_url":job["job_url"],"employer":reviewed.employer().map(|c|c["name"].clone()),"profile_version":profile.map(|p|p["version"].clone()),"profile_confirmed":confirmed,"vacancy_review":currentness,"provider_verified":false,"state":state,"reason":reason,"match":fit,"submission_allowed":false}),
    )
}
/// One bounded job/company query and one history summary, regardless of listing count.
pub(super) async fn jobs_in(
    tx: &mut Transaction<'_, Postgres>,
    selected: Option<Uuid>,
    now: DateTime<Utc>,
) -> Result<Vec<Value>> {
    let rows:Vec<(Value,Option<Value>)>=sqlx::query_as("SELECT to_jsonb(j),CASE WHEN c.id IS NULL THEN NULL ELSE jsonb_set(to_jsonb(c),'{metadata_}',coalesce(c.metadata,'{}'::jsonb)) END FROM jobs j LEFT JOIN companies c ON c.id=j.company_id WHERE j.source_platform='naukri' AND ($1::uuid IS NULL OR j.id=$1) ORDER BY j.created_at DESC,j.id LIMIT 100").bind(selected).fetch_all(&mut **tx).await.map_err(db)?;
    let profile = match crate::profile_store::get(tx).await {
        Ok(p) => Some(p.value),
        Err(Failure("profile_not_found")) => None,
        Err(e) => return Err(e),
    };
    let confirmation = get(tx, "phase1_profile_confirmation")
        .await?
        .unwrap_or(Value::Null);
    let confirmed = profile.as_ref().is_some_and(|p| {
        confirmation["profile_id"] == p["id"]
            && confirmation["profile_version"] == p["version"]
            && confirmation["confirmed_at"]
                .as_str()
                .is_some_and(|s| !s.is_empty())
    });
    let urls = rows
        .iter()
        .filter_map(|(j, _)| {
            j["job_url"]
                .as_str()
                .and_then(|u| filters::naukri_url(u).ok())
        })
        .collect::<Vec<_>>();
    let reqs = urls
        .iter()
        .filter_map(|u| u.rsplit('-').next())
        .map(str::to_owned)
        .collect::<Vec<_>>();
    let ids = rows
        .iter()
        .filter_map(|(j, _)| j["id"].as_str().and_then(|s| s.parse::<Uuid>().ok()))
        .collect::<Vec<_>>();
    let prior:Vec<String>=sqlx::query_scalar("SELECT 'id:'||j.id::text FROM application_packets p JOIN jobs j ON j.id=p.job_id WHERE p.lifecycle_state IN ('user_reported_submitted','provider_confirmed_submitted','submitting','submission_unknown') AND j.id=ANY($1) UNION SELECT 'url:'||j.job_url FROM application_packets p JOIN jobs j ON j.id=p.job_id WHERE p.lifecycle_state IN ('user_reported_submitted','provider_confirmed_submitted','submitting','submission_unknown') AND j.source_platform='naukri' AND substring(j.job_url from '-([0-9]{10,20})/?(?:[?#].*)?$')=ANY($2) UNION SELECT 'req:'||split_part(key,':',2) FROM owner_preferences WHERE key=ANY($3)").bind(ids).bind(&reqs).bind(reqs.iter().flat_map(|r|[format!("naukri_receipt:{r}"),format!("naukri_worker_receipt:{r}")]).collect::<Vec<_>>()).fetch_all(&mut **tx).await.map_err(db)?;
    let prior = prior
        .into_iter()
        .filter_map(|entry| {
            if let Some(url) = entry.strip_prefix("url:") {
                filters::naukri_url(url)
                    .ok()
                    .and_then(|url| url.rsplit('-').next().map(|req| format!("req:{req}")))
            } else {
                Some(entry)
            }
        })
        .collect::<HashSet<_>>();
    rows.into_iter()
        .map(|(j, c)| {
            let retained = j["id"]
                .as_str()
                .is_some_and(|s| prior.contains(&format!("id:{s}")))
                || j["job_url"]
                    .as_str()
                    .and_then(|u| filters::naukri_url(u).ok())
                    .and_then(|u| u.rsplit('-').next().map(str::to_owned))
                    .is_some_and(|r| prior.contains(&format!("req:{r}")))
                || j["discovery_metadata"]["data_provenance"]["posting_status"]
                    == "already_applied"
                || matches!(j["status"].as_str(), Some("applied" | "submitted"))
                || matches!(
                    j["application_status"].as_str(),
                    Some(
                        "applied"
                            | "submitted"
                            | "interview"
                            | "offer"
                            | "applied_manually"
                            | "applied_verified"
                    )
                );
            decision(j, c, profile.as_ref(), confirmed, retained, now)
        })
        .collect()
}
