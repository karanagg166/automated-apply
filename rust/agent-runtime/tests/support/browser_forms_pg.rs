// Source-phase regressions: fictional profile, isolated PostgreSQL, no browser/provider IO.
fn browser_form_values()->BTreeMap<String,String> {
    let mut values=browser_values();values.insert("BROWSER_FILL_ENABLED".into(),"true".into());values
}
async fn browser_form_call(c:&mut PgConnection,route:BrowserRoute,input:Value)->Result<Value> {
    let values=browser_form_values();
    let profiles=browser_profiles::Settings::from_values(&values).unwrap();
    let answers=answer_settings();
    let resumes=automated_apply_agents::private_resume::Settings::from_values(&values).unwrap();
    browser_profiles::dispatch(c,route,route.method(),input.to_string().as_bytes(),&profiles,&packet_settings(),Some(browser_profiles::form_service::Services{answers:&answers,resumes:&resumes})).await
}
async fn browser_form_native(c:&mut PgConnection,name:&str,context:&Value,extra:Value)->Result<Value> {
    let mut value=context.clone();value["command"]=json!(name);value["request_id"]=json!(Uuid::new_v4());value["tab_id"]=json!(50);
    for(k,v)in extra.as_object().unwrap(){value[k]=v.clone();}
    browser_form_call(c,BrowserRoute::Native,value).await
}
fn browser_form_observation(packet:&Value)->Value {
    json!({"document_id":Uuid::new_v4(),"url":packet["snapshot"]["original_job_url"],"fields":[{"field_id":"f1","kind":"text","label":"Full name","required":true}]})
}
async fn browser_form_inspect(c:&mut PgConnection,context:&Value,packet:&Value,extra:Value)->Value {
    let mut value=json!({"application_id":packet["id"],"inspection":browser_form_observation(packet)});for(k,v)in extra.as_object().unwrap(){value[k]=v.clone();}
    let result=browser_form_native(c,"inspect_form",context,value).await.unwrap();assert_eq!(result["ok"],true,"{result}");assert_eq!(result["capability"],"form_fill");result["data"].clone()
}
async fn browser_form_authorize(c:&mut PgConnection,context:&Value,plan:&Value,extra:Value)->Value {
    let mut value=json!({"plan_id":plan["id"],"field_ids":["f1"]});for(k,v)in extra.as_object().unwrap(){value[k]=v.clone();}
    browser_form_native(c,"authorize_form",context,value).await.unwrap()
}
fn browser_form_receipt(plan:&Value)->Value {
    json!({"plan_id":plan["id"],"results":[{"field_id":"f1","status":"filled"}],"state":"form_filled","verification_method":"retained_after_blur","network_guard_active":true})
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_forms_inspection_exact_review_consumption_receipt_and_no_replay() {
    let(mut c,context,packet)=browser_command_fixture().await;
    let data=browser_form_inspect(&mut c,&context,&packet,json!({})).await;let plan=&data["plan"];
    assert_eq!(plan["state"],"preview");assert_eq!(plan["actions"][0]["value"],"Fictional Person");assert_eq!(plan["actions"][0]["needs_input"],false);assert_eq!(plan["profile_binding_id"],context["profile_binding_id"]);assert_eq!(data["submitted"],false);
    let denied=browser_form_authorize(&mut c,&context,plan,json!({"field_ids":["f1","f1"]})).await;assert_eq!(denied["ok"],false);
    let authorized=browser_form_authorize(&mut c,&context,plan,json!({})).await;assert_eq!(authorized["ok"],true,"{authorized}");assert_eq!(authorized["data"]["plan"]["state"],"consumed");
    assert_eq!(browser_form_authorize(&mut c,&context,plan,json!({})).await["ok"],false);
    let receipt=browser_form_receipt(plan);let first=browser_form_native(&mut c,"record_form_fill",&context,json!({"receipt":receipt})).await.unwrap();assert_eq!(first["data"]["status"],"form_filled");assert_eq!(first["data"]["submitted"],false);
    let again=browser_form_native(&mut c,"record_form_fill",&context,json!({"receipt":receipt})).await.unwrap();assert_eq!(again["data"]["status"],"already_recorded");
    let saved=browser_pref(&mut c,&format!("ext_receipt:{}",plan["id"].as_str().unwrap())).await;assert_eq!(saved["submitted"],false);assert_eq!(saved["profile_binding_id"],context["profile_binding_id"]);
    let list=browser_form_call(&mut c,BrowserRoute::Plans,Value::Null).await.unwrap();assert_eq!(list[0]["state"],"finished");
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_forms_nonce_is_single_use_and_denial_rolls_back_all_generated_records() {
    let(mut c,context,packet)=browser_command_fixture().await;let request=Uuid::new_v4();let observation=browser_form_observation(&packet);
    let extra=json!({"application_id":packet["id"],"inspection":observation,"request_id":request});let result=browser_form_native(&mut c,"inspect_form",&context,extra.clone()).await.unwrap();assert_eq!(result["ok"],true);
    assert_eq!(browser_form_native(&mut c,"inspect_form",&context,extra.clone()).await.unwrap()["error_code"],"form_request_already_consumed");
    let mut changed=extra;changed["inspection"]["has_next"]=json!(true);assert_eq!(browser_form_native(&mut c,"inspect_form",&context,changed).await.unwrap()["error_code"],"native_request_conflict");
    let before=browser_snapshot(&mut c).await;let mut observation=browser_form_observation(&packet);observation["fields"]=json!([{"field_id":"f1","kind":"text","label":"Current location","required":true}]);
    let denied=browser_form_native(&mut c,"inspect_form",&context,json!({"application_id":packet["id"],"inspection":observation,"tab_id":null})).await.unwrap();assert_eq!(denied["error_code"],"extension_tab_binding_mismatch");assert_eq!(browser_snapshot(&mut c).await,before);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_forms_unknown_required_question_is_bridged_once_with_final_revision() {
    let(mut c,context,packet)=browser_command_fixture().await;let mut observation=browser_form_observation(&packet);observation["fields"]=json!([{"field_id":"f1","kind":"text","label":"Preferred shift rotation?","required":true}]);
    let data=browser_form_inspect(&mut c,&context,&packet,json!({"inspection":observation})).await;assert_eq!(data["plan"]["actions"][0]["needs_input"],true);let revision=data["plan"]["packet_revision"].as_i64().unwrap();assert!(revision>packet["revision"].as_i64().unwrap());
    let count:i64=sqlx::query_scalar("SELECT count(*) FROM application_packet_fields WHERE packet_id=$1 AND question='Preferred shift rotation?'").bind(packet["id"].as_str().unwrap().parse::<Uuid>().unwrap()).fetch_one(&mut c).await.unwrap();assert_eq!(count,1);
    let second=browser_form_inspect(&mut c,&context,&packet,json!({"inspection":observation})).await;assert_eq!(second["plan"]["packet_revision"],revision);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'exec_q:')").fetch_one(&mut c).await.unwrap(),0);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_forms_sensitive_and_challenge_controls_never_receive_a_fill_value() {
    let(mut c,context,packet)=browser_command_fixture().await;let mut observation=browser_form_observation(&packet);observation["fields"]=json!([{"field_id":"f1","kind":"text","label":"Government ID","required":true},{"field_id":"f2","kind":"text","label":"API token","required":true}]);observation["challenge_state"]=json!("WIDGET_PRESENT_UNVERIFIED");
    let data=browser_form_inspect(&mut c,&context,&packet,json!({"inspection":observation})).await;assert_eq!(data["plan"]["state"],"read_only");assert!(data["plan"]["actions"].as_array().unwrap().iter().all(|a|a["needs_input"]==true && a["value"].is_null()));assert_eq!(browser_form_authorize(&mut c,&context,&data["plan"],json!({})).await["ok"],false);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_forms_task_receipt_reaches_review_state_without_claiming_a_submission() {
    let(mut c,context,packet)=browser_command_fixture().await;let task=browser_task_open(&mut c,&context,&packet).await;let task=browser_task_event(&mut c,&context,&task,"bind",json!({"tab_id":50})).await["data"]["task"].clone();
    let data=browser_form_inspect(&mut c,&context,&packet,json!({"task_id":task["id"],"expected_task_version":task["version"]})).await;let task=&data["task"];assert_eq!(task["state"],"FORM_INSPECTED");assert_eq!(task["counts"]["ready"],1);
    let authorized=browser_form_authorize(&mut c,&context,&data["plan"],json!({"task_id":task["id"],"expected_task_version":task["version"]})).await;assert_eq!(authorized["ok"],true,"{authorized}");let task=&authorized["data"]["task"];assert_eq!(task["state"],"FILLING");
    let receipt=browser_form_native(&mut c,"record_form_fill",&context,json!({"task_id":task["id"],"expected_task_version":task["version"],"receipt":browser_form_receipt(&data["plan"])})).await.unwrap();assert_eq!(receipt["ok"],true,"{receipt}");assert_eq!(receipt["data"]["task"]["state"],"READY_FOR_SUBMISSION");assert_eq!(receipt["data"]["submitted"],false);assert_eq!(receipt["data"]["task"]["capabilities"]["reviewed_submission"],false);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_forms_late_receipt_keeps_original_binding_without_changing_transferred_task() {
    let(mut c,context,packet)=browser_command_fixture().await;let task=browser_task_open(&mut c,&context,&packet).await;let task=browser_task_event(&mut c,&context,&task,"bind",json!({"tab_id":50})).await["data"]["task"].clone();let data=browser_form_inspect(&mut c,&context,&packet,json!({"task_id":task["id"],"expected_task_version":task["version"]})).await;let task=&data["task"];
    let result=browser_form_authorize(&mut c,&context,&data["plan"],json!({"task_id":task["id"],"expected_task_version":task["version"]})).await;assert_eq!(result["ok"],true,"{result}");let mut transferred=result["data"]["task"].clone();transferred["profile_binding_id"]=json!(Uuid::new_v4());transferred["state"]=json!("PAUSED");transferred["reason"]=json!("owner_pause");let key=format!("ext_task:{}",task["id"].as_str().unwrap());browser_save(&mut c,&key,transferred.clone()).await;
    let result=browser_form_native(&mut c,"record_form_fill",&context,json!({"task_id":task["id"],"receipt":browser_form_receipt(&data["plan"])})).await.unwrap();assert_eq!(result["data"]["status"],"historical_receipt_recorded");assert_eq!(browser_pref(&mut c,&key).await,transferred);assert_eq!(result["data"]["original_profile_binding_id"],context["profile_binding_id"]);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_forms_review_rechecks_expiry_packet_and_candidate_context() {
    let(mut c,context,packet)=browser_command_fixture().await;let data=browser_form_inspect(&mut c,&context,&packet,json!({})).await;let mut plan=data["plan"].clone();let key=format!("fill_plan:{}",plan["id"].as_str().unwrap());plan["expires_at"]=json!("2000-01-01T00:00:00Z");browser_save(&mut c,&key,plan.clone()).await;assert_eq!(browser_form_authorize(&mut c,&context,&plan,json!({})).await["error_code"],"fill_plan_stale");
    let plan=browser_form_inspect(&mut c,&context,&packet,json!({})).await["plan"].clone();sqlx::query("UPDATE candidate_profiles SET full_name='Updated fictional identity' WHERE singleton_key='primary'").execute(&mut c).await.unwrap();let denied=browser_form_authorize(&mut c,&context,&plan,json!({})).await;assert_eq!(denied["ok"],false);assert_eq!(browser_pref(&mut c,&format!("fill_plan:{}",plan["id"].as_str().unwrap())).await["state"],"preview");
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_forms_unapproved_fields_and_partial_receipts_cannot_claim_complete_fill() {
    let(mut c,context,packet)=browser_command_fixture().await;let plan=browser_form_inspect(&mut c,&context,&packet,json!({})).await["plan"].clone();assert_eq!(browser_form_authorize(&mut c,&context,&plan,json!({"field_ids":["f2"]})).await["ok"],false);assert_eq!(browser_form_authorize(&mut c,&context,&plan,json!({})).await["ok"],true);
    let mut receipt=browser_form_receipt(&plan);receipt["results"][0]["field_id"]=json!("f2");let denied=browser_form_native(&mut c,"record_form_fill",&context,json!({"receipt":receipt})).await.unwrap();assert_eq!(denied["ok"],false);
    receipt["results"]=json!([]);let partial=browser_form_native(&mut c,"record_form_fill",&context,json!({"receipt":receipt})).await.unwrap();assert_eq!(partial["data"]["status"],"needs_input");assert_eq!(partial["data"]["submitted"],false);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_forms_suppressed_write_ack_rolls_back_plan_task_and_all_audits() {
    let(mut c,context,packet)=browser_command_fixture().await;let before=browser_snapshot(&mut c).await;let count:i64=sqlx::query_scalar("SELECT count(*) FROM agent_operations").fetch_one(&mut c).await.unwrap();
    sqlx::raw_sql("CREATE FUNCTION fixture_form_suppress() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'fill_plan:') THEN RETURN NULL; END IF; RETURN NEW; END $$;CREATE TRIGGER fixture_form_suppress BEFORE INSERT OR UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_form_suppress()").execute(&mut c).await.unwrap();
    let error=browser_form_native(&mut c,"inspect_form",&context,json!({"application_id":packet["id"],"inspection":browser_form_observation(&packet)})).await.unwrap_err();assert_eq!(error,Failure("browser_profile_write_ack_failed"));assert_eq!(browser_snapshot(&mut c).await,before);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM agent_operations").fetch_one(&mut c).await.unwrap(),count);
    sqlx::raw_sql("DROP TRIGGER fixture_form_suppress ON owner_preferences;DROP FUNCTION fixture_form_suppress()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_forms_execution_fill_history_and_outbox_match_existing_format() {
    let(mut c,context,packet)=browser_command_fixture().await;let id=Uuid::new_v4();let key=format!("exec:{id}");browser_save(&mut c,&key,json!({"id":id,"packet_id":packet["id"],"state":"PREPARING","revision":3,"history":[],"evidence":[],"cancelled":false,"question_only":false})).await;
    let plan=browser_form_inspect(&mut c,&context,&packet,json!({})).await["plan"].clone();let authorized=browser_form_authorize(&mut c,&context,&plan,json!({})).await;assert_eq!(authorized["ok"],true,"{authorized}");let execution=browser_pref(&mut c,&key).await;assert_eq!(execution["diagnostic"],"fill_authorized");assert_eq!(execution["history"][0],json!({"from":"PREPARING","to":"FILLING","reason":"fill_authorized"}));let event=Uuid::new_v5(&Uuid::NAMESPACE_URL,format!("{id}:4:state_changed").as_bytes());assert_eq!(browser_pref(&mut c,&format!("exec_event:{event}")).await["event"],"state_changed");
    let result=browser_form_native(&mut c,"record_form_fill",&context,json!({"receipt":browser_form_receipt(&plan)})).await.unwrap();assert_eq!(result["ok"],true,"{result}");let execution=browser_pref(&mut c,&key).await;assert_eq!(execution["state"],"READY_FOR_REVIEW");assert_eq!(execution["revision"],5);assert!(execution["lease_until"].is_null());
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_forms_owner_http_routes_keep_native_headers_out_and_reject_foreign_origin() {
    let(mut c,context,packet)=browser_command_fixture().await;let plan=browser_form_inspect(&mut c,&context,&packet,json!({})).await["plan"].clone();let(url,stop,server)=http_fixture_values(browser_form_values()).await;let http=client();let endpoint=format!("{url}/api/v1/browser/plans/{}/review",plan["id"].as_str().unwrap());
    let denied=http.post(&endpoint).bearer_auth(HOST_TOKEN).header("origin","https://untrusted.example.net").json(&json!({"field_ids":["f1"]})).send().await.unwrap();assert_eq!(denied.status(),403);
    let reviewed=http.post(&endpoint).bearer_auth(HOST_TOKEN).json(&json!({"field_ids":["f1"]})).send().await.unwrap();let status=reviewed.status();let reviewed:Value=reviewed.json().await.unwrap();assert_eq!(status,200,"{reviewed}");assert_eq!(reviewed["state"],"authorized");
    let denied=http.get(format!("{url}/api/v1/browser/plans")).bearer_auth(HOST_TOKEN).header("x-agent-client",BROWSER_EXTENSION).send().await.unwrap();assert_eq!(denied.status(),403);stop.cancel();server.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_forms_contextual_questions_bind_siblings_to_final_revision_and_never_execute() {
    let(mut c,context,packet)=browser_command_fixture().await;let task=browser_task_open(&mut c,&context,&packet).await;let task=browser_task_event(&mut c,&context,&task,"bind",json!({"tab_id":50})).await["data"]["task"].clone();
    let mut observation=browser_form_observation(&packet);observation["fields"]=json!([{"field_id":"f1","kind":"date","label":"Start date","section":"Employment entry one","semantic_key":"a".repeat(64),"required":true},{"field_id":"f2","kind":"date","label":"Start date","section":"Employment entry two","semantic_key":"b".repeat(64),"required":true}]);
    let data=browser_form_inspect(&mut c,&context,&packet,json!({"task_id":task["id"],"expected_task_version":task["version"],"inspection":observation})).await;let task=&data["task"];
    let asked=browser_form_native(&mut c,"ask_form_questions",&context,json!({"task_id":task["id"],"expected_task_version":task["version"]})).await.unwrap();assert_eq!(asked["ok"],true,"{asked}");assert_eq!(asked["capability"],"extension_task");let data=&asked["data"];let task=&data["task"];assert!(task["plan_id"].is_null());assert_eq!(task["state"],"NEEDS_INPUT");let questions=data["questions"].as_array().unwrap();assert_eq!(questions.len(),2);assert_ne!(questions[0]["question"],questions[1]["question"]);
    for q in questions {assert_eq!(q["packet_revision"],task["packet_revision"]);assert_eq!(q["state"],"pending");assert_eq!(q["message_ids"],json!([]));assert_eq!(q["reuse_approved"],false);assert_eq!(q["extension_task_id"],task["id"]);let execution=browser_pref(&mut c,&format!("exec:{}",q["execution_id"].as_str().unwrap())).await;assert_eq!(execution["question_only"],true);assert_eq!(execution["attempts"],0);assert!(execution["lease_until"].is_null());}
    assert_eq!(data["submitted"],false);assert_eq!(browser_form_native(&mut c,"ask_form_questions",&context,json!({"task_id":task["id"],"expected_task_version":task["version"]})).await.unwrap()["error_code"],"fresh_form_inspection_required");
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_forms_question_queue_rejects_owner_pause_and_leaves_records_unchanged() {
    let(mut c,context,packet)=browser_command_fixture().await;let task=browser_task_open(&mut c,&context,&packet).await;let task=browser_task_event(&mut c,&context,&task,"bind",json!({"tab_id":50})).await["data"]["task"].clone();let mut observation=browser_form_observation(&packet);observation["fields"]=json!([{"field_id":"f1","kind":"text","label":"Preferred shift rotation?","required":true}]);let data=browser_form_inspect(&mut c,&context,&packet,json!({"task_id":task["id"],"expected_task_version":task["version"],"inspection":observation})).await;let task=&data["task"];
    let paused=browser_task_event(&mut c,&context,task,"pause",json!({})).await["data"]["task"].clone();let before=browser_snapshot(&mut c).await;let result=browser_form_native(&mut c,"ask_form_questions",&context,json!({"task_id":paused["id"],"expected_task_version":paused["version"]})).await.unwrap();assert_eq!(result["error_code"],"extension_task_paused_or_cancelled");assert_eq!(browser_snapshot(&mut c).await,before);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_forms_long_inspection_expires_original_lease_and_rolls_back_its_new_plan() {
    let(mut c,context,packet)=browser_command_fixture().await;let queued=browser_call(&mut c,BrowserRoute::Enqueue,browser_enqueue_input(&context,&packet)).await.unwrap();let lease=browser_native(&mut c,"poll_chrome_command",&context,json!({})).await.unwrap()["data"]["command"].clone();let executing=browser_native(&mut c,"start_chrome_command",&context,browser_lease_command(&lease)).await.unwrap()["data"]["command"].clone();let key=format!("chr_cmd:{}",queued["id"].as_str().unwrap());
    sqlx::raw_sql("CREATE FUNCTION fixture_form_wait() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'fill_plan:') THEN PERFORM pg_sleep(0.9); END IF; RETURN NEW; END $$;CREATE TRIGGER fixture_form_wait BEFORE INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_form_wait()").execute(&mut c).await.unwrap();sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{lease_expires_at}',to_jsonb(clock_timestamp()+interval '700 milliseconds')) WHERE key=$1").bind(&key).execute(&mut c).await.unwrap();
    let mut extra=browser_lease_command(&executing);extra["application_id"]=packet["id"].clone();extra["inspection"]=browser_form_observation(&packet);let request=Uuid::new_v4();extra["request_id"]=json!(request);let result=browser_form_native(&mut c,"inspect_form",&context,extra).await.unwrap();assert_eq!(result["error_code"],"profile_command_expired","{result}");assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'fill_plan:')").fetch_one(&mut c).await.unwrap(),0);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM agent_operations WHERE key=$1").bind(format!("manual_form:{BROWSER_EXTENSION}:{request}")).fetch_one(&mut c).await.unwrap(),0);assert_eq!(browser_pref(&mut c,&key).await["state"],"outcome_unknown");
    sqlx::raw_sql("DROP TRIGGER fixture_form_wait ON owner_preferences;DROP FUNCTION fixture_form_wait()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_forms_commit_failure_is_unknown_and_reconnection_never_replays_the_request() {
    let(mut c,context,packet)=browser_command_fixture().await;let before=browser_snapshot(&mut c).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_form_commit_fail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'fill_plan:') THEN RAISE EXCEPTION 'fictional deferred failure'; END IF; RETURN NEW; END $$;CREATE CONSTRAINT TRIGGER fixture_form_commit_fail AFTER INSERT ON owner_preferences DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fixture_form_commit_fail()").execute(&mut c).await.unwrap();
    let error=browser_form_native(&mut c,"inspect_form",&context,json!({"application_id":packet["id"],"inspection":browser_form_observation(&packet)})).await.unwrap_err();assert_eq!(error,Failure("browser_profile_commit_outcome_unknown"));let mut observer=connection().await;assert_eq!(browser_snapshot(&mut observer).await,before);sqlx::raw_sql("DROP TRIGGER fixture_form_commit_fail ON owner_preferences;DROP FUNCTION fixture_form_commit_fail()").execute(&mut observer).await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_forms_paused_question_only_context_cannot_authorize_a_browser_fill() {
    let(mut c,context,packet)=browser_command_fixture().await;let plan=browser_form_inspect(&mut c,&context,&packet,json!({})).await["plan"].clone();let id=Uuid::new_v4();browser_save(&mut c,&format!("exec:{id}"),json!({"id":id,"packet_id":packet["id"],"state":"PAUSED","revision":2,"history":[],"evidence":[],"cancelled":false,"question_only":true})).await;
    let result=browser_form_authorize(&mut c,&context,&plan,json!({})).await;assert_eq!(result["error_code"],"execution_paused_or_cancelled");assert_eq!(browser_pref(&mut c,&format!("fill_plan:{}",plan["id"].as_str().unwrap())).await["state"],"preview");
}
