//! Deferred comparisons with actual preparation and reviewed-history predicates.
use automated_apply_agents::execution::{review, reviewed_history};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
fn original(value: Value) -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let script = r#"
import ast,json,sys,types
from pathlib import Path
from datetime import datetime,date,timezone
scope=globals().copy()
def load(path,names):
 body=[]
 for n in ast.parse(Path(path).read_text()).body:
  name=n.name if isinstance(n,ast.FunctionDef) else None
  if name in names:body.append(n)
 assert len(body)==len(names)
 exec(compile(ast.Module(body=body,type_ignores=[]),path,'exec'),scope)
load('backend/app/services/applications/platforms/naukri.py',{'posting_unavailable'})
load('backend/app/execution/worker.py',{'eligibility'})
load('backend/app/integrations/gmail/history.py',{'canonical_url','previously_applied'})
raw=json.load(sys.stdin)
if 'eligibility' in raw:out=[scope['eligibility'](types.SimpleNamespace(**j),types.SimpleNamespace(**p),types.SimpleNamespace(**f)) for j,p,f in raw['eligibility']]
else:out=[scope['previously_applied'](types.SimpleNamespace(**j),types.SimpleNamespace(**c) if c else None,h) for j,c,h in raw['history']]
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
        .write_all(value.to_string().as_bytes())
        .unwrap();
    let out = child.wait_with_output().unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    serde_json::from_slice(&out.stdout).unwrap()
}
#[test]
fn legacy_preparation_eligibility_matches_actual_rule_order_for_required_preferred_unknown_and_missing_facts()
 {
    let now = DateTime::parse_from_rfc3339("2026-11-16T12:00:00Z")
        .unwrap()
        .with_timezone(&Utc);
    let fit = json!({"match_score":80.,"matched_skills":["Rust"],"missing_skills":[],"positive_factors":[],"negative_factors":[],"exclusion_reasons":[],"unknown_fields":[],"explanation":"fictional"});
    let mut cases = Vec::new();
    for requirement in ["required", "preferred", "unknown"] {
        for years in [Value::Null, json!(0.), json!(2.), json!(4.)] {
            for issue in 0..4 {
                let job = json!({"title":"Rust Engineer","status":"discovered","discovery_metadata":{"experience_min_years":1.,"experience_max_years":3.,"data_provenance":{"experience_requirement":requirement}}});
                let profile = json!({"verified_experience_years":years});
                let mut fit = fit.clone();
                match issue {
                    0 => {}
                    1 => fit["match_score"] = json!(49.),
                    2 => fit["missing_skills"] = json!(["Go"]),
                    _ => fit["exclusion_reasons"] = json!(["Prior application"]),
                }
                cases.push((job, profile, fit));
            }
        }
    }
    let expected = original(
        json!({"eligibility":cases.iter().map(|(j,p,f)|json!([j,p,f])).collect::<Vec<_>>()}),
    );
    assert_eq!(cases.len(), 48);
    for (index, (job, profile, fit)) in cases.into_iter().enumerate() {
        let fit = serde_json::from_value(fit).unwrap();
        assert_eq!(
            json!(review::preparation_eligibility(&job, &profile, &fit, now).unwrap()),
            expected[index],
            "case {index}"
        );
    }
}
#[test]
fn reviewed_history_matches_actual_url_ats_and_company_role_fallback_without_adding_claims() {
    let mut cases = Vec::new();
    for index in 0..16 {
        let mut job = json!({"title":" Rust Engineer ","job_url":"https://www.naukri.com/job-listings-fictional-123456789012?utm_source=fixture","application_url":null});
        let mut company = json!({"name":" Fictional Labs "});
        let mut row = json!({"confirmed_application":true,"company":"fictional labs","role":"rust engineer","job_url":null});
        match index {
            0 => {}
            1 => row["confirmed_application"] = json!(false),
            2 => row["company"] = json!("other"),
            3 => row["role"] = json!("other"),
            4 => {
                row["job_url"] = json!("https://www.naukri.com/job-listings-fictional-123456789012")
            }
            5 => row["job_url"] = json!("https://example.org/other"),
            6 => company = Value::Null,
            7 => job["job_url"] = Value::Null,
            8 => {
                job["job_url"] = Value::Null;
                row["job_url"] = json!("https://example.org/other");
            }
            9 => {
                job["application_url"] =
                    json!("https://boards.greenhouse.io/fictional/jobs/12345?ref=fixture");
                row["job_url"] = json!("https://job-boards.greenhouse.io/fictional/jobs/12345");
            }
            10 => {
                job["application_url"] =
                    json!("https://jobs.lever.co/fictional/1234567890abcdef/apply");
                row["job_url"] = json!("https://jobs.lever.co/fictional/1234567890abcdef");
            }
            11 => {
                job["application_url"] =
                    json!("https://jobs.smartrecruiters.com/Fictional/123456-Rust?oga=true");
                row["job_url"] = json!("https://jobs.smartrecruiters.com/Fictional/123456");
            }
            12 => {
                company["name"] = json!("Straße");
                row["company"] = json!("STRASSE");
            }
            13 => job["title"] = json!("Other"),
            14 => row["job_url"] = json!(""),
            _ => {
                job["job_url"] = json!("http://127.0.0.1/private");
                row["job_url"] = json!("https://example.org/other");
            }
        }
        cases.push((job, company, vec![row]));
    }
    let expected =
        original(json!({"history":cases.iter().map(|(j,c,h)|json!([j,c,h])).collect::<Vec<_>>()}));
    for (index, (job, company, history)) in cases.into_iter().enumerate() {
        assert_eq!(
            reviewed_history::previously_applied(
                &job,
                (!company.is_null()).then_some(&company),
                &history
            ),
            expected[index].as_bool().unwrap(),
            "history {index}"
        );
    }
}
