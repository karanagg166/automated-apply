//! Source-phase queue policy/filter/evidence regression corpora; final-gate execution only.
use automated_apply_agents::execution::{
    contracts::{self, Kind},
    filters, receipts,
};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};

fn oracle(input: Value) -> Value {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let script = r#"
import ast,hashlib,json,re,sys,types
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID,NAMESPACE_URL,uuid4,uuid5
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
module=types.ModuleType('actual_execution_policy_oracle');sys.modules[module.__name__]=module
scope=module.__dict__;scope.update({k:v for k,v in globals().copy().items() if not k.startswith('__')})
def load(path,names):
 body=[]
 for n in ast.parse(Path(path).read_text()).body:
  name=n.name if isinstance(n,(ast.ClassDef,ast.FunctionDef)) else n.targets[0].id if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) else None
  if name in names:body.append(n)
 assert len(body)==len(names),(path,names)
 exec(compile(ast.Module(body=body,type_ignores=[]),path,'exec'),scope)
load('backend/app/execution/contracts.py',{'Contract'})
load('backend/app/execution/queue_contracts.py',{'Platform','QueueLimits','QueuePreferences','PlatformQueuePolicy','QueuePolicy'})
load('backend/app/execution/application_queue.py',{'TERMINAL','FILTER_HOLD_REASONS','uses_capacity','limits','listing_exclusion','initial_item','inspection_order'})
load('backend/app/execution/naukri_receipts.py',{'PREFIX','recorded_application','worker_recorded'})
raw=json.load(sys.stdin);now=datetime.fromisoformat(raw['now']);out={}
if 'policies' in raw:
 out['policies']=[];out['limits']=[]
 for p in raw['policies']:
  try:
   p=scope['QueuePolicy'].model_validate(p);out['policies'].append(p.model_dump(mode='json'));out['limits'].append(scope['limits'](p,'naukri'))
  except ValueError:out['policies'].append(None);out['limits'].append(None)
if 'capacity' in raw:out['capacity']=[scope['uses_capacity'](v) for v in raw['capacity']]
if 'exclusions' in raw:out['exclusions']=[scope['listing_exclusion'](f,p,now) for f,p in raw['exclusions']]
if 'orders' in raw:out['orders']=[scope['inspection_order'](types.SimpleNamespace(value=v,created_at=datetime.fromisoformat(created)),years,now) for v,created,years in raw['orders']]
if 'initial' in raw:out['initial']=[scope['initial_item'](config,'naukri',url,'saved_verified_job',reference,now) for config,url,reference in raw['initial']]
if 'receipts' in raw:out['receipts']=[[scope['recorded_application'](k,v,now),scope['worker_recorded'](k,v,now)] for k,v in raw['receipts']]
if 'zones' in raw:out['days']=[now.astimezone(ZoneInfo(z)).date().isoformat() for z in raw['zones']]
assert 'backend.app.core.config' not in sys.modules
print(json.dumps(out))
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
        .write_all(input.to_string().as_bytes())
        .unwrap();
    let output = child.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).unwrap()
}
fn now() -> DateTime<Utc> {
    DateTime::parse_from_rfc3339("2026-11-16T00:00:00Z")
        .unwrap()
        .with_timezone(&Utc)
}
#[test]
fn execution_queue_policy_defaults_current_saved_controls_custom_limits_and_timezone_match_python()
{
    let policies = vec![
        json!({}),
        json!({"global_limits":{"max_job_age_days":14,"applicant_limit":1000,"minimum_match_score":50},"platforms":{"naukri":{"enabled":true,"mode":"SUPERVISED","owner_submission_authorized":true,"supervised_submission_cap":4,"hourly_submission_cap":1,"skill_match_mode":"any"}}}),
        json!({"platforms":{"naukri":{"preferences":{"roles":[" Rust Engineer ","Rust Engineer"],"locations":["Remote"],"experience_min":0,"experience_max":2},"cap_mode":"custom","age_mode":"custom","applicants_mode":"custom","limits":{"daily_cap":3,"max_job_age_days":14,"applicant_limit":1000,"minimum_match_score":99}}}}),
        json!({"platforms":{}}),
        json!({"day_timezone":"../../private"}),
        json!({"platforms":{"naukri":{"preferences":{"experience_min":5,"experience_max":1}}}}),
        json!({"background_only":false}),
        json!({"concurrency":2}),
    ];
    let zones = json!([
        "Asia/Kolkata",
        "UTC",
        "Europe/London",
        "America/New_York",
        "Pacific/Kiritimati",
        "Pacific/Pago_Pago"
    ]);
    let expected = oracle(json!({"now":now().to_rfc3339(),"policies":policies,"zones":zones}));
    for (index, p) in policies.into_iter().enumerate() {
        let value = contracts::normalize(Kind::Policy, p);
        if expected["policies"][index].is_null() {
            assert!(value.is_err(), "policy {index}");
        } else {
            let value = value.unwrap();
            assert_eq!(value, expected["policies"][index], "policy {index}");
            assert_eq!(
                contracts::limits(&value, "naukri").unwrap(),
                expected["limits"][index]
            );
        }
    }
    for (index, zone) in zones.as_array().unwrap().iter().enumerate() {
        assert_eq!(
            contracts::day_bucket(now(), zone.as_str().unwrap()).unwrap(),
            expected["days"][index]
        );
    }
}
#[test]
fn execution_queue_filter_holds_date_uncertainty_applicant_bounds_and_fair_inspection_match_python()
{
    let mut capacity = Vec::new();
    for reason in filters::FILTER_HOLDS {
        for changes in [
            json!({}),
            json!({"admitted_actions":[{"fingerprint":"apply:initial"}]}),
            json!({"packet_id":"fictional-packet"}),
            json!({"form_pending":true}),
            json!({"lease_until":"2026-11-16T01:00:00Z"}),
        ] {
            let mut value = json!({"stage":"NEEDS_INPUT","status":"waiting","reason":reason,"admitted_actions":[]});
            for (k, v) in changes.as_object().unwrap() {
                value[k] = v.clone();
            }
            capacity.push(value);
        }
    }
    for stage in filters::TERMINAL {
        capacity.push(json!({"stage":stage}));
    }
    capacity.push(
        json!({"stage":"SUBMISSION_UNKNOWN","status":"unknown","admitted_actions":["retained"]}),
    );
    let dates = vec![
        json!({"posted_at":"2026-11-15T12:00:00Z"}),
        json!({"posted_at":"2026-11-02T00:00:00Z"}),
        json!({"posted_at":"2026-11-01T23:59:59Z"}),
        json!({"posted_at":"2026-11-16T00:00:01Z"}),
        json!({"posted_at":"2026-11-15T12:00:00"}),
        json!({"posted_date":"2026-11-02"}),
        json!({"posted_date":"2026-11-01"}),
        json!({"posted_date":"2026-10-30"}),
        json!({"posted_date":"2026-11-20"}),
        json!({}),
    ];
    let bounds = [
        Value::Null,
        json!(0),
        json!(999),
        json!(1000),
        json!(1001),
        json!(-1),
        json!(true),
        json!("999"),
        json!(999.0),
    ];
    let mut exclusions = Vec::new();
    for date in dates {
        for lo in &bounds {
            for hi in &bounds {
                for mode in ["needs_review", "skip", "allow_lower_bound", "allow"] {
                    let mut facts = date.clone();
                    facts["applicants_min"] = lo.clone();
                    facts["applicants_max"] = hi.clone();
                    exclusions.push(json!([facts,{"max_job_age_days":14,"applicant_limit":1000,"unknown_applicants":mode}]));
                }
            }
        }
    }
    let mut orders = Vec::new();
    for operation in ["inspect_job", "inspect_profile", "apply"] {
        for created in ["2026-11-15T21:00:00Z", "2026-11-15T23:30:00Z"] {
            for years in [Value::Null, json!(0), json!(1.5), json!(7)] {
                orders.push(json!([{"operation":operation,"url":"https://www.naukri.com/job-listings-fictional-0-to-2-years-123456789012"},created,years]));
            }
        }
    }
    let initial = json!([[{"revision":9},"https://www.naukri.com/job-listings-fictional-123456789012",null],[{"revision":9},"https://www.naukri.com/job-listings-fictional-123456789012","fictional-message-reference"]]);
    let expected = oracle(
        json!({"now":now().to_rfc3339(),"capacity":capacity,"exclusions":exclusions,"orders":orders,"initial":initial}),
    );
    for (index, value) in capacity.iter().enumerate() {
        assert_eq!(
            filters::uses_capacity(value),
            expected["capacity"][index].as_bool().unwrap(),
            "capacity {index}"
        );
    }
    for (index, case) in exclusions.iter().enumerate() {
        assert_eq!(
            json!(filters::listing_exclusion(&case[0], &case[1], now()).unwrap()),
            expected["exclusions"][index],
            "exclusion {index}"
        );
    }
    for (index, case) in orders.iter().enumerate() {
        let created = DateTime::parse_from_rfc3339(case[1].as_str().unwrap())
            .unwrap()
            .with_timezone(&Utc);
        assert_eq!(
            filters::inspection_order(&case[0], created, case[2].as_f64(), now()),
            expected["orders"][index].as_u64().unwrap() as u8
        );
    }
    for (index, case) in initial.as_array().unwrap().iter().enumerate() {
        assert_eq!(
            filters::initial_item(
                &case[0],
                case[1].as_str().unwrap(),
                "saved_verified_job",
                case[2].as_str(),
                now()
            )
            .unwrap(),
            expected["initial"][index]
        );
    }
}
#[test]
fn execution_receipt_provenance_matches_legacy_and_first_worker_requires_current_admitted_context()
{
    let id = "11111111-1111-4111-8111-111111111111";
    let key = "naukri_worker_receipt:123456789012";
    let hash = "a".repeat(64);
    let dispatch = json!({"state":"CLICKED","admission_id":id,"profile_binding_id":id,"account_sha256":hash,"document_id":"fictional-apply-document","evidence_sha256":"e".repeat(64),"observed_at":"2026-11-15T23:59:57Z"});
    let receipt = json!({"queue_id":id,"requisition":"123456789012","confirmation_source":"naukri_application_status_ui","operation_mode":"recurring_worker_ui","persistent_after_reload":true,"status":"Application Sent","account_sha256":hash,"worker_dispatched":true,"observed_at":"2026-11-15T23:59:59Z","first_observation":{"document_id":"first-document","evidence_sha256":"b".repeat(64),"observed_at":"2026-11-15T23:59:58Z"},"second_observation":{"document_id":"second-document","evidence_sha256":"c".repeat(64),"state":"APPLICATION_SENT","account_sha256":hash},"apply_dispatch_observation":dispatch});
    let work = json!({"id":id,"platform":"naukri","requisition":"123456789012","candidate_profile_id":id,"account_sha256":hash,"account_binding_revision":3,"stage":"SUBMITTED_CONFIRMED","submission_mode":"recurring_worker_ui","admitted_actions":[{"id":id,"fingerprint":"apply:initial","at":"2026-11-15T23:59:56Z"}],"document_id":"fictional-apply-document","apply_dispatch_observation":dispatch});
    let account = json!({"approved":true,"candidate_profile_id":id,"profile_binding_id":id,"account_sha256":hash,"revision":3});
    assert!(receipts::first_worker_bound(
        key,
        &receipt,
        &work,
        &account,
        now()
    ));
    let mut cases = vec![json!([key, receipt])];
    for changes in [
        json!({"persistent_after_reload":false}),
        json!({"confirmation_source":"human_reported"}),
        json!({"operation_mode":"owner_authorized_software_operated_ui"}),
        json!({"observed_at":"2026-11-16T00:05:01Z"}),
        json!({"observed_at":"2026-11-15T23:59:58Z"}),
        json!({"observed_at":"2026-11-15T23:59:59"}),
        json!({"account_sha256":"bad"}),
        json!({"second_observation":{"document_id":"first-document","state":"APPLICATION_SENT","account_sha256":hash,"evidence_sha256":"c".repeat(64)}}),
    ] {
        let mut changed = receipt.clone();
        for (k, v) in changes.as_object().unwrap() {
            changed[k] = v.clone();
        }
        cases.push(json!([key, changed]));
    }
    cases.push(json!(["naukri_receipt:123456789012",{"requisition":"123456789012","confirmation_source":"naukri_application_status_ui","operation_mode":"owner_authorized_software_operated_ui","status":"Application Sent","persistent_after_reload":true,"private_evidence_sha256":"d".repeat(64),"observed_at":"2026-11-15T23:59:58Z"}]));
    cases.push(json!([key, null]));
    let expected = oracle(json!({"now":now().to_rfc3339(),"receipts":cases}));
    for (index, case) in cases.iter().enumerate() {
        assert_eq!(
            json!([
                receipts::recorded_application(case[0].as_str().unwrap(), &case[1], now()),
                receipts::worker_recorded(case[0].as_str().unwrap(), &case[1], now())
            ]),
            expected["receipts"][index]
        );
    }
    for changes in [
        json!({"stage":"SUBMISSION_UNKNOWN"}),
        json!({"admitted_actions":[]}),
        json!({"apply_dispatch_observation":null}),
        json!({"document_id":"unrelated-apply-document"}),
        json!({"account_binding_revision":2}),
        json!({"submission_mode":"manual_extension"}),
    ] {
        let mut changed = work.clone();
        for (k, v) in changes.as_object().unwrap() {
            changed[k] = v.clone();
        }
        assert!(!receipts::first_worker_bound(
            key,
            &receipt,
            &changed,
            &account,
            now()
        ));
    }
    let mut reconciled = receipt.clone();
    reconciled["worker_dispatched"] = json!(false);
    assert!(!receipts::first_worker_bound(
        key,
        &reconciled,
        &work,
        &account,
        now()
    ));
    for field in ["candidate_profile_id", "profile_binding_id", "revision"] {
        let mut malformed = account.clone();
        malformed.as_object_mut().unwrap().remove(field);
        assert!(!receipts::first_worker_bound(
            key,
            &receipt,
            &work,
            &malformed,
            now()
        ));
    }
}
