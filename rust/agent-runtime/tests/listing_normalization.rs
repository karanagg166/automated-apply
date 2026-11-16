//! Fictional actual-model parity; no application configuration or network imported.
use automated_apply_agents::execution::listing_ingestion;
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
fn normalize_dates(value: &mut Value) {
    if let Some(object) = value.as_object_mut() {
        for (k, v) in object {
            if matches!(
                k.as_str(),
                "date_posted"
                    | "first_observed_date"
                    | "last_observed_date"
                    | "retrieved_at"
                    | "observed_at"
            ) && v.is_string()
            {
                let at = DateTime::parse_from_rfc3339(v.as_str().unwrap()).unwrap();
                *v = json!(at.with_timezone(&Utc).to_rfc3339());
            } else {
                normalize_dates(v);
            }
        }
    }
}
#[test]
fn observed_listing_normalization_matches_actual_normalized_job_defaults_and_provenance() {
    let now = DateTime::parse_from_rfc3339("2026-11-16T00:00:00Z")
        .unwrap()
        .with_timezone(&Utc);
    let mut cases = vec![];
    for remote in ["remote", "onsite", "hybrid", "unknown"] {
        for employment in [Value::Null, json!("full_time"), json!("internship")] {
            for salary in [Value::Null, json!(120000.0)] {
                for posted in [Value::Null, json!("2026-11-15T12:00:00Z")] {
                    let observed = json!({"requisition":"123456789012","title":"Rust Developer","company":"Fictional Labs","location":"India","description":"Fictional observed role","skills":["Rust","Python"],"experience_min":0.0,"experience_max":2.0,"posted_at":posted,"posted_date":null,"remote_type":remote,"employment_type":employment,"salary_min":salary,"salary_max":salary,"salary_currency":if salary.is_null(){Value::Null}else{json!("INR")},"salary_period":if salary.is_null(){Value::Null}else{json!("year")},"evidence_sha256":"a".repeat(64),"posting_recruiter":null});
                    cases.push(json!({"work":{"url":"https://www.naukri.com/job-listings-fictional-123456789012","requisition":"123456789012"},"observed":observed,"now":now.to_rfc3339()}));
                }
            }
        }
    }
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let script = r#"
import json,sys
from datetime import datetime
from backend.app.schemas.normalized_job import NormalizedJob
out=[]
for c in json.load(sys.stdin):
 o,w=c['observed'],c['work'];now=datetime.fromisoformat(c['now'])
 item=NormalizedJob(source_name='naukri',source_job_id=w['requisition'],original_url=w['url'],title=o['title'],company_name=o['company'],location=o['location'],description=o['description'],skills_required=o['skills'],experience_min_years=o['experience_min'],experience_max_years=o['experience_max'],remote_type=o['remote_type'],employment_type=o['employment_type'],salary_min=o['salary_min'],salary_max=o['salary_max'],salary_currency=o['salary_currency'],salary_period=o['salary_period'],date_posted=o['posted_at'],first_observed_date=now,last_observed_date=now,retrieved_at=now,source_verification_status='observed',data_provenance={'method':'bound_browser_ui','evidence_sha256':o['evidence_sha256'],'observed_at':now.isoformat(),'posting_recruiter':o['posting_recruiter'],'experience_requirement':'required','observed_posted_date':o['posted_date']})
 out.append(item.model_dump(mode='json'))
assert 'backend.app.core.config' not in sys.modules
print(json.dumps(out))
"#;
    let mut child = Command::new(root.join(".venv/bin/python"))
        .args(["-c", script])
        .current_dir(root)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(json!(cases).to_string().as_bytes())
        .unwrap();
    let out = child.wait_with_output().unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let mut expected: Value = serde_json::from_slice(&out.stdout).unwrap();
    for (index, case) in cases.iter().enumerate() {
        let mut actual =
            listing_ingestion::normalized(&case["work"], &case["observed"], now).unwrap();
        normalize_dates(&mut actual);
        normalize_dates(&mut expected[index]);
        assert_eq!(actual, expected[index], "case {index}");
    }
}
