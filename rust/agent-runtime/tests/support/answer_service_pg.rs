use std::sync::atomic::{AtomicUsize, Ordering};

fn answer_settings() -> automated_apply_agents::answer_service::Settings {
    automated_apply_agents::answer_service::Settings::from_values(
        &BTreeMap::new(),
        true,
        BTreeMap::new(),
    )
    .unwrap()
}
async fn narrative_fixture() -> PgConnection {
    let mut c = missing_fixture().await;
    let projects = json!([{"name":"Queue","purpose":"My project uses Rust.","contribution":"I built Rust workers. I tested the workers.","technologies":["Rust"]}]);
    sqlx::query("UPDATE candidate_profiles SET projects=$1 WHERE singleton_key='primary'")
        .bind(projects)
        .execute(&mut c)
        .await
        .unwrap();
    c
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn generation_saves_exact_direct_draft_without_inference_or_application_authority() {
    use automated_apply_agents::answer_service;
    let mut c = missing_fixture().await;
    let before = profile_store::get(&mut c).await.unwrap().value;
    let result = answer_service::generate(
        &mut c,
        json!({"question":"Email","save_draft":true,"rewrite":true,"writing_style":"concise"}),
        &answer_settings(),
    )
    .await
    .unwrap();
    assert_eq!(result["answer"], "private-fictional@example.com");
    assert_eq!(result["source"], "candidate_profile");
    assert_eq!(result["used_llm"], false);
    assert_eq!(result["writing_style"], "concise");
    let id = result["draft_id"]
        .as_str()
        .unwrap()
        .parse::<Uuid>()
        .unwrap();
    let mut observer = connection().await;
    let row: Value =
        sqlx::query_scalar("SELECT to_jsonb(d) FROM application_answer_drafts d WHERE id=$1")
            .bind(id)
            .fetch_one(&mut observer)
            .await
            .unwrap();
    assert_eq!(row["answer"], result["answer"]);
    assert_eq!(row["review_status"], "draft");
    assert_eq!(row["candidate_profile_version"], 4);
    assert_eq!(profile_store::get(&mut c).await.unwrap().value, before);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM application_packets")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM llm_monthly_usage")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn generation_reuses_only_exact_current_owner_answer_and_retains_same_draft() {
    use automated_apply_agents::{answer_service, missing_store};
    let mut c = missing_fixture().await;
    let input = json!({"question":"Preferred interview time?","save_draft":true});
    let first = answer_service::generate(&mut c, input.clone(), &answer_settings())
        .await
        .unwrap();
    assert_eq!(first["status"], "needs_input");
    let id = first["missing_input_id"].as_str().unwrap();
    let same = answer_service::generate(&mut c, input.clone(), &answer_settings())
        .await
        .unwrap();
    assert_eq!(same["missing_input_id"], first["missing_input_id"]);
    missing_edit(&mut c, id, 1).await;
    let approved = missing_approve(&mut c, id, 2, &Uuid::new_v4().simple().to_string())
        .await
        .unwrap();
    let result = answer_service::generate(&mut c, input.clone(), &answer_settings())
        .await
        .unwrap();
    assert_eq!(result["source"], "owner_approved_exact_context");
    assert_eq!(result["draft_id"], approved["draft_id"]);
    assert_eq!(result["requires_review"], false);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM application_answer_drafts")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        4
    );
    sqlx::query("UPDATE candidate_profiles SET version=5 WHERE singleton_key='primary'")
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        missing_store::read(&mut c, id).await.unwrap()["effective_status"],
        "review_required"
    );
    let result = answer_service::generate(&mut c, input, &answer_settings())
        .await
        .unwrap();
    assert_eq!(result["status"], "needs_input");
    assert!(result["answer"].is_null());
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn generation_extracts_actual_attributed_project_facts_and_keeps_uploads_manual() {
    use automated_apply_agents::answer_service;
    let mut c = narrative_fixture().await;
    let result = answer_service::generate(
        &mut c,
        json!({"question":"Describe a project you built","save_draft":true}),
        &answer_settings(),
    )
    .await
    .unwrap();
    assert_eq!(result["status"], "draft_ready");
    assert_eq!(result["source"], "deterministic_extractive");
    assert_eq!(result["used_llm"], false);
    assert!(
        result["answer"]
            .as_str()
            .unwrap()
            .contains("I built Rust workers.")
    );
    assert_eq!(result["requires_review"], true);
    assert_eq!(
        result["evidence_references"][0]["source_type"],
        "verified_project"
    );
    let upload = answer_service::generate(
        &mut c,
        json!({"question":"Upload resume","save_draft":true,"rewrite":true}),
        &answer_settings(),
    )
    .await
    .unwrap();
    assert_eq!(upload["status"], "file_upload_required");
    assert!(upload["answer"].is_null());
    assert!(upload["draft_id"].is_null());
    assert_eq!(upload["resources"][0]["accessibility"], "not_checked");
    let bounded = answer_service::generate(
        &mut c,
        json!({"question":"Email within 2 characters","save_draft":true}),
        &answer_settings(),
    )
    .await
    .unwrap();
    assert_eq!(bounded["error_code"], "output_length_exceeded");
    assert!(bounded["answer"].is_null());
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM llm_monthly_usage")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn generation_missing_evidence_does_not_infer_work_from_skills_or_retain_sensitive_declarations()
 {
    use automated_apply_agents::answer_service;
    let mut c = missing_fixture().await;
    sqlx::query("INSERT INTO candidate_evidence(id,candidate_profile_id,evidence_type,title,content,user_confirmed,created_at,updated_at) VALUES($1,$2,'other','Redis','I built Redis workers.',false,clock_timestamp(),clock_timestamp())").bind(Uuid::new_v4()).bind(profile_pin().id).execute(&mut c).await.unwrap();
    let result = answer_service::generate(
        &mut c,
        json!({"question":"Describe your experience with Redis","save_draft":true}),
        &answer_settings(),
    )
    .await
    .unwrap();
    assert_eq!(result["status"], "needs_input");
    assert!(result["answer"].is_null());
    assert!(result["draft_id"].is_null());
    let sensitive = answer_service::generate(
        &mut c,
        json!({"question":"What is your passport number?"}),
        &answer_settings(),
    )
    .await
    .unwrap();
    assert_eq!(sensitive["status"], "needs_input");
    assert!(sensitive["missing_input_id"].is_null());
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM owner_preferences WHERE starts_with(key,'needs_input:')"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        1
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn generation_rejects_context_substitution_and_commits_neither_draft_nor_question_on_failure()
{
    use automated_apply_agents::answer_service;
    let mut c = missing_fixture().await;
    let job = Uuid::new_v4();
    let company = Uuid::new_v4();
    sqlx::query("INSERT INTO companies(id,name,domain) VALUES($1,'Fictional Labs','example.com')")
        .bind(company)
        .execute(&mut c)
        .await
        .unwrap();
    sqlx::query("INSERT INTO jobs(id,company_id,title,description,job_url,source_platform) VALUES($1,$2,'Rust role','Saved employer description','https://example.com/job','greenhouse')").bind(job).bind(company).execute(&mut c).await.unwrap();
    for (key, value, code) in [
        (
            "company_name",
            "Invented company",
            "company_context_mismatch",
        ),
        (
            "job_description",
            "Invented listing",
            "job_context_mismatch",
        ),
    ] {
        let mut input = json!({"question":"Email","job_id":job,"save_draft":true});
        input[key] = json!(value);
        let result = answer_service::generate(&mut c, input, &answer_settings())
            .await
            .unwrap();
        assert_eq!(result["error_code"], code);
        assert_eq!(result["status"], "validation_failed");
    }
    sqlx::raw_sql("CREATE OR REPLACE FUNCTION fixture_generation_reject() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fictional_generation_commit_failure';RETURN NEW;END $$;CREATE CONSTRAINT TRIGGER fixture_generation_reject AFTER INSERT ON application_answer_drafts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fixture_generation_reject()").execute(&mut c).await.unwrap();
    assert_eq!(
        answer_service::generate(
            &mut c,
            json!({"question":"Email","save_draft":true}),
            &answer_settings()
        )
        .await
        .err(),
        Some(Failure("profile_database_error"))
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM application_answer_drafts")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        3
    );
    sqlx::raw_sql("ALTER TABLE owner_preferences ADD CONSTRAINT fixture_missing_refusal CHECK(NOT starts_with(key,'needs_input:'))").execute(&mut c).await.unwrap();
    assert_eq!(
        answer_service::generate(
            &mut c,
            json!({"question":"Preferred schedule?"}),
            &answer_settings()
        )
        .await
        .err(),
        Some(Failure("profile_database_error"))
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM owner_preferences WHERE starts_with(key,'needs_input:')"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        0
    );
}
#[derive(Clone)]
struct AnswerModelFixture {
    calls: Arc<AtomicUsize>,
    bodies: Arc<tokio::sync::Mutex<Vec<Value>>>,
    changed: bool,
    status: u16,
}
async fn answer_model_response(
    axum::extract::State(state): axum::extract::State<AnswerModelFixture>,
    axum::Json(body): axum::Json<Value>,
) -> (axum::http::StatusCode, axum::Json<Value>) {
    state.calls.fetch_add(1, Ordering::SeqCst);
    state.bodies.lock().await.push(body);
    if state.changed {
        let mut c = connection().await;
        sqlx::query("UPDATE candidate_profiles SET version=5 WHERE singleton_key='primary'")
            .execute(&mut c)
            .await
            .unwrap();
    }
    let reference = json!({"source_type":"verified_project","source_id":format!("{}:project:0",profile_pin().id)});
    let content = json!({"answer":"I built Rust workers.","evidence_references":[reference],"claims":[{"text":"I built Rust workers.","quote":"I built Rust workers.","source":reference}],"opportunity_claims":[]});
    (
        axum::http::StatusCode::from_u16(state.status).unwrap(),
        axum::Json(
            json!({"finish_reason":"COMPLETE","message":{"role":"assistant","content":[{"type":"text","text":content.to_string()}]},"usage":{"tokens":{"input_tokens":100,"output_tokens":10}}}),
        ),
    )
}
async fn answer_cloud_fixture(
    changed: bool,
    status: u16,
) -> (
    automated_apply_agents::answer_service::Settings,
    AnswerModelFixture,
    CancellationToken,
    tokio::task::JoinHandle<()>,
) {
    let state = AnswerModelFixture {
        calls: Arc::new(AtomicUsize::new(0)),
        bodies: Arc::new(tokio::sync::Mutex::new(vec![])),
        changed,
        status,
    };
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let stop = CancellationToken::new();
    let shutdown = stop.clone();
    let router = axum::Router::new()
        .route("/v2/chat", axum::routing::post(answer_model_response))
        .with_state(state.clone());
    let server = tokio::spawn(async move {
        axum::serve(listener, router)
            .with_graceful_shutdown(shutdown.cancelled_owned())
            .await
            .unwrap();
    });
    let settings = automated_apply_agents::answer_service::Settings::from_values(
        &answer_cloud_values(format!("http://{addr}/v2/chat")),
        true,
        BTreeMap::new(),
    )
    .unwrap();
    (settings, state, stop, server)
}
fn answer_cloud_values(endpoint: String) -> BTreeMap<String, String> {
    let mut values = BTreeMap::from([
        ("LLM_PROVIDER".into(), "cohere".into()),
        ("COHERE_MODEL".into(), "command-a-plus-05-2026".into()),
        ("COHERE_API_KEY".into(), "fictional-test-only-key".into()),
        ("COHERE_ENABLED".into(), "true".into()),
        ("COHERE_EVALUATION_KEY_CONFIRMED".into(), "true".into()),
        ("COHERE_OWNER_TEXT_AUTHORIZED".into(), "true".into()),
        ("COHERE_CANDIDATE_DATA_AUTHORIZED".into(), "true".into()),
        ("LLM_MONTHLY_MAX_REQUESTS".into(), "5".into()),
        ("COHERE_MONTHLY_MAX_REQUESTS".into(), "5".into()),
        ("COHERE_MONTHLY_MAX_TOKENS".into(), "110000".into()),
    ]);
    values.insert("RUST_COHERE_FIXTURE_ENDPOINT".into(), endpoint);
    values
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn generation_uses_one_bounded_cloud_call_and_rechecks_current_facts_without_holding_a_read_lock()
 {
    use automated_apply_agents::answer_service;
    for changed in [false, true] {
        let mut c = narrative_fixture().await;
        let (settings, state, stop, server) = answer_cloud_fixture(changed, 200).await;
        let result = answer_service::generate(
            &mut c,
            json!({"question":"Describe a project you built","rewrite":true,"save_draft":true}),
            &settings,
        )
        .await
        .unwrap();
        assert_eq!(state.calls.load(Ordering::SeqCst), 1);
        assert_eq!(result["used_llm"], true);
        let body = state.bodies.lock().await[0].clone();
        assert_eq!(body["stream"], false);
        assert!(body.get("tools").is_none());
        assert!(!body.to_string().contains("private-fictional@example.com"));
        assert!(!body.to_string().contains("fictional-test-only-key"));
        if changed {
            assert_eq!(result["error_code"], "generation_context_changed");
            assert!(result["answer"].is_null());
            assert!(result["draft_id"].is_null());
            assert_eq!(
                sqlx::query_scalar::<_, i64>("SELECT count(*) FROM application_answer_drafts")
                    .fetch_one(&mut c)
                    .await
                    .unwrap(),
                3
            );
        } else {
            assert_eq!(result["answer"], "I built Rust workers.");
            assert_eq!(result["status"], "draft_ready");
            assert_eq!(result["requires_review"], true);
            assert!(result["draft_id"].as_str().is_some());
        }
        assert_eq!(
            sqlx::query_scalar::<_, i32>(
                "SELECT requests FROM llm_monthly_usage WHERE provider='cohere'"
            )
            .fetch_one(&mut c)
            .await
            .unwrap(),
            1
        );
        stop.cancel();
        server.await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn generation_cloud_429_consumes_one_request_and_preserves_cooldown_without_automatic_retry()
{
    use automated_apply_agents::answer_service;
    let mut c = narrative_fixture().await;
    let (settings, state, stop, server) = answer_cloud_fixture(false, 429).await;
    let input = json!({"question":"Describe a project you built","rewrite":true,"save_draft":true});
    let first = answer_service::generate(&mut c, input.clone(), &settings)
        .await
        .unwrap();
    assert_eq!(first["status"], "provider_unavailable");
    assert_eq!(first["error_code"], "rate_limited");
    assert_eq!(first["used_llm"], true);
    let second = answer_service::generate(&mut c, input, &settings)
        .await
        .unwrap();
    assert_eq!(second["error_code"], "rate_limited");
    assert_eq!(second["used_llm"], false);
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        sqlx::query_scalar::<_, i32>(
            "SELECT requests FROM llm_monthly_usage WHERE provider='cohere'"
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
    server.await.unwrap();
}
#[derive(Clone)]
struct BlockingAnswerFixture {
    model: AnswerModelFixture,
    entered: Arc<tokio::sync::Notify>,
    release: Arc<tokio::sync::Notify>,
}
async fn blocking_answer_response(
    axum::extract::State(state): axum::extract::State<BlockingAnswerFixture>,
    body: axum::Json<Value>,
) -> (axum::http::StatusCode, axum::Json<Value>) {
    state.entered.notify_one();
    state.release.notified().await;
    answer_model_response(axum::extract::State(state.model), body).await
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn generation_http_keeps_stop_responsive_and_rejects_parallel_generation_during_provider_wait()
 {
    let mut c = narrative_fixture().await;
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let model_stop = CancellationToken::new();
    let shutdown = model_stop.clone();
    let state = BlockingAnswerFixture {
        model: AnswerModelFixture {
            calls: Arc::new(AtomicUsize::new(0)),
            bodies: Arc::new(tokio::sync::Mutex::new(vec![])),
            changed: false,
            status: 200,
        },
        entered: Arc::new(tokio::sync::Notify::new()),
        release: Arc::new(tokio::sync::Notify::new()),
    };
    let router = axum::Router::new()
        .route("/v2/chat", axum::routing::post(blocking_answer_response))
        .with_state(state.clone());
    let model = tokio::spawn(async move {
        axum::serve(listener, router)
            .with_graceful_shutdown(shutdown.cancelled_owned())
            .await
            .unwrap();
    });
    let mut values = host_values();
    values.extend(answer_cloud_values(format!("http://{address}/v2/chat")));
    values.insert("LLM_MAX_CONCURRENCY".into(), "1".into());
    let (url, stop, server) = http_fixture_values(values).await;
    let target = format!("{url}/api/v1/application-answers/generate");
    let endpoint = target.clone();
    let http = reqwest::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(10))
        .build()
        .unwrap();
    let request = tokio::spawn(async move {
        http.post(endpoint).bearer_auth(HOST_TOKEN).json(&json!({"question":"Describe a project you built","rewrite":true,"save_draft":true})).send().await.unwrap()
    });
    tokio::time::timeout(Duration::from_secs(2), state.entered.notified())
        .await
        .unwrap();
    let control = client();
    let status: Value = control
        .get(format!("{url}/api/v1/rust-agent/control"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    let paused = control
        .put(format!("{url}/api/v1/rust-agent/control"))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"expected_revision":status["revision"],"mode":"STOPPED"}))
        .send()
        .await
        .unwrap();
    assert_eq!(paused.status(), 200);
    assert_eq!(paused.json::<Value>().await.unwrap()["mode"], "STOPPED");
    assert!(!request.is_finished());
    assert_eq!(
        control
            .post(&target)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"question":"Email"}))
            .send()
            .await
            .unwrap()
            .status(),
        429
    );
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM pg_stat_activity WHERE application_name='automated-apply:api' AND state='idle in transaction'").fetch_one(&mut c).await.unwrap(),0);
    state.release.notify_one();
    let response = request.await.unwrap();
    assert_eq!(response.status(), 200);
    assert_eq!(
        response.json::<Value>().await.unwrap()["status"],
        "draft_ready"
    );
    assert_eq!(state.model.calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        sqlx::query_scalar::<_, i32>(
            "SELECT requests FROM llm_monthly_usage WHERE provider='cohere'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        1
    );
    stop.cancel();
    server.await.unwrap();
    model_stop.cancel();
    model.await.unwrap();
}
