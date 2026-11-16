//! Actual legacy search function with fictional IO adapters; execution deferred to combined gate.
use automated_apply_agents::execution::search;
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
fn oracle(cases: &[Value]) -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let script = r#"
import ast,asyncio,json,re,sys,types
from datetime import datetime,timedelta
from pathlib import Path
from urllib.parse import quote,urlencode
from uuid import NAMESPACE_URL,uuid4,uuid5
scope=dict(globals());tree=ast.parse(Path('backend/app/execution/naukri_native.py').read_text());node=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='search_work');node=ast.fix_missing_locations(ast.NodeTransformer().visit(node))
# Replace only the runtime context import; execute the actual function body/defaults/URL logic.
node.body=[n for n in node.body if not isinstance(n,ast.ImportFrom)]
scope.update(SEARCH='apply_search:naukri',OwnerPreference=object)
async def context(session):return session.profile,True,None
async def instant(session):return session.now
async def put(session,key,value):session.saved=value
scope.update(context=context,instant=instant,queue=types.SimpleNamespace(put=put))
exec(compile(ast.Module(body=[node],type_ignores=[]),'actual_search_work','exec'),scope)
def ns(value):
 if isinstance(value,dict):return types.SimpleNamespace(**{k:ns(v) for k,v in value.items()})
 return value
class Session:
 async def get(self,*args,**kwargs):return types.SimpleNamespace(value=self.old) if self.old else None
async def main():
 out=[]
 for c in json.load(sys.stdin):
  s=Session();s.old=c['old'];s.now=datetime.fromisoformat(c['now']);s.profile=ns(c['profile']);s.profile.preferences=c['profile']['preferences']
  result=await scope['search_work'](s,{'revision':162},types.SimpleNamespace(platforms={'naukri':ns(c['setting'])}),{})
  out.append({k:result[k] for k in ('url','role_index','search_page','candidates_found')} if result else None)
 print(json.dumps(out))
asyncio.run(main())
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
        .write_all(json!(cases).to_string().as_bytes())
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
fn ordinary_search_rotation_fresher_interleaving_encoding_and_bounded_pagination_match_actual_python()
 {
    let now = DateTime::parse_from_rfc3339("2026-11-16T00:00:00Z")
        .unwrap()
        .with_timezone(&Utc);
    let mut cases = vec![];
    for years in [Value::Null, json!(0), json!(0.9), json!(1), json!(4)] {
        for custom in [false, true] {
            for role_index in [0, 1, 2, 3, 4, 5, -1] {
                for old in [
                    json!({}),
                    json!({"search_page":1,"status":"idle","last_finished_at":"2026-11-15T00:00:00Z","last_cycle_count":0,"url":"https://www.naukri.com/rust-engineer-jobs"}),
                    json!({"search_page":2,"status":"idle","last_finished_at":"2026-11-15T00:00:00Z","last_cycle_count":0,"url":"https://www.naukri.com/rust-engineer-jobs-2"}),
                    json!({"next_at":"2026-11-16T00:01:00Z"}),
                ] {
                    let mut old = old;
                    old["role_index"] = json!(role_index);
                    let setting = json!({"sources":["naukri_ui_search"],"preferences_mode":if custom{"custom"}else{"inherit"},"preferences":{"roles":[" C++ / C# Engineer ","Rust Engineer","Trainee Developer"]},"discovery_interval_seconds":1800});
                    let profile = json!({"preferences":{"target_titles":["Rust Engineer","Backend Intern","İ Developer"]},"verified_experience_years":years});
                    cases.push(json!({"old":old,"setting":setting,"profile":profile,"now":now.to_rfc3339()}));
                }
            }
        }
    }
    let expected = oracle(&cases);
    for (index, c) in cases.iter().enumerate() {
        assert_eq!(
            json!(search::proposal(&c["old"], &c["setting"], &c["profile"], now).unwrap()),
            expected[index],
            "case {index}"
        );
    }
}
#[test]
fn search_proposal_holds_disabled_sources_empty_roles_and_corrupt_cursor() {
    let now = DateTime::parse_from_rfc3339("2026-11-16T00:00:00Z")
        .unwrap()
        .with_timezone(&Utc);
    let setting = json!({"sources":[],"preferences_mode":"inherit"});
    let profile = json!({"preferences":{"target_titles":["Rust Engineer"]}});
    assert!(
        search::proposal(&json!({}), &setting, &profile, now)
            .unwrap()
            .is_none()
    );
    let mut setting = setting;
    setting["sources"] = json!(["naukri_ui_search"]);
    assert!(search::proposal(&json!({"role_index":"lost"}), &setting, &profile, now).is_err());
    assert!(
        search::proposal(
            &json!({}),
            &setting,
            &json!({"preferences":{"target_titles":[]}}),
            now
        )
        .unwrap()
        .is_none()
    );
}
