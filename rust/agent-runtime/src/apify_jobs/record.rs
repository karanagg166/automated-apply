//! Selected job/company claims only. Generic paid-job retention excludes personal profile/founder URLs.
use crate::{
    Failure, Result,
    job_sources::{contract, rules},
};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
fn invalid() -> Failure {
    Failure("apify_job_record_invalid")
}
fn truthy(v: &Value) -> bool {
    crate::contacts::rules::truthy(v)
}
fn choose(item: &Value, keys: &[&str]) -> Value {
    keys.iter()
        .map(|k| &item[k])
        .find(|v| truthy(v))
        .cloned()
        .unwrap_or(Value::Null)
}
fn scalar(v: &Value) -> Result<Option<String>> {
    if !truthy(v) {
        return Ok(None);
    }
    let s = match v {
        Value::String(s) => s.clone(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        Value::Number(_) => crate::python_json::serialize(v, false, false),
        _ => return Err(invalid()),
    };
    if s.chars().count() > 255 {
        return Err(invalid());
    }
    Ok(Some(s))
}
pub fn normalize(portal: &str, actor: &str, item: &Value, now: DateTime<Utc>) -> Result<Value> {
    if !crate::source_registry::APIFY_PORTALS.contains(&portal)
        || !item.is_object()
        || item.to_string().len() > 1048576
    {
        return Err(invalid());
    }
    crate::apify_config::safe_actor(actor)?;
    if truthy(&item["employmentType"]) && !item["employmentType"].is_string() {
        return Err(invalid());
    }
    let company = choose(item, &["companyName", "company"]);
    let data = company.as_object();
    let name = if data.is_some_and(|m| !m.is_empty()) {
        company["name"].clone()
    } else {
        company.clone()
    };
    let mut skills = choose(item, &["skills"]);
    if skills.is_null() {
        skills = json!([])
    }
    if let Some(raw) = skills.as_str() {
        skills = json!(
            raw.split(',')
                .map(|s| s.trim_matches(crate::context_contract::python_space))
                .filter(|s| !s.is_empty())
                .collect::<Vec<_>>()
        );
    }
    let mut location = item["location"].clone();
    if let Some(list) = location.as_array() {
        location = json!(
            list.iter()
                .map(|v| v.as_str().ok_or_else(invalid))
                .collect::<Result<Vec<_>>>()?
                .join(", ")
        );
    }
    let raw = choose(item, &["salary", "compensation"]);
    // Structured raw blobs are not retained as stringified vendor payloads.
    if raw.is_array() || raw.is_object() {
        return Err(invalid());
    }
    let salary = if truthy(&raw) {
        Some(match &raw {
            Value::String(s) => s.clone(),
            Value::Bool(v) => if *v { "True" } else { "False" }.into(),
            Value::Number(_) => crate::python_json::serialize(&raw, false, false),
            _ => return Err(invalid()),
        })
    } else {
        None
    };
    let salary_fields = rules::salary_fields(raw.as_str())?;
    let mut intelligence = json!({});
    if data.is_some() {
        for key in ["stage", "batch", "technologies", "remote_policy"] {
            if let Some(value) = company.get(key) {
                let valid = value.is_null()
                    || value.as_str().is_some_and(|s| s.chars().count() <= 2000)
                    || key == "technologies"
                        && value.as_array().is_some_and(|a| {
                            a.len() <= 100
                                && a.iter()
                                    .all(|v| v.as_str().is_some_and(|s| s.chars().count() <= 200))
                        });
                if !valid {
                    return Err(invalid());
                }
                intelligence[key] = value.clone();
            }
        }
    }
    if intelligence.as_object().is_some_and(|m| !m.is_empty()) {
        intelligence["source"] = json!(portal);
        intelligence["verification_status"] = json!("source_reported");
    }
    let mut job = json!({"source_name":portal,"source_job_id":scalar(&choose(item,&["id","jobId","slug"]))?,"original_url":choose(item,&["url","jobUrl","job_url","link"]),"application_url":choose(item,&["applyUrl","applicationUrl"]),"company_name":name,"company_domain":if truthy(&item["companyDomain"]){item["companyDomain"].clone()}else{company.get("domain").cloned().unwrap_or(Value::Null)},"title":choose(item,&["title","jobTitle","role"]),"description":choose(item,&["description","jobDescription"]),"location":location,"remote_type":if item["isRemote"]==true{"remote"}else{rules::remote_policy(location.as_str())},"employment_type":rules::employment(item["employmentType"].as_str()),"experience_level":item["seniority"],"salary_raw":salary,"equity":item["equity"],"skills_required":skills,"date_posted":rules::date(&choose(item,&["postedDate","datePosted"]))?,"company_intelligence":intelligence,"data_provenance":{"adapter":"ApifyJobAdapter","portal":portal,"actor_id":actor},"source_verification_status":"source_reported","is_confirmed_current":false});
    job.as_object_mut()
        .ok_or_else(invalid)?
        .extend(salary_fields.as_object().ok_or_else(invalid)?.clone());
    contract::normalize(job, now).map_err(|_| invalid())
}
