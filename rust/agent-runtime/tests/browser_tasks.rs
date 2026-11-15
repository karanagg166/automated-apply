use automated_apply_agents::browser_profiles::tasks;
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
fn python(raw: Value) -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let code = r#"
import ast,json,sys
from pathlib import Path
from uuid import UUID
from typing import Literal
from types import SimpleNamespace
from urllib.parse import urlsplit
from pydantic import BaseModel,ConfigDict,Field
class Contract(BaseModel):model_config=ConfigDict(extra='forbid',hide_input_in_errors=True,validate_assignment=True)
scope=dict(UUID=UUID,Literal=Literal,Field=Field,Contract=Contract,urlsplit=urlsplit)
tree=ast.parse(Path('backend/app/browser/extension_tasks.py').read_text());names={'TaskCounts','TaskCapabilities','ExtensionTask','permitted_navigation','field_question'};nodes=[n for n in tree.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name in names];exec(compile(ast.Module(body=nodes,type_ignores=[]),'task-oracle','exec'),scope)
next_node=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='NEXT' for t in n.targets));exec(compile(ast.Module(body=[next_node],type_ignores=[]),'task-next-oracle','exec'),scope)
raw=json.load(sys.stdin);out={'next':scope['NEXT'],'navigation':[scope['permitted_navigation'](v,u) for v,u in raw['navigation']],'questions':[scope['field_question'](SimpleNamespace(**f)) for f in raw['fields']],'tasks':[]}
for value in raw['tasks']:
 try:out['tasks'].append({'ok':scope['ExtensionTask'].model_validate(value).model_dump(mode='json')})
 except ValueError:out['tasks'].append({'error':True})
assert 'backend.app.core.config' not in sys.modules
print(json.dumps(out))
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
    let out = child.wait_with_output().unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    serde_json::from_slice(&out.stdout).unwrap()
}
fn task() -> Value {
    json!({"id":"11111111-1111-4111-8111-111111111111","version":4,"application_id":"22222222-2222-4222-8222-222222222222","job_id":"33333333-3333-4333-8333-333333333333","company_name":null,"job_title":"Fictional Rust role","packet_revision":2,"profile_version":4,"context_digest":"d".repeat(64),"target_url":"https://example.com/form","current_url":"https://example.com/form","browser_session_id":"44444444-4444-4444-8444-444444444444","tab_id":null,"state":"PACKET_READY","challenge_state":"UNKNOWN","step":null,"plan_id":null,"authorization_id":null,"field_answer_revisions":{},"verified_receipts":[],"reason":null,"next_action":"Inspect this application step and review its answers.","mode":"ASSISTED_FILL","capabilities":{},"counts":{},"browser_connection":"unverified","tab_active":false,"updated_at":"2026-11-16T00:00:00Z"})
}
#[test]
fn browser_tasks_saved_defaults_navigation_questions_and_next_actions_match_actual_python() {
    let base = task();
    let mut values = vec![base.clone()];
    for state in [
        "PAUSED",
        "FILLING",
        "FAILED_FINAL",
        "READY_FOR_SUBMISSION",
        "SUBMISSION_UNKNOWN",
        "SUBMITTED_CONFIRMED",
    ] {
        let mut v = base.clone();
        v["state"] = json!(state);
        values.push(v);
    }
    let mut invalid = base.clone();
    invalid["unknown"] = json!(true);
    values.push(invalid);
    let mut invalid = base.clone();
    invalid["capabilities"]["reviewed_submission"] = json!(true);
    values.push(invalid);
    let target = json!({"target_url":"https://example.com/form"});
    let navigation = vec![
        json!([target, "https://example.com/form"]),
        json!([target, "https://example.com/other"]),
        json!([target, "https://example.com/form?next=1"]),
        json!([target, "https://example.com/form#step"]),
        json!([target, "http://example.com/form"]),
        json!([target, "https://other.example/form"]),
        json!([{"target_url":"http://127.0.0.1:12345/form"},"http://127.0.0.1:12345/form"]),
        json!([{"target_url":"https://user@example.com/form"},"https://user@example.com/form"]),
    ];
    let fields = vec![
        json!({"label":"Date","group_label":null,"section":"Education","page_step":"Step 2"}),
        json!({"label":"Date","group_label":"Start date","section":"Previous role","page_step":"Step 1"}),
        json!({"label":"Experience","group_label":"","section":"Experience","page_step":"Experience"}),
        json!({"label":"项目","group_label":null,"section":"经历","page_step":null}),
        json!({"label":"","group_label":null,"section":null,"page_step":null}),
    ];
    let oracle = python(json!({"tasks":values,"navigation":navigation,"fields":fields}));
    for (k, v) in oracle["next"].as_object().unwrap() {
        assert_eq!(tasks::next_action(k).unwrap(), v.as_str().unwrap());
    }
    for (i, v) in values.iter().enumerate() {
        let actual = match tasks::validate(v.clone()) {
            Ok(v) => json!({"ok":v}),
            Err(_) => json!({"error":true}),
        };
        assert_eq!(actual, oracle["tasks"][i], "{v}");
    }
    for (i, pair) in navigation.iter().enumerate() {
        assert_eq!(
            json!(tasks::navigation(&pair[0], pair[1].as_str().unwrap())),
            oracle["navigation"][i]
        );
    }
    for (i, f) in fields.iter().enumerate() {
        assert_eq!(
            json!(tasks::field_question(f).unwrap()),
            oracle["questions"][i]
        );
    }
    assert_eq!(values.len(), 9);
    assert_eq!(oracle["next"].as_object().unwrap().len(), 14);
}
