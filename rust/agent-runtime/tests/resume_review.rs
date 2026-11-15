use automated_apply_agents::{
    Failure,
    resume_review::{approval_request, canonical_source, differences, source_request},
};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
fn python(raw: Value) -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let code = r#"
import ast,json,re,sys
from pathlib import Path
from uuid import UUID
from typing import Literal
from urllib.parse import parse_qs,urlsplit
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
from backend.app.ai.schemas import Contract
from backend.app.schemas.candidate_profile import CandidateProfileCreate
from backend.app.schemas.candidate_resources import EvidenceWrite
scope=dict(Literal=Literal,re=re,parse_qs=parse_qs,urlsplit=urlsplit,UUID=UUID,BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,field_validator=field_validator,model_validator=model_validator,Contract=Contract,CandidateProfileCreate=CandidateProfileCreate,EvidenceWrite=EvidenceWrite)
def extract(path,names):
 tree=ast.parse(Path(path).read_text());nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names];exec(compile(ast.Module(body=nodes,type_ignores=[]),path,'exec'),scope)
extract('backend/app/resume_sync/source.py',{'canonical_source'})
extract('backend/app/dashboard/schemas.py',{'ResumeConfirm'})
extract('backend/app/resume_sync/schemas.py',{'SourceSettings','ApproveResume'})
scope['CATEGORIES']=('skills','work_experience','employment_dates','education','projects','professional_links','achievements','other_claims')
extract('backend/app/resume_sync/facts.py',{'verified_context','differences'})
raw=json.load(sys.stdin);output={}
for key,model in [('sources',scope['SourceSettings']),('approvals',scope['ApproveResume'])]:
 output[key]=[]
 for value in raw[key]:
  try:output[key].append({'ok':model.model_validate(value).model_dump(mode='json')})
  except ValueError:output[key].append({'error':True})
output['urls']=[]
for value in raw['urls']:
 try:output['urls'].append({'ok':scope['canonical_source'](*value)})
 except ValueError:output['urls'].append({'error':True})
output['differences']=[scope['differences'](*case) for case in raw['differences']]
assert 'backend.app.core.config' not in sys.modules
print(json.dumps(output))
"#;
    let mut child = Command::new(root.join(".venv/bin/python"))
        .args(["-c", code])
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
fn profile() -> Value {
    json!({"full_name":"Fictional Person","email":"fictional@example.com","verified_skills":["Rust"]})
}
#[test]
fn resume_source_and_approval_inputs_match_actual_python_models() {
    let url = "https://drive.google.com/file/d/Fictional_File_123/view?usp=sharing";
    let source = json!({"canonical_url":url,"expected_generation":1});
    let approval = json!({"owner_confirmed":true,"expected_generation":1,"profile":profile()});
    let mut sources = vec![
        source.clone(),
        json!({"canonical_url":format!("  {url}  "),"expected_generation":1}),
    ];
    let mut approvals = vec![approval.clone()];
    for (key, values) in [
        (
            "expected_generation",
            vec![json!(0), json!("2"), json!(true), json!(2.0), json!(null)],
        ),
        ("sync_enabled", vec![json!("false"), json!(1), json!(null)]),
        (
            "interval_hours",
            vec![json!(0), json!(168), json!(169), json!("24")],
        ),
    ] {
        for value in values {
            let mut case = source.clone();
            case[key] = value;
            sources.push(case);
        }
    }
    for (key, values) in [
        (
            "owner_confirmed",
            vec![json!(1), json!("true"), json!(false)],
        ),
        (
            "expected_profile_version",
            vec![json!("2"), json!(null), json!(0)],
        ),
        ("allow_skill_removals", vec![json!("yes"), json!(0)]),
        (
            "expected_sha256",
            vec![json!("a".repeat(64)), json!("A".repeat(64))],
        ),
        (
            "evidence",
            vec![
                json!([{"evidence_type":"other","title":"Claim","content":"Fictional claim","user_confirmed":true}]),
                json!([{"evidence_type":"other","title":"Claim","content":"Fictional claim","user_confirmed":false}]),
            ],
        ),
    ] {
        for value in values {
            let mut case = approval.clone();
            case[key] = value;
            approvals.push(case);
        }
    }
    let mut extra = approval.clone();
    extra["submit"] = json!(true);
    approvals.push(extra);
    let urls = vec![
        json!([url, null]),
        json!([url, "Fictional_File_123"]),
        json!([url, "Other_File_123"]),
        json!([url.replace("https:", "HTTPS:"), null]),
        json!([url.replace("drive.google.com", "DRIVE.GOOGLE.COM"), null]),
        json!([format!("{url}&usp=second"), null]),
        json!([url.replace("usp=sharing", "usp"), null]),
        json!([format!("{url}#private"), null]),
        json!([url.replace("Fictional_File_123", "short"), null]),
        json!([url.replace("/file/d/", "/file/x/../d/"), null]),
    ];
    let expected =
        python(json!({"sources":sources,"approvals":approvals,"urls":urls,"differences":[]}));
    for (raw, wanted) in sources
        .into_iter()
        .zip(expected["sources"].as_array().unwrap())
    {
        let actual = match source_request(raw) {
            Ok(v) => {
                json!({"ok":{"canonical_url":v.canonical_url,"expected_generation":v.expected,"sync_enabled":v.enabled,"interval_hours":v.interval}})
            }
            Err(_) => json!({"error":true}),
        };
        assert_eq!(actual, *wanted);
    }
    for (raw, wanted) in approvals
        .into_iter()
        .zip(expected["approvals"].as_array().unwrap())
    {
        let actual = match approval_request(raw.clone()) {
            Ok(v) => {
                json!({"ok":{"owner_confirmed":true,"primary":raw.get("primary").cloned().unwrap_or(json!(false)),"expected_primary_resource_id":v.expected_primary,"expected_sha256":v.expected_sha256,"expected_profile_version":v.expected_profile,"expected_generation":v.expected,"profile":v.profile,"allow_skill_removals":v.allow_removals,"evidence":v.evidence}})
            }
            Err(_) => json!({"error":true}),
        };
        assert_eq!(actual, *wanted);
    }
    for (raw, wanted) in urls.into_iter().zip(expected["urls"].as_array().unwrap()) {
        let actual = match canonical_source(raw[0].as_str().unwrap(), raw[1].as_str()) {
            Ok((id, url)) => json!({"ok":[id,url]}),
            Err(_) => json!({"error":true}),
        };
        assert_eq!(actual, *wanted);
    }
}
#[test]
fn resume_differences_preserve_verified_facts_without_inferring_dates_or_removed_skills() {
    let categories = [
        "skills",
        "work_experience",
        "employment_dates",
        "education",
        "projects",
        "professional_links",
        "achievements",
        "other_claims",
    ];
    let sections = categories
        .iter()
        .map(|category| {
            (
                (*category).to_string(),
                json!([format!("Fictional {category}")]),
            )
        })
        .collect::<serde_json::Map<_, _>>();
    let current = json!({"sections":sections,"suggestions":{"verified_skills":["Rust","SQL"]},"text":"Fictional source evidence"});
    let previous = json!({"sections":{"skills":["old"],"work_experience":["Old company 2020"],"employment_dates":["Old company 2020"],"education":[],"projects":[],"professional_links":[],"achievements":[],"other_claims":[]},"suggestions":{"verified_skills":["RUST","Python"]}});
    let profile = json!({"full_name":"Fictional Person","email":"fictional@example.com","verified_experience_years":0.0,"verified_roles":[{"company":"Company","role":"Engineer","start_date":"2020-01-01","end_date":null,"highlight":"Verbatim owner fact"}],"education":[{"institution":"School","qualification":"Degree","graduation_year":2024}],"projects":[{"name":"Project","description":"Owner description","achievements":["Confirmed achievement"]}],"certifications":[{"name":"Certificate","issuer":"Issuer","issued_on":"2024-01-01"}],"github_url":"https://github.com/fictional"});
    let mut cases = vec![];
    for before in [Value::Null, previous] {
        for verified in [Value::Null, profile.clone()] {
            cases.push(json!([before, current, ["Rust", "Python"], verified]));
        }
    }
    let expected = python(json!({"sources":[],"approvals":[],"urls":[],"differences":cases}));
    for (case, wanted) in cases
        .into_iter()
        .zip(expected["differences"].as_array().unwrap())
    {
        assert_eq!(
            differences(&case[0], &case[1], &case[2], &case[3]).unwrap(),
            *wanted
        );
    }
    assert_eq!(
        canonical_source(
            "https://drive.google.com/file/d/Fictional_File_123/view",
            Some("wrong")
        )
        .err(),
        Some(Failure("invalid_resume_drive_source"))
    );
}
