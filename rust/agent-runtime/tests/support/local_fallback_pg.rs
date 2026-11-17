// Deferred fixed loopback primary + explicit local-only Ollama fixtures.
struct FallbackPrimary { mode:&'static str,calls:AtomicUsize }
async fn fallback_primary_response(axum::extract::State(f):axum::extract::State<Arc<FallbackPrimary>>,request:axum::extract::Request)->axum::response::Response {
    use axum::response::IntoResponse;
    assert_eq!(request.headers()["authorization"],"Bearer fictional-test-only-key");
    f.calls.fetch_add(1,Ordering::SeqCst);
    if f.mode=="slow" {tokio::time::sleep(Duration::from_millis(800)).await;}
    if f.mode!="usage" {return axum::http::StatusCode::TOO_MANY_REQUESTS.into_response();}
    let reference=json!({"source_type":"verified_project","source_id":format!("{}:project:0",profile_pin().id)});
    let content=json!({"answer":"I built Rust workers.","evidence_references":[reference],"claims":[{"text":"I built Rust workers.","quote":"I built Rust workers.","source":reference}],"opportunity_claims":[]});
    axum::Json(json!({"finish_reason":"COMPLETE","message":{"content":[{"type":"text","text":content.to_string()}]},"usage":{"tokens":{"input_tokens":64001,"output_tokens":10}}})).into_response()
}
async fn fallback_fixture(mode:&'static str,local:&'static str)->(BTreeMap<String,String>,Arc<FallbackPrimary>,OllamaFixture,CancellationToken,tokio::task::JoinHandle<()>) {
    let (local_values,state,local_stop,local_task)=ollama_fixture(local).await;
    let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();let addr=listener.local_addr().unwrap();
    let primary=Arc::new(FallbackPrimary{mode,calls:AtomicUsize::new(0)});let router=axum::Router::new().route("/v2/chat",axum::routing::post(fallback_primary_response)).with_state(primary.clone());
    let stop=CancellationToken::new();let shutdown=stop.clone();let task=tokio::spawn(async move {axum::serve(listener,router).with_graceful_shutdown(shutdown.cancelled_owned()).await.unwrap();local_stop.cancel();local_task.await.unwrap();});
    let mut values=answer_cloud_values(format!("http://{addr}/v2/chat"));
    for key in ["OLLAMA_ENABLED","OLLAMA_MODEL","RUST_OLLAMA_FIXTURE_ENDPOINT"] {values.insert(key.into(),local_values[key].clone());}
    values.insert("LLM_LOCAL_FALLBACK_ENABLED".into(),"true".into());
    (values,primary,state,stop,task)
}
async fn fallback_generate(c:&mut PgConnection,values:&BTreeMap<String,String>,rewrite:bool)->Value {
    let settings=automated_apply_agents::answer_service::Settings::from_values(values,true,BTreeMap::new()).unwrap();
    automated_apply_agents::answer_service::generate(c,json!({"question":"Describe a project you built","rewrite":rewrite,"save_draft":true}),&settings).await.unwrap()
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn local_fallback_preserves_spent_primary_and_reports_actual_local_model_usage_and_draft() {
    let mut c=narrative_fixture().await;let (values,primary,local,stop,task)=fallback_fixture("429","ok").await;
    let result=fallback_generate(&mut c,&values,true).await;
    assert_eq!(result["status"],"draft_ready");assert_eq!(result["provider"],"ollama");assert_eq!(result["model"],"fixture:local");assert_eq!(result["requires_review"],true);assert_eq!(result["used_llm"],true);
    assert_eq!(result["usage"],json!({"input_tokens":100,"output_tokens":20}));assert!(result["warnings"].as_array().unwrap().iter().any(|v|v.as_str().unwrap().contains("local Ollama fallback")));
    assert_eq!(primary.calls.load(Ordering::SeqCst),1);assert_eq!(local.requests.lock().await.len(),3);
    assert_eq!(sqlx::query_scalar::<_,i32>("SELECT requests FROM llm_monthly_usage WHERE provider='cohere'").fetch_one(&mut c).await.unwrap(),1);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT (value->>'requests')::bigint FROM owner_preferences WHERE starts_with(key,'ai:ollama:')").fetch_one(&mut c).await.unwrap(),1);
    stop.cancel();task.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn disabled_fallback_or_deterministic_extraction_never_touches_local_daemon() {
    let mut c=narrative_fixture().await;let (mut values,primary,local,stop,task)=fallback_fixture("429","ok").await;
    let result=fallback_generate(&mut c,&values,false).await;assert_eq!(result["used_llm"],false);assert_eq!(primary.calls.load(Ordering::SeqCst),0);assert_eq!(local.requests.lock().await.len(),0);
    values.insert("LLM_LOCAL_FALLBACK_ENABLED".into(),"false".into());let result=fallback_generate(&mut c,&values,true).await;
    assert_eq!(result["error_code"],"rate_limited");assert_eq!(result["provider"],"cohere");assert_eq!(primary.calls.load(Ordering::SeqCst),1);assert_eq!(local.requests.lock().await.len(),0);
    stop.cancel();task.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn failed_local_metadata_reports_actual_provider_without_sending_candidate_prompt() {
    let mut c=narrative_fixture().await;let (values,primary,local,stop,task)=fallback_fixture("429","cloud").await;
    let result=fallback_generate(&mut c,&values,true).await;
    assert_eq!(result["provider"],"ollama");assert_eq!(result["model"],"fixture:local");assert_eq!(result["error_code"],"local_model_unverified");assert!(result["answer"].is_null());assert_eq!(result["used_llm"],true);
    assert_eq!(primary.calls.load(Ordering::SeqCst),1);let requests=local.requests.lock().await;assert_eq!(requests.len(),1);assert_eq!(requests[0].0,"/api/status");drop(requests);
    stop.cancel();task.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn unknown_primary_ledger_and_usage_overrun_never_dispatch_local_fallback() {
    for mode in ["ledger","usage"] {
        let mut c=narrative_fixture().await;let (values,primary,local,stop,task)=fallback_fixture(mode,"ok").await;
        if mode=="ledger" {sqlx::raw_sql("CREATE FUNCTION fixture_fail_fallback_ledger() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fictional ledger failure';END $$;CREATE TRIGGER fixture_fail_fallback_ledger BEFORE INSERT ON llm_monthly_usage FOR EACH ROW EXECUTE FUNCTION fixture_fail_fallback_ledger()").execute(&mut c).await.unwrap();}
        let result=fallback_generate(&mut c,&values,true).await;
        assert_eq!(result["provider"],"cohere");assert_eq!(result["error_code"],if mode=="ledger" {"provider_ledger_unavailable"}else{"provider_usage_exceeds_reservation"});assert_eq!(local.requests.lock().await.len(),0);
        assert_eq!(primary.calls.load(Ordering::SeqCst),if mode=="ledger" {0}else{1});
        if mode=="ledger" {sqlx::raw_sql("DROP TRIGGER fixture_fail_fallback_ledger ON llm_monthly_usage;DROP FUNCTION fixture_fail_fallback_ledger()").execute(&mut c).await.unwrap();}
        stop.cancel();task.await.unwrap();
    }
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn fallback_uses_original_deadline_after_slow_primary_and_never_cancels_reservation_commit() {
    for slow_commit in [false,true] {
        let mut c=narrative_fixture().await;let (mut values,primary,local,stop,task)=fallback_fixture(if slow_commit {"429"}else{"slow"},"ok").await;
        values.insert("LLM_TIMEOUT_SECONDS".into(),"1".into());
        if slow_commit {sqlx::raw_sql("CREATE FUNCTION fixture_slow_fallback_commit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_sleep(0.7);RETURN NEW;END $$;CREATE CONSTRAINT TRIGGER fixture_slow_fallback_commit AFTER INSERT ON llm_monthly_usage DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fixture_slow_fallback_commit()").execute(&mut c).await.unwrap();}
        let started=std::time::Instant::now();let result=fallback_generate(&mut c,&values,true).await;
        assert!(started.elapsed()<Duration::from_millis(1600));assert_eq!(result["provider"],"ollama");assert_eq!(result["status"],"draft_ready");assert_eq!(local.requests.lock().await.len(),3);
        assert_eq!(primary.calls.load(Ordering::SeqCst),if slow_commit {0}else{1});
        assert_eq!(sqlx::query_scalar::<_,i32>("SELECT requests FROM llm_monthly_usage WHERE provider='cohere'").fetch_one(&mut c).await.unwrap(),1);
        if slow_commit {sqlx::raw_sql("DROP TRIGGER fixture_slow_fallback_commit ON llm_monthly_usage;DROP FUNCTION fixture_slow_fallback_commit()").execute(&mut c).await.unwrap();}
        stop.cancel();task.await.unwrap();
    }
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn fallback_result_rechecks_current_candidate_context_before_saving_draft() {
    let mut c=narrative_fixture().await;let (values,_,local,stop,task)=fallback_fixture("429","changed").await;
    let before:i64=sqlx::query_scalar("SELECT count(*) FROM application_answer_drafts").fetch_one(&mut c).await.unwrap();
    let result=fallback_generate(&mut c,&values,true).await;assert_eq!(result["error_code"],"generation_context_changed");assert!(result["answer"].is_null());assert!(result["draft_id"].is_null());assert_eq!(local.requests.lock().await.len(),3);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_answer_drafts").fetch_one(&mut c).await.unwrap(),before);
    stop.cancel();task.await.unwrap();
}
