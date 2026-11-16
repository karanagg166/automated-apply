//! Deferred actual-source calendar/window/query/signal comparisons. No mailbox/settings access.
use automated_apply_agents::{
    Failure,
    gmail_accounts::{
        contract::{self, Kind},
        sync_rules,
    },
};
use chrono::{DateTime, Utc};
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
fn policy(value: Value) -> Value {
    let mut value = contract::normalize(Kind::Policy, value).unwrap();
    value.as_object_mut().unwrap().remove("expected_version");
    value
}
#[test]
fn gmail_selected_windows_and_queries_match_actual_calendar_clamp_checkpoint_and_folder_source() {
    let mut cases = Vec::new();
    for now in [
        "2024-03-31T12:34:56.123456+00:00",
        "2025-03-31T12:34:56+00:00",
        "2026-01-31T00:00:00+00:00",
    ] {
        for months in [None, Some(1), Some(2), Some(24)] {
            for mode in 0..3 {
                let mut p = json!({"expected_version":0,"read_body":true,"body_purpose":"Read selected fictional job messages","sender_allowlist":["fictional@example.com"],"query_allowlist":"subject:jobs","folders":["INBOX","SENT"],"label_allowlist":["Label_jobs"],"backfill_days":7});
                if let Some(months) = months {
                    p["history_months"] = json!(months);
                }
                let nowtime = DateTime::parse_from_rfc3339(now)
                    .unwrap()
                    .with_timezone(&Utc);
                let mut state = json!({"window_start":null,"window_end":null,"checkpoint":null});
                if mode == 1 {
                    state["checkpoint"] = json!(nowtime - chrono::Duration::days(1));
                }
                if mode == 2 {
                    state["window_start"] = json!(nowtime - chrono::Duration::days(2));
                    state["window_end"] = json!(nowtime - chrono::Duration::days(1));
                    state["folder_index"] = json!(1);
                }
                cases.push(json!({"now":now,"policy":policy(p),"state":state}));
            }
        }
    }
    let actual = oracle(
        r#"import ast,calendar,json,re,sys,types
from datetime import datetime,timedelta,timezone
from pathlib import Path
tree=ast.parse(Path('backend/app/integrations/gmail/read_service.py').read_text())
service=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='GmailReadService')
sync=next(n for n in service.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='sync')
start=next(i for i,n in enumerate(sync.body) if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='end')
end=next(i for i in range(start,len(sync.body)) if isinstance(sync.body[i],ast.Expr) and isinstance(sync.body[i].value,ast.Call) and isinstance(sync.body[i].value.func,ast.Attribute) and isinstance(sync.body[i].value.func.value,ast.Name) and sync.body[i].value.func.value.id=='value')
window_nodes=sync.body[start:end]
scope={}
loop=next(n for n in ast.walk(sync) if isinstance(n,ast.For) and isinstance(n.iter,ast.Call) and isinstance(n.iter.func,ast.Name) and n.iter.func.id=='range')
query_nodes=loop.body[:2]
folder_nodes=[n for n in loop.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id in {'folder_index','folder'}]
request=next(n.value.value for n in loop.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='page')
labels=next(k.value for k in request.keywords if k.arg=='labels')
out=[]
for c in json.load(sys.stdin):
 clock=datetime.fromisoformat(c['now'])
 class Clock(datetime):
  @classmethod
  def now(cls,tz=None):return clock
 ns={'datetime':Clock,'timedelta':timedelta,'timezone':timezone,'calendar':calendar,'value':dict(c['state']),'policy':types.SimpleNamespace(**c['policy'])}
 exec(compile(ast.fix_missing_locations(ast.Module(body=window_nodes+query_nodes+folder_nodes,type_ignores=[])),'<actual-selected-window>','exec'),ns)
 selected=eval(compile(ast.Expression(body=labels),'<actual-labels>','eval'),ns)
 out.append({'start':ns['start'].isoformat(),'end':ns['end'].isoformat(),'query':ns['query'],'labels':selected,'folder':ns['folder']})
assert 'backend.app.core.config' not in sys.modules
print(json.dumps(out))
"#,
        &json!(cases),
    );
    for (index, (case, want)) in cases.iter().zip(actual.as_array().unwrap()).enumerate() {
        let now = DateTime::parse_from_rfc3339(case["now"].as_str().unwrap())
            .unwrap()
            .with_timezone(&Utc);
        let window = sync_rules::window(&case["policy"], &case["state"], now).unwrap();
        assert_eq!(
            window.start,
            DateTime::parse_from_rfc3339(want["start"].as_str().unwrap())
                .unwrap()
                .with_timezone(&Utc),
            "case {index}"
        );
        assert_eq!(
            window.end,
            DateTime::parse_from_rfc3339(want["end"].as_str().unwrap())
                .unwrap()
                .with_timezone(&Utc)
        );
        let (labels, query, folder) =
            sync_rules::request(&case["policy"], &case["state"], &window).unwrap();
        assert_eq!(json!(labels), want["labels"]);
        assert_eq!(json!(query), want["query"]);
        assert_eq!(json!(folder), want["folder"]);
    }
}
#[test]
fn gmail_metadata_subject_signals_match_actual_uncertain_projection_and_never_confirm_submission() {
    let mut cases = Vec::new();
    for subject in [
        "Application received",
        "Interview for Rust engineer position",
        "Application unsuccessful rejection",
        "Recruiter response about job",
        "Application status update under review",
        "Thank you for applying",
        "Personal newsletter",
    ] {
        for historical in [false, true] {
            cases.push(json!({"subject":subject,"historical":historical}));
        }
    }
    let actual = oracle(
        r#"import ast,json,re,sys,types
from pathlib import Path
tree=ast.parse(Path('backend/app/integrations/gmail/read_service.py').read_text())
topic=next(n for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='TOPIC')
service=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='GmailReadService')
sync=next(n for n in service.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='sync')
evidence=next(n for n in ast.walk(sync) if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='evidence' and isinstance(n.value,ast.Dict))
out=[]
for c in json.load(sys.stdin):
 ns={'re':re,'subject':c['subject'],'policy':types.SimpleNamespace(folders=['INBOX'] if c['historical'] else [])}
 exec(compile(ast.fix_missing_locations(ast.Module(body=[topic,evidence],type_ignores=[])),'<actual-subject-signals>','exec'),ns)
 out.append(ns['evidence'] if ns['TOPIC'].search(c['subject']) else None)
print(json.dumps(out))
"#,
        &json!(cases),
    );
    let now = DateTime::parse_from_rfc3339("2026-11-16T12:00:00Z")
        .unwrap()
        .with_timezone(&Utc);
    for (case, want) in cases.iter().zip(actual.as_array().unwrap()) {
        let historical = case["historical"] == true;
        let mut p = json!({"expected_version":0,"enabled":true,"label_allowlist":["Label_jobs"]});
        if historical {
            p["folders"] = json!(["INBOX"]);
        }
        let p = policy(p);
        let window = sync_rules::window(&p, &json!({}), now).unwrap();
        let metadata = json!({"id":"msg-1","threadId":"thread-1","internalDate":now.timestamp_millis().to_string(),"labelIds":["Label_jobs","INBOX"],"payload":{"headers":[{"name":"From","value":"Fictional <fictional@example.com>"},{"name":"Subject","value":case["subject"]}]}});
        let selected = sync_rules::metadata(
            &metadata,
            "msg-1",
            &p,
            &window,
            if historical { Some("INBOX") } else { None },
        )
        .unwrap();
        assert_eq!(
            selected.map(|s| s.evidence).as_ref(),
            if want.is_null() { None } else { Some(want) }
        );
    }
}
#[test]
fn selected_cursor_completion_and_metadata_scope_do_not_skip_folder_or_emit_forbidden_query() {
    let p = policy(
        json!({"expected_version":0,"enabled":true,"folders":["INBOX","SENT"],"history_months":1}),
    );
    let now = Utc::now();
    let mut state =
        json!({"window_start":now-chrono::Duration::days(5),"window_end":now,"page_token":null});
    let window = sync_rules::window(&p, &state, now).unwrap();
    assert!(
        sync_rules::request(&p, &state, &window)
            .unwrap()
            .1
            .is_none()
    );
    assert!(sync_rules::advance(&p, &mut state, Some("next-private-page"), &window).unwrap());
    assert_eq!(
        sync_rules::advance(&p, &mut state, Some("next-private-page"), &window).unwrap_err(),
        Failure("gmail_page_token_invalid")
    );
    assert!(!sync_rules::advance(&p, &mut state, None, &window).unwrap());
    assert_eq!(state["folder_index"], 1);
    assert!(!state["window_end"].is_null());
    assert_eq!(
        sync_rules::request(&p, &state, &window).unwrap().0,
        vec!["SENT"]
    );
    assert!(!sync_rules::advance(&p, &mut state, None, &window).unwrap());
    assert!(state["window_end"].is_null());
    assert!(state["checkpoint"].is_string());
}
