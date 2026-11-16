//! Deferred actual AlertPolicy/authentication/query/source link identity comparisons.
use automated_apply_agents::mailboxes::alert_rules;
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
fn oracle(script: &str, input: &Value) -> Value {
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
fn message() -> Value {
    json!({"payload":{"headers":[{"name":"From","value":"Naukri <naukrialerts@naukri.com>"},{"name":"Authentication-Results","value":"mx.google.com; dkim=pass header.i=@naukri.com; dmarc=pass header.from=naukri.com"},{"name":"Subject","value":"Recommended jobs"}]}})
}
#[test]
fn official_alert_authentication_matches_actual_receiving_dmarc_dkim_and_duplicate_header_rules() {
    let mut cases = Vec::new();
    for index in 0..26 {
        let mut v = message();
        match index {
            0 => {}
            1 => v["payload"]["headers"][0]["value"] = json!("other@naukri.com"),
            2 => v["payload"]["headers"][0]["value"] = json!("naukrialerts@evil.example"),
            3 => v["payload"]["headers"][0]["value"] = json!("Naukri <NAUKRIALERTS@NAUKRI.COM>"),
            4 => v["payload"]["headers"]
                .as_array_mut()
                .unwrap()
                .push(json!({"name":"From","value":"naukrialerts@naukri.com"})),
            5 => v["payload"]["headers"]
                .as_array_mut()
                .unwrap()
                .push(json!({"name":"Authentication-Results","value":"mx.google.com; dmarc=pass"})),
            6 => {
                v["payload"]["headers"].as_array_mut().unwrap().remove(1);
            }
            7 => {
                v["payload"]["headers"][1]["value"] = json!(
                    "evil.example; dkim=pass header.i=@naukri.com; dmarc=pass header.from=naukri.com"
                )
            }
            8 => {
                v["payload"]["headers"][1]["value"] = json!(
                    "mx.google.com; dkim=pass header.d=naukri.com; dmarc=pass header.from=naukri.com"
                )
            }
            9 => {
                v["payload"]["headers"][1]["value"] = json!(
                    "mx.google.com; dkim=fail header.d=naukri.com; dmarc=pass header.from=naukri.com"
                )
            }
            10 => {
                v["payload"]["headers"][1]["value"] = json!(
                    "mx.google.com; dkim=pass header.d=naukri.com; dmarc=fail header.from=naukri.com"
                )
            }
            11 => {
                v["payload"]["headers"][1]["value"] = json!(
                    "mx.google.com; dkim=pass header.d=naukri.com.evil.example; dmarc=pass header.from=naukri.com"
                )
            }
            12 => {
                v["payload"]["headers"][1]["value"] = json!(
                    "mx.google.com; dkim=pass header.d=naukri.com; dmarc=pass header.from=naukri.com.evil.example"
                )
            }
            13 => {
                v["payload"]["headers"][1]["value"] = json!(
                    "MX.GOOGLE.COM;\n DKIM=PASS HEADER.I=@NAUKRI.COM;\n DMARC=PASS HEADER.FROM=NAUKRI.COM"
                )
            }
            14 => {
                v["payload"]["headers"][1]["value"] = json!(
                    "mx.google.com; dkim=passfoo header.d=naukri.com; dmarc=pass header.from=naukri.com"
                )
            }
            15 => {
                v["payload"]["headers"][1]["value"] = json!(
                    "mx.google.com; dkim=pass header.i=@naukri.com; dmarc=pass action=none header.from=naukri.com"
                )
            }
            16 => {
                v["payload"]["headers"][1]["value"] = json!(
                    "mx.google.com; dmarc=pass header.from=naukri.com; dkim=pass header.d=naukri.com;"
                )
            }
            17 => {
                v["payload"]["headers"][1]["value"] = json!(
                    "mx.google.com ; dkim=pass header.i=@naukri.com; dmarc=pass header.from=naukri.com"
                )
            }
            18 => v["payload"]["headers"] = json!("wrong"),
            19 => v["payload"]["headers"][1]["value"] = json!(1),
            20 => v["payload"]["headers"][0]["name"] = json!(1),
            21 => {
                v["payload"]["headers"] = json!(vec![json!({"name":"Other","value":"value"}); 101])
            }
            22 => v = json!({}),
            23 => {
                v["payload"]["headers"][0]["value"] = json!("naukrialerts@naukri.com.evil.example")
            }
            24 => {
                v["payload"]["headers"][1]["value"] = json!(
                    "mx.google.com; dkim=pass header.i=@naukri.com; dmarc=pass header.from=naukri.com "
                )
            }
            _ => v["payload"]["headers"][1]["name"] = json!("AUTHENTICATION-RESULTS"),
        };
        cases.push(v);
    }
    let actual = oracle(
        r#"import ast,json,re,sys
from pathlib import Path
from email.utils import parseaddr
tree=ast.parse(Path('backend/app/integrations/gmail/job_alerts.py').read_text());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='authenticated_alert')
ns={'re':re,'parseaddr':parseaddr,'SENDER':'naukrialerts@naukri.com'};exec(compile(ast.Module(body=[node],type_ignores=[]),'<actual-alert-auth>','exec'),ns)
print(json.dumps([ns['authenticated_alert'](v) for v in json.load(sys.stdin)]))
"#,
        &json!(cases),
    );
    for (index, (message, want)) in cases.iter().zip(actual.as_array().unwrap()).enumerate() {
        assert_eq!(
            alert_rules::authenticated(message),
            want.as_bool().unwrap(),
            "case {index}"
        );
    }
    let mut ambiguous = message();
    ambiguous["payload"]["headers"][0]["value"] =
        json!("naukrialerts@naukri.com, other@evil.example");
    assert!(!alert_rules::authenticated(&ambiguous));
}
#[test]
fn alert_policy_matches_actual_dto_and_query_is_fixed_official_sender() {
    let mut cases = Vec::new();
    for index in 0..14 {
        let mut v = json!({"expected_version":0,"expected_generation":1,"enabled":true});
        match index {
            0 => {}
            1 => v["expected_version"] = json!("2"),
            2 => v["expected_generation"] = json!("3"),
            3 => v["expected_generation"] = json!(true),
            4 => v["expected_generation"] = json!(0),
            5 => v["expected_version"] = json!(-1),
            6 => v["enabled"] = json!("true"),
            7 => v["enabled"] = json!(1),
            8 => v["interval_seconds"] = json!(899),
            9 => v["interval_seconds"] = json!(86401),
            10 => v["interval_seconds"] = json!(86400),
            11 => v["interval_seconds"] = json!("900"),
            12 => v["enabled"] = json!(false),
            _ => v["query"] = json!("arbitrary"),
        };
        cases.push(v);
    }
    let actual = oracle(
        r#"import json,runpy,sys
model=runpy.run_path('rust/scripts/export_gmail_contracts.py')['models']()['gmail-alert-policy'];out=[]
for v in json.load(sys.stdin):
 try:out.append(model.model_validate(v).model_dump(mode='json'))
 except ValueError:out.append(None)
assert 'backend.app.core.config' not in sys.modules
print(json.dumps(out))
"#,
        &json!(cases),
    );
    for (v, want) in cases.into_iter().zip(actual.as_array().unwrap()) {
        assert_eq!(
            alert_rules::policy(v).ok().as_ref(),
            if want.is_null() { None } else { Some(want) }
        );
    }
    assert_eq!(
        alert_rules::query(&json!({"scan_after":1,"scan_until":100})).unwrap(),
        "in:inbox from:naukrialerts@naukri.com after:1 before:100"
    );
    assert!(alert_rules::query(&json!({"scan_after":100,"scan_until":1})).is_err());
}
#[test]
fn alert_direct_requisition_links_match_actual_normalization_and_cross_source_deduplication() {
    let cases = json!([
        [
            "https://naukri.com/job-listings-fictional-123456789012?private=query",
            "https://www.naukri.com/job-listings-other-slug-123456789012/",
            "https://example.com/jobs/1",
            "https://www.naukri.com/nlogin/login"
        ],
        [
            "https://www.naukri.com/job-listings-first-123456789012",
            "https://naukri.com/job-listings-second-223456789012"
        ],
        [],
        [
            "http://naukri.com/job-listings-fake-123456789012",
            "https://www.naukri.com/redirect?url=https://example.com"
        ]
    ]);
    let actual = oracle(
        r#"import ast,json,re,sys
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit
from pydantic import TypeAdapter
from backend.app.core.urls import PublicHTTPSURL
def safe_url(v):
 try:return str(TypeAdapter(PublicHTTPSURL).validate_python(v))
 except ValueError:return None
tree=ast.parse(Path('backend/app/execution/naukri.py').read_text());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='normalized_url');ns={'safe_url':safe_url,'urlsplit':urlsplit,'urlunsplit':urlunsplit,'re':re};exec(compile(ast.Module(body=[node],type_ignores=[]),'<actual-alert-url>','exec'),ns)
out=[]
for values in json.load(sys.stdin):
 refs={}
 for raw in values[:25]:
  try:url=ns['normalized_url'](raw);refs[url.rsplit('-',1)[-1]]=url
  except ValueError:continue
 out.append(list(map(list,refs.items())))
print(json.dumps(out))
"#,
        &cases,
    );
    for (input, want) in cases
        .as_array()
        .unwrap()
        .iter()
        .zip(actual.as_array().unwrap())
    {
        assert_eq!(json!(alert_rules::links(input).unwrap()), *want);
    }
}
