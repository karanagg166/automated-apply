use crate::text::{bounded_skill_present, description_text, folded, lowered, skill_key, title_key};
use indexmap::IndexMap;
use serde::{Deserialize, Serialize};

#[derive(Clone, Default, Deserialize, Serialize)]
#[serde(default)]
pub struct Preferences {
    #[serde(deserialize_with = "labels")]
    pub target_titles: Vec<String>,
    #[serde(deserialize_with = "labels")]
    pub preferred_locations: Vec<String>,
    pub remote_preference: Option<String>,
    #[serde(deserialize_with = "labels")]
    pub employment_types: Vec<String>,
    pub prioritize_startups: Option<bool>,
    #[serde(deserialize_with = "labels")]
    pub company_stages: Vec<String>,
    pub minimum_salary: Option<f64>,
    pub salary_currency: Option<String>,
    pub salary_period: Option<String>,
    #[serde(deserialize_with = "labels")]
    pub excluded_companies: Vec<String>,
    #[serde(deserialize_with = "labels")]
    pub excluded_titles: Vec<String>,
    #[serde(deserialize_with = "labels")]
    pub excluded_keywords: Vec<String>,
}
#[derive(Clone, Default, Deserialize, Serialize)]
#[serde(default)]
pub struct Profile {
    #[serde(deserialize_with = "labels")]
    pub verified_skills: Vec<String>,
    pub verified_experience_years: Option<f64>,
    pub preferences: Preferences,
}
#[derive(Clone, Default, Deserialize, Serialize)]
#[serde(default)]
pub struct Listing {
    pub title: String,
    pub description: Option<String>,
    pub skills_required: Vec<String>,
    pub location: Option<String>,
    pub is_remote: bool,
    pub remote_type: String,
    pub experience_level: Option<String>,
    pub employment_type: Option<String>,
    pub salary_min: Option<f64>,
    pub salary_max: Option<f64>,
    pub salary_currency: Option<String>,
    pub salary_period: Option<String>,
    pub date_posted: Option<String>,
}
#[derive(Clone, Default, Deserialize, Serialize)]
#[serde(default)]
pub struct Company {
    pub name: String,
    pub domain: Option<String>,
    pub startup_stage: Option<String>,
    pub startup_source: Option<String>,
}
#[derive(Debug, Serialize, Deserialize, PartialEq)]
pub struct BaseMatch {
    pub match_score: f64,
    pub matched_skills: Vec<String>,
    pub missing_skills: Vec<String>,
    pub location_match: bool,
    pub title_match: bool,
    pub explanation: String,
}
#[derive(Debug, Serialize, Deserialize, PartialEq)]
pub struct DiscoveryMatch {
    pub match_score: f64,
    pub matched_skills: Vec<String>,
    pub missing_skills: Vec<String>,
    pub positive_factors: Vec<String>,
    pub negative_factors: Vec<String>,
    pub exclusion_reasons: Vec<String>,
    pub unknown_fields: Vec<String>,
    pub explanation: String,
}
fn truth(value: &Option<String>) -> bool {
    value.as_ref().is_some_and(|v| !v.is_empty())
}
fn round2(value: f64) -> f64 {
    format!("{value:.2}").parse().unwrap()
}
fn score_text(value: f64) -> String {
    if value == 0.0 || value == 100.0 {
        format!("{value:.0}")
    } else if value.fract() == 0.0 {
        format!("{value:.1}")
    } else {
        value.to_string()
    }
}

pub fn base_match(job: &Listing, profile: &Profile) -> BaseMatch {
    let title = lowered(&job.title);
    let title_normal = title_key(&job.title);
    let description = description_text(job.description.as_deref().unwrap_or(""));
    let mut title_points: f64 = 0.0;
    let mut title_match = false;
    for target in &profile.preferences.target_titles {
        let target = title_key(target);
        if title_normal.contains(&target) {
            title_points = 30.0;
            title_match = true;
            break;
        }
        if target
            .split_whitespace()
            .any(|w| w.chars().count() > 3 && title_normal.contains(w))
        {
            title_points = title_points.max(15.0);
        }
    }
    let (mut matched, mut missing) = (Vec::new(), Vec::new());
    let skill_points = if !job.skills_required.is_empty() {
        let verified: IndexMap<_, _> = profile
            .verified_skills
            .iter()
            .map(|s| (skill_key(s), s.clone()))
            .collect();
        let required: IndexMap<_, _> = job
            .skills_required
            .iter()
            .map(|s| (skill_key(s), s.clone()))
            .collect();
        for (key, skill) in &required {
            if let Some(skill) = verified.get(key) {
                matched.push(skill.clone());
            } else {
                missing.push(skill.clone());
            }
        }
        matched.len() as f64 / required.len() as f64 * 40.0
    } else {
        let verified: IndexMap<_, _> = profile
            .verified_skills
            .iter()
            .map(|s| (lowered(s), s.clone()))
            .collect();
        for (key, skill) in verified {
            if bounded_skill_present(&key, &description) || bounded_skill_present(&key, &title) {
                matched.push(skill);
            }
        }
        (matched.len() as f64 * 8.0).min(40.0)
    };
    let policy = profile.preferences.remote_preference.as_deref();
    let mut location_match = false;
    if policy == Some("remote") && job.is_remote {
        location_match = true;
    } else if matches!(policy, Some("hybrid" | "any" | "onsite")) {
        if job.is_remote && policy != Some("onsite") {
            location_match = true;
        } else if !job.is_remote && truth(&job.location) {
            location_match = profile.preferences.preferred_locations.iter().any(|p| {
                job.location
                    .as_ref()
                    .unwrap()
                    .to_lowercase()
                    .contains(&p.to_lowercase())
            });
        }
    }
    let location_points = if location_match { 20.0 } else { 0.0 };
    let mut experience = if profile.verified_experience_years.is_some() {
        10.0
    } else {
        0.0
    };
    if let (Some(level), Some(years)) = (&job.experience_level, profile.verified_experience_years) {
        let level = level.to_lowercase();
        if level.contains("senior") && years < 3.0 {
            experience = 2.0;
        } else if level.contains("junior") && years > 6.0 {
            experience = 5.0;
        }
    }
    let score =
        round2((title_points + skill_points + location_points + experience).clamp(0.0, 100.0));
    let mut explanation = format!(
        "Title relevance: {title_points:.1}/30. Skills matched ({}): {}. Location/Remote match: {} ({location_points:.1}/20). Seniority alignment: {experience:.1}/10.",
        matched.len(),
        if matched.is_empty() {
            "None".into()
        } else {
            matched
                .iter()
                .take(5)
                .cloned()
                .collect::<Vec<_>>()
                .join(", ")
        },
        if location_match { "Yes" } else { "No" }
    );
    if profile.verified_experience_years.is_none() {
        explanation.push_str(" Experience is unknown; no seniority points awarded.");
    }
    BaseMatch {
        match_score: score,
        matched_skills: matched,
        missing_skills: missing,
        location_match,
        title_match,
        explanation,
    }
}

/// History is a separately verified repository result, never an instruction/model flag.
pub fn discovery_match(
    job: &Listing,
    profile: &Profile,
    company: Option<&Company>,
    history_match: bool,
) -> DiscoveryMatch {
    let prefs = &profile.preferences;
    let base = base_match(job, profile);
    let mut score = base.match_score;
    let (mut positive, mut negative, mut unknown, mut excluded) = (
        Vec::<String>::new(),
        Vec::<String>::new(),
        Vec::<String>::new(),
        Vec::<String>::new(),
    );
    let title = folded(&job.title);
    let description = folded(job.description.as_deref().unwrap_or(""));
    let name = company.map(|c| folded(&c.name)).unwrap_or_default();
    if history_match {
        excluded.push("Previously applied: confirmed reviewed mailbox history".into());
    }
    for v in &prefs.excluded_companies {
        if name == folded(v)
            || company.is_some_and(|c| c.domain.as_deref() == Some(folded(v).as_str()))
        {
            excluded.push(format!("Excluded company: {v}"));
        }
    }
    for v in &prefs.excluded_titles {
        if title.contains(&folded(v)) {
            excluded.push(format!("Excluded title: {v}"));
        }
    }
    for v in &prefs.excluded_keywords {
        if format!("{title} {description} {name}").contains(&folded(v)) {
            excluded.push(format!("Excluded keyword: {v}"));
        }
    }
    if base.title_match {
        positive.push("Target role matches".into());
    } else if !prefs.target_titles.is_empty() {
        negative.push("Title differs from target roles".into());
    }
    if !base.matched_skills.is_empty() {
        positive.push("Verified skills align with listing evidence".into());
    }
    if !base.missing_skills.is_empty() {
        negative.push("Some required skills are not in the saved profile".into());
    }
    if job.skills_required.is_empty() {
        unknown.push("required_skills".into());
    }
    if profile.verified_experience_years.is_none() || !truth(&job.experience_level) {
        unknown.push("experience_suitability".into());
        if profile.verified_experience_years.is_some() && !truth(&job.experience_level) {
            score -= 10.0;
        }
    } else if job
        .experience_level
        .as_ref()
        .unwrap()
        .to_lowercase()
        .contains("senior")
        && profile.verified_experience_years.is_some_and(|n| n < 3.0)
    {
        negative.push("Seniority may exceed verified experience".into());
    }
    let remote = if truth(&Some(job.remote_type.clone())) {
        job.remote_type.as_str()
    } else {
        "unknown"
    };
    if remote == "unknown" {
        unknown.push("remote_policy".into());
    }
    if !truth(&job.location) {
        unknown.push("location".into());
    }
    if base.location_match {
        score -= 20.0;
    }
    let location = truth(&job.location)
        && prefs
            .preferred_locations
            .iter()
            .any(|p| folded(job.location.as_ref().unwrap()).contains(&folded(p)));
    let policy = prefs.remote_preference.as_deref();
    let compatible = match policy {
        Some("remote") => remote == "remote",
        Some("hybrid") => remote == "hybrid" && (location || prefs.preferred_locations.is_empty()),
        Some("onsite") => remote == "onsite" && (location || prefs.preferred_locations.is_empty()),
        None | Some("any") => {
            location
                || remote == "remote"
                || (prefs.preferred_locations.is_empty() && truth(&job.location))
        }
        _ => false,
    };
    if compatible {
        score += 20.0;
        positive.push("Location and remote policy fit preferences".into());
    } else if policy.is_some_and(|p| !p.is_empty() && p != "any") && remote != "unknown" {
        negative.push("Remote policy differs from preference".into());
    }
    if !prefs.employment_types.is_empty() {
        match &job.employment_type {
            Some(t) if !t.is_empty() => {
                if prefs.employment_types.contains(t) {
                    score += 5.0;
                    positive.push("Employment type matches".into());
                } else {
                    score -= 5.0;
                    negative.push("Employment type differs".into());
                }
            }
            _ => unknown.push("employment_type".into()),
        }
    }
    let stage = company.and_then(|c| c.startup_stage.as_deref());
    if prefs.prioritize_startups == Some(true) {
        if company.is_some_and(|c| c.startup_source.as_deref() == Some("work_at_a_startup"))
            || matches!(stage, Some("pre_seed" | "seed" | "early" | "startup"))
        {
            score += 10.0;
            positive.push("Startup source or observed stage matches startup preference".into());
        } else {
            unknown.push("startup_status".into());
        }
    }
    if !prefs.company_stages.is_empty() {
        match stage.filter(|s| !s.is_empty()) {
            None => unknown.push("company_stage".into()),
            Some(stage) => {
                if prefs
                    .company_stages
                    .iter()
                    .any(|s| folded(s) == folded(stage))
                {
                    score += 5.0;
                    positive.push("Observed company stage matches".into());
                } else {
                    negative.push("Observed company stage differs".into());
                }
            }
        }
    }
    if let Some(minimum) = prefs.minimum_salary {
        if (job.salary_min.is_none() && job.salary_max.is_none())
            || !truth(&prefs.salary_currency)
            || !truth(&prefs.salary_period)
            || job.salary_currency != prefs.salary_currency
            || job.salary_period != prefs.salary_period
        {
            unknown.push("salary_comparison".into());
        } else if job.salary_max.is_some_and(|s| s < minimum) {
            score -= 5.0;
            negative.push("Published salary is below preference".into());
        } else if job.salary_min.is_some_and(|s| s >= minimum) {
            score += 5.0;
            positive.push("Published salary meets preference".into());
        } else {
            unknown.push("salary_comparison".into());
        }
    }
    if company.is_none_or(|c| c.name.is_empty()) {
        unknown.push("company_name".into());
    }
    unknown.push("company_size".into());
    if !truth(&job.date_posted) {
        unknown.push("publication_date".into());
    }
    if job.salary_min.is_none() && job.salary_max.is_none() {
        unknown.push("salary".into());
    }
    score = if excluded.is_empty() {
        round2(score.clamp(0.0, 100.0))
    } else {
        0.0
    };
    let factors = positive
        .iter()
        .chain(&negative)
        .chain(&excluded)
        .cloned()
        .collect::<Vec<_>>()
        .join("; ");
    let mut explanation = format!(
        "Profile preference score: {}/100. {}",
        score_text(score),
        if factors.is_empty() {
            "No confirmed preference alignment"
        } else {
            &factors
        }
    );
    if !unknown.is_empty() {
        explanation.push_str(&format!(". Unknown: {}", unknown.join(", ")));
    }
    explanation.push_str(". Listing relevance requires eligibility review.");
    DiscoveryMatch {
        match_score: score,
        matched_skills: base.matched_skills,
        missing_skills: base.missing_skills,
        positive_factors: positive,
        negative_factors: negative,
        exclusion_reasons: excluded,
        unknown_fields: unknown,
        explanation,
    }
}

fn labels<'de, D: serde::Deserializer<'de>>(deserializer: D) -> Result<Vec<String>, D::Error> {
    let input = Vec::<String>::deserialize(deserializer)?;
    if input.len() > 100 {
        return Err(serde::de::Error::custom("profile_list_limit"));
    }
    let mut result = Vec::new();
    let mut seen = std::collections::HashSet::new();
    for value in input {
        let clean = value.split_whitespace().collect::<Vec<_>>().join(" ");
        if clean.is_empty() || clean.chars().count() > 200 {
            return Err(serde::de::Error::custom("invalid_profile_label"));
        }
        if seen.insert(folded(&clean)) {
            result.push(clean);
        }
    }
    Ok(result)
}
