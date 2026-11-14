#[derive(Clone)]
struct GeminiFixture {
    calls: Arc<AtomicUsize>,
    requests: Arc<tokio::sync::Mutex<Vec<Value>>>,
    mode: &'static str,
}
async fn gemini_response(
    axum::extract::State(state): axum::extract::State<GeminiFixture>,
    headers: axum::http::HeaderMap,
    axum::Json(body): axum::Json<Value>,
) -> axum::response::Response {
    use axum::response::IntoResponse;
    assert_eq!(headers["x-goog-api-key"], "fictional-gemini-key");
    assert!(!headers.contains_key("authorization"));
    state.calls.fetch_add(1, Ordering::SeqCst);
    state.requests.lock().await.push(body);
    if state.mode == "changed" {
        let mut c = connection().await;
        sqlx::query("UPDATE candidate_profiles SET version=5 WHERE singleton_key='primary'")
            .execute(&mut c)
            .await
            .unwrap();
    }
    if state.mode == "429" {
        return (
            axum::http::StatusCode::TOO_MANY_REQUESTS,
            [("retry-after", "120")],
            "fictional refusal",
        )
            .into_response();
    }
    if state.mode == "redirect" {
        return (
            axum::http::StatusCode::FOUND,
            [("location", "/must-not-follow")],
            "",
        )
            .into_response();
    }
    if state.mode == "oversize" {
        return "x".repeat(131073).into_response();
    }
    let source = json!({"source_type":"verified_project","source_id":format!("{}:project:0",profile_pin().id)});
    let answer = if state.mode == "unsupported" {
        "I built a million users."
    } else {
        "I built Rust workers."
    };
    let content = json!({"answer":answer,"evidence_references":[source],"claims":[{"text":answer,"quote":"I built Rust workers.","source":source}],"opportunity_claims":[]});
    let reason = if state.mode == "incomplete" {
        "MAX_TOKENS"
    } else {
        "STOP"
    };
    axum::Json(json!({"candidates":[{"finishReason":reason,"content":{"role":"model","parts":[{"text":content.to_string()}]}}],"usageMetadata":{"promptTokenCount":100,"candidatesTokenCount":10,"thoughtsTokenCount":2}})).into_response()
}
fn gemini_values(endpoint: String) -> BTreeMap<String, String> {
    BTreeMap::from([
        ("LLM_PROVIDER".into(), "gemini".into()),
        ("LLM_MODEL".into(), "models/gemini-fixture".into()),
        ("GEMINI_API_KEY".into(), "fictional-gemini-key".into()),
        ("GEMINI_ENABLED".into(), "true".into()),
        ("GEMINI_CANDIDATE_DATA_AUTHORIZED".into(), "true".into()),
        ("GEMINI_APPROVED_MONTHLY_REQUESTS".into(), "2".into()),
        ("LLM_MONTHLY_MAX_REQUESTS".into(), "5".into()),
        ("RUST_GEMINI_FIXTURE_ENDPOINT".into(), endpoint),
    ])
}
async fn gemini_fixture(
    mode: &'static str,
) -> (
    BTreeMap<String, String>,
    GeminiFixture,
    CancellationToken,
    tokio::task::JoinHandle<()>,
) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let state = GeminiFixture {
        calls: Arc::new(AtomicUsize::new(0)),
        requests: Arc::new(tokio::sync::Mutex::new(vec![])),
        mode,
    };
    let stop = CancellationToken::new();
    let shutdown = stop.clone();
    let router = axum::Router::new()
        .route(
            "/v1beta/models/gemini-fixture:generateContent",
            axum::routing::post(gemini_response),
        )
        .with_state(state.clone());
    let task = tokio::spawn(async move {
        axum::serve(listener, router)
            .with_graceful_shutdown(shutdown.cancelled_owned())
            .await
            .unwrap();
    });
    (
        gemini_values(format!(
            "http://{address}/v1beta/models/gemini-fixture:generateContent"
        )),
        state,
        stop,
        task,
    )
}
fn gemini_settings(
    values: &BTreeMap<String, String>,
    fixture: bool,
) -> automated_apply_agents::answer_service::Settings {
    automated_apply_agents::answer_service::Settings::from_values(values, fixture, BTreeMap::new())
        .unwrap()
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gemini_generation_uses_native_structured_endpoint_and_shared_durable_grants() {
    use automated_apply_agents::answer_service;
    let mut c = narrative_fixture().await;
    sqlx::query("INSERT INTO llm_monthly_usage(provider,month,requests) VALUES('gemini',to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM'),1),('cohere',to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM'),4)").execute(&mut c).await.unwrap();
    let (values, state, stop, task) = gemini_fixture("ok").await;
    let settings = gemini_settings(&values, true);
    let input = json!({"question":"Describe a project you built","rewrite":true,"save_draft":true});
    let result = answer_service::generate(&mut c, input.clone(), &settings)
        .await
        .unwrap();
    assert_eq!(result["status"], "draft_ready");
    assert_eq!(result["answer"], "I built Rust workers.");
    assert_eq!(result["provider"], "gemini");
    assert_eq!(result["requires_review"], true);
    assert_eq!(
        result["usage"],
        json!({"input_tokens":100,"output_tokens":12})
    );
    let next = answer_service::generate(&mut c, input, &settings)
        .await
        .unwrap();
    assert_eq!(next["error_code"], "monthly_request_limit");
    assert_eq!(next["used_llm"], false);
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    let bodies = state.requests.lock().await;
    let body = &bodies[0];
    assert_eq!(body["generationConfig"]["candidateCount"], 1);
    assert_eq!(
        body["generationConfig"]["responseMimeType"],
        "application/json"
    );
    assert_eq!(
        body["generationConfig"]["responseJsonSchema"]["additionalProperties"],
        false
    );
    assert!(body.get("tools").is_none());
    assert!(!body.to_string().contains("private-fictional@example.com"));
    assert!(!body.to_string().contains("fictional-gemini-key"));
    let row: (i32, i32, i32) = sqlx::query_as(
        "SELECT requests,input_tokens,output_tokens FROM llm_monthly_usage WHERE provider='gemini'",
    )
    .fetch_one(&mut c)
    .await
    .unwrap();
    assert_eq!(row, (2, 100, 12));
    assert_eq!(
        sqlx::query_scalar::<_, i32>(
            "SELECT requests FROM llm_monthly_usage WHERE provider='cohere'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        4
    );
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gemini_permissions_fixture_destinations_and_input_bounds_fail_before_reservation() {
    use automated_apply_agents::answer_service;
    let mut c = narrative_fixture().await;
    let (values, state, stop, task) = gemini_fixture("ok").await;
    for (key, value, fixture, code) in [
        (
            "GEMINI_ENABLED",
            "false",
            true,
            "provider_permission_required",
        ),
        (
            "GEMINI_APPROVED_MONTHLY_REQUESTS",
            "0",
            true,
            "provider_permission_required",
        ),
        (
            "GEMINI_CANDIDATE_DATA_AUTHORIZED",
            "false",
            true,
            "candidate_cloud_authorization_required",
        ),
        ("LLM_MODEL", "gemini-x/other", true, "model_unavailable"),
        ("LLM_MAX_INPUT_CHARS", "1000", true, "input_limit_exceeded"),
        (
            "RUST_GEMINI_FIXTURE_ENDPOINT",
            "http://127.0.0.1:9999/v2/chat",
            true,
            "provider_fixture_endpoint_denied",
        ),
        (
            "RUST_GEMINI_FIXTURE_ENDPOINT",
            values["RUST_GEMINI_FIXTURE_ENDPOINT"].as_str(),
            false,
            "provider_fixture_endpoint_denied",
        ),
    ] {
        let mut changed = values.clone();
        changed.insert(key.into(), value.into());
        let result = answer_service::generate(
            &mut c,
            json!({"question":"Describe a project you built","rewrite":true}),
            &gemini_settings(&changed, fixture),
        )
        .await
        .unwrap();
        assert_eq!(result["error_code"], code, "{key}");
        assert_eq!(result["used_llm"], false);
        assert!(result["draft_id"].is_null());
    }
    assert_eq!(state.calls.load(Ordering::SeqCst), 0);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM llm_monthly_usage")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gemini_failed_or_stale_answers_never_save_and_do_not_retry_or_refund() {
    use automated_apply_agents::answer_service;
    for (mode, code) in [
        ("changed", "generation_context_changed"),
        ("incomplete", "invalid_structured_response"),
        ("unsupported", "unsupported_accomplishment"),
        ("redirect", "provider_error"),
        ("oversize", "provider_response_size"),
    ] {
        let mut c = narrative_fixture().await;
        let (values, state, stop, task) = gemini_fixture(mode).await;
        let result = answer_service::generate(
            &mut c,
            json!({"question":"Describe a project you built","rewrite":true,"save_draft":true}),
            &gemini_settings(&values, true),
        )
        .await
        .unwrap();
        assert_eq!(result["error_code"], code, "{mode}: {result}");
        assert_eq!(result["used_llm"], true);
        assert!(result["answer"].is_null());
        assert!(result["draft_id"].is_null());
        assert_eq!(state.calls.load(Ordering::SeqCst), 1);
        assert_eq!(
            sqlx::query_scalar::<_, i32>(
                "SELECT requests FROM llm_monthly_usage WHERE provider='gemini'"
            )
            .fetch_one(&mut c)
            .await
            .unwrap(),
            1
        );
        assert_eq!(
            sqlx::query_scalar::<_, i64>("SELECT count(*) FROM application_answer_drafts")
                .fetch_one(&mut c)
                .await
                .unwrap(),
            3
        );
        stop.cancel();
        task.await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gemini_429_retains_provider_retry_after_across_connections_without_second_call() {
    use automated_apply_agents::answer_service;
    let mut c = narrative_fixture().await;
    let (values, state, stop, task) = gemini_fixture("429").await;
    let settings = gemini_settings(&values, true);
    let input = json!({"question":"Describe a project you built","rewrite":true});
    let result = answer_service::generate(&mut c, input.clone(), &settings)
        .await
        .unwrap();
    assert_eq!(result["error_code"], "rate_limited");
    assert_eq!(result["retry_after_seconds"], 120.0);
    assert_eq!(result["used_llm"], true);
    c.close().await.unwrap();
    let mut c = connection().await;
    let result = answer_service::generate(&mut c, input, &settings)
        .await
        .unwrap();
    assert_eq!(result["error_code"], "rate_limited");
    assert_eq!(result["used_llm"], false);
    assert!((119.0..=120.0).contains(&result["retry_after_seconds"].as_f64().unwrap()));
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    assert!(sqlx::query_scalar::<_,bool>("SELECT cooldown_until>clock_timestamp()+interval '110 seconds' FROM llm_monthly_usage WHERE provider='gemini'").fetch_one(&mut c).await.unwrap());
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gemini_monthly_grants_are_atomic_across_connections_and_keep_cohere_separate() {
    let mut a = setup().await;
    let mut b = connection().await;
    let (first, second) = tokio::join!(
        monthly::reserve_gemini(&mut a, 5, 1),
        monthly::reserve_gemini(&mut b, 5, 1)
    );
    assert_eq!(usize::from(first.is_ok()) + usize::from(second.is_ok()), 1);
    assert_eq!(
        first.err().or(second.err()),
        Some(Failure("monthly_request_limit"))
    );
    let month = tokio::time::timeout(
        Duration::from_secs(2),
        monthly::reserve(&mut a, monthly_policy()),
    )
    .await
    .unwrap()
    .unwrap();
    monthly::tokens(&mut a, &month, Some(5), Some(7))
        .await
        .unwrap();
    assert_eq!(
        sqlx::query_scalar::<_, i32>(
            "SELECT requests FROM llm_monthly_usage WHERE provider='gemini'"
        )
        .fetch_one(&mut a)
        .await
        .unwrap(),
        1
    );
    assert_eq!(
        sqlx::query_scalar::<_, i32>(
            "SELECT input_tokens FROM llm_monthly_usage WHERE provider='gemini'"
        )
        .fetch_one(&mut a)
        .await
        .unwrap(),
        0
    );
}
