async fn browser_command_fixture()->(PgConnection,Value,Value) {
    let (mut c,job)=packet_service_fixture().await;
    sqlx::raw_sql("CREATE TABLE IF NOT EXISTS agent_operations(key varchar(180) PRIMARY KEY,actor varchar(120) NOT NULL,command varchar(50) NOT NULL,payload_hash varchar(64) NOT NULL,result jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp());CREATE TABLE IF NOT EXISTS agent_policies(key varchar(20) PRIMARY KEY,version integer NOT NULL,preferences jsonb NOT NULL);DELETE FROM agent_policies;").execute(&mut c).await.unwrap();
    let packet=packet_create(&mut c,job,"fictional-browser-command",json!([])).await.unwrap();
    browser_save(&mut c,"phase1_profile_confirmation",json!({"profile_id":packet["candidate_profile_id"],"profile_version":packet["candidate_profile_version"],"confirmed_at":"2026-11-16T00:00:00Z"})).await;
    let context=browser_context();browser_connect(&mut c,&context).await;
    browser_call(&mut c,BrowserRoute::Select,json!({"expected_version":0,"profile_binding_id":context["profile_binding_id"]})).await.unwrap();
    let result=browser_native(&mut c,"heartbeat_chrome_profile",&context,json!({"profile_commands_enabled":true})).await.unwrap();assert_eq!(result["ok"],true);
    (c,context,packet)
}
fn browser_enqueue_input(context:&Value,packet:&Value)->Value {json!({"request_id":Uuid::new_v4(),"profile_binding_id":context["profile_binding_id"],"selection_version":1,"expected_profile_version":2,"application_id":packet["id"],"packet_revision":packet["revision"],"action":"open"})}
fn browser_lease_command(value:&Value)->Value {json!({"chrome_command_id":value["id"],"expected_command_version":value["version"],"command_lease_token":value["lease_token"]})}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_commands_enqueue_poll_start_ack_are_one_lease_without_duplicate_dispatch() {
    let (mut c,context,packet)=browser_command_fixture().await;let input=browser_enqueue_input(&context,&packet);
    let first=browser_call(&mut c,BrowserRoute::Enqueue,input.clone()).await.unwrap();assert_eq!(first["state"],"queued");assert_eq!(first["submitted"],false);assert!(first["lease_token"].is_null());
    assert_eq!(browser_call(&mut c,BrowserRoute::Enqueue,input.clone()).await.unwrap(),first);
    let mut changed=input.clone();changed["action"]=json!("pause");assert_eq!(browser_call(&mut c,BrowserRoute::Enqueue,changed).await.unwrap_err(),Failure("command_id_conflict"));
    let lease=browser_native(&mut c,"poll_chrome_command",&context,json!({})).await.unwrap();assert_eq!(lease["ok"],true,"{lease}");let lease=lease["data"]["command"].clone();assert_eq!(lease["state"],"leased");assert_eq!(lease["version"],2);assert!(lease["lease_token"].as_str().unwrap().parse::<Uuid>().is_ok());
    assert_eq!(browser_native(&mut c,"poll_chrome_command",&context,json!({})).await.unwrap()["data"]["command"],Value::Null);
    let started=browser_native(&mut c,"start_chrome_command",&context,browser_lease_command(&lease)).await.unwrap();assert_eq!(started["ok"],true,"{started}");let executing=started["data"]["command"].clone();assert_eq!(executing["state"],"executing");assert_eq!(executing["version"],3);
    let replay=browser_native(&mut c,"start_chrome_command",&context,browser_lease_command(&lease)).await.unwrap();assert_eq!(replay["error_code"],"profile_command_revision_conflict");
    let mut ack=browser_lease_command(&executing);ack["command_outcome"]=json!("completed");let done=browser_native(&mut c,"ack_chrome_command",&context,ack.clone()).await.unwrap();assert_eq!(done["data"]["command"]["state"],"completed");assert_eq!(done["data"]["command"]["version"],4);assert_eq!(done["data"]["submitted"],false);
    assert_eq!(browser_native(&mut c,"ack_chrome_command",&context,ack).await.unwrap()["error_code"],"profile_command_revision_conflict");assert_eq!(browser_native(&mut c,"poll_chrome_command",&context,json!({})).await.unwrap()["data"]["command"],Value::Null);
    // Idempotent owner retry returns historical terminal result, never another command.
    assert_eq!(browser_call(&mut c,BrowserRoute::Enqueue,input).await.unwrap()["state"],"completed");assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'chr_cmd:')").fetch_one(&mut c).await.unwrap(),1);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_commands_expired_lease_and_changed_profile_are_unknown_and_never_released_again() {
    let (mut c,context,packet)=browser_command_fixture().await;let one=browser_enqueue_input(&context,&packet);let first=browser_call(&mut c,BrowserRoute::Enqueue,one).await.unwrap();let second=browser_call(&mut c,BrowserRoute::Enqueue,browser_enqueue_input(&context,&packet)).await.unwrap();
    let lease=browser_native(&mut c,"poll_chrome_command",&context,json!({})).await.unwrap()["data"]["command"].clone();assert_eq!(lease["id"],first["id"]);
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{lease_expires_at}','\"2000-01-01T00:00:00Z\"') WHERE key=$1").bind(format!("chr_cmd:{}",lease["id"].as_str().unwrap())).execute(&mut c).await.unwrap();
    let stale=browser_native(&mut c,"start_chrome_command",&context,browser_lease_command(&lease)).await.unwrap();assert_eq!(stale["error_code"],"profile_command_revision_conflict");assert_eq!(browser_pref(&mut c,&format!("chr_cmd:{}",lease["id"].as_str().unwrap())).await["state"],"outcome_unknown");
    let next=browser_native(&mut c,"poll_chrome_command",&context,json!({})).await.unwrap()["data"]["command"].clone();assert_eq!(next["id"],second["id"]);
    browser_native(&mut c,"heartbeat_chrome_profile",&context,json!({"profile_commands_enabled":false})).await.unwrap();assert_eq!(browser_pref(&mut c,&format!("chr_cmd:{}",next["id"].as_str().unwrap())).await["state"],"outcome_unknown");
    browser_native(&mut c,"heartbeat_chrome_profile",&context,json!({"profile_commands_enabled":true})).await.unwrap();assert_eq!(browser_native(&mut c,"poll_chrome_command",&context,json!({})).await.unwrap()["data"]["command"],Value::Null);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_commands_start_rechecks_packet_profile_policy_and_retained_receipt_before_execution() {
    let (mut c,context,packet)=browser_command_fixture().await;let input=browser_enqueue_input(&context,&packet);browser_call(&mut c,BrowserRoute::Enqueue,input.clone()).await.unwrap();let lease=browser_native(&mut c,"poll_chrome_command",&context,json!({})).await.unwrap()["data"]["command"].clone();
    // Changing only the owner confirmation does not need a candidate rewrite to revoke execution.
    browser_save(&mut c,"phase1_profile_confirmation",json!({"profile_id":packet["candidate_profile_id"],"profile_version":999,"confirmed_at":"2026-11-16T00:00:00Z"})).await;
    let denied=browser_native(&mut c,"start_chrome_command",&context,browser_lease_command(&lease)).await.unwrap();assert_eq!(denied["error_code"],"stale_or_unreviewed_candidate_context");assert_eq!(browser_pref(&mut c,&format!("chr_cmd:{}",lease["id"].as_str().unwrap())).await["state"],"leased");
    browser_save(&mut c,"phase1_profile_confirmation",json!({"profile_id":packet["candidate_profile_id"],"profile_version":4,"confirmed_at":"2026-11-16T00:00:00Z"})).await;
    sqlx::query("INSERT INTO agent_policies(key,version,preferences) VALUES('primary',2,$1)").bind(json!({"default":"approve","platforms":{"naukri":"manual_only"}})).execute(&mut c).await.unwrap();
    assert_eq!(browser_native(&mut c,"start_chrome_command",&context,browser_lease_command(&lease)).await.unwrap()["error_code"],"platform_fill_policy_denied");sqlx::query("DELETE FROM agent_policies").execute(&mut c).await.unwrap();
    // Even damaged receipt evidence prevents replay; it is not promoted to a verified receipt.
    let url:String=sqlx::query_scalar("SELECT job_url FROM jobs WHERE id=$1").bind(packet["job_id"].as_str().unwrap().parse::<Uuid>().unwrap()).fetch_one(&mut c).await.unwrap();let req=url.trim_end_matches('/').rsplit('-').next().unwrap();browser_save(&mut c,&format!("naukri_worker_receipt:{req}"),json!({"damaged":"must reconcile"})).await;
    assert_eq!(browser_native(&mut c,"start_chrome_command",&context,browser_lease_command(&lease)).await.unwrap()["error_code"],"application_not_eligible");
    let new=browser_enqueue_input(&context,&packet);assert_eq!(browser_call(&mut c,BrowserRoute::Enqueue,new).await.unwrap_err(),Failure("application_not_eligible"));
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_commands_stale_packet_and_policy_stop_cannot_start_a_previously_leased_command() {
    let (mut c,context,packet)=browser_command_fixture().await;browser_call(&mut c,BrowserRoute::Enqueue,browser_enqueue_input(&context,&packet)).await.unwrap();let lease=browser_native(&mut c,"poll_chrome_command",&context,json!({})).await.unwrap()["data"]["command"].clone();
    browser_save(&mut c,"naukri_automation",json!({"revision":7,"state":"STOPPED"})).await;assert_eq!(browser_native(&mut c,"start_chrome_command",&context,browser_lease_command(&lease)).await.unwrap()["error_code"],"naukri_automation_stopped");browser_save(&mut c,"naukri_automation",json!({"revision":8,"state":"RUNNING"})).await;
    browser_save(&mut c,"exec_config:naukri",json!({"mode":"OFF"})).await;assert_eq!(browser_native(&mut c,"start_chrome_command",&context,browser_lease_command(&lease)).await.unwrap()["error_code"],"execution_mode_off");browser_save(&mut c,"exec_config:naukri",json!({"mode":"ON_DEMAND"})).await;
    sqlx::query("UPDATE application_packets SET revision=revision+1 WHERE id=$1").bind(packet["id"].as_str().unwrap().parse::<Uuid>().unwrap()).execute(&mut c).await.unwrap();assert_eq!(browser_native(&mut c,"start_chrome_command",&context,browser_lease_command(&lease)).await.unwrap()["error_code"],"extension_task_context_stale");
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_commands_wrong_profile_session_lease_and_queue_capacity_cannot_grant_execution() {
    let (mut c,context,packet)=browser_command_fixture().await;browser_call(&mut c,BrowserRoute::Enqueue,browser_enqueue_input(&context,&packet)).await.unwrap();let lease=browser_native(&mut c,"poll_chrome_command",&context,json!({})).await.unwrap()["data"]["command"].clone();
    let mut wrong=browser_lease_command(&lease);wrong["command_lease_token"]=json!(Uuid::new_v4());assert_eq!(browser_native(&mut c,"start_chrome_command",&context,wrong).await.unwrap()["error_code"],"profile_command_revision_conflict");
    let mut wrong=browser_lease_command(&lease);wrong["browser_session_id"]=json!(Uuid::new_v4());assert_eq!(browser_native(&mut c,"start_chrome_command",&context,wrong).await.unwrap()["error_code"],"PROFILE_SESSION_CHANGED");
    for _ in 0..19 {browser_call(&mut c,BrowserRoute::Enqueue,browser_enqueue_input(&context,&packet)).await.unwrap();}
    assert_eq!(browser_call(&mut c,BrowserRoute::Enqueue,browser_enqueue_input(&context,&packet)).await.unwrap_err(),Failure("profile_queue_full"));assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'chr_cmd:')").fetch_one(&mut c).await.unwrap(),20);
    assert_eq!(browser_native(&mut c,"poll_chrome_command",&context,json!({})).await.unwrap()["data"]["command"],Value::Null);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_commands_offline_owner_enqueue_commits_revocation_before_rejecting() {
    let (mut c,context,packet)=browser_command_fixture().await;let task=browser_seed_task(&mut c,&context,"FILLING").await;let key=format!("chr_prof:{}",context["profile_binding_id"].as_str().unwrap());sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{last_heartbeat}','\"2000-01-01T00:00:00Z\"') WHERE key=$1").bind(key).execute(&mut c).await.unwrap();
    assert_eq!(browser_call(&mut c,BrowserRoute::Enqueue,browser_enqueue_input(&context,&packet)).await.unwrap_err(),Failure("PROFILE_OFFLINE"));assert_eq!(browser_pref(&mut c,&task).await["state"],"PAUSED");assert_eq!(browser_pref(&mut c,&task).await["verified_receipts"][0]["state"],"manual_required");
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_commands_two_native_pollers_deliver_only_one_command() {
    let (mut c,context,packet)=browser_command_fixture().await;browser_call(&mut c,BrowserRoute::Enqueue,browser_enqueue_input(&context,&packet)).await.unwrap();let mut other=connection().await;
    let (a,b)=tokio::join!(browser_native(&mut c,"poll_chrome_command",&context,json!({})),browser_native(&mut other,"poll_chrome_command",&context,json!({})));let a=a.unwrap();let b=b.unwrap();assert_eq!(a["ok"],true);assert_eq!(b["ok"],true);assert_ne!(a["data"]["command"].is_null(),b["data"]["command"].is_null());
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_commands_quarantined_admission_and_other_slug_receipt_cannot_be_reopened() {
    let (mut c,context,packet)=browser_command_fixture().await;
    let url:String=sqlx::query_scalar("SELECT job_url FROM jobs WHERE id=$1").bind(packet["job_id"].as_str().unwrap().parse::<Uuid>().unwrap()).fetch_one(&mut c).await.unwrap();let req=url.trim_end_matches('/').rsplit('-').next().unwrap();
    let id=Uuid::new_v5(&Uuid::NAMESPACE_URL,format!("naukri:{req}").as_bytes());let key=format!("apply_work:{id}");let retained=json!({"id":id,"platform":"naukri","status":"unknown","stage":"SUBMISSION_UNKNOWN","admitted_actions":["apply"],"revision":9});browser_save(&mut c,&key,retained.clone()).await;
    assert_eq!(browser_call(&mut c,BrowserRoute::Enqueue,browser_enqueue_input(&context,&packet)).await.unwrap_err(),Failure("application_not_eligible"));assert_eq!(browser_pref(&mut c,&key).await,retained);
    sqlx::query("DELETE FROM owner_preferences WHERE key=$1").bind(&key).execute(&mut c).await.unwrap();
    let other=Uuid::new_v4();sqlx::query("INSERT INTO jobs(id,title,job_url,source_platform) VALUES($1,'Retained other slug',$2,'naukri')").bind(other).bind(format!("https://www.naukri.com/job-listings-other-slug-{req}")).execute(&mut c).await.unwrap();
    // A previously uncertain packet on an alternate slug still refers to the same vacancy.
    let mut snapshot=packet["snapshot"].clone();snapshot["job_id"]=json!(other);
    let other_packet=Uuid::new_v4();
    sqlx::query("INSERT INTO application_packets(id,job_id,candidate_profile_id,candidate_profile_version,platform,lifecycle_state,snapshot,revision,readiness_state,tracking_state,idempotency_key,request_hash) VALUES($1,$2,$3,4,'naukri','created',$4,1,'manual_action_required','not_applied','fictional-other-slug',repeat('d',64))").bind(other_packet).bind(other).bind(packet["candidate_profile_id"].as_str().unwrap().parse::<Uuid>().unwrap()).bind(snapshot).execute(&mut c).await.unwrap();
    let work=Uuid::new_v4();browser_save(&mut c,&format!("apply_work:{work}"),json!({"id":work,"platform":"naukri","packet_id":other_packet,"job_id":other,"candidate_profile_id":packet["candidate_profile_id"],"profile_version":4,"packet_revision":1,"admitted_actions":[{"fingerprint":"apply:fictional-history"}]})).await;
    sqlx::query("UPDATE application_packets SET lifecycle_state='submission_unknown' WHERE id=$1").bind(other_packet).execute(&mut c).await.unwrap();
    assert_eq!(browser_call(&mut c,BrowserRoute::Enqueue,browser_enqueue_input(&context,&packet)).await.unwrap_err(),Failure("application_not_eligible"));
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_commands_prepare_requires_exact_current_task_and_failed_lease_write_is_not_delivered() {
    let (mut c,context,packet)=browser_command_fixture().await;let mut input=browser_enqueue_input(&context,&packet);input["action"]=json!("prepare");assert_eq!(browser_call(&mut c,BrowserRoute::Enqueue,input.clone()).await.unwrap_err(),Failure("extension_task_required"));
    let task=browser_seed_task(&mut c,&context,"PACKET_READY").await;let mut saved=browser_pref(&mut c,&task).await;saved["application_id"]=packet["id"].clone();browser_save(&mut c,&task,saved.clone()).await;
    input["task_id"]=saved["id"].clone();input["expected_task_version"]=json!(99);assert_eq!(browser_call(&mut c,BrowserRoute::Enqueue,input.clone()).await.unwrap_err(),Failure("extension_task_revision_conflict"));input["expected_task_version"]=json!(4);let queued=browser_call(&mut c,BrowserRoute::Enqueue,input).await.unwrap();
    sqlx::raw_sql("CREATE FUNCTION fixture_browser_lease_suppress() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'chr_cmd:') AND NEW.value->>'state'='leased' THEN RETURN NULL; END IF; RETURN NEW; END $$; CREATE TRIGGER fixture_browser_lease_suppress BEFORE UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_browser_lease_suppress()").execute(&mut c).await.unwrap();
    assert_eq!(browser_native(&mut c,"poll_chrome_command",&context,json!({})).await.unwrap_err(),Failure("browser_profile_write_ack_failed"));assert_eq!(browser_pref(&mut c,&format!("chr_cmd:{}",queued["id"].as_str().unwrap())).await,queued);
    sqlx::raw_sql("DROP TRIGGER fixture_browser_lease_suppress ON owner_preferences; DROP FUNCTION fixture_browser_lease_suppress()").execute(&mut c).await.unwrap();
    assert_eq!(browser_native(&mut c,"poll_chrome_command",&context,json!({})).await.unwrap()["data"]["command"]["state"],"leased");
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_commands_actual_http_owner_enqueue_and_native_handshake_keep_roles_separate() {
    let (mut c,context,packet)=browser_command_fixture().await;let (url,stop,server)=http_fixture_values(browser_values()).await;let http=client();let endpoint=format!("{url}/api/v1/browser/chrome-profiles/commands");let input=browser_enqueue_input(&context,&packet);
    assert_eq!(http.post(&endpoint).bearer_auth(HOST_TOKEN).header("x-agent-client",BROWSER_EXTENSION).json(&input).send().await.unwrap().status(),403);
    let enqueued=http.post(&endpoint).bearer_auth(HOST_TOKEN).json(&input).send().await.unwrap();let status=enqueued.status();let enqueued:Value=enqueued.json().await.unwrap();assert_eq!(status,200,"{enqueued}");assert_eq!(enqueued["state"],"queued");
    let mut poll=context.clone();poll["command"]=json!("poll_chrome_command");poll["request_id"]=json!(Uuid::new_v4());let native=http.post(format!("{url}{}",browser_profiles::NATIVE)).bearer_auth(HOST_TOKEN).header("x-agent-client",BROWSER_EXTENSION).json(&poll).send().await.unwrap();assert_eq!(native.status(),200);assert_eq!(native.json::<Value>().await.unwrap()["data"]["command"]["state"],"leased");
    let status:Value=http.get(format!("{url}{}",browser_profiles::PROFILES)).bearer_auth(HOST_TOKEN).send().await.unwrap().json().await.unwrap();assert!(status["commands"][0].get("lease_token").is_none());
    let counts:Value=sqlx::query_scalar("SELECT jsonb_build_object('packets',(SELECT count(*) FROM application_packets),'receipts',(SELECT count(*) FROM application_submission_evidence),'commands',(SELECT count(*) FROM owner_preferences WHERE starts_with(key,'chr_cmd:')))").fetch_one(&mut c).await.unwrap();assert_eq!(counts,json!({"packets":1,"receipts":0,"commands":1}));stop.cancel();server.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_commands_lease_expiring_during_material_lock_wait_never_starts() {
    let (mut c,context,packet)=browser_command_fixture().await;browser_call(&mut c,BrowserRoute::Enqueue,browser_enqueue_input(&context,&packet)).await.unwrap();let lease=browser_native(&mut c,"poll_chrome_command",&context,json!({})).await.unwrap()["data"]["command"].clone();
    let key=format!("chr_cmd:{}",lease["id"].as_str().unwrap());sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{lease_expires_at}',to_jsonb(clock_timestamp()+interval '700 milliseconds')) WHERE key=$1").bind(&key).execute(&mut c).await.unwrap();
    let mut blocker=connection().await;let mut locked=blocker.begin().await.unwrap();sqlx::query("SELECT id FROM jobs WHERE id=$1 FOR UPDATE").bind(packet["job_id"].as_str().unwrap().parse::<Uuid>().unwrap()).execute(&mut *locked).await.unwrap();
    let context2=context.clone();let command=browser_lease_command(&lease);let task=tokio::spawn(async move{let r=browser_native(&mut c,"start_chrome_command",&context2,command).await;(c,r)});
    tokio::time::sleep(Duration::from_millis(900)).await;locked.rollback().await.unwrap();let (mut c,result)=task.await.unwrap();let result=result.unwrap();assert_eq!(result["error_code"],"profile_command_expired","{result}");assert_eq!(browser_pref(&mut c,&key).await["state"],"outcome_unknown");assert_eq!(browser_native(&mut c,"poll_chrome_command",&context,json!({})).await.unwrap()["data"]["command"],Value::Null);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_commands_large_terminal_history_does_not_block_active_dispatch_status_or_revocation() {
    let (mut c,context,packet)=browser_command_fixture().await;
    sqlx::query("INSERT INTO owner_preferences(key,value) SELECT 'chr_cmd:'||md5('fixture-command-'||g)::uuid::text,jsonb_build_object('id',md5('fixture-command-'||g)::uuid,'profile_binding_id',$1::jsonb,'state','completed','version',4,'expires_at','2000-01-01T00:00:00Z') FROM generate_series(1,10001) g").bind(&context["profile_binding_id"]).execute(&mut c).await.unwrap();
    sqlx::query("INSERT INTO owner_preferences(key,value) SELECT 'ext_task:'||md5('fixture-task-'||g)::uuid::text,jsonb_build_object('id',md5('fixture-task-'||g)::uuid,'profile_binding_id',$1::jsonb,'state','FAILED_FINAL','version',4) FROM generate_series(1,10001) g").bind(&context["profile_binding_id"]).execute(&mut c).await.unwrap();
    let queued=browser_call(&mut c,BrowserRoute::Enqueue,browser_enqueue_input(&context,&packet)).await.unwrap();let poll=browser_native(&mut c,"poll_chrome_command",&context,json!({})).await.unwrap();assert_eq!(poll["data"]["command"]["id"],queued["id"]);
    let listing=browser_call(&mut c,BrowserRoute::List,Value::Null).await.unwrap();assert_eq!(listing["commands"].as_array().unwrap().len(),30);assert!(listing["commands"].as_array().unwrap().iter().any(|v|v["id"]==queued["id"]));
    let restarted=browser_native(&mut c,"heartbeat_chrome_profile",&context,json!({"browser_session_id":Uuid::new_v4(),"profile_commands_enabled":true})).await.unwrap();assert_eq!(restarted["ok"],true,"{restarted}");assert_eq!(browser_pref(&mut c,&format!("chr_cmd:{}",queued["id"].as_str().unwrap())).await["state"],"outcome_unknown");
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'chr_cmd:') AND value->>'state'='completed'").fetch_one(&mut c).await.unwrap(),10001);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'ext_task:') AND value->>'state'='FAILED_FINAL'").fetch_one(&mut c).await.unwrap(),10001);
}
async fn browser_framed_native(path:&std::path::Path,command:Value)->Value {
    use tokio::io::AsyncWriteExt;
    let executable=std::env::current_exe().unwrap().parent().unwrap().parent().unwrap().join("automated-apply-native");
    let mut child=tokio::process::Command::new(executable).arg(path).arg(format!("chrome-extension://{BROWSER_EXTENSION}/")).env_clear().stdin(std::process::Stdio::piped()).stdout(std::process::Stdio::piped()).stderr(std::process::Stdio::piped()).kill_on_drop(true).spawn().unwrap();
    let payload=command.to_string();let mut stdin=child.stdin.take().unwrap();stdin.write_all(&(payload.len() as u32).to_le_bytes()).await.unwrap();stdin.write_all(payload.as_bytes()).await.unwrap();stdin.shutdown().await.unwrap();drop(stdin);
    let output=tokio::time::timeout(Duration::from_secs(8),child.wait_with_output()).await.unwrap().unwrap();assert!(output.status.success());assert!(output.stderr.is_empty());assert!(output.stdout.len()>4);let length=u32::from_le_bytes(output.stdout[..4].try_into().unwrap()) as usize;assert_eq!(length+4,output.stdout.len());let result:Value=serde_json::from_slice(&output.stdout[4..]).unwrap();assert_eq!(result["request_id"],command["request_id"]);assert_eq!(result["ok"],true,"{result}");assert!(!result.to_string().contains(&"f".repeat(64)));result
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_commands_actual_native_process_frames_lease_start_and_ack_against_rust_http_host() {
    let (mut c,context,packet)=browser_command_fixture().await;let (url,stop,server)=http_fixture_values(browser_values()).await;
    let directory=tempfile::tempdir().unwrap();std::fs::set_permissions(directory.path(),std::fs::Permissions::from_mode(0o700)).unwrap();let path=directory.path().join("native.private.env");std::fs::write(&path,format!("CHROME_EXTENSION_ID='{BROWSER_EXTENSION}'\nCHROME_NATIVE_MESSAGING_ENABLED=true\nJOB_AGENT_API_TOKEN='{HOST_TOKEN}'\nLOCAL_AGENT_ENDPOINT='{url}'\n")).unwrap();std::fs::set_permissions(&path,std::fs::Permissions::from_mode(0o600)).unwrap();
    let queued=browser_call(&mut c,BrowserRoute::Enqueue,browser_enqueue_input(&context,&packet)).await.unwrap();let mut request=context.clone();request["command"]=json!("poll_chrome_command");request["request_id"]=json!(Uuid::new_v4());let leased=browser_framed_native(&path,request).await["data"]["command"].clone();assert_eq!(leased["id"],queued["id"]);
    let mut request=context.clone();for(k,v)in browser_lease_command(&leased).as_object().unwrap(){request[k]=v.clone();}request["command"]=json!("start_chrome_command");request["request_id"]=json!(Uuid::new_v4());let executing=browser_framed_native(&path,request).await["data"]["command"].clone();assert_eq!(executing["state"],"executing");
    let mut request=context.clone();for(k,v)in browser_lease_command(&executing).as_object().unwrap(){request[k]=v.clone();}request["command"]=json!("ack_chrome_command");request["request_id"]=json!(Uuid::new_v4());request["command_outcome"]=json!("completed");let done=browser_framed_native(&path,request).await;assert_eq!(done["data"]["command"]["state"],"completed");assert_eq!(done["data"]["submitted"],false);stop.cancel();server.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_commands_explicit_fixture_origin_can_use_only_its_exact_numeric_local_target() {
    let (mut c,job)=packet_service_fixture().await;
    sqlx::raw_sql("CREATE TABLE IF NOT EXISTS agent_operations(key varchar(180) PRIMARY KEY,actor varchar(120) NOT NULL,command varchar(50) NOT NULL,payload_hash varchar(64) NOT NULL,result jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp());CREATE TABLE IF NOT EXISTS agent_policies(key varchar(20) PRIMARY KEY,version integer NOT NULL,preferences jsonb NOT NULL);DELETE FROM agent_policies;").execute(&mut c).await.unwrap();
    let target="http://127.0.0.1:12345/fictional-form";
    sqlx::query("UPDATE jobs SET application_url=$1 WHERE id=$2").bind(target).bind(job).execute(&mut c).await.unwrap();let packet=packet_create(&mut c,job,"fictional-numeric-browser",json!([])).await.unwrap();
    browser_save(&mut c,"phase1_profile_confirmation",json!({"profile_id":packet["candidate_profile_id"],"profile_version":4,"confirmed_at":"2026-11-16T00:00:00Z"})).await;let context=browser_context();browser_connect(&mut c,&context).await;browser_call(&mut c,BrowserRoute::Select,json!({"expected_version":0,"profile_binding_id":context["profile_binding_id"]})).await.unwrap();browser_native(&mut c,"heartbeat_chrome_profile",&context,json!({"profile_commands_enabled":true})).await.unwrap();
    let mut values=browser_values();values.insert("BROWSER_FIXTURE_ORIGIN".into(),"http://127.0.0.1:12345".into());let settings=browser_profiles::Settings::from_values(&values).unwrap();let input=browser_enqueue_input(&context,&packet);
    let queued=browser_profiles::dispatch(&mut c,BrowserRoute::Enqueue,"POST",input.to_string().as_bytes(),&settings,&packet_settings(),None).await.unwrap();assert_eq!(queued["destination"],target);
    let mut poll=context.clone();poll["command"]=json!("poll_chrome_command");let lease=browser_profiles::dispatch(&mut c,BrowserRoute::Native,"POST",poll.to_string().as_bytes(),&settings,&packet_settings(),None).await.unwrap()["data"]["command"].clone();let mut start=context.clone();start["command"]=json!("start_chrome_command");for(k,v)in browser_lease_command(&lease).as_object().unwrap(){start[k]=v.clone();}let result=browser_profiles::dispatch(&mut c,BrowserRoute::Native,"POST",start.to_string().as_bytes(),&settings,&packet_settings(),None).await.unwrap();assert_eq!(result["data"]["command"]["state"],"executing");
    values.insert("BROWSER_FIXTURE_ORIGIN".into(),"http://127.0.0.1:12346".into());let settings=browser_profiles::Settings::from_values(&values).unwrap();assert_eq!(browser_profiles::dispatch(&mut c,BrowserRoute::Enqueue,"POST",browser_enqueue_input(&context,&packet).to_string().as_bytes(),&settings,&packet_settings(),None).await.unwrap_err(),Failure("unsupported_form_adapter"));
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn browser_commands_ordinary_status_does_not_wait_for_the_execution_owner_row() {
    let (mut c,_,_)=browser_command_fixture().await;let mut holder=connection().await;let mut tx=holder.begin().await.unwrap();sqlx::query("SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE").execute(&mut *tx).await.unwrap();
    sqlx::query("SET lock_timeout='100ms'").execute(&mut c).await.unwrap();
    let status=tokio::time::timeout(Duration::from_secs(2),browser_call(&mut c,BrowserRoute::List,Value::Null)).await.unwrap().unwrap();assert_eq!(status["profiles"].as_array().unwrap().len(),1);assert_eq!(status["profiles"][0]["status"],"CONNECTED");tx.rollback().await.unwrap();
}
