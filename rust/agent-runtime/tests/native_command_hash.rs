//! Actual source-model serialization oracle; isolated and unrun until the final gate.
use automated_apply_agents::browser_profiles::native_contract::payload_hash;
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};

fn python(raw: &[String]) -> Vec<String> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let script = r#"
import ast,hashlib,json,re,sys,types
from pathlib import Path
from datetime import date,datetime,timedelta,timezone
from typing import Annotated,Literal
from uuid import UUID,uuid4
from pydantic import BaseModel,ConfigDict,Field,SecretStr,StrictBool,field_validator,model_validator
from backend.app.core.urls import PublicHTTPSURL
module=types.ModuleType('actual_native_command_oracle');sys.modules[module.__name__]=module
scope=module.__dict__;scope.update({key:value for key,value in globals().copy().items() if not key.startswith('__')})
def load(path,names):
 tree=ast.parse(Path(path).read_text());body=[]
 for node in tree.body:
  name=node.name if isinstance(node,ast.ClassDef) else node.targets[0].id if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) else None
  if name in names:body.append(node)
 assert len(body)==len(names),(path,names)
 exec(compile(ast.Module(body=body,type_ignores=[]),path,'exec'),scope)
load('backend/app/browser/contracts.py',{'Contract','Text','Kind','FormField','ManualControl','Inspection','FieldResult','FillReceipt'})
load('backend/app/local_agent/intents.py',{'IntentKind','ROUTING_CATEGORIES','Intent'})
load('backend/app/execution/contracts.py',{'Contract'})
tree=ast.parse(Path('backend/app/execution/profile_sync.py').read_text());fields=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='FIELDS' for t in n.targets))
profile_module=types.ModuleType('backend.app.execution.profile_sync');profile_module.FIELDS=fields;sys.modules[profile_module.__name__]=profile_module
load('backend/app/execution/queue_contracts.py',{'ObservedNaukriJob','NaukriExecutionObservation','NaukriQuestionnaire','NaukriWorkReport'})
load('backend/app/local_agent/contracts.py',{'StrictModel','Operation','Command'})
out=[hashlib.sha256(scope['Command'].model_validate_json(raw).model_dump_json().encode()).hexdigest() for raw in json.load(sys.stdin)]
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
        .write_all(serde_json::to_string(raw).unwrap().as_bytes())
        .unwrap();
    let output = child.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).unwrap()
}
const REQUEST: &str = "11111111-1111-4111-8111-111111111111";
fn command(name: &str, extra: Value) -> String {
    let mut input = json!({"command":name,"request_id":REQUEST});
    for (k, v) in extra.as_object().unwrap() {
        input[k] = v.clone();
    }
    input.to_string()
}
#[test]
fn native_command_defaults_masked_secret_models_dates_numbers_and_raw_dictionary_order_match_python()
 {
    let mut cases = Vec::new();
    for name in [
        "health",
        "open_application_task",
        "inspect_form",
        "authorize_form",
        "record_form_fill",
        "poll_naukri_work",
    ] {
        cases.push(command(name, json!({})));
    }
    for secret in ["a".repeat(64), "b".repeat(64)] {
        cases.push(command("connect_chrome_profile",json!({"profile_secret":secret,"profile_binding_id":"AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA","profile_label":"Fictional व्यक्ति"})));
    }
    cases.push(command("inspect_form",json!({"inspection":{"document_id":REQUEST,"url":"https://example.com/apply","fields":[{"field_id":"f1","kind":"select","label":"Language","options":["हिन्दी","English"]}],"manual_controls":[{"control_id":"u1","kind":"frame","label":"Fictional component","reason":"manual"}]}})));
    cases.push(command("record_form_fill",json!({"receipt":{"plan_id":"AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA","results":[{"status":"filled","field_id":"f1"}],"state":"form_filled"}})));
    cases.push(command(
        "conversation",
        json!({"intent":{"category":"PREPARE_APPLICATION","url":"HTTPS://Example.com:443"}}),
    ));
    for experience in [0.0, 1.0, 1.5, 0.0000001] {
        cases.push(command("finish_naukri_work",json!({"work_report":{"kind":"job_facts","job":{"requisition":"123456789012","title":" Fictional Engineer ","company":" Fictional Employer ","location":" Fictional City ","description":" Fictional duties ","skills":[" Rust ","Rust"," Python "],"experience_min":experience,"posted_at":"2020-01-02T12:34:56.123+00:00","salary_min":1000000000000.0,"evidence_sha256":"a".repeat(64)}}})));
    }
    cases.push(command("finish_naukri_work",json!({"work_report":{"kind":"questionnaire","questionnaire":{"document_id":REQUEST,"step_sha256":"a".repeat(64),"question":"Preferred shift?","answer_kind":"choice","options":["Morning","Evening"]}}})));
    for fields in [
        r#""preferences":{"z":1,"a":2},"skills":["Rust"]"#,
        r#""skills":["Rust"],"preferences":{"a":2,"z":1}"#,
    ] {
        cases.push(format!(r#"{{"command":"finish_naukri_work","request_id":"{REQUEST}","work_report":{{"kind":"execution_observation","execution":{{"state":"PROFILE_OBSERVED","document_id":"fictional-document","evidence_sha256":"{}","account_sha256":"{}","profile_fields":{{{fields}}}}}}}}}"#,"a".repeat(64),"b".repeat(64)));
    }
    let expected = python(&cases);
    assert_eq!(expected.len(), 18);
    for (index, raw) in cases.iter().enumerate() {
        assert_eq!(
            payload_hash(raw.as_bytes()).unwrap(),
            expected[index],
            "case {index}"
        );
    }
    assert_eq!(
        expected[6], expected[7],
        "SecretStr serialization masks either input secret"
    );
    assert_ne!(
        expected[16], expected[17],
        "opaque dict insertion order is retained by the legacy recipe"
    );
}
#[test]
fn native_command_validation_denies_duplicate_fields_invalid_intent_and_questionnaire_without_authority()
 {
    let cases = [
        command(
            "inspect_form",
            json!({"inspection":{"document_id":REQUEST,"url":"https://example.com","fields":[{"field_id":"f1","kind":"text","label":"Name"},{"field_id":"f1","kind":"text","label":"Other"}]}}),
        ),
        command(
            "conversation",
            json!({"intent":{"category":"HELP","job_id":REQUEST}}),
        ),
        command(
            "conversation",
            json!({"intent":{"category":"HELP","url":"https://example.com"}}),
        ),
        command(
            "conversation",
            json!({"intent":{"category":"PREPARE_APPLICATION"}}),
        ),
        command("health", json!({"url":"https://127.0.0.1/"})),
        command(
            "finish_naukri_work",
            json!({"work_report":{"kind":"questionnaire","questionnaire":{"document_id":REQUEST,"step_sha256":"a".repeat(64),"question":"Shift?","answer_kind":"choice","options":["A","A"]}}}),
        ),
        command(
            "finish_naukri_work",
            json!({"work_report":{"kind":"questionnaire","questionnaire":{"document_id":REQUEST,"step_sha256":"a".repeat(64),"question":"Shift?","answer_kind":"choice","options":[]}}}),
        ),
        command(
            "finish_naukri_work",
            json!({"work_report":{"kind":"execution_observation","execution":{"state":"PROFILE_OBSERVED","document_id":"fictional-document","evidence_sha256":"a".repeat(64),"account_sha256":"b".repeat(64),"profile_fields":{"unknown_personal_field":"unsupported"}}}}),
        ),
    ];
    for raw in cases {
        assert!(payload_hash(raw.as_bytes()).is_err());
    }
}
