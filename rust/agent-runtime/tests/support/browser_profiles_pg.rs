use automated_apply_agents::browser_profiles::{self,Route as BrowserRoute};
const BROWSER_EXTENSION:&str="gdjbmkffcpicbpiikcohlmokkmcpipgp";
fn browser_values()->BTreeMap<String,String> {
    let mut v=host_values();v.insert("CHROME_EXTENSION_ID".into(),BROWSER_EXTENSION.into());v.insert("CHROME_NATIVE_MESSAGING_ENABLED".into(),"true".into());v.insert("CHROME_PROFILE_COMMANDS_ENABLED".into(),"true".into());v
}
async fn browser_fixture()->PgConnection {
    let mut c=knowledge_fixture().await;
    sqlx::raw_sql("CREATE TABLE IF NOT EXISTS owner_preferences(key varchar(50) PRIMARY KEY,value jsonb NOT NULL); ALTER TABLE owner_preferences ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT clock_timestamp(), ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT clock_timestamp(); DELETE FROM owner_preferences; CREATE TABLE IF NOT EXISTS agent_operations(key varchar(180) PRIMARY KEY,actor varchar(120) NOT NULL,command varchar(50) NOT NULL,payload_hash varchar(64) NOT NULL,result jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp()); DELETE FROM agent_operations;").execute(&mut c).await.unwrap();c
}
async fn browser_call(c:&mut PgConnection,route:BrowserRoute,input:Value)->Result<Value> {
    browser_profiles::dispatch(c,route,route.method(),input.to_string().as_bytes(),&browser_profiles::Settings::from_values(&browser_values()).unwrap()).await
}
fn browser_context()->Value {json!({"profile_binding_id":Uuid::new_v4(),"profile_secret":"f".repeat(64),"browser_session_id":Uuid::new_v4(),"window_id":10})}
async fn browser_native(c:&mut PgConnection,name:&str,context:&Value,updates:Value)->Result<Value> {
    let mut input=context.clone();input["command"]=json!(name);input["request_id"]=json!(Uuid::new_v4());
    for (k,v) in updates.as_object().unwrap(){input[k]=v.clone();}
    browser_call(c,BrowserRoute::Native,input).await
}
async fn browser_connect(c:&mut PgConnection,context:&Value)->Value {let r=browser_native(c,"connect_chrome_profile",context,json!({"profile_label":"Fictional Brave"})).await.unwrap();assert_eq!(r["ok"],true,"{r}");r["data"]["profile"].clone()}
async fn browser_pref(c:&mut PgConnection,key:&str)->Value {sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1").bind(key).fetch_one(c).await.unwrap()}
async fn browser_save(c:&mut PgConnection,key:&str,value:Value) {sqlx::query("INSERT INTO owner_preferences(key,value) VALUES($1,$2) ON CONFLICT(key) DO UPDATE SET value=excluded.value").bind(key).bind(value).execute(c).await.unwrap();}
async fn browser_snapshot(c:&mut PgConnection)->Value {sqlx::query_scalar("SELECT coalesce(jsonb_object_agg(key,value),'{}') FROM owner_preferences").fetch_one(c).await.unwrap()}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_profiles_native_connect_authenticate_select_and_windowless_is_never_available() {
    let mut c=browser_fixture().await;let context=browser_context();let profile=browser_connect(&mut c,&context).await;
    assert_eq!(profile["version"],1);assert_eq!(profile["commands_enabled"],false);assert_eq!(profile["selected"],false);assert!(!profile.to_string().contains(&"f".repeat(64)));
    browser_call(&mut c,BrowserRoute::Select,json!({"expected_version":0,"profile_binding_id":context["profile_binding_id"]})).await.unwrap();
    let enabled=browser_native(&mut c,"heartbeat_chrome_profile",&context,json!({"profile_commands_enabled":true})).await.unwrap();assert_eq!(enabled["data"]["profile"]["version"],2);
    let same=browser_native(&mut c,"heartbeat_chrome_profile",&context,json!({"profile_commands_enabled":true})).await.unwrap();assert_eq!(same["data"]["profile"]["version"],2);
    let before=browser_snapshot(&mut c).await;
    let bad=browser_native(&mut c,"heartbeat_chrome_profile",&context,json!({"profile_secret":"e".repeat(64)})).await.unwrap();assert_eq!(bad["error_code"],"PROFILE_OFFLINE");assert_eq!(browser_snapshot(&mut c).await,before);
    let conflict=browser_native(&mut c,"connect_chrome_profile",&context,json!({"profile_secret":"e".repeat(64),"profile_label":"Imposter"})).await.unwrap();assert_eq!(conflict["error_code"],"profile_identity_conflict");assert_eq!(browser_snapshot(&mut c).await,before);
    let windowless=browser_native(&mut c,"heartbeat_chrome_profile",&context,json!({"window_id":null,"profile_commands_enabled":true})).await.unwrap();assert_eq!(windowless["data"]["background_window_allowed"],false);assert_eq!(windowless["data"]["profile"]["status"],"PROFILE_OFFLINE");assert_eq!(windowless["data"]["profile"]["version"],3);
    let disconnected=browser_call(&mut c,BrowserRoute::Disconnect(context["profile_binding_id"].as_str().unwrap().parse().unwrap()),json!({"expected_version":3})).await.unwrap();assert_eq!(disconnected["disconnected"],true);
    let listing=browser_call(&mut c,BrowserRoute::List,Value::Null).await.unwrap();assert_eq!(listing["selection"]["profile_binding_id"],Value::Null);assert_eq!(listing["selection"]["version"],2);assert_eq!(listing["profiles"][0]["status"],"DISCONNECTED");
    let dead=browser_native(&mut c,"heartbeat_chrome_profile",&context,json!({})).await.unwrap();assert_eq!(dead["error_code"],"PROFILE_OFFLINE");
}
async fn browser_seed_task(c:&mut PgConnection,context:&Value,state:&str)->String {
    let id=Uuid::new_v4();let key=format!("ext_task:{id}");browser_save(c,&key,json!({"id":id,"application_id":Uuid::new_v4(),"profile_binding_id":context["profile_binding_id"],"browser_session_id":context["browser_session_id"],"version":4,"state":state,"reason":"global_stop","plan_id":Uuid::new_v4(),"authorization_id":Uuid::new_v4(),"packet_revision":2,"profile_version":4,"verified_receipts":[],"tab_id":50,"window_id":10,"tab_active":true,"network_guard_active":true,"counts":{"ready":3,"completed":1,"existing":1,"manual":2}})).await;key
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_profiles_session_replacement_quarantines_original_forms_and_revokes_all_old_authority() {
    let mut c=browser_fixture().await;let context=browser_context();browser_connect(&mut c,&context).await;
    let task=browser_seed_task(&mut c,&context,"FILLING").await;
    let plan=format!("fill_plan:{}",Uuid::new_v4());browser_save(&mut c,&plan,json!({"profile_binding_id":context["profile_binding_id"],"state":"authorized","approved_fields":["f1"],"expires_at":"2099-01-01T00:00:00Z"})).await;
    let cmd=format!("chr_cmd:{}",Uuid::new_v4());browser_save(&mut c,&cmd,json!({"profile_binding_id":context["profile_binding_id"],"state":"executing","version":3})).await;
    let workid=Uuid::new_v4();let work=format!("apply_work:{workid}");let form=json!({"profile_binding_id":context["profile_binding_id"],"browser_session_id":context["browser_session_id"],"window_id":10,"tab_id":50});
    browser_save(&mut c,&work,json!({"id":workid,"platform":"naukri","revision":8,"stage":"NEEDS_INPUT","status":"waiting","form_pending":true,"form_binding":form,"admitted_actions":[{"action":"apply","admission":"preserve"}],"lease_token":Uuid::new_v4(),"lease_until":"2099-01-01T00:00:00Z"})).await;
    let question=format!("exec_q:{}",Uuid::new_v4());browser_save(&mut c,&question,json!({"queue_work_id":workid,"state":"delivery_unknown","reuse_approved":true})).await;
    let quota=json!({"supervised_consumed":3,"supervised_limit":4,"hourly_limit":1,"strict_receipts":0});browser_save(&mut c,"apply_queue",quota.clone()).await;
    let new_session=Uuid::new_v4();let result=browser_native(&mut c,"heartbeat_chrome_profile",&context,json!({"browser_session_id":new_session,"profile_commands_enabled":true})).await.unwrap();assert_eq!(result["ok"],true,"{result}");
    let saved=browser_pref(&mut c,&task).await;assert_eq!(saved["state"],"PAUSED");assert_eq!(saved["reason"],"global_stop");assert_eq!(saved["version"],6);assert_eq!(saved["browser_session_id"],json!(new_session));assert_eq!(saved["tab_id"],Value::Null);assert_eq!(saved["counts"]["ready"],0);assert_eq!(saved["counts"]["manual"],2);assert_eq!(saved["network_guard_active"],false);assert_eq!(saved["verified_receipts"][0]["verification_method"],"unknown");assert_eq!(saved["verified_receipts"][0]["submitted"],false);
    assert_eq!(browser_pref(&mut c,&plan).await["approved_fields"],json!([]));assert_eq!(browser_pref(&mut c,&cmd).await["state"],"outcome_unknown");
    let saved=browser_pref(&mut c,&work).await;assert_eq!(saved["stage"],"SUBMISSION_UNKNOWN");assert_eq!(saved["revision"],9);assert_eq!(saved["admitted_actions"],json!([{"action":"apply","admission":"preserve"}]));assert_eq!(saved["form_loss_observation"]["replay_authorized"],false);assert_eq!(saved["lease_token"],Value::Null);
    assert_eq!(browser_pref(&mut c,&question).await["state"],"closed_form_unavailable");assert_eq!(browser_pref(&mut c,"apply_queue").await,quota);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM agent_operations").fetch_one(&mut c).await.unwrap(),2);
    // No repeated quarantine or version increment on an ordinary heartbeat.
    browser_native(&mut c,"heartbeat_chrome_profile",&context,json!({"browser_session_id":new_session,"profile_commands_enabled":true})).await.unwrap();assert_eq!(browser_pref(&mut c,&work).await["revision"],9);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_profiles_window_change_matches_only_old_window_and_preserves_other_tasks_and_work() {
    let mut c=browser_fixture().await;let context=browser_context();browser_connect(&mut c,&context).await;let task=browser_seed_task(&mut c,&context,"PACKET_READY").await;
    let mut keys=Vec::new();
    for window in [10,20] {let id=Uuid::new_v4();let key=format!("apply_work:{id}");browser_save(&mut c,&key,json!({"id":id,"platform":"naukri","revision":1,"stage":"NEEDS_INPUT","form_pending":true,"admitted_actions":["apply"],"form_binding":{"profile_binding_id":context["profile_binding_id"],"browser_session_id":context["browser_session_id"],"window_id":window,"tab_id":window+100}})).await;keys.push(key);}
    let result=browser_native(&mut c,"heartbeat_chrome_profile",&context,json!({"window_id":30})).await.unwrap();assert_eq!(result["ok"],true);assert_eq!(browser_pref(&mut c,&keys[0]).await["stage"],"SUBMISSION_UNKNOWN");assert_eq!(browser_pref(&mut c,&keys[0]).await["form_loss_observation"]["source"],"authenticated_browser_window_replaced");assert_eq!(browser_pref(&mut c,&keys[1]).await["stage"],"NEEDS_INPUT");assert_eq!(browser_pref(&mut c,&task).await["state"],"PACKET_READY");
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_profiles_status_expires_without_redelivery_and_redacts_live_command_secrets() {
    let mut c=browser_fixture().await;let context=browser_context();browser_connect(&mut c,&context).await;
    for (i,state) in ["queued","leased","executing","completed"].iter().enumerate() {browser_save(&mut c,&format!("chr_cmd:{i}"),json!({"id":i,"profile_binding_id":context["profile_binding_id"],"state":state,"version":1,"expires_at":"2000-01-01T00:00:00Z","lease_token":"SECRET_LEASE","payload_hash":"PRIVATE_HASH"})).await;}
    let listing=browser_call(&mut c,BrowserRoute::List,Value::Null).await.unwrap();assert_eq!(listing["commands"][0]["state"],"expired");assert_eq!(listing["commands"][1]["state"],"outcome_unknown");assert_eq!(listing["commands"][2]["state"],"outcome_unknown");assert_eq!(listing["commands"][3]["state"],"completed");assert!(!listing.to_string().contains("SECRET_LEASE"));assert!(!listing.to_string().contains("PRIVATE_HASH"));
    let before=browser_snapshot(&mut c).await;browser_call(&mut c,BrowserRoute::List,Value::Null).await.unwrap();assert_eq!(browser_snapshot(&mut c).await,before);
    let poll=browser_native(&mut c,"poll_chrome_command",&context,json!({})).await.unwrap();assert_eq!(poll["ok"],false);assert_eq!(poll["error_code"],"browser_command_execution_unavailable");assert_eq!(browser_snapshot(&mut c).await,before);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_profiles_selection_conflict_fixed_binding_and_eight_installation_limit() {
    let mut c=browser_fixture().await;let mut first=Value::Null;
    for index in 0..8 {let context=browser_context();browser_connect(&mut c,&context).await;if index==0{first=context;}}
    let ninth=browser_native(&mut c,"connect_chrome_profile",&browser_context(),json!({"profile_label":"Ninth"})).await.unwrap();assert_eq!(ninth["error_code"],"profile_limit_reached");
    browser_save(&mut c,"chr_fixed_profile",json!({"profile_binding_id":first["profile_binding_id"]})).await;
    assert_eq!(browser_call(&mut c,BrowserRoute::Select,json!({"expected_version":0,"profile_binding_id":Uuid::new_v4()})).await.unwrap_err(),Failure("FIXED_PROFILE_REQUIRED"));
    browser_call(&mut c,BrowserRoute::Select,json!({"expected_version":0,"profile_binding_id":first["profile_binding_id"]})).await.unwrap();
    let before=browser_snapshot(&mut c).await;assert_eq!(browser_call(&mut c,BrowserRoute::Select,json!({"expected_version":0,"profile_binding_id":null})).await.unwrap_err(),Failure("PROFILE_SELECTION_CONFLICT"));assert_eq!(browser_snapshot(&mut c).await,before);
    for input in [json!({"expected_version":1}),json!({"expected_version":-1,"profile_binding_id":null}),json!({"expected_version":1,"profile_binding_id":null,"other":true})] {assert_eq!(browser_call(&mut c,BrowserRoute::Select,input).await.unwrap_err(),Failure("invalid_browser_profile_request"));}
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_profiles_lifecycle_write_failure_rolls_back_authority_and_releases_owner_lock() {
    let mut c=browser_fixture().await;let context=browser_context();browser_connect(&mut c,&context).await;let task=browser_seed_task(&mut c,&context,"FILLING").await;let before=browser_snapshot(&mut c).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_browser_suppress() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'chr_prof:') THEN RETURN NULL; END IF; RETURN NEW; END $$; CREATE TRIGGER fixture_browser_suppress BEFORE UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_browser_suppress()").execute(&mut c).await.unwrap();
    let result=browser_native(&mut c,"heartbeat_chrome_profile",&context,json!({"browser_session_id":Uuid::new_v4()})).await;assert_eq!(result.unwrap_err(),Failure("browser_profile_write_ack_failed"));assert_eq!(browser_snapshot(&mut c).await,before);assert_eq!(browser_pref(&mut c,&task).await["state"],"FILLING");assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM agent_operations").fetch_one(&mut c).await.unwrap(),0);
    let mut second=connection().await;sqlx::query("SET lock_timeout='150ms'").execute(&mut second).await.unwrap();let mut tx=second.begin().await.unwrap();sqlx::query("SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE").execute(&mut *tx).await.unwrap();tx.rollback().await.unwrap();
    sqlx::raw_sql("DROP TRIGGER fixture_browser_suppress ON owner_preferences; DROP FUNCTION fixture_browser_suppress()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_profiles_two_owner_selections_use_one_compare_and_swap() {
    let mut c=browser_fixture().await;let one=browser_context();let two=browser_context();browser_connect(&mut c,&one).await;browser_connect(&mut c,&two).await;let mut other=connection().await;
    let (a,b)=tokio::join!(browser_call(&mut c,BrowserRoute::Select,json!({"expected_version":0,"profile_binding_id":one["profile_binding_id"]})),browser_call(&mut other,BrowserRoute::Select,json!({"expected_version":0,"profile_binding_id":two["profile_binding_id"]})));assert_ne!(a.is_ok(),b.is_ok());assert_eq!(browser_pref(&mut c,"chr_selection").await["version"],1);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_profiles_actual_http_native_identity_is_confined_to_the_exact_route() {
    let mut c=browser_fixture().await;let (url,stop,server)=http_fixture_values(browser_values()).await;let http=client();let endpoint=format!("{url}{}",browser_profiles::NATIVE);let mut input=browser_context();input["command"]=json!("connect_chrome_profile");input["profile_label"]=json!("Fictional Brave");input["request_id"]=json!(Uuid::new_v4());
    for extension in [None,Some("not-an-extension"),Some("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")] {let mut req=http.post(&endpoint).bearer_auth(HOST_TOKEN).json(&input);if let Some(id)=extension{req=req.header("x-agent-client",id);}assert_eq!(req.send().await.unwrap().status(),403);}
    assert_eq!(http.post(&endpoint).header("x-agent-client",BROWSER_EXTENSION).json(&input).send().await.unwrap().status(),401);
    assert_eq!(http.post(&endpoint).bearer_auth(HOST_TOKEN).header("x-agent-client",BROWSER_EXTENSION).header("origin","https://evil.example.com").json(&input).send().await.unwrap().status(),403);
    assert_eq!(http.post(&endpoint).bearer_auth(HOST_TOKEN).header("x-agent-client",BROWSER_EXTENSION).header("x-agent-client",BROWSER_EXTENSION).json(&input).send().await.unwrap().status(),403);
    let good=http.post(&endpoint).bearer_auth(HOST_TOKEN).header("x-agent-client",BROWSER_EXTENSION).json(&input).send().await.unwrap();let status=good.status();let good:Value=good.json().await.unwrap();assert_eq!(status,200,"{good}");assert_eq!(good["ok"],true);assert_eq!(good["request_id"],input["request_id"]);
    assert_eq!(http.get(&endpoint).bearer_auth(HOST_TOKEN).header("x-agent-client",BROWSER_EXTENSION).send().await.unwrap().status(),405);
    for path in ["/api/v1/profile",browser_profiles::PROFILES,"/api/v1/rust-agent/control"] {assert_eq!(http.get(format!("{url}{path}")).bearer_auth(HOST_TOKEN).header("x-agent-client",BROWSER_EXTENSION).send().await.unwrap().status(),403);}
    let listing=http.get(format!("{url}{}",browser_profiles::PROFILES)).bearer_auth(HOST_TOKEN).send().await.unwrap();assert_eq!(listing.status(),200);let listing:Value=listing.json().await.unwrap();assert_eq!(listing["profiles"].as_array().unwrap().len(),1);assert!(!listing.to_string().contains("secret_hash"));
    let malformed=http.post(&endpoint).bearer_auth(HOST_TOKEN).header("x-agent-client",BROWSER_EXTENSION).json(&json!({"command":"heartbeat_chrome_profile","profile_secret":"secret","page_can_grant":true})).send().await.unwrap();assert_eq!(malformed.status(),422);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'chr_prof:')").fetch_one(&mut c).await.unwrap(),1);stop.cancel();server.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_profiles_lost_form_emits_only_one_honest_unknown_notice_after_three_checks() {
    let mut c=browser_fixture().await;let context=browser_context();browser_connect(&mut c,&context).await;
    sqlx::raw_sql("CREATE TABLE IF NOT EXISTS owner_notifications(id uuid PRIMARY KEY,dedup_key varchar(200) UNIQUE NOT NULL,kind varchar(50) NOT NULL,title varchar(200) NOT NULL,body text NOT NULL,href varchar(200) NOT NULL,read_at timestamptz,created_at timestamptz NOT NULL,updated_at timestamptz NOT NULL)").execute(&mut c).await.unwrap();
    let id=Uuid::new_v4();let key=format!("apply_work:{id}");browser_save(&mut c,&key,json!({"id":id,"platform":"naukri","packet_id":Uuid::new_v4(),"title":"Fictional Rust role","company":"Fictional Company","revision":1,"stage":"NEEDS_INPUT","form_pending":true,"admitted_actions":["apply"],"reconciliation_attempts":3,"form_binding":{"profile_binding_id":context["profile_binding_id"],"browser_session_id":context["browser_session_id"],"window_id":10,"tab_id":50}})).await;
    browser_native(&mut c,"heartbeat_chrome_profile",&context,json!({"window_id":20})).await.unwrap();
    let row=browser_pref(&mut c,&key).await;assert_eq!(row["uncertain_outcome_notice"]["verified_submission"],false);assert_eq!(row["uncertain_outcome_notice"]["channels"],json!(["in_app"]));
    let dedup=format!("naukri-unknown:{id}");let notice:Value=sqlx::query_scalar("SELECT to_jsonb(n) FROM owner_notifications n WHERE dedup_key=$1").bind(&dedup).fetch_one(&mut c).await.unwrap();assert_eq!(notice["kind"],"application_submission_unknown");assert!(notice["body"].as_str().unwrap().contains("Apply will not be repeated"));
    browser_native(&mut c,"heartbeat_chrome_profile",&context,json!({"window_id":30})).await.unwrap();assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_notifications WHERE dedup_key=$1").bind(dedup).fetch_one(&mut c).await.unwrap(),1);assert_eq!(browser_pref(&mut c,&key).await["revision"],2);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_profiles_failed_commit_is_unknown_not_success_and_native_mutation_is_not_replayed() {
    let mut c=browser_fixture().await;let (url,stop,server)=http_fixture_values(browser_values()).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_browser_commit_fail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fictional deferred failure'; END $$; CREATE CONSTRAINT TRIGGER fixture_browser_commit_fail AFTER INSERT ON owner_preferences DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fixture_browser_commit_fail()").execute(&mut c).await.unwrap();
    let http=client();let mut input=browser_context();input["command"]=json!("connect_chrome_profile");input["request_id"]=json!(Uuid::new_v4());input["profile_label"]=json!("Fictional Brave");
    let response=http.post(format!("{url}{}",browser_profiles::NATIVE)).bearer_auth(HOST_TOKEN).header("x-agent-client",BROWSER_EXTENSION).json(&input).send().await.unwrap();assert_eq!(response.status(),503);assert!(response.headers().get("x-agent-transaction-rolled-back").is_none());assert_eq!(response.json::<Value>().await.unwrap()["detail"],"browser_profile_commit_outcome_unknown");
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'chr_prof:')").fetch_one(&mut c).await.unwrap(),0);
    sqlx::raw_sql("DROP TRIGGER fixture_browser_commit_fail ON owner_preferences; DROP FUNCTION fixture_browser_commit_fail()").execute(&mut c).await.unwrap();
    tokio::time::sleep(Duration::from_millis(1100)).await;
    let status=http.get(format!("{url}{}",browser_profiles::PROFILES)).bearer_auth(HOST_TOKEN).send().await.unwrap();assert_eq!(status.status(),200);assert_eq!(status.json::<Value>().await.unwrap()["profiles"],json!([]));stop.cancel();server.await.unwrap();
}
