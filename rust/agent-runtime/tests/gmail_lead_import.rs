//! Deferred actual NormalizedJob/source import call comparisons. No settings or mailbox IO.
use automated_apply_agents::gmail_accounts::{
    self,
    contract::{self, Kind},
    lead_import,
};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
#[test]
fn reviewed_email_link_normalization_matches_actual_import_constructor_without_vacancy_inference() {
    let now = DateTime::parse_from_rfc3339("2026-11-16T00:00:00Z")
        .unwrap()
        .with_timezone(&Utc);
    let mut cases = Vec::new();
    for index in 0..18 {
        let mut v = json!({"job_url":"https://example.com/jobs/one?utm_source=mail","title":" Fictional Engineer ","reviewed_job_evidence":true});
        match index {
            0 => {}
            1 => v["company_name"] = json!(" Fictional Employer "),
            2 => {
                v["company_name"] = json!("Fictional Employer");
                v["company_domain"] = json!(" Fictional.Example. ");
            }
            3 => v["company_domain"] = json!("https://fictional.example"),
            4 => v["company_domain"] = json!("localhost"),
            5 => v["company_domain"] = json!("127.0.0.1"),
            6 => v["company_domain"] = json!(""),
            7 => v["company_name"] = json!(""),
            8 => v["company_name"] = json!("    "),
            9 => {
                v["job_url"] = json!("https://boards.greenhouse.io/fictional/jobs/123?gh_src=mail")
            }
            10 => {
                v["job_url"] = json!(
                    "https://jobs.lever.co/fictional/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/apply"
                )
            }
            11 => {
                v["job_url"] =
                    json!("https://www.naukri.com/job-listings-fictional-123456789012?source=mail")
            }
            12 => v["company_domain"] = json!("sub.fictional.example"),
            13 => v["company_domain"] = json!("fictional.example/path"),
            14 => v["title"] = json!("Rust Engineer हिन्दी"),
            15 => v["reviewed_job_evidence"] = json!(false),
            16 => v["job_url"] = json!("https://user:secret@example.com/job"),
            _ => v["company_domain"] = json!("fictional..example"),
        };
        cases.push(v);
    }
    let script = r#"import ast,hashlib,json,runpy,sys
from pathlib import Path
from datetime import datetime,timezone
from backend.app.schemas.normalized_job import NormalizedJob
models=runpy.run_path('rust/scripts/export_gmail_contracts.py')['models']()
tree=ast.parse(Path('backend/app/integrations/gmail/read_service.py').read_text())
service=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='GmailReadService')
method=next(n for n in service.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='import_lead')
constructor=next(n for n in ast.walk(method) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='NormalizedJob')
for field in ['first_observed_date','last_observed_date','retrieved_at']:constructor.keywords.append(ast.keyword(arg=field,value=ast.Name(id='clock',ctx=ast.Load())))
expression=compile(ast.fix_missing_locations(ast.Expression(body=constructor)),'<actual-import-normalized-job>','eval')
out=[]
for raw in json.load(sys.stdin):
 try:
  data=models['gmail-lead-import'].model_validate(raw);url=str(data.job_url);identity=hashlib.sha256(url.encode()).hexdigest();clock=datetime(2026,11,16,tzinfo=timezone.utc)
  out.append(eval(expression,globals(),locals()).model_dump(mode='json'))
 except ValueError:out.append(None)
assert 'backend.app.core.config' not in sys.modules
print(json.dumps(out))
"#;
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
        .write_all(json!(cases).to_string().as_bytes())
        .unwrap();
    let output = child.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let actual: Vec<Value> = serde_json::from_slice(&output.stdout).unwrap();
    for (index, (input, want)) in cases.into_iter().zip(actual).enumerate() {
        let got = contract::normalize(Kind::LeadImport, input)
            .and_then(|v| lead_import::normalized(&v, now))
            .ok();
        assert_eq!(
            got.as_ref(),
            if want.is_null() { None } else { Some(&want) },
            "case {index}"
        );
    }
}
#[test]
fn reviewed_email_import_route_is_exact_account_and_lowercase_message_evidence_post_only() {
    let account = uuid::Uuid::from_u128(1);
    let path = format!(
        "{}/{account}/evidence/{}/import",
        gmail_accounts::PATH,
        "a".repeat(32)
    );
    assert_eq!(gmail_accounts::route(&path).unwrap().method(), "POST");
    for path in [
        path.clone() + "/extra",
        format!(
            "{}/{account}/evidence/{}/import",
            gmail_accounts::PATH,
            "A".repeat(32)
        ),
        format!("{}/{account}/evidence/missing/import", gmail_accounts::PATH),
    ] {
        assert!(gmail_accounts::route(&path).is_none());
    }
}
