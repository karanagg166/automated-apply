#[derive(Clone)]
struct OllamaFixture {
    mode: &'static str,
    requests: Arc<tokio::sync::Mutex<Vec<(String, Value)>>>,
}
async fn ollama_response(
    axum::extract::State(state): axum::extract::State<OllamaFixture>,
    request: axum::extract::Request,
) -> axum::response::Response {
    use axum::response::IntoResponse;
    let path = request.uri().path().to_string();
    assert!(!request.headers().contains_key("authorization"));
    assert_eq!(request.headers()["accept-encoding"], "identity");
    let raw = axum::body::to_bytes(request.into_body(), 65536)
        .await
        .unwrap();
    let body = if raw.is_empty() {
        Value::Null
    } else {
        serde_json::from_slice(&raw).unwrap()
    };
    state.requests.lock().await.push((path.clone(), body.clone()));
    match path.as_str() {
        "/api/status" => {
            if state.mode == "cloud" {
                return axum::Json(json!({"cloud":{"disabled":false}})).into_response();
            }
            if state.mode == "missing_status" {
                return axum::http::StatusCode::NOT_FOUND.into_response();
            }
            if state.mode == "redirect" {
                return (
                    axum::http::StatusCode::FOUND,
                    [("location", "/must-not-follow")],
                    "",
                )
                    .into_response();
            }
            if state.mode == "encoding" {
                return ([("content-encoding", "gzip")], "forbidden").into_response();
            }
            axum::Json(json!({"cloud":{"disabled":true}})).into_response()
        }
        "/api/show" => {
            assert_eq!(
                state.requests.lock().await.last().unwrap().1,
                json!({"model":"fixture:local"})
            );
            if state.mode == "remote" {
                return axum::Json(json!({"remote_model":"cloud","model_info":{"x":1}}))
                    .into_response();
            }
            if state.mode == "empty_info" {
                return axum::Json(json!({"model_info":{}})).into_response();
            }
            axum::Json(json!({"model_info":{"fixture.architecture":"fictional"}})).into_response()
        }
        "/api/generate" | "/api/chat" => {
            if state.mode == "429" {
                return axum::http::StatusCode::TOO_MANY_REQUESTS.into_response();
            }
            if state.mode == "oversize" {
                return "x".repeat(131073).into_response();
            }
            if state.mode == "slow" {
                // An observable server stall verifies the absolute transport deadline.
                tokio::time::sleep(std::time::Duration::from_millis(1200)).await;
            }
            if state.mode == "changed" {
                let mut c = connection().await;
                sqlx::query(
                    "UPDATE candidate_profiles SET version=5 WHERE singleton_key='primary'",
                )
                .execute(&mut c)
                .await
                .unwrap();
            }
            let source = json!({"source_type":"verified_project","source_id":format!("{}:project:0",profile_pin().id)});
            let answer = if state.mode == "unsupported" {
                "I built a million users."
            } else {
                "I built Rust workers."
            };
            let content = json!({"answer":answer,"evidence_references":[source],"claims":[{"text":answer,"quote":"I built Rust workers.","source":source}],"opportunity_claims":[]});
            let mut value = json!({"model":"fixture:local","done":true,"done_reason":"stop","response":content.to_string(),"prompt_eval_count":100,"eval_count":20});
            if path=="/api/chat" {
                let (_,payload)=body["messages"][1]["content"].as_str().unwrap().split_once('\n').unwrap();
                let selected:Value=serde_json::from_str(payload).unwrap();
                let mut sentences=selected["permitted_sentences"].as_array().unwrap().iter().map(|row|row[0].as_str().unwrap()).collect::<Vec<_>>();sentences.reverse();
                let text=if state.mode=="unsupported" {"I invented millions of users.".into()}else{sentences.join(" ")};
                value.as_object_mut().unwrap().remove("response");
                value["message"]=json!({"role":"assistant","content":json!({"answer":text}).to_string()});
            }
            match state.mode {
                "incomplete" => value["done_reason"] = json!("length"),
                "wrong_model" => value["model"] = json!("another:local"),
                "tool" => value["tool_calls"] = json!([{"name":"apply"}]),
                "bad_usage" => value["eval_count"] = json!(true),
                "over_usage" => value["eval_count"] = json!(257),
                "remote_reply" => value["remote_host"] = json!("https://forbidden.invalid"),
                _ => {}
            }
            axum::Json(value).into_response()
        }
        _ => panic!("unexpected provider path"),
    }
}
async fn ollama_fixture(
    mode: &'static str,
) -> (
    BTreeMap<String, String>,
    OllamaFixture,
    CancellationToken,
    tokio::task::JoinHandle<()>,
) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let state = OllamaFixture {
        mode,
        requests: Arc::new(tokio::sync::Mutex::new(vec![])),
    };
    let stop = CancellationToken::new();
    let shutdown = stop.clone();
    let router = axum::Router::new()
        .fallback(ollama_response)
        .with_state(state.clone());
    let task = tokio::spawn(async move {
        axum::serve(listener, router)
            .with_graceful_shutdown(shutdown.cancelled_owned())
            .await
            .unwrap();
    });
    let values = BTreeMap::from([
        ("LLM_PROVIDER".into(), "ollama".into()),
        ("OLLAMA_ENABLED".into(), "true".into()),
        ("OLLAMA_MODEL".into(), "fixture:local".into()),
        (
            "RUST_OLLAMA_FIXTURE_ENDPOINT".into(),
            format!("http://{address}"),
        ),
        ("LLM_MONTHLY_MAX_REQUESTS".into(), "2".into()),
    ]);
    (values, state, stop, task)
}
async fn ollama_generate(
    c: &mut PgConnection,
    values: &BTreeMap<String, String>,
    fixture: bool,
) -> Value {
    automated_apply_agents::answer_service::generate(
        c,
        json!({"question":"Describe a project you built","rewrite":true,"save_draft":true}),
        &gemini_settings(values, fixture),
    )
    .await
    .unwrap()
}
async fn ollama_ledger(c: &mut PgConnection) -> Value {
    sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key='ai:ollama:'||to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM')").fetch_one(c).await.unwrap()
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn ollama_reuses_legacy_optional_ledger_and_saves_only_reviewable_grounded_draft() {
    let mut c = narrative_fixture().await;
    sqlx::query("INSERT INTO owner_preferences(key,value) VALUES('ai:ollama:'||to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM'),'{\"requests\":1,\"cooldown\":0,\"retained\":\"owner-field\"}')").execute(&mut c).await.unwrap();
    let (values, state, stop, task) = ollama_fixture("ok").await;
    let result = ollama_generate(&mut c, &values, true).await;
    assert_eq!(result["status"], "draft_ready");
    assert_eq!(result["provider"], "ollama");
    assert_eq!(result["answer"], "I built Rust workers.");
    assert_eq!(result["requires_review"], true);
    assert_eq!(
        result["usage"],
        json!({"input_tokens":100,"output_tokens":20})
    );
    let next = ollama_generate(&mut c, &values, true).await;
    assert_eq!(next["error_code"], "monthly_request_limit");
    assert_eq!(next["used_llm"], false);
    assert_eq!(
        ollama_ledger(&mut c).await,
        json!({"requests":2,"cooldown":0,"retained":"owner-field"})
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM llm_monthly_usage")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM application_packets")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    let requests = state.requests.lock().await;
    assert_eq!(requests.len(), 3);
    assert_eq!(requests[0].0, "/api/status");
    assert_eq!(requests[1].0, "/api/show");
    assert_eq!(requests[2].0, "/api/generate");
    let body = &requests[2].1;
    assert_eq!(body["keep_alive"], 0);
    assert_eq!(
        body["options"],
        json!({"temperature":0,"seed":0,"num_ctx":2048,"num_thread":2,"num_predict":256})
    );
    assert_eq!(body["format"]["additionalProperties"], false);
    assert_eq!(body["stream"], false);
    assert!(!body.to_string().contains("private-fictional@example.com"));
    assert!(body.get("tools").is_none());
    drop(requests);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn ollama_metadata_must_prove_locality_before_receiving_any_candidate_prompt() {
    for (mode, code) in [
        ("cloud", "local_model_unverified"),
        ("remote", "local_model_unverified"),
        ("empty_info", "local_model_unverified"),
        ("missing_status", "model_unavailable"),
        ("redirect", "provider_redirect_denied"),
        ("encoding", "provider_encoding_denied"),
    ] {
        let mut c = narrative_fixture().await;
        let (values, state, stop, task) = ollama_fixture(mode).await;
        let result = ollama_generate(&mut c, &values, true).await;
        assert_eq!(result["error_code"], code, "{mode}");
        assert_eq!(result["used_llm"], true);
        assert!(result["answer"].is_null());
        let requests = state.requests.lock().await;
        assert!(requests.iter().all(|(path, _)| path != "/api/generate"));
        assert!(
            !serde_json::to_string(&*requests)
                .unwrap()
                .contains("Rust workers")
        );
        drop(requests);
        assert_eq!(ollama_ledger(&mut c).await["requests"], 1);
        stop.cancel();
        task.await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn ollama_rejects_incomplete_foreign_tool_oversized_and_ungrounded_outputs() {
    for (mode, code) in [
        ("incomplete", "invalid_structured_response"),
        ("wrong_model", "invalid_structured_response"),
        ("tool", "invalid_structured_response"),
        ("bad_usage", "invalid_structured_response"),
        ("over_usage", "provider_output_size"),
        ("remote_reply", "local_model_unverified"),
        ("oversize", "provider_response_size"),
        ("unsupported", "unsupported_accomplishment"),
    ] {
        let mut c = narrative_fixture().await;
        let (values, state, stop, task) = ollama_fixture(mode).await;
        let result = ollama_generate(&mut c, &values, true).await;
        assert_eq!(result["error_code"], code, "{mode}: {result}");
        assert_eq!(result["used_llm"], true);
        assert!(result["answer"].is_null());
        assert!(result["draft_id"].is_null());
        assert_eq!(state.requests.lock().await.len(), 3);
        assert_eq!(ollama_ledger(&mut c).await["requests"], 1);
        stop.cancel();
        task.await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn ollama_configuration_and_input_failures_do_not_consume_quota_or_contact_daemon() {
    let mut c = narrative_fixture().await;
    let (values, state, stop, task) = ollama_fixture("ok").await;
    for (key, value, fixture, code) in [
        (
            "OLLAMA_ENABLED",
            "false",
            true,
            "provider_execution_not_authorized",
        ),
        (
            "OLLAMA_MODEL",
            "cloud-fixture",
            true,
            "cloud_model_forbidden",
        ),
        ("OLLAMA_MODEL", "https://bad.invalid", true, "invalid_model"),
        (
            "LLM_MONTHLY_MAX_REQUESTS",
            "0",
            true,
            "monthly_request_limit",
        ),
        ("LLM_MAX_INPUT_CHARS", "1000", true, "input_limit_exceeded"),
        (
            "RUST_OLLAMA_FIXTURE_ENDPOINT",
            "http://127.0.0.1:12345/other",
            true,
            "provider_fixture_endpoint_denied",
        ),
        (
            "RUST_OLLAMA_FIXTURE_ENDPOINT",
            values["RUST_OLLAMA_FIXTURE_ENDPOINT"].as_str(),
            false,
            "provider_fixture_endpoint_denied",
        ),
    ] {
        let mut changed = values.clone();
        changed.insert(key.into(), value.into());
        let result = ollama_generate(&mut c, &changed, fixture).await;
        assert_eq!(result["error_code"], code, "{key}");
        assert_eq!(result["used_llm"], false);
    }
    assert_eq!(state.requests.lock().await.len(), 0);
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM owner_preferences WHERE key LIKE 'ai:ollama:%'"
        )
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
async fn ollama_rate_limit_persists_shared_cooldown_and_never_refunds_failed_request() {
    let mut c = narrative_fixture().await;
    let (values, state, stop, task) = ollama_fixture("429").await;
    let first = ollama_generate(&mut c, &values, true).await;
    assert_eq!(first["error_code"], "rate_limited");
    assert_eq!(first["used_llm"], true);
    assert_eq!(first["retry_after_seconds"], 60.0);
    let second = ollama_generate(&mut c, &values, true).await;
    assert_eq!(second["error_code"], "rate_limited");
    assert_eq!(second["used_llm"], false);
    assert_eq!(state.requests.lock().await.len(), 3);
    assert_eq!(ollama_ledger(&mut c).await["requests"], 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn ollama_malformed_legacy_counter_fails_closed_without_resetting_owner_data() {
    let mut c = narrative_fixture().await;
    let (values, state, stop, task) = ollama_fixture("ok").await;
    for value in [
        json!({"requests":true,"cooldown":0}),
        json!({"requests":-1,"cooldown":0}),
        json!({"requests":0,"cooldown":"bad"}),
    ] {
        sqlx::query("INSERT INTO owner_preferences(key,value) VALUES('ai:ollama:'||to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM'),$1) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value").bind(&value).execute(&mut c).await.unwrap();
        let result = ollama_generate(&mut c, &values, true).await;
        assert_eq!(result["error_code"], "provider_ledger_invalid");
        assert_eq!(result["used_llm"], false);
        assert_eq!(ollama_ledger(&mut c).await, value);
    }
    assert_eq!(state.requests.lock().await.len(), 0);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn ollama_rechecks_context_after_generation_and_cannot_save_stale_answers() {
    let mut c = narrative_fixture().await;
    let (values, _state, stop, task) = ollama_fixture("changed").await;
    let result = ollama_generate(&mut c, &values, true).await;
    assert_eq!(result["error_code"], "generation_context_changed");
    assert!(result["answer"].is_null());
    assert!(result["draft_id"].is_null());
    assert_eq!(ollama_ledger(&mut c).await["requests"], 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn ollama_total_transport_deadline_does_not_retry_or_refund_the_reservation() {
    let mut c = narrative_fixture().await;
    let (mut values, state, stop, task) = ollama_fixture("slow").await;
    values.insert("LLM_TIMEOUT_SECONDS".into(), "1".into());
    let start = std::time::Instant::now();
    let result = ollama_generate(&mut c, &values, true).await;
    assert_eq!(result["error_code"], "timeout");
    assert_eq!(result["used_llm"], true);
    assert!(start.elapsed() < std::time::Duration::from_secs(3));
    assert_eq!(state.requests.lock().await.len(), 3);
    assert_eq!(ollama_ledger(&mut c).await["requests"], 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn ollama_concurrent_independent_clients_cannot_overspend_the_shared_request_cap() {
    let mut c1 = narrative_fixture().await;
    let mut c2 = connection().await;
    let (mut values, state, stop, task) = ollama_fixture("ok").await;
    values.insert("LLM_MONTHLY_MAX_REQUESTS".into(), "1".into());
    let (first, second) = tokio::join!(
        ollama_generate(&mut c1, &values, true),
        ollama_generate(&mut c2, &values, true)
    );
    let results = [first, second];
    assert_eq!(
        results
            .iter()
            .filter(|r| r["status"] == "draft_ready")
            .count(),
        1
    );
    assert_eq!(
        results
            .iter()
            .filter(|r| r["error_code"] == "monthly_request_limit" && r["used_llm"] == false)
            .count(),
        1
    );
    assert_eq!(ollama_ledger(&mut c1).await["requests"], 1);
    assert_eq!(state.requests.lock().await.len(), 3);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn ollama_shared_runtime_gate_rejects_overlapping_generation_before_reservation() {
    let mut c1 = narrative_fixture().await;
    let mut c2 = connection().await;
    let (values, state, stop, task) = ollama_fixture("slow").await;
    let settings = gemini_settings(&values, true);
    let request = json!({"question":"Describe a project you built","rewrite":true});
    let (first, second) = tokio::join!(
        automated_apply_agents::answer_service::generate(&mut c1, request.clone(), &settings),
        automated_apply_agents::answer_service::generate(&mut c2, request, &settings)
    );
    let results = [first.unwrap(), second.unwrap()];
    assert_eq!(
        results
            .iter()
            .filter(|r| r["status"] == "draft_ready")
            .count(),
        1
    );
    assert_eq!(
        results
            .iter()
            .filter(|r| r["error_code"] == "provider_busy" && r["used_llm"] == false)
            .count(),
        1
    );
    assert_eq!(ollama_ledger(&mut c1).await["requests"], 1);
    assert_eq!(state.requests.lock().await.len(), 3);
    stop.cancel();
    task.await.unwrap();
}
