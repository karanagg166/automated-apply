//! Deferred loopback transport fixtures. Fixture grants do not establish database admission.
use super::*;
use axum::{
    Json, Router,
    body::{Body, to_bytes},
    extract::State,
    http::{Request, StatusCode},
    response::{IntoResponse, Response},
};
use std::sync::{
    Arc,
    atomic::{AtomicUsize, Ordering},
};
use tokio::sync::Mutex;
struct Fixture {
    mode: &'static str,
    calls: AtomicUsize,
    seen: Mutex<Vec<Value>>,
}
fn apollo_person() -> Value {
    json!({"name":"Fictional Person","title":"CTO","organization":{"primary_domain":"example.com"},"linkedin_url":"https://www.linkedin.com/in/fictional-person","email":"person@example.com","id":"fixture-person","email_status":"verified","private":"PRIVATE_VENDOR_CANARY"})
}
fn signal_person() -> Value {
    json!({"fullName":"Fictional Person","experience":[{"current":true,"website":"https://example.com","position":"CTO"}],"social":[{"type":"li","link":"https://www.linkedin.com/in/fictional-person"}],"contacts":[{"type":"email","subType":"work","value":"person@example.com","rating":90}],"uid":"11111111111111111111111111111111"})
}
async fn handler(State(state): State<Arc<Fixture>>, request: Request<Body>) -> Response {
    state.calls.fetch_add(1, Ordering::SeqCst);
    let path = request.uri().path().to_owned();
    let method = request.method().to_string();
    let auth =
        request.headers().contains_key("x-api-key") || request.headers().contains_key("apikey");
    let bytes = to_bytes(request.into_body(), 65536).await.unwrap();
    let body = serde_json::from_slice::<Value>(&bytes).unwrap_or(Value::Null);
    state
        .seen
        .lock()
        .await
        .push(json!({"path":path,"method":method,"authentication_present":auth,"body":body}));
    match state.mode {
        "redirect" => {
            return (
                StatusCode::TEMPORARY_REDIRECT,
                [("location", "/redirect-target")],
            )
                .into_response();
        }
        "rate" => return (StatusCode::TOO_MANY_REQUESTS, [("retry-after", "120")]).into_response(),
        "error" => return StatusCode::INTERNAL_SERVER_ERROR.into_response(),
        "malformed" => return "not JSON".into_response(),
        "oversized" => return "x".repeat(1048577).into_response(),
        "slow" => tokio::time::sleep(Duration::from_millis(1200)).await,
        "async" if path == "/candidate/search" => {
            return (StatusCode::CREATED, Json(json!({"requestId":1748}))).into_response();
        }
        "pending" if path == "/candidate/search" => return StatusCode::NO_CONTENT.into_response(),
        _ => {}
    }
    let rates = json!({"minute":{"limit":10,"consumed":0,"left_over":10},"hour":{"limit":100,"consumed":0,"left_over":100},"day":{"limit":1000,"consumed":0,"left_over":1000}});
    Json(match path.as_str(){
        "/auth/health"=>json!({"healthy":state.mode!="unhealthy","is_logged_in":state.mode!="unhealthy"}),
        "/usage_stats/api_usage_stats"=>json!({"api/v1/people/match":rates,"api/v1/mixed_people/api_search":rates}),
        "/usage_stats/credit_usage_stats"=>json!({"credit_usage_stats":{"lead_credit":{"limit":100,"consumed":0,"left_over":100}}}),
        "/credits"=>json!({"credits":100}),
        "/people/match"=>json!({"person":apollo_person()}),
        "/mixed_people/api_search"=>json!({"people":[apollo_person(),apollo_person()]}),
        "/candidate/search"=>json!([{"item":if state.mode=="wrong_item"{"https://www.linkedin.com/in/other-person/"}else{"https://www.linkedin.com/in/fictional-person/"},"status":"success","candidate":signal_person()}]),
        _=>Value::Null
    }).into_response()
}
async fn fixture(mode: &'static str) -> (String, Arc<Fixture>, tokio::task::JoinHandle<()>) {
    let state = Arc::new(Fixture {
        mode,
        calls: AtomicUsize::new(0),
        seen: Mutex::new(Vec::new()),
    });
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let router = Router::new().fallback(handler).with_state(state.clone());
    let task = tokio::spawn(async move {
        axum::serve(listener, router).await.unwrap();
    });
    (format!("http://{address}/"), state, task)
}
fn request() -> Value {
    json!({"company_id":"11111111-1111-4111-8111-111111111111","company_domain":"example.com","full_name":"Fictional Person","linkedin_url":"https://www.linkedin.com/in/fictional-person/","target_roles":["cto"],"max_people":2,"allow_paid":true})
}
fn eligibility_at(at: DateTime<Utc>) -> capabilities::Eligibility {
    capabilities::Eligibility::from_values(&BTreeMap::from([
        ("APOLLO_API_KEY".into(), "fictional-provider-key".into()),
        ("APOLLO_FREE_ACCOUNT_CONFIRMED".into(), "true".into()),
        ("APOLLO_WORK_EMAIL_CONFIRMED".into(), "true".into()),
        ("APOLLO_ELIGIBILITY_REVIEWED_AT".into(), at.to_rfc3339()),
        (
            "APOLLO_ELIGIBILITY_EVIDENCE_URL".into(),
            "https://contact-fixture.example/review".into(),
        ),
        (
            "APOLLO_REVIEWED_ENDPOINTS".into(),
            json!(["api/v1/people/match", "api/v1/mixed_people/api_search"]).to_string(),
        ),
        ("APOLLO_CREDIT_POOL".into(), "lead_credit".into()),
    ]))
    .unwrap()
}
fn eligibility() -> capabilities::Eligibility {
    eligibility_at(Utc::now())
}
fn client(name: Name, endpoint: &str) -> Client {
    Client::new(
        name,
        "fictional-provider-key",
        Duration::from_secs(1),
        true,
        Some(endpoint),
    )
    .unwrap()
}
fn grant(name: Name, operation: capabilities::Operation) -> super::super::dispatch::Grant {
    super::super::dispatch::fixture_grant(
        name.name(),
        "fictional-provider-key",
        operation,
        request(),
    )
}
#[tokio::test(flavor = "current_thread")]
async fn fixed_apollo_metadata_proof_has_three_documented_calls_and_no_lookup_permission() {
    let (endpoint, state, task) = fixture("normal").await;
    let client = client(Name::Apollo, &endpoint);
    let proof = client
        .introspect(capabilities::Operation::Enrich, 2, &eligibility())
        .await
        .unwrap();
    assert_eq!(state.calls.load(Ordering::SeqCst), 3);
    let finding = proof.finding();
    assert_eq!(finding["provider_requests_performed"], 3);
    assert_eq!(finding["lookup_authorized"], false);
    assert_eq!(finding["credits"]["remaining"], 100);
    proof
        .check(&client, capabilities::Operation::Enrich, 2, Utc::now())
        .unwrap();
    let seen = state.seen.lock().await;
    assert_eq!(seen[0]["path"], "/auth/health");
    assert_eq!(
        seen[1]["body"],
        json!({"endpoints":["api/v1/people/match"]})
    );
    assert!(seen.iter().all(|r| r["authentication_present"] == true));
    assert!(!finding.to_string().contains("fictional-provider-key"));
    task.abort();
}
#[tokio::test(flavor = "current_thread")]
async fn fixed_metadata_unhealthy_account_stops_before_stats_or_credits() {
    let (endpoint, state, task) = fixture("unhealthy").await;
    let error = client(Name::Apollo, &endpoint)
        .introspect(capabilities::Operation::Enrich, 2, &eligibility())
        .await
        .err()
        .unwrap();
    assert_eq!(error.state, "authorization_required");
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    task.abort();
}
#[tokio::test(flavor = "current_thread")]
async fn fixed_apollo_match_disables_personal_phone_and_waterfall_fields_and_keeps_email_unverified()
 {
    let (endpoint, state, task) = fixture("normal").await;
    let result = client(Name::Apollo, &endpoint)
        .execute(grant(Name::Apollo, capabilities::Operation::Enrich))
        .await;
    assert_eq!(result.state, "completed");
    assert_eq!(result.observations[0]["email_status"], "provider_reported");
    assert!(
        !json!(result.observations)
            .to_string()
            .contains("PRIVATE_VENDOR_CANARY")
    );
    let seen = state.seen.lock().await;
    assert_eq!(seen.len(), 1);
    assert_eq!(seen[0]["path"], "/people/match");
    for field in [
        "reveal_personal_emails",
        "reveal_phone_number",
        "run_waterfall_email",
        "run_waterfall_phone",
    ] {
        assert_eq!(seen[0]["body"][field], false);
    }
    assert!(seen[0]["body"].get("webhook_url").is_none());
    task.abort();
}
#[tokio::test(flavor = "current_thread")]
async fn fixed_apollo_search_is_bounded_and_duplicate_observations_do_not_create_duplicate_people()
{
    let (endpoint, state, task) = fixture("normal").await;
    let result = client(Name::Apollo, &endpoint)
        .execute(grant(Name::Apollo, capabilities::Operation::Search))
        .await;
    assert_eq!(result.state, "completed");
    assert_eq!(result.observations.len(), 1);
    assert_eq!(result.credits_used, Some(0));
    let seen = state.seen.lock().await;
    assert_eq!(seen[0]["body"]["per_page"], 2);
    assert_eq!(
        seen[0]["body"]["q_organization_domains_list"],
        json!(["example.com"])
    );
    task.abort();
}
#[tokio::test(flavor = "current_thread")]
async fn fixed_signalhire_uses_one_identifier_without_callback_or_waterfall_and_preserves_async_unknowns()
 {
    for (mode, expected) in [
        ("normal", "completed"),
        ("async", "queued"),
        ("pending", "running"),
        ("wrong_item", "billing_uncertain"),
    ] {
        let (endpoint, state, task) = fixture(mode).await;
        let result = client(Name::SignalHire, &endpoint)
            .execute(grant(Name::SignalHire, capabilities::Operation::Enrich))
            .await;
        assert_eq!(result.state, expected);
        assert_eq!(state.calls.load(Ordering::SeqCst), 1);
        let seen = state.seen.lock().await;
        assert_eq!(
            seen[0]["body"],
            json!({"items":["https://www.linkedin.com/in/fictional-person/"],"withoutWaterfall":true})
        );
        if mode == "async" {
            assert_eq!(result.provider_run_id.as_deref(), Some("1748"));
            assert!(result.outcome_unknown);
        }
        task.abort();
    }
}
#[tokio::test(flavor = "current_thread")]
async fn fixed_provider_redirect_server_error_malformed_and_oversized_post_results_never_retry() {
    for mode in ["redirect", "error", "malformed", "oversized"] {
        let (endpoint, state, task) = fixture(mode).await;
        let result = client(Name::Apollo, &endpoint)
            .execute(grant(Name::Apollo, capabilities::Operation::Enrich))
            .await;
        assert_eq!(result.state, "billing_uncertain", "{mode}");
        assert!(result.outcome_unknown);
        assert_eq!(state.calls.load(Ordering::SeqCst), 1);
        task.abort();
    }
}
#[tokio::test(flavor = "current_thread")]
async fn fixed_provider_rate_limit_retains_retry_after_and_timeout_never_repeats_post() {
    let (endpoint, state, task) = fixture("rate").await;
    let result = client(Name::Apollo, &endpoint)
        .execute(grant(Name::Apollo, capabilities::Operation::Enrich))
        .await;
    assert_eq!(result.state, "rate_limited");
    assert_eq!(result.retry_after_seconds, Some(120));
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    task.abort();
    let (endpoint, state, task) = fixture("slow").await;
    let result = client(Name::Apollo, &endpoint)
        .execute(grant(Name::Apollo, capabilities::Operation::Enrich))
        .await;
    assert_eq!(result.state, "billing_uncertain");
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    task.abort();
}
#[tokio::test(flavor = "current_thread")]
async fn fixed_signalhire_credit_probe_and_unsupported_search_do_not_create_lookup_requests() {
    let (endpoint, state, task) = fixture("normal").await;
    let client = client(Name::SignalHire, &endpoint);
    let proof = client
        .introspect(capabilities::Operation::Enrich, 1, &eligibility())
        .await
        .unwrap();
    assert_eq!(proof.finding()["credits_remaining"], 100);
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    let error = client
        .introspect(capabilities::Operation::Search, 0, &eligibility())
        .await
        .err()
        .unwrap();
    assert_eq!(error.state, "unsupported_operation");
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    task.abort();
}
#[tokio::test(flavor = "current_thread")]
async fn fixed_proof_cannot_change_key_operation_cost_or_time_and_wrong_grant_key_sends_nothing() {
    let (endpoint, state, task) = fixture("normal").await;
    let client = client(Name::Apollo, &endpoint);
    let proof = client
        .introspect(capabilities::Operation::Enrich, 2, &eligibility())
        .await
        .unwrap();
    let other = Client::new(
        Name::Apollo,
        "different-fictional-key",
        Duration::from_secs(1),
        true,
        Some(&endpoint),
    )
    .unwrap();
    assert!(
        proof
            .check(&other, capabilities::Operation::Enrich, 2, Utc::now())
            .is_err()
    );
    assert!(
        proof
            .check(&client, capabilities::Operation::Search, 2, Utc::now())
            .is_err()
    );
    assert!(
        proof
            .check(&client, capabilities::Operation::Enrich, 3, Utc::now())
            .is_err()
    );
    assert!(
        proof
            .check(
                &client,
                capabilities::Operation::Enrich,
                2,
                Utc::now() + chrono::Duration::seconds(61)
            )
            .is_err()
    );
    let near =
        eligibility_at(Utc::now() - chrono::Duration::hours(24) + chrono::Duration::seconds(30));
    let expiring = client
        .introspect(capabilities::Operation::Enrich, 2, &near)
        .await
        .unwrap();
    assert!(
        expiring
            .check(
                &client,
                capabilities::Operation::Enrich,
                2,
                Utc::now() + chrono::Duration::seconds(31)
            )
            .is_err()
    );
    let result = other
        .execute(grant(Name::Apollo, capabilities::Operation::Enrich))
        .await;
    assert_eq!(
        result.error_code,
        Some("contact_provider_dispatch_context_changed")
    );
    assert_eq!(state.calls.load(Ordering::SeqCst), 6);
    task.abort();
}
#[test]
fn fixed_provider_fixture_boundaries_and_secret_headers_cannot_select_arbitrary_origins() {
    for url in [
        "https://other.example/",
        "http://localhost:8080/",
        "http://127.0.0.2:8080/",
        "http://127.0.0.1:80/",
        "http://127.0.0.1:8080/path",
        "http://127.0.0.1:8080/?key=secret",
        "http://user:secret@127.0.0.1:8080/",
    ] {
        assert!(
            Client::new(
                Name::Apollo,
                "fictional-key",
                Duration::from_secs(1),
                true,
                Some(url)
            )
            .is_err()
        );
    }
    assert!(
        Client::new(
            Name::Apollo,
            "bad\nkey",
            Duration::from_secs(1),
            true,
            Some("http://127.0.0.1:8080/")
        )
        .is_err()
    );
    assert!(
        Client::new(
            Name::Apollo,
            "fictional-key",
            Duration::from_secs(1),
            false,
            Some("http://127.0.0.1:8080/")
        )
        .is_err()
    );
    assert!(
        Client::new(
            Name::Apollo,
            "fictional-key",
            Duration::from_secs(1),
            true,
            None
        )
        .is_err()
    );
}
