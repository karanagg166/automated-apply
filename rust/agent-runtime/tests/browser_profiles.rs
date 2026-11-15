use automated_apply_agents::{
    Failure,
    browser_profiles::{self, Settings},
};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use std::collections::BTreeMap;
fn profile() -> Value {
    json!({"id":"11111111-1111-4111-8111-111111111111","browser_session_id":"22222222-2222-4222-8222-222222222222","connected":true,"window_id":10,"commands_enabled":false,"last_heartbeat":"2026-11-16T00:00:00Z","version":1,"label":"Fictional Brave","secret_hash":"NEVER_PUBLIC"})
}
#[test]
fn browser_profile_liveness_bounds_window_and_future_clock_without_secret_projection() {
    let now = DateTime::parse_from_rfc3339("2026-11-16T00:01:39.999Z")
        .unwrap()
        .with_timezone(&Utc);
    let p = profile();
    assert!(browser_profiles::online(&p, now).unwrap());
    assert!(!browser_profiles::online(&p, now + chrono::Duration::milliseconds(1)).unwrap());
    assert!(!browser_profiles::online(&p, now - chrono::Duration::seconds(101)).unwrap());
    let public = browser_profiles::public(&p, &p["id"], now).unwrap();
    assert_eq!(public["status"], "CONNECTED");
    assert_eq!(public["selected"], true);
    assert!(!public.to_string().contains("NEVER_PUBLIC"));
    assert_eq!(public.as_object().unwrap().len(), 10);
    for window in [Value::Null, json!(-1), json!(true), json!("10")] {
        let mut p = p.clone();
        p["window_id"] = window;
        assert!(!browser_profiles::online(&p, now).unwrap());
    }
    let mut p = p.clone();
    p["connected"] = json!(false);
    assert_eq!(
        browser_profiles::public(&p, &Value::Null, now).unwrap()["status"],
        "DISCONNECTED"
    );
}
#[test]
fn browser_profile_config_and_routes_are_closed_and_disabled_by_default() {
    assert!(Settings::from_values(&BTreeMap::new()).is_ok());
    for id in [
        "a".repeat(31),
        "a".repeat(33),
        "q".repeat(32),
        "A".repeat(32),
    ] {
        assert_eq!(
            Settings::from_values(&BTreeMap::from([("CHROME_EXTENSION_ID".into(), id)])).err(),
            Some(Failure("invalid_browser_extension_id"))
        );
    }
    assert_eq!(
        Settings::from_values(&BTreeMap::from([(
            "CHROME_NATIVE_MESSAGING_ENABLED".into(),
            "true".into()
        )]))
        .err(),
        Some(Failure("browser_extension_id_required"))
    );
    assert_eq!(
        browser_profiles::route(browser_profiles::NATIVE)
            .unwrap()
            .method(),
        "POST"
    );
    assert_eq!(
        browser_profiles::route(browser_profiles::PROFILES)
            .unwrap()
            .method(),
        "GET"
    );
    for path in [
        "/api/v1/browser/chrome-profiles/x/disconnect",
        "/api/v1/browser/chrome-profiles/select/extra",
        "/api/v1/browser/chrome-profiles/",
        "/api/v1/local-agent/chrome/extra",
    ] {
        assert!(browser_profiles::route(path).is_none());
    }
}
#[test]
fn browser_profile_public_projection_matches_actual_python_for_ordinary_saved_bindings() {
    use std::{
        io::Write,
        path::PathBuf,
        process::{Command, Stdio},
    };
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let code = r#"
import ast,json,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
scope={'datetime':datetime,'LIVE_SECONDS':100}
tree=ast.parse(Path('backend/app/browser/chrome_profiles.py').read_text())
nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'online','public'}]
exec(compile(ast.Module(body=nodes,type_ignores=[]),'legacy-profile-oracle','exec'),scope)
now=datetime.fromisoformat('2026-11-16T00:01:00+00:00');scope['now']=lambda:now
raw=json.load(sys.stdin);out=[scope['public'](v,s) for v,s in raw]
assert 'backend.app.core.config' not in sys.modules
print(json.dumps(out))
"#;
    let now = DateTime::parse_from_rfc3339("2026-11-16T00:01:00Z")
        .unwrap()
        .with_timezone(&Utc);
    let mut cases = Vec::new();
    let mut actual = Vec::new();
    for connected in [false, true] {
        for delta in [0, 1, 60, 99, 100, 101, 3600] {
            for window in [Value::Null, json!(0), json!(10)] {
                let mut p = profile();
                p["connected"] = json!(connected);
                p["window_id"] = window;
                p["last_heartbeat"] = json!((now - chrono::Duration::seconds(delta)).to_rfc3339());
                let selected = if delta % 2 == 0 {
                    p["id"].clone()
                } else {
                    Value::Null
                };
                cases.push(json!([p, selected]));
                actual.push(browser_profiles::public(&p, &selected, now).unwrap());
            }
        }
    }
    let mut child = Command::new(root.join(".venv/bin/python"))
        .args(["-c", code])
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
        .write_all(json!(cases).to_string().as_bytes())
        .unwrap();
    let out = child.wait_with_output().unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let expected: Value = serde_json::from_slice(&out.stdout).unwrap();
    assert_eq!(json!(actual), expected);
    assert_eq!(cases.len(), 42);
}
