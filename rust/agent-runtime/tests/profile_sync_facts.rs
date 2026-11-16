//! Actual legacy pure-function oracle, executed only with the final combined gate.
use automated_apply_agents::execution::{
    contracts::{self, Kind},
    profile_sync as sync,
};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
fn oracle(input: &Value) -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let script = r#"import ast,hashlib,json,sys,types
from pathlib import Path
class ToolDenied(Exception):pass
scope={'hashlib':hashlib,'json':json,'ToolDenied':ToolDenied}
def load(path,names):
 nodes=[]
 for n in ast.parse(Path(path).read_text()).body:
  name=n.name if isinstance(n,ast.FunctionDef) else n.targets[0].id if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) else None
  if name in names:nodes.append(n)
 assert len(nodes)==len(names),(path,names)
 exec(compile(ast.Module(body=nodes,type_ignores=[]),path,'exec'),scope)
load('backend/app/services/application_assistant.py',{'skill_key'})
load('backend/app/execution/profile_skills.py',{'skills','additions','prepared'})
for name in ['backend','backend.app','backend.app.execution']:
 module=types.ModuleType(name);module.__path__=[];sys.modules[name]=module
module=types.ModuleType('backend.app.execution.profile_skills');module.additions=scope['additions'];sys.modules[module.__name__]=module
load('backend/app/execution/profile_sync.py',{'FIELDS','SUPPORTED_WRITES','reference','comparison_value','compare','canonical'})
def result(fn,*args):
 try:return fn(*args)
 except ToolDenied as exc:return {'error':str(exc)}
raw=json.load(sys.stdin)
output={'references':[scope['reference'](v) for v in raw['references']],
'comparisons':[result(scope['compare'],c,o,a) for c,o,a in raw['comparisons']],
'additions':[result(scope['additions'],c,e) for c,e in raw['additions']],
'prepared':[result(scope['prepared'],b,a,o) for b,a,o in raw['prepared']],
'canonical':[scope['canonical'](types.SimpleNamespace(**p),types.SimpleNamespace(resource_version=r) if r else None) for p,r in raw['canonical']]}
assert 'backend.app.core.config' not in sys.modules
print(json.dumps(output))
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
        .write_all(input.to_string().as_bytes())
        .unwrap();
    let output = child.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).unwrap()
}
fn outcome<T: serde::Serialize>(value: automated_apply_agents::Result<T>) -> Value {
    match value {
        Ok(value) => serde_json::to_value(value).unwrap(),
        Err(error) => json!({"error":error.0}),
    }
}
#[test]
fn profile_comparison_references_alias_additions_and_canonical_unknowns_match_actual_legacy() {
    let references = vec![
        Value::Null,
        json!(""),
        json!([]),
        json!({}),
        json!(false),
        json!(0),
        json!("Fictional résumé 🚀"),
        json!({"z":1.0,"a":["Rust",true]}),
        json!(1e-7),
    ];
    let mut comparisons = vec![];
    for field in sync::FIELDS {
        for approved in [false, true] {
            for (canonical, observed) in [
                (Value::Null, Value::Null),
                (json!("Fictional value"), Value::Null),
                (Value::Null, json!("Fictional value")),
                (json!("same"), json!("same")),
                (json!("old"), json!("new")),
            ] {
                comparisons.push(json!([{(*field):canonical},{(*field):observed},if approved{vec![*field]}else{vec![]}]));
            }
        }
    }
    comparisons.extend([json!([{"phone":"+91 9876543210"},{"phone":"98765 43210"},["phone"]]),json!([{"phone":"+١٢ ٣٤٥٦٧٨٩٠١٢"},{"phone":"٣٤٥٦٧٨٩٠١٢"},[]]),json!([{"full_name":"  FİCTIONAL\u{001c}Straße  "},{"full_name":"fi̇ctional strasse"},[]]),json!([{"education":[{"institution":"Fictional School"}]},{"education":{"presence_only":true}},[]]),json!([{"skills":["Rust","React.js"]},{"skills":["Rust","Reactjs"]},["skills"]]),json!([{"skills":["Rust","Python"]},{"skills":["Rust","Existing Platform Skill"]},["skills"]])]);
    let additions = vec![
        json!([["Rust", "React.js", "Python", "Reactjs"], ["Rust", "React"]]),
        json!([["Node.js", "Type Script"], []]),
        json!([[], ["Rust"]]),
        json!([["Rust"], [1]]),
        json!([["Python\u{001c}  Tools"], ["python tools"]]),
    ];
    let prepared = vec![
        json!([["Old Skill"], ["Rust"], ["Old Skill", "Rust"]]),
        json!([["Old Skill"], ["Rust"], ["Rust"]]),
        json!([["Old Skill"], ["Rust"], ["Old Skill", "Unapproved"]]),
        json!([["React.js"], ["Reactjs"], ["React.js", "Reactjs"]]),
        json!([[], ["Rust"], ["Rust"]]),
    ];
    let profile = json!({"full_name":"Fictional Person","email":"fixture@example.com","phone":null,"summary":null,"verified_skills":["Rust"],"verified_roles":[{"title":"Historical Fictional Role"}],"education":[],"projects":[],"preferences":{"target_titles":["Rust Engineer"],"minimum_salary":999999,"preferred_locations":["Remote"],"remote_preference":"any"},"github_url":null,"portfolio_url":null,"linkedin_url":null});
    let canonical = vec![json!([profile, "fictional-resume-version"])];
    let input = json!({"references":references,"comparisons":comparisons,"additions":additions,"prepared":prepared,"canonical":canonical});
    let expected = oracle(&input);
    for (i, value) in input["references"].as_array().unwrap().iter().enumerate() {
        assert_eq!(json!(sync::reference(value)), expected["references"][i]);
    }
    for (i, case) in input["comparisons"].as_array().unwrap().iter().enumerate() {
        let approved = serde_json::from_value::<Vec<String>>(case[2].clone()).unwrap();
        assert_eq!(
            outcome(sync::compare(&case[0], &case[1], &approved)),
            expected["comparisons"][i],
            "{case}"
        );
    }
    for (i, case) in input["additions"].as_array().unwrap().iter().enumerate() {
        assert_eq!(
            outcome(sync::additions(&case[0], &case[1])),
            expected["additions"][i]
        );
    }
    for (i, case) in input["prepared"].as_array().unwrap().iter().enumerate() {
        assert_eq!(
            outcome(sync::prepared(&case[0], &case[1], &case[2])),
            expected["prepared"][i]
        );
    }
    let projected = sync::canonical(&input["canonical"][0][0], Some("fictional-resume-version"));
    assert_eq!(projected, expected["canonical"][0]);
    assert!(projected["headline"].is_null());
    assert!(projected["professional_title"].is_null());
    assert!(projected["expected_compensation"].is_null());
}
#[test]
fn profile_sync_and_account_dtos_keep_disabled_defaults_and_closed_review_inputs() {
    let policy = contracts::normalize(Kind::SyncPolicy, json!({})).unwrap();
    assert_eq!(policy["enabled"], false);
    assert_eq!(policy["auto_profile_sync"], false);
    assert_eq!(policy["interval_seconds"], 1800);
    assert_eq!(policy["approved_fields"], json!([]));
    assert!(
        contracts::normalize(
            Kind::SyncPolicy,
            json!({"approved_fields":["unsupported" ]})
        )
        .is_err()
    );
    let value=contracts::normalize(Kind::AccountApproval,json!({"expected_revision":0,"candidate_profile_id":"AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA","profile_binding_id":"BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB","account_sha256":"a".repeat(64),"evidence_sha256":"b".repeat(64),"owner_confirmed":true})).unwrap();
    assert_eq!(
        value["candidate_profile_id"],
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    );
    assert!(
        contracts::normalize(
            Kind::AccountApproval,
            json!({"expected_revision":0,"owner_confirmed":true,"automatic":true})
        )
        .is_err()
    );
}
