//! Source-phase fixtures; no provider, browser, credentials or receipt minting.
use automated_apply_agents::{Failure, browser_profiles::native_contract, execution::submission};
use serde_json::{Value, json};
#[test]
fn native_submission_report_reuses_closed_dto_defaults_and_keeps_execution_evidence_typed() {
    let report=native_contract::work_report(json!({"kind":"execution_observation","observed_url":submission::HISTORY_URL,"requisition":"123456789012","execution":{"state":"APPLICATION_SENT","document_id":"fictional-history-document-one","evidence_sha256":"a".repeat(64),"account_sha256":"b".repeat(64)}})).unwrap();
    assert_eq!(report["candidates"], json!([]));
    assert!(report["execution"]["resume_bytes"].is_null());
    assert_eq!(report["execution"]["profile_fields"], json!({}));
    for mutation in [
        json!({"arbitrary_submit":true}),
        json!({"execution":{"state":"APPLICATION_SENT","document_id":"short","evidence_sha256":"a".repeat(64),"account_sha256":"b".repeat(64)}}),
    ] {
        let mut value = report.clone();
        for (k, v) in mutation.as_object().unwrap() {
            value[k] = v.clone();
        }
        assert_eq!(
            native_contract::work_report(value).unwrap_err(),
            Failure("invalid_browser_profile_request")
        );
    }
}
#[test]
fn submission_descriptors_keep_expected_binding_without_exposing_private_fields() {
    let binding = json!({"profile_binding_id":"fictional-binding","tab_id":50});
    let proof = json!({"source":"profile_ui","account_sha256":"a".repeat(64),"binding":binding,"work_id":"fictional-work","profile_document_id":"fictional-profile-document"});
    let mut work = json!({"id":"fictional-work","binding":binding,"account_sha256":"a".repeat(64),"account_observation":proof,"operation":"reconcile_application","url":"https://www.naukri.com/job-listings-fictional-123456789012","profile_secret":"PRIVATE_SECRET_CANARY","admitted_actions":[{"id":"PRIVATE_ADMISSION_CANARY"}]});
    assert_eq!(
        submission::browser_url(&work).unwrap(),
        submission::HISTORY_URL
    );
    assert!(
        !submission::descriptor(&work)
            .to_string()
            .contains("PRIVATE_")
    );
    work["binding"]["tab_id"] = json!(51);
    assert_eq!(submission::account_observation(&work), Value::Null);
    work["operation"] = json!("inspect_profile");
    assert_eq!(
        submission::browser_url(&work).unwrap(),
        submission::PROFILE_URL
    );
}
#[test]
fn submission_receipt_hash_matches_the_actual_legacy_evidence_expression() {
    use std::{
        io::Write,
        path::PathBuf,
        process::{Command, Stdio},
    };
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let inputs = json!([{"status":"Application Sent","nested":{"z":1,"a":true}},{"title":"Fictional résumé 🚀","value":1.0,"small":1e-7,"none":null}]);
    let script = r#"import ast,hashlib,json,sys
from pathlib import Path
m=ast.parse(Path('backend/app/execution/naukri_submission.py').read_text())
f=next(n for n in m.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='confirm')
expr=next(n.value for n in ast.walk(f) if isinstance(n,ast.keyword) and n.arg=='request_hash')
code=compile(ast.Expression(expr),'<actual receipt hash>','eval')
print(json.dumps([eval(code,{'hashlib':hashlib,'json':json,'receipt':receipt}) for receipt in json.load(sys.stdin)]))
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
        .write_all(inputs.to_string().as_bytes())
        .unwrap();
    let output = child.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let expected: Vec<String> = serde_json::from_slice(&output.stdout).unwrap();
    for (input, expected) in inputs.as_array().unwrap().iter().zip(expected) {
        assert_eq!(submission::receipt_request_hash(input), expected);
    }
}
