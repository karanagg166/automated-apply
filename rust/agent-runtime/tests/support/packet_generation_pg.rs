async fn packet_generation_fixture()->(PgConnection,Uuid,Value){
    let (mut c,job)=packet_service_fixture().await;
    // The shared fictional model emits attributed project references for this fixture profile UUID.
    let owner=profile_pin().id;
    sqlx::query("UPDATE candidate_profiles SET id=$1,projects=$2 WHERE singleton_key='primary'").bind(owner).bind(json!([{"name":"Queue","purpose":"My project uses Rust.","contribution":"I built Rust workers. I tested the workers.","technologies":["Rust"]}])).execute(&mut c).await.unwrap();
    sqlx::query("UPDATE candidate_resources SET candidate_profile_id=$1").bind(owner).execute(&mut c).await.unwrap();
    let packet=packet_create(&mut c,job,"fictional-packet-generation",json!([{"question":"Describe a project you built"}])).await.unwrap();
    (c,job,packet)
}
async fn packet_generate(c:&mut PgConnection,packet:&Value,revision:i32,rewrite:bool,answers:&automated_apply_agents::answer_service::Settings)->Result<Value>{
    automated_apply_agents::packet_generation::generate(c,packet["id"].as_str().unwrap().parse().unwrap(),packet["fields"][7]["id"].as_str().unwrap().parse().unwrap(),automated_apply_agents::packet_generation::request(json!({"expected_revision":revision,"rewrite":rewrite})).unwrap(),&packet_settings(),answers).await
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn packet_generation_http_explicit_extractive_draft_and_manual_upload_do_not_grant_approval(){
    let (mut c,_job,original)=packet_generation_fixture().await;let id=original["id"].as_str().unwrap();let field=original["fields"][7]["id"].as_str().unwrap();
    let (url,stop,server)=http_fixture().await;let http=client();let root=format!("{url}/api/v1/application-packets/{id}/questions");let endpoint=format!("{root}/{field}/generate");
    let response=http.post(&endpoint).bearer_auth(HOST_TOKEN).json(&json!({"expected_revision":1})).send().await.unwrap();let status=response.status();let generated:Value=response.json().await.unwrap();assert_eq!(status,200,"{generated}");
    assert_eq!(generated["revision"],2);assert_eq!(generated["fields"][7]["validation_status"],"draft_ready");assert!(generated["fields"][7]["proposed_answer"].as_str().unwrap().contains("I built Rust workers."));assert_eq!(generated["fields"][7]["provenance"]["source"],"deterministic_extractive");assert_eq!(generated["fields"][7]["review_status"],"pending");assert_eq!(generated["fields"][7]["answer_revision"],2);assert!(generated["fields"][7]["provenance"]["answer_draft_id"].is_string());assert!(generated["approved_revision"].is_null());
    assert_eq!(http.post(&endpoint).bearer_auth(HOST_TOKEN).json(&json!({"expected_revision":1})).send().await.unwrap().status(),409);
    let upload=format!("{root}/{}/generate",original["fields"][6]["id"].as_str().unwrap());let response=http.post(&upload).bearer_auth(HOST_TOKEN).json(&json!({"expected_revision":2,"rewrite":true})).send().await.unwrap();assert_eq!(response.status(),200);let upload:Value=response.json().await.unwrap();assert_eq!(upload["revision"],3);assert_eq!(upload["fields"][6]["validation_status"],"file_upload_required");assert!(upload["fields"][6]["proposed_answer"].is_null());
    assert_eq!(http.get(&endpoint).bearer_auth(HOST_TOKEN).send().await.unwrap().status(),405);assert_eq!(http.post(&endpoint).json(&json!({"expected_revision":3})).send().await.unwrap().status(),401);assert_eq!(http.post(&endpoint).bearer_auth(HOST_TOKEN).header("X-Agent-Client","extension").json(&json!({"expected_revision":3})).send().await.unwrap().status(),403);
    let events:Vec<String>=sqlx::query_scalar("SELECT event_type FROM application_events ORDER BY packet_revision").fetch_all(&mut c).await.unwrap();assert_eq!(events,vec!["packet_created","answer_generated","answer_generated"]);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_answer_drafts").fetch_one(&mut c).await.unwrap(),4);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM llm_monthly_usage").fetch_one(&mut c).await.unwrap(),0);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_submission_evidence").fetch_one(&mut c).await.unwrap(),0);
    stop.cancel();server.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn packet_generation_bounded_cloud_call_rechecks_profile_context_without_holding_packet_claim(){
    for changed in [false,true]{
        let (mut c,_job,original)=packet_generation_fixture().await;let (settings,state,stop,server)=answer_cloud_fixture(changed,200).await;
        let result=packet_generate(&mut c,&original,1,true,&settings).await;
        assert_eq!(state.calls.load(Ordering::SeqCst),1);
        assert_eq!(sqlx::query_scalar::<_,i32>("SELECT requests FROM llm_monthly_usage WHERE provider='cohere'").fetch_one(&mut c).await.unwrap(),1);
        if changed {
            assert_eq!(result.unwrap_err(),Failure("packet_context_changed"));
            assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_events").fetch_one(&mut c).await.unwrap(),1);
            assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'prv:')").fetch_one(&mut c).await.unwrap(),0);
        }else{
            let result=result.unwrap();assert_eq!(result["revision"],2);assert_eq!(result["fields"][7]["proposed_answer"],"I built Rust workers.");assert_eq!(result["fields"][7]["provenance"]["provider"],"cohere");assert_eq!(result["fields"][7]["review_status"],"pending");assert!(result["approved_revision"].is_null());assert!(result["fields"][7]["provenance"]["answer_draft_id"].is_string());
        }
        stop.cancel();server.await.unwrap();
    }
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn packet_generation_provider_429_is_not_retried_and_preserves_consumed_allowance(){
    let (mut c,_job,original)=packet_generation_fixture().await;let (settings,state,stop,server)=answer_cloud_fixture(false,429).await;
    let first=packet_generate(&mut c,&original,1,true,&settings).await.unwrap();assert_eq!(first["revision"],2);assert!(first["fields"][7]["proposed_answer"].is_null());assert_eq!(first["fields"][7]["provenance"]["error_code"],"rate_limited");
    let second=packet_generate(&mut c,&original,2,true,&settings).await.unwrap();assert_eq!(second["revision"],3);assert!(second["fields"][7]["proposed_answer"].is_null());assert_eq!(state.calls.load(Ordering::SeqCst),1);
    assert_eq!(sqlx::query_scalar::<_,i32>("SELECT requests FROM llm_monthly_usage WHERE provider='cohere'").fetch_one(&mut c).await.unwrap(),1);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_answer_drafts").fetch_one(&mut c).await.unwrap(),3);
    stop.cancel();server.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn packet_generation_http_owner_edits_and_stop_remain_responsive_during_cloud_wait(){
    let (mut c,_job,original)=packet_generation_fixture().await;
    let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();let addr=listener.local_addr().unwrap();let model_stop=CancellationToken::new();let shutdown=model_stop.clone();
    let state=BlockingAnswerFixture{model:AnswerModelFixture{calls:Arc::new(AtomicUsize::new(0)),bodies:Arc::new(tokio::sync::Mutex::new(vec![])),changed:false,status:200},entered:Arc::new(tokio::sync::Notify::new()),release:Arc::new(tokio::sync::Notify::new())};
    let router=axum::Router::new().route("/v2/chat",axum::routing::post(blocking_answer_response)).with_state(state.clone());let model=tokio::spawn(async move{axum::serve(listener,router).with_graceful_shutdown(shutdown.cancelled_owned()).await.unwrap();});
    let mut values=host_values();values.extend(answer_cloud_values(format!("http://{addr}/v2/chat")));values.insert("LLM_MAX_CONCURRENCY".into(),"1".into());let (url,stop,server)=http_fixture_values(values).await;
    let id=original["id"].as_str().unwrap();let field=original["fields"][7]["id"].as_str().unwrap();let root=format!("{url}/api/v1/application-packets/{id}");let endpoint=format!("{root}/questions/{field}/generate");let target=endpoint.clone();
    let request=tokio::spawn(async move{client().post(target).bearer_auth(HOST_TOKEN).json(&json!({"expected_revision":1,"rewrite":true})).send().await.unwrap()});
    tokio::time::timeout(Duration::from_secs(2),state.entered.notified()).await.unwrap();assert!(!request.is_finished());
    let control=client();let status:Value=control.get(format!("{url}/api/v1/rust-agent/control")).bearer_auth(HOST_TOKEN).send().await.unwrap().json().await.unwrap();let stopped=control.put(format!("{url}/api/v1/rust-agent/control")).bearer_auth(HOST_TOKEN).json(&json!({"expected_revision":status["revision"],"mode":"STOPPED"})).send().await.unwrap();assert_eq!(stopped.status(),200);
    assert_eq!(control.post(&endpoint).bearer_auth(HOST_TOKEN).json(&json!({"expected_revision":1})).send().await.unwrap().status(),429);
    let edit=control.patch(format!("{root}/questions/{field}")).bearer_auth(HOST_TOKEN).json(&json!({"expected_revision":1,"answer":"Owner's factual answer wins"})).send().await.unwrap();let status=edit.status();let edit:Value=edit.json().await.unwrap();assert_eq!(status,200,"{edit}");assert_eq!(edit["revision"],2);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM pg_stat_activity WHERE application_name='automated-apply:api' AND state='idle in transaction'").fetch_one(&mut c).await.unwrap(),0);
    state.release.notify_one();let response=request.await.unwrap();assert_eq!(response.status(),409);
    let current:Value=control.get(&root).bearer_auth(HOST_TOKEN).send().await.unwrap().json().await.unwrap();assert_eq!(current["fields"][7]["human_answer"],"Owner's factual answer wins");assert_eq!(current["revision"],2);assert!(current["approved_revision"].is_null());assert_eq!(state.model.calls.load(Ordering::SeqCst),1);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_answer_drafts").fetch_one(&mut c).await.unwrap(),4);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_events").fetch_one(&mut c).await.unwrap(),2);assert_eq!(sqlx::query_scalar::<_,i32>("SELECT requests FROM llm_monthly_usage WHERE provider='cohere'").fetch_one(&mut c).await.unwrap(),1);
    stop.cancel();server.await.unwrap();model_stop.cancel();model.await.unwrap();
}

#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn packet_generation_failed_packet_commit_retains_draft_and_consumed_model_request(){
    let (mut c,_job,original)=packet_generation_fixture().await;let (settings,state,stop,server)=answer_cloud_fixture(false,200).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_generation_event_failure() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fictional generated packet event failure'; END $$; CREATE TRIGGER fixture_generation_event_failure BEFORE INSERT ON application_events FOR EACH ROW EXECUTE FUNCTION fixture_generation_event_failure()").execute(&mut c).await.unwrap();
    assert_eq!(packet_generate(&mut c,&original,1,true,&settings).await.unwrap_err(),Failure("packet_database_error"));
    assert_eq!(state.calls.load(Ordering::SeqCst),1);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_answer_drafts").fetch_one(&mut c).await.unwrap(),4);assert_eq!(sqlx::query_scalar::<_,i32>("SELECT requests FROM llm_monthly_usage WHERE provider='cohere'").fetch_one(&mut c).await.unwrap(),1);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'prv:')").fetch_one(&mut c).await.unwrap(),0);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_events").fetch_one(&mut c).await.unwrap(),1);
    let packet=original["id"].as_str().unwrap().parse::<Uuid>().unwrap();let current=automated_apply_agents::packet_service::dispatch(&mut c,"GET",&format!("/api/v1/application-packets/{packet}"),None,b"",&packet_settings(),&answer_settings()).await.unwrap().0;assert_eq!(current,original);
    sqlx::raw_sql("DROP TRIGGER fixture_generation_event_failure ON application_events; DROP FUNCTION fixture_generation_event_failure()").execute(&mut c).await.unwrap();stop.cancel();server.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn packet_generation_known_post_model_serialization_retries_only_the_packet_transaction(){
    let (mut c,_job,original)=packet_generation_fixture().await;let (settings,state,stop,server)=answer_cloud_fixture(false,200).await;
    // Sequences are deliberately nontransactional in this fictional fault injector.
    sqlx::raw_sql("CREATE SEQUENCE fixture_generation_abort_count; CREATE FUNCTION fixture_generation_abort_once() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF nextval('fixture_generation_abort_count')=1 THEN RAISE EXCEPTION 'fictional serialization abort' USING ERRCODE='40001'; END IF; RETURN NEW; END $$; CREATE TRIGGER fixture_generation_abort_once BEFORE INSERT ON application_events FOR EACH ROW EXECUTE FUNCTION fixture_generation_abort_once()").execute(&mut c).await.unwrap();
    let result=packet_generate(&mut c,&original,1,true,&settings).await.unwrap();assert_eq!(result["revision"],2);assert_eq!(result["fields"][7]["proposed_answer"],"I built Rust workers.");assert!(result["approved_revision"].is_null());assert_eq!(state.calls.load(Ordering::SeqCst),1);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_answer_drafts").fetch_one(&mut c).await.unwrap(),4);assert_eq!(sqlx::query_scalar::<_,i32>("SELECT requests FROM llm_monthly_usage WHERE provider='cohere'").fetch_one(&mut c).await.unwrap(),1);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'prv:')").fetch_one(&mut c).await.unwrap(),1);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_events").fetch_one(&mut c).await.unwrap(),2);
    sqlx::raw_sql("DROP TRIGGER fixture_generation_abort_once ON application_events; DROP FUNCTION fixture_generation_abort_once(); DROP SEQUENCE fixture_generation_abort_count").execute(&mut c).await.unwrap();stop.cancel();server.await.unwrap();
}
