//! Deferred comparisons with actual legacy URL, owner DTO and normalization code. No settings/network.
use automated_apply_agents::{
    execution::{
        contracts::{self, Kind},
        owner_import,
    },
    job_urls,
};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
#[test]
fn owner_import_normalization_matches_actual_models_and_does_not_infer_provider_verified_facts() {
    let now = DateTime::parse_from_rfc3339("2026-11-16T12:00:00Z")
        .unwrap()
        .with_timezone(&Utc);
    let mut cases = Vec::new();
    for index in 0..16 {
        let mut input = json!({"url":"https://naukri.com/job-listings-fictional-123456789012/?utm_source=fixture","title":" Rust Engineer ","employer":" Fictional Labs ","description":" Fictional evidence ","required_skills":[" Rust ",""],"preferred_skills":[" Go "],"experience_min":0,"experience_max":2,"remote_type":"remote","salary_min":100,"salary_max":200,"salary_currency":"INR","salary_period":"year"});
        match index {
            0 => {}
            1 => input["remote_type"] = json!("hybrid"),
            2 => input["experience_requirement"] = json!("required"),
            3 => {
                input["experience_requirement"] = json!("required");
                input["experience_min"] = Value::Null;
            }
            4 => input["provenance"] = json!("owner_job_alert"),
            5 => {
                input["provenance"] = json!("owner_job_alert");
                input["message_reference"] = json!("gmail-alert:fictional");
            }
            6 => input["salary_currency"] = json!("bad"),
            7 => input["salary_max"] = json!(1e13),
            8 => input["posted_at"] = json!("1989-01-01T00:00:00Z"),
            9 => input["posted_at"] = json!("2026-11-15T10:00:00+05:30"),
            10 => {
                input["application_url"] =
                    json!("https://boards.greenhouse.io/fictional/jobs/123456?utm_source=test")
            }
            11 => {
                input["application_url"] =
                    json!("https://jobs.lever.co/fictional/1234567890abcdef/apply?ref=fixture")
            }
            12 => {
                input["application_url"] =
                    json!("https://jobs.ashbyhq.com/fictional/1234567890abcdef/application")
            }
            13 => {
                input["application_url"] = json!(
                    "https://jobs.smartrecruiters.com/Fictional/123456-Rust?oga=true&utm_source=test"
                )
            }
            14 => input["application_url"] = json!("https://example.org/careers"),
            _ => {
                input["posting_status"] = json!("active");
                input["observed_at"] = json!("2026-11-15T10:00:00+05:30");
                input["valid_through"] = json!("2026-12-01");
            }
        }
        cases.push(input);
    }
    let urls = json!([
        "https://boards.greenhouse.io/fictional/jobs/12345/?utm_source=test&b=2&a=1#section",
        "https://example.org/a/?z=a+b&a=~*",
        "https://jobs.lever.co/fictional/1234567890abcdef/apply?ref=test",
        "https://jobs.smartrecruiters.com/Fictional/123456-Rust?oga=true&keep=yes",
        "https://www.naukri.com/job-listings-fictional-123456789012/?utm_source=fixture",
        "http://127.0.0.1/private"
    ]);
    let script = r#"
import json,re,runpy,sys
from urllib.parse import urlsplit,urlunsplit
from pydantic import TypeAdapter,ValidationError
from backend.app.execution.contracts import ImportBatch
from backend.app.core.job_urls import canonical_job_url,ats_job_url
from backend.app.core.urls import PublicHTTPSURL
from backend.app.schemas.normalized_job import NormalizedJob
load=runpy.run_path('rust/scripts/export_execution_contracts.py')['load']
scope=dict(re=re,urlsplit=urlsplit,urlunsplit=urlunsplit,TypeAdapter=TypeAdapter,ValidationError=ValidationError,PublicHTTPSURL=PublicHTTPSURL,NormalizedJob=NormalizedJob)
load(scope,'backend/app/services/applications/platforms/base.py',{'safe_url'})
load(scope,'backend/app/execution/naukri.py',{'normalize','normalized_url'})
raw=json.load(sys.stdin);out={'items':[],'urls':[]}
for value in raw['items']:
 try:out['items'].append(scope['normalize'](ImportBatch.model_validate({'jobs':[value]}).jobs[0]).model_dump(mode='json'))
 except ValueError:out['items'].append(None)
for url in raw['urls']:
 try:out['urls'].append([canonical_job_url(url),ats_job_url(url)])
 except ValueError:out['urls'].append(None)
assert 'backend.app.core.config' not in sys.modules
print(json.dumps(out))
"#;
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
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
        .write_all(json!({"items":cases,"urls":urls}).to_string().as_bytes())
        .unwrap();
    let out = child.wait_with_output().unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let mut expected: Value = serde_json::from_slice(&out.stdout).unwrap();
    for (index, input) in cases.into_iter().enumerate() {
        let actual = contracts::normalize(Kind::ImportBatch, json!({"jobs":[input]}))
            .and_then(|b| owner_import::normalized(&b["jobs"][0], now));
        if expected["items"][index].is_null() {
            assert!(actual.is_err(), "case {index}");
        } else {
            for key in ["first_observed_date", "last_observed_date", "retrieved_at"] {
                expected["items"][index][key] =
                    json!(now.to_rfc3339_opts(chrono::SecondsFormat::Secs, false));
            }
            if let Some(raw) = expected["items"][index]["date_posted"].as_str() {
                expected["items"][index]["date_posted"] = json!(
                    DateTime::parse_from_rfc3339(raw)
                        .unwrap()
                        .with_timezone(&Utc)
                        .to_rfc3339_opts(chrono::SecondsFormat::Secs, false)
                );
            }
            assert_eq!(actual.unwrap(), expected["items"][index], "case {index}");
        }
    }
    for (index, url) in urls.as_array().unwrap().iter().enumerate() {
        let raw = url.as_str().unwrap();
        if expected["urls"][index].is_null() {
            assert!(job_urls::canonical(raw).is_err());
        } else {
            assert_eq!(
                job_urls::canonical(raw).unwrap(),
                expected["urls"][index][0]
            );
            assert_eq!(
                json!(job_urls::ats(Some(raw)).unwrap()),
                expected["urls"][index][1]
            );
        }
    }
}
