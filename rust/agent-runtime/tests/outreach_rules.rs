//! Deferred actual sentence-support and approval-hash compatibility; no application imports.
use automated_apply_agents::outreach::drafts;
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
fn oracle(script: &str, input: Value) -> Value {
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
        .write_all(input.to_string().as_bytes())
        .unwrap();
    let out = c.wait_with_output().unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    serde_json::from_slice(&out.stdout).unwrap()
}
#[test]
fn outreach_sentence_support_matches_actual_unicode_punctuation_and_line_break_rules() {
    let cases = [
        "",
        "   ",
        "Fictional sentence.",
        "One. Two! Three?",
        "One.\nTwo",
        "One\n\nTwo",
        "Same. Same.",
        "One.\u{001c}Two",
        "One.\u{00a0}Two",
        "One\u{001f}\nTwo",
        "No punctuation but spaces",
        "Fictional 😀. 次の文。",
        "v1.0 remains one sentence.",
        "One!\tTwo",
        "Leading\r\nline",
        "A.B remains joined.",
        "What?\u{2028}Next.",
        "\u{001c} first \u{001f}",
        "One.\rTwo",
        "A!  B?\nC.",
    ];
    let actual = oracle(
        r#"import json,re,runpy,sys
s={'__name__':'outreach_rules_fixture','re':re};runpy.run_path('rust/scripts/export_execution_contracts.py')['load'](s,'backend/app/services/outreach_drafting.py',{'sentences'})
print(json.dumps([sorted(s['sentences'](v)) for v in json.load(sys.stdin)]));assert 'backend.app.core.config' not in sys.modules
"#,
        json!(cases),
    );
    for (index, (input, want)) in cases.iter().zip(actual.as_array().unwrap()).enumerate() {
        assert_eq!(
            json!(drafts::sentences(input).unwrap()),
            *want,
            "case {index}"
        );
    }
}
#[test]
fn outreach_approval_hash_matches_actual_revision_content_recipient_and_unicode_binding() {
    let mut cases = Vec::new();
    for n in 0..14 {
        let mut v = json!({"subject":"Fictional introduction — Candidate","body":"Fictional body.\n\nVerified contribution.","recipient_email":"person@example.com","evidence_hash":"a".repeat(64),"draft_revision":1});
        match n {
            0 => {}
            1 => v["subject"] = json!("Changed subject"),
            2 => v["body"] = json!("Changed body"),
            3 => v["recipient_email"] = json!("other@example.com"),
            4 => v["evidence_hash"] = json!("b".repeat(64)),
            5 => v["draft_revision"] = json!(2),
            6 => v["draft_revision"] = json!(2147483647),
            7 => v["recipient_email"] = Value::Null,
            8 => v["evidence_hash"] = Value::Null,
            9 => v["body"] = json!("UTF-8 résumé 🚀 योगदान"),
            10 => v["body"] = json!("line\r\n\tvalue"),
            11 => v["subject"] = json!("\"quoted\""),
            12 => v["body"] = json!("slash / backslash \\"),
            _ => v["body"] = json!("\u{001c}text\u{001f}"),
        };
        cases.push(v);
    }
    let actual = oracle(
        r#"import hashlib,json,runpy,sys
s={'__name__':'outreach_rules_fixture','hashlib':hashlib,'json':json};runpy.run_path('rust/scripts/export_execution_contracts.py')['load'](s,'backend/app/services/outreach_drafting.py',{'fingerprint'})
print(json.dumps([s['fingerprint']([v[k] for k in ('subject','body','recipient_email','evidence_hash','draft_revision')]) for v in json.load(sys.stdin)]));assert 'backend.app.core.config' not in sys.modules
"#,
        json!(cases),
    );
    for (index, (input, want)) in cases.iter().zip(actual.as_array().unwrap()).enumerate() {
        assert_eq!(json!(drafts::approval_digest(input)), *want, "case {index}");
    }
}
