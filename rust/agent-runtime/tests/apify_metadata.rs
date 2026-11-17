//! Deferred source-phase comparisons and isolated loopback HTTP; no actual provider/account access.
use automated_apply_agents::{Failure, apify_metadata as meta};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
};
fn now() -> DateTime<Utc> {
    DateTime::parse_from_rfc3339("2026-11-17T00:00:00Z")
        .unwrap()
        .to_utc()
}
fn document(schema: Value) -> Value {
    json!({"paths":{"/run":{"post":{"requestBody":{"content":{"application/json":{"schema":schema}}}}}}})
}
fn limits() -> Value {
    json!({"data":{"monthlyUsageCycle":{"startAt":"2026-11-01T00:00:00Z","endAt":"2026-12-01T00:00:00Z","private":"PRIVATE_CYCLE_CANARY"},"limits":{"maxMonthlyUsageUsd":10,"maxActorCount":2,"private":"PRIVATE_LIMIT_CANARY"},"current":{"monthlyUsageUsd":3,"actorCount":1,"email":"PRIVATE_ACCOUNT_CANARY"},"email":"PRIVATE_ACCOUNT_CANARY"}})
}
fn usage() -> Value {
    json!({"data":{"usageCycle":{"startAt":"2026-11-01T00:00:00Z","endAt":"2026-12-01T00:00:00Z"},"totalUsageCreditsUsdBeforeVolumeDiscount":1.25,"totalUsageCreditsUsdAfterVolumeDiscount":1.0,"dailyServiceUsages":[{"secret":"PRIVATE_DAILY_CANARY"}],"monthlyServiceUsage":{"secret":"PRIVATE_SERVICE_CANARY"}}})
}
#[test]
fn actor_input_schema_and_digest_match_actual_python_extractor_on_twenty_cases() {
    let mut cases = Vec::new();
    for n in 0..20 {
        let mut d = document(
            json!({"type":"object","properties":{"query":{"type":"string","default":"Fictional café 🚀"}},"n":1e-6}),
        );
        match n {
            0 => {}
            1 => d = json!(null),
            2 => d = json!({}),
            3 => d["paths"] = json!({}),
            4 => d["paths"]["other"] = d["paths"]["/run"].clone(),
            5 => d["paths"]["other"] = document(json!({"type":"array"}))["paths"]["/run"].clone(),
            6 => d = document(json!({})),
            7 => d = document(json!([])),
            8 => d = document(json!(null)),
            9 => {
                d = document(json!({"$ref":"#/components/schemas/Input"}));
                d["components"] = json!({"schemas":{"Input":{"type":"object"}}});
            }
            10 => d = document(json!({"$ref":"https://forbidden-fixture.example/schema"})),
            11 => d = document(json!({"$ref":"#/components/schemas/Missing"})),
            12 => d = document(json!({"$ref":7})),
            13 => {
                d = document(json!({"$ref":"#/components/schemas/Input"}));
                d["components"] = json!({"schemas":{"Input":"invalid"}});
            }
            14 => d["paths"]["ignored"] = json!("invalid"),
            15 => {
                d["paths"]["ignored"] = json!({"get":{"requestBody":{"content":{"application/json":{"schema":{"type":"array"}}}}}})
            }
            16 => d = document(json!({"type":"object","default":{"a":true,"b":1.0}})),
            17 => {
                d = document(json!({"$ref":"#/components/schemas/nested/Input"}));
                d["components"] = json!({"schemas":{"Input":{"type":"string"}}});
            }
            18 => d = document(json!({"$ref":"#/components/schemas/Input","type":"object"})),
            19 => {
                d = document(json!({"$ref":"#/components/schemas/Input"}));
                d["components"] =
                    json!({"schemas":{"Input":{"$ref":"https://never-fetch-fixture.example"}}});
            }
            _ => unreachable!(),
        }
        cases.push(d);
    }
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let script = r#"import hashlib,json,runpy,sys
m=runpy.run_path('rust/scripts/export_apify_contracts.py');scope={}
m['load'](scope,'backend/app/services/providers/apify.py',{'input_schema'})
out=[]
for d in json.load(sys.stdin):
 s=scope['input_schema'](d)
 out.append({'schema':s,'digest':hashlib.sha256(json.dumps(s,sort_keys=True).encode()).hexdigest() if s else None})
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
        .write_all(serde_json::to_string(&cases).unwrap().as_bytes())
        .unwrap();
    let output = p.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let expected: Vec<Value> = serde_json::from_slice(&output.stdout).unwrap();
    let validator = jsonschema::draft202012::options()
        .should_validate_formats(false)
        .build(
            &serde_json::from_str::<Value>(include_str!("../schemas/apify-actor-metadata.json"))
                .unwrap(),
        )
        .unwrap();
    for (d, e) in cases.iter().zip(expected) {
        let a = meta::actor(
            "fictional/public-jobs",
            &json!({"data":{"title":"Fictional actor","pricingInfos":[]}}),
            d,
            now(),
        )
        .unwrap();
        assert_eq!(a["input_schema"], e["schema"]);
        assert_eq!(a["schema_digest"], e["digest"]);
        assert!(validator.is_valid(&a));
        assert_eq!(a["collection_status"], "disabled_pending_review");
        assert_eq!(
            a["source_url"],
            "https://api.apify.com/v2/actors/fictional~public-jobs"
        );
    }
}
#[test]
fn metadata_projections_bound_actor_store_and_inspection_without_unknown_fields() {
    assert_eq!(
        meta::inspect_request(&json!({"actor_id":" \u{001c}fictional/public-jobs\n"})).unwrap(),
        "fictional/public-jobs"
    );
    for value in [
        json!({"actor_id":"fictional/job","extra":true}),
        json!({"actor_id":"../private"}),
        json!({"actor_id":1}),
        json!({}),
    ] {
        assert!(meta::inspect_request(&value).is_err());
    }
    for value in [
        json!({}),
        json!({"data":[]}),
        json!({"data":{"title":1}}),
        json!({"data":{"pricingInfos":[1]}}),
        json!({"data":{"pricingInfos":null}}),
        json!({"data":{"title":"x".repeat(1001)}}),
    ] {
        assert!(meta::actor("fictional/job", &value, &json!({}), now()).is_err());
    }
    assert_eq!(
        meta::input_schema(&document(json!({"default":"x".repeat(65536)}))),
        Err(Failure("apify_actor_schema_limit"))
    );
    let items=meta::store(&json!({"data":{"items":[{"id":"fictional","title":"Job actor","pricingInfos":[],"private":"PRIVATE_STORE_CANARY"},7]}}),2).unwrap();
    assert_eq!(items.len(), 1);
    assert!(!json!(items).to_string().contains("PRIVATE_STORE_CANARY"));
    assert!(meta::store(&json!({"data":{"items":[]}}), 21).is_err());
    assert!(meta::store(&json!({"data":{"items":[{"id":1}]}}), 1).is_err());
    // Malformed OpenAPI structures are untrusted metadata, never a panic or network reference.
    for d in [
        json!({"paths":7}),
        json!({"paths":{"x":{"post":7}}}),
        json!({"paths":{"x":{"post":{"requestBody":7}}}}),
    ] {
        assert_eq!(meta::input_schema(&d).unwrap(), None);
    }
}
#[test]
fn account_projection_retains_only_documented_numbers_and_cycles_never_credit_authority() {
    let out = meta::account(&limits(), &usage(), now()).unwrap();
    assert!(!out.to_string().contains("CANARY"));
    assert_eq!(out["limits"]["current"]["monthlyUsageUsd"], 3);
    assert_eq!(out["usage"]["totalUsageCreditsUsdAfterVolumeDiscount"], 1.0);
    assert_eq!(out["execution_authorized"], false);
    assert_eq!(out["authenticated"], true);
    assert_eq!(out.as_object().unwrap().len(), 7);
    assert_eq!(out["usage"].as_object().unwrap().len(), 3);
    for n in 0..9 {
        let mut l = limits();
        let mut u = usage();
        match n {
            0 => l["data"]["limits"]["maxMonthlyUsageUsd"] = json!("10"),
            1 => l["data"]["current"]["monthlyUsageUsd"] = json!(-1),
            2 => l["data"]["monthlyUsageCycle"]["endAt"] = json!("invalid"),
            3 => u["data"]["usageCycle"]["endAt"] = json!("2026-12-02T00:00:00Z"),
            4 => u["data"]["usageCycle"]["endAt"] = json!("2026-10-01T00:00:00Z"),
            5 => u["data"]["totalUsageCreditsUsdAfterVolumeDiscount"] = json!(true),
            6 => {
                u["data"]
                    .as_object_mut()
                    .unwrap()
                    .remove("totalUsageCreditsUsdBeforeVolumeDiscount");
            }
            7 => l["data"]["limits"] = json!({}),
            8 => l = json!({"data":[]}),
            _ => unreachable!(),
        }
        assert!(meta::account(&l, &u, now()).is_err(), "case {n}");
    }
}
#[test]
fn fixture_origin_and_sensitive_local_credentials_are_explicit_and_bounded() {
    use meta::transport::Client;
    for endpoint in [
        "https://api.apify.com/v2/",
        "http://localhost:12345/v2/",
        "http://127.0.0.1:80/v2/",
        "http://127.0.0.1:12345/",
        "http://127.0.0.1:12345/v2/?token=secret",
        "http://user@127.0.0.1:12345/v2/",
    ] {
        let values =
            BTreeMap::from([("RUST_APIFY_METADATA_FIXTURE_ORIGIN".into(), endpoint.into())]);
        assert!(Client::from_values(&values, true).is_err());
        assert!(Client::from_values(&values, false).is_err());
    }
    assert!(
        !Client::from_values(&BTreeMap::new(), false)
            .unwrap()
            .token_configured()
    );
    assert!(
        Client::from_values(
            &BTreeMap::from([("APIFY_API_TOKEN".into(), "bad\nkey".into())]),
            false
        )
        .is_err()
    );
}
struct Fixture {
    mode: &'static str,
    calls: AtomicUsize,
}
async fn respond(
    axum::extract::State(f): axum::extract::State<Arc<Fixture>>,
    r: axum::extract::Request,
) -> axum::response::Response {
    use axum::response::IntoResponse;
    f.calls.fetch_add(1, Ordering::SeqCst);
    assert_eq!(r.method(), "GET");
    let path = r.uri().path();
    assert!(path.starts_with("/v2/"));
    if path.contains("users/me/") {
        assert_eq!(
            r.headers()["authorization"],
            "Bearer PRIVATE_FICTIONAL_APIFY_TOKEN"
        );
        assert!(r.uri().query().is_none());
    } else {
        assert!(!r.headers().contains_key("authorization"));
    }
    match f.mode {
        "auth"=>(axum::http::StatusCode::UNAUTHORIZED,axum::Json(json!({"error":"PRIVATE_ERROR_CANARY"}))).into_response(),
        "rate"=>(axum::http::StatusCode::TOO_MANY_REQUESTS,axum::Json(json!({"error":"PRIVATE_ERROR_CANARY"}))).into_response(),
        "redirect"=>(axum::http::StatusCode::FOUND,[("location","/not-permitted")],"PRIVATE_REDIRECT_CANARY").into_response(),
        "oversized"=>([("content-type","application/json")],"x".repeat(1048577)).into_response(),
        "invalid"=>([("content-type","application/json")],"PRIVATE_INVALID_JSON_CANARY").into_response(),
        "html"=>"PRIVATE_HTML_CANARY".into_response(),
        _=>axum::Json(match path {
            "/v2/users/me/limits"=>limits(),"/v2/users/me/usage/monthly"=>usage(),
            "/v2/actors/fictional~public-jobs"=>json!({"data":{"title":"Fictional actor","pricingInfos":[],"private":"PRIVATE_ACTOR_CANARY"}}),
            "/v2/actors/fictional~public-jobs/builds/default/openapi.json"=>document(json!({"type":"object"})),
            "/v2/store"=>{let query=r.uri().query().unwrap();assert!(query.contains("limit=2"));assert!(query.contains("search="));assert!(!query.contains("token"));json!({"data":{"items":[{"id":"fictional"}]}})},
            _=>panic!("unexpected metadata request"),
        }).into_response(),
    }
}
async fn fixture(
    mode: &'static str,
) -> (
    meta::transport::Client,
    Arc<Fixture>,
    tokio::task::JoinHandle<()>,
) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let state = Arc::new(Fixture {
        mode,
        calls: AtomicUsize::new(0),
    });
    let router = axum::Router::new()
        .fallback(respond)
        .with_state(state.clone());
    let task = tokio::spawn(async move {
        axum::serve(listener, router).await.unwrap();
    });
    let values = BTreeMap::from([
        (
            "RUST_APIFY_METADATA_FIXTURE_ORIGIN".into(),
            format!("http://{addr}/v2/"),
        ),
        (
            "APIFY_API_TOKEN".into(),
            "PRIVATE_FICTIONAL_APIFY_TOKEN".into(),
        ),
    ]);
    (
        meta::transport::Client::from_values(&values, true).unwrap(),
        state,
        task,
    )
}
#[tokio::test]
async fn fixed_get_routes_separate_public_metadata_and_authenticated_account_headers() {
    let (c, f, task) = fixture("ok").await;
    let actor = c.actor("fictional/public-jobs").await.unwrap();
    assert_eq!(actor["collection_status"], "disabled_pending_review");
    assert!(!actor.to_string().contains("PRIVATE_ACTOR_CANARY"));
    let account = c.account().await.unwrap();
    assert_eq!(account["execution_authorized"], false);
    assert!(!account.to_string().contains("CANARY"));
    assert_eq!(c.discover("fictional jobs", 2).await.unwrap().len(), 1);
    assert_eq!(f.calls.load(Ordering::SeqCst), 5);
    assert!(c.actor("../private").await.is_err());
    assert!(c.discover("", 2).await.is_err());
    assert!(c.discover("x", 21).await.is_err());
    assert_eq!(f.calls.load(Ordering::SeqCst), 5);
    task.abort();
}
#[tokio::test]
async fn metadata_status_failures_are_fixed_sanitized_and_never_retried_or_redirected() {
    for (mode, code) in [
        ("auth", "apify_metadata_authentication_required"),
        ("rate", "apify_metadata_rate_limited"),
        ("redirect", "apify_metadata_http_unavailable"),
        ("oversized", "apify_metadata_response_limit"),
        ("invalid", "apify_metadata_json_invalid"),
        ("html", "apify_metadata_json_required"),
    ] {
        let (c, f, task) = fixture(mode).await;
        assert_eq!(c.account().await, Err(Failure(code)));
        assert_eq!(f.calls.load(Ordering::SeqCst), 1);
        task.abort();
    }
}
#[tokio::test]
async fn missing_credential_refuses_account_before_any_network() {
    let c = meta::transport::Client::from_values(&BTreeMap::new(), false).unwrap();
    assert_eq!(
        c.account().await,
        Err(Failure("apify_local_token_not_configured"))
    );
}
#[test]
fn actor_inspect_matches_actual_strip_contract_then_safe_actor_without_settings_imports() {
    let values = json!([{"actor_id":"fictional/jobs"},{"actor_id":" fictional/jobs "},{"actor_id":"\u{001c}fictional/jobs\u{001f}"},{"actor_id":"../private"},{"actor_id":4},{"actor_id":""},{"actor_id":"fictional/jobs","extra":true},null]);
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let script = r#"import json,re,runpy,sys
from enum import StrEnum
m=runpy.run_path('rust/scripts/export_apify_contracts.py');Actor=m['metadata_models']()['actor-inspect'];s={'re':re,'StrEnum':StrEnum}
m['load'](s,'backend/app/schemas/discovery.py',{'DiscoveryStatus','DiscoveryError'})
m['load'](s,'backend/app/services/providers/apify.py',{'ACTOR_ID','safe_actor'})
out=[]
for v in json.load(sys.stdin):
 try:
  a=Actor.model_validate(v).actor_id;s['safe_actor'](a);out.append(a)
 except (ValueError,TypeError):out.append(None)
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
        .write_all(values.to_string().as_bytes())
        .unwrap();
    let output = p.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let expected: Vec<Value> = serde_json::from_slice(&output.stdout).unwrap();
    for (value, expected) in values.as_array().unwrap().iter().zip(expected) {
        assert_eq!(
            meta::inspect_request(value)
                .map(|s| json!(s))
                .unwrap_or(Value::Null),
            expected
        );
    }
}
#[tokio::test]
async fn incomplete_response_retains_fixed_transport_failure_without_retry_or_raw_body() {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let task = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut request = vec![0u8; 16384];
        let n = stream.read(&mut request).await.unwrap();
        assert!(String::from_utf8_lossy(&request[..n]).starts_with("GET /v2/users/me/limits "));
        stream.write_all(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 200\r\nConnection: close\r\n\r\n{\"private\":\"PRIVATE_TRUNCATED_CANARY\"").await.unwrap();
        stream.shutdown().await.unwrap();
    });
    let c = meta::transport::Client::from_values(
        &BTreeMap::from([
            (
                "RUST_APIFY_METADATA_FIXTURE_ORIGIN".into(),
                format!("http://{addr}/v2/"),
            ),
            (
                "APIFY_API_TOKEN".into(),
                "PRIVATE_FICTIONAL_APIFY_TOKEN".into(),
            ),
        ]),
        true,
    )
    .unwrap();
    assert_eq!(
        c.account().await,
        Err(Failure("apify_metadata_transport_error"))
    );
    task.await.unwrap();
}
