//! Saved professional evidence ranking. Ordering weights never establish mailbox verification.
use super::{Settings, invalid};
use crate::{Failure, Result};
use chrono::{DateTime, Duration, NaiveDate, NaiveDateTime, Utc};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
pub fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(value) => *value,
        Value::Number(value) => value.as_f64().is_some_and(|n| n != 0.0),
        Value::String(value) => !value.is_empty(),
        Value::Array(value) => !value.is_empty(),
        Value::Object(value) => !value.is_empty(),
    }
}
/// Legacy saved evidence uses UTC wall time, including naive imported ISO strings.
pub fn timestamp(value: &Value) -> Option<DateTime<Utc>> {
    let value = value.as_str()?;
    if let Ok(at) = DateTime::parse_from_rfc3339(value) {
        return Some(at.naive_local().and_utc());
    }
    for format in ["%Y-%m-%dT%H:%M:%S%.f", "%Y-%m-%d %H:%M:%S%.f"] {
        if let Ok(at) = NaiveDateTime::parse_from_str(value, format) {
            return Some(at.and_utc());
        }
    }
    NaiveDate::parse_from_str(value, "%Y-%m-%d")
        .ok()?
        .and_hms_opt(0, 0, 0)
        .map(|value| value.and_utc())
}
pub fn fresh(value: &Value, days: i64, now: DateTime<Utc>) -> bool {
    timestamp(value).is_some_and(|at| at >= now - Duration::days(days))
}
pub fn email_observed_at(contact: &Value) -> Value {
    let value = &contact["metadata_"]["email_observed_at"];
    if truthy(value) {
        if timestamp(value).is_some() {
            value.clone()
        } else {
            Value::Null
        }
    } else {
        contact["last_checked_at"].clone()
    }
}
pub fn email_kind(email: &str) -> &'static str {
    let email = automated_apply_domain::text::folded(email);
    let local = email
        .split('@')
        .next()
        .unwrap_or("")
        .split('+')
        .next()
        .unwrap_or("");
    let role = [
        "careers",
        "jobs",
        "hr",
        "recruitment",
        "recruiting",
        "talent",
        "hiring",
        "info",
        "hello",
        "contact",
        "support",
        "team",
        "admin",
        "sales",
        "office",
        "people",
        "noreply",
        "no-reply",
    ]
    .contains(&local)
        || ["careers", "jobs", "recruiting", "hr", "hiring"]
            .iter()
            .any(|prefix| {
                local
                    .strip_prefix(prefix)
                    .is_some_and(|tail| tail.starts_with(['.', '_', '-']))
            });
    if role {
        "role_based"
    } else {
        "person_specific"
    }
}
pub fn business_email(email: &str, company_domain: &str) -> Option<String> {
    if email.len() > 255 || email.chars().any(char::is_whitespace) || email.contains(['<', '>']) {
        return None;
    }
    let checked = crate::profile_contract::email(email).ok()?;
    let email = automated_apply_domain::text::folded(&checked);
    let company = reqwest::Url::parse(&if company_domain.contains("://") {
        company_domain.to_owned()
    } else {
        format!("https://{company_domain}")
    })
    .ok()?;
    let domain = automated_apply_domain::text::folded(
        company
            .host_str()?
            .strip_prefix("www.")
            .unwrap_or(company.host_str()?),
    );
    if email.rsplit_once('@')?.1 == domain {
        Some(email)
    } else {
        None
    }
}
fn link(value: &Value) -> Option<String> {
    value.as_str().and_then(crate::resources::public_https)
}
fn metadata(value: &Value) -> Result<&serde_json::Map<String, Value>> {
    value["metadata_"].as_object().ok_or_else(invalid)
}
pub fn rank(
    contact: &Value,
    company: &Value,
    job: Option<&Value>,
    ttl: i64,
    now: DateTime<Utc>,
) -> Result<Value> {
    let role =
        automated_apply_domain::text::folded(contact["role_title"].as_str().ok_or_else(invalid)?);
    let meta = metadata(contact)?;
    if meta
        .get("evidence_strength")
        .is_some_and(|v| v.as_str().is_none_or(|s| s.len() > 100))
    {
        return Err(invalid());
    }
    let company_meta = metadata(company)?;
    let count = company_meta.get("employee_count").and_then(Value::as_i64);
    let band = company_meta
        .get("_verified_team_size_band")
        .and_then(Value::as_str);
    let small = count.is_some_and(|n| n <= 50) || matches!(band, Some("1-10" | "2-10" | "11-50"));
    let large = count.is_some_and(|n| n >= 250);
    let mut reasons = Vec::new();
    let mut score = 0;
    let recruiter = ["recruit", "talent", "human resources", "hr"]
        .iter()
        .any(|s| role.contains(s));
    let manager = [
        "engineering manager",
        "hiring manager",
        "head of engineering",
        "vp engineering",
        "vp of engineering",
    ]
    .iter()
    .any(|s| role.contains(s));
    let executive = [
        "founder",
        "cto",
        "chief technology",
        "ceo",
        "chief executive",
    ]
    .iter()
    .any(|s| role.contains(s));
    if recruiter || manager {
        score += 40;
        reasons.push("Reported recruiting or engineering management role")
    } else if executive {
        score += if small {
            45
        } else if large {
            10
        } else {
            20
        };
        reasons.push(if small {
            "Technical or executive leadership at a known small company"
        } else {
            "Leadership role; direct hiring responsibility is unconfirmed"
        })
    }
    if let Some(job) = job {
        reasons.push("Same employer as the target opening");
        let job_id = job["id"].as_str().ok_or_else(invalid)?;
        if contact["_target_job_associated"] == true
            || meta
                .get("job_ids")
                .and_then(Value::as_array)
                .is_some_and(|ids| ids.iter().any(|id| id == job_id))
        {
            score += 40;
            reasons.push("Explicitly associated with this opening")
        }
        let title =
            automated_apply_domain::text::folded(job["title"].as_str().ok_or_else(invalid)?);
        if title.contains("intern")
            && ["campus", "university", "early career"]
                .iter()
                .any(|s| role.contains(s))
        {
            score += 30;
            reasons.push("Campus recruiting role fits internship hiring")
        }
    }
    if meta
        .get("hiring_responsibility_confirmed")
        .is_some_and(truthy)
    {
        score += 20;
        reasons.push("Human-confirmed hiring responsibility")
    }
    if meta.get("evidence_strength") == Some(&json!("strong")) {
        score += 15;
        reasons.push("Strong identity evidence")
    }
    let current = fresh(&contact["last_checked_at"], ttl, now);
    if current {
        score += 10;
        reasons.push("Contact evidence checked within cache lifetime")
    } else {
        reasons.push("Evidence requires a freshness review")
    }
    let review = meta.get("identity_review_required").is_some_and(truthy);
    let suppressed = contact["do_not_contact"].as_bool().ok_or_else(invalid)?;
    if review {
        reasons.push("Conflicting identity evidence requires review")
    }
    if suppressed {
        reasons.push("Contact suppressed by human review")
    }
    let available = !suppressed && !review && current;
    let email = contact["email"].as_str().filter(|s| !s.is_empty());
    let has_link = link(&contact["linkedin_url"]).is_some();
    let draft_ready = available
        && email.is_some_and(|email| email_kind(email) == "person_specific")
        && fresh(&email_observed_at(contact), ttl, now)
        && contact["email_status"] == "verified"
        && fresh(&contact["last_verified_at"], ttl, now)
        && fresh(&contact["last_reviewed_at"], ttl, now);
    Ok(
        json!({"priority":if suppressed{"suppressed"}else if review{"review_required"}else if score>=60{"high"}else if score>=35{"medium"}else{"low"},"ordering_score":if suppressed||review{0}else{score},"reasons":reasons,"evidence_strength":meta.get("evidence_strength").cloned().unwrap_or(json!("unknown")),"confidence":if review{"requires_review"}else if meta.get("evidence_strength")==Some(&json!("strong"))&&current{"supported"}else{"limited"},"manual_linkedin_available":available&&has_link,"email_send_ready":false,"email_draft_review_ready":draft_ready,"manual_outreach_review_available":!suppressed&&!review&&current&&(has_link||matches!(contact["email_status"].as_str(),Some("provider_reported"|"verified"))),"outbound_messages_sent":0}),
    )
}
pub fn output(
    contact: &Value,
    company: &Value,
    job: Option<&Value>,
    settings: &Settings,
    now: DateTime<Utc>,
) -> Result<Value> {
    for (key, max) in [
        ("full_name", 255),
        ("role_title", 255),
        ("email_status", 50),
    ] {
        if contact[key]
            .as_str()
            .is_none_or(|s| s.is_empty() || s.chars().count() > max)
        {
            return Err(invalid());
        }
    }
    for (key, max) in [("email", 255), ("enrichment_source", 100)] {
        if !contact[key].is_null()
            && contact[key]
                .as_str()
                .is_none_or(|s| s.chars().count() > max)
        {
            return Err(invalid());
        }
    }
    if company["name"]
        .as_str()
        .is_none_or(|s| s.is_empty() || s.chars().count() > 255)
    {
        return Err(invalid());
    }
    if contact["_metadata_invalid"] == true {
        return Err(invalid());
    }
    let meta = metadata(contact)?;
    let mut ranking = rank(contact, company, job, settings.cache_days, now)?;
    let source = contact["enrichment_source"].as_str();
    let expired = matches!(
        source,
        Some("apollo" | "signalhire" | "public_search" | "official_company")
    ) && !fresh(&email_observed_at(contact), settings.retention_days, now);
    if expired {
        for key in [
            "email_send_ready",
            "email_draft_review_ready",
            "manual_outreach_review_available",
            "manual_linkedin_available",
        ] {
            ranking[key] = json!(false)
        }
    }
    let email = contact["email"].as_str().filter(|s| !s.is_empty());
    let publication = meta.get("email_publication_url").and_then(link);
    let published = email.is_some_and(|email| {
        meta.get("email_publication_confirmed").is_some_and(truthy)
            && publication.is_some()
            && meta.get("email_publication_digest").and_then(Value::as_str)
                == Some(format!("{:x}", Sha256::digest(email.as_bytes())).as_str())
    });
    let suppressed = contact["do_not_contact"] == true;
    let stale = email.is_some() && !fresh(&email_observed_at(contact), settings.cache_days, now);
    let id = contact["id"]
        .as_str()
        .and_then(|s| s.parse::<uuid::Uuid>().ok())
        .ok_or_else(invalid)?;
    let company_id = contact["company_id"]
        .as_str()
        .and_then(|s| s.parse::<uuid::Uuid>().ok())
        .ok_or_else(invalid)?;
    if company["id"] != company_id.to_string() {
        return Err(Failure("contact_employer_missing"));
    }
    let references = meta.get("job_ids").cloned().unwrap_or(json!([]));
    let references = references
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .take(100)
        .map(|value| {
            value
                .as_str()
                .filter(|s| s.len() <= 100)
                .map(|s| json!(s))
                .ok_or_else(invalid)
        })
        .collect::<Result<Vec<_>>>()?;
    let confidence = if contact["confidence_score"].is_null() {
        0.0
    } else {
        contact["confidence_score"]
            .as_f64()
            .filter(|n| n.is_finite())
            .ok_or_else(invalid)?
    };
    let mut value = json!({"id":id,"company_id":company_id,"company":company["name"],"full_name":contact["full_name"],"role_title":contact["role_title"],"linkedin_url":if expired{None}else{link(&contact["linkedin_url"])},"email":if expired{Value::Null}else{contact["email"].clone()},"email_status":if expired{json!("unknown")}else{contact["email_status"].clone()},"email_evidence_status":if expired||suppressed||stale{"suppressed_or_stale"}else if email.is_none(){"not_found"}else if contact["email_status"]=="verified"{"verified_using_authorized_method"}else if published{"published_source_supported"}else if contact["email_status"]=="provider_reported"{"provider_reported"}else{"unverified"},"email_publication_url":if published&&!expired&&!suppressed{publication}else{None},"source":contact["enrichment_source"],"legacy_confidence_score":confidence,"last_checked_at":contact["last_checked_at"],"last_reviewed_at":contact["last_reviewed_at"],"do_not_contact":contact["do_not_contact"],"suppression_reason":contact["suppression_reason"],"human_review_notes":contact["human_review_notes"],"associated_job_ids":references,"retention_expired":expired});
    for (key, item) in ranking.as_object().ok_or_else(invalid)? {
        value[key] = item.clone();
    }
    Ok(value)
}
