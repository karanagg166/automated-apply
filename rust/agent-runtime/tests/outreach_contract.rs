//! Deferred actual draft DTO comparisons and pure history qualification. Fictional data only.
use automated_apply_agents::outreach::{
    self,
    contract::{self, Kind},
    history,
};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
fn actual(cases: &Value) -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let script = r#"import json,runpy,sys
models=runpy.run_path('rust/scripts/export_outreach_contracts.py')['models']();out=[]
for row in json.load(sys.stdin):
 try:
  model=models[row['name']].model_validate(row['value']);value=model.model_dump(mode='json',exclude_unset=row['name']!='outreach-input');out.append({'ok':True,'value':value})
 except (ValueError,TypeError):out.append({'ok':False})
assert 'backend.app.core.config' not in sys.modules
print(json.dumps(out))
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
        .write_all(cases.to_string().as_bytes())
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
fn outreach_actual_draft_inputs_edits_and_decisions_preserve_omission_defaults_and_validation() {
    let mut cases: Vec<(Kind, &str, Value)> = Vec::new();
    for n in 0..32 {
        let mut v = json!({"contact_id":"AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"});
        match n {
            0 => {}
            1 => v["contact_id"] = json!("wrong"),
            2 => v["job_id"] = json!("11111111-1111-4111-8111-111111111111"),
            3 => v["job_id"] = Value::Null,
            4 => v["purpose"] = json!("exploratory"),
            5 => v["purpose"] = json!(" exploratory "),
            6 => v["writing_style"] = json!("founder-focused"),
            7 => v["writing_style"] = json!("concise "),
            8 => v["max_length"] = json!("400"),
            9 => v["max_length"] = json!(5000.0),
            10 => v["max_length"] = json!(399),
            11 => v["max_length"] = json!(5001),
            12 => v["max_length"] = json!(400.5),
            13 => v["max_length"] = json!(true),
            14 => v["personal_instructions"] = json!("  Fictional instruction  "),
            15 => v["personal_instructions"] = json!("x".repeat(1001)),
            16 => v["personal_instructions"] = json!(4),
            17 => v["personal_instructions"] = json!("\u{001c} hello \u{001f}"),
            18 => v["use_llm"] = json!("YES"),
            19 => v["use_llm"] = json!(0),
            20 => v["use_llm"] = json!(2),
            21 => v["use_llm"] = Value::Null,
            22 => v["idempotency_key"] = json!("  fictional_request  "),
            23 => v["idempotency_key"] = json!("short"),
            24 => v["idempotency_key"] = json!("bad key too"),
            25 => v["idempotency_key"] = json!("x".repeat(101)),
            26 => v["idempotency_key"] = json!("é".repeat(8)),
            27 => v["extra"] = json!(true),
            28 => v["contact_id"] = Value::Null,
            29 => v = json!({}),
            30 => v = Value::Null,
            _ => v["writing_style"] = json!("friendly"),
        }
        cases.push((Kind::Input, "outreach-input", v));
    }
    for n in 0..28 {
        let mut v = json!({"expected_revision":1,"body":" Fictional reviewed body "});
        match n {
            0 => {}
            1 => v = json!({"expected_revision":1}),
            2 => v["body"] = Value::Null,
            3 => v["subject"] = Value::Null,
            4 => v["recipient_email"] = Value::Null,
            5 => v["subject"] = json!(" Fictional subject "),
            6 => v["subject"] = json!("Bad\r\nheader"),
            7 => v["subject"] = json!("\n Fictional subject \r"),
            8 => v["subject"] = json!("x".repeat(256)),
            9 => v["subject"] = json!(" "),
            10 => v["body"] = json!("hello\nworld"),
            11 => v["body"] = json!("x".repeat(5001)),
            12 => v["body"] = json!(" "),
            13 => v["recipient_email"] = json!("Owner@EXAMPLE.COM"),
            14 => v["recipient_email"] = json!("  Owner@EXAMPLE.COM  "),
            15 => v["recipient_email"] = json!("bad"),
            16 => v["recipient_email"] = json!("owner\n@example.com"),
            17 => v["expected_revision"] = json!("2"),
            18 => v["expected_revision"] = json!(true),
            19 => v["expected_revision"] = json!(0),
            20 => v["expected_revision"] = json!(2.0),
            21 => v["expected_revision"] = json!(1.5),
            22 => {
                v.as_object_mut().unwrap().remove("expected_revision");
            }
            23 => v["extra"] = json!(true),
            24 => v["body"] = json!(6),
            25 => v["subject"] = json!(false),
            26 => v["body"] = json!("\u{001c} reviewed \u{001f}"),
            _ => v = Value::Null,
        }
        cases.push((Kind::Edit, "outreach-edit", v));
    }
    for v in [
        json!({"expected_revision":1}),
        json!({"expected_revision":"2"}),
        json!({"expected_revision":true}),
        json!({"expected_revision":2.0}),
        json!({"expected_revision":1.5}),
        json!({"expected_revision":0}),
        json!({"expected_revision":null}),
        json!({"expected_revision":1,"extra":true}),
        json!({}),
        Value::Null,
    ] {
        cases.push((Kind::Decision, "outreach-decision", v));
    }
    let want = actual(&json!(
        cases
            .iter()
            .map(|(_, name, v)| json!({"name":name,"value":v}))
            .collect::<Vec<_>>()
    ));
    for (index, ((kind, _, v), expected)) in
        cases.into_iter().zip(want.as_array().unwrap()).enumerate()
    {
        let got = match contract::normalize(kind, v) {
            Ok(value) => json!({"ok":true,"value":value}),
            Err(_) => json!({"ok":false}),
        };
        assert_eq!(got, *expected, "case {index}");
    }
}
#[test]
fn outreach_history_qualifies_interruption_without_creating_acceptance_or_mutating_the_original() {
    let settings = outreach::Settings::from_values(&Default::default()).unwrap();
    let now = chrono::DateTime::parse_from_rfc3339("2026-11-17T12:00:00Z")
        .unwrap()
        .to_utc();
    let base = json!({"id":"11111111-1111-4111-8111-111111111111","draft_id":"22222222-2222-4222-8222-222222222222","draft_revision":1,"subject":"Fictional subject","body":"Fictional body","created_at":"2026-11-17T11:00:00Z","attempted_at":null,"accepted_at":null,"reconciliation_required":false});
    for (status, qualified, reconcile) in [
        ("prepared", "failed_before_send", false),
        ("attempting", "outcome_unknown", true),
        ("accepted_by_gmail", "accepted_by_gmail", false),
        ("outcome_unknown", "outcome_unknown", false),
    ] {
        let mut v = base.clone();
        v["status"] = json!(status);
        let original = v.clone();
        let result = history::qualify(v.clone(), true, now, &settings).unwrap();
        assert_eq!(result["status"], qualified);
        assert_eq!(result["recorded_status"], status);
        assert_eq!(result["reconciliation_required"], reconcile);
        assert_eq!(result["delivery_verified"], false);
        assert!(result["accepted_at"].is_null());
        assert_eq!(v, original);
    }
    let mut recent = base.clone();
    recent["status"] = json!("attempting");
    recent["created_at"] = json!("2026-11-17T11:59:00Z");
    assert_eq!(
        history::qualify(recent, true, now, &settings).unwrap()["status"],
        "attempting"
    );
    let mut malformed = base;
    malformed["draft_revision"] = json!(0);
    assert!(history::qualify(malformed, true, now, &settings).is_err());
}
#[test]
fn outreach_page_and_settings_are_bounded_and_routes_never_claim_send_authority() {
    assert_eq!(contract::page(None).unwrap(), (20, 0));
    assert_eq!(
        contract::page(Some("limit=100&offset=100000")).unwrap(),
        (100, 100000)
    );
    for q in [
        "limit=0",
        "limit=101",
        "offset=-1",
        "offset=100001",
        "limit=1&limit=2",
        "extra=true",
        "limit=1.5",
    ] {
        assert!(contract::page(Some(q)).is_err(), "{q}");
    }
    for path in [
        "/api/v1/outreach/drafts/11111111-1111-4111-8111-111111111111/send",
        "/api/v1/outreach/send-attempts/wrong",
        "/api/v1/outreach/history/extra",
    ] {
        assert!(history::route(path).is_none());
    }
    for timeout in ["0", "61", "NaN", "inf", "wrong"] {
        assert!(
            outreach::Settings::from_values(
                &[("GMAIL_SEND_TIMEOUT_SECONDS".into(), timeout.into())].into()
            )
            .is_err()
        );
    }
}
