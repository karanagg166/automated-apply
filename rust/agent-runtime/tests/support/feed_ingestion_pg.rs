async fn ingestion_fixture()->(PgConnection,Uuid) {
    let (mut c,_)=packet_service_fixture().await;
    sqlx::raw_sql("ALTER TABLE owner_preferences ALTER COLUMN key TYPE VARCHAR(50); ALTER TABLE jobs ADD COLUMN canonical_key text UNIQUE; DROP TABLE job_source_observations").execute(&mut c).await.unwrap();
    let source=include_str!("../../../../supabase/fresh_public/001_phase1_public.sql");
    let table=source.split("CREATE TABLE IF NOT EXISTS public.job_source_observations (").nth(1).unwrap().split("CREATE INDEX IF NOT EXISTS idx_observation_job").next().unwrap();
    sqlx::raw_sql(sqlx::AssertSqlSafe(format!("CREATE TABLE IF NOT EXISTS public.job_source_observations ({table}"))).execute(&mut c).await.unwrap();
    use automated_apply_agents::public_discovery::{self,Platform,Reservation};
    let (token,record)=match public_discovery::reserve(&mut c,Platform::Himalayas,20).await.unwrap(){Reservation::Fetch{token,record}=>(token,record),_=>panic!()};
    let batch=public_discovery::himalayas(br#"{"jobs":[{"guid":"fixture-intake","title":"Rust Developer","companyName":"Example","applicationLink":"https://himalayas.app/companies/example/jobs/intake?ref=original","description":"Short untrusted description","pubDate":1794690000}]}"#).unwrap();
    let output=public_discovery::finish(&mut c,Platform::Himalayas,token,record,Ok(batch),20).await.unwrap();assert_eq!(output["batch_token"],json!(token));
    (c,token)
}
async fn intake(c:&mut PgConnection,token:Uuid)->Result<Value>{automated_apply_agents::feed_ingestion::ingest(c,automated_apply_agents::public_discovery::Platform::Himalayas,automated_apply_agents::feed_ingestion::Input{batch_token:token}).await}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn feed_intake_replay_preserves_owner_decisions_original_link_and_unknown_posting_age(){
    let (mut c,t)=ingestion_fixture().await;let first=intake(&mut c,t).await.unwrap();assert_eq!(first["inserted_count"],1);let id=first["job_ids"][0].as_str().unwrap().parse::<Uuid>().unwrap();
    let row:Value=sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1").bind(id).fetch_one(&mut c).await.unwrap();assert_eq!(row["application_url"],"https://himalayas.app/companies/example/jobs/intake?ref=original");assert_eq!(row["date_posted"],Value::Null);assert_eq!(row["company_id"],Value::Null);assert_eq!(row["skills_required"],json!([]));
    sqlx::query("UPDATE jobs SET status='applied',title='Owner corrected title' WHERE id=$1").bind(id).execute(&mut c).await.unwrap();assert_eq!(intake(&mut c,t).await.unwrap(),first);
    let state:(String,String)=sqlx::query_as("SELECT status,title FROM jobs WHERE id=$1").bind(id).fetch_one(&mut c).await.unwrap();assert_eq!(state,("applied".into(),"Owner corrected title".into()));
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn feed_intake_conflicting_stale_and_forged_cache_cannot_write_jobs(){
    let (mut c,t)=ingestion_fixture().await;assert_eq!(intake(&mut c,Uuid::new_v4()).await.unwrap_err().0,"feed_batch_changed");
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{batch,jobs,0,application_url}','\"https://evil.example/job\"') WHERE key='public_feed:himalayas'").execute(&mut c).await.unwrap();assert!(intake(&mut c,t).await.is_err());
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{fetched_at}','1') WHERE key='public_feed:himalayas'").execute(&mut c).await.unwrap();assert_eq!(intake(&mut c,t).await.unwrap_err().0,"feed_batch_stale");
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM job_source_observations").fetch_one(&mut c).await.unwrap(),0);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn feed_intake_suppressed_observation_rolls_back_new_job_and_receipt(){
    let (mut c,t)=ingestion_fixture().await;let count:i64=sqlx::query_scalar("SELECT count(*) FROM jobs").fetch_one(&mut c).await.unwrap();
    sqlx::raw_sql("CREATE FUNCTION intake_suppress() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NULL; END $$; CREATE TRIGGER intake_suppress BEFORE INSERT ON job_source_observations FOR EACH ROW EXECUTE FUNCTION intake_suppress()").execute(&mut c).await.unwrap();
    assert_eq!(intake(&mut c,t).await.unwrap_err().0,"feed_ingestion_write_ack_failed");
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM jobs").fetch_one(&mut c).await.unwrap(),count);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'feed_in:')").fetch_one(&mut c).await.unwrap(),0);
    sqlx::raw_sql("DROP TRIGGER intake_suppress ON job_source_observations; DROP FUNCTION intake_suppress()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn feed_intake_concurrent_calls_commit_one_job_and_one_ledger(){
    let (mut a,t)=ingestion_fixture().await;let mut b=connection().await;
    let (left,right)=tokio::join!(intake(&mut a,t),intake(&mut b,t));assert_eq!(left.unwrap(),right.unwrap());
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'feed_in:')").fetch_one(&mut a).await.unwrap(),1);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn feed_intake_new_batch_deduplicates_without_overwriting_owner_state(){
    let (mut c,t)=ingestion_fixture().await;let first=intake(&mut c,t).await.unwrap();let id=first["job_ids"][0].as_str().unwrap().parse::<Uuid>().unwrap();
    sqlx::query("UPDATE jobs SET status='archived',title='Owner title',application_url='https://himalayas.app/jobs/owner-link' WHERE id=$1").bind(id).execute(&mut c).await.unwrap();
    let next=Uuid::new_v4();sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{token}',$1) WHERE key='public_feed:himalayas'").bind(json!(next)).execute(&mut c).await.unwrap();
    let result=intake(&mut c,next).await.unwrap();assert_eq!(result["inserted_count"],0);assert_eq!(result["duplicate_count"],1);assert_eq!(result["job_ids"],first["job_ids"]);
    let row:Value=sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1").bind(id).fetch_one(&mut c).await.unwrap();assert_eq!(row["status"],"archived");assert_eq!(row["title"],"Owner title");assert_eq!(row["application_url"],"https://himalayas.app/jobs/owner-link");
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn feed_intake_expiry_and_truncated_preview_never_become_complete_eligibility(){
    let (mut c,t)=ingestion_fixture().await;
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(jsonb_set(value,'{batch,jobs,0,description_truncated}','true'),'{batch,jobs,0,expires_at}','\"2000-01-01T00:00:00Z\"') WHERE key='public_feed:himalayas'").execute(&mut c).await.unwrap();
    assert_eq!(intake(&mut c,t).await.unwrap()["expired_count"],1);
    let next=Uuid::new_v4();sqlx::query("UPDATE owner_preferences SET value=jsonb_set(jsonb_set(value,'{token}',$1),'{batch,jobs,0,expires_at}','null') WHERE key='public_feed:himalayas'").bind(json!(next)).execute(&mut c).await.unwrap();
    let result=intake(&mut c,next).await.unwrap();let id=result["job_ids"][0].as_str().unwrap().parse::<Uuid>().unwrap();let row:Value=sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1").bind(id).fetch_one(&mut c).await.unwrap();assert_eq!(row["description"],Value::Null);assert_eq!(row["discovery_metadata"]["description_truncated"],true);assert_eq!(row["discovery_metadata"]["eligibility_verified"],false);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn feed_intake_http_auth_method_validation_and_committed_readback(){
    let (mut c,t)=ingestion_fixture().await;let (url,stop,server)=http_fixture().await;let http=client();let endpoint=format!("{url}/api/v1/rust-agent/platforms/himalayas/ingest");
    assert_eq!(http.post(&endpoint).json(&json!({"batch_token":t})).send().await.unwrap().status(),401);
    assert_eq!(http.get(&endpoint).bearer_auth(HOST_TOKEN).send().await.unwrap().status(),405);
    assert_eq!(http.post(&endpoint).bearer_auth(HOST_TOKEN).json(&json!({"jobs":[]})).send().await.unwrap().status(),422);
    let response=http.post(&endpoint).bearer_auth(HOST_TOKEN).json(&json!({"batch_token":t})).send().await.unwrap();let status=response.status();let body:Value=response.json().await.unwrap();assert_eq!(status,200,"{body}");assert_eq!(body["inserted_count"],1);assert_eq!(body["application_dispatch"],false);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM job_source_observations").fetch_one(&mut c).await.unwrap(),1);
    stop.cancel();server.await.unwrap();
}
