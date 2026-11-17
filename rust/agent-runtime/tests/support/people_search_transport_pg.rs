//! Deferred actual loopback-only HTTP through original admission and retained findings.
use automated_apply_agents::people_research::{
    controller::Service as PeopleSearchService, transport::Client as PeopleSearchClient,
};
struct PeopleSearchHttpFixture {
    mode: &'static str,
    calls: AtomicUsize,
    entered: tokio::sync::Notify,
    release: tokio::sync::Notify,
}
async fn people_search_response(
    axum::extract::State(state): axum::extract::State<Arc<PeopleSearchHttpFixture>>,
    request: axum::extract::Request,
) -> axum::response::Response {
    use axum::response::IntoResponse as _;
    state.calls.fetch_add(1, Ordering::SeqCst);
    assert_eq!(request.method(), "POST");
    assert_eq!(request.uri().path(), "/search");
    assert!(request.uri().query().is_none());
    assert_eq!(
        request.headers()["x-api-key"],
        "PRIVATE_FICTIONAL_SEARCH_KEY_CANARY"
    );
    let bytes = axum::body::to_bytes(request.into_body(), 16384)
        .await
        .unwrap();
    let input: Value = serde_json::from_slice(&bytes).unwrap();
    assert!(
        input["q"]
            .as_str()
            .unwrap()
            .contains("Fictional Contact Employer")
    );
    assert!(input["num"].as_u64().is_some_and(|n| n <= 20));
    assert_eq!(input.as_object().unwrap().len(), 2);
    state.entered.notify_one();
    if state.mode == "hold" {
        state.release.notified().await;
    }
    match state.mode {
        "rate"=>(axum::http::StatusCode::TOO_MANY_REQUESTS,[("retry-after","120")],axum::Json(json!({"private":"PRIVATE_PROVIDER_ERROR_CANARY"}))).into_response(),
        "auth401"=>(axum::http::StatusCode::UNAUTHORIZED,axum::Json(json!({"private":"PRIVATE_PROVIDER_ERROR_CANARY"}))).into_response(),
        "auth403"=>(axum::http::StatusCode::FORBIDDEN,axum::Json(json!({"private":"PRIVATE_PROVIDER_ERROR_CANARY"}))).into_response(),
        "redirect"=>(axum::http::StatusCode::FOUND,[("location","/unpermitted-result-page")],"PRIVATE_REDIRECT_BODY_CANARY").into_response(),
        "invalid"=>(axum::http::StatusCode::OK,"PRIVATE_INVALID_JSON_CANARY").into_response(),
        "missing"=>axum::Json(json!({"unexpected_private":"PRIVATE_SCHEMA_CANARY"})).into_response(),
        "oversized"=>(axum::http::StatusCode::OK,"x".repeat(1048577)).into_response(),
        "public"=>axum::Json(json!({"organic":[{"title":"Fictional Search Professional | CTO at Fictional Contact Employer","link":"https://linkedin.com/in/fictional-search-professional","snippet":"PRIVATE_PROVIDER_SNIPPET_CANARY"}]})).into_response(),
        _=>axum::Json(json!({"organic":[{"title":"Fictional Search Professional | CTO at Fictional Contact Employer","link":"https://contact-fixture.example/team","snippet":"PRIVATE_PROVIDER_SNIPPET_CANARY"}]})).into_response(),
    }
}
async fn people_search_http(
    mode: &'static str,
) -> (
    BTreeMap<String, String>,
    Arc<PeopleSearchHttpFixture>,
    CancellationToken,
    tokio::task::JoinHandle<()>,
) {
    let state = Arc::new(PeopleSearchHttpFixture {
        mode,
        calls: AtomicUsize::new(0),
        entered: tokio::sync::Notify::new(),
        release: tokio::sync::Notify::new(),
    });
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let stop = CancellationToken::new();
    let shutdown = stop.clone();
    let router = axum::Router::new()
        .fallback(people_search_response)
        .with_state(state.clone());
    let task = tokio::spawn(async move {
        axum::serve(listener, router)
            .with_graceful_shutdown(shutdown.cancelled_owned())
            .await
            .unwrap();
    });
    let mut values = people_search_values();
    values.insert(
        "RUST_PEOPLE_SEARCH_FIXTURE_ENDPOINT".into(),
        format!("http://{addr}/search"),
    );
    (values, state, stop, task)
}
async fn people_search_with(
    c: &mut PgConnection,
    input: Value,
    id: u128,
    values: &BTreeMap<String, String>,
) -> Result<Value> {
    let settings = PeopleSearchSettings::from_values(values).unwrap();
    let client = PeopleSearchClient::from_values(values, true).unwrap();
    let contacts = contact_settings();
    PeopleSearchService {
        settings: &settings,
        client: client.as_ref(),
        contacts: &contacts,
    }
    .acquire(c, input, Uuid::from_u128(id))
    .await
}
fn people_search_no_private(result: &Value) {
    for private in [
        "PRIVATE_FICTIONAL_SEARCH_KEY_CANARY",
        "PRIVATE_PROVIDER_SNIPPET_CANARY",
        "PRIVATE_PROVIDER_ERROR_CANARY",
        "PRIVATE_REDIRECT_BODY_CANARY",
        "PRIVATE_INVALID_JSON_CANARY",
        "PRIVATE_SCHEMA_CANARY",
        "https://contact-fixture.example/permission",
    ] {
        assert!(!result.to_string().contains(private));
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_official_transport_commits_selected_finding_before_any_contact_import_and_never_reposts()
 {
    let mut c = people_search_fixture().await;
    let data_before = people_ingest_snapshot(&mut c).await;
    let (values, state, stop, task) = people_search_http("official").await;
    let first = people_search_with(&mut c, people_search_input(), 30001, &values)
        .await
        .unwrap();
    assert_eq!(first["status"], "finding_retained");
    assert_eq!(first["provider_status"], "success");
    assert_eq!(first["persistence_status"], "not_imported");
    assert_eq!(first["people"][0]["human_confirmed"], false);
    assert_eq!(first["people"][0]["verification_status"], "requires_review");
    assert_eq!(first["provider_request_attempted"], true);
    assert_eq!(first["provider_response_retained"], true);
    people_search_no_private(&first);
    assert_eq!(people_ingest_snapshot(&mut c).await, data_before);
    let before = people_search_snapshot(&mut c).await;
    assert_eq!(
        people_search_with(&mut c, people_search_input(), 30001, &values)
            .await
            .unwrap(),
        first
    );
    assert_eq!(
        people_search_runs::retained(&mut c, Uuid::from_u128(30001))
            .await
            .unwrap(),
        first
    );
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    assert_eq!(people_search_snapshot(&mut c).await, before);
    let reservation: Value = sqlx::query_scalar(
        "SELECT to_jsonb(r) FROM discovery_budget_reservations r WHERE provider='serper'",
    )
    .fetch_one(&mut c)
    .await
    .unwrap();
    assert_eq!(reservation["state"], "completed");
    assert!(reservation["reported_actual"].is_null());
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_public_profile_results_remain_candidates_without_identity_mailbox_or_result_page_fetch()
 {
    let mut c = people_search_fixture().await;
    let (mut values, state, stop, task) = people_search_http("public").await;
    values.insert("LINKEDIN_SEARCH_RETENTION_AUTHORIZED".into(), "true".into());
    let mut input = people_search_input();
    input["research_mode"] = json!("public_profiles");
    let result = people_search_with(&mut c, input, 30002, &values)
        .await
        .unwrap();
    assert_eq!(result["people"][0]["source"], "public_search");
    assert_eq!(
        result["people"][0]["verification_status"],
        "source_reported"
    );
    assert!(result["people"][0].get("email").is_none());
    assert_eq!(result["outbound_messages_sent"], 0);
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    people_search_no_private(&result);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_rate_response_retains_local_allowance_and_monotonic_cooldown_without_another_post()
 {
    let mut c = people_search_fixture().await;
    let (values, state, stop, task) = people_search_http("rate").await;
    let result = people_search_with(&mut c, people_search_input(), 30003, &values)
        .await
        .unwrap();
    assert_eq!(result["status"], "rate_limited");
    assert_eq!(result["retry_after_seconds"], 120);
    people_search_no_private(&result);
    let cooling:bool=sqlx::query_scalar("SELECT cooldown_until>clock_timestamp()+interval '110 seconds' AND reserved=1 FROM discovery_monthly_budgets WHERE provider='serper'").fetch_one(&mut c).await.unwrap();
    assert!(cooling);
    assert_eq!(
        people_search_with(&mut c, people_search_input(), 30003, &values)
            .await
            .unwrap(),
        result
    );
    assert_eq!(
        people_search_with(&mut c, people_search_input(), 30004, &values)
            .await
            .unwrap_err(),
        Failure("contact_provider_cooling_down")
    );
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_auth_redirect_invalid_and_oversized_responses_are_qualified_without_diagnostics_or_retries()
 {
    let mut c = people_search_fixture().await;
    for (n, mode, status) in [
        (0, "auth401", "authentication_required"),
        (1, "auth403", "authentication_required"),
        (2, "redirect", "upstream_error"),
        (3, "invalid", "outcome_unknown"),
        (4, "missing", "outcome_unknown"),
        (5, "oversized", "outcome_unknown"),
    ] {
        let (values, state, stop, task) = people_search_http(mode).await;
        let result = people_search_with(&mut c, people_search_input(), 30100 + n, &values)
            .await
            .unwrap();
        assert_eq!(result["status"], status);
        assert_eq!(result["people"], json!([]));
        assert_eq!(result["provider_charge_verified"], false);
        assert_eq!(state.calls.load(Ordering::SeqCst), 1);
        people_search_no_private(&result);
        assert_eq!(
            people_search_with(&mut c, people_search_input(), 30100 + n, &values)
                .await
                .unwrap(),
            result
        );
        assert_eq!(state.calls.load(Ordering::SeqCst), 1);
        stop.cancel();
        task.await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_network_response_loss_retains_unknown_cost_and_cannot_repeat_the_original_post()
 {
    use tokio::io::AsyncReadExt as _;
    let mut c = people_search_fixture().await;
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let calls = Arc::new(AtomicUsize::new(0));
    let count = calls.clone();
    let task = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut bytes = [0_u8; 16384];
        let read = stream.read(&mut bytes).await.unwrap();
        assert!(read > 0);
        count.fetch_add(1, Ordering::SeqCst);
        drop(stream);
    });
    let mut values = people_search_values();
    values.insert(
        "RUST_PEOPLE_SEARCH_FIXTURE_ENDPOINT".into(),
        format!("http://{addr}/search"),
    );
    let result = people_search_with(&mut c, people_search_input(), 30005, &values)
        .await
        .unwrap();
    task.await.unwrap();
    assert_eq!(result["status"], "outcome_unknown");
    assert_eq!(result["provider_request_attempted"], true);
    assert_eq!(result["provider_response_retained"], false);
    assert_eq!(result["reserved_local_requests"], 1);
    assert_eq!(
        people_search_with(&mut c, people_search_input(), 30005, &values)
            .await
            .unwrap(),
        result
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_remote_wait_holds_no_owner_fence_and_retains_findings_despite_current_company_changes()
 {
    let mut c = people_search_fixture().await;
    let (values, state, stop, task) = people_search_http("hold").await;
    let run_values = values.clone();
    let pending = tokio::spawn(async move {
        people_search_with(&mut c, people_search_input(), 30006, &run_values).await
    });
    state.entered.notified().await;
    let mut other = connection().await;
    let mut tx = other.begin().await.unwrap();
    tokio::time::timeout(
        Duration::from_secs(1),
        sqlx::query(
            "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
        )
        .fetch_one(&mut *tx),
    )
    .await
    .unwrap()
    .unwrap();
    tx.rollback().await.unwrap();
    sqlx::query("UPDATE companies SET metadata=metadata||'{\"changed_while_searching\":true}'::jsonb WHERE domain='contact-fixture.example'").execute(&mut other).await.unwrap();
    state.release.notify_one();
    let result = pending.await.unwrap().unwrap();
    assert_eq!(result["status"], "finding_retained");
    assert_eq!(result["persistence_status"], "not_imported");
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_cancellation_after_post_admission_never_creates_a_second_transport_grant() {
    let mut c = people_search_fixture().await;
    let (values, state, stop, task) = people_search_http("hold").await;
    let run_values = values.clone();
    let pending = tokio::spawn(async move {
        let mut connection = connection().await;
        people_search_with(&mut connection, people_search_input(), 30007, &run_values).await
    });
    state.entered.notified().await;
    pending.abort();
    let _ = pending.await;
    let before = people_search_snapshot(&mut c).await;
    let result = people_search_with(&mut c, people_search_input(), 30007, &values)
        .await
        .unwrap();
    assert_eq!(result["recorded_state"], "dispatch_admitted");
    assert_eq!(result["replay_authorized"], false);
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    assert_eq!(people_search_snapshot(&mut c).await, before);
    state.release.notify_one();
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_finding_and_terminal_ack_failures_leave_original_intent_without_network_replay()
 {
    let mut c = people_search_fixture().await;
    let (values, state, stop, task) = people_search_http("official").await;
    for (n, body, error) in [
        (
            0,
            "IF NEW.value->>'state'='finding_retained' AND starts_with(NEW.key,'people_search:') THEN RETURN NULL;END IF;RETURN NEW;",
            "public_research_write_ack_failed",
        ),
        (
            1,
            "IF NEW.value->>'state'='finding_retained' AND starts_with(NEW.key,'people_search:') THEN UPDATE discovery_budget_reservations SET created_at=created_at+interval '1 hour';END IF;RETURN NEW;",
            "invalid_contact_budget",
        ),
    ] {
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("CREATE FUNCTION fixture_search_finding_corrupt() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {body} END $$;CREATE TRIGGER fixture_search_finding_corrupt BEFORE UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_search_finding_corrupt()"))).execute(&mut c).await.unwrap();
        assert_eq!(
            people_search_with(&mut c, people_search_input(), 30200 + n, &values)
                .await
                .unwrap_err(),
            Failure(error)
        );
        let count = state.calls.load(Ordering::SeqCst);
        let result = people_search_with(&mut c, people_search_input(), 30200 + n, &values)
            .await
            .unwrap();
        assert_eq!(result["recorded_state"], "dispatch_admitted");
        assert_eq!(state.calls.load(Ordering::SeqCst), count);
        sqlx::raw_sql("DROP TRIGGER fixture_search_finding_corrupt ON owner_preferences;DROP FUNCTION fixture_search_finding_corrupt()").execute(&mut c).await.unwrap();
    }
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_retained_findings_exclude_unknown_private_root_fields_and_permission_provenance()
 {
    let mut c = people_search_fixture().await;
    let (values, _, stop, task) = people_search_http("official").await;
    people_search_with(&mut c, people_search_input(), 30008, &values)
        .await
        .unwrap();
    let key = format!("people_search:{}", Uuid::from_u128(30008).simple());
    let mut journal: Value = sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(&key)
        .fetch_one(&mut c)
        .await
        .unwrap();
    journal["finding"]["private_vendor"] = json!("PRIVATE_RETAINED_ROOT_CANARY");
    journal["finding_hash"] =
        json!(automated_apply_agents::startup_catalog::identity::content_hash(&journal["finding"]));
    sqlx::query("UPDATE owner_preferences SET value=$1 WHERE key=$2")
        .bind(&journal)
        .bind(&key)
        .execute(&mut c)
        .await
        .unwrap();
    let before = people_search_snapshot(&mut c).await;
    let result = people_search_runs::retained(&mut c, Uuid::from_u128(30008))
        .await
        .unwrap();
    assert!(!result.to_string().contains("PRIVATE_RETAINED_ROOT_CANARY"));
    people_search_no_private(&result);
    assert_eq!(people_search_snapshot(&mut c).await, before);
    stop.cancel();
    task.await.unwrap();
}
