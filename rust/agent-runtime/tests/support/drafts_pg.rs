async fn draft_fixture()->PgConnection{
    let mut c=profile_fixture().await;sqlx::raw_sql(include_str!("../fixtures/drafts.sql")).execute(&mut c).await.unwrap();c
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn saved_answer_draft_list_and_owner_review_are_scoped_committed_and_not_submission_authority(){
    let mut c=draft_fixture().await;let (url,stop,server)=http_fixture().await;let http=client();let list=format!("{url}/api/v1/application-answers/drafts");
    assert_eq!(http.get(&list).send().await.unwrap().status(),401);
    let response=http.get(format!("{list}?limit=1")).bearer_auth(HOST_TOKEN).send().await.unwrap();assert_eq!(response.status(),200);let rows:Value=response.json().await.unwrap();assert_eq!(rows.as_array().unwrap().len(),1);assert_eq!(rows[0]["answer"],"I built fictional Rust workers.");assert_eq!(rows[0]["stale"],false);
    let all:Value=http.get(&list).bearer_auth(HOST_TOKEN).send().await.unwrap().json().await.unwrap();assert_eq!(all.as_array().unwrap().len(),2);assert_eq!(all[1]["stale"],true);
    for query in ["limit=101","offset=-1","limit=1&limit=2"]{assert_eq!(http.get(format!("{list}?{query}")).bearer_auth(HOST_TOKEN).send().await.unwrap().status(),422);}
    let item=format!("{list}/30000000-0000-0000-0000-000000000001");
    assert_eq!(http.patch(&item).bearer_auth(HOST_TOKEN).header("x-agent-client","extension").json(&json!({"review_status":"reviewed"})).send().await.unwrap().status(),403);
    let reviewed:Value=http.patch(&item).bearer_auth(HOST_TOKEN).json(&json!({"review_status":"reviewed"})).send().await.unwrap().json().await.unwrap();assert_eq!(reviewed["review_status"],"reviewed");assert_eq!(reviewed["stale"],false);assert_eq!(reviewed["answer"],rows[0]["answer"]);
    let mut observer=connection().await;assert_eq!(sqlx::query_scalar::<_,String>("SELECT review_status FROM application_answer_drafts WHERE id='30000000-0000-0000-0000-000000000001'").fetch_one(&mut observer).await.unwrap(),"reviewed");
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_packets").fetch_one(&mut c).await.unwrap(),0);assert_eq!(profile_store::get(&mut c).await.unwrap().version,4);
    stop.cancel();server.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn saved_answer_stale_review_is_rejected_while_discard_and_exact_owner_status_remain_available(){
    let mut c=draft_fixture().await;let (url,stop,server)=http_fixture().await;let http=client();let root=format!("{url}/api/v1/application-answers/drafts");let stale=format!("{root}/30000000-0000-0000-0000-000000000002");
    let response=http.patch(&stale).bearer_auth(HOST_TOKEN).json(&json!({"review_status":"reviewed"})).send().await.unwrap();assert_eq!(response.status(),409);assert_eq!(response.json::<Value>().await.unwrap()["detail"],"Draft is stale; regenerate or correct the profile before reviewing");
    let discarded:Value=http.patch(&stale).bearer_auth(HOST_TOKEN).json(&json!({"review_status":"discarded"})).send().await.unwrap().json().await.unwrap();assert_eq!(discarded["review_status"],"discarded");assert_eq!(discarded["stale"],true);
    for input in [json!({}),json!({"review_status":" reviewed "}),json!({"review_status":"submitted"}),json!({"review_status":"reviewed","approve":true})]{assert_eq!(http.patch(&stale).bearer_auth(HOST_TOKEN).json(&input).send().await.unwrap().status(),422);}
    let foreign=format!("{root}/30000000-0000-0000-0000-000000000003");assert_eq!(http.patch(&foreign).bearer_auth(HOST_TOKEN).json(&json!({"review_status":"reviewed"})).send().await.unwrap().status(),404);
    let method=http.post(&stale).bearer_auth(HOST_TOKEN).send().await.unwrap();assert_eq!(method.status(),405);assert_eq!(method.headers()["allow"],"PATCH");
    assert_eq!(sqlx::query_scalar::<_,String>("SELECT review_status FROM application_answer_drafts WHERE id='30000000-0000-0000-0000-000000000003'").fetch_one(&mut c).await.unwrap(),"draft");
    stop.cancel();server.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn saved_answer_review_waits_for_concurrent_profile_correction_and_rejects_old_version(){
    use automated_apply_agents::answer_store::{self,Review,ReviewStatus};
    let mut c=draft_fixture().await;let mut writer=connection().await;
    let mut transaction=writer.begin().await.unwrap();sqlx::query("UPDATE candidate_profiles SET version=5 WHERE singleton_key='primary'").execute(&mut *transaction).await.unwrap();
    let pending=answer_store::review(&mut c,Uuid::from_u128(0x30000000000000000000000000000001),Review{review_status:ReviewStatus::Reviewed});tokio::pin!(pending);
    assert!(tokio::time::timeout(Duration::from_millis(80),&mut pending).await.is_err());transaction.commit().await.unwrap();assert_eq!(pending.await.err(),Some(Failure("answer_draft_stale")));
    assert_eq!(sqlx::query_scalar::<_,String>("SELECT review_status FROM application_answer_drafts WHERE id='30000000-0000-0000-0000-000000000001'").fetch_one(&mut writer).await.unwrap(),"draft");
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn saved_answer_bad_return_record_and_deferred_commit_both_rollback_review(){
    use automated_apply_agents::answer_store::{self,Review,ReviewStatus};let mut c=draft_fixture().await;
    let id=Uuid::from_u128(0x30000000000000000000000000000001);
    sqlx::raw_sql("CREATE OR REPLACE FUNCTION fixture_draft_time() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.updated_at='infinity'; RETURN NEW;END $$;CREATE TRIGGER fixture_draft_time BEFORE UPDATE ON application_answer_drafts FOR EACH ROW EXECUTE FUNCTION fixture_draft_time()").execute(&mut c).await.unwrap();
    assert_eq!(answer_store::review(&mut c,id,Review{review_status:ReviewStatus::Reviewed}).await.err(),Some(Failure("invalid_answer_draft_record")));
    assert_eq!(sqlx::query_scalar::<_,String>("SELECT review_status FROM application_answer_drafts WHERE id=$1").bind(id).fetch_one(&mut c).await.unwrap(),"draft");
    sqlx::raw_sql("DROP TRIGGER fixture_draft_time ON application_answer_drafts;CREATE OR REPLACE FUNCTION fixture_draft_commit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fictional_draft_commit_rejected';RETURN NEW;END $$;CREATE CONSTRAINT TRIGGER fixture_draft_commit AFTER UPDATE ON application_answer_drafts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fixture_draft_commit()").execute(&mut c).await.unwrap();
    assert_eq!(answer_store::review(&mut c,id,Review{review_status:ReviewStatus::Reviewed}).await.err(),Some(Failure("profile_database_error")));
    assert_eq!(sqlx::query_scalar::<_,String>("SELECT review_status FROM application_answer_drafts WHERE id=$1").bind(id).fetch_one(&mut c).await.unwrap(),"draft");
}
