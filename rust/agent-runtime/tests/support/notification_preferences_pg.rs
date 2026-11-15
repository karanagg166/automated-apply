#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn notification_preferences_http_defaults_and_atomic_replacement_do_not_dispatch(){
    let mut c=notification_fixture().await;let (url,stop,server)=http_fixture().await;let http=client();let target=format!("{url}/api/v1/dashboard/notification-preferences");
    let defaults=automated_apply_agents::notification_preferences::normalize(json!({})).unwrap();
    let response=http.get(format!("{target}?ignored=1")).bearer_auth(HOST_TOKEN).send().await.unwrap();assert_eq!(response.status(),200);assert_eq!(response.json::<Value>().await.unwrap(),defaults);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE key='notifications'").fetch_one(&mut c).await.unwrap(),0);
    let profile=profile_store::get(&mut c).await.unwrap().value;
    let response=http.put(&target).bearer_auth(HOST_TOKEN).json(&json!({"in_app":false,"paused":true,"daily_digest":false,"minimum_job_score":50,"timezone":"Etc/UTC"})).send().await.unwrap();assert_eq!(response.status(),200);let saved:Value=response.json().await.unwrap();assert_eq!(saved["in_app"],false);assert_eq!(saved["paused"],true);assert_eq!(saved["minimum_job_score"],50);assert_eq!(saved["telegram"],false);assert_eq!(saved["browser_push"],false);
    assert_eq!(sqlx::query_scalar::<_,Value>("SELECT value FROM owner_preferences WHERE key='notifications'").fetch_one(&mut c).await.unwrap(),saved);
    let read:Value=http.get(&target).bearer_auth(HOST_TOKEN).send().await.unwrap().json().await.unwrap();assert_eq!(read,saved);
    let response=http.put(&target).bearer_auth(HOST_TOKEN).json(&json!({"paused":true})).send().await.unwrap();assert_eq!(response.status(),200);let replaced:Value=response.json().await.unwrap();assert_eq!(replaced["paused"],true);assert_eq!(replaced["in_app"],true);assert_eq!(replaced["daily_digest"],true);assert_eq!(replaced["minimum_job_score"],75);assert_eq!(replaced["timezone"],"Asia/Kolkata");
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_notifications").fetch_one(&mut c).await.unwrap(),105);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM notification_deliveries").fetch_one(&mut c).await.unwrap(),105);assert_eq!(profile_store::get(&mut c).await.unwrap().value,profile);
    assert_eq!(http.get(&target).send().await.unwrap().status(),401);assert_eq!(http.put(&target).bearer_auth(HOST_TOKEN).header("X-Agent-Client","model").json(&json!({"paused":false})).send().await.unwrap().status(),403);assert_eq!(http.post(&target).bearer_auth(HOST_TOKEN).json(&json!({})).send().await.unwrap().status(),405);
    stop.cancel();server.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn notification_preferences_invalid_input_and_saved_data_fail_closed_and_remain_repairable(){
    let mut c=notification_fixture().await;let (url,stop,server)=http_fixture().await;let http=client();let target=format!("{url}/api/v1/dashboard/notification-preferences");
    for value in [json!({"telegram":true}),json!({"whatsapp":true}),json!({"browser_push":true}),json!({"timezone":"../../private-owner-file"}),json!({"quiet_start":24}),json!({"arbitrary_token":"fictional_rejected_value"})] {let response=http.put(&target).bearer_auth(HOST_TOKEN).json(&value).send().await.unwrap();assert_eq!(response.status(),422);assert!(!response.text().await.unwrap().contains("fictional_rejected_value"));}
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE key='notifications'").fetch_one(&mut c).await.unwrap(),0);
    sqlx::query("INSERT INTO owner_preferences(key,value) VALUES('notifications','{\"telegram\":true,\"private_canary\":\"fictional-secret\"}')").execute(&mut c).await.unwrap();
    let response=http.get(&target).bearer_auth(HOST_TOKEN).send().await.unwrap();assert_eq!(response.status(),503);assert!(!response.text().await.unwrap().contains("fictional-secret"));
    let response=http.put(&target).bearer_auth(HOST_TOKEN).json(&json!({"paused":true})).send().await.unwrap();assert_eq!(response.status(),200);assert_eq!(response.json::<Value>().await.unwrap()["paused"],true);
    stop.cancel();server.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn notification_preferences_suppressed_and_deferred_commit_failures_never_acknowledge_success(){
    let mut c=notification_fixture().await;let original=automated_apply_agents::notification_preferences::normalize(json!({"paused":true})).unwrap();sqlx::query("INSERT INTO owner_preferences(key,value) VALUES('notifications',$1)").bind(&original).execute(&mut c).await.unwrap();
    let (url,stop,server)=http_fixture().await;let http=client();let target=format!("{url}/api/v1/dashboard/notification-preferences");
    sqlx::raw_sql("CREATE FUNCTION fixture_pref_suppress() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.key='notifications' THEN RETURN NULL; END IF; RETURN NEW; END $$; CREATE TRIGGER fixture_pref_suppress BEFORE UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_pref_suppress()").execute(&mut c).await.unwrap();
    assert_eq!(http.put(&target).bearer_auth(HOST_TOKEN).json(&json!({"paused":false})).send().await.unwrap().status(),409);
    assert_eq!(sqlx::query_scalar::<_,Value>("SELECT value FROM owner_preferences WHERE key='notifications'").fetch_one(&mut c).await.unwrap(),original);
    sqlx::raw_sql("DROP TRIGGER fixture_pref_suppress ON owner_preferences; DROP FUNCTION fixture_pref_suppress(); CREATE FUNCTION fixture_pref_deferred_failure() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fictional preference commit rejection'; END $$; CREATE CONSTRAINT TRIGGER fixture_pref_deferred_failure AFTER INSERT OR UPDATE ON owner_preferences DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.key='notifications') EXECUTE FUNCTION fixture_pref_deferred_failure()").execute(&mut c).await.unwrap();
    let response=http.put(&target).bearer_auth(HOST_TOKEN).json(&json!({"paused":false})).send().await.unwrap();assert_eq!(response.status(),503);assert!(!response.headers().contains_key("X-Automated-Apply-Transaction"));
    assert_eq!(sqlx::query_scalar::<_,Value>("SELECT value FROM owner_preferences WHERE key='notifications'").fetch_one(&mut c).await.unwrap(),original);
    sqlx::raw_sql("DROP TRIGGER fixture_pref_deferred_failure ON owner_preferences; DROP FUNCTION fixture_pref_deferred_failure()").execute(&mut c).await.unwrap();stop.cancel();server.await.unwrap();
}
