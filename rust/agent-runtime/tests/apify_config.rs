//! Deferred actual actor contract/guard comparisons; no credentials, HTTP or execution.
use automated_apply_agents::apify_config;
use serde_json::{Value, json};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
};

fn actor() -> Value {
    json!({"actor_id":"fictional/public-jobs","build":"1.2.3","schema_evidence_url":"https://actor-fixture.example/schema","pricing_evidence_url":"https://actor-fixture.example/pricing","permission_evidence_url":"https://actor-fixture.example/terms","pricing_model":"PAY_PER_EVENT","estimated_per_item_usd":0.01,"field_map":{"limit":"maxItems"}})
}
fn oracle(cases: Value) -> Value {
    let script = r#"import ast,json,re,runpy,sys
from datetime import datetime,timedelta,timezone
from enum import StrEnum
from types import SimpleNamespace
module=runpy.run_path('rust/scripts/export_apify_contracts.py');Actor=module['model']();load=module['load'];root=module['ROOT']
scope={'re':re,'json':json,'StrEnum':StrEnum}
load(scope,'backend/app/schemas/discovery.py',{'DiscoveryStatus','DiscoveryError'})
load(scope,'backend/app/services/providers/apify.py',{'ACTOR_ID','DENIED_INPUT','safe_actor','execution_input_allowed'})
class Clock(datetime):
 @classmethod
 def now(cls,tz=None):return datetime(2026,11,17,tzinfo=timezone.utc)
scope.update(datetime=Clock,timedelta=timedelta,timezone=timezone,DiscoveryError=scope['DiscoveryError'])
tree=ast.parse((root/'backend/app/services/job_sources/apify_adapter.py').read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ApifyJobAdapter');method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='validate_configuration')
exec(compile(ast.Module(body=[method],type_ignores=[]),'actual_apify_preflight','exec'),scope)
out=[]
for c in json.load(sys.stdin):
 try:
  op=c['op']
  if op=='dto':v=Actor.model_validate(c['value']).model_dump(mode='json')
  elif op=='input':v=Actor.model_validate(c['value']).build_input(SimpleNamespace(**c['query']))
  elif op=='actor':v=scope['safe_actor'](c['value'])
  elif op=='allowed':scope['execution_input_allowed'](c['actor'],c['value']);v=True
  elif op=='preflight':
   a=Actor.model_validate(c['value'])
   def actor():
    a.build_input(SimpleNamespace(keywords=[],locations=[],limit=20));scope['execution_input_allowed'](a.actor_id,a.fixed_input);return a
   subject=SimpleNamespace(api_token=c['credential'],actor=actor,settings=SimpleNamespace(APIFY_PER_RUN_CAP_USD=c['per_run']),monthly_limit_usd=c['monthly'])
   v=not scope['validate_configuration'](subject)
  else:raise AssertionError(op)
  out.append({'ok':True,'value':v})
 except (ValueError,TypeError):out.append({'ok':False})
assert 'backend.app.core.config' not in sys.modules
assert 'httpx' not in sys.modules
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
        .write_all(cases.to_string().as_bytes())
        .unwrap();
    let output = c.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).unwrap()
}
#[test]
fn reviewed_actor_dto_matches_actual_defaults_pinned_build_public_urls_and_numeric_coercion() {
    let mut cases = Vec::new();
    for n in 0..48 {
        let mut v = actor();
        match n {
            0 => {}
            1 => v["enabled"] = json!("YES"),
            2 => v["reviewed"] = json!(0),
            3 => v["reviewed"] = json!(2),
            4 => v["actor_id"] = json!("bare-id"),
            5 => v["actor_id"] = json!("fictional~public-jobs"),
            6 => v["actor_id"] = json!("fictional/a/b"),
            7 => v["actor_id"] = json!("fictional/public jobs"),
            8 => v["build"] = json!("latest"),
            9 => v["build"] = json!("1.2"),
            10 => v["build"] = json!("01.02.003"),
            11 => v["schema_evidence_url"] = json!("http://actor-fixture.example/schema"),
            12 => v["pricing_evidence_url"] = json!("https://127.0.0.1/pricing"),
            13 => {
                v["permission_evidence_url"] =
                    json!("https://owner:password@actor-fixture.example/terms")
            }
            14 => {
                v["schema_evidence_url"] =
                    json!("https://actor-fixture.example/schema?b=2&a=1#section")
            }
            15 => v["pricing_model"] = json!("PAY_PER_RESULT"),
            16 => v["estimated_per_item_usd"] = json!("0.05"),
            17 => v["estimated_per_item_usd"] = json!(true),
            18 => v["estimated_per_item_usd"] = json!(-0.01),
            19 => v["estimated_per_item_usd"] = json!(101),
            20 => v["estimated_per_item_usd"] = json!("NaN"),
            21 => v["estimated_start_usd"] = json!(0),
            22 => v["estimated_start_usd"] = json!("0"),
            23 => v["estimated_start_usd"] = Value::Null,
            24 => v["review_expires_at"] = json!("2026-11-17T12:00:00Z"),
            25 => v["review_expires_at"] = json!("2026-11-17T12:00:00"),
            26 => v["review_expires_at"] = json!("2026-11-17T17:30:00.123456789+05:30"),
            27 => v["review_expires_at"] = json!(1794873600),
            28 => v["review_expires_at"] = json!("invalid"),
            29 => v["field_map"] = json!({}),
            30 => v["field_map"] = json!({"limit":"same","query":"same"}),
            31 => v["field_map"] = json!({"unknown":"limit"}),
            32 => v["field_map"] = json!({"limit":"1invalid"}),
            33 => v["field_map"] = json!({"limit":"a".repeat(81)}),
            34 => v["field_map"] = json!({"limit":"a".repeat(82)}),
            35 => v["fixed_input"] = json!({"nested":[true,1,"fictional"]}),
            36 => v["fixed_input"] = json!([]),
            37 => v["extra"] = json!(true),
            38 => {
                v.as_object_mut().unwrap().remove("field_map");
            }
            39 => {
                v.as_object_mut().unwrap().remove("estimated_per_item_usd");
            }
            40 => v = Value::Null,
            41 => v = json!([]),
            42 => v["enabled"] = Value::Null,
            43 => v["platform_usage_included"] = json!("off"),
            44 => v["account_spending_limit_verified"] = json!(1),
            45 => v["review_expires_at"] = json!("2026-11-17"),
            46 => v["actor_id"] = json!("fictional/public-jobs\n"),
            _ => v["estimated_per_item_usd"] = json!(100),
        }
        cases.push(json!({"op":"dto","value":v}));
    }
    let actual = oracle(json!(cases));
    for (i, (v, want)) in cases.iter().zip(actual.as_array().unwrap()).enumerate() {
        let got = match apify_config::normalize(v["value"].clone()) {
            Ok(v) => json!({"ok":true,"value":v}),
            Err(_) => json!({"ok":false}),
        };
        assert_eq!(got, *want, "actor DTO {i}");
        if i == 0 || i == 21 {
            assert_eq!(
                got["value"]["estimated_start_usd"].is_f64(),
                i == 21,
                "omitted default retains integer; explicit input coerces float"
            );
        }
    }
}
#[test]
fn fixed_mapping_identifiers_and_collection_guards_match_actual_pure_implementations() {
    let mut cases = Vec::new();
    for n in 0..12 {
        let mut v = actor();
        v["field_map"] = json!({"query":"search","keywords":"words","location":"place","locations":"places","limit":"maxItems"});
        v["fixed_input"] = json!({"maxItems":999,"fixed":"kept"});
        match n {
            0 => {}
            1 => v["field_map"] = json!({}),
            2 => v["field_map"] = json!({"query":"same","limit":"same"}),
            3 => v["field_map"] = json!({"limit":"maxItems"}),
            4 => v["field_map"] = json!({"limit":"maxItems","keywords":"words"}),
            5 => v["fixed_input"] = json!({"search":"old","words":"old","places":"old"}),
            6 => v["fixed_input"] = json!({}),
            7 => v["field_map"] = json!({"limit":"limit","location":"locations"}),
            8 => v["field_map"] = json!({"limit":"limit","locations":"locations"}),
            9 => v["field_map"] = json!({"limit":"limit","query":"query"}),
            10 => v["field_map"] = json!({"limit":"limit","keywords":"keywords"}),
            _ => {}
        }
        let q = if n == 11 {
            json!({"keywords":[],"locations":[],"limit":1})
        } else {
            json!({"keywords":["Rust","Python"],"locations":["India","Remote"],"limit":20})
        };
        cases.push(json!({"op":"input","value":v,"query":q}));
    }
    for v in [
        "bare",
        "fictional/public-jobs",
        "fictional~public-jobs",
        "../private",
        "a/b/c",
        "https://api.example/a",
        "",
        "actor?token=fictional",
        "a/b\n",
        "a b",
        "a-b_c/def_1",
        &"a".repeat(201),
    ] {
        cases.push(json!({"op":"actor","value":v}));
    }
    for (actor, input) in [
        ("fictional/public-jobs", json!({"limit":20})),
        ("fictional/LinkedIn-jobs", json!({})),
        ("fictional/public-jobs", json!({"cookies":"fictional"})),
        ("fictional/public-jobs", json!({"sessionId":"fictional"})),
        (
            "fictional/public-jobs",
            json!({"nested":{"passWord":"fictional"}}),
        ),
        (
            "fictional/public-jobs",
            json!({"chromeProfile":"fictional"}),
        ),
        ("fictional/public-jobs", json!({"csrf":"fictional"})),
        ("fictional/public-jobs", json!({"li_at":"fictional"})),
        ("fictional/public-jobs", json!({"access_token":"fictional"})),
        (
            "fictional/public-jobs",
            json!({"url":"https://linkedin.com/in/fictional"}),
        ),
        (
            "fictional/public-jobs",
            json!({"query":"Fictional Unicode कंपनी"}),
        ),
        ("a/b/c", json!({})),
    ] {
        cases.push(json!({"op":"allowed","actor":actor,"value":input}));
    }
    let actual = oracle(json!(cases));
    for (i, (c, want)) in cases.iter().zip(actual.as_array().unwrap()).enumerate() {
        let got = match c["op"].as_str().unwrap() {
            "input" => apify_config::normalize(c["value"].clone())
                .and_then(|v| apify_config::build_input(&v, &c["query"])),
            "actor" => apify_config::safe_actor(c["value"].as_str().unwrap()).map(|s| json!(s)),
            _ => apify_config::execution_input_allowed(c["actor"].as_str().unwrap(), &c["value"])
                .map(|_| json!(true)),
        };
        let got = match got {
            Ok(v) => json!({"ok":true,"value":v}),
            Err(_) => json!({"ok":false}),
        };
        assert_eq!(got, *want, "mapping/collection {i}");
    }
}
#[test]
fn saved_review_preflight_matches_actual_prerequisites_without_claiming_live_or_dispatch_authority()
{
    let now = chrono::DateTime::parse_from_rfc3339("2026-11-17T00:00:00Z")
        .unwrap()
        .to_utc();
    let mut cases = Vec::new();
    for n in 0..16 {
        let mut v = actor();
        v["enabled"] = json!(true);
        v["reviewed"] = json!(true);
        v["review_expires_at"] = json!("2026-11-17T12:00:00Z");
        v["platform_usage_included"] = json!(true);
        v["account_spending_limit_verified"] = json!(true);
        let (mut credential, mut monthly, mut per_run) = (true, 5.0, 1.0);
        match n {
            0 => {}
            1 => credential = false,
            2 => v["enabled"] = json!(false),
            3 => v["reviewed"] = json!(false),
            4 => v["review_expires_at"] = Value::Null,
            5 => v["review_expires_at"] = json!("2026-11-17T00:00:00Z"),
            6 => v["review_expires_at"] = json!("2026-11-18T00:00:01Z"),
            7 => v["review_expires_at"] = json!("2026-11-18T00:00:00Z"),
            8 => v["review_expires_at"] = json!("2026-11-17T12:00:00"),
            9 => v["platform_usage_included"] = json!(false),
            10 => v["account_spending_limit_verified"] = json!(false),
            11 => per_run = 0.0,
            12 => monthly = 0.5,
            13 => v["field_map"] = json!({}),
            14 => v["fixed_input"] = json!({"session":"fictional"}),
            _ => v["actor_id"] = json!("fictional/linkedin-jobs"),
        }
        cases.push(json!({"op":"preflight","value":v,"credential":credential,"monthly":monthly,"per_run":per_run}));
    }
    let actual = oracle(json!(cases));
    for (i, (c, want)) in cases.iter().zip(actual.as_array().unwrap()).enumerate() {
        let got = apify_config::preflight(
            c["value"].clone(),
            c["credential"].as_bool().unwrap(),
            c["monthly"].as_f64().unwrap(),
            c["per_run"].as_f64().unwrap(),
            now,
        )
        .unwrap();
        let ready = want["ok"] == true && want["value"] == true;
        assert_eq!(got["configuration_review_ready"], ready, "preflight {i}");
        assert_eq!(got["live_verified"], false);
        assert_eq!(got["dispatch_authorized"], false);
    }
    assert!(apify_config::normalize(json!({"fixed_input":{"large":"x".repeat(65536)}})).is_err());
    assert!(apify_config::preflight(actor(), true, f64::NAN, 1.0, now).is_err());
    let mut v = apify_config::normalize(actor()).unwrap();
    v["fixed_input"] = json!({"nested":"x".repeat(65536)});
    assert!(
        apify_config::build_input(&v, &json!({"keywords":[],"locations":[],"limit":20})).is_err()
    );
}
