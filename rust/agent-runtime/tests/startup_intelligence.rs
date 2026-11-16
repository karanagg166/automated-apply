//! Deferred actual size/hiring comparisons and explicit conservative correction regressions.
use automated_apply_agents::startup_catalog::intelligence;
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
fn now() -> chrono::DateTime<chrono::Utc> {
    chrono::DateTime::parse_from_rfc3339("2026-11-17T12:00:00Z")
        .unwrap()
        .to_utc()
}
fn observation(
    n: u32,
    source: &str,
    identity: &str,
    count: Option<i64>,
    band: &str,
    at: &str,
) -> Value {
    json!({"id":format!("00000000-0000-4000-8000-{n:012}"),"source":source,"identity_key":identity,"source_url":format!("https://company-fixture.example/source/{n}"),"observed_at":at,"attributes":{"employee_count":count,"team_size_band":band,"historical":false},"verification_status":"source_reported"})
}
fn oracle(input: Value) -> Value {
    let script = r#"import json,re,runpy,sys
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace as NS
load=runpy.run_path('rust/scripts/export_execution_contracts.py')['load'];s={'__name__':'intelligence_fixture','timezone':timezone,'re':re,'timedelta':timedelta,'now':lambda:datetime(2026,11,17,12,tzinfo=timezone.utc)}
load(s,'backend/app/services/startup_discovery/normalizer.py',{'BANDS','utc'})
load(s,'backend/app/services/startup_discovery/intelligence.py',{'company_size','hiring_intelligence'})
def row(v):
 v=dict(v)
 for k in ('observed_at','last_observed_at','date_posted'):
  if v.get(k):v[k]=datetime.fromisoformat(v[k].replace('Z','+00:00'))
 return NS(**v)
out=[]
for case in json.load(sys.stdin):
 observations=[row(v) for v in case['observations']]
 if case['op']=='size':out.append(s['company_size'](observations))
 else:out.append(s['hiring_intelligence']([row(v) for v in case['jobs']],observations,30,[row(v) for v in case['job_observations']]))
assert 'backend.app.core.config' not in sys.modules;print(json.dumps(out))
"#;
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let mut c = Command::new(root.join(".venv/bin/python"))
        .current_dir(root)
        .args(["-B", "-c", script])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    c.stdin
        .take()
        .unwrap()
        .write_all(input.to_string().as_bytes())
        .unwrap();
    let out = c.wait_with_output().unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    serde_json::from_slice(&out.stdout).unwrap()
}
#[test]
fn startup_company_size_matches_actual_source_identity_priority_overlap_conflicts_and_historical_evidence()
 {
    let base = observation(
        1,
        "manual",
        "first",
        Some(12),
        "11-50",
        "2026-11-16T12:00:00Z",
    );
    let mut cases = Vec::new();
    let mut native = Vec::new();
    for n in 0..24 {
        let mut rows = vec![base.clone()];
        match n {
            0 => rows.clear(),
            1 => {}
            2 => {
                rows[0]["attributes"]["employee_count"] = Value::Null;
                rows[0]["attributes"]["team_size_band"] = json!("unknown");
            }
            3 => rows[0]["verification_status"] = json!("requires_review"),
            4 => rows[0]["attributes"]["historical"] = json!(true),
            5 => rows[0]["observed_at"] = json!("2026-01-01T00:00:00Z"),
            6 => {
                let mut human = observation(
                    2,
                    "manual",
                    "human",
                    Some(5),
                    "1-10",
                    "2026-11-14T12:00:00Z",
                );
                human["verification_status"] = json!("human_confirmed");
                rows.push(human);
            }
            7 => rows.push(observation(
                2,
                "public_source",
                "other",
                Some(5),
                "1-10",
                "2026-11-15T12:00:00Z",
            )),
            8 => rows.push(observation(
                2,
                "manual",
                "first",
                Some(5),
                "1-10",
                "2026-11-15T12:00:00Z",
            )),
            9..=12 => {
                rows = vec![
                    observation(
                        1,
                        "manual",
                        "first",
                        if n == 9 {
                            Some(8)
                        } else if n == 10 {
                            Some(1)
                        } else {
                            None
                        },
                        "1-10",
                        "2026-11-16T12:00:00Z",
                    ),
                    observation(
                        2,
                        "public_source",
                        "other",
                        None,
                        if n == 11 { "11-50" } else { "2-10" },
                        "2026-11-15T12:00:00Z",
                    ),
                ];
            }
            13 => rows.push(observation(
                2,
                "public_source",
                "other",
                Some(12),
                "11-50",
                "2026-11-16T12:00:00Z",
            )),
            14 => {
                rows[0]["verification_status"] = json!("human_confirmed");
                rows.push(observation(
                    2,
                    "public_source",
                    "other",
                    Some(5),
                    "1-10",
                    "2026-11-16T12:00:00Z",
                ));
            }
            15 => {
                rows[0]["observed_at"] = json!("2026-11-16T17:30:00+05:30");
            }
            16 => {
                rows[0]["observed_at"] = json!("2026-11-16T12:00:00");
            }
            17 => {
                rows[0]["attributes"]["employee_count"] = Value::Null;
            }
            18 => {
                rows = vec![observation(
                    1,
                    "manual",
                    "first",
                    None,
                    "500+",
                    "2026-11-16T12:00:00Z",
                )]
            }
            19 => {
                rows = vec![observation(
                    1,
                    "manual",
                    "first",
                    Some(501),
                    "500+",
                    "2026-11-16T12:00:00Z",
                )]
            }
            20 => {
                rows[0]["verification_status"] = json!("human_confirmed");
                let mut second = observation(
                    2,
                    "public_source",
                    "other",
                    Some(5),
                    "1-10",
                    "2026-11-16T12:00:00Z",
                );
                second["verification_status"] = json!("human_confirmed");
                rows.push(second);
            }
            21 => rows.push(observation(
                2,
                "manual",
                "first",
                Some(5),
                "1-10",
                "2026-11-16T12:00:00Z",
            )),
            22 => rows.push(observation(
                2,
                "manual",
                "second",
                Some(5),
                "1-10",
                "2026-11-16T12:00:00Z",
            )),
            _ => {
                rows[0]["attributes"]["historical"] = json!(true);
                rows.push(observation(
                    2,
                    "manual",
                    "first",
                    None,
                    "2-10",
                    "2026-11-15T12:00:00Z",
                ));
            }
        }
        native.push(intelligence::company_size(&rows, now(), 180).unwrap());
        cases.push(json!({"op":"size","observations":rows}));
    }
    assert_eq!(json!(native), oracle(json!(cases)));
}
fn job() -> Value {
    json!({"id":"11111111-1111-4111-8111-111111111111","title":"Fictional Rust Engineer","job_url":"https://company-fixture.example/jobs/1","source_platform":"manual","source_verification_status":"source_reported","discovery_metadata":{},"last_observed_at":"2026-11-16T12:00:00Z","date_posted":null,"location":"Remote","remote_type":"remote"})
}
#[test]
fn startup_hiring_matches_actual_saved_jobs_expiry_board_and_attributable_statement_precedence() {
    let mut cases = Vec::new();
    let mut native = Vec::new();
    for n in 0..26 {
        let mut jobs = vec![job()];
        let mut observations = Vec::new();
        let mut boards = Vec::new();
        match n{
        0=>jobs.clear(),1=>{},2=>jobs[0]["discovery_metadata"]["is_confirmed_current"]=json!(true),3=>{jobs[0]["discovery_metadata"]["is_confirmed_current"]=json!(true);jobs[0]["source_verification_status"]=json!("requires_review");},4=>jobs[0]["discovery_metadata"]["listing_status"]=json!("closed"),5=>jobs[0]["discovery_metadata"]["is_expired"]=json!(true),6=>jobs[0]["discovery_metadata"]["date_expires"]=json!("2026-11-16T00:00:00Z"),7=>jobs[0]["discovery_metadata"]["expires_at"]=json!("2026-12-01T00:00:00Z"),8=>jobs[0]["discovery_metadata"]["expires_at"]=json!("malformed"),9=>jobs[0]["last_observed_at"]=json!("2026-01-01T00:00:00Z"),10=>jobs[0]["last_observed_at"]=Value::Null,
        11..=13=>boards.push(json!({"job_id":jobs[0]["id"],"source":"greenhouse","verification_status":if n==13{"requires_review"}else{"source_reported"},"last_observed_at":if n==12{"2026-01-01T00:00:00Z"}else{"2026-11-16T12:00:00Z"}})),
        14..=21|23..=25=>{
            if !matches!(n,19|20|24|25){jobs.clear();}let mut o=observation(1,"manual","first",None,"unknown","2026-11-16T12:00:00Z");o["attributes"]["hiring_statement"]=json!(if matches!(n,14|24){"hiring_possible"}else{"not_currently_hiring"});o["attributes"]["authoritative_statement"]=json!(true);
            match n{16=>o["observed_at"]=json!("2026-01-01T00:00:00Z"),17=>o["attributes"]["historical"]=json!(true),18=>o["verification_status"]=json!("requires_review"),20=>jobs[0]["discovery_metadata"]["is_confirmed_current"]=json!(true),21|23=>{let mut second=o.clone();second["id"]=json!("00000000-0000-4000-8000-000000000002");second["attributes"]["hiring_statement"]=json!("hiring_possible");if n==21{second["observed_at"]=json!("2026-11-15T00:00:00Z");}observations.push(second);},24=>jobs[0]["discovery_metadata"]["listing_status"]=json!("closed"),25=>jobs[0]["last_observed_at"]=json!("2026-01-01T00:00:00Z"),_=>{}}
            observations.push(o);
        },22=>jobs[0]["discovery_metadata"]["expires_at"]=json!("2026-12-01T00:00:00"),_=>unreachable!(),
    }
        native.push(intelligence::hiring(&jobs, &observations, &boards, now(), 30).unwrap());
        cases.push(json!({"op":"hiring","jobs":jobs,"observations":observations,"job_observations":boards}));
    }
    assert_eq!(json!(native), oracle(json!(cases)));
}
#[test]
fn startup_intelligence_refuses_future_proof_and_unqualified_negative_hiring_without_inventing_counts()
 {
    let future = observation(
        1,
        "manual",
        "first",
        Some(12),
        "11-50",
        "2026-11-18T12:00:00Z",
    );
    let size = intelligence::company_size(&[future], now(), 180).unwrap();
    assert_eq!(size["team_size_band"], "unknown");
    assert!(size["employee_count"].is_null());
    let mut future_job = job();
    future_job["last_observed_at"] = json!("2026-11-18T12:00:00Z");
    future_job["discovery_metadata"]["is_confirmed_current"] = json!(true);
    assert_eq!(
        intelligence::hiring(&[future_job], &[], &[], now(), 30).unwrap()["hiring_status"],
        "hiring_unknown"
    );
    let mut negative = observation(
        1,
        "manual",
        "first",
        None,
        "unknown",
        "2026-11-16T12:00:00Z",
    );
    negative["attributes"]["hiring_statement"] = json!("not_currently_hiring");
    assert_eq!(
        intelligence::hiring(&[], &[negative.clone()], &[], now(), 30).unwrap()["hiring_status"],
        "hiring_unknown"
    );
    negative["attributes"]["authoritative_statement"] = json!(true);
    assert_eq!(
        intelligence::hiring(&[], &[negative], &[], now(), 30).unwrap()["hiring_status"],
        "not_currently_hiring"
    );
    assert!(intelligence::company_size(&[], now(), 0).is_err());
    assert!(intelligence::hiring(&vec![job(); 501], &[], &[], now(), 30).is_err());
}
