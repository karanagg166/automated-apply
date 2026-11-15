struct FeedProvider {calls:usize,fail:bool}
impl automated_apply_agents::discovery_schedule::Provider for FeedProvider {
    async fn fetch(&mut self,p:automated_apply_agents::public_discovery::Platform)->Result<automated_apply_agents::public_discovery::Batch>{
        self.calls+=1;if self.fail{return Err(Failure("public_feed_rate_limited"));}
        Ok(automated_apply_agents::public_discovery::Batch{platform:p,jobs:vec![],has_more:false,skipped_invalid:0,duplicate_count:0})
    }
}
async fn enable_schedule(c:&mut PgConnection,names:Value){
    let input=automated_apply_agents::discovery_schedule::request(json!({"expected_revision":0,"enabled":names}).to_string().as_bytes()).unwrap();
    automated_apply_agents::discovery_schedule::update(c,input).await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn discovery_schedule_disabled_default_and_stopped_control_do_not_dispatch(){
    use automated_apply_agents::discovery_schedule;
    let (mut c,_)=ingestion_fixture().await;let mut provider=FeedProvider{calls:0,fail:false};
    assert_eq!(discovery_schedule::policy(&mut c).await.unwrap().revision,0);
    discovery_schedule::tick(&mut c,&mut provider).await.unwrap();assert_eq!(provider.calls,0);
    enable_schedule(&mut c,json!(["himalayas"])).await;
    sqlx::query("UPDATE rust_agent_control SET mode='STOPPED'").execute(&mut c).await.unwrap();
    discovery_schedule::tick(&mut c,&mut provider).await.unwrap();assert_eq!(provider.calls,0);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM job_source_observations").fetch_one(&mut c).await.unwrap(),0);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn discovery_schedule_ingests_cached_batch_once_without_network_and_then_respects_cooldown(){
    use automated_apply_agents::discovery_schedule;
    let (mut c,_)=ingestion_fixture().await;enable_schedule(&mut c,json!(["himalayas"])).await;let mut provider=FeedProvider{calls:0,fail:false};
    discovery_schedule::tick(&mut c,&mut provider).await.unwrap();discovery_schedule::tick(&mut c,&mut provider).await.unwrap();
    assert_eq!(provider.calls,0);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM job_source_observations").fetch_one(&mut c).await.unwrap(),1);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn discovery_schedule_failed_source_retains_cooldown_and_does_not_starve_other_source(){
    use automated_apply_agents::discovery_schedule;
    let (mut c,_)=ingestion_fixture().await;sqlx::query("DELETE FROM owner_preferences WHERE key='public_feed:himalayas'").execute(&mut c).await.unwrap();enable_schedule(&mut c,json!(["himalayas","we_work_remotely"])).await;
    let mut provider=FeedProvider{calls:0,fail:true};discovery_schedule::tick(&mut c,&mut provider).await.unwrap();discovery_schedule::tick(&mut c,&mut provider).await.unwrap();discovery_schedule::tick(&mut c,&mut provider).await.unwrap();assert_eq!(provider.calls,2);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'public_feed:') AND value->>'state'='failed'").fetch_one(&mut c).await.unwrap(),2);
    assert_eq!(discovery_schedule::status(&mut c).await.unwrap()["last_status"]["error_code"],"public_feed_rate_limited");
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn discovery_schedule_revisions_conflict_and_suppressed_update_cannot_enable_work(){
    use automated_apply_agents::discovery_schedule;
    let (mut c,_)=ingestion_fixture().await;enable_schedule(&mut c,json!([])).await;
    let stale=discovery_schedule::request(br#"{"expected_revision":0,"enabled":["himalayas"]}"#).unwrap();assert_eq!(discovery_schedule::update(&mut c,stale).await.err().unwrap().0,"discovery_schedule_revision_conflict");
    sqlx::raw_sql("CREATE FUNCTION suppress_schedule() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.key='public_feed_schedule' THEN RETURN NULL; END IF; RETURN NEW; END $$; CREATE TRIGGER suppress_schedule BEFORE UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION suppress_schedule()").execute(&mut c).await.unwrap();
    let input=discovery_schedule::request(br#"{"expected_revision":1,"enabled":["himalayas"]}"#).unwrap();assert_eq!(discovery_schedule::update(&mut c,input).await.err().unwrap().0,"discovery_schedule_write_ack_failed");assert!(discovery_schedule::policy(&mut c).await.unwrap().enabled.is_empty());
    sqlx::raw_sql("DROP TRIGGER suppress_schedule ON owner_preferences; DROP FUNCTION suppress_schedule()").execute(&mut c).await.unwrap();
}
struct StopDuringFetch;
impl automated_apply_agents::discovery_schedule::Provider for StopDuringFetch {
    async fn fetch(&mut self,_:automated_apply_agents::public_discovery::Platform)->Result<automated_apply_agents::public_discovery::Batch>{
        let mut owner=connection().await;sqlx::query("UPDATE rust_agent_control SET mode='STOPPED'").execute(&mut owner).await.unwrap();
        automated_apply_agents::public_discovery::himalayas(br#"{"jobs":[{"guid":"stopped-fixture","title":"Engineer","applicationLink":"https://himalayas.app/jobs/stopped-fixture"}]}"#)
    }
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn discovery_schedule_stop_during_fetch_preserves_cache_and_defers_ingestion_until_resume(){
    use automated_apply_agents::discovery_schedule;
    let (mut c,_)=ingestion_fixture().await;sqlx::query("DELETE FROM owner_preferences WHERE key='public_feed:himalayas'").execute(&mut c).await.unwrap();enable_schedule(&mut c,json!(["himalayas"])).await;
    discovery_schedule::tick(&mut c,&mut StopDuringFetch).await.unwrap();assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM job_source_observations").fetch_one(&mut c).await.unwrap(),0);
    sqlx::query("UPDATE rust_agent_control SET mode='RUNNING'").execute(&mut c).await.unwrap();let mut provider=FeedProvider{calls:0,fail:false};discovery_schedule::tick(&mut c,&mut provider).await.unwrap();assert_eq!(provider.calls,0);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM job_source_observations").fetch_one(&mut c).await.unwrap(),1);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn discovery_schedule_owner_http_updates_are_authenticated_revisioned_and_never_start_application_work(){
    let (_c,_)=ingestion_fixture().await;let (url,stop,server)=http_fixture().await;let http=client();let endpoint=format!("{url}/api/v1/rust-agent/discovery/schedule");
    assert_eq!(http.get(&endpoint).send().await.unwrap().status(),401);
    let initial:Value=http.get(&endpoint).bearer_auth(HOST_TOKEN).send().await.unwrap().json().await.unwrap();assert_eq!(initial["policy"]["enabled"],json!([]));assert_eq!(initial["application_dispatch"],false);
    assert_eq!(http.put(&endpoint).bearer_auth(HOST_TOKEN).json(&json!({"expected_revision":0,"enabled":["himalayas"],"apply":true})).send().await.unwrap().status(),422);
    let response=http.put(&endpoint).bearer_auth(HOST_TOKEN).json(&json!({"expected_revision":0,"enabled":["himalayas"]})).send().await.unwrap();assert_eq!(response.status(),200);let saved:Value=response.json().await.unwrap();assert_eq!(saved["policy"]["revision"],1);
    assert_eq!(http.put(&endpoint).bearer_auth(HOST_TOKEN).json(&json!({"expected_revision":0,"enabled":[]})).send().await.unwrap().status(),409);
    stop.cancel();server.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn discovery_schedule_intake_transaction_independently_fences_stopped_or_revised_authority(){
    use automated_apply_agents::{discovery_schedule,feed_ingestion,public_discovery::Platform};
    let (mut c,t)=ingestion_fixture().await;enable_schedule(&mut c,json!(["himalayas"])).await;
    sqlx::query("UPDATE rust_agent_control SET mode='STOPPED'").execute(&mut c).await.unwrap();
    assert_eq!(feed_ingestion::ingest_scheduled(&mut c,Platform::Himalayas,feed_ingestion::Input{batch_token:t},1).await.unwrap_err().0,"discovery_schedule_changed");
    sqlx::query("UPDATE rust_agent_control SET mode='RUNNING'").execute(&mut c).await.unwrap();
    let update=discovery_schedule::request(br#"{"expected_revision":1,"enabled":[]}"#).unwrap();discovery_schedule::update(&mut c,update).await.unwrap();
    assert_eq!(feed_ingestion::ingest_scheduled(&mut c,Platform::Himalayas,feed_ingestion::Input{batch_token:t},1).await.unwrap_err().0,"discovery_schedule_changed");
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM job_source_observations").fetch_one(&mut c).await.unwrap(),0);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn discovery_schedule_cached_feed_reads_revalidate_destinations_before_exposing_links(){
    use automated_apply_agents::public_discovery::{self,Platform};
    let (mut c,_)=ingestion_fixture().await;
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{batch,jobs,0,application_url}','\"javascript:alert(1)\"') WHERE key='public_feed:himalayas'").execute(&mut c).await.unwrap();
    assert_eq!(public_discovery::reserve(&mut c,Platform::Himalayas,20).await.err().unwrap().0,"public_feed_saved_state_invalid");
}
