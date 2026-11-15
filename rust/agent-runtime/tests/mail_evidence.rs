use automated_apply_agents::{
    Failure,
    mail_evidence::{content_evidence, decoded_body, encoded, headers, single_address},
    mailboxes::Search,
};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
fn part(mime: &str, body: &str) -> Value {
    json!({"mimeType":mime,"body":{"data":encoded(body.as_bytes())}})
}
fn python(cases: &[Value]) -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let code = r#"
import ast,base64,json,re,sys
from html.parser import HTMLParser
from pathlib import Path
from pydantic import TypeAdapter
from backend.app.core.urls import PublicHTTPSURL
source=ast.parse(Path('backend/app/integrations/gmail/read_client.py').read_text())
nodes=[n for n in source.body if isinstance(n,ast.ClassDef) and n.name=='TextHTML' or isinstance(n,ast.FunctionDef) and n.name=='content_evidence']
scope=dict(base64=base64,re=re,HTMLParser=HTMLParser,TypeAdapter=TypeAdapter,PublicHTTPSURL=PublicHTTPSURL,ConnectionError=ValueError)
exec(compile(ast.Module(body=nodes,type_ignores=[]),'isolated_mime_oracle','exec'),scope)
assert 'backend.app.core.config' not in sys.modules
output=[]
for case in json.load(sys.stdin):
 try:output.append({'ok':scope['content_evidence'](case)})
 except ValueError as error:output.append({'error':str(error)})
print(json.dumps(output))
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
        .write_all(json!(cases).to_string().as_bytes())
        .unwrap();
    let output = child.wait_with_output().unwrap();
    assert!(output.status.success());
    serde_json::from_slice(&output.stdout).unwrap()
}
#[test]
fn selected_mime_evidence_matches_actual_python_for_bounded_common_messages() {
    let texts = [
        "",
        "Interview",
        "Application received, unfortunately not moving forward",
        "Job alert hiring open position",
        "Recruiter reply opportunity",
        "Please share and kindly confirm next steps",
        "follow-up status of your application",
        "https://example.com/jobs/1?private=discard#tracking",
        "https://127.0.0.1/private https://example.com:8443/denied",
        "https://example.com/工作?private=remove",
        "Interview & application status",
        "Unicode résumé 工作 vacancies",
    ];
    let mut cases = vec![];
    for text in texts {
        cases.push(part("text/plain", text));
        cases.push(part(
            "text/html",
            &format!("<html><body><p>{text}</p></body></html>"),
        ));
        cases.push(json!({"mimeType":"multipart/alternative","parts":[part("text/plain",text),part("text/html",&format!("<p>{text}</p>"))]}));
    }
    cases.push(part("text/html","<head>interview<a href='https://hidden.example.com/private'>secret</a></head><script>application received</script><style>unfortunately</style><p>Public job alert</p><a href='https://example.com/jobs/2?private=remove'>listing</a>"));
    cases.push(part("text/html","<a href=https://example.com/first?a=1&amp;b=2>first</a><a href='https://example.com/first'>duplicate</a>"));
    cases.push(json!({"filename":"private.txt","mimeType":"text/plain","body":{"data":encoded(b"interview https://hidden.example.com/file")}}));
    cases.push(json!({"mimeType":"text/plain","body":{"attachmentId":"fictional-attachment","data":"invalid"}}));
    cases.push(json!({"mimeType":"text/plain","body":{"data":"%%%"}}));
    cases.push(json!({"mimeType":"multipart/mixed","parts":(0..101).map(|_|json!({})).collect::<Vec<_>>() }));
    let oracle = python(&cases);
    for (case, wanted) in cases.iter().zip(oracle.as_array().unwrap()) {
        let result = match content_evidence(case) {
            Ok(value) => json!({"ok":value}),
            Err(error) => json!({"error":error.0}),
        };
        assert_eq!(result, *wanted, "fictional input only: {case}");
    }
    assert_eq!(cases.len(), 42);
}
#[test]
fn mime_limits_and_hidden_attachments_fail_closed_without_raw_content() {
    let mut deep = part("text/plain", "interview");
    for _ in 0..13 {
        deep = json!({"parts":[deep]});
    }
    assert_eq!(
        content_evidence(&deep).err(),
        Some(Failure("gmail_mime_limits"))
    );
    assert_eq!(
        content_evidence(&part("text/plain", &"x".repeat(262145))).err(),
        Some(Failure("gmail_mime_limits"))
    );
    let input = part(
        "text/html",
        "<script>var fake='<a href=\"https://hidden.example.com/a\">interview</a>';</script><template>application received</template><p>status update</p>",
    );
    let output = content_evidence(&input).unwrap();
    assert_eq!(output["links"], json!([]));
    assert_eq!(output["signals"], json!([]));
    assert!(!output.to_string().contains("fake"));
    let input = json!({"parts":[part("text/plain",&"x".repeat(200000)),part("text/plain",&"x".repeat(62145))]});
    assert_eq!(
        content_evidence(&input).err(),
        Some(Failure("gmail_mime_limits"))
    );
    assert_eq!(decoded_body("__8=", 100).unwrap(), vec![255, 255]);
    assert_eq!(decoded_body("//8=", 100).unwrap(), vec![255, 255]);
}
#[test]
fn header_projection_and_address_parser_do_not_leak_unselected_headers_or_accept_multiple_recipients()
 {
    let message = json!({"payload":{"headers":[{"name":"From","value":" Fictional <fixture@example.com>\r\n "},{"name":"Subject","value":"\t one  two\nthree"},{"name":"Authorization","value":"Bearer private-canary"},{"name":"subject","value":"ignored duplicate"}]}});
    let values = headers(&message);
    assert_eq!(values["subject"], "one two three");
    assert!(!json!(values).to_string().contains("private-canary"));
    assert_eq!(
        single_address(&values["from"]).as_deref(),
        Some("fixture@example.com")
    );
    assert!(single_address("one@example.com, two@example.com").is_none());
    assert!(single_address("Group:one@example.com;").is_none());
    assert!(single_address("one@example.com\r\nBcc:two@example.com").is_none());
    assert!(Search::parse(json!({"query":"in:inbox","limit":"5"})).is_ok());
    for value in [
        json!({"limit":6}),
        json!({"query":""}),
        json!({"query":1}),
        json!({"query":"x","send":true}),
    ] {
        assert!(Search::parse(value).is_err());
    }
}
