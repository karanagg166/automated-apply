//! Source-stage actual-function oracles; deferred to the complete combined gate.
use automated_apply_agents::execution::{question_answers, questionnaire_steps as steps};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
fn oracle(mode: &str, cases: &[Value]) -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let script = r#"
import ast,asyncio,base64,hashlib,json,re,sys,types,copy
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from pydantic import TypeAdapter,ValidationError
from backend.app.core.urls import PublicHTTPSURL
class ToolDenied(Exception):pass
ProfileConflictError=ToolDenied
scope=dict(globals())
class Imports(ast.NodeTransformer):
 def visit_ImportFrom(self,node):return None
 def visit_Import(self,node):return None
def load(path,names):
 tree=ast.parse(Path(path).read_text());nodes=[]
 for n in tree.body:
  name=n.name if isinstance(n,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)) else n.targets[0].id if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) else None
  if name in names:nodes.append(Imports().visit(n))
 assert len(nodes)==len(names),(path,names)
 exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),path,'exec'),scope)
load('backend/app/knowledge/missing_input.py',{'SENSITIVE','permitted'})
load('backend/app/services/applications/platforms/base.py',{'safe_url'})
load('backend/app/execution/questions.py',{'field_answer','validate'})
load('backend/app/core/text.py',{'normalize','phrase_in'})
load('backend/app/services/profile_link_resolver.py',{'ALIASES','resource_types','is_file_upload'})
load('backend/app/knowledge/narrative_phrases.py',{'PHRASES','canonical_question'})
scope['QuestionClassification']=lambda question_type,field=None:types.SimpleNamespace(question_type=question_type,field=field)
load('backend/app/services/application_question_classifier.py',{'ApplicationQuestionClassifier'})
load('backend/app/execution/naukri_questionnaires.py',{'answer_bank_key','reuse_key','receive'})
load('backend/app/execution/naukri_submission.py',{'retain_account_observation'})
scope['submission']=types.SimpleNamespace(PROFILE_URL='https://www.naukri.com/mnjuser/profile',retain_account_observation=scope['retain_account_observation'])
async def context(*args,**kwargs):return None
async def instant(s):return s.now
scope.update(context=context,instant=instant)
class Data(types.SimpleNamespace):
 def model_dump(self,**kwargs):return copy.deepcopy(self.raw)
def data(v):return Data(raw=v,**v) if isinstance(v,dict) else None
raw=json.load(sys.stdin);out=[]
async def main():
 for c in raw['cases']:
  now=datetime.fromisoformat(c['now']);error=None;value=None
  try:
   if raw['mode']=='answers':value=scope['validate'](c['question'],c['answer'],now)
   elif raw['mode']=='reuse':value=scope['reuse_key'](c['work'],c['step'])
   else:
    value=copy.deepcopy(c['work']);report={'kind':None,'reason':None,'execution':None,'observed_url':None,'requisition':None,'stage':None,'job':None,'questionnaire':None,'document_id':None,'step_sha256':None,**c['report']}
    for key in ('execution','job','questionnaire'):report[key]=data(report[key])
    await scope['receive'](types.SimpleNamespace(now=now),value,Data(**report),None)
  except ToolDenied as e:error=str(e)
  out.append({'value':value,'error':error})
 assert 'backend.app.core.config' not in sys.modules
 print(json.dumps(out))
asyncio.run(main())
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
        .write_all(json!({"mode":mode,"cases":cases}).to_string().as_bytes())
        .unwrap();
    let out = child.wait_with_output().unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    serde_json::from_slice(&out.stdout).unwrap()
}
fn now() -> DateTime<Utc> {
    DateTime::parse_from_rfc3339("2026-10-15T00:00:00Z")
        .unwrap()
        .with_timezone(&Utc)
}
#[test]
fn owner_answer_length_options_types_sensitivity_expiry_and_dst_match_actual_validation() {
    let mut cases = vec![];
    for (kind, answers) in [
        ("number", vec!["-12.5", "12", "+1", "1e2", "NaN"]),
        (
            "date",
            vec!["2026-02-28", "2026-02-30", "2026-2-01", "0000-01-01"],
        ),
        ("month", vec!["2026-11", "2026-13", "2026-1"]),
        (
            "email",
            vec![
                "fictional@example.com",
                "bad@localhost",
                "bad email@example.com",
            ],
        ),
        (
            "url",
            vec![
                "https://example.com/profile",
                "http://example.com",
                "https://127.0.0.1/",
            ],
        ),
        (
            "text",
            vec![
                "Verified fictional answer",
                " ",
                "api_key: fictional-credential",
            ],
        ),
    ] {
        for answer in answers {
            cases.push(json!({"question":{"question":"Provide the observed field","form_kind":kind,"answer_type":"text","options":[],"max_characters":4000},"answer":answer,"now":now().to_rfc3339()}));
        }
    }
    for question in [
        "What salary do you expect?",
        "Can you relocate?",
        "Are you authorized to work?",
        "Share a verified fact",
        "Your passport number",
    ] {
        cases.push(json!({"question":{"question":question,"answer_type":"text","options":[],"max_characters":4000},"answer":"Verified factual answer","now":now().to_rfc3339()}));
    }
    for options in [json!([]), json!(["Yes", "No"])] {
        for answer in [
            "Yes",
            "No",
            "yes",
            "Maybe",
            "Yes | 2026-10-16T12:30 Asia/Kolkata",
            "2026-10-16T12:30 Asia/Kolkata",
            "2026-11-01T01:30 America/New_York",
            "2026-11-01T03:30 America/New_York",
            "2026-10-01T00:00 UTC",
            "2027-10-01T00:00 UTC",
            "2026-10-16T12:30 Invalid/Zone",
        ] {
            cases.push(json!({"question":{"question":"Interview availability","answer_type":"availability","options":options,"max_characters":4000},"answer":answer,"now":now().to_rfc3339()}));
        }
    }
    let expected = oracle("answers", &cases);
    for (index, c) in cases.iter().enumerate() {
        let answer =
            question_answers::validate(&c["question"], c["answer"].as_str().unwrap(), now());
        if let Some(error) = expected[index]["error"].as_str() {
            assert_eq!(answer.unwrap_err().0, error, "case {index}");
        } else {
            assert_eq!(
                json!(answer.unwrap()),
                expected[index]["value"],
                "case {index}"
            );
        }
    }
}
fn work() -> Value {
    json!({"id":"11111111-1111-4111-8111-111111111111","candidate_profile_id":"22222222-2222-4222-8222-222222222222","profile_version":4,"operation":"inspect_questionnaire","url":"https://www.naukri.com/job-listings-fictional-123456789012","requisition":"123456789012","status":"executing","stage":"QUESTIONS","account_sha256":"a".repeat(64),"binding":{"tab_id":50},"upload_preflight":{"sha256":"b".repeat(64),"byte_count":120},"admitted_actions":[{"fingerprint":"apply:initial"}],"facts":{"requisition":"123456789012","title":"Rust Engineer","company":"Fictional Labs","description":"Fictional development rôle","location":"Remote","skills":["Rust"],"experience_min":0.0,"experience_max":2.0,"salary_min":null,"salary_max":null}})
}
#[test]
fn original_questionnaire_step_transitions_match_actual_receive_and_never_repeat_answer() {
    let mut cases = vec![];
    for question in [
        "What is your full name?",
        "How many years of experience?",
        "Expected salary?",
        "Why this role?",
        "Your login email?",
        "Do you accept consent?",
        "Your passport number?",
        "Share a project",
    ] {
        for variation in 0..5 {
            let mut work = work();
            let mut step = json!({"document_id":"33333333-3333-4333-8333-333333333333","question":question,"answer_kind":"text","options":[],"max_characters":4000});
            step["step_sha256"] = json!(steps::step_hash(&work, &step));
            match variation{1=>work["questionnaire_document_id"]=json!("44444444-4444-4444-8444-444444444444"),2=>work["questionnaire_steps"]=json!(20),3=>work["admitted_actions"].as_array_mut().unwrap().push(json!({"fingerprint":format!("answer_questionnaire:{}",step["step_sha256"].as_str().unwrap())})),4=>work["questionnaire_answer"]=json!({"answer":"Verified answer","step_sha256":step["step_sha256"],"answer_expires_at":"2026-10-16T00:00:00Z"}),_=>{}}
            let report = json!({"kind":"questionnaire","observed_url":work["url"],"requisition":work["requisition"],"questionnaire":step});
            cases.push(json!({"work":work,"report":report,"now":now().to_rfc3339()}));
        }
    }
    for operation in steps::OPERATIONS {
        for kind in ["failed", "needs_input"] {
            let mut work = work();
            work["operation"] = json!(operation);
            cases.push(json!({"work":work,"report":{"kind":kind,"reason":"fixture_connection_lost"},"now":now().to_rfc3339()}));
        }
    }
    let expected = oracle("steps", &cases);
    for (index, c) in cases.iter().enumerate() {
        let mut actual = c["work"].clone();
        let result = steps::transition(&mut actual, &c["report"], now());
        assert_eq!(
            json!(result.err().map(|e| e.0)),
            expected[index]["error"],
            "case {index}"
        );
        assert_eq!(actual, expected[index]["value"], "case {index}");
    }
}
#[test]
fn reusable_answer_identity_matches_actual_full_width_hash_and_separates_job_context() {
    let mut cases = vec![];
    for question in [
        "What is your full name?",
        "Your GitHub URL?",
        "Are you authorized to work?",
        "Expected salary?",
        "Describe a project you built",
        "Why this company?",
    ] {
        for employer in ["Fictional Labs", "Other Fictional Employer"] {
            let mut work = work();
            work["facts"]["company"] = json!(employer);
            cases.push(json!({"work":work,"step":{"question":question,"answer_kind":"text","options":[]},"now":now().to_rfc3339()}));
        }
    }
    let expected = oracle("reuse", &cases);
    for (index, c) in cases.iter().enumerate() {
        let key = steps::reuse_key(&c["work"], &c["step"]);
        assert_eq!(key.len(), 50);
        assert_eq!(json!(key), expected[index]["value"], "case {index}");
    }
}

#[test]
fn refreshed_questionnaire_job_cannot_change_salary_units_or_other_requirement_groups_before_answering()
 {
    let mut original = work();
    original["operation"] = json!("refresh_questionnaire_job");
    original["facts"]["salary_min"] = json!(120000.0);
    original["facts"]["salary_max"] = json!(200000.0);
    original["facts"]["salary_currency"] = json!("INR");
    original["facts"]["salary_period"] = json!("year");
    original["facts"]["remote_type"] = json!("remote");
    original["facts"]["employment_type"] = json!("full_time");
    for (field, value) in [
        ("salary_currency", json!("USD")),
        ("salary_period", json!("month")),
        ("salary_max", json!(300000.0)),
        ("remote_type", json!("onsite")),
        ("employment_type", json!("contract")),
    ] {
        let mut job = original["facts"].clone();
        job[field] = value;
        let report = json!({"kind":"job_facts","observed_url":original["url"],"requisition":original["requisition"],"job":job});
        let mut attempt = original.clone();
        assert_eq!(
            steps::transition(&mut attempt, &report, now())
                .unwrap_err()
                .0,
            "questionnaire_job_requirements_changed"
        );
        assert_eq!(attempt, original);
    }
}
