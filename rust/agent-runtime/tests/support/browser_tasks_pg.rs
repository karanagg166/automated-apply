async fn browser_task_open(c:&mut PgConnection,context:&Value,packet:&Value)->Value {
    let r=browser_native(c,"open_application_task",context,json!({"application_id":packet["id"]})).await.unwrap();assert_eq!(r["ok"],true,"{r}");assert_eq!(r["capability"],"extension_task");r["data"]["task"].clone()
}
async fn browser_task_event(c:&mut PgConnection,context:&Value,task:&Value,event:&str,extra:Value)->Value {
    let mut v=json!({"task_id":task["id"],"expected_task_version":task["version"],"task_event":event,"tab_id":task["tab_id"],"window_id":task["window_id"]});for(k,x)in extra.as_object().unwrap(){v[k]=x.clone();}browser_native(c,"update_application_task",context,v).await.unwrap()
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_tasks_native_open_duplicate_bind_pause_resume_and_cancel_keep_exact_ownership() {
    let (mut c,context,packet)=browser_command_fixture().await;let task=browser_task_open(&mut c,&context,&packet).await;assert_eq!(task["state"],"PACKET_READY");assert_eq!(task["tab_id"],Value::Null);assert_eq!(task["capabilities"]["reviewed_submission"],false);
    assert_eq!(browser_task_open(&mut c,&context,&packet).await,task);
    let bound=browser_task_event(&mut c,&context,&task,"bind",json!({"tab_id":50,"observed_url":task["target_url"]})).await;assert_eq!(bound["ok"],true,"{bound}");let task=bound["data"]["task"].clone();assert_eq!(task["version"],2);assert_eq!(task["tab_id"],50);
    let pause=browser_task_event(&mut c,&context,&task,"pause",json!({})).await;assert_eq!(pause["ok"],true);let paused=pause["data"]["task"].clone();assert_eq!(paused["state"],"PAUSED");assert_eq!(paused["reason"],"owner_pause");
    assert_eq!(browser_task_event(&mut c,&context,&paused,"bind",json!({"tab_id":50})).await["error_code"],"extension_task_paused_or_cancelled");
    let resume=browser_task_event(&mut c,&context,&paused,"resume",json!({})).await;assert_eq!(resume["ok"],true);let task=resume["data"]["task"].clone();assert_eq!(task["state"],"PACKET_READY");assert!(task["plan_id"].is_null());
    let cancel=browser_task_event(&mut c,&context,&task,"cancel",json!({})).await;let task=cancel["data"]["task"].clone();assert_eq!(task["state"],"FAILED_FINAL");assert_eq!(browser_task_event(&mut c,&context,&task,"resume",json!({})).await["error_code"],"extension_task_terminal");assert_eq!(browser_native(&mut c,"open_application_task",&context,json!({"application_id":packet["id"]})).await.unwrap()["error_code"],"extension_task_terminal");
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_tasks_focus_loss_is_idempotent_and_never_grants_a_new_plan() {
    let (mut c,context,packet)=browser_command_fixture().await;let task=browser_task_open(&mut c,&context,&packet).await;let task=browser_task_event(&mut c,&context,&task,"bind",json!({"tab_id":50})).await["data"]["task"].clone();
    let paused=browser_task_event(&mut c,&context,&task,"focus_lost",json!({})).await["data"]["task"].clone();assert_eq!(paused["state"],"PAUSED");assert_eq!(paused["reason"],"focus_lost");assert_eq!(paused["tab_active"],false);
    let same=browser_task_event(&mut c,&context,&paused,"focus_lost",json!({})).await;assert_eq!(same["data"]["task"],paused);
    let unknown=browser_task_event(&mut c,&context,&paused,"navigation",json!({"observed_url":"https://www.naukri.com/account"})).await["data"]["task"].clone();assert_eq!(unknown["reason"],"unexpected_navigation");assert_eq!(unknown["current_url"],task["target_url"]);assert!(unknown["authorization_id"].is_null());
    let denied=browser_task_event(&mut c,&context,&unknown,"fill_started",json!({"plan_id":Uuid::new_v4()})).await;assert_eq!(denied["error_code"],"extension_task_not_authorized");assert_eq!(browser_task_event(&mut c,&context,&unknown,"fill_finished",json!({})).await["error_code"],"verified_fill_receipt_required");
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_tasks_native_request_nonce_is_consumed_and_failed_savepoint_does_not_leave_a_task() {
    let (mut c,context,packet)=browser_command_fixture().await;let id=Uuid::new_v4();let request=json!({"application_id":packet["id"],"request_id":id});let one=browser_native(&mut c,"open_application_task",&context,request.clone()).await.unwrap();assert_eq!(one["ok"],true);assert_eq!(browser_native(&mut c,"open_application_task",&context,request).await.unwrap()["error_code"],"form_request_already_consumed");
    let task=one["data"]["task"].clone();let before=browser_snapshot(&mut c).await;let count:i64=sqlx::query_scalar("SELECT count(*) FROM agent_operations").fetch_one(&mut c).await.unwrap();
    sqlx::raw_sql("CREATE FUNCTION fixture_task_audit_fail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'extension_request:') THEN RAISE EXCEPTION 'fictional request audit failure'; END IF; RETURN NEW; END $$;CREATE TRIGGER fixture_task_audit_fail BEFORE INSERT ON agent_operations FOR EACH ROW EXECUTE FUNCTION fixture_task_audit_fail()").execute(&mut c).await.unwrap();
    let error=browser_native(&mut c,"update_application_task",&context,json!({"task_id":task["id"],"expected_task_version":task["version"],"task_event":"bind","tab_id":50,"observed_url":task["target_url"]})).await.unwrap_err();assert_eq!(error,Failure("browser_profile_database_error"));assert_eq!(browser_snapshot(&mut c).await,before);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM agent_operations").fetch_one(&mut c).await.unwrap(),count);
    sqlx::raw_sql("DROP TRIGGER fixture_task_audit_fail ON agent_operations;DROP FUNCTION fixture_task_audit_fail()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_tasks_read_checkpoint_uses_consistent_metadata_without_waiting_for_owner_lock() {
    let (mut c,context,packet)=browser_command_fixture().await;let task=browser_task_open(&mut c,&context,&packet).await;let task=browser_task_event(&mut c,&context,&task,"bind",json!({"tab_id":50})).await["data"]["task"].clone();let count:i64=sqlx::query_scalar("SELECT count(*) FROM agent_operations").fetch_one(&mut c).await.unwrap();
    let mut holder=connection().await;let mut tx=holder.begin().await.unwrap();sqlx::query("SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE").execute(&mut *tx).await.unwrap();sqlx::query("SET lock_timeout='100ms'").execute(&mut c).await.unwrap();
    let checkpoint=browser_native(&mut c,"get_application_task",&context,json!({"task_id":task["id"],"expected_task_version":task["version"],"tab_id":50})).await.unwrap();assert_eq!(checkpoint["ok"],true,"{checkpoint}");assert_eq!(checkpoint["data"]["task"],task);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM agent_operations").fetch_one(&mut c).await.unwrap(),count);tx.rollback().await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_tasks_fill_recovery_retains_unknown_evidence_and_owner_pause_without_reauthorization() {
    let (mut c,context,packet)=browser_command_fixture().await;let task=browser_task_open(&mut c,&context,&packet).await;let mut task=browser_task_event(&mut c,&context,&task,"bind",json!({"tab_id":50})).await["data"]["task"].clone();task["state"]=json!("FILLING");task["plan_id"]=json!(Uuid::new_v4());task["authorization_id"]=json!(Uuid::new_v4());let key=format!("ext_task:{}",task["id"].as_str().unwrap());browser_save(&mut c,&key,task.clone()).await;
    let recovered=browser_task_event(&mut c,&context,&task,"worker_restart",json!({})).await;assert_eq!(recovered["ok"],true,"{recovered}");let mut task=recovered["data"]["task"].clone();assert_eq!(task["state"],"PAUSED");assert_eq!(task["verified_receipts"][0]["state"],"manual_required");assert_eq!(task["verified_receipts"][0]["verification_method"],"unknown");assert_eq!(task["verified_receipts"][0]["submitted"],false);assert!(task["plan_id"].is_null());
    task["reason"]=json!("global_stop");browser_save(&mut c,&key,task.clone()).await;let again=browser_task_event(&mut c,&context,&task,"recover",json!({})).await["data"]["task"].clone();assert_eq!(again["reason"],"global_stop");assert_eq!(again["tab_id"],Value::Null);assert_eq!(again["network_guard_active"],false);assert_eq!(again["verified_receipts"].as_array().unwrap().len(),1);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_tasks_get_filling_pauses_on_changed_candidate_instead_of_claiming_a_completed_fill() {
    let (mut c,context,packet)=browser_command_fixture().await;let mut task=browser_task_open(&mut c,&context,&packet).await;task["state"]=json!("FILLING");let key=format!("ext_task:{}",task["id"].as_str().unwrap());browser_save(&mut c,&key,task.clone()).await;
    sqlx::query("UPDATE candidate_profiles SET full_name='Corrected fictional name' WHERE singleton_key='primary'").execute(&mut c).await.unwrap();let result=browser_native(&mut c,"get_application_task",&context,json!({"task_id":task["id"]})).await.unwrap();assert_eq!(result["ok"],true,"{result}");assert_eq!(result["data"]["task"]["state"],"PAUSED");assert_eq!(result["data"]["task"]["reason"],"candidate_or_packet_changed_during_fill");assert!(result["data"]["task"]["authorization_id"].is_null());
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_tasks_remote_request_cannot_outlive_original_executing_command_lease() {
    let (mut c,context,packet)=browser_command_fixture().await;let queued=browser_call(&mut c,BrowserRoute::Enqueue,browser_enqueue_input(&context,&packet)).await.unwrap();let leased=browser_native(&mut c,"poll_chrome_command",&context,json!({})).await.unwrap()["data"]["command"].clone();let executing=browser_native(&mut c,"start_chrome_command",&context,browser_lease_command(&leased)).await.unwrap()["data"]["command"].clone();
    let mut open=browser_lease_command(&executing);open["application_id"]=packet["id"].clone();let task=browser_native(&mut c,"open_application_task",&context,open.clone()).await.unwrap();assert_eq!(task["ok"],true,"{task}");
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{lease_expires_at}','\"2000-01-01T00:00:00Z\"') WHERE key=$1").bind(format!("chr_cmd:{}",queued["id"].as_str().unwrap())).execute(&mut c).await.unwrap();let before=browser_snapshot(&mut c).await;
    open["task_id"]=task["data"]["task"]["id"].clone();open["expected_task_version"]=task["data"]["task"]["version"].clone();open["task_event"]=json!("bind");open["tab_id"]=json!(50);let denied=browser_native(&mut c,"update_application_task",&context,open).await.unwrap();assert_eq!(denied["error_code"],"profile_command_expired");assert_eq!(browser_snapshot(&mut c).await,before);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_tasks_owner_http_status_lookup_and_control_preserve_native_client_separation() {
    let (mut c,context,packet)=browser_command_fixture().await;let task=browser_task_open(&mut c,&context,&packet).await;let (url,stop,server)=http_fixture_values(browser_values()).await;let http=client();let listing=format!("{url}/api/v1/browser/extension-tasks");
    assert_eq!(http.get(&listing).bearer_auth(HOST_TOKEN).header("x-agent-client",BROWSER_EXTENSION).send().await.unwrap().status(),403);let listed:Value=http.get(&listing).bearer_auth(HOST_TOKEN).send().await.unwrap().json().await.unwrap();assert_eq!(listed,json!([task.clone()]));
    let found:Value=http.get(format!("{listing}/application/{}",packet["id"].as_str().unwrap())).bearer_auth(HOST_TOKEN).send().await.unwrap().json().await.unwrap();assert_eq!(found,task);let missing:Value=http.get(format!("{listing}/application/{}",Uuid::new_v4())).bearer_auth(HOST_TOKEN).send().await.unwrap().json().await.unwrap();assert_eq!(missing,Value::Null);
    let control=format!("{listing}/{}/control",task["id"].as_str().unwrap());let paused=http.post(&control).bearer_auth(HOST_TOKEN).json(&json!({"expected_version":1,"action":"pause"})).send().await.unwrap();assert_eq!(paused.status(),200);assert_eq!(paused.json::<Value>().await.unwrap()["reason"],"owner_pause");assert_eq!(http.post(&control).bearer_auth(HOST_TOKEN).json(&json!({"expected_version":1,"action":"resume"})).send().await.unwrap().status(),409);assert_eq!(http.post(&control).bearer_auth(HOST_TOKEN).json(&json!({"expected_version":2,"action":"submit"})).send().await.unwrap().status(),422);stop.cancel();server.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_tasks_explicit_profile_transfer_preserves_owner_pause_and_requires_fresh_tab_ownership() {
    let (mut c,context,packet)=browser_command_fixture().await;let task=browser_task_open(&mut c,&context,&packet).await;let paused=browser_task_event(&mut c,&context,&task,"pause",json!({})).await["data"]["task"].clone();
    let next=browser_context();browser_connect(&mut c,&next).await;browser_call(&mut c,BrowserRoute::Select,json!({"expected_version":1,"profile_binding_id":next["profile_binding_id"]})).await.unwrap();let transferred=browser_task_open(&mut c,&next,&packet).await;assert_eq!(transferred["id"],task["id"]);assert_eq!(transferred["profile_binding_id"],next["profile_binding_id"]);assert_eq!(transferred["browser_session_id"],next["browser_session_id"]);assert_eq!(transferred["state"],"PAUSED");assert_eq!(transferred["reason"],"owner_pause");assert_eq!(transferred["tab_id"],Value::Null);assert!(transferred["plan_id"].is_null());assert!(transferred["version"].as_i64().unwrap()>paused["version"].as_i64().unwrap());
    assert_eq!(browser_native(&mut c,"get_application_task",&context,json!({"task_id":task["id"]})).await.unwrap()["error_code"],"PROFILE_NOT_SELECTED");assert_eq!(browser_task_event(&mut c,&next,&transferred,"bind",json!({"tab_id":50})).await["error_code"],"extension_task_paused_or_cancelled");
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_tasks_two_open_requests_create_one_task_and_stale_binding_cannot_take_an_owned_tab() {
    let (mut c,context,packet)=browser_command_fixture().await;let mut other=connection().await;let (a,b)=tokio::join!(browser_native(&mut c,"open_application_task",&context,json!({"application_id":packet["id"]})),browser_native(&mut other,"open_application_task",&context,json!({"application_id":packet["id"]})));let a=a.unwrap();let b=b.unwrap();assert_eq!(a["data"]["task"],b["data"]["task"]);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'ext_task:')").fetch_one(&mut c).await.unwrap(),1);
    let task=a["data"]["task"].clone();let mut owned=task.clone();owned["id"]=json!(Uuid::new_v4());owned["application_id"]=json!(Uuid::new_v4());owned["job_id"]=json!(Uuid::new_v4());owned["tab_id"]=json!(50);let key=format!("ext_task:{}",owned["id"].as_str().unwrap());browser_save(&mut c,&key,owned).await;assert_eq!(browser_task_event(&mut c,&context,&task,"bind",json!({"tab_id":50})).await["error_code"],"extension_tab_already_owned");
    assert_eq!(browser_task_event(&mut c,&context,&task,"bind",json!({"tab_id":51,"expected_task_version":999})).await["error_code"],"extension_task_revision_conflict");
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_tasks_focus_pause_null_reason_stays_null_and_missing_plan_cannot_claim_fill_started() {
    let (mut c,context,packet)=browser_command_fixture().await;let mut task=browser_task_open(&mut c,&context,&packet).await;let key=format!("ext_task:{}",task["id"].as_str().unwrap());task["state"]=json!("PAUSED");task["browser_connection"]=json!("paused");task["tab_id"]=json!(50);browser_save(&mut c,&key,task.clone()).await;
    let result=browser_task_event(&mut c,&context,&task,"focus_lost",json!({})).await;assert_eq!(result["data"]["task"]["reason"],Value::Null);assert_eq!(result["data"]["task"]["version"],task["version"]);
    task["state"]=json!("FILLING");browser_save(&mut c,&key,task.clone()).await;assert_eq!(browser_task_event(&mut c,&context,&task,"fill_started",json!({})).await["error_code"],"extension_task_not_authorized");
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_tasks_long_open_rolls_back_its_task_when_the_original_remote_lease_expires() {
    let (mut c,context,packet)=browser_command_fixture().await;let queued=browser_call(&mut c,BrowserRoute::Enqueue,browser_enqueue_input(&context,&packet)).await.unwrap();let lease=browser_native(&mut c,"poll_chrome_command",&context,json!({})).await.unwrap()["data"]["command"].clone();let executing=browser_native(&mut c,"start_chrome_command",&context,browser_lease_command(&lease)).await.unwrap()["data"]["command"].clone();let key=format!("chr_cmd:{}",queued["id"].as_str().unwrap());
    sqlx::raw_sql("CREATE FUNCTION fixture_task_open_wait() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'ext_task:') THEN PERFORM pg_sleep(0.9); END IF; RETURN NEW; END $$; CREATE TRIGGER fixture_task_open_wait BEFORE INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_task_open_wait()").execute(&mut c).await.unwrap();sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{lease_expires_at}',to_jsonb(clock_timestamp()+interval '700 milliseconds')) WHERE key=$1").bind(&key).execute(&mut c).await.unwrap();
    let request_id=Uuid::new_v4();let mut request=browser_lease_command(&executing);request["application_id"]=packet["id"].clone();request["request_id"]=json!(request_id);let result=browser_native(&mut c,"open_application_task",&context,request).await.unwrap();assert_eq!(result["error_code"],"profile_command_expired","{result}");assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'ext_task:')").fetch_one(&mut c).await.unwrap(),0);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM agent_operations WHERE key=$1").bind(format!("extension_request:{BROWSER_EXTENSION}:{request_id}")).fetch_one(&mut c).await.unwrap(),0);assert_eq!(browser_pref(&mut c,&key).await["state"],"outcome_unknown");
    sqlx::raw_sql("DROP TRIGGER fixture_task_open_wait ON owner_preferences;DROP FUNCTION fixture_task_open_wait()").execute(&mut c).await.unwrap();
}
