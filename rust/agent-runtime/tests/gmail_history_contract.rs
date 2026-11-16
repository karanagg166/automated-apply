//! Deferred actual-source Gmail DTO/URL identity oracles. No settings, database or mail access.
use automated_apply_agents::gmail_history::contract::{self, Kind};
use chrono::Utc;
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
fn python(script: &str, input: &Value) -> Value {
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
#[test]
fn reviewed_history_normalization_matches_actual_owner_dtos_for_bounds_strict_flags_dates_and_evidence()
 {
    let base = json!({"expected_version":0,"company":" Fictional Employer ","role":" Rust Engineer ","applied_at":"2000-01-01T00:00:00Z","job_url":null,"evidence":{"00000000-0000-4000-8000-000000000001":["a".repeat(32)]},"status":"applied","confirmed_application":true,"retention_days":365,"owner_reviewed":true});
    let mut cases = Vec::new();
    for i in 0..40 {
        let mut v = base.clone();
        match i {
            0 => {}
            1 => v["company"] = json!("  "),
            2 => v["role"] = json!("x".repeat(201)),
            3 => v["expected_version"] = json!("1"),
            4 => v["expected_version"] = json!(true),
            5 => v["expected_version"] = json!(-1),
            6 => v["retention_days"] = json!("14"),
            7 => v["retention_days"] = json!(13),
            8 => v["retention_days"] = json!(7301),
            9 => v["owner_reviewed"] = json!(false),
            10 => v["owner_reviewed"] = json!(1),
            11 => v["confirmed_application"] = json!("true"),
            12 => v["status"] = json!(" uncertain "),
            13 => v["status"] = json!("submitted"),
            14 => v["applied_at"] = json!("2099-01-01T00:00:00Z"),
            15 => v["applied_at"] = json!("2000-01-01T00:00:00"),
            16 => v["applied_at"] = json!(946684800),
            17 => v["applied_at"] = json!(946684800000_i64),
            18 => v["applied_at"] = json!("946684800"),
            19 => v["applied_at"] = json!("2000-01-01T10:30:12.123+05:30"),
            20 => v["job_url"] = json!("HTTPS://Example.com:443/jobs/one"),
            21 => v["job_url"] = json!("http://example.com/job"),
            22 => v["job_url"] = json!("https://127.0.0.1/job"),
            23 => v["evidence"] = json!({}),
            24 => v["evidence"] = json!({"invalid":["a".repeat(32)]}),
            25 => v["evidence"] = json!({"00000000-0000-4000-8000-000000000001":[]}),
            26 => {
                v["evidence"] =
                    json!({"00000000-0000-4000-8000-000000000001":vec!["a".repeat(32);26]})
            }
            27 => v["evidence"] = json!({"00000000-0000-4000-8000-000000000001":["A".repeat(32)]}),
            28 => {
                v["evidence"] =
                    json!({"00000000-0000-4000-8000-000000000001":[format!(" {} ","a".repeat(32))]})
            }
            29 => v["evidence"] = json!({"AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA":["b".repeat(32)]}),
            30 => {
                v.as_object_mut().unwrap().remove("job_url");
            }
            31 => v["extra"] = json!(true),
            32 => v["company"] = json!(format!("  {}  ", "x".repeat(200))),
            33 => v["applied_at"] = json!("2000-01-01 00:00:00+00:00"),
            34 => v["retention_days"] = json!(7300),
            35 => v["confirmed_application"] = json!(false),
            36 => v["status"] = json!("recruiter_response"),
            37 => {
                v["evidence"] = json!({"00000000-0000-4000-8000-000000000001":["a".repeat(32)],"00000000-0000-4000-8000-000000000002":["b".repeat(32)]})
            }
            38 => v["retention_days"] = json!(14.0),
            _ => v["expected_version"] = json!(0.0),
        }
        cases.push(v);
    }
    let actual = python(
        r#"import json,runpy,sys
scope=runpy.run_path('rust/scripts/export_gmail_contracts.py')
model=scope['models']()['gmail-history-review']
out=[]
for value in json.load(sys.stdin):
 try: out.append(model.model_validate(value).model_dump(mode='json'))
 except ValueError: out.append(None)
assert 'backend.app.core.config' not in sys.modules
print(json.dumps(out))
"#,
        &json!(cases),
    );
    let now = Utc::now();
    for (i, (input, want)) in cases
        .into_iter()
        .zip(actual.as_array().unwrap())
        .enumerate()
    {
        let got = contract::normalize(Kind::Review, input, now).ok();
        assert_eq!(
            got.as_ref(),
            if want.is_null() { None } else { Some(want) },
            "case {i}"
        );
    }
}
#[test]
fn reviewed_history_opportunity_identity_matches_actual_ats_and_casefold_recipe() {
    let urls = vec![
        Value::Null,
        json!("https://boards.greenhouse.io/fictional/jobs/123?utm_source=mail"),
        json!("https://jobs.lever.co/fictional/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/apply"),
        json!(
            "https://jobs.ashbyhq.com/fictional/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/application"
        ),
        json!("https://www.naukri.com/job-listings-fictional-123456789012?source=mail"),
        json!("https://example.com/jobs/one/?b=2&a=1&utm_source=mail"),
    ];
    let mut cases = Vec::new();
    for company in [" Fictional Employer ", "Straße Labs", "Σίσυφος"] {
        for url in &urls {
            cases.push(json!({"company":company,"role":" Rust Engineer ","url":url}));
        }
    }
    let actual = python(
        r#"import ast,hashlib,json,sys
from pathlib import Path
node=next(n for n in ast.parse(Path('backend/app/integrations/gmail/history.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='canonical_url')
ns={};exec(compile(ast.Module(body=[node],type_ignores=[]),'<actual-history-url>','exec'),ns)
out=[]
for c in json.load(sys.stdin):
 identity=ns['canonical_url'](c['url']) or c['company'].strip().casefold()+'\n'+c['role'].strip().casefold()
 out.append(identity)
assert 'backend.app.core.config' not in sys.modules
print(json.dumps(out))
"#,
        &json!(cases),
    );
    for (input, want) in cases.iter().zip(actual.as_array().unwrap()) {
        assert_eq!(
            contract::opportunity(
                input["company"].as_str().unwrap(),
                input["role"].as_str().unwrap(),
                input["url"].as_str()
            ),
            want.as_str().unwrap()
        );
    }
}
