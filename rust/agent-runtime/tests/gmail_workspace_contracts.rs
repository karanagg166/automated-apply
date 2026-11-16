//! Deferred actual DTO/content/hash comparisons; no configuration or mailbox imports.
use automated_apply_agents::gmail_workspace::{
    self,
    contract::{self, Kind},
};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
fn oracle(script: &str, input: &Value) -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let mut child = Command::new(root.join(".venv/bin/python"))
        .current_dir(root)
        .args(["-B", "-c", script])
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
    let out = child.wait_with_output().unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    serde_json::from_slice(&out.stdout).unwrap()
}
fn draft() -> Value {
    json!({"recipient":"target@EXAMPLE.COM","company":"Fictional Co","role":"Rust developer","context":"I reviewed the public Rust role."})
}
#[test]
fn workspace_dtos_match_actual_consent_draft_and_exact_approval_models() {
    let mut cases = Vec::new();
    for index in 0..22 {
        let mut v = draft();
        match index {
            0 => {}
            1 => v["expected_version"] = json!("4"),
            2 => v["expected_version"] = json!(true),
            3 => v["expected_version"] = json!(-1),
            4 => v["recipient"] = json!(" Target <target@example.com> "),
            5 => v["recipient"] = json!("invalid"),
            6 => v["company"] = json!("  工作 team  "),
            7 => v["role"] = json!("  "),
            8 => v["context"] = json!("short"),
            9 => v["body"] = json!("  Reviewed body.\n  "),
            10 => v["subject"] = json!(" \n "),
            11 => v["subject"] = json!("s".repeat(201)),
            12 => v["body"] = json!("b".repeat(10001)),
            13 => v["context"] = json!(1),
            14 => v["send"] = json!(true),
            15 => v["expected_version"] = Value::Null,
            16 => v["recipient"] = json!("plus+tag@example.com"),
            17 => v["subject"] = Value::Null,
            18 => v["body"] = Value::Null,
            19 => v["company"] = json!("c".repeat(201)),
            20 => v["role"] = json!("r".repeat(201)),
            _ => v["context"] = json!("c".repeat(2001)),
        }
        cases.push(json!(["gmail-workspace-draft", v]));
    }
    for v in [
        json!({"account_consent":true}),
        json!({"account_consent":false,"read_body":true}),
        json!({"account_consent":"true"}),
        json!({"account_consent":true,"read_body":1}),
        json!({"account_consent":true,"extra":false}),
    ] {
        cases.push(json!(["gmail-workspace-consent", v]));
    }
    for index in 0..10 {
        let mut v = json!({"expected_version":1,"content_hash":"a".repeat(64),"owner_reviewed":true,"expected_account_generation":2});
        match index {
            0 => {}
            1 => v["owner_reviewed"] = json!(false),
            2 => v["owner_reviewed"] = json!(1),
            3 => v["expected_version"] = json!("3"),
            4 => v["expected_account_generation"] = json!(0),
            5 => v["content_hash"] = json!("A".repeat(64)),
            6 => v["content_hash"] = json!("x"),
            7 => v["expected_version"] = json!(1.5),
            8 => v["extra"] = json!(1),
            _ => v["content_hash"] = json!(format!(" {} ", "b".repeat(64))),
        }
        cases.push(json!(["gmail-workspace-approval", v]));
    }
    let actual = oracle(
        r#"import json,runpy,sys
models=runpy.run_path('rust/scripts/export_gmail_contracts.py')['models']();out=[]
for name,v in json.load(sys.stdin):
 try:out.append(models[name].model_validate(v).model_dump(mode='json'))
 except ValueError:out.append(None)
assert 'backend.app.core.config' not in sys.modules
print(json.dumps(out))
"#,
        &json!(cases),
    );
    for (case, want) in cases.iter().zip(actual.as_array().unwrap()) {
        let kind = match case[0].as_str().unwrap() {
            "gmail-workspace-draft" => Kind::Draft,
            "gmail-workspace-consent" => Kind::Consent,
            _ => Kind::Approval,
        };
        assert_eq!(
            contract::normalize(kind, case[1].clone()).ok().as_ref(),
            if want.is_null() { None } else { Some(want) },
            "{case}"
        );
    }
}
#[test]
fn workspace_default_content_and_hash_use_actual_legacy_save_expressions() {
    let mut cases = Vec::new();
    for index in 0..10 {
        let mut input = contract::normalize(Kind::Draft, draft()).unwrap();
        let mut profile = json!({"full_name":"Fictional Candidate","verified_skills":["Rust","Python","SQL","Docker","Extra"]});
        match index {
            0 => {}
            1 => profile["full_name"] = json!("Fictional 工作"),
            2 => profile["verified_skills"] = json!([]),
            3 => input["subject"] = json!("Explicit subject"),
            4 => input["body"] = json!("Explicit reviewed body.\nSecond line."),
            5 => {
                input["subject"] = json!("Unicode 工作 résumé");
                input["body"] = json!("Fictional 👩‍💻\tcontent")
            }
            6 => input["company"] = json!("Quoted \\\" company"),
            7 => input["subject"] = json!("bad\r\nsubject"),
            8 => input["context"] = json!("Line one.\nLine two."),
            _ => profile["verified_skills"] = json!(["Rust"]),
        }
        cases.push(json!([input, profile]));
    }
    let actual = oracle(
        r#"import ast,hashlib,json,sys
from pathlib import Path
from types import SimpleNamespace
tree=ast.parse(Path('backend/app/integrations/gmail/drafts.py').read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='DraftAccountService');save=next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='save');content=next(n for n in save.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='content' for t in n.targets));guard=next(n for n in save.body if isinstance(n,ast.If) and 'gmail_draft_header_invalid' in ast.unparse(n));assignment=next(n for n in save.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='value' for t in n.targets));hash_node=next(v for k,v in zip(assignment.value.keys,assignment.value.values) if isinstance(k,ast.Constant) and k.value=='content_hash');out=[]
for data,profile in json.load(sys.stdin):
 ns={'data':SimpleNamespace(**data),'profile':SimpleNamespace(**profile),'ConnectionError':RuntimeError,'json':json,'digest':lambda value:hashlib.sha256(value.encode()).hexdigest()}
 try:
  exec(compile(ast.Module(body=[content,guard],type_ignores=[]),'<actual-save-content>','exec'),ns);digest=eval(compile(ast.Expression(hash_node),'<actual-save-hash>','eval'),ns);out.append({'content':ns['content'],'hash':digest})
 except RuntimeError:out.append(None)
print(json.dumps(out))
"#,
        &json!(cases),
    );
    for (case, want) in cases.iter().zip(actual.as_array().unwrap()) {
        let got = contract::content(&case[0], &case[1])
            .ok()
            .map(|content| json!({"hash":contract::digest(&content),"content":content}));
        assert_eq!(got.as_ref(), if want.is_null() { None } else { Some(want) });
    }
}
#[test]
fn workspace_routes_preserve_existing_local_contract_and_deny_nested_or_arbitrary_identity() {
    let root = gmail_workspace::PATH;
    assert!(
        gmail_workspace::route(&format!("{root}/accounts"))
            .unwrap()
            .accepts("GET")
    );
    assert!(
        gmail_workspace::route(&format!("{root}/drafts"))
            .unwrap()
            .accepts("POST")
    );
    for suffix in [
        "/drafts/send",
        "/drafts/../account",
        "/drafts/123",
        "/accounts/other",
        "/drafts/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/create-in-gmail",
    ] {
        assert!(gmail_workspace::route(&format!("{root}{suffix}")).is_none());
    }
    assert!(
        gmail_workspace::route(&format!("{root}/drafts/{}", "a".repeat(32)))
            .unwrap()
            .accepts("PUT")
    );
    for slot in ["read_1", "read_2", "outreach"] {
        assert!(gmail_workspace::io_route(&format!("{root}/accounts/{slot}/connect")).is_some());
    }
    assert!(gmail_workspace::io_route(&format!("{root}/outreach/disconnect")).is_some());
    for suffix in [
        "/accounts/read_3/connect",
        "/accounts/read_1/send",
        "/outreach/send",
        "/accounts/outreach/connect/extra",
    ] {
        assert!(gmail_workspace::io_route(&format!("{root}{suffix}")).is_none());
    }
}
