//! Deferred actual identity/filter comparisons; fictional pinned clock, no HTTP/settings/ORM imports.
use automated_apply_agents::job_sources::{contract, filters, identity};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
use uuid::Uuid;
fn now() -> DateTime<Utc> {
    DateTime::parse_from_rfc3339("2026-11-17T00:00:00Z")
        .unwrap()
        .to_utc()
}
fn item() -> Value {
    json!({"source_name":"fictional_feed","source_job_id":"12345","original_url":"https://job-fixture.example/jobs/12345?utm_source=fixture","title":"Rust Engineer","description":"Fictional public role. ".repeat(20),"company_name":"Fictional Employer","company_domain":"company-fixture.example","location":"Berlin","remote_type":"remote","first_observed_date":"2026-11-17T00:00:00Z","last_observed_date":"2026-11-17T00:00:00Z","retrieved_at":"2026-11-17T00:00:00Z"})
}
fn oracle(cases: &Value) -> Vec<Value> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let script = r#"import ast,hashlib,json,re,runpy,sys
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from typing import Annotated,Any,Literal
from uuid import UUID
from pydantic import BaseModel,ConfigDict,Field,StringConstraints,field_validator,model_validator
from backend.app.core.job_urls import ats_job_url,canonical_job_url
m=runpy.run_path('rust/scripts/export_execution_contracts.py')
s=dict(__name__='fictional_intake_rules',re=re,hashlib=hashlib,datetime=datetime,timedelta=timedelta,timezone=timezone,Any=Any,Literal=Literal,Annotated=Annotated,StringConstraints=StringConstraints,BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,field_validator=field_validator,model_validator=model_validator,ats_job_url=ats_job_url,canonical_job_url=canonical_job_url)
m['load'](s,'backend/app/schemas/normalized_job.py',{'NormalizedJob'})
m['load'](s,'backend/app/schemas/discovery.py',{'Text','DiscoveryQuery'})
m['load'](s,'backend/app/services/job_deduplication.py',{'digest','folded','observation_key','content_identity'})
class Clock(datetime):
 @classmethod
 def now(cls,tz=None):return datetime(2026,11,17,tzinfo=timezone.utc)
s['datetime']=Clock
tree=ast.parse((m['ROOT']/'backend/app/services/job_discovery_service.py').read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='JobDiscoveryService');method=next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='run')
loop=next(n for n in ast.walk(method) if isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='job' and isinstance(n.iter,ast.Attribute) and n.iter.attr=='jobs' and isinstance(n.iter.value,ast.Name) and n.iter.value.id=='result')
code=compile(ast.Module(body=[loop],type_ignores=[]),'actual_discovery_filter','exec')
out=[]
for c in json.load(sys.stdin):
 try:
  if c['op']=='fold':v=s['folded'](c['value'])
  else:
   model=s['NormalizedJob'].model_validate(c['item'])
   if c['op']=='identity':v=dict(observation=s['observation_key'](model),content=s['content_identity'](model,UUID(c['company']) if c['company'] else None))
   else:
    scope=s.copy();scope.update(request=SimpleNamespace(query=s['DiscoveryQuery'].model_validate(c['explicit'])),query=s['DiscoveryQuery'].model_validate(c['effective']),result=SimpleNamespace(jobs=[model]),counts={'skipped':0},filtered=[])
    exec(code,scope);v=dict(included=bool(scope['filtered']),skipped=scope['counts']['skipped'])
  out.append({'ok':True,'value':v})
 except (ValueError,TypeError,KeyError,AttributeError,OverflowError):out.append({'ok':False})
assert 'backend.app.core.config' not in sys.modules
assert 'sqlalchemy' not in sys.modules
assert 'httpx' not in sys.modules
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
fn exact_observation_and_conservative_content_identity_match_forty_actual_cases() {
    let mut cases = Vec::new();
    for n in 0..40 {
        let mut v = item();
        let mut company = Some(Uuid::from_u128(123456));
        match n % 20 {
            0 => {}
            1 => company = None,
            2 => v["company_domain"] = Value::Null,
            3 => v["location"] = Value::Null,
            4 => v["description"] = json!("short"),
            5 => v["remote_type"] = json!("unknown"),
            6 => v["source_job_id"] = Value::Null,
            7 => v["source_job_id"] = json!(""),
            8 => v["data_provenance"] = json!({"board_token":"global:fictional"}),
            9 => v["data_provenance"] = json!({"board_token":"eu:fictional"}),
            10 => v["description"] = json!("ß".repeat(100)),
            11 => v["description"] = json!("x".repeat(199)),
            12 => v["description"] = json!("x".repeat(200)),
            13 => v["title"] = json!(" <b>RUST</b>\n Engineer "),
            14 => v["location"] = json!(" BERLIN\u{001c} "),
            15 => v["remote_type"] = json!("hybrid"),
            16 => v["original_url"] = json!("https://boards.greenhouse.io/fictional/jobs/12345/"),
            17 => v["data_provenance"] = json!({"board_token":"fictional"}),
            18 => v["description"] = Value::Null,
            19 => v["company_domain"] = json!("other-fixture.example"),
            _ => unreachable!(),
        }
        if n >= 20 {
            v["source_job_id"] = Value::Null;
        }
        cases.push(json!({"op":"identity","item":v,"company":company}));
    }
    let expected = oracle(&json!(cases));
    for (n, (case, expected)) in cases.iter().zip(expected).enumerate() {
        let job = contract::normalize(case["item"].clone(), now()).unwrap();
        let company = case["company"].as_str().map(|s| s.parse::<Uuid>().unwrap());
        let result = json!({"observation":identity::observation_key(&job).unwrap(),"content":identity::content_identity(&job,company).unwrap()});
        assert_eq!(expected["ok"], true);
        assert_eq!(result, expected["value"], "case {n}");
    }
}
#[test]
fn discovery_filters_match_thirty_two_actual_explicit_and_profile_query_cases() {
    let mut cases = Vec::new();
    for n in 0..32 {
        let mut v = item();
        let mut explicit = json!({});
        let mut effective = json!({});
        match n {
            0 => {}
            1 => explicit["keywords"] = json!(["Rust"]),
            2 => explicit["keywords"] = json!(["Golang"]),
            3 => {
                explicit["locations"] = json!(["Mumbai"]);
                v["location"] = Value::Null;
            }
            4 => explicit["locations"] = json!(["Mumbai"]),
            5 => {
                explicit["remote_preference"] = json!("onsite");
                v["remote_type"] = json!("unknown");
            }
            6 => explicit["remote_preference"] = json!("onsite"),
            7 => {
                explicit["employment_types"] = json!(["contract"]);
                v["employment_type"] = Value::Null;
            }
            8 => {
                explicit["employment_types"] = json!(["contract"]);
                v["employment_type"] = json!("full_time");
            }
            9 => {
                explicit["max_age_days"] = json!(14);
                v["date_posted"] = json!("2026-10-01T00:00:00Z");
            }
            10 => {
                explicit["max_age_days"] = json!(14);
                v["date_posted"] = Value::Null;
            }
            11 => effective["keywords"] = json!(["Golang"]),
            12 => effective["remote_preference"] = json!("onsite"),
            13 => effective["locations"] = json!(["Tokyo"]),
            14 => {
                explicit["keywords"] = json!(["straße"]);
                v["title"] = json!("STRASSE Engineer");
            }
            15 => {
                explicit["keywords"] = json!(["Rust"]);
                v["title"] = json!("Go Engineer");
            }
            16 => {
                explicit["remote_preference"] = json!("any");
                v["remote_type"] = json!("hybrid");
            }
            17 => explicit["remote_preference"] = json!("hybrid"),
            18 => {
                explicit["max_age_days"] = json!(14);
                explicit["keywords"] = json!(["Golang"]);
                v["date_posted"] = json!("2026-10-01T00:00:00Z");
            }
            19 => {
                explicit["employment_types"] = json!(["full_time"]);
                v["employment_type"] = json!("full-time");
            }
            20 => {
                explicit["locations"] = json!(["Mumbai"]);
                v["location"] = json!("");
            }
            21 => {
                explicit["keywords"] = json!(["Σίσυφος"]);
                v["title"] = json!("ΣΊΣΥΦΟΣ Engineer");
            }
            22 => {
                explicit["max_age_days"] = json!(14);
                v["date_posted"] = json!("2026-11-03T00:00:00Z");
            }
            23 => {
                explicit["max_age_days"] = json!(14);
                v["date_posted"] = json!("2026-11-02T23:59:59Z");
            }
            24 => {
                explicit["remote_preference"] = json!("onsite");
                v["remote_type"] = json!("unknown");
                v["is_remote"] = json!(true);
            }
            25 => {
                explicit["keywords"] = json!(["Rust"]);
                v["title"] = json!("<b>Rust</b> Engineer");
            }
            26 => {
                effective["keywords"] = json!(["Golang"]);
                effective["employment_types"] = json!(["contract"]);
            }
            27 => {
                explicit["locations"] = json!(["India"]);
                v["location"] = json!("Worldwide");
            }
            28 => {
                explicit["remote_preference"] = json!("hybrid");
                v["remote_type"] = json!("hybrid");
            }
            29 => {
                explicit["employment_types"] = json!([]);
                v["employment_type"] = json!("contract");
            }
            30 => {
                explicit["max_age_days"] = json!(14);
                v["date_posted"] = json!("2026-11-17T00:00:00Z");
            }
            31 => explicit["employment_types"] = json!(["invalid"]),
            _ => unreachable!(),
        }
        for (k, value) in explicit.as_object().unwrap() {
            effective[k] = value.clone();
        }
        cases.push(json!({"op":"filter","item":v,"explicit":explicit,"effective":effective}));
    }
    let expected = oracle(&json!(cases));
    for (n, (case, expected)) in cases.iter().zip(expected).enumerate() {
        let result =
            filters::exclusion(&case["item"], &case["explicit"], &case["effective"], now());
        assert_eq!(
            result.is_ok(),
            expected["ok"].as_bool().unwrap(),
            "case {n}"
        );
        if let Ok(reason) = result {
            assert_eq!(
                json!({"included":reason.is_none(),"skipped":usize::from(reason.is_some())}),
                expected["value"],
                "case {n}"
            );
        }
    }
}
#[test]
fn identity_fold_matches_actual_twelve_html_unicode_and_whitespace_cases() {
    let values = [
        None,
        Some(""),
        Some("<b>Rust</b> Engineer"),
        Some("Straße"),
        Some("\u{001c}RUST\n Engineer\u{001f}"),
        Some("a<>b"),
        Some("<tag\n attr>Role</tag>"),
        Some("ΣΊΣΥΦΟΣ"),
        Some("👩‍💻 Engineer"),
        Some("Rust &amp; PostgreSQL"),
        Some("a\r\nb"),
        Some(" < unfinished"),
    ];
    let cases = values
        .iter()
        .map(|v| json!({"op":"fold","value":v}))
        .collect::<Vec<_>>();
    let expected = oracle(&json!(cases));
    for (value, expected) in values.into_iter().zip(expected) {
        assert_eq!(expected["ok"], true);
        assert_eq!(json!(identity::folded(value)), expected["value"]);
    }
    let mut v = item();
    v["data_provenance"] = json!({"board_token":{"private":"PRIVATE_UNTYPED_CANARY"}});
    assert!(identity::observation_key(&v).is_err());
}
