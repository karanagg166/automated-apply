use automated_apply_agents::{
    mail_evidence::encoded,
    mailboxes::{ReviewedDraft, draft_hash, mime_message, verified_content},
};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
fn python(raw: Value) -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let code = r#"
import ast,json,sys,hashlib
from pathlib import Path
from uuid import UUID
from pydantic import BaseModel,ConfigDict,Field,StrictBool,EmailStr
class Contract(BaseModel):model_config=ConfigDict(extra='forbid')
scope=dict(Contract=Contract,Field=Field,StrictBool=StrictBool,EmailStr=EmailStr,UUID=UUID,json=json,digest=lambda text:hashlib.sha256(text.encode()).hexdigest())
source=ast.parse(Path('backend/app/integrations/gmail/mailboxes.py').read_text())
nodes=[n for n in source.body if isinstance(n,ast.ClassDef) and n.name in {'Generation','ReviewedDraft'} or isinstance(n,ast.FunctionDef) and n.name=='draft_hash']
exec(compile(ast.Module(body=nodes,type_ignores=[]),'isolated_reviewed_draft_oracle','exec'),scope)
raw=json.load(sys.stdin);output=[]
for value in raw['cases']:
 try:output.append({'ok':scope['ReviewedDraft'].model_validate(value).model_dump(mode='json')})
 except ValueError:output.append({'error':True})
print(json.dumps({'cases':output,'hashes':[scope['draft_hash'](*values) for values in raw['hashes']]}))
assert 'backend.app.core.config' not in sys.modules
"#;
    let mut child = Command::new(root.join(".venv/bin/python"))
        .args(["-c", code])
        .current_dir(root)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(raw.to_string().as_bytes())
        .unwrap();
    let output = child.wait_with_output().unwrap();
    assert!(output.status.success());
    serde_json::from_slice(&output.stdout).unwrap()
}
fn input() -> Value {
    json!({"expected_generation":1,"request_id":"00000000-0000-0000-0000-000000000001","recipient":"Recipient@example.com","subject":"Reviewed draft","body":"Fictional owner text","content_hash":"a".repeat(64),"owner_reviewed":true})
}
#[test]
fn reviewed_dto_and_unicode_content_hashes_match_actual_python_without_importing_runtime() {
    let mut cases = vec![input()];
    for (key, values) in [
        (
            "expected_generation",
            vec![
                json!("2"),
                json!(2.0),
                json!(true),
                json!(0),
                json!(null),
                json!(-1),
            ],
        ),
        (
            "request_id",
            vec![
                json!("00000000000000000000000000000001"),
                json!("invalid"),
                json!(null),
            ],
        ),
        (
            "recipient",
            vec![
                json!(" Fictional <target@example.com> "),
                json!("räksmörgås@example.com"),
                json!("user@bücher.de"),
                json!("invalid"),
                json!("a@example.com,b@example.com"),
                json!("a@example.com\r\nBcc:other@example.com"),
            ],
        ),
        (
            "subject",
            vec![
                json!("Résumé 工作"),
                json!("a".repeat(180)),
                json!("a".repeat(181)),
                json!(""),
                json!("subject\r\nBcc:other@example.com"),
                json!(null),
            ],
        ),
        (
            "body",
            vec![
                json!(""),
                json!("x".repeat(10000)),
                json!("x".repeat(10001)),
                json!("Line1\r\nLine2\n"),
                json!(12),
            ],
        ),
        (
            "content_hash",
            vec![
                json!("A".repeat(64)),
                json!("a".repeat(63)),
                json!("0".repeat(64)),
            ],
        ),
        (
            "owner_reviewed",
            vec![json!(1), json!("true"), json!(false)],
        ),
    ] {
        for value in values {
            let mut case = input();
            case[key] = value;
            cases.push(case);
        }
    }
    let mut extra = input();
    extra["send"] = json!(true);
    cases.push(extra);
    let hashes = vec![
        vec!["Target@Example.com", "Subject", "Body"],
        vec!["Target@Example.com", "工作 résumé", "One\r\nTwo\r\n"],
        vec!["İ@EXAMPLE.COM", "subject", "\n\n"],
        vec!["r@example.com", "quoted \" subject", "body\rtext\n\n"],
    ];
    let expected = python(json!({"cases":cases,"hashes":hashes}));
    for (case, wanted) in cases.into_iter().zip(expected["cases"].as_array().unwrap()) {
        let result = match ReviewedDraft::parse(case) {
            Ok(v) => {
                json!({"ok":{"expected_generation":v.expected_generation,"request_id":v.request_id,"recipient":v.recipient,"subject":v.subject,"body":v.body,"content_hash":v.content_hash,"owner_reviewed":v.owner_reviewed}})
            }
            Err(_) => json!({"error":true}),
        };
        assert_eq!(result, *wanted);
    }
    for (values, hash) in hashes
        .into_iter()
        .zip(expected["hashes"].as_array().unwrap())
    {
        assert_eq!(
            draft_hash(values[0], values[1], values[2]),
            hash.as_str().unwrap()
        );
    }
}
#[test]
fn native_mime_roundtrip_encodes_unicode_and_never_adds_hidden_recipients() {
    let from = "fixture@example.com";
    let recipient = "target@example.com";
    for (subject, body) in [
        ("Fictional draft", "One\nTwo"),
        ("Résumé 工作", "Unicode résumé 工作\r\nSecond line\n"),
        (&"😀".repeat(180), "Unicode subject maximum"),
        ("Long message", &"a".repeat(150)),
    ] {
        let raw = mime_message(
            from,
            recipient,
            subject,
            body,
            "fictional-marker@automated-apply.invalid",
        )
        .unwrap();
        let message = mail_parser::MessageParser::default().parse(&raw).unwrap();
        assert_eq!(message.subject(), Some(subject));
        assert_eq!(
            message.message_id(),
            Some("fictional-marker@automated-apply.invalid")
        );
        assert!(message.bcc().is_none());
        assert!(message.cc().is_none());
        let actual_body = message.body_text(0).unwrap();
        let data = json!({"id":"fictional-message","labelIds":["DRAFT"],"payload":{"headers":[{"name":"From","value":from},{"name":"To","value":recipient},{"name":"Subject","value":message.header_raw("Subject").unwrap().trim()},{"name":"Message-ID","value":"<fictional-marker@automated-apply.invalid>"}],"body":{"data":encoded(actual_body.as_bytes())}}});
        verified_content(&data, from, recipient, subject, body).unwrap();
        for key in ["body", "cc", "duplicate_to", "sent", "from"] {
            let mut changed = data.clone();
            match key {
                "body" => changed["payload"]["body"]["data"] = json!(encoded(b"changed body")),
                "cc" => changed["payload"]["headers"]
                    .as_array_mut()
                    .unwrap()
                    .push(json!({"name":"Cc","value":"other@example.com"})),
                "duplicate_to" => changed["payload"]["headers"]
                    .as_array_mut()
                    .unwrap()
                    .push(json!({"name":"To","value":"other@example.com"})),
                "sent" => changed["labelIds"] = json!(["DRAFT", "SENT"]),
                "from" => changed["payload"]["headers"][0]["value"] = json!("other@example.com"),
                _ => unreachable!(),
            };
            assert!(verified_content(&changed, from, recipient, subject, body).is_err());
        }
    }
    assert!(
        mime_message(
            from,
            recipient,
            "subject\r\nBcc:other@example.com",
            "body",
            "marker@example.com"
        )
        .is_err()
    );
}
