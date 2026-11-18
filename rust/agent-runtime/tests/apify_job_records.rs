//! Deferred actual portal record parity and exact USD arithmetic. No settings/provider clients.
use automated_apply_agents::apify_jobs::{money::Usd, record};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
fn now() -> chrono::DateTime<chrono::Utc> {
    chrono::DateTime::parse_from_rfc3339("2026-11-17T00:00:00Z")
        .unwrap()
        .to_utc()
}
fn oracle(cases: &Value) -> Vec<Value> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let script = r#"import ast,json,math,re,runpy,sys
from datetime import datetime,timedelta,timezone
from decimal import Decimal,ROUND_CEILING
from typing import Any,Literal
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
from backend.app.core.job_urls import ats_job_url,canonical_job_url
class Clock(datetime):
 @classmethod
 def now(cls,tz=None):return datetime(2026,11,17,tzinfo=timezone.utc)
m=runpy.run_path('rust/scripts/export_execution_contracts.py');root=m['ROOT']
s=dict(__name__='fictional_apify_record',re=re,math=math,json=json,datetime=datetime,timedelta=timedelta,timezone=timezone,Any=Any,Literal=Literal,BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,field_validator=field_validator,model_validator=model_validator,ats_job_url=ats_job_url,canonical_job_url=canonical_job_url)
m['load'](s,'backend/app/schemas/normalized_job.py',{'NormalizedJob'})
m['load'](s,'backend/app/services/job_sources/normalization.py',{'parse_date','remote_policy','employment','salary_fields'})
m['load'](s,'backend/app/services/job_sources/apify_adapter.py',{'ACTOR_CATALOG'})
cls=next(n for n in ast.parse((root/'backend/app/services/job_sources/apify_adapter.py').read_text()).body if isinstance(n,ast.ClassDef) and n.name=='ApifyJobAdapter')
method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='normalize_portal_record');exec(compile(ast.Module(body=[method],type_ignores=[]),'actual_apify_job_record','exec'),s)
s['datetime']=Clock
subject=type('ApifyJobAdapter',(),{})();subject.configuration={'actor_id':'fictional/public-jobs'}
out=[]
for c in json.load(sys.stdin):
 try:
  if c.get('money'):
   v=int((Decimal(str(c['value']))*1000000).to_integral_value(rounding=ROUND_CEILING))
  else:
   v=s['normalize_portal_record'](subject,c['portal'],c['value']).model_dump(mode='json')
   info=v['company_intelligence'];info.pop('profile_url',None);info.pop('founder_urls',None)
   if not(set(info)-{'source','verification_status'}):v['company_intelligence']={}
  out.append({'ok':True,'value':v})
 except (ValueError,TypeError,KeyError,AttributeError,OverflowError):out.append({'ok':False})
assert 'httpx' not in sys.modules
assert 'backend.app.core.config' not in sys.modules
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
fn base() -> Value {
    json!({"id":12345,"url":"https://job-fixture.example/jobs/12345","applyUrl":"https://job-fixture.example/apply/12345","companyName":"Fictional Employer","title":"Fictional Engineer","description":"Fictional public job evidence","location":"Remote","employmentType":"Full-time","skills":"Rust, Python","salary":"USD 50k - 70k annual","postedDate":"2026-11-01T00:00:00Z"})
}
#[test]
fn selected_apify_portal_records_match_actual_normalizer_without_personal_profile_retention() {
    let mut cases = automated_apply_agents::source_registry::APIFY_PORTALS
        .iter()
        .map(|portal| json!({"portal":portal,"value":base()}))
        .collect::<Vec<_>>();
    let variants = vec![
        json!({"id":false}),
        json!({"id":true}),
        json!({"id":1.5}),
        json!({"salary":90000}),
        json!({"salary":true}),
        json!({"skills":[" Rust ","Python"]}),
        json!({"skills":"Rust,,Python"}),
        json!({"skills":{}}),
        json!({"location":["Remote","India"]}),
        json!({"location":[1]}),
        json!({"employmentType":1}),
        json!({"description":null}),
        json!({"url":"http://job-fixture.example/jobs/12345"}),
        json!({"title":""}),
        json!({"companyName":{"name":"Fictional Employer","domain":"employer-fixture.example","stage":"seed","batch":"W25","technologies":["Rust"],"remote_policy":"remote"}}),
        json!({"companyName":{"name":"Fictional Employer","founder_urls":["https://www.linkedin.com/in/fictional-founder"],"profile_url":"https://company-fixture.example/about"}}),
        json!({"companyName":{"name":12}}),
        json!({"postedDate":"20261101"}),
        json!({"isRemote":true,"location":"Office"}),
        json!({"seniority":"junior"}),
        json!({"id":null,"jobId":"alternate-id"}),
        json!({"companyDomain":"https://bad-domain.example/path"}),
    ];
    for patch in variants {
        let mut v = base();
        v.as_object_mut()
            .unwrap()
            .extend(patch.as_object().unwrap().clone());
        cases.push(json!({"portal":"naukri","value":v}));
    }
    assert_eq!(cases.len(), 31);
    let expected = oracle(&json!(cases));
    for (i, (case, want)) in cases.iter().zip(expected).enumerate() {
        let got = record::normalize(
            case["portal"].as_str().unwrap(),
            "fictional/public-jobs",
            &case["value"],
            now(),
        );
        assert_eq!(got.is_ok(), want["ok"] == true, "case {i}");
        if let Ok(got) = got {
            assert_eq!(got, want["value"], "case {i}");
            assert!(!got.to_string().contains("fictional-founder"));
        }
    }
}
#[test]
fn exact_estimate_ceiling_matches_decimal_without_underreserving_binary_float_fractions() {
    let cases = [
        0.0,
        -0.0,
        0.1,
        0.2,
        0.3,
        0.000001,
        0.0000001,
        0.0000011,
        1e-12,
        0.1000000001,
        1.005,
        0.3333333333333333,
        0.9999999999,
        1.0000001,
        99.999999,
        100.0,
        999999.999999,
        1e12,
    ];
    let input = cases
        .iter()
        .map(|value| json!({"money":true,"value":value}))
        .collect::<Vec<_>>();
    let expected = oracle(&json!(input));
    for (value, want) in cases.iter().zip(expected) {
        assert_eq!(
            Usd::estimate(&json!(value)).unwrap().micros(),
            want["value"].as_u64().unwrap(),
            "{value}"
        );
    }
    assert_eq!(
        Usd::estimated_total(&json!(0), &json!(0.0000001), 100)
            .unwrap()
            .micros(),
        100,
        "per-item ceilings are intentionally conservative"
    );
}
#[test]
fn plain_usd_caps_and_private_vendor_record_guards_are_conservative() {
    for (raw, want) in [
        ("0", "0.000000"),
        ("0.000001", "0.000001"),
        ("1.25", "1.250000"),
        ("9999999999.999999", "9999999999.999999"),
    ] {
        assert_eq!(Usd::parse(raw).unwrap().decimal(), want);
    }
    for raw in [
        "",
        " 1",
        "+1",
        "-1",
        "1e-6",
        "1.",
        ".1",
        "01",
        "0.0000001",
        "NaN",
        "10000000000",
    ] {
        assert!(Usd::parse(raw).is_err(), "{raw}");
    }
    for raw in [json!(-0.1), json!(true), json!("1"), Value::Null] {
        assert!(Usd::estimate(&raw).is_err());
    }
    let mut job = base();
    job["salary"] = json!({"private_token":"PRIVATE_VENDOR_CANARY"});
    assert!(record::normalize("naukri", "fictional/public-jobs", &job, now()).is_err());
    assert!(record::normalize("linkedin", "fictional/public-jobs", &base(), now()).is_err());
}
