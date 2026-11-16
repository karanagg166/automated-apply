//! Deferred actual Gmail selected-account policy and retained-lead comparisons.
use automated_apply_agents::gmail_accounts::{
    self, Page,
    contract::{self, Kind},
};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
use uuid::Uuid;
fn oracle(script: &str, input: &Value) -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let mut child = Command::new(root.join(".venv/bin/python"))
        .args(["-B", "-c", script])
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
    let out = child.wait_with_output().unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    serde_json::from_slice(&out.stdout).unwrap()
}
#[test]
fn gmail_selected_policy_and_consent_normalization_match_actual_source_declarations() {
    let mut cases = Vec::<(Kind, String, Value)>::new();
    for i in 0..38 {
        let mut v = json!({"expected_version":0});
        match i {
            0 => {}
            1 => v["enabled"] = json!(true),
            2 => {
                v["enabled"] = json!(true);
                v["sender_allowlist"] = json!(["Owner@Example.COM"]);
            }
            3 => {
                v["enabled"] = json!(true);
                v["label_allowlist"] = json!(["Label_jobs_1"]);
            }
            4 => {
                v["enabled"] = json!(true);
                v["folders"] = json!(["INBOX", "SENT"]);
                v["history_months"] = json!(24);
            }
            5 => {
                v["folders"] = json!(["INBOX", "INBOX"]);
            }
            6 => v["history_months"] = json!(1),
            7 => {
                v["folders"] = json!(["SENT"]);
                v["max_pages"] = json!(2);
            }
            8 => v["label_allowlist"] = json!(["INBOX"]),
            9 => v["label_allowlist"] = json!(["Label_"]),
            10 => v["label_allowlist"] = json!(["Label_é"]),
            11 => v["label_allowlist"] = json!([format!("Label_{}", "a".repeat(101))]),
            12 => v["read_body"] = json!(true),
            13 => {
                v["read_body"] = json!(true);
                v["body_purpose"] = json!("  Review selected job messages  ");
            }
            14 => v["query_allowlist"] = json!("subject:jobs"),
            15 => {
                v["query_allowlist"] = json!("subject:jobs");
                v["read_body"] = json!(true);
                v["body_purpose"] = json!("Review selected job messages");
            }
            16 => v["retention_days"] = json!(0),
            17 => v["retention_days"] = json!(91),
            18 => v["backfill_days"] = json!(31),
            19 => v["max_pages"] = json!(4),
            20 => v["history_months"] = json!(25),
            21 => v["expected_version"] = json!("2"),
            22 => v["expected_version"] = json!(true),
            23 => v["enabled"] = json!(1),
            24 => v["read_body"] = json!("true"),
            25 => v["retain_metadata"] = json!(true),
            26 => v["sender_allowlist"] = json!(["invalid"]),
            27 => v["sender_allowlist"] = json!(["Owner@Example.COM"]),
            28 => v["sender_allowlist"] = json!(vec!["fictional@example.com"; 26]),
            29 => v["label_allowlist"] = json!(vec!["Label_jobs"; 11]),
            30 => v["folders"] = json!(["TRASH"]),
            31 => v["extra"] = json!(true),
            32 => v["expected_version"] = json!(-1),
            33 => v["max_pages"] = json!("3"),
            34 => v["retention_days"] = json!(14.0),
            35 => {
                v["read_body"] = json!(true);
                v["body_purpose"] = json!(" short ");
            }
            36 => v["query_allowlist"] = json!("   "),
            _ => {
                v["enabled"] = json!(true);
                v["folders"] = json!(["INBOX"]);
                v["retain_metadata"] = json!(true);
            }
        }
        cases.push((Kind::Policy, "gmail-read-policy".into(), v));
    }
    for v in [
        json!({"account_consent":true}),
        json!({"account_consent":false}),
        json!({"account_consent":"true"}),
        json!({"account_consent":true,"read_body":true,"expected_email":"Owner@Example.COM"}),
        json!({"account_consent":true,"expected_email":"invalid"}),
    ] {
        cases.push((Kind::Connect, "gmail-read-connect".into(), v));
    }
    for v in [
        json!({"job_url":"https://example.com/jobs/1","title":" Fictional Engineer ","reviewed_job_evidence":true}),
        json!({"job_url":"https://example.com/jobs/1","title":"Fictional","reviewed_job_evidence":false}),
        json!({"job_url":"https://127.0.0.1/job","title":"Fictional","reviewed_job_evidence":true}),
        json!({"job_url":"https://example.com/jobs/1","title":"Fictional","company_name":" Employer ","company_domain":" example.com ","reviewed_job_evidence":true}),
    ] {
        cases.push((Kind::LeadImport, "gmail-lead-import".into(), v));
    }
    let input = json!(
        cases
            .iter()
            .map(|(_, name, v)| json!({"name":name,"value":v}))
            .collect::<Vec<_>>()
    );
    let actual = oracle(
        r#"import json,runpy,sys
models=runpy.run_path('rust/scripts/export_gmail_contracts.py')['models']()
out=[]
for case in json.load(sys.stdin):
 try: out.append(models[case['name']].model_validate(case['value']).model_dump(mode='json'))
 except ValueError: out.append(None)
assert 'backend.app.core.config' not in sys.modules
print(json.dumps(out))
"#,
        &input,
    );
    for (index, ((kind, _, value), want)) in cases
        .into_iter()
        .zip(actual.as_array().unwrap())
        .enumerate()
    {
        let got = contract::normalize(kind, value).ok();
        assert_eq!(
            got.as_ref(),
            if want.is_null() { None } else { Some(want) },
            "case {index}"
        );
    }
}
#[test]
fn retained_leads_match_actual_grouping_and_preserve_legacy_unknown_import_markers() {
    let account = Uuid::from_u128(1);
    let mut cases = Vec::new();
    for index in 0..8 {
        let mut messages = vec![
            json!({"id":"a".repeat(32),"links":["https://example.com/jobs/1","https://example.com/jobs/2"]}),
            json!({"id":"b".repeat(32),"links":["https://example.com/jobs/1"]}),
        ];
        match index {
            0 => {}
            1 => messages[0]["imported_leads"] = json!({"https://example.com/jobs/1":["job-1"]}),
            2 => messages[0]["imported_job_ids"] = json!(["unknown-old-job"]),
            3 => {
                messages[0]["imported_job_ids"] = json!(["job-1"]);
                messages[0]["imported_leads"] = json!({"https://example.com/jobs/1":["job-1"]});
            }
            4 => {
                messages[0]["imported_job_ids"] = json!(["old-unknown"]);
                messages[1]["imported_leads"] =
                    json!({"https://example.com/jobs/1":["job-2","job-1","job-2"]});
            }
            5 => messages[0]["links"] = json!([]),
            6 => {
                messages[0]["links"] =
                    json!(["https://example.com/jobs/1", "https://example.com/jobs/1"])
            }
            _ => messages.clear(),
        };
        cases.push(messages);
    }
    let actual = oracle(
        r#"import ast,asyncio,hashlib,json,sys,types
from pathlib import Path
from uuid import UUID
node=next(n for n in ast.parse(Path('backend/app/integrations/gmail/read_service.py').read_text()).body if isinstance(n,ast.ClassDef) and n.name=='GmailReadService')
leads=next(n for n in node.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='leads')
ns={'hashlib':hashlib};exec(compile(ast.Module(body=[leads],type_ignores=[]),'<actual-retained-leads>','exec'),ns)
async def run(cases):
 out=[]
 for messages in cases:
  async def evidence(*args):return messages
  out.append(await ns['leads'](types.SimpleNamespace(evidence=evidence),UUID(int=1)))
 return out
print(json.dumps(asyncio.run(run(json.load(sys.stdin)))))
"#,
        &json!(cases),
    );
    for (messages, want) in cases.iter().zip(actual.as_array().unwrap()) {
        assert_eq!(
            json!(gmail_accounts::leads(account, messages).unwrap()),
            *want
        );
    }
}
#[test]
fn gmail_evidence_paging_and_closed_route_methods_are_bounded() {
    assert_eq!(
        Page::parse(None).unwrap(),
        Page {
            offset: 0,
            limit: 25
        }
    );
    assert_eq!(
        Page::parse(Some("limit=100&offset=100000")).unwrap(),
        Page {
            offset: 100000,
            limit: 100
        }
    );
    for query in [
        "limit=0",
        "limit=101",
        "offset=-1",
        "offset=100001",
        "limit=1&limit=2",
        "url=https://example.com",
        "limit=wrong",
    ] {
        assert!(Page::parse(Some(query)).is_err());
    }
    let id = Uuid::from_u128(1);
    for (action, method) in [
        ("", "GET"),
        ("/selection", "PUT"),
        ("/evidence", "GET"),
        ("/leads", "GET"),
    ] {
        assert_eq!(
            gmail_accounts::route(&format!("{}/{id}{action}", gmail_accounts::PATH))
                .unwrap()
                .method(),
            method
        );
    }
    for tail in ["send", "trash", "delete", "evidence/extra"] {
        assert!(gmail_accounts::route(&format!("{}/{id}/{tail}", gmail_accounts::PATH)).is_none());
    }
}
