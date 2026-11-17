// Guarded original-Apply questionnaire fixtures. No native transport/browser or real submission.
async fn questionnaire_fixture()->(PgConnection,Value,automated_apply_agents::private_resume::Settings){
    use sha2::Digest;
    let(mut c,inspection)=listing_fixture().await;let eligible=listing_observe(&mut c,&inspection,listing_report(&inspection)).await.unwrap();assert_eq!(eligible["operation"],"prepare");
    sqlx::raw_sql("DROP TABLE IF EXISTS drive_resume_versions;DROP TABLE IF EXISTS private_resumes;CREATE TABLE private_resumes(id uuid PRIMARY KEY,ciphertext bytea NOT NULL,sha256 varchar(64) NOT NULL,confirmed boolean NOT NULL,resource_id uuid NOT NULL)").execute(&mut c).await.unwrap();
    let corpus:Value=serde_json::from_str(include_str!("../../../document-worker/tests/fixtures/pdf-corpus.json")).unwrap();let raw:Vec<u8>=serde_json::from_value(corpus["pdfs"].as_array().unwrap().iter().find(|v|v["name"]=="text").unwrap()["bytes"].clone()).unwrap();let key=corpus["fernet"]["key"].as_str().unwrap();let cipher=fernet::Fernet::new(key).unwrap();let mut values=host_values();values.insert("RESUME_ENCRYPTION_KEY".into(),key.into());let resumes=automated_apply_agents::private_resume::Settings::from_values(&values).unwrap();let id=Uuid::new_v4();let resource:Uuid=sqlx::query_scalar("SELECT id FROM candidate_resources WHERE resource_type='resume' ORDER BY id LIMIT 1").fetch_one(&mut c).await.unwrap();sqlx::query("UPDATE candidate_resources SET source_type='private_upload',url=$2,user_confirmed=true,is_primary=true WHERE id=$1").bind(resource).bind(format!("private-resume:{id}")).execute(&mut c).await.unwrap();sqlx::query("INSERT INTO private_resumes(id,ciphertext,sha256,confirmed,resource_id) VALUES($1,$2,$3,true,$4)").bind(id).bind(cipher.encrypt(&raw).as_bytes()).bind(format!("{:x}",sha2::Sha256::digest(&raw))).bind(resource).execute(&mut c).await.unwrap();
    sqlx::query("UPDATE candidate_profiles SET projects=$1 WHERE singleton_key='primary'").bind(json!([{"name":"Queue","purpose":"My project uses Rust.","contribution":"I built Rust workers. I tested the workers.","technologies":["Rust"]}])).execute(&mut c).await.unwrap();
    let packets=packet_settings();let answers=answer_settings();assert!(automated_apply_agents::execution::preparation::prepare_one(&mut c,automated_apply_agents::execution::preparation::Services{packets:&packets,answers:&answers,resumes:&resumes}).await.unwrap());let key=format!("apply_work:{}",eligible["id"].as_str().unwrap());let mut work=browser_pref(&mut c,&key).await;assert_eq!(work["stage"],"READY_TO_APPLY");let revision=work["packet_revision"].as_i64().unwrap()+1;work["packet_revision"]=json!(revision);work["admitted_actions"]=json!([{"id":Uuid::new_v4(),"fingerprint":"apply:initial","at":chrono::Utc::now().to_rfc3339()}]);work["binding"]=inspection["binding"].clone();work["form_binding"]=work["binding"].clone();work["stage"]=json!("QUESTIONS");work["operation"]=json!("inspect_questionnaire");work["status"]=json!("executing");work["lease_token"]=json!(Uuid::new_v4());work["lease_until"]=json!((chrono::Utc::now()+chrono::Duration::seconds(180)).to_rfc3339());browser_save(&mut c,&key,work.clone()).await;
    sqlx::query("UPDATE application_packets SET lifecycle_state='submitting',revision=$2,approved_revision=NULL WHERE id=$1").bind(work["packet_id"].as_str().unwrap().parse::<Uuid>().unwrap()).bind(revision as i32).execute(&mut c).await.unwrap();(c,work,resumes)
}
fn questionnaire_report(work:&Value,question:&str)->Value{let mut step=json!({"document_id":"33333333-3333-4333-8333-333333333333","question":question,"answer_kind":"text","options":[],"max_characters":4000});step["step_sha256"]=json!(automated_apply_agents::execution::questionnaire_steps::step_hash(work,&step));json!({"kind":"questionnaire","observed_url":work["url"],"requisition":work["requisition"],"questionnaire":step})}
async fn questionnaire_observe(c:&mut PgConnection,work:&Value,report:Value,resumes:&automated_apply_agents::private_resume::Settings)->Result<Value>{automated_apply_agents::execution::questionnaires::observe(c,sync_request(work),report,&packet_settings(),resumes).await}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn execution_original_questionnaire_read_keeps_packet_submitting_and_same_spent_apply_before_answer_preparation(){
    let(mut c,work,resumes)=questionnaire_fixture().await;let observed=questionnaire_observe(&mut c,&work,questionnaire_report(&work,"What is your full name?"),&resumes).await.unwrap();assert_eq!(observed["operation"],"prepare_questionnaire");assert_eq!(observed["status"],"queued");assert_eq!(observed["admitted_actions"],work["admitted_actions"]);assert_eq!(observed["questionnaire_document_id"],"33333333-3333-4333-8333-333333333333");assert!(observed["lease_token"].is_null());assert_eq!(sqlx::query_scalar::<_,String>("SELECT lifecycle_state FROM application_packets WHERE id=$1").bind(work["packet_id"].as_str().unwrap().parse::<Uuid>().unwrap()).fetch_one(&mut c).await.unwrap(),"submitting");
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn execution_questionnaire_denies_changed_original_document_and_identity_sensitive_questions_never_get_an_answer(){
    let(mut c,work,resumes)=questionnaire_fixture().await;let mut original=work.clone();original["questionnaire_document_id"]=json!("44444444-4444-4444-8444-444444444444");let key=format!("apply_work:{}",work["id"].as_str().unwrap());browser_save(&mut c,&key,original.clone()).await;let before=browser_snapshot(&mut c).await;assert_eq!(questionnaire_observe(&mut c,&original,questionnaire_report(&work,"What is your full name?"),&resumes).await.unwrap_err(),Failure("questionnaire_original_document_required"));assert_eq!(browser_snapshot(&mut c).await,before);browser_save(&mut c,&key,work.clone()).await;let blocked=questionnaire_observe(&mut c,&work,questionnaire_report(&work,"Your account login email?"),&resumes).await.unwrap();assert_eq!(blocked["reason"],"questionnaire_identity_or_consent_requires_manual_review");assert_eq!(blocked["status"],"waiting");assert!(blocked["questionnaire_answer"].is_null());assert_eq!(blocked["admitted_actions"],work["admitted_actions"]);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn execution_questionnaire_rechecks_canonical_pdf_before_recording_even_a_read_observation(){
    let(mut c,work,resumes)=questionnaire_fixture().await;let before=browser_snapshot(&mut c).await;sqlx::query("UPDATE private_resumes SET sha256=repeat('b',64)").execute(&mut c).await.unwrap();assert_eq!(questionnaire_observe(&mut c,&work,questionnaire_report(&work,"What is your full name?"),&resumes).await.unwrap_err(),Failure("questionnaire_canonical_resume_changed"));assert_eq!(browser_snapshot(&mut c).await,before);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn execution_questionnaire_event_ack_failure_rolls_back_original_step_and_work_revision(){
    let(mut c,work,resumes)=questionnaire_fixture().await;let before=browser_snapshot(&mut c).await;sqlx::raw_sql("CREATE FUNCTION fixture_questionnaire_event_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'apply_event:') THEN RETURN NULL; END IF; RETURN NEW; END $$;CREATE TRIGGER fixture_questionnaire_event_drop BEFORE INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_questionnaire_event_drop()").execute(&mut c).await.unwrap();assert_eq!(questionnaire_observe(&mut c,&work,questionnaire_report(&work,"What is your full name?"),&resumes).await.unwrap_err(),Failure("execution_write_ack_failed"));assert_eq!(browser_snapshot(&mut c).await,before);sqlx::raw_sql("DROP TRIGGER fixture_questionnaire_event_drop ON owner_preferences;DROP FUNCTION fixture_questionnaire_event_drop()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn execution_applied_questionnaire_switches_to_history_only_with_both_original_documents() {
    let (mut c, mut work, resumes) = questionnaire_fixture().await;
    let key = format!("apply_work:{}", work["id"].as_str().unwrap());
    let chatbot = "33333333-3333-4333-8333-333333333333";
    let listing = "fictional-original-listing-document";
    work["form_pending"] = json!(true);
    work["questionnaire_steps"] = json!(1);
    work["questionnaire_document_id"] = json!(chatbot);
    work["document_id"] = json!(listing);
    browser_save(&mut c, &key, work.clone()).await;
    let before = browser_snapshot(&mut c).await;
    let report = json!({
        "kind":"execution_observation","document_id":chatbot,
        "observed_url":work["url"],"requisition":work["requisition"],
        "execution":{"state":"APPLIED","document_id":listing,"account_sha256":work["account_sha256"],
            "evidence_sha256":"e".repeat(64),"title":work["title"],"company":work["company"]}
    });
    let mut wrong = report.clone();
    wrong["execution"]["document_id"] = json!("fictional-replacement-listing");
    assert_eq!(
        questionnaire_observe(&mut c, &work, wrong, &resumes)
            .await
            .unwrap_err(),
        Failure("questionnaire_completion_observation_mismatch")
    );
    assert_eq!(browser_snapshot(&mut c).await, before);
    let observed = questionnaire_observe(&mut c, &work, report, &resumes)
        .await
        .unwrap();
    assert_eq!(observed["stage"], "VERIFYING");
    assert_eq!(observed["operation"], "reconcile_application");
    assert_eq!(
        observed["questionnaire_completion_observation"]["document_id"],
        chatbot
    );
    assert_eq!(observed["admitted_actions"], work["admitted_actions"]);
    assert_eq!(observed["form_pending"], true);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM application_submission_evidence")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
}
