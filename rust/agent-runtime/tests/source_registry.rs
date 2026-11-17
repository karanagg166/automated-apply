//! Deferred saved metadata comparisons. Actual registry rules are loaded without HTTP/settings.
use automated_apply_agents::{
    source_registry::Settings,
    startup_catalog::owner::{self, Route},
};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};
fn now() -> chrono::DateTime<chrono::Utc> {
    chrono::DateTime::parse_from_rfc3339("2026-11-17T00:00:00Z")
        .unwrap()
        .to_utc()
}
fn values(v: &Value) -> BTreeMap<String, String> {
    v.as_object()
        .unwrap()
        .iter()
        .map(|(k, v)| {
            (
                k.clone(),
                v.as_str()
                    .map(String::from)
                    .unwrap_or_else(|| v.to_string()),
            )
        })
        .collect()
}
#[test]
fn saved_source_metadata_matches_actual_registry_without_keys_actor_inputs_or_live_claims() {
    let actor = json!({"actor_id":"fictional/public-jobs","build":"1.2.3","enabled":true,"reviewed":true,"review_expires_at":"2026-11-17T12:00:00Z","platform_usage_included":true,"account_spending_limit_verified":true,"schema_evidence_url":"https://actor-fixture.example/schema","pricing_evidence_url":"https://actor-fixture.example/pricing","permission_evidence_url":"https://actor-fixture.example/terms","pricing_model":"PAY_PER_EVENT","estimated_per_item_usd":0.01,"field_map":{"limit":"maxItems"},"fixed_input":{"private_canary":"PRIVATE_ACTOR_INPUT_CANARY"}});
    let paid = json!({"APIFY_API_TOKEN":"PRIVATE_KEY_CANARY","APIFY_MONTHLY_LIMIT_USD":5,"APIFY_PER_RUN_CAP_USD":1,"APIFY_SOURCES":{"wellfound":actor,"naukri":actor}});
    let mut cases = vec![
        json!({}),
        json!({"GREENHOUSE_BOARDS":{"fictional":"PRIVATE_BOARD_COMPANY_CANARY"}}),
        json!({"LEVER_BOARDS":{"fictional":"Fictional Employer"},"ASHBY_BOARDS":{"fictional":"Fictional Employer"},"SMARTRECRUITERS_BOARDS":{"fictional":"Fictional Employer"}}),
        json!({"APIFY_API_TOKEN":"PRIVATE_KEY_CANARY"}),
        paid.clone(),
    ];
    for n in 0..5 {
        let mut v = paid.clone();
        match n {
            0 => {
                v["APIFY_SOURCES"]["wellfound"]["review_expires_at"] = json!("2026-11-16T12:00:00Z")
            }
            1 => v["APIFY_PER_RUN_CAP_USD"] = json!(0),
            2 => v["APIFY_SOURCE_ROUTES"] = json!({"wellfound":[{},actor]}),
            3 => v["APIFY_SOURCE_ROUTES"] = json!({"wellfound":vec![actor.clone();6]}),
            _ => {
                v["PEOPLE_SEARCH_ENABLED"] = json!(true);
                v["SERPER_API_KEY"] = json!("PRIVATE_SEARCH_KEY_CANARY");
                v["PUBLIC_SEARCH_RIGHTS_REVIEWED"] = json!(true);
                v["PUBLIC_SEARCH_PERMISSION_EVIDENCE_URL"] =
                    json!("https://search-fixture.example/permission");
            }
        }
        cases.push(v);
    }
    let script = r#"import ast,json,re,runpy,sys,types
from datetime import datetime,timedelta,timezone
from enum import StrEnum
from types import SimpleNamespace
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
m=runpy.run_path('rust/scripts/export_apify_contracts.py');load=m['load'];root=m['ROOT'];Actor=m['model']()
class Clock(datetime):
 @classmethod
 def now(cls,tz=None):return datetime(2026,11,17,tzinfo=timezone.utc)
scope={'__name__':'actual_pure_registry','re':re,'json':json,'StrEnum':StrEnum,'datetime':Clock,'timedelta':timedelta,'timezone':timezone,'BaseModel':BaseModel,'ConfigDict':ConfigDict,'Field':Field,'Literal':Literal,'ActorConfiguration':Actor,'JobSourceAdapter':object,'DiscoveryQuery':lambda:SimpleNamespace(keywords=[],locations=[],limit=20)}
load(scope,'backend/app/schemas/discovery.py',{'DiscoveryStatus','DiscoveryError'});scope['Status']=scope['DiscoveryStatus']
load(scope,'backend/app/services/providers/apify.py',{'ACTOR_ID','DENIED_INPUT','safe_actor','execution_input_allowed'})
module=types.ModuleType('backend.app.services.providers.apify');module.execution_input_allowed=scope['execution_input_allowed'];sys.modules[module.__name__]=module
tree=ast.parse((root/'backend/app/services/job_sources/apify_adapter.py').read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ApifyJobAdapter');cls.body=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in {'__init__','actor','validate_configuration'}];exec(compile(ast.Module(body=[cls],type_ignores=[]),'actual_pure_adapter','exec'),scope)
module=types.ModuleType('backend.app.services.job_sources.apify_adapter');module.ApifyJobAdapter=scope['ApifyJobAdapter'];sys.modules[module.__name__]=module
load(scope,'backend/app/services/job_sources/registry.py',{'SourceConfig','APIFY_PORTALS','NAMES','source_registry'})
load(scope,'backend/app/services/startup_discovery/source_registry.py',{'PUBLIC_SOURCES','INTERVALS','startup_sources'})
out=[]
for row in json.load(sys.stdin):
 d=dict(GREENHOUSE_BOARDS={},LEVER_BOARDS={},ASHBY_BOARDS={},SMARTRECRUITERS_BOARDS={},APIFY_API_TOKEN=None,APIFY_SOURCES={},APIFY_SOURCE_ROUTES={},APIFY_MONTHLY_LIMIT_USD=0,APIFY_PER_RUN_CAP_USD=0,PEOPLE_SEARCH_ENABLED=False,SERPER_API_KEY=None,PUBLIC_SEARCH_RIGHTS_REVIEWED=False,PUBLIC_SEARCH_PERMISSION_EVIDENCE_URL=None);d.update(row);settings=SimpleNamespace(**d)
 out.append({'jobs':[v.model_dump(mode='json') for v in scope['source_registry'](settings).values()],'startups':scope['startup_sources'](settings)})
assert 'backend.app.core.config' not in sys.modules;assert 'httpx' not in sys.modules
print(json.dumps(out))
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
        .write_all(json!(cases).to_string().as_bytes())
        .unwrap();
    let output = c.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let actual: Value = serde_json::from_slice(&output.stdout).unwrap();
    for (i, (input, want)) in cases.iter().zip(actual.as_array().unwrap()).enumerate() {
        let s = Settings::from_values(&values(input)).unwrap();
        for (got, want, id) in [
            (s.jobs(now()), &want["jobs"], "id"),
            (s.startups(now()), &want["startups"], "provider"),
        ] {
            for expected in want.as_array().unwrap() {
                let row = got["sources"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .find(|r| r[id] == expected[id])
                    .unwrap();
                for (key, value) in expected.as_object().unwrap() {
                    // Native reviewed execution is additional source evidence; legacy DTO parity remains separate.
                    if key == "configuration" && row["adapter_type"] == "apify" {
                        let mut original = row[key].clone();
                        original.as_object_mut().unwrap().remove("native_execution");
                        assert_eq!(&original, value, "case {i} original configuration");
                        assert_eq!(
                            row[key]["native_execution"]["ready"], false,
                            "legacy cases have no pinned build/schema review"
                        );
                        continue;
                    }
                    assert_eq!(
                        &row[key], value,
                        "case {i} source {} field {key}",
                        expected[id]
                    );
                }
            }
            for row in got["sources"].as_array().unwrap() {
                assert_eq!(row["live_verified"], false);
                assert_eq!(row["dispatch_authorized"], false);
                assert_eq!(row["read_only"].as_bool().unwrap_or(true), true);
            }
            for secret in [
                "PRIVATE_KEY_CANARY",
                "PRIVATE_SEARCH_KEY_CANARY",
                "PRIVATE_BOARD_COMPANY_CANARY",
                "PRIVATE_ACTOR_INPUT_CANARY",
                "https://actor-fixture.example/terms",
            ] {
                assert!(!got.to_string().contains(secret));
            }
            assert_eq!(got["provider_calls"], 0);
            assert_eq!(got["writes"], 0);
        }
    }
}
#[test]
fn public_search_requires_permission_evidence_and_settings_reject_ambiguous_or_unbounded_configuration()
 {
    let mut v = json!({"PEOPLE_SEARCH_ENABLED":true,"SERPER_API_KEY":"PRIVATE_SEARCH_KEY_CANARY","PUBLIC_SEARCH_RIGHTS_REVIEWED":true});
    let row = Settings::from_values(&values(&v))
        .unwrap()
        .startup("public_search", now())
        .unwrap();
    assert_eq!(row["configured"], true);
    assert_eq!(row["authorized"], false);
    assert_eq!(row["availability"], "configuration_required");
    v["PUBLIC_SEARCH_PERMISSION_EVIDENCE_URL"] = json!("https://127.0.0.1/permission");
    assert!(Settings::from_values(&values(&v)).is_err());
    for v in [
        json!({"APIFY_MONTHLY_LIMIT_USD":"NaN"}),
        json!({"APIFY_PER_RUN_CAP_USD":101}),
        json!({"APIFY_SOURCES":[]}),
        json!({"APIFY_SOURCE_ROUTES":{"wellfound":{}}}),
        json!({"LEVER_BOARDS":{"Case":"Fictional","case":"Fictional"}}),
        json!({"ASHBY_BOARDS":{"https://private":"Fictional"}}),
        json!({"SMARTRECRUITERS_BOARDS":{"board":" "}}),
        json!({"LEVER_REGION":"private"}),
        json!({"GREENHOUSE_BOARDS":{"x":"x".repeat(524289)}}),
    ] {
        assert!(Settings::from_values(&values(&v)).is_err(), "{v}");
    }
    assert!(
        Settings::from_values(&BTreeMap::new())
            .unwrap()
            .startup("unknown", now())
            .is_err()
    );
}
#[test]
fn startup_owner_routes_are_closed_and_distinguish_read_preview_and_original_run_creation() {
    for (path, method) in [
        ("/api/v1/startups/sources", "GET"),
        ("/api/v1/discovery/sources", "GET"),
        ("/api/v1/startups/discovery/preview", "POST"),
        ("/api/v1/startups/discovery/runs", "POST"),
        (
            "/api/v1/startups/discovery/runs/00000000-0000-0000-0000-000000000001",
            "GET",
        ),
    ] {
        assert_eq!(owner::route(path).unwrap().method(), method);
    }
    for path in [
        "/api/v1/startups/discovery/runs/",
        "/api/v1/startups/discovery/runs/private",
        "/api/v1/startups/discovery/runs/00000000-0000-0000-0000-000000000001/retry",
        "/api/v1/startups/sources/reload",
    ] {
        assert_eq!(owner::route(path), None);
    }
    assert_eq!(
        owner::route("/api/v1/startups/sources"),
        Some(Route::Sources)
    );
}
