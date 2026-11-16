//! Final-gate cases for the owner's any-skill rule, reviewed facts and custom preferences.
use automated_apply_agents::Failure;
use automated_apply_agents::execution::{
    contracts::{self, Kind},
    eligibility,
};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use uuid::Uuid;
fn fixture() -> (Value, Value, Value, Value, Value, DateTime<Utc>) {
    let policy=contracts::normalize(Kind::Policy,json!({"global_limits":{"max_job_age_days":14,"applicant_limit":1000,"minimum_match_score":50},"platforms":{"naukri":{"skill_match_mode":"any"}}})).unwrap();
    let work = json!({"platform":"naukri","facts":{"posted_date":"2026-11-15","applicants_min":20,"applicants_max":20}});
    let company = json!({"id":Uuid::new_v4(),"name":"Fictional Employer","domain":"fictional.example.com","metadata_":{}});
    let job = json!({"id":Uuid::new_v4(),"company_id":company["id"],"title":"Rust Engineer","description":"Rust and Python engineering","job_url":"https://www.naukri.com/job-listings-fictional-123456789012","application_url":null,"source_platform":"naukri","location":"Remote","is_remote":true,"remote_type":"remote","experience_level":"junior","employment_type":"full_time","skills_required":["Rust","Python"],"date_posted":"2026-11-15T00:00:00Z","discovery_metadata":{"experience_min_years":0,"experience_max_years":1}});
    let profile = json!({"verified_skills":["Rust"],"verified_experience_years":0.5,"preferences":{"target_titles":["Rust Engineer"],"remote_preference":"any"}});
    (
        work,
        policy,
        job,
        company,
        profile,
        DateTime::parse_from_rfc3339("2026-11-16T00:00:00Z")
            .unwrap()
            .with_timezone(&Utc),
    )
}
#[test]
fn execution_eligibility_any_skill_preserves_unmatched_skills_and_all_other_filters() {
    let (mut work, mut policy, job, company, mut profile, now) = fixture();
    eligibility::check(
        &mut work,
        &policy,
        job.clone(),
        Some(company.clone()),
        &profile,
        now,
    )
    .unwrap();
    assert!(work["match_score"].as_f64().unwrap() >= 50.0);
    assert_eq!(profile["verified_skills"], json!(["Rust"]));
    policy["platforms"]["naukri"]["skill_match_mode"] = json!("all");
    assert_eq!(
        eligibility::check(
            &mut work,
            &policy,
            job.clone(),
            Some(company.clone()),
            &profile,
            now
        ),
        Err(Failure(
            "current_profile_preferences_or_required_skills_exclude_job"
        ))
    );
    policy["platforms"]["naukri"]["skill_match_mode"] = json!("any");
    profile["verified_skills"] = json!([]);
    assert_eq!(
        eligibility::check(
            &mut work,
            &policy,
            job.clone(),
            Some(company.clone()),
            &profile,
            now
        ),
        Err(Failure(
            "current_profile_preferences_or_required_skills_exclude_job"
        ))
    );
    profile["verified_skills"] = json!(["Rust"]);
    work["facts"]["applicants_min"] = json!(1000);
    work["facts"]["applicants_max"] = json!(1000);
    assert_eq!(
        eligibility::check(
            &mut work,
            &policy,
            job.clone(),
            Some(company.clone()),
            &profile,
            now
        ),
        Err(Failure("applicant_limit_reached"))
    );
    work["facts"]["applicants_min"] = json!(20);
    work["facts"]["applicants_max"] = Value::Null;
    assert_eq!(
        eligibility::check(
            &mut work,
            &policy,
            job.clone(),
            Some(company.clone()),
            &profile,
            now
        ),
        Err(Failure("applicant_count_requires_review"))
    );
    work["facts"]["applicants_max"] = json!(20);
    profile["preferences"]["excluded_companies"] = json!(["Fictional Employer"]);
    assert_eq!(
        eligibility::check(&mut work, &policy, job, Some(company), &profile, now),
        Err(Failure(
            "current_profile_preferences_or_required_skills_exclude_job"
        ))
    );
}
#[test]
fn execution_eligibility_closed_unknown_experience_and_custom_boundaries_are_not_inferred() {
    let (mut work, mut policy, mut job, company, profile, now) = fixture();
    job["status"] = json!("closed");
    assert_eq!(
        eligibility::check(
            &mut work,
            &policy,
            job.clone(),
            Some(company.clone()),
            &profile,
            now
        ),
        Err(Failure("vacancy_closed_expired_or_invalid"))
    );
    job["status"] = json!("new");
    job["discovery_metadata"]["experience_min_years"] = Value::Null;
    assert_eq!(
        eligibility::check(
            &mut work,
            &policy,
            job.clone(),
            Some(company.clone()),
            &profile,
            now
        ),
        Err(Failure("verified_experience_requirements_required"))
    );
    job["discovery_metadata"]["experience_min_years"] = json!(0);
    job["discovery_metadata"]["experience_max_years"] = Value::Null;
    eligibility::check(
        &mut work,
        &policy,
        job.clone(),
        Some(company.clone()),
        &profile,
        now,
    )
    .unwrap();
    policy["platforms"]["naukri"]["preferences_mode"] = json!("custom");
    policy["platforms"]["naukri"]["preferences"]["experience_max"] = json!(1);
    assert_eq!(
        eligibility::check(
            &mut work,
            &policy,
            job.clone(),
            Some(company.clone()),
            &profile,
            now
        ),
        Err(Failure(
            "advertised_experience_outside_platform_preferences"
        ))
    );
    policy["platforms"]["naukri"]["preferences"]["experience_max"] = Value::Null;
    policy["platforms"]["naukri"]["preferences"]["maximum_salary"] = json!(1_000_000);
    assert_eq!(
        eligibility::check(&mut work, &policy, job, Some(company), &profile, now),
        Err(Failure("salary_comparison_requires_review"))
    );
    let mut value = json!({"admitted_actions":[{"fingerprint":"apply:spent"}]});
    eligibility::hold(&mut value, "questionnaire_owner_answer_changed");
    assert_eq!(value["stage"], "NEEDS_INPUT");
    assert_eq!(value["admitted_actions"][0]["fingerprint"], "apply:spent");
}
