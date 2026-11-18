//! Deferred actual startup-prefixed run request hashes; no settings/claim/database import.
use automated_apply_agents::{
    research_contract::{self, Kind},
    startup_catalog::runs,
};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
#[test]
fn startup_original_request_hash_matches_actual_claim_expression_and_excludes_only_idempotency() {
    let mut cases = Vec::new();
    for n in 0..16 {
        let mut v = json!({"idempotency_key":"fictional_request_hash"});
        match n {
            0 => {}
            1 => v["idempotency_key"] = json!("different_original_key"),
            2 => v["allow_paid"] = json!(true),
            3 => v["permission_confirmed"] = json!(true),
            4 => v["filters"] = json!({"max_employees":null}),
            5 => v["filters"] = json!({"query":"Résumé 🚀"}),
            6 => v["filters"] = json!({"roles":["CTO","Recruiter"]}),
            7 => v["query"] = json!({"keywords":["Rust"],"locations":["India"]}),
            8 => v["query"] = json!({"limit":1}),
            9 => v["query"] = json!({"remote_preference":"remote"}),
            10 => v["filters"] = json!({"use_profile":false}),
            11 => v["filters"] = json!({"minimum_score":50.5}),
            12 => v["filters"] = json!({"observed_after":"2026-11-15T12:00:00Z"}),
            13 => v["filters"] = json!({"early_stage":true}),
            14 => {
                v["permission_confirmed"] = json!(true);
                v["companies"] = json!([{"name":"Fictional Company","source":"manual","source_url":"https://company-fixture.example/about","permission_evidence_url":"https://company-fixture.example/terms","observed_at":"2026-11-15T12:00:00Z"}]);
            }
            _ => v["filters"] = json!({"country":" India ","industries":[" AI "]}),
        };
        cases.push(v);
    }
    let script = r#"import ast,hashlib,json,runpy,sys,types
name='backend.app.services.startup_discovery.normalizer'
module=types.ModuleType(name)
module.size_band=runpy.run_path('backend/app/services/startup_discovery/normalizer.py')['size_band']
sys.modules[name]=module
model=runpy.run_path('rust/scripts/export_startup_contracts.py')['models']()['startup-run-request'];tree=ast.parse(open('backend/app/services/job_discovery_service.py').read());service=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='JobDiscoveryService');claim=next(n for n in service.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='claim');assignment=next(n for n in claim.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='fingerprint' for t in n.targets));code=compile(ast.Module(body=[assignment],type_ignores=[]),'actual_run_claim_hash','exec');out=[]
for v in json.load(sys.stdin):
 request=model.model_validate(v);request=request.model_copy(update={'source':'startup_'+request.source});scope={'hashlib':hashlib,'json':json,'request':request};exec(code,scope);out.append(scope['fingerprint'])
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
    let now = chrono::DateTime::parse_from_rfc3339("2026-11-17T00:00:00Z")
        .unwrap()
        .to_utc();
    for (index, (v, want)) in cases.iter().zip(actual.as_array().unwrap()).enumerate() {
        let v = research_contract::normalize(Kind::StartupRun, v.clone(), now).unwrap();
        assert_eq!(
            json!(runs::request_hash(&v).unwrap()),
            *want,
            "case {index}"
        );
    }
    assert_eq!(actual[0], actual[1]);
}
