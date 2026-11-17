//! Deferred actual DTO comparisons, pinned fictional clock; no provider or owner data.
use automated_apply_agents::job_sources::contract;
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
fn now() -> DateTime<Utc> {
    DateTime::parse_from_rfc3339("2026-11-17T00:00:00Z")
        .unwrap()
        .to_utc()
}
fn base() -> Value {
    json!({"source_name":"fictional_feed","original_url":"https://job-fixture.example/jobs/123?utm_source=fixture&a=1#part","title":" Fictional Rust Engineer "})
}
fn oracle(cases: &Value) -> Vec<Value> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let script = r#"import json,re,runpy,sys
from datetime import datetime,timedelta,timezone
from typing import Any,Literal
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
from backend.app.core.job_urls import ats_job_url,canonical_job_url
m=runpy.run_path('rust/scripts/export_execution_contracts.py')
s=dict(__name__='fictional_job_contract',re=re,datetime=datetime,timedelta=timedelta,timezone=timezone,Any=Any,Literal=Literal,BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,field_validator=field_validator,model_validator=model_validator,ats_job_url=ats_job_url,canonical_job_url=canonical_job_url)
m['load'](s,'backend/app/schemas/normalized_job.py',{'NormalizedJob'})
class Clock(datetime):
 @classmethod
 def now(cls,tz=None):return datetime(2026,11,17,tzinfo=timezone.utc)
s['datetime']=Clock
q=dict(__name__='fictional_query',BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,Literal=Literal)
from typing import Annotated
from pydantic import StringConstraints
q.update(Annotated=Annotated,StringConstraints=StringConstraints)
m['load'](q,'backend/app/schemas/discovery.py',{'Text','DiscoveryQuery'})
out=[]
for c in json.load(sys.stdin):
 try:
  model=s['NormalizedJob'] if c['kind']=='job' else q['DiscoveryQuery']
  out.append({'ok':True,'value':model.model_validate(c['value']).model_dump(mode='json')})
 except (ValueError,TypeError):out.append({'ok':False})
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
fn compare(cases: Vec<Value>) {
    let expected = oracle(&json!(cases));
    for (n, (case, expected)) in cases.into_iter().zip(expected).enumerate() {
        let actual = if case["kind"] == "job" {
            contract::normalize(case["value"].clone(), now())
        } else {
            contract::query(case["value"].clone())
        };
        assert_eq!(
            actual.is_ok(),
            expected["ok"] == true,
            "case {n}: {case} => {actual:?}"
        );
        if let Ok(value) = actual {
            assert_eq!(value, expected["value"], "case {n}");
        }
    }
}
#[test]
fn normalized_job_matches_actual_seventy_evidence_date_url_remote_and_pay_contract_cases() {
    let mut cases = Vec::new();
    for n in 0..70 {
        let mut v = base();
        match n {
            0 => {}
            1 => v["extra"] = json!({"ignored":true}),
            2 => v["remote_type"] = Value::Null,
            3 => v["remote_type"] = json!("unspecified"),
            4 => {
                v["remote_type"] = json!("hybrid");
                v["is_remote"] = json!(true);
            }
            5 => {
                v["remote_type"] = json!("onsite");
                v["is_remote"] = json!(true);
            }
            6 => v["is_remote"] = json!("YES"),
            7 => v["is_remote"] = json!(false),
            8 => v["remote_type"] = json!("unknown"),
            9 => v["company_name"] = json!("\u{001c}  \n"),
            10 => v["salary_currency"] = json!("usd"),
            11 => v["salary_currency"] = json!("€"),
            12 => {
                v["salary_min"] = json!(2);
                v["salary_max"] = json!(1);
            }
            13 => v["salary_min"] = json!("1_000.50"),
            14 => v["experience_min_years"] = json!("1"),
            15 => v["experience_min_years"] = json!(1),
            16 => v["experience_min_years"] = json!(true),
            17 => v["experience_max_years"] = json!(61),
            18 => v["date_posted"] = json!("1989-12-31T23:59:59Z"),
            19 => v["date_posted"] = json!("2026-11-18T00:00:01Z"),
            20 => v["date_posted"] = json!("2026-11-18T00:00:00Z"),
            21 => v["date_posted"] = json!(1767225600),
            22 => v["date_posted"] = json!(1767225600000i64),
            23 => v["date_posted"] = json!("2026-11-01T00:00:00"),
            24 => v["date_posted"] = json!("2026-11-01"),
            25 => {
                v["first_observed_date"] = json!("2026-11-16T00:00:00Z");
                v["last_observed_date"] = json!("2026-11-15T00:00:00Z");
            }
            26 => v["first_observed_date"] = Value::Null,
            27 => v["retrieved_at"] = json!("2026-11-01T05:30:00.123456+05:30"),
            28 => v["original_url"] = json!("http://job-fixture.example/jobs/123"),
            29 => v["original_url"] = json!("https://127.0.0.1/jobs/123"),
            30 => v["original_url"] = json!("https://owner:secret@job-fixture.example/jobs/123"),
            31 => {
                v["application_url"] =
                    json!("https://jobs.lever.co/fictional/abcdefghij-12345/apply")
            }
            32 => {
                v["application_url"] =
                    json!("https://jobs.lever.co/fictional/abcdefghij-12345/apply");
                v["canonical_url"] = json!("https://jobs.lever.co/fictional/abcdefghij-12345");
            }
            33 => v["canonical_url"] = json!("https://other-fixture.example/jobs/999"),
            34 => v["canonical_url"] = v["original_url"].clone(),
            35 => {
                v["application_url"] =
                    json!("https://job-boards.greenhouse.io/fictional/jobs/12345?gh_src=tracking")
            }
            36 => {
                v["application_url"] = json!(
                    "https://jobs.smartrecruiters.com/fictional/12345-fictional-role?oga=true"
                )
            }
            37 => v["company_domain"] = json!(" Company-Fixture.Example. "),
            38 => v["company_domain"] = json!("localhost"),
            39 => v["company_domain"] = json!("bad/path"),
            40 => v["skills_required"] = json!([" Rust ", "", "Rust"]),
            41 => v["skills_required"] = json!([true]),
            42 => v["skills_preferred"] = json!(vec!["Rust"; 101]),
            43 => v["salary_min"] = json!(true),
            44 => v["salary_max"] = json!("nan"),
            45 => v["is_confirmed_current"] = json!("off"),
            46 => v["is_confirmed_current"] = Value::Null,
            47 => v["company_intelligence"] = json!({"stage":1}),
            48 => v["company_intelligence"] = json!({"technologies":[1]}),
            49 => {
                v["company_intelligence"] =
                    json!({"technologies":[" Rust "],"other":{"arbitrary":"unchanged"}})
            }
            50 => v["quality_flags"] = json!(vec!["flag"; 50]),
            51 => v["quality_flags"] = json!(["company_unknown"]),
            52 => v["source_name"] = json!(""),
            53 => v["title"] = json!("x".repeat(256)),
            54 => v["salary_period"] = json!("annual"),
            55 => v["salary_min"] = json!(1000000000001i64),
            56 => v["experience_min_years"] = json!(-1),
            57 => {
                v["experience_min_years"] = json!(2);
                v["experience_max_years"] = json!(1);
            }
            58 => v["source_verification_status"] = json!("verified"),
            59 => v["source_verification_status"] = json!("invented"),
            60 => v["remote_type"] = json!("remote "),
            61 => v["remote_type"] = json!(true),
            62 => v["company_name"] = json!(" Fictional Company "),
            63 => v["description"] = json!(" Fictional description \n"),
            64 => v["salary_currency"] = json!(" USD "),
            65 => v["source_job_id"] = json!(123),
            66 => v["company_intelligence"] = json!([]),
            67 => v["data_provenance"] = json!({"nested":" retained spaces "}),
            68 => v["date_posted"] = json!(true),
            69 => v["original_url"] = json!("https://boards.greenhouse.io/fictional/jobs/12345/"),
            _ => unreachable!(),
        }
        cases.push(json!({"kind":"job","value":v}));
    }
    compare(cases);
}
#[test]
fn discovery_query_matches_actual_thirty_bounded_pagination_and_keyword_cases() {
    let mut cases = Vec::new();
    for n in 0..30 {
        let mut v = json!({});
        match n {
            0 => {}
            1 => v["keywords"] = json!([" Rust ", " Tokio "]),
            2 => v["keywords"] = json!([""]),
            3 => v["keywords"] = json!(vec!["Rust"; 11]),
            4 => v["locations"] = json!([" Remote "]),
            5 => v["page"] = json!("2"),
            6 => v["page"] = json!("2.0"),
            7 => v["page"] = json!("2e0"),
            8 => v["limit"] = json!(true),
            9 => v["limit"] = json!(false),
            10 => v["limit"] = json!(101),
            11 => v["page"] = json!(0),
            12 => v["page"] = json!(100),
            13 => v["page"] = json!(101),
            14 => v["max_age_days"] = json!("14"),
            15 => v["max_age_days"] = json!(3651),
            16 => v["remote_preference"] = json!("hybrid"),
            17 => v["remote_preference"] = json!(" remote "),
            18 => v["employment_types"] = json!(["full_time", "contract"]),
            19 => v["employment_types"] = json!([" Full-time "]),
            20 => v["extra"] = json!(true),
            21 => v["page"] = Value::Null,
            22 => v["keywords"] = Value::Null,
            23 => v["locations"] = json!("remote"),
            24 => v["keywords"] = json!([1]),
            25 => v["limit"] = json!(1.5),
            26 => v["limit"] = json!(1.0),
            27 => v["limit"] = json!("1_0"),
            28 => v["keywords"] = json!(["\u{001c}Rust\u{001f}"]),
            29 => v["employment_types"] = json!(vec!["full_time"; 5]),
            _ => unreachable!(),
        }
        cases.push(json!({"kind":"query","value":v}));
    }
    compare(cases);
}
#[test]
fn normalized_job_record_cap_includes_all_retained_provenance_and_default_fields() {
    let mut value = base();
    value["description"] = json!("x".repeat(200000));
    value["data_provenance"] = json!({"observed":"x".repeat(65000)});
    assert_eq!(
        contract::normalize(value, now()),
        Err(automated_apply_agents::Failure(
            "normalized_job_record_limit"
        ))
    );
    let mut value = base();
    value["ignored"] = json!("x".repeat(1048577));
    assert_eq!(
        contract::normalize(value, now()),
        Err(automated_apply_agents::Failure(
            "normalized_job_input_limit"
        ))
    );
}
