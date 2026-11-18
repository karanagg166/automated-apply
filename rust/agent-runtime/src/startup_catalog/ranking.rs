//! Explainable saved relevance weights. A score establishes no factual or application authority.
use crate::{Failure, Result};
use automated_apply_domain::{
    matching::{Company, Listing, Profile, discovery_match},
    text::folded,
};
use serde_json::{Value, json};
fn invalid() -> Failure {
    Failure("invalid_startup_ranking_record")
}
fn labels(value: &Value) -> Result<Vec<String>> {
    value
        .as_array()
        .filter(|a| a.len() <= 100)
        .ok_or_else(invalid)?
        .iter()
        .map(|v| {
            v.as_str()
                .filter(|s| s.chars().count() <= 400)
                .map(String::from)
                .ok_or_else(invalid)
        })
        .collect()
}
pub struct RankInput<'a> {
    pub company: &'a Value,
    pub jobs: &'a [Value],
    pub attributes: &'a Value,
    pub size: &'a Value,
    pub hiring: &'a Value,
    pub contacts: &'a [Value],
    pub profile: Option<&'a Value>,
    pub filters: &'a Value,
}
pub fn rank(input: RankInput<'_>) -> Result<Value> {
    let RankInput {
        company,
        jobs,
        attributes,
        size,
        hiring,
        contacts,
        profile,
        filters,
    } = input;
    if jobs.len() > 500
        || contacts.len() > 100
        || !attributes.is_object()
        || json!([
            company, jobs, attributes, size, hiring, contacts, profile, filters
        ])
        .to_string()
        .len()
            > 16 * 1024 * 1024
    {
        return Err(Failure("startup_ranking_inventory_limit"));
    }
    let name = company["name"]
        .as_str()
        .filter(|s| s.len() <= 1020)
        .ok_or_else(invalid)?;
    let domain = company["domain"].as_str();
    let meta = company
        .get("metadata_")
        .or_else(|| company.get("metadata"))
        .cloned()
        .unwrap_or(json!({}));
    if !meta.is_null() && !meta.is_object() {
        return Err(invalid());
    }
    let employer = Company {
        name: name.to_owned(),
        domain: domain.map(String::from),
        startup_stage: meta["startup_discovery"]["stage"]
            .as_str()
            .map(String::from),
        startup_source: meta["startup_discovery"]["source"]
            .as_str()
            .map(String::from),
    };
    let parsed = profile
        .map(|value| serde_json::from_value::<Profile>(value.clone()).map_err(|_| invalid()))
        .transpose()?;
    let mut listings = Vec::new();
    for job in jobs {
        let mut value = job.clone();
        if !value.is_object() {
            return Err(invalid());
        }
        for (key, fallback) in [
            ("remote_type", json!("unknown")),
            ("skills_required", json!([])),
            ("is_remote", json!(false)),
        ] {
            if value[key].is_null() {
                value[key] = fallback;
            }
        }
        listings.push(serde_json::from_value::<Listing>(value).map_err(|_| invalid())?);
    }
    let matches = if let Some(profile) = &parsed {
        listings
            .iter()
            .map(|job| discovery_match(job, profile, Some(&employer), false))
            .collect::<Vec<_>>()
    } else {
        vec![]
    };
    let eligible = matches
        .iter()
        .filter(|m| m.exclusion_reasons.is_empty())
        .collect::<Vec<_>>();
    let mut score = 0.0_f64;
    let mut reasons = Vec::new();
    let mut missing = Vec::new();
    if let Some(best) = eligible.iter().map(|m| m.match_score).reduce(f64::max) {
        score += best * 0.55;
        reasons.push("Best saved-profile job relevance contributes up to 55 points".to_owned());
    } else if parsed.is_none() {
        missing.push("saved_candidate_profile".to_owned());
    }
    let requested = labels(&filters["skills"])?;
    let skills = if requested.is_empty() {
        parsed
            .as_ref()
            .map(|p| p.verified_skills.clone())
            .unwrap_or_default()
    } else {
        requested
    };
    let tech = if attributes["technology_stack"].is_null() {
        vec![]
    } else {
        labels(&attributes["technology_stack"])?
    };
    if !skills.is_empty() && !tech.is_empty() {
        let mut overlap = skills
            .iter()
            .filter(|skill| tech.iter().any(|t| folded(t) == folded(skill)))
            .cloned()
            .collect::<Vec<_>>();
        overlap.sort();
        score += 10.0 * overlap.len() as f64 / skills.len() as f64;
        if !overlap.is_empty() {
            reasons.push(format!(
                "Reported technology matches: {}",
                overlap.join(", ")
            ));
        }
    } else {
        missing.push("technology_compatibility".to_owned());
    }
    match size["team_size_band"].as_str() {
        Some("1-10" | "2-10" | "11-50") => {
            score += 10.0;
            reasons.push(
                "Evidence reports a company of 1–50 employees; engineering team size is unknown"
                    .to_owned(),
            );
        }
        Some("unknown") => missing.push(
            size["team_size_evidence_status"]
                .as_str()
                .ok_or_else(invalid)?
                .to_owned(),
        ),
        Some("51-200" | "201-500" | "500+") => {}
        _ => return Err(invalid()),
    }
    match hiring["hiring_status"].as_str() {
        Some("hiring_confirmed") => {
            score += 15.0;
            reasons.push("Fresh attributable current opening".to_owned());
        }
        Some("hiring_possible") => {
            score += 5.0;
            reasons.push("Recent hiring evidence needs confirmation".to_owned());
        }
        Some("hiring_unknown" | "not_currently_hiring") => {}
        _ => return Err(invalid()),
    }
    let wanted = labels(&filters["locations"])?;
    let locations = if wanted.is_empty() {
        parsed
            .as_ref()
            .map(|p| p.preferences.preferred_locations.clone())
            .unwrap_or_default()
    } else {
        wanted
    };
    let policy = filters["remote_preference"].as_str().or_else(|| {
        parsed
            .as_ref()
            .and_then(|p| p.preferences.remote_preference.as_deref())
    });
    let location = attributes["location"]
        .as_str()
        .filter(|s| !s.is_empty())
        .map(String::from)
        .unwrap_or_else(|| {
            listings
                .iter()
                .map(|j| j.location.as_deref().unwrap_or(""))
                .collect::<Vec<_>>()
                .join(" ")
        });
    let mut remote = attributes["remote_policy"].as_str().unwrap_or("unknown");
    if remote == "unknown"
        && !listings.is_empty()
        && listings.iter().all(|j| j.remote_type == "remote")
    {
        remote = "remote";
    }
    if locations
        .iter()
        .any(|l| folded(&location).contains(&folded(l)))
        || policy == Some("remote") && remote == "remote"
    {
        score += 5.0;
        reasons.push("Location or remote evidence matches saved/requested preferences; work eligibility requires review".to_owned());
    }
    if let Some(p) = &parsed
        && attributes["stage"]
            .as_str()
            .is_some_and(|stage| p.preferences.company_stages.iter().any(|s| s == stage))
    {
        score += 3.0;
        reasons.push("Reported stage matches saved preferences".to_owned());
    }
    if contacts.iter().any(|c| {
        c["confidence"] == "supported"
            && c["priority"]
                .as_str()
                .is_some_and(|p| !matches!(p, "suppressed" | "review_required"))
    }) {
        score += 2.0;
        reasons.push("Fresh strong professional evidence is available".to_owned());
    } else {
        missing.push("independently_confirmed_professional_contact".to_owned());
    }
    let mut excluded = Vec::new();
    for m in &matches {
        for reason in &m.exclusion_reasons {
            if !excluded.contains(reason) {
                excluded.push(reason.clone());
            }
        }
    }
    if let Some(p) = &parsed
        && p.preferences.excluded_companies.iter().any(|value| {
            folded(value) == folded(name) || domain.is_some_and(|d| folded(value) == folded(d))
        })
    {
        excluded.push("Company excluded by saved preferences".to_owned());
    }
    let version = profile.map(|p| p["version"].clone()).unwrap_or(Value::Null);
    if profile.is_some()
        && !version
            .as_i64()
            .is_some_and(|n| (1..=i32::MAX as i64).contains(&n))
    {
        return Err(invalid());
    }
    let rounded = if score <= 0.0 {
        json!(0)
    } else if score >= 100.0 {
        json!(100)
    } else {
        json!(
            format!("{score:.2}")
                .parse::<f64>()
                .map_err(|_| invalid())?
        )
    };
    Ok(
        json!({"startup_match_score":rounded,"ranking_reasons":reasons,"missing_information":missing,"matching_roles":if parsed.is_some(){eligible.len()}else{jobs.len()},"profile_version":version,"exclusion_reasons":excluded,"score_kind":"relevance_not_probability"}),
    )
}
