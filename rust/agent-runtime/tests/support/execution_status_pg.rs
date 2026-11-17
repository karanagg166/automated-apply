// Real HTTP/SQL fictional status fixtures; no production configuration or browser.
async fn execution_status(c:&mut PgConnection,query:Option<&str>)->Result<Value>{automated_apply_agents::execution::dispatch(c,automated_apply_agents::execution::Route::Queue,"GET",query).await}
async fn execution_seed_policy(c:&mut PgConnection)->Value {
    let policy=automated_apply_agents::execution::contracts::normalize(automated_apply_agents::execution::contracts::Kind::Policy,json!({"global_limits":{"max_job_age_days":14,"applicant_limit":1000,"minimum_match_score":50},"platforms":{"naukri":{"enabled":true,"mode":"SUPERVISED","owner_submission_authorized":true,"supervised_submission_cap":4,"hourly_submission_cap":1,"skill_match_mode":"any"}}})).unwrap();let value=json!({"revision":162,"state":"STOPPED","policy":policy});browser_save(c,"application_queue_policy",value.clone()).await;value
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn execution_status_preserves_saved_stop_filters_admissions_and_daily_reservations() {
    let mut c=browser_fixture().await;let config=execution_seed_policy(&mut c).await;
    let admissions=json!(["first-uncertain","second-uncertain","third-uncertain"]);sqlx::query("INSERT INTO owner_preferences(key,value) SELECT 'apply_budget:naukri:'||to_char((clock_timestamp() AT TIME ZONE 'Asia/Kolkata')::date+i,'YYYY-MM-DD'),$1 FROM generate_series(-1,1) i").bind(json!({"reservations":admissions})).execute(&mut c).await.unwrap();
    for(i,stage)in ["SUBMISSION_UNKNOWN","NEEDS_INPUT","SKIPPED"].iter().enumerate(){let id=Uuid::new_v4();browser_save(&mut c,&format!("apply_work:{id}"),json!({"id":id,"platform":"naukri","requisition":format!("1234567890{i:02}"),"stage":stage,"status":"waiting","operation":"inspect_job","revision":4,"title":format!("Fictional Engineer {i}"),"company":"Fictional Employer","location":"Remote","match_score":80,"facts":{"description":"PRIVATE_RAW_DESCRIPTION_CANARY","posted_date":"2026-11-15","applicants_min":50},"admitted_actions":[{"fingerprint":"apply:initial"}],"binding":{"profile_secret":"PRIVATE_BINDING_CANARY"}})).await;}
    browser_save(&mut c,"apply_search:naukri",json!({"last_cycle_count":3,"last_error":null,"lease_token":"PRIVATE_SEARCH_LEASE"})).await;let before=browser_snapshot(&mut c).await;
    let data=execution_status(&mut c,None).await.unwrap();assert_eq!(data["configuration"],config);assert_eq!(data["quota"],json!({"reserved_today":3,"daily_cap":4,"remaining":1,"hourly_cap":1}));assert_eq!(data["total"],3);assert_eq!(data["counts"]["SUBMISSION_UNKNOWN"],1);assert_eq!(data["discovery"]["last_cycle_count"],3);assert_eq!(data["capabilities"]["submission"],"unavailable");assert!(!data.to_string().contains("PRIVATE_"));assert_eq!(browser_snapshot(&mut c).await,before);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn execution_status_filtered_paging_counts_all_stages_without_returning_full_descriptions() {
    let mut c=browser_fixture().await;execution_seed_policy(&mut c).await;
    for(i,score)in [10,55,90].iter().enumerate(){let id=Uuid::new_v4();browser_save(&mut c,&format!("apply_work:{id}"),json!({"id":id,"platform":"naukri","stage":"NEEDS_INPUT","title":format!("Engineer {i}"),"company":"Fictional O'Reilly","location":"Remote","match_score":score})).await;}
    let filtered=execution_status(&mut c,Some("platform=naukri&stage=NEEDS_INPUT&search=O%27Reilly&location=Rem&minimum_score=50&limit=1&offset=1")).await.unwrap();assert_eq!(filtered["items"].as_array().unwrap().len(),1);assert_eq!(filtered["total"],2);assert_eq!(filtered["counts"]["NEEDS_INPUT"],3);assert_eq!(filtered["limit"],1);assert_eq!(filtered["offset"],1);
    assert_eq!(execution_status(&mut c,Some("search=%27%20OR%201%3D1--")).await.unwrap()["total"],0);
    for query in ["limit=0","offset=-1","minimum_score=101","platform=unconfigured","stage=NOT_A_STAGE"]{assert_eq!(execution_status(&mut c,Some(query)).await.unwrap_err(),Failure("invalid_execution_page"));}
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn execution_status_retained_history_is_aggregated_without_inventory_cap_or_owner_lock_wait() {
    let mut c=browser_fixture().await;execution_seed_policy(&mut c).await;browser_save(&mut c,"agent_conversation:primary",json!({"retained":true})).await;
    sqlx::query("INSERT INTO owner_preferences(key,value) SELECT 'apply_work:history-'||i,jsonb_build_object('id',i,'platform','naukri','stage','SKIPPED','facts',jsonb_build_object('description',repeat('PRIVATE_HISTORY_DESCRIPTION_CANARY',128))) FROM generate_series(1,20002) i").execute(&mut c).await.unwrap();
    let mut owner=connection().await;let mut held=owner.begin().await.unwrap();sqlx::query("SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE").execute(&mut *held).await.unwrap();sqlx::query("SET lock_timeout='100ms'").execute(&mut c).await.unwrap();
    let data=execution_status(&mut c,Some("limit=2")).await.unwrap();assert_eq!(data["total"],20002);assert_eq!(data["counts"]["SKIPPED"],20002);assert_eq!(data["items"].as_array().unwrap().len(),2);assert!(data.to_string().len()<20000);assert!(!data.to_string().contains("PRIVATE_HISTORY_DESCRIPTION"));held.rollback().await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn execution_status_bad_saved_budget_or_policy_never_becomes_a_reset_allowance() {
    let mut c=browser_fixture().await;let config=execution_seed_policy(&mut c).await;let day:String=sqlx::query_scalar("SELECT to_char(clock_timestamp() AT TIME ZONE 'Asia/Kolkata','YYYY-MM-DD')").fetch_one(&mut c).await.unwrap();let key=format!("apply_budget:naukri:{day}");browser_save(&mut c,&key,json!({"reservations":null,"retained_unknown":true})).await;let before=browser_snapshot(&mut c).await;
    assert_eq!(execution_status(&mut c,None).await.unwrap_err(),Failure("invalid_execution_saved_record"));assert_eq!(browser_snapshot(&mut c).await,before);
    browser_save(&mut c,&key,json!({"reservations":[]})).await;let mut invalid=config.clone();invalid["policy"]["day_timezone"]=json!("../../owner-private");browser_save(&mut c,"application_queue_policy",invalid.clone()).await;assert_eq!(execution_status(&mut c,None).await.unwrap_err(),Failure("invalid_execution_saved_record"));assert_eq!(browser_pref(&mut c,"application_queue_policy").await,invalid);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn execution_status_http_owner_native_separation_methods_and_account_defaults_remain_closed() {
    let mut c=browser_fixture().await;let config=execution_seed_policy(&mut c).await;let(url,stop,server)=http_fixture_values(browser_values()).await;let http=client();let queue=format!("{url}/api/v1/execution/queue");
    assert_eq!(http.get(&queue).send().await.unwrap().status(),401);assert_eq!(http.get(&queue).bearer_auth(HOST_TOKEN).header("x-agent-client",BROWSER_EXTENSION).send().await.unwrap().status(),403);assert_eq!(http.get(&queue).bearer_auth(HOST_TOKEN).header("origin","https://untrusted.example.net").send().await.unwrap().status(),403);
    let status=http.get(&queue).bearer_auth(HOST_TOKEN).send().await.unwrap();assert_eq!(status.status(),200);assert_eq!(status.json::<Value>().await.unwrap()["configuration"],config);let wrong=http.post(&queue).bearer_auth(HOST_TOKEN).json(&json!({"action":"start","expected_revision":162})).send().await.unwrap();assert_eq!(wrong.status(),405);assert_eq!(wrong.headers().get("allow").unwrap(),"GET");
    let account=http.get(format!("{url}/api/v1/execution/naukri/account-binding")).bearer_auth(HOST_TOKEN).send().await.unwrap();assert_eq!(account.status(),200);assert_eq!(account.json::<Value>().await.unwrap(),json!({"revision":0,"approved":false}));assert_eq!(http.get(format!("{queue}?limit=0")).bearer_auth(HOST_TOKEN).send().await.unwrap().status(),422);stop.cancel();server.await.unwrap();assert_eq!(browser_pref(&mut c,"application_queue_policy").await,config);
}
