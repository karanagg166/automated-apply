//! Deferred final-gate comparisons against actual legacy DTO/policy code; no application settings.
use automated_apply_agents::execution::{
    contracts::{self, Kind},
    legacy_policy,
};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
fn actual(raw: Value) -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let script = r#"
import ast,json,runpy,sys,types
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from typing import Literal
from uuid import UUID
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
PublicHTTPSURL=runpy.run_path('backend/app/core/urls.py')['PublicHTTPSURL']
module=types.ModuleType('actual_execution_owner');sys.modules[module.__name__]=module
scope=module.__dict__;scope.update({k:v for k,v in globals().copy().items() if not k.startswith('__')})
def load(path,names):
 body=[]
 for n in ast.parse(Path(path).read_text()).body:
  name=n.name if isinstance(n,(ast.ClassDef,ast.FunctionDef)) else n.targets[0].id if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) else None
  if name in names:body.append(n)
 assert len(body)==len(names)
 exec(compile(ast.Module(body=body,type_ignores=[]),path,'exec'),scope)
raw=json.load(sys.stdin)
if 'contracts' in raw:
 load('backend/app/execution/contracts.py',{'Contract','QuestionAnswer','AutomationPolicy','AutomationPolicyUpdate','AutomationControl','ImportJob','ImportBatch'})
 out=[]
 for kind,value in raw['contracts']:
  try:out.append(scope[kind].model_validate(value).model_dump(mode='json'))
  except ValueError:out.append(None)
else:
 load('backend/app/execution/recurring.py',{'policy_reason'})
 class Clock(datetime):
  @classmethod
  def now(cls,tz=None):return datetime.fromisoformat(raw['now'])
 scope['datetime']=Clock
 out=[scope['policy_reason'](types.SimpleNamespace(**j),d,types.SimpleNamespace(**p)) for j,d,p in raw['reasons']]
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
        .write_all(raw.to_string().as_bytes())
        .unwrap();
    let output = child.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).unwrap()
}
fn policy() -> Value {
    json!({"profile_version":4,"resume_resource_id":"AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA","resume_version":"a".repeat(64),"allowed_roles":[" Rust Engineer ","RUST ENGINEER"],"allowed_locations":[" Remote "],"experience_min":0,"experience_max":2})
}
#[test]
fn owner_preparation_dtos_match_actual_strict_answers_scoped_policy_and_import_validation() {
    let mut cases = Vec::new();
    for value in [
        json!({"expected_revision":2,"answer":"  factual answer  "}),
        json!({"expected_revision":2.0,"answer":"yes"}),
        json!({"expected_revision":"2","answer":"yes"}),
        json!({"expected_revision":true,"answer":"yes"}),
        json!({"expected_revision":2,"answer":"\u{1c}"}),
        json!({"expected_revision":2,"answer":"é".repeat(4000)}),
        json!({"expected_revision":2,"answer":" ".repeat(4001)}),
    ] {
        cases.push(("QuestionAnswer", Kind::QuestionAnswer, value));
    }
    for index in 0..11 {
        let mut p = policy();
        match index {
            0 => {}
            1 => p["source"] = json!("gmail_job_alerts"),
            2 => {
                p["source"] = json!("gmail_job_alerts");
                p["gmail_account_id"] = json!("AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA");
                p["gmail_policy_version"] = json!(1);
            }
            3 => p["minimum_match_score"] = json!(50),
            4 => p["max_applications_per_day"] = json!(1),
            5 => p["permitted_actions"] = json!(["APPLY"]),
            6 => p["experience_min"] = json!(3),
            7 => p["allowed_roles"] = json!([" "]),
            8 => p["allowed_locations"] = json!(["ß", "SS"]),
            9 => p["excluded_companies"] = json!([" "]),
            _ => p["allowed_roles"] = json!([" ".repeat(201)]),
        };
        cases.push(("AutomationPolicy", Kind::AutomationPolicy, p));
    }
    for value in [
        json!({"action":"start","expected_revision":0}),
        json!({"action":"resume","expected_revision":1}),
        json!({"action":"stop","expected_revision":-1}),
    ] {
        cases.push(("AutomationControl", Kind::AutomationControl, value));
    }
    cases.push((
        "AutomationPolicyUpdate",
        Kind::AutomationPolicyUpdate,
        json!({"expected_revision":0,"policy":policy()}),
    ));
    for index in 0..11 {
        let mut j = json!({"url":"https://www.naukri.com/job-listings-fictional-123456789012","title":" Rust Engineer ","employer":" Fictional Labs "});
        match index {
            0 => {}
            1 => j["title"] = json!(" "),
            2 => j["experience_min"] = json!(-1),
            3 => {
                j["salary_min"] = json!(100);
                j["salary_max"] = json!(50);
            }
            4 => j["application_url"] = json!("http://example.org/apply"),
            5 => j["application_url"] = json!("https://127.0.0.1/apply"),
            6 => j["application_url"] = json!("https://EXAMPLE.ORG/apply"),
            7 => j["posted_at"] = json!("2026-01-01T12:00:00"),
            8 => j["posted_at"] = json!("2026-01-01T12:00:00Z"),
            9 => j["posting_status"] = json!("active"),
            _ => {
                j["posting_status"] = json!("active");
                j["observed_at"] = json!("2026-01-01T12:00:00+05:30");
            }
        }
        cases.push(("ImportBatch", Kind::ImportBatch, json!({"jobs":[j]})));
    }
    for index in 0..4 {
        let mut p = policy();
        match index {
            0 => p["profile_version"] = json!("4"),
            1 => p["experience_min"] = json!("0.0"),
            2 => p["telegram_questions"] = json!("false"),
            _ => p["max_applications_per_day"] = json!(false),
        }
        cases.push(("AutomationPolicy", Kind::AutomationPolicy, p));
    }
    let expected = actual(
        json!({"contracts":cases.iter().map(|(name,_,v)|json!([name,v])).collect::<Vec<_>>()}),
    );
    assert_eq!(cases.len(), 37);
    for (index, (name, kind, value)) in cases.into_iter().enumerate() {
        let got = contracts::normalize(kind, value);
        if expected[index].is_null() {
            assert!(got.is_err(), "{index} {name}");
        } else {
            assert_eq!(got.unwrap(), expected[index], "{index} {name}");
        }
    }
}
#[test]
fn recurring_preparation_reason_matches_actual_legacy_policy_without_changing_application_filters()
{
    let now = DateTime::parse_from_rfc3339("2026-11-16T12:00:00Z")
        .unwrap()
        .with_timezone(&Utc);
    let mut p = contracts::normalize(Kind::AutomationPolicy, policy()).unwrap();
    p["allowed_roles"] = json!(["rust engineer"]);
    p["allowed_locations"] = json!(["remote"]);
    let job = json!({"location":"Remote","discovery_metadata":{"location":"Remote","experience_min_years":0,"experience_max_years":2,"skills_required":["Rust"],"date_posted":"2026-11-15T12:00:00+00:00","data_provenance":{"experience_requirement":"required"}}});
    let decision = json!({"state":"ELIGIBLE","reason":"preparation_only_owner_review_required","title":"Rust Engineer","employer":"Fictional Labs","match":{"match_score":90,"missing_skills":[],"negative_factors":[],"unknown_fields":["company_size","salary"]}});
    let mut cases = Vec::new();
    for index in 0..16 {
        let (mut j, mut d, mut policy) = (job.clone(), decision.clone(), p.clone());
        match index {
            0 => {}
            1 => d["state"] = json!("NEEDS_INPUT"),
            2 => d["title"] = json!("Other"),
            3 => policy["excluded_companies"] = json!(["fictional labs"]),
            4 => j["location"] = json!("Other"),
            5 => j["discovery_metadata"]["location"] = json!("Other"),
            6 => {
                j["discovery_metadata"]["data_provenance"]["experience_requirement"] =
                    json!("preferred")
            }
            7 => j["discovery_metadata"]["experience_max_years"] = Value::Null,
            8 => j["discovery_metadata"]["experience_max_years"] = json!(3),
            9 => j["discovery_metadata"]["date_posted"] = json!("bad"),
            10 => j["discovery_metadata"]["date_posted"] = json!("2026-10-01T00:00:00Z"),
            11 => j["discovery_metadata"]["date_posted"] = json!("2026-11-17T00:00:00Z"),
            12 => j["discovery_metadata"]["skills_required"] = json!([]),
            13 => d["match"]["match_score"] = json!(79),
            14 => d["match"]["negative_factors"] = json!(["Seniority"]),
            _ => d["match"]["unknown_fields"] = json!(["remote_policy"]),
        }
        cases.push((j, d, policy));
    }
    let expected = actual(
        json!({"now":now.to_rfc3339(),"reasons":cases.iter().map(|(j,d,p)|json!([j,d,p])).collect::<Vec<_>>()}),
    );
    for (index, (j, d, p)) in cases.into_iter().enumerate() {
        assert_eq!(
            json!(legacy_policy::reason(&j, &d, &p, now).unwrap()),
            expected[index],
            "policy case {index}"
        );
    }
}
#[test]
fn naukri_capabilities_match_actual_legacy_function_without_promoting_source_to_live_acceptance() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let script = r#"
import ast,json
from pathlib import Path
names={'EVIDENCE','capability_matrix'};body=[]
for n in ast.parse(Path('backend/app/execution/naukri.py').read_text()).body:
 name=n.name if isinstance(n,ast.FunctionDef) else n.targets[0].id if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) else None
 if name in names:body.append(n)
assert len(body)==2
scope={};exec(compile(ast.Module(body=body,type_ignores=[]),'actual_capabilities','exec'),scope)
print(json.dumps(scope['capability_matrix']()))
"#;
    let out = Command::new(root.join(".venv/bin/python"))
        .args(["-c", script])
        .current_dir(root)
        .output()
        .unwrap();
    assert!(out.status.success());
    let actual: Value = serde_json::from_slice(&out.stdout).unwrap();
    assert_eq!(
        automated_apply_agents::execution::owner_status::capabilities(),
        actual
    );
    assert_eq!(actual["live_verified"], false);
    assert_eq!(actual["recurring_submission"]["enabled"], false);
}
