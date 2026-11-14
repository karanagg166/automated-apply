fn owner_proof_fixture()->(automated_apply_agents::owner_proof::SigningKey,Value){
    let cases:Vec<Value>=serde_json::from_str(include_str!("../fixtures/owner-proof-corpus.json")).unwrap();let case=cases[0].clone();
    let key=automated_apply_agents::owner_proof::SigningKey::from_values(&std::collections::BTreeMap::from([("BROWSER_OWNER_APPROVAL_KEY".into(),case["key"].as_str().unwrap().into())])).unwrap().unwrap();(key,case)
}
fn verified_proof(key:&automated_apply_agents::owner_proof::SigningKey,case:&Value)->automated_apply_agents::owner_proof::Proof{
    key.verify_at(case["path"].as_str().unwrap(),case["body"].as_str().unwrap().as_bytes(),case["header"].as_str().unwrap(),case["timestamp"].as_u64().unwrap() as f64).unwrap()
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn owner_approval_nonce_commits_once_and_survives_connection_restart_without_other_effects(){
    let mut c=confirmation_fixture().await;let (key,case)=owner_proof_fixture();let nonce_key=format!("owner-proof:{}",case["nonce"].as_str().unwrap());
    let before:Value=sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key='phase1_profile_confirmation'").fetch_one(&mut c).await.unwrap();
    let mut transaction=c.begin().await.unwrap();verified_proof(&key,&case).claim(&mut transaction).await.unwrap();transaction.commit().await.unwrap();drop(c);
    let mut observer=connection().await;let stored:Value=sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1").bind(&nonce_key).fetch_one(&mut observer).await.unwrap();assert_eq!(stored,json!({"operation":case["path"]}));
    let mut replay=observer.begin().await.unwrap();assert_eq!(verified_proof(&key,&case).claim(&mut replay).await.err(),Some(Failure("owner_approval_already_used")));replay.rollback().await.unwrap();
    assert_eq!(sqlx::query_scalar::<_,Value>("SELECT value FROM owner_preferences WHERE key='phase1_profile_confirmation'").fetch_one(&mut observer).await.unwrap(),before);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_packets").fetch_one(&mut observer).await.unwrap(),0);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM llm_monthly_usage").fetch_one(&mut observer).await.unwrap(),0);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn owner_approval_nonce_rolls_back_with_effect_or_deferred_commit_failure(){
    let mut c=confirmation_fixture().await;let (key,case)=owner_proof_fixture();
    let mut transaction=c.begin().await.unwrap();verified_proof(&key,&case).claim(&mut transaction).await.unwrap();transaction.rollback().await.unwrap();
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE key LIKE 'owner-proof:%'").fetch_one(&mut c).await.unwrap(),0);
    sqlx::raw_sql("CREATE OR REPLACE FUNCTION fixture_owner_proof_reject() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.key LIKE 'owner-proof:%' THEN RAISE EXCEPTION 'fictional_proof_commit_rejected'; END IF;RETURN NEW;END $$;CREATE CONSTRAINT TRIGGER fixture_owner_proof_commit AFTER INSERT ON owner_preferences DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fixture_owner_proof_reject()").execute(&mut c).await.unwrap();
    let mut transaction=c.begin().await.unwrap();verified_proof(&key,&case).claim(&mut transaction).await.unwrap();assert!(transaction.commit().await.is_err());
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE key LIKE 'owner-proof:%'").fetch_one(&mut c).await.unwrap(),0);
    sqlx::query("DROP TRIGGER fixture_owner_proof_commit ON owner_preferences").execute(&mut c).await.unwrap();
    let mut transaction=c.begin().await.unwrap();verified_proof(&key,&case).claim(&mut transaction).await.unwrap();transaction.commit().await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn concurrent_owner_proof_claims_have_one_committed_winner(){
    let mut c=confirmation_fixture().await;let mut second=connection().await;let (key,case)=owner_proof_fixture();
    let mut first=c.begin().await.unwrap();verified_proof(&key,&case).claim(&mut first).await.unwrap();
    let mut contender=second.begin().await.unwrap();let pending=verified_proof(&key,&case).claim(&mut contender);tokio::pin!(pending);
    assert!(tokio::time::timeout(Duration::from_millis(80),&mut pending).await.is_err());first.commit().await.unwrap();assert_eq!(pending.await.err(),Some(Failure("owner_approval_already_used")));
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE key LIKE 'owner-proof:%'").fetch_one(&mut c).await.unwrap(),1);
}
