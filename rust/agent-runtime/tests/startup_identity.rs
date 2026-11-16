//! Deferred actual source identity/content-hash expressions; no DB/provider imports.
use automated_apply_agents::startup_catalog::identity;
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
#[test]
fn startup_company_identity_and_observation_content_match_actual_priority_and_unicode_serialization()
 {
    let mut cases = Vec::new();
    for n in 0..20 {
        let mut v = json!({"source_company_id":null,"domain":"company-fixture.example","source_url":"https://company-fixture.example/about","name":"Fictional Company","employee_count":12,"historical":false});
        match n {
            0 => {}
            1 => v["source_company_id"] = json!("source-123"),
            2 => {
                v["source_company_id"] = json!("source-123");
                v["domain"] = Value::Null;
            }
            3 => v["domain"] = Value::Null,
            4 => {
                v["source_company_id"] = json!("");
                v["domain"] = Value::Null;
            }
            5 => v["name"] = json!("Résumé 🚀 कंपनी"),
            6 => v["name"] = json!("\"quoted\" \\ value"),
            7 => v["name"] = json!("\u{001c}control\u{001f}"),
            8 => v["employee_count"] = Value::Null,
            9 => v["historical"] = json!(true),
            10 => v["technology_stack"] = json!(["Rust", "Python"]),
            11 => v["source_url"] = json!("https://company-fixture.example/about?a=1&b=2"),
            12 => v["source_company_id"] = json!(" ID with spaces "),
            13 => v["domain"] = json!("sub.company-fixture.example"),
            14 => v["name"] = json!("Same employer changed display"),
            15 => v["description"] = json!("Text\nSecond line"),
            16 => v["founding_year"] = json!(2020),
            17 => v["technology_stack"] = json!([]),
            18 => v["name"] = json!("Ελληνικά Straße"),
            _ => v["stage"] = json!("seed"),
        };
        cases.push(v);
    }
    let script = r#"import ast,hashlib,json,runpy,sys
from types import SimpleNamespace as NS
s={'__name__':'company_identity_fixture','hashlib':hashlib};runpy.run_path('rust/scripts/export_execution_contracts.py')['load'](s,'backend/app/services/startup_discovery/company_identity.py',{'identity_key'})
# Compile the actual digest assignment from ingest_company, not a restated formula.
tree=ast.parse(open('backend/app/services/startup_discovery/evidence.py').read());function=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='ingest_company');assignment=next(n for n in function.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='digest' for t in n.targets));code=compile(ast.Module(body=[assignment],type_ignores=[]),'actual_ingest_digest','exec');out=[]
for v in json.load(sys.stdin):
 scope={'hashlib':hashlib,'json':json,'attributes':v};exec(code,scope);out.append({'identity':s['identity_key'](NS(**v)),'content':scope['digest']})
assert 'backend.app.core.config' not in sys.modules;print(json.dumps(out))
"#;
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let mut c = Command::new(root.join(".venv/bin/python"))
        .current_dir(root)
        .args(["-B", "-c", script])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    c.stdin
        .take()
        .unwrap()
        .write_all(json!(cases).to_string().as_bytes())
        .unwrap();
    let out = c.wait_with_output().unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let actual: Value = serde_json::from_slice(&out.stdout).unwrap();
    for (index, (value, want)) in cases.iter().zip(actual.as_array().unwrap()).enumerate() {
        assert_eq!(
            json!({"identity":identity::identity_key(value).unwrap(),"content":identity::content_hash(value)}),
            *want,
            "case {index}"
        );
    }
    assert_eq!(
        identity::identity_key(&cases[0]).unwrap(),
        identity::identity_key(&cases[14]).unwrap()
    );
}
