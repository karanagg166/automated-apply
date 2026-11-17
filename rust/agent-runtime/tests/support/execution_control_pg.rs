//! Final-gate-only controller integration. Fictional native PostgreSQL; no browser/provider.
async fn execution_mutate(c:&mut PgConnection,route:automated_apply_agents::execution::Route<'_>,input:Value)->Result<Value>{automated_apply_agents::execution::dispatch_body(c,route,route.method(),None,input.to_string().as_bytes()).await}
async fn execution_control(c:&mut PgConnection,revision:i64,action:&str)->Result<Value>{execution_mutate(c,automated_apply_agents::execution::Route::Control,json!({"expected_revision":revision,"action":action})).await}
async fn execution_work(c:&mut PgConnection,stage:&str,status:&str,operation:&str)->String {let id=Uuid::new_v4();let key=format!("apply_work:{id}");browser_save(c,&key,json!({"id":id,"platform":"naukri","stage":stage,"status":status,"operation":operation,"reason":null,"revision":8,"lease_token":Uuid::new_v4(),"lease_until":"2099-01-01T00:00:00Z","admitted_actions":[{"fingerprint":"apply:retained-spent"}]})).await;key}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn execution_stop_quarantines_only_executing_writes_and_keeps_all_spent_admissions() {
    let mut c=browser_fixture().await;execution_seed_policy(&mut c).await;let write=execution_work(&mut c,"APPLYING","executing","apply").await;let read=execution_work(&mut c,"VERIFYING","executing","inspect_application").await;let uncertain=execution_work(&mut c,"SUBMISSION_UNKNOWN","unknown","apply").await;let unknown_before=browser_pref(&mut c,&uncertain).await;let budget=json!({"reservations":["first-spent","second-spent","third-spent"]});browser_save(&mut c,"apply_budget:naukri:2026-11-16",budget.clone()).await;
    for key in ["apply_search:naukri","apply_profile_sync:naukri"] {browser_save(&mut c,key,json!({"revision":5,"status":"executing","lease_token":"retained","lease_until":"2099-01-01T00:00:00Z","next_at":"2099-01-01T00:00:00Z","approved_summary":{"old_authority":true}})).await;}
    browser_save(&mut c,"naukri_automation",json!({"revision":44,"state":"RUNNING","policy":{"preserve":true}})).await;
    let stopped=execution_control(&mut c,162,"stop").await.unwrap();assert_eq!(stopped["revision"],163);assert_eq!(stopped["state"],"STOPPED");let value=browser_pref(&mut c,&write).await;assert_eq!(value["stage"],"SUBMISSION_UNKNOWN");assert_eq!(value["admitted_actions"][0]["fingerprint"],"apply:retained-spent");assert!(value["lease_token"].is_null());assert_eq!(browser_pref(&mut c,&read).await["stage"],"PAUSED");assert_eq!(browser_pref(&mut c,&uncertain).await,unknown_before);assert_eq!(browser_pref(&mut c,"apply_budget:naukri:2026-11-16").await,budget);assert_eq!(browser_pref(&mut c,"naukri_automation").await["revision"],45);assert!(browser_pref(&mut c,"apply_profile_sync:naukri").await.get("approved_summary").is_none());assert!(browser_pref(&mut c,"apply_search:naukri").await["next_at"].is_null());assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'apply_event:')").fetch_one(&mut c).await.unwrap(),2);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn execution_start_requires_current_mode_and_resumes_writes_only_into_fresh_inspection() {
    let mut c=browser_fixture().await;execution_seed_policy(&mut c).await;let pending=execution_work(&mut c,"READY_TO_APPLY","queued","apply").await;let unknown=execution_work(&mut c,"SUBMISSION_UNKNOWN","unknown","apply").await;execution_control(&mut c,162,"pause").await.unwrap();let before=browser_snapshot(&mut c).await;assert_eq!(execution_control(&mut c,163,"start").await.unwrap_err(),Failure("execution_mode_off"));assert_eq!(browser_snapshot(&mut c).await,before);
    browser_save(&mut c,"exec_config:naukri",json!({"mode":"ON_DEMAND"})).await;let running=execution_control(&mut c,163,"start").await.unwrap();assert_eq!(running["state"],"RUNNING");let resumed=browser_pref(&mut c,&pending).await;assert_eq!(resumed["stage"],"VERIFYING");assert_eq!(resumed["operation"],"inspect_application");assert_eq!(resumed["admitted_actions"][0]["fingerprint"],"apply:retained-spent");assert_eq!(browser_pref(&mut c,&unknown).await["stage"],"SUBMISSION_UNKNOWN");assert!(browser_snapshot(&mut c).await.get("naukri_automation").is_none());
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn execution_stop_fences_naukri_tasks_plans_and_commands_without_stopping_other_packets() {
    let(mut c,context,packet)=browser_command_fixture().await;let task=browser_task_open(&mut c,&context,&packet).await;sqlx::query("UPDATE jobs SET source_platform='naukri' WHERE id=$1").bind(packet["job_id"].as_str().unwrap().parse::<Uuid>().unwrap()).execute(&mut c).await.unwrap();execution_seed_policy(&mut c).await;
    let plan=format!("fill_plan:{}",Uuid::new_v4());browser_save(&mut c,&plan,json!({"application_id":packet["id"],"state":"authorized","approved_fields":["f1"],"expires_at":"2099-01-01T00:00:00Z"})).await;
    let command=format!("chr_cmd:{}",Uuid::new_v4());browser_save(&mut c,&command,json!({"application_id":packet["id"],"state":"executing","version":3})).await;let unrelated=format!("chr_cmd:{}",Uuid::new_v4());let other=json!({"application_id":Uuid::new_v4(),"state":"queued","version":7});browser_save(&mut c,&unrelated,other.clone()).await;
    let id=Uuid::new_v4();let legacy=format!("exec:{id}");browser_save(&mut c,&legacy,json!({"id":id,"job_id":packet["job_id"],"platform":"manual_ats","state":"SUBMITTING","revision":7,"fence":8,"lease_until":"2099-01-01T00:00:00Z"})).await;
    execution_control(&mut c,162,"stop").await.unwrap();let key=format!("ext_task:{}",task["id"].as_str().unwrap());let stopped=browser_pref(&mut c,&key).await;assert_eq!(stopped["state"],"PAUSED");assert_eq!(stopped["reason"],"global_stop");assert_eq!(stopped["browser_connection"],"paused");assert!(stopped["authorization_id"].is_null());assert_eq!(browser_pref(&mut c,&plan).await["state"],"read_only");assert_eq!(browser_pref(&mut c,&plan).await["approved_fields"],json!([]));assert_eq!(browser_pref(&mut c,&command).await["state"],"outcome_unknown");assert_eq!(browser_pref(&mut c,&unrelated).await,other);assert_eq!(browser_pref(&mut c,&legacy).await["state"],"SUBMISSION_UNKNOWN");assert_eq!(browser_pref(&mut c,&legacy).await["fence"],9);
    execution_control(&mut c,163,"pause").await.unwrap();assert_eq!(browser_pref(&mut c,&key).await["reason"],"global_stop");
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn execution_stop_ignores_large_unattempted_holds_without_rewriting_retained_history() {
    let mut c=browser_fixture().await;execution_seed_policy(&mut c).await;sqlx::query("INSERT INTO owner_preferences(key,value) SELECT 'apply_work:hold-'||i,jsonb_build_object('id',i,'platform','naukri','stage','NEEDS_INPUT','status','waiting','reason','applicant_count_requires_review','admitted_actions','[]'::jsonb,'packet_id',NULL,'lease_until',NULL,'facts',jsonb_build_object('description',repeat('Fictional retained description',128))) FROM generate_series(1,20002) i").execute(&mut c).await.unwrap();execution_control(&mut c,162,"stop").await.unwrap();assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'apply_event:')").fetch_one(&mut c).await.unwrap(),0);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'apply_work:') AND value->>'stage'='NEEDS_INPUT'").fetch_one(&mut c).await.unwrap(),20002);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn execution_control_write_ack_and_outbox_failure_roll_back_every_authority_change() {
    let mut c=browser_fixture().await;execution_seed_policy(&mut c).await;let _=execution_work(&mut c,"READY_TO_APPLY","queued","apply").await;let before=browser_snapshot(&mut c).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_exec_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.key='application_queue_policy' THEN RETURN NULL; END IF; RETURN NEW; END $$; CREATE TRIGGER fixture_exec_drop BEFORE UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_exec_drop()").execute(&mut c).await.unwrap();assert_eq!(execution_control(&mut c,162,"stop").await.unwrap_err(),Failure("execution_write_ack_failed"));assert_eq!(browser_snapshot(&mut c).await,before);sqlx::raw_sql("DROP TRIGGER fixture_exec_drop ON owner_preferences;DROP FUNCTION fixture_exec_drop()").execute(&mut c).await.unwrap();
    sqlx::raw_sql("CREATE FUNCTION fixture_exec_event_fail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'apply_event:') THEN RAISE EXCEPTION 'fictional event failure'; END IF; RETURN NEW; END $$; CREATE TRIGGER fixture_exec_event_fail BEFORE INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_exec_event_fail()").execute(&mut c).await.unwrap();assert_eq!(execution_control(&mut c,162,"stop").await.unwrap_err(),Failure("execution_database_error"));assert_eq!(browser_snapshot(&mut c).await,before);sqlx::raw_sql("DROP TRIGGER fixture_exec_event_fail ON owner_preferences;DROP FUNCTION fixture_exec_event_fail()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn execution_policy_edit_pauses_existing_queue_and_requests_filter_review_without_resetting_cap() {
    let mut c=browser_fixture().await;let mut config=execution_seed_policy(&mut c).await;config["state"]=json!("RUNNING");browser_save(&mut c,"application_queue_policy",config.clone()).await;let mut policy=config["policy"].clone();policy["platforms"]["naukri"]["skill_match_mode"]=json!("all");let saved=execution_mutate(&mut c,automated_apply_agents::execution::Route::Policy,json!({"expected_revision":162,"policy":policy})).await.unwrap();assert_eq!(saved["state"],"PAUSED");assert_eq!(saved["revision"],163);assert_eq!(saved["policy"]["platforms"]["naukri"]["supervised_submission_cap"],4);assert_eq!(browser_pref(&mut c,"apply_filter_recheck").await["status"],"pending");let recheck=browser_pref(&mut c,"apply_filter_recheck").await;policy["global_limits"]["daily_cap"]=json!(79);execution_mutate(&mut c,automated_apply_agents::execution::Route::Policy,json!({"expected_revision":163,"policy":policy})).await.unwrap();assert_eq!(browser_pref(&mut c,"apply_filter_recheck").await,recheck);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn execution_control_compare_and_swap_rechecks_after_waiting_for_owner_lock() {
    let mut c=browser_fixture().await;execution_seed_policy(&mut c).await;browser_save(&mut c,"agent_conversation:primary",json!({})).await;let mut second=connection().await;let (one,two)=tokio::join!(execution_control(&mut c,162,"stop"),execution_control(&mut second,162,"pause"));assert_eq!(usize::from(one.is_ok())+usize::from(two.is_ok()),1);let failure=one.err().or(two.err()).unwrap();assert_eq!(failure,Failure("queue_policy_revision_conflict"));assert_eq!(browser_pref(&mut c,"application_queue_policy").await["revision"],163);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn execution_control_http_requires_owner_and_valid_contract_before_changing_stop_revision() {
    let mut c=browser_fixture().await;execution_seed_policy(&mut c).await;let(url,stop,server)=http_fixture_values(browser_values()).await;let http=client();let endpoint=format!("{url}/api/v1/execution/queue/control");let data=json!({"expected_revision":162,"action":"stop"});assert_eq!(http.post(&endpoint).json(&data).send().await.unwrap().status(),401);assert_eq!(http.post(&endpoint).bearer_auth(HOST_TOKEN).header("x-agent-client",BROWSER_EXTENSION).json(&data).send().await.unwrap().status(),403);assert_eq!(http.post(&endpoint).bearer_auth(HOST_TOKEN).json(&json!({"expected_revision":162,"action":"start","extra_authority":true})).send().await.unwrap().status(),422);let done=http.post(&endpoint).bearer_auth(HOST_TOKEN).json(&data).send().await.unwrap();assert_eq!(done.status(),200);assert_eq!(done.json::<Value>().await.unwrap()["revision"],163);let stale=http.post(&endpoint).bearer_auth(HOST_TOKEN).json(&data).send().await.unwrap();assert_eq!(stale.status(),409);assert_eq!(stale.json::<Value>().await.unwrap()["detail"],"queue_policy_revision_conflict");let wrong=http.get(&endpoint).bearer_auth(HOST_TOKEN).send().await.unwrap();assert_eq!(wrong.status(),405);assert_eq!(wrong.headers().get("allow").unwrap(),"POST");stop.cancel();server.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn execution_automatic_requires_bound_worker_and_packet_evidence_and_scans_past_bad_history()
{
    let (mut c, work, account) = submission_fixture().await;
    let first = submission_observe(
        &mut c,
        &work,
        submission_report("fictional-history-document-one"),
    )
    .await
    .unwrap();
    let next = submission_reclaim(&mut c, &first).await;
    let confirmed = submission_observe(
        &mut c,
        &next,
        submission_report("fictional-history-document-two"),
    )
    .await
    .unwrap();
    let config = execution_seed_policy(&mut c).await;
    let mut policy = config["policy"].clone();
    policy["platforms"]["naukri"]["mode"] = json!("AUTOMATIC");
    let input = json!({"expected_revision":162,"policy":policy});
    let route = automated_apply_agents::execution::Route::Policy;
    let key = format!("apply_work:{}", work["id"].as_str().unwrap());
    let mut admission_only = confirmed.clone();
    admission_only["apply_dispatch_observation"] = Value::Null;
    browser_save(&mut c, &key, admission_only).await;
    assert_eq!(
        execution_mutate(&mut c, route, input.clone())
            .await
            .unwrap_err(),
        Failure("automatic_first_verified_worker_receipt_required")
    );
    browser_save(&mut c, &key, confirmed.clone()).await;
    browser_save(&mut c, "naukri_account_binding", json!({})).await;
    assert_eq!(
        execution_mutate(&mut c, route, input.clone())
            .await
            .unwrap_err(),
        Failure("approved_naukri_account_binding_required")
    );
    browser_save(&mut c, "naukri_account_binding", account.clone()).await;
    let receipt_key = "naukri_worker_receipt:123456789012";
    let original = browser_pref(&mut c, receipt_key).await;
    let mut drift = original.clone();
    drift["second_observation"]["evidence_sha256"] = json!("d".repeat(64));
    browser_save(&mut c, receipt_key, drift).await;
    assert_eq!(
        execution_mutate(&mut c, route, input.clone())
            .await
            .unwrap_err(),
        Failure("automatic_first_verified_worker_receipt_required")
    );
    browser_save(&mut c, receipt_key, original).await;
    for i in 0..15 {
        let req = format!("2234567890{i:02}");
        let other = Uuid::new_v4();
        browser_save(
            &mut c,
            &format!("apply_work:{other}"),
            json!({"id":other,"platform":"naukri","stage":"SUBMITTED_CONFIRMED"}),
        )
        .await;
        browser_save(&mut c, &format!("naukri_worker_receipt:{req}"),
            json!({"requisition":req,"queue_id":other,"account_sha256":account["account_sha256"],"worker_dispatched":true})).await;
    }
    let accepted = execution_mutate(&mut c, route, input).await.unwrap();
    assert_eq!(accepted["revision"], 163);
    assert_eq!(accepted["state"], "STOPPED");
    assert_eq!(browser_pref(&mut c, &key).await, confirmed);
    browser_save(
        &mut c,
        "chr_selection",
        json!({"version":3,"profile_binding_id":Uuid::new_v4()}),
    )
    .await;
    assert_eq!(
        execution_control(&mut c, 163, "start").await.unwrap_err(),
        Failure("naukri_account_binding_context_changed")
    );
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn execution_policy_changed_applicant_decision_resolves_existing_notice_without_inventing_counts() {
    let mut c=browser_fixture().await;let config=execution_seed_policy(&mut c).await;sqlx::raw_sql("CREATE TABLE IF NOT EXISTS owner_notifications(id uuid PRIMARY KEY,dedup_key varchar(200) UNIQUE NOT NULL,kind varchar(50) NOT NULL,title varchar(200) NOT NULL,body text NOT NULL,href varchar(200) NOT NULL,read_at timestamptz,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),updated_at timestamptz NOT NULL DEFAULT clock_timestamp());DELETE FROM owner_notifications").execute(&mut c).await.unwrap();let id=Uuid::new_v4();sqlx::query("INSERT INTO owner_notifications(id,dedup_key,kind,title,body,href) VALUES($1,'naukri_applicant_question:1000','automation_policy_question','Fictional question','Retain uncertain labels','/naukri')").bind(id).execute(&mut c).await.unwrap();
    let mut policy=config["policy"].clone();policy["global_limits"]["unknown_applicants"]=json!("allow_lower_bound");let saved=execution_mutate(&mut c,automated_apply_agents::execution::Route::Policy,json!({"expected_revision":162,"policy":policy})).await.unwrap();assert_eq!(saved["policy"]["global_limits"]["unknown_applicants"],"allow_lower_bound");assert_eq!(sqlx::query_scalar::<_,String>("SELECT kind FROM owner_notifications WHERE id=$1").bind(id).fetch_one(&mut c).await.unwrap(),"automation_policy_resolved");assert_eq!(browser_pref(&mut c,"apply_filter_recheck").await["fresh_reads"],0);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'apply_work:')").fetch_one(&mut c).await.unwrap(),0);
}
