// Actual native DTO/selected-profile broker fixtures; no browser/provider side effects.
fn native_queue_context(work:&Value)->Value{json!({"profile_binding_id":work["binding"]["profile_binding_id"],"profile_secret":"f".repeat(64),"browser_session_id":work["binding"]["browser_session_id"],"window_id":work["binding"]["window_id"]})}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_supervised_saved_listing_precedes_due_profile_and_search_reads() {
    let (mut connection, binding, _) = sync_fixture(json!(["summary"])).await;
    let mut config = browser_pref(&mut connection, "application_queue_policy").await;
    let setting = &mut config["policy"]["platforms"]["naukri"];
    setting["mode"] = json!("SUPERVISED");
    setting["owner_submission_authorized"] = json!(true);
    setting["sources"] = json!(["saved_verified_job", "naukri_ui_search"]);
    browser_save(&mut connection, "application_queue_policy", config).await;

    let listing = automated_apply_agents::execution::queue::enqueue(
        &mut connection,
        "https://www.naukri.com/job-listings-fictional-backend-engineer-0123456789",
        "saved_verified_job",
        None,
    )
    .await
    .unwrap();
    let context = native_queue_context(&json!({"binding": binding}));
    let poll = native_queue_call(
        &mut connection,
        &context,
        "poll_naukri_work",
        json!({}),
        &sync_resume_settings(),
    )
    .await
    .unwrap();
    let work = &poll["data"]["work"];
    assert_eq!(work["id"], listing["id"], "{poll}");
    assert_eq!(work["operation"], "inspect_job");
    assert_eq!(poll["data"]["submitted"], false);
    let reserved: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM owner_preferences WHERE starts_with(key, 'apply_budget:')",
    )
    .fetch_one(&mut connection)
    .await
    .unwrap();
    assert_eq!(reserved, 0);
}
async fn native_queue_call(c:&mut PgConnection,context:&Value,name:&str,extra:Value,resumes:&automated_apply_agents::private_resume::Settings)->Result<Value>{let mut command=context.clone();command["command"]=json!(name);command["request_id"]=json!(Uuid::new_v4());for(k,v)in extra.as_object().unwrap(){command[k]=v.clone();}let settings=browser_profiles::Settings::from_values(&browser_values()).unwrap();let answers=answer_settings();browser_profiles::dispatch(c,BrowserRoute::Native,"POST",command.to_string().as_bytes(),&settings,&packet_settings(),Some(browser_profiles::form_service::Services{answers:&answers,resumes})).await}
fn native_queue_step(work:&Value)->Value{json!({"work_id":work["id"],"expected_work_revision":work["revision"],"work_lease_token":work["lease_token"],"tab_id":50})}
async fn native_queue_fixture()->(PgConnection,Value,Value){let(mut c,inspection)=listing_fixture().await;execution_mutate(&mut c,automated_apply_agents::execution::Route::SyncPolicy,json!({"expected_revision":1,"policy":{"enabled":false}})).await.unwrap();let context=native_queue_context(&inspection);let mut queued=inspection.clone();queued["status"]=json!("queued");queued["lease_token"]=Value::Null;queued["lease_until"]=Value::Null;queued["binding"]=Value::Null;browser_save(&mut c,&format!("apply_work:{}",inspection["id"].as_str().unwrap()),queued).await;(c,context,inspection)}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_poll_bind_read_admit_check_and_listing_finish_use_actual_authenticated_contract(){
    let(mut c,context,_)=native_queue_fixture().await;let resumes=sync_resume_settings();let poll=native_queue_call(&mut c,&context,"poll_naukri_work",json!({}),&resumes).await.unwrap();assert_eq!(poll["ok"],true,"{poll}");let work=&poll["data"]["work"];assert_eq!(work["operation"],"inspect_job");assert!(work["binding"]["tab_id"].is_null());let bound=native_queue_call(&mut c,&context,"bind_naukri_work",native_queue_step(work),&resumes).await.unwrap();assert_eq!(bound["ok"],true,"{bound}");let work=&bound["data"]["work"];assert_eq!(work["binding"]["tab_id"],50);let admitted=native_queue_call(&mut c,&context,"admit_naukri_work",native_queue_step(work),&resumes).await.unwrap();assert_eq!(admitted["ok"],true,"{admitted}");let work=&admitted["data"]["work"];assert_eq!(work["status"],"executing");let check=native_queue_call(&mut c,&context,"check_naukri_work",native_queue_step(work),&resumes).await.unwrap();assert_eq!(check["data"]["work"]["revision"],work["revision"]);let mut finish=native_queue_step(work);finish["work_report"]=listing_report(work);let finished=native_queue_call(&mut c,&context,"finish_naukri_work",finish,&resumes).await.unwrap();assert_eq!(finished["ok"],true,"{finished}");assert_eq!(finished["data"]["continue"],false);assert_eq!(finished["data"]["work"]["operation"],"prepare");assert_eq!(finished["data"]["work"]["status"],"queued");assert_eq!(finished["data"]["submitted"],false);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'apply_budget:')").fetch_one(&mut c).await.unwrap(),0);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_status_is_read_only_under_owner_lock_and_retains_secret_and_history_redaction(){
    let(mut c,context,_)=native_queue_fixture().await;let resumes=sync_resume_settings();let before=browser_snapshot(&mut c).await;let mut other=connection().await;let mut held=other.begin().await.unwrap();sqlx::query("SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE").execute(&mut *held).await.unwrap();sqlx::query("SET lock_timeout='100ms'").execute(&mut c).await.unwrap();let status=native_queue_call(&mut c,&context,"naukri_queue_status",json!({}),&resumes).await.unwrap();assert_eq!(status["ok"],true,"{status}");assert_eq!(status["capability"],"naukri_queue_controls");assert_eq!(status["data"]["queue"]["state"],"RUNNING");assert!(!status.to_string().contains(&"f".repeat(64)));assert!(!status.to_string().contains("Fictional development role"));assert_eq!(browser_snapshot(&mut c).await,before);held.rollback().await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_wrong_secret_session_window_or_tab_does_not_claim_any_work(){
    let(mut c,context,_)=native_queue_fixture().await;let resumes=sync_resume_settings();let before=browser_snapshot(&mut c).await;
    for(field,value,error)in[("profile_secret",json!("e".repeat(64)),"PROFILE_OFFLINE"),("browser_session_id",json!(Uuid::new_v4()),"PROFILE_SESSION_CHANGED"),("window_id",json!(11),"queue_window_binding_changed"),("tab_id",json!(50),"queue_poll_without_tab_required")]{let mut extra=json!({});extra[field]=value;let result=native_queue_call(&mut c,&context,"poll_naukri_work",extra,&resumes).await.unwrap();assert_eq!(result["ok"],false,"{result}");assert_eq!(result["error_code"],error);assert_eq!(browser_snapshot(&mut c).await,before);}
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_stop_revokes_an_issued_lease_and_stale_admit_cannot_spend_budget(){
    let(mut c,context,_)=native_queue_fixture().await;let resumes=sync_resume_settings();let work=native_queue_call(&mut c,&context,"poll_naukri_work",json!({}),&resumes).await.unwrap()["data"]["work"].clone();let stopped=native_queue_call(&mut c,&context,"naukri_queue_control",json!({"queue_action":"stop","expected_queue_revision":162}),&resumes).await.unwrap();assert_eq!(stopped["ok"],true,"{stopped}");assert_eq!(stopped["data"]["queue"]["state"],"STOPPED");let before=browser_snapshot(&mut c).await;let stale=native_queue_call(&mut c,&context,"bind_naukri_work",native_queue_step(&work),&resumes).await.unwrap();assert_eq!(stale["error_code"],"queue_lease_lost");assert_eq!(browser_snapshot(&mut c).await,before);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'apply_budget:')").fetch_one(&mut c).await.unwrap(),0);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_poll_yields_to_legacy_work_and_an_existing_active_lease(){
    let(mut c,context,_)=native_queue_fixture().await;let resumes=sync_resume_settings();browser_save(&mut c,"chr_cmd:fictional-busy",json!({"state":"executing"})).await;let busy=native_queue_call(&mut c,&context,"poll_naukri_work",json!({}),&resumes).await.unwrap();assert!(busy["data"]["work"].is_null());assert_eq!(browser_pref(&mut c,"apply_consumer:naukri").await["busy"],true);browser_save(&mut c,"chr_cmd:fictional-busy",json!({"state":"completed"})).await;let claimed=native_queue_call(&mut c,&context,"poll_naukri_work",json!({}),&resumes).await.unwrap();assert!(claimed["data"]["work"].is_object());let again=native_queue_call(&mut c,&context,"poll_naukri_work",json!({}),&resumes).await.unwrap();assert!(again["data"]["work"].is_null());assert_eq!(browser_pref(&mut c,"apply_consumer:naukri").await["busy"],true);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_abandon_of_an_unattempted_read_preserves_backoff_and_cannot_become_an_apply(){
    let(mut c,context,_)=native_queue_fixture().await;let resumes=sync_resume_settings();let poll=native_queue_call(&mut c,&context,"poll_naukri_work",json!({}),&resumes).await.unwrap();let bound=native_queue_call(&mut c,&context,"bind_naukri_work",native_queue_step(&poll["data"]["work"]),&resumes).await.unwrap();let mut fields=native_queue_step(&bound["data"]["work"]);fields["work_report"]=json!({"kind":"needs_input","reason":"owner_platform_active"});let result=native_queue_call(&mut c,&context,"abandon_naukri_work",fields,&resumes).await.unwrap();assert_eq!(result["ok"],true,"{result}");assert_eq!(result["data"]["work"]["operation"],"inspect_job");assert_eq!(result["data"]["work"]["status"],"queued");let work=browser_pref(&mut c,&format!("apply_work:{}",result["data"]["work"]["id"].as_str().unwrap())).await;assert_eq!(work["admitted_actions"],json!([]));assert!(work["available_at"].is_string());
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_original_tab_loss_under_stop_closes_questions_and_never_refunds_or_replays_apply(){
    let(mut c,work,q,resumes)=queue_question_fixture().await;let context=native_queue_context(&work);let key=format!("apply_work:{}",work["id"].as_str().unwrap());let mut pending=work.clone();pending["form_pending"]=json!(true);browser_save(&mut c,&key,pending).await;let mut config=browser_pref(&mut c,"application_queue_policy").await;config["state"]=json!("STOPPED");browser_save(&mut c,"application_queue_policy",config).await;let extra=json!({"work_id":work["id"],"tab_id":50,"work_report":{"kind":"needs_input","reason":"original_questionnaire_tab_unavailable"}});let result=native_queue_call(&mut c,&context,"poll_naukri_work",extra.clone(),&resumes).await.unwrap();assert_eq!(result["ok"],true,"{result}");assert_eq!(result["data"]["form_loss_recorded"],true);assert_eq!(result["data"]["state_changed"],true);let lost=browser_pref(&mut c,&key).await;assert_eq!(lost["status"],"unknown");assert_eq!(lost["stage"],"SUBMISSION_UNKNOWN");assert_eq!(lost["admitted_actions"],work["admitted_actions"]);assert_eq!(lost["form_loss_observation"]["replay_authorized"],false);assert_eq!(browser_pref(&mut c,&format!("exec_q:{}",q["id"].as_str().unwrap())).await["state"],"closed_form_unavailable");let duplicate=native_queue_call(&mut c,&context,"poll_naukri_work",extra,&resumes).await.unwrap();assert_eq!(duplicate["data"]["state_changed"],false);assert_eq!(browser_pref(&mut c,&key).await,lost);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_suspended_webui_request_and_windowless_binding_never_return_navigation_authority(){
    let(mut c,context,_)=native_queue_fixture().await;let resumes=sync_resume_settings();let mut config=browser_pref(&mut c,"application_queue_policy").await;config["state"]=json!("STOPPED");browser_save(&mut c,"application_queue_policy",config).await;let metadata=json!({"kind":"open_extension_manager","request_id":Uuid::new_v4(),"expires_at":(chrono::Utc::now()+chrono::Duration::seconds(90)).to_rfc3339(),"binding":{"profile_binding_id":context["profile_binding_id"],"profile_version":2,"selection_version":1,"browser_session_id":context["browser_session_id"],"window_id":10,"tab_id":null}});browser_save(&mut c,"naukri_extension_maintenance",metadata.clone()).await;let result=native_queue_call(&mut c,&context,"poll_naukri_work",json!({}),&resumes).await.unwrap();assert_eq!(result["ok"],true,"{result}");assert!(result["data"]["maintenance"].is_null());assert!(result["data"]["work"].is_null());assert_eq!(browser_pref(&mut c,"naukri_extension_maintenance").await,metadata);let windowless=native_queue_call(&mut c,&context,"poll_naukri_work",json!({"window_id":null}),&resumes).await.unwrap();assert_eq!(windowless["error_code"],"queue_window_binding_changed");assert_eq!(browser_pref(&mut c,"naukri_extension_maintenance").await,metadata);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_dropped_work_ack_rolls_back_whole_poll_and_consumer_metadata(){
    let(mut c,context,_)=native_queue_fixture().await;let resumes=sync_resume_settings();let before=browser_snapshot(&mut c).await;sqlx::raw_sql("CREATE FUNCTION fixture_native_claim_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'apply_work:') AND NEW.value->>'status'='leased' THEN RETURN NULL; END IF; RETURN NEW; END $$;CREATE TRIGGER fixture_native_claim_drop BEFORE UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_native_claim_drop()").execute(&mut c).await.unwrap();assert_eq!(native_queue_call(&mut c,&context,"poll_naukri_work",json!({}),&resumes).await.unwrap_err(),Failure("execution_write_ack_failed"));assert_eq!(browser_snapshot(&mut c).await,before);sqlx::raw_sql("DROP TRIGGER fixture_native_claim_drop ON owner_preferences;DROP FUNCTION fixture_native_claim_drop()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_http_requires_host_auth_and_exact_configured_extension_before_queue_status(){
    let(_c,context,_)=native_queue_fixture().await;let(url,stop,server)=http_fixture_values(browser_values()).await;let endpoint=format!("{url}{}",browser_profiles::NATIVE);let mut command=context;command["request_id"]=json!(Uuid::new_v4());command["command"]=json!("naukri_queue_status");let http=client();assert_eq!(http.post(&endpoint).json(&command).send().await.unwrap().status(),403);assert_eq!(http.post(&endpoint).header("x-agent-client",BROWSER_EXTENSION).json(&command).send().await.unwrap().status(),401);assert_eq!(http.post(&endpoint).bearer_auth(HOST_TOKEN).header("x-agent-client","bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb").json(&command).send().await.unwrap().status(),403);let result=http.post(&endpoint).bearer_auth(HOST_TOKEN).header("x-agent-client",BROWSER_EXTENSION).json(&command).send().await.unwrap();assert_eq!(result.status(),200);let body:Value=result.json().await.unwrap();assert_eq!(body["ok"],true,"{body}");assert_eq!(body["data"]["queue"]["revision"],162);assert_eq!(body["data"]["submitted"],false);stop.cancel();server.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_automatic_start_still_requires_first_strict_current_worker_receipt(){
    let(mut c,context,_)=native_queue_fixture().await;let resumes=sync_resume_settings();let mut config=browser_pref(&mut c,"application_queue_policy").await;config["state"]=json!("STOPPED");config["policy"]["platforms"]["naukri"]["mode"]=json!("AUTOMATIC");browser_save(&mut c,"application_queue_policy",config).await;let before=browser_snapshot(&mut c).await;let denied=native_queue_call(&mut c,&context,"naukri_queue_control",json!({"queue_action":"start","expected_queue_revision":162}),&resumes).await.unwrap();assert_eq!(denied["error_code"],"automatic_first_verified_worker_receipt_required");assert_eq!(browser_snapshot(&mut c).await,before);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_profile_save_still_requires_durable_unknown_intent_and_independent_persistence_read(){
    let(mut c,binding,profile)=sync_fixture(json!(["summary"])).await;let synthetic=json!({"binding":binding});let context=native_queue_context(&synthetic);let resumes=sync_resume_settings();let poll=native_queue_call(&mut c,&context,"poll_naukri_work",json!({}),&resumes).await.unwrap();let work=&poll["data"]["work"];assert_eq!(work["operation"],"inspect_profile_sync");let bound=native_queue_call(&mut c,&context,"bind_naukri_work",native_queue_step(work),&resumes).await.unwrap();let admitted=native_queue_call(&mut c,&context,"admit_naukri_work",native_queue_step(&bound["data"]["work"]),&resumes).await.unwrap();let mut fields=native_queue_step(&admitted["data"]["work"]);fields["work_report"]=sync_report("PROFILE_OBSERVED","fictional-native-profile-one",json!({"summary":"Old fictional summary"}));let proposal=native_queue_call(&mut c,&context,"finish_naukri_work",fields,&resumes).await.unwrap();assert_eq!(proposal["ok"],true,"{proposal}");assert_eq!(proposal["data"]["work"]["operation"],"sync_profile");let save=native_queue_call(&mut c,&context,"admit_naukri_work",native_queue_step(&proposal["data"]["work"]),&resumes).await.unwrap();assert_eq!(save["ok"],true,"{save}");assert_eq!(browser_pref(&mut c,"apply_profile_sync:naukri").await["sync_attempt"]["outcome"],"UNKNOWN");assert_eq!(save["data"]["work"]["execution"]["approved_summary"],profile["summary"]);let mut fields=native_queue_step(&save["data"]["work"]);fields["work_report"]=sync_report("PROFILE_SAVE_ATTEMPTED","fictional-native-profile-one",json!({}));let reloading=native_queue_call(&mut c,&context,"finish_naukri_work",fields,&resumes).await.unwrap();let reading=native_queue_call(&mut c,&context,"admit_naukri_work",native_queue_step(&reloading["data"]["work"]),&resumes).await.unwrap();let mut fields=native_queue_step(&reading["data"]["work"]);fields["work_report"]=sync_report("PROFILE_OBSERVED","fictional-native-profile-two",json!({"summary":profile["summary"]}));let finished=native_queue_call(&mut c,&context,"finish_naukri_work",fields,&resumes).await.unwrap();assert_eq!(finished["ok"],true,"{finished}");assert_eq!(finished["data"]["continue"],false);assert_eq!(browser_pref(&mut c,"apply_profile_sync:naukri").await["previous_verified_attempt"]["outcome"],"SYNC_VERIFIED");assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'apply_budget:') OR starts_with(key,'naukri_worker_receipt:')").fetch_one(&mut c).await.unwrap(),0);
}
