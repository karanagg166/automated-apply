// Deferred explicit sentence-only provider branch through fixed fictional loopback.
fn sentence_values(mut values:BTreeMap<String,String>)->BTreeMap<String,String> {
    values.insert("OLLAMA_ENABLED".into(),"false".into());values.insert("OLLAMA_GENERATION_AUTHORIZED".into(),"true".into());values
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn explicit_sentence_rearranger_uses_chat_permitted_sentences_and_shared_budget_grounding() {
    let mut c=narrative_fixture().await;let (values,state,stop,task)=ollama_fixture("ok").await;
    let result=ollama_generate(&mut c,&sentence_values(values),true).await;
    assert_eq!(result["status"],"draft_ready");assert_eq!(result["provider"],"ollama");assert_eq!(result["requires_review"],true);assert!(result["draft_id"].is_string());
    let calls=state.requests.lock().await.clone();assert_eq!(calls.len(),3);assert_eq!(calls[2].0,"/api/chat");
    let body=&calls[2].1;assert_eq!(body["tools"],json!([]));assert_eq!(body["stream"],false);assert_eq!(body["keep_alive"],0);assert_eq!(body["options"]["num_ctx"],1024);assert_eq!(body["options"]["num_thread"],2);assert!(body["options"]["num_predict"].as_u64().unwrap()<=256);
    let raw=body.to_string();assert!(!raw.contains("private-fictional@example.com"));assert!(!raw.contains("evidence_references"));assert!(!raw.contains("source_id"));
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT (value->>'requests')::bigint FROM owner_preferences WHERE starts_with(key,'ai:ollama:')").fetch_one(&mut c).await.unwrap(),1);
    stop.cancel();task.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn sentence_rearranger_missing_authorization_or_locality_never_sends_candidate_prompt() {
    for mode in ["permission","cloud","remote"] {
        let mut c=narrative_fixture().await;let (values,state,stop,task)=ollama_fixture(if mode=="permission" {"ok"}else{mode}).await;
        let mut values=sentence_values(values);if mode=="permission" {values.insert("OLLAMA_GENERATION_AUTHORIZED".into(),"false".into());}
        let result=ollama_generate(&mut c,&values,true).await;assert!(result["answer"].is_null());
        assert_eq!(state.requests.lock().await.iter().filter(|(path,_)|path=="/api/chat").count(),0);
        assert_eq!(result["error_code"],if mode=="permission" {"provider_execution_not_authorized"}else{"local_model_unverified"});
        stop.cancel();task.await.unwrap();
    }
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn sentence_rearranger_rejects_tools_added_facts_usage_overrun_and_oversized_replies_without_retry() {
    for mode in ["unsupported","tool","over_usage","oversize"] {
        let mut c=narrative_fixture().await;let (values,state,stop,task)=ollama_fixture(mode).await;
        let before:i64=sqlx::query_scalar("SELECT count(*) FROM application_answer_drafts").fetch_one(&mut c).await.unwrap();
        let result=ollama_generate(&mut c,&sentence_values(values),true).await;assert!(result["answer"].is_null());assert!(result["error_code"].is_string());assert_eq!(state.requests.lock().await.len(),3);
        assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_answer_drafts").fetch_one(&mut c).await.unwrap(),before);
        assert_eq!(sqlx::query_scalar::<_,i64>("SELECT (value->>'requests')::bigint FROM owner_preferences WHERE starts_with(key,'ai:ollama:')").fetch_one(&mut c).await.unwrap(),1);
        stop.cancel();task.await.unwrap();
    }
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn sentence_rearranger_keeps_current_candidate_stamp_and_extracts_without_calling_model() {
    let mut c=narrative_fixture().await;let (values,state,stop,task)=ollama_fixture("changed").await;let values=sentence_values(values);
    let settings=automated_apply_agents::answer_service::Settings::from_values(&values,true,BTreeMap::new()).unwrap();
    let deterministic=automated_apply_agents::answer_service::generate(&mut c,json!({"question":"Describe a project you built","rewrite":false}),&settings).await.unwrap();assert_eq!(deterministic["used_llm"],false);assert_eq!(state.requests.lock().await.len(),0);
    let result=ollama_generate(&mut c,&values,true).await;assert_eq!(result["error_code"],"generation_context_changed");assert!(result["answer"].is_null());assert!(result["draft_id"].is_null());assert_eq!(state.requests.lock().await.len(),3);
    stop.cancel();task.await.unwrap();
}
