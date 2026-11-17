//! Deferred actual owner-run DTO/hash/query expansion comparisons; no application settings or HTTP.
use automated_apply_agents::job_sources::scope;
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
fn request() -> Value {
    json!({"source":"greenhouse"})
}
fn profile() -> Value {
    json!({"id":"00000000-0000-0000-0000-000000000123","version":3,"full_name":"PRIVATE_CANDIDATE_NAME_CANARY","email":"PRIVATE_CANDIDATE_EMAIL_CANARY","preferences":{"target_titles":["Rust Engineer","Backend Engineer"],"preferred_locations":["Remote","India"],"remote_preference":"remote","employment_types":["full_time"]}})
}
fn oracle(cases: &Value) -> Vec<Value> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let script = r#"import hashlib,json,runpy,sys
from types import SimpleNamespace
m=runpy.run_path('rust/scripts/export_startup_contracts.py');R=m['models']()['discovery-run-request'];Q=R.model_fields['query'].annotation
s={};m['load'](s,'backend/app/services/job_discovery_service.py',{'build_query'})
out=[]
for c in json.load(sys.stdin):
 try:
  if c['op']=='dto':v=R.model_validate(c['value']).model_dump(mode='json')
  elif c['op']=='hash':v=hashlib.sha256(json.dumps(R.model_validate(c['value']).model_dump(mode='json',exclude={'idempotency_key'}),sort_keys=True).encode()).hexdigest()
  else:
   p=c['profile'];p=SimpleNamespace(preferences=SimpleNamespace(**p['preferences'])) if p else None
   v=s['build_query'](Q.model_validate(c['value']),p).model_dump(mode='json')
  out.append({'ok':True,'value':v})
 except (ValueError,TypeError,KeyError,AttributeError):out.append({'ok':False})
assert 'backend.app.core.config' not in sys.modules
assert 'httpx' not in sys.modules
assert 'sqlalchemy' not in sys.modules
print(json.dumps(out))"#;
    let mut p = Command::new(root.join(".venv/bin/python"))
        .current_dir(root)
        .args(["-B", "-c", script])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    p.stdin
        .take()
        .unwrap()
        .write_all(cases.to_string().as_bytes())
        .unwrap();
    let output = p.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).unwrap()
}
#[test]
fn owner_discovery_run_dto_matches_thirty_two_actual_defaults_bounds_and_coercions() {
    let mut cases = Vec::new();
    for n in 0..32 {
        let mut v = request();
        match n {
            0 => {}
            1 => {
                v.as_object_mut().unwrap().remove("source");
            }
            2 => v["source"] = json!("lever"),
            3 => v["source"] = json!("a"),
            4 => v["source"] = json!("Greenhouse"),
            5 => v["source"] = json!("cutshort"),
            6 => v["source"] = json!("greenhouse\n"),
            7 => v["idempotency_key"] = Value::Null,
            8 => v["idempotency_key"] = json!("stable_-123"),
            9 => v["idempotency_key"] = json!("bad.key"),
            10 => v["idempotency_key"] = json!(" bad "),
            11 => v["idempotency_key"] = json!("x".repeat(101)),
            12 => v["idempotency_key"] = json!("x".repeat(100)),
            13 => v["allow_paid"] = json!("YES"),
            14 => v["use_profile"] = json!("false"),
            15 => v["use_profile"] = Value::Null,
            16 => v["query"] = json!({"keywords":[" Rust "]}),
            17 => v["manual_jobs"] = json!([1]),
            18 => v["manual_jobs"] = json!([{}]),
            19 => v["manual_jobs"] = json!(vec![json!({}); 101]),
            20 => v["manual_jobs"] = json!(vec![json!({}); 100]),
            21 => v["extra"] = json!(true),
            22 => v["query"] = Value::Null,
            23 => v["query"] = json!({"page":100}),
            24 => v["query"] = json!({"page":"2.0"}),
            25 => v["query"] = json!({"max_age_days":"14"}),
            26 => v["allow_paid"] = json!("off"),
            27 => v["use_profile"] = json!(0),
            28 => v["source"] = json!("x".repeat(51)),
            29 => v["source"] = json!("greenhouse/jobs"),
            30 => v["manual_jobs"] = json!([{"fixture_float":1e-6}]),
            31 => v["idempotency_key"] = json!(123),
            _ => unreachable!(),
        }
        cases.push(json!({"op":"dto","value":v}));
    }
    let expected = oracle(&json!(cases));
    for (n, (case, expected)) in cases.iter().zip(expected).enumerate() {
        let v = scope::normalize(case["value"].clone());
        assert_eq!(v.is_ok(), expected["ok"].as_bool().unwrap(), "case {n}");
        if let Ok(v) = v {
            assert_eq!(v, expected["value"], "case {n}");
        }
    }
}
#[test]
fn original_run_hash_matches_sixteen_actual_sorted_json_cases_and_excludes_compatibility_key() {
    let mut cases = Vec::new();
    for n in 0..16 {
        let mut v = request();
        v["idempotency_key"] = json!(format!("fictional_{n}"));
        match n % 8 {
            0 => {}
            1 => v["query"] = json!({"keywords":["Café Rust 🚀"]}),
            2 => v["use_profile"] = json!(false),
            3 => v["allow_paid"] = json!(true),
            4 => v["manual_jobs"] = json!([{"float":1e-6,"text":"literal"}]),
            5 => v["query"] = json!({"page":2,"limit":100}),
            6 => v["query"] = json!({"employment_types":["contract","full_time"]}),
            7 => v["source"] = json!("remotive"),
            _ => unreachable!(),
        }
        cases.push(json!({"op":"hash","value":v}));
    }
    let expected = oracle(&json!(cases));
    for (n, (case, expected)) in cases.iter().zip(expected).enumerate() {
        assert_eq!(
            json!(scope::request_hash(&case["value"]).unwrap()),
            expected["value"],
            "case {n}"
        );
    }
    let mut a = request();
    a["idempotency_key"] = json!("first");
    let mut b = a.clone();
    b["idempotency_key"] = json!("second");
    assert_eq!(
        scope::request_hash(&a).unwrap(),
        scope::request_hash(&b).unwrap()
    );
}
#[test]
fn effective_query_matches_twenty_four_actual_explicit_and_profile_expansions() {
    let mut cases = Vec::new();
    for n in 0..24 {
        let mut q = json!({});
        let mut p = profile();
        match n % 12 {
            0 => {}
            1 => q["keywords"] = json!(["Golang"]),
            2 => q["locations"] = json!(["Berlin"]),
            3 => q["remote_preference"] = json!("any"),
            4 => q["employment_types"] = json!(["contract"]),
            5 => q["max_age_days"] = json!(14),
            6 => q["page"] = json!(2),
            7 => {
                p["preferences"]["target_titles"] = json!(
                    (0..12)
                        .map(|i| format!("Fictional role {i}"))
                        .collect::<Vec<_>>()
                )
            }
            8 => {
                p["preferences"]["preferred_locations"] = json!(
                    (0..12)
                        .map(|i| format!("Fictional place {i}"))
                        .collect::<Vec<_>>()
                )
            }
            9 => q["remote_preference"] = json!("onsite"),
            10 => {
                q["keywords"] = json!([" Rust "]);
                q["locations"] = json!([" Remote "]);
            }
            11 => p = Value::Null,
            _ => unreachable!(),
        }
        if n >= 12 {
            q["limit"] = json!(5);
        }
        cases.push(json!({"op":"effective","value":q,"profile":p}));
    }
    let expected = oracle(&json!(cases));
    for (n, (case, expected)) in cases.iter().zip(expected).enumerate() {
        let p = if case["profile"].is_null() {
            None
        } else {
            Some(&case["profile"])
        };
        let result = scope::effective_query(&case["value"], p).unwrap();
        assert_eq!(result, expected["value"], "case {n}");
        assert!(!result.to_string().contains("CANARY"));
    }
}
#[test]
fn private_profile_scope_pins_facts_without_copying_candidate_data_and_disabled_profile_is_ignored()
{
    let p = profile();
    let value = scope::build(request(), Some(&p)).unwrap();
    assert!(!value.to_string().contains("CANARY"));
    assert_eq!(value["profile_pin"]["version"], 3);
    assert_eq!(value["provider_calls"], 0);
    assert_eq!(value["writes"], 0);
    assert_eq!(value["execution_authorized"], false);
    let mut changed = p.clone();
    changed["verified_skills"] = json!(["Rust"]);
    assert_ne!(
        scope::profile_pin(Some(&p)).unwrap(),
        scope::profile_pin(Some(&changed)).unwrap()
    );
    let mut disabled = request();
    disabled["use_profile"] = json!(false);
    let invalid = json!({"private":"PRIVATE_IGNORED_PROFILE_CANARY"});
    let value = scope::build(disabled, Some(&invalid)).unwrap();
    assert!(value["profile_pin"].is_null());
    assert_eq!(value["effective_query"]["keywords"], json!([]));
    assert!(!value.to_string().contains("CANARY"));
    assert!(scope::profile_pin(Some(&invalid)).is_err());
    let mut manual = request();
    manual["manual_jobs"] = json!([{}]);
    assert!(scope::build(manual, None).is_err());
    let mut source = request();
    source["source"] = json!("naukri");
    assert!(scope::build(source, None).is_err());
    let mut large = request();
    large["manual_jobs"] = json!([{"text":"x".repeat(4194305)}]);
    assert!(scope::normalize(large).is_err());
}
