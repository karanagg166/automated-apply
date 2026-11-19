const MISSING_SIGNING_KEY: &str = "fictional-separate-owner-key-0123456789";
fn missing_signature(path: &str, body: &[u8], nonce: &str, seconds: i64) -> String {
    use hmac::{Hmac, KeyInit, Mac};
    use sha2::{Digest, Sha256};
    let timestamp = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs() as i64 + seconds;
    let mut mac = Hmac::<sha2_hmac::Sha256>::new_from_slice(MISSING_SIGNING_KEY.as_bytes()).unwrap();
    mac.update(format!("POST\n{path}\n{timestamp}\n{nonce}\n{:x}", Sha256::digest(body)).as_bytes());
    let hex = mac.finalize().into_bytes().iter().map(|b|format!("{b:02x}")).collect::<String>();
    format!("v1:{timestamp}:{nonce}:{hex}")
}
fn missing_proof(path: &str, body: &[u8], nonce: &str) -> automated_apply_agents::owner_proof::Proof {
    let values=BTreeMap::from([("BROWSER_OWNER_APPROVAL_KEY".into(),MISSING_SIGNING_KEY.into())]);
    let key=automated_apply_agents::owner_proof::SigningKey::from_values(&values).unwrap().unwrap();
    let now=std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs_f64();
    key.verify_at(path,body,&missing_signature(path,body,nonce,0),now).unwrap()
}
async fn missing_fixture() -> PgConnection {
    let mut c = resource_fixture().await;
    sqlx::raw_sql(include_str!("../fixtures/drafts.sql")).execute(&mut c).await.unwrap();
    c
}
fn missing_create(question: &str) -> automated_apply_agents::missing_contract::Create {
    automated_apply_agents::missing_contract::normalize_create(json!({"question":question,"missing_fact":"Provide the exact factual value","required_input_type":"text"})).unwrap()
}
async fn missing_edit(c: &mut PgConnection, id: &str, version: u64) -> Value {
    automated_apply_agents::missing_store::edit(c,id,automated_apply_agents::missing_contract::normalize_edit(json!({"expected_version":version,"answer":"Owner confirmed fictional fact","evidence_note":"Direct owner factual statement"})).unwrap()).await.unwrap()
}
async fn missing_approve(c: &mut PgConnection,id:&str,version:u64,nonce:&str) -> Result<Value> {
    let body=json!({"expected_version":version,"expected_profile_version":4,"factual_confirmation":true});
    let path=format!("/api/v1/application-answers/missing/{id}/approve");
    automated_apply_agents::missing_store::approve(c,id,automated_apply_agents::missing_contract::normalize_approve(body.clone()).unwrap(),missing_proof(&path,body.to_string().as_bytes(),nonce)).await
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn missing_answer_owner_http_lifecycle_is_durable_exact_context_and_never_submission_authority() {
    use automated_apply_agents::{answer_contract,missing_store};
    let mut c=missing_fixture().await;
    let mut values=host_values();values.insert("BROWSER_OWNER_APPROVAL_KEY".into(),MISSING_SIGNING_KEY.into());
    let (url,stop,server)=http_fixture_values(values).await;let http=client();let root=format!("{url}/api/v1/application-answers/missing");
    assert_eq!(http.post(&root).body("bad json").send().await.unwrap().status(),401);
    let input=json!({"question":"Preferred interview time?","missing_fact":"Exact owner preference"});
    assert_eq!(http.post(&root).bearer_auth(HOST_TOKEN).header("x-agent-client","extension").json(&input).send().await.unwrap().status(),403);
    let response=http.post(&root).bearer_auth(HOST_TOKEN).json(&input).send().await.unwrap();assert_eq!(response.status(),201);
    let created:Value=response.json().await.unwrap();let id=created["id"].as_str().unwrap();let item=format!("{root}/{id}");assert_eq!(created["status"],"needs_input");assert_eq!(created["stale"],false);assert_eq!(created["ever_approved"],false);
    let duplicate:Value=http.post(&root).bearer_auth(HOST_TOKEN).json(&input).send().await.unwrap().json().await.unwrap();assert_eq!(duplicate,created);
    let edit=json!({"expected_version":1,"answer":"Weekday afternoons","evidence_note":"Direct owner statement"});
    let edited:Value=http.patch(&item).bearer_auth(HOST_TOKEN).json(&edit).send().await.unwrap().json().await.unwrap();assert_eq!(edited["version"],2);assert_eq!(edited["status"],"draft");
    let body=json!({"expected_version":2,"expected_profile_version":4,"factual_confirmation":true}).to_string();let path=format!("/api/v1/application-answers/missing/{id}/approve");let endpoint=format!("{url}{path}");let nonce=Uuid::new_v4().simple().to_string();let signature=missing_signature(&path,body.as_bytes(),&nonce,0);
    assert_eq!(http.post(&endpoint).bearer_auth(HOST_TOKEN).body(body.clone()).send().await.unwrap().status(),403);
    let response=http.post(&endpoint).bearer_auth(HOST_TOKEN).header("X-Browser-Owner-Approval",&signature).body(body.clone()).send().await.unwrap();assert_eq!(response.status(),200);let approved:Value=response.json().await.unwrap();assert_eq!(approved["status"],"approved");assert_eq!(approved["version"],3);assert_eq!(approved["ever_approved"],true);
    let mut observer=connection().await;
    assert_eq!(missing_store::read(&mut observer,id).await.unwrap(),approved);
    let draft:Uuid=approved["draft_id"].as_str().unwrap().parse().unwrap();assert_eq!(sqlx::query_scalar::<_,String>("SELECT review_status FROM application_answer_drafts WHERE id=$1").bind(draft).fetch_one(&mut observer).await.unwrap(),"reviewed");
    let request=answer_contract::normalize(json!({"question":"Preferred interview time?"})).unwrap();let mut tx=observer.begin().await.unwrap();sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY").execute(&mut *tx).await.unwrap();assert_eq!(missing_store::approved_in(&mut tx,&request).await.unwrap().unwrap()["answer"],"Weekday afternoons");tx.commit().await.unwrap();
    let history:Value=http.get(format!("{item}/history")).bearer_auth(HOST_TOKEN).send().await.unwrap().json().await.unwrap();assert_eq!(history["history"].as_array().unwrap().len(),2);assert_eq!(history["history"][0]["operation"],"approved_exact_context");assert_eq!(history["history"][0]["previous"]["status"],"draft");
    let page:Value=http.get(format!("{root}?limit=1")).bearer_auth(HOST_TOKEN).send().await.unwrap().json().await.unwrap();assert_eq!(page["requests"],json!([approved]));
    for query in ["limit=101","limit=1&limit=2","offset=-1","unknown=1"] {assert_eq!(http.get(format!("{root}?{query}")).bearer_auth(HOST_TOKEN).send().await.unwrap().status(),422);}
    let edited=missing_edit(&mut c,id,3).await;assert_eq!(edited["status"],"draft");assert_eq!(edited["draft_id"],Value::Null);assert_eq!(sqlx::query_scalar::<_,String>("SELECT review_status FROM application_answer_drafts WHERE id=$1").bind(draft).fetch_one(&mut observer).await.unwrap(),"discarded");
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_packets").fetch_one(&mut c).await.unwrap(),0);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM llm_monthly_usage").fetch_one(&mut c).await.unwrap(),0);assert_eq!(profile_store::get(&mut c).await.unwrap().version,4);
    stop.cancel();server.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn missing_approval_rejects_stale_facts_profile_or_replayed_owner_intent() {
    use automated_apply_agents::missing_store as store;
    let mut c=missing_fixture().await;let created=store::create(&mut c,missing_create("Preferred schedule?")).await.unwrap();let id=created["id"].as_str().unwrap();missing_edit(&mut c,id,1).await;
    sqlx::query("INSERT INTO candidate_evidence(id,candidate_profile_id,evidence_type,title,content,user_confirmed,created_at,updated_at) VALUES($1,$2,'other','Changed context','Fictional evidence',false,clock_timestamp(),clock_timestamp())").bind(Uuid::new_v4()).bind(profile_pin().id).execute(&mut c).await.unwrap();
    let nonce=Uuid::new_v4().simple().to_string();assert_eq!(missing_approve(&mut c,id,2,&nonce).await.err(),Some(Failure("missing_input_context_changed_edit_before_approval")));
    missing_edit(&mut c,id,2).await;let approved=missing_approve(&mut c,id,3,&nonce).await.unwrap();assert_eq!(approved["version"],4);
    missing_edit(&mut c,id,4).await;assert_eq!(missing_approve(&mut c,id,5,&nonce).await.err(),Some(Failure("owner_approval_already_used")));assert_eq!(store::read(&mut c,id).await.unwrap()["status"],"draft");
    missing_approve(&mut c,id,5,&Uuid::new_v4().simple().to_string()).await.unwrap();sqlx::query("UPDATE candidate_profiles SET version=5 WHERE singleton_key='primary'").execute(&mut c).await.unwrap();let stale=store::read(&mut c,id).await.unwrap();assert_eq!(stale["effective_status"],"review_required");assert_eq!(stale["stale"],true);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'owner-proof:')").fetch_one(&mut c).await.unwrap(),2);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn missing_approval_signature_binds_dashboard_body_path_time_and_separate_key() {
    let mut c=missing_fixture().await;let created=automated_apply_agents::missing_store::create(&mut c,missing_create("Preferred work schedule?")).await.unwrap();let id=created["id"].as_str().unwrap();missing_edit(&mut c,id,1).await;
    let mut values=host_values();values.insert("BROWSER_OWNER_APPROVAL_KEY".into(),MISSING_SIGNING_KEY.into());let (url,stop,server)=http_fixture_values(values).await;let http=client();let path=format!("/api/v1/application-answers/missing/{id}/approve");let body=json!({"expected_version":2,"expected_profile_version":4,"factual_confirmation":true}).to_string();
    for signature in [missing_signature("/api/v1/another/approve",body.as_bytes(),&Uuid::new_v4().simple().to_string(),0),missing_signature(&path,b"{}",&Uuid::new_v4().simple().to_string(),0),missing_signature(&path,body.as_bytes(),&Uuid::new_v4().simple().to_string(),-60),"invalid".into()] {
        assert_eq!(http.post(format!("{url}{path}")).bearer_auth(HOST_TOKEN).header("X-Browser-Owner-Approval",signature).body(body.clone()).send().await.unwrap().status(),403);
    }
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'owner-proof:')").fetch_one(&mut c).await.unwrap(),0);stop.cancel();server.await.unwrap();
    let (url,stop,server)=http_fixture().await;assert_eq!(http.post(format!("{url}{path}")).bearer_auth(HOST_TOKEN).body(body).send().await.unwrap().status(),503);stop.cancel();server.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn missing_input_foreign_context_sensitive_answers_and_key_collisions_are_rejected() {
    use automated_apply_agents::{missing_contract as contract,missing_store as store};
    let mut c=missing_fixture().await;
    assert_eq!(store::create(&mut c,missing_create("What is your passport number?")).await.err(),Some(Failure("sensitive_answer_not_retained")));
    let created=store::create(&mut c,missing_create("Preferred schedule?")).await.unwrap();let id=created["id"].as_str().unwrap();
    let edit=contract::normalize_edit(json!({"expected_version":1,"answer":"password is private","evidence_note":"Owner"})).unwrap();assert_eq!(store::edit(&mut c,id,edit).await.err(),Some(Failure("sensitive_answer_not_retained")));
    let input=contract::normalize_create(json!({"question":"Schedule?","missing_fact":"Owner preference","packet_id":Uuid::new_v4()})).unwrap();assert_eq!(store::create(&mut c,input).await.err(),Some(Failure("missing_input_packet_context_mismatch")));
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{question}','\"Different question\"') WHERE key=$1").bind(format!("needs_input:{id}")).execute(&mut c).await.unwrap();assert_eq!(store::create(&mut c,missing_create("Preferred schedule?")).await.err(),Some(Failure("missing_input_identity_collision")));
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{candidate_profile_id}',$1) WHERE key=$2").bind(json!(Uuid::from_u128(99))).bind(format!("needs_input:{id}")).execute(&mut c).await.unwrap();assert_eq!(store::read(&mut c,id).await.err(),Some(Failure("missing_input_not_found")));assert!(store::list(&mut c,0,25).await.unwrap()["requests"].as_array().unwrap().is_empty());assert_eq!(store::history(&mut c,id,0,25).await.err(),Some(Failure("missing_input_not_found")));
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn missing_approval_deferred_failure_rolls_back_draft_history_and_nonce_atomically() {
    use automated_apply_agents::missing_store as store;
    let mut c=missing_fixture().await;let created=store::create(&mut c,missing_create("Preferred schedule?")).await.unwrap();let id=created["id"].as_str().unwrap();let edited=missing_edit(&mut c,id,1).await;let nonce=Uuid::new_v4().simple().to_string();
    sqlx::raw_sql("CREATE OR REPLACE FUNCTION fixture_missing_commit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.key LIKE 'input_rev:%' THEN RAISE EXCEPTION 'fictional_missing_commit_rejected'; END IF;RETURN NEW;END $$;CREATE CONSTRAINT TRIGGER fixture_missing_commit AFTER INSERT ON owner_preferences DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fixture_missing_commit()").execute(&mut c).await.unwrap();
    assert_eq!(missing_approve(&mut c,id,2,&nonce).await.err(),Some(Failure("profile_database_error")));assert_eq!(store::read(&mut c,id).await.unwrap(),edited);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'owner-proof:')").fetch_one(&mut c).await.unwrap(),0);assert_eq!(store::history(&mut c,id,0,25).await.unwrap()["history"].as_array().unwrap().len(),1);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_answer_drafts").fetch_one(&mut c).await.unwrap(),3);
    sqlx::query("DROP TRIGGER fixture_missing_commit ON owner_preferences").execute(&mut c).await.unwrap();missing_approve(&mut c,id,2,&nonce).await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn missing_approval_bad_saved_draft_rolls_back_without_claiming_owner_intent() {
    use automated_apply_agents::missing_store as store;
    let mut c=missing_fixture().await;let created=store::create(&mut c,missing_create("Preferred schedule?")).await.unwrap();let id=created["id"].as_str().unwrap();let edited=missing_edit(&mut c,id,1).await;
    sqlx::raw_sql("CREATE OR REPLACE FUNCTION fixture_missing_draft_time() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.updated_at='infinity';RETURN NEW;END $$;CREATE TRIGGER fixture_missing_draft_time BEFORE INSERT ON application_answer_drafts FOR EACH ROW EXECUTE FUNCTION fixture_missing_draft_time()").execute(&mut c).await.unwrap();
    assert_eq!(missing_approve(&mut c,id,2,&Uuid::new_v4().simple().to_string()).await.err(),Some(Failure("invalid_answer_draft_record")));assert_eq!(store::read(&mut c,id).await.unwrap(),edited);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'owner-proof:')").fetch_one(&mut c).await.unwrap(),0);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn missing_input_concurrent_edits_have_one_versioned_winner() {
    use automated_apply_agents::{missing_contract as contract,missing_store as store};
    let mut c=missing_fixture().await;let created=store::create(&mut c,missing_create("Preferred schedule?")).await.unwrap();let id=created["id"].as_str().unwrap();let mut second=connection().await;
    let input=|| contract::normalize_edit(json!({"expected_version":1,"answer":"Fictional fact","evidence_note":"Owner statement"})).unwrap();
    let (a,b)=tokio::join!(store::edit(&mut c,id,input()),store::edit(&mut second,id,input()));assert_ne!(a.is_ok(),b.is_ok());assert_eq!(a.err().or_else(||b.err()),Some(Failure("missing_input_version_conflict")));assert_eq!(store::read(&mut c,id).await.unwrap()["version"],2);assert_eq!(store::history(&mut c,id,0,25).await.unwrap()["history"].as_array().unwrap().len(),1);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn missing_approval_rechecks_proof_route_and_age_at_transaction_claim() {
    use automated_apply_agents::{missing_contract as contract,missing_store as store,owner_proof::SigningKey};
    let mut c=missing_fixture().await;let created=store::create(&mut c,missing_create("Preferred schedule?")).await.unwrap();let id=created["id"].as_str().unwrap();let edited=missing_edit(&mut c,id,1).await;
    let input=json!({"expected_version":2,"expected_profile_version":4,"factual_confirmation":true});let body=input.to_string();let path=format!("/api/v1/application-answers/missing/{id}/approve");
    let key=SigningKey::from_values(&BTreeMap::from([("BROWSER_OWNER_APPROVAL_KEY".into(),MISSING_SIGNING_KEY.into())])).unwrap().unwrap();
    let now=std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs_f64();let old=missing_signature(&path,body.as_bytes(),&Uuid::new_v4().simple().to_string(),-60);
    let proof=key.verify_at(&path,body.as_bytes(),&old,now-60.0).unwrap();assert_eq!(store::approve(&mut c,id,contract::normalize_approve(input.clone()).unwrap(),proof).await.err(),Some(Failure("owner_approval_required")));
    let wrong=missing_proof("/api/v1/another/approve",body.as_bytes(),&Uuid::new_v4().simple().to_string());assert_eq!(store::approve(&mut c,id,contract::normalize_approve(input).unwrap(),wrong).await.err(),Some(Failure("owner_approval_operation_mismatch")));
    assert_eq!(store::read(&mut c,id).await.unwrap(),edited);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'owner-proof:')").fetch_one(&mut c).await.unwrap(),0);
}
