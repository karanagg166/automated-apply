//! Deferred actual legacy saved projection comparison; sending/current probes are overridden.
use automated_apply_agents::{
    gmail_legacy,
    google_oauth::{GrantMode, scopes},
};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
#[test]
fn legacy_status_preserves_actual_saved_identity_fields_while_disabling_send_and_current_probe_claims()
 {
    let mut cases = Vec::new();
    for index in 0..16 {
        let mut value = json!({"id":"11111111-1111-4111-8111-111111111111","status":"connected","account_email":"fixture@example.com","google_subject":"fictional-subject","granted_scopes":scopes(GrantMode::Metadata),"workflow":"legacy","connected_at":"2026-01-01T00:00:00Z","last_verified_at":"2026-01-02T00:00:00Z","last_refresh_at":null});
        match index {
            0 => {}
            1 => value["granted_scopes"] = json!(scopes(GrantMode::Read)),
            2 => value["granted_scopes"] = json!(scopes(GrantMode::Compose)),
            3 => {
                value["granted_scopes"] = json!([
                    "openid",
                    "https://www.googleapis.com/auth/userinfo.email",
                    "https://www.googleapis.com/auth/gmail.metadata",
                    "https://www.googleapis.com/auth/gmail.send"
                ])
            }
            4 => value["status"] = json!("disconnected"),
            5 => value["status"] = json!("reauthorization_required"),
            6 => value["last_verified_at"] = Value::Null,
            7 => value["google_subject"] = json!(""),
            8 => value["granted_scopes"] = json!([]),
            9 => value["granted_scopes"] = json!(["unknown-scope"]),
            10 => value["granted_scopes"] = json!(scopes(GrantMode::ReadDraft)),
            11 => value["account_email"] = json!("other@example.com"),
            12 => value["last_refresh_at"] = json!("2026-01-03T00:00:00Z"),
            13 => value["status"] = json!("credential_expired"),
            14 => value["last_verified_at"] = json!("2026-01-04T00:00:00Z"),
            _ => value["connected_at"] = json!("2025-12-01T00:00:00Z"),
        };
        cases.push(value);
    }
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let script = r#"import ast,json,sys
from pathlib import Path
from types import SimpleNamespace
scope={};tree=ast.parse(Path('backend/app/integrations/google_oauth.py').read_text());names={'METADATA_SCOPE','SCOPES','SEND_SCOPE','SEND_SCOPES','COMPOSE_SCOPE','COMPOSE_SCOPES','READ_SCOPE','READ_SCOPES'};nodes=[n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in names for t in n.targets)];exec(compile(ast.Module(body=nodes,type_ignores=[]),'<actual-google-scopes>','exec'),scope)
tree=ast.parse(Path('backend/app/integrations/connection_service.py').read_text());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='account_output');exec(compile(ast.Module(body=[node],type_ignores=[]),'<actual-legacy-status>','exec'),scope)
print(json.dumps([scope['account_output'](SimpleNamespace(**v)) for v in json.load(sys.stdin)]))
"#;
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
    let actual: Value = serde_json::from_slice(&output.stdout).unwrap();
    for (value, actual) in cases.iter().zip(actual.as_array().unwrap()) {
        let got = gmail_legacy::projection(Some(value), true, true).unwrap();
        for field in [
            "id",
            "status",
            "account_email",
            "google_subject",
            "granted_scopes",
            "workflow",
            "connected_at",
            "last_verified_at",
            "last_refresh_at",
        ] {
            assert_eq!(got[field], actual[field], "{field}");
        }
        assert_eq!(got["live_verified"], false);
        assert_eq!(got["permissions"]["send"], false);
        assert_eq!(got["sending_enabled"], false);
        assert_eq!(got["send_capability"], "disabled_by_owner_policy");
        assert_eq!(got["read_mail_enabled"], false);
    }
    let absent = gmail_legacy::projection(None, false, false).unwrap();
    assert_eq!(absent["status"], "not_connected");
    assert_eq!(absent["live_verified"], false);
    let restricted = gmail_legacy::projection(cases.first(), false, true).unwrap();
    assert_eq!(restricted["authorization_state"], "account_not_authorized");
    assert_eq!(restricted["permissions"]["read_metadata"], false);
}
#[test]
fn legacy_status_and_refusal_paths_are_closed_and_never_recognize_arbitrary_outreach_actions() {
    assert!(gmail_legacy::route(gmail_legacy::STATUS).is_some());
    for suffix in ["send", "send-preview"] {
        assert_eq!(
            gmail_legacy::route(&format!(
                "/api/v1/outreach/drafts/11111111-1111-4111-8111-111111111111/{suffix}"
            ))
            .unwrap()
            .method(),
            "POST"
        );
    }
    for path in [
        "/api/v1/outreach/drafts/not-a-uuid/send",
        "/api/v1/outreach/drafts/11111111-1111-4111-8111-111111111111/send/extra",
        "/api/v1/integrations/gmail/status/other",
        "/api/v1/outreach/send",
    ] {
        assert!(gmail_legacy::route(path).is_none());
    }
}
