fn packet_settings()->automated_apply_agents::packet_service::Settings {
    automated_apply_agents::packet_service::Settings {policy:Default::default(),multi_select:false,schema:"public".into(),telegram_notices:false}
}
async fn packet_service_fixture()->(PgConnection,Uuid) {
    let mut c=packet_material_fixture().await;
    sqlx::raw_sql(include_str!("../fixtures/drafts.sql")).execute(&mut c).await.unwrap();
    let corpus:Value=serde_json::from_str(include_str!("../fixtures/packet-context-corpus.json")).unwrap();
    seed_packet_material(&mut c,&corpus["records"][0]).await;
    let job=corpus["records"][0]["job"]["id"].as_str().unwrap().parse().unwrap();
    sqlx::raw_sql("DROP TABLE application_packets; ALTER TABLE candidate_resources ADD UNIQUE(id,candidate_profile_id)").execute(&mut c).await.unwrap();
    // Execute the repository's actual table/guard definitions, not permissive hand-written substitutes.
    let original=include_str!("../../../../supabase/fresh_public/001_phase1_public.sql");
    let tables=original.split("CREATE TABLE IF NOT EXISTS public.application_packets (").nth(1).unwrap().split("\nDO $$\nDECLARE table_name text; client_role text;").next().unwrap();
    sqlx::raw_sql(sqlx::AssertSqlSafe(format!("CREATE TABLE IF NOT EXISTS public.application_packets ({tables}"))).execute(&mut c).await.unwrap();
    let worker=include_str!("../../../../supabase/fresh_public/followups/003_naukri_worker.sql");
    let actual=worker.split("\nALTER TABLE public.application_packets DROP CONSTRAINT application_packets_lifecycle_state_check").nth(1).unwrap().split("\nCOMMIT;").next().unwrap();
    sqlx::raw_sql(sqlx::AssertSqlSafe(format!("ALTER TABLE public.application_packets DROP CONSTRAINT application_packets_lifecycle_state_check{actual}"))).execute(&mut c).await.unwrap();
    (c,job)
}
async fn packet_create(c:&mut PgConnection,job:Uuid,key:&str,questions:Value)->Result<Value>{
    automated_apply_agents::packet_service::dispatch(c,"POST",&format!("/api/v1/jobs/{job}/application-packets"),None,json!({"idempotency_key":key,"questions":questions}).to_string().as_bytes(),&packet_settings(),&answer_settings()).await.map(|(v,created)|{assert!(created);v})
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn packet_flow_http_previews_creates_replays_reads_lists_and_events_with_actual_guards(){
    let (mut c,job)=packet_service_fixture().await;
    let (url,stop,server)=http_fixture().await;
    let http=client();
    let platforms=http.get(format!("{url}/api/v1/applications/platforms")).bearer_auth(HOST_TOKEN).send().await.unwrap();assert_eq!(platforms.status(),200);
    let caps:Value=platforms.json().await.unwrap();assert_eq!(caps.as_array().unwrap().len(),17);assert!(caps.as_array().unwrap().iter().all(|c|c["live_verified"]==false));
    let preview_url=format!("{url}/api/v1/jobs/{job}/application-preview");
    let preview=http.post(&preview_url).bearer_auth(HOST_TOKEN).json(&json!({})).send().await.unwrap();let status=preview.status();let preview:Value=preview.json().await.unwrap();assert_eq!(status,200,"{preview}");
    assert_eq!(preview["fields"].as_array().unwrap().len(),7);assert_eq!(preview["readiness"]["stale"],false);
    assert!(preview["fields"].as_array().unwrap().iter().all(|f|f["review_status"]=="pending"));
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_packets").fetch_one(&mut c).await.unwrap(),0);
    let create_url=format!("{url}/api/v1/jobs/{job}/application-packets");let input=json!({"idempotency_key":"fictional-packet-001","questions":[{"question":"Preferred interview time?"},{"question":"Describe a project"}]});
    let created=http.post(&create_url).bearer_auth(HOST_TOKEN).json(&input).send().await.unwrap();let status=created.status();let created:Value=created.json().await.unwrap();assert_eq!(status,201,"{created}");
    assert_eq!(created["revision"],1);assert_eq!(created["approved_revision"],Value::Null);assert_eq!(created["lifecycle_state"],"created");assert_eq!(created["tracking_state"],"not_applied");assert_eq!(created["fields"].as_array().unwrap().len(),9);
    assert!(created["fields"].as_array().unwrap().iter().all(|f|f["id"]!=preview["fields"][0]["id"]));
    assert_eq!(created["fields"][6]["validation_status"],"file_upload_required");assert!(created["fields"][8]["proposed_answer"].is_null());
    let id=created["id"].as_str().unwrap();let item=format!("{url}/api/v1/application-packets/{id}");
    for (suffix,expected) in [("",created.clone()),("/readiness",created["readiness"].clone())] {
        let response=http.get(format!("{item}{suffix}")).bearer_auth(HOST_TOKEN).send().await.unwrap();assert_eq!(response.status(),200);assert_eq!(response.json::<Value>().await.unwrap(),expected);
    }
    let listing:Value=http.get(format!("{url}/api/v1/application-packets?limit=1&job_id={job}&status=created")).bearer_auth(HOST_TOKEN).send().await.unwrap().json().await.unwrap();assert_eq!(listing["packets"],json!([created.clone()]));
    let events:Value=http.get(format!("{item}/events")).bearer_auth(HOST_TOKEN).send().await.unwrap().json().await.unwrap();assert_eq!(events.as_array().unwrap().len(),1);assert_eq!(events[0]["event_type"],"packet_created");assert_eq!(events[0]["origin"],"owner_rest");
    assert_eq!(http.get(format!("{item}?status=unknown&job_id=ignored")).bearer_auth(HOST_TOKEN).send().await.unwrap().status(),200);
    assert_eq!(http.get(format!("{item}/events?status=unknown&job_id=ignored")).bearer_auth(HOST_TOKEN).send().await.unwrap().status(),200);
    sqlx::query("UPDATE candidate_profiles SET full_name='New fictional owner name' WHERE singleton_key='primary'").execute(&mut c).await.unwrap();
    let replay=http.post(&create_url).bearer_auth(HOST_TOKEN).json(&input).send().await.unwrap();assert_eq!(replay.status(),201);let replay:Value=replay.json().await.unwrap();assert_eq!(replay["snapshot"],created["snapshot"]);assert_eq!(replay["fields"],created["fields"]);assert_eq!(replay["review_status"],"stale");assert_eq!(replay["readiness"]["stale"],true);
    let mut conflict=input.clone();conflict["questions"]=json!([]);
    assert_eq!(http.post(&create_url).bearer_auth(HOST_TOKEN).json(&conflict).send().await.unwrap().status(),409);
    conflict["idempotency_key"]=json!("fictional-different-key");assert_eq!(http.post(&create_url).bearer_auth(HOST_TOKEN).json(&conflict).send().await.unwrap().status(),409);
    for (query,status) in [("limit=0",422),("limit=101",422),("job_id=invalid",422),("status=unknown",422)] {assert_eq!(http.get(format!("{url}/api/v1/application-packets?{query}")).bearer_auth(HOST_TOKEN).send().await.unwrap().status(),status);}
    assert_eq!(http.get(&preview_url).bearer_auth(HOST_TOKEN).send().await.unwrap().status(),405);
    assert_eq!(http.get(format!("{url}/api/v1/application-packets/{}",Uuid::new_v4())).bearer_auth(HOST_TOKEN).send().await.unwrap().status(),404);
    assert_eq!(http.get(&item).send().await.unwrap().status(),401);
    assert_eq!(http.get(&item).bearer_auth(HOST_TOKEN).header("X-Agent-Client","model").send().await.unwrap().status(),403);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_packets").fetch_one(&mut c).await.unwrap(),1);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_events").fetch_one(&mut c).await.unwrap(),1);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_submission_evidence").fetch_one(&mut c).await.unwrap(),0);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM llm_monthly_usage").fetch_one(&mut c).await.unwrap(),0);
    stop.cancel();server.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn packet_flow_concurrent_create_and_partial_field_failure_are_atomic(){
    let (mut c,job)=packet_service_fixture().await;let mut second=connection().await;
    let questions=json!([{"question":"Preferred interview time?"}]);
    let (a,b)=tokio::join!(packet_create(&mut c,job,"fictional-concurrent",questions.clone()),packet_create(&mut second,job,"fictional-concurrent",questions));
    let a=a.unwrap();let b=b.unwrap();assert_eq!(a,b);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_packets").fetch_one(&mut c).await.unwrap(),1);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_events").fetch_one(&mut c).await.unwrap(),1);
    let second_job=Uuid::new_v4();sqlx::query("INSERT INTO jobs(id,title,job_url,source_platform) VALUES($1,'Another fictional Rust role','https://www.naukri.com/job-listings-fictional-123456789012','naukri')").bind(second_job).execute(&mut c).await.unwrap();
    let before:i64=sqlx::query_scalar("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'needs_input:')").fetch_one(&mut c).await.unwrap();
    sqlx::raw_sql("CREATE FUNCTION fixture_fail_packet_field() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.position=7 THEN RAISE EXCEPTION 'fictional injected field failure'; END IF; RETURN NEW; END $$; CREATE TRIGGER fixture_fail_field BEFORE INSERT ON application_packet_fields FOR EACH ROW EXECUTE FUNCTION fixture_fail_packet_field()").execute(&mut c).await.unwrap();
    assert_eq!(packet_create(&mut c,second_job,"fictional-rollback-001",json!([{"question":"Preferred relocation city?"}])).await.unwrap_err(),Failure("packet_database_error"));
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_packets").fetch_one(&mut c).await.unwrap(),1);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_packet_fields").fetch_one(&mut c).await.unwrap(),8);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'needs_input:')").fetch_one(&mut c).await.unwrap(),before);
    sqlx::raw_sql("DROP TRIGGER fixture_fail_field ON application_packet_fields; DROP FUNCTION fixture_fail_packet_field()").execute(&mut c).await.unwrap();
    packet_create(&mut c,second_job,"fictional-rollback-001",json!([{"question":"Preferred relocation city?"}])).await.unwrap();
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_events").fetch_one(&mut c).await.unwrap(),2);
    let third=Uuid::new_v4();sqlx::query("INSERT INTO jobs(id,title,job_url,source_platform) VALUES($1,'Third fictional Rust role','https://www.naukri.com/job-listings-fictional-123456789012','naukri')").bind(third).execute(&mut c).await.unwrap();
    let before:i64=sqlx::query_scalar("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'needs_input:')").fetch_one(&mut c).await.unwrap();
    sqlx::raw_sql("CREATE FUNCTION fixture_fail_packet_event() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fictional injected history failure'; END $$; CREATE TRIGGER fixture_fail_event BEFORE INSERT ON application_events FOR EACH ROW EXECUTE FUNCTION fixture_fail_packet_event()").execute(&mut c).await.unwrap();
    assert_eq!(packet_create(&mut c,third,"fictional-event-rollback",json!([{"question":"Preferred interview language?"}])).await.unwrap_err(),Failure("packet_database_error"));
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_packets").fetch_one(&mut c).await.unwrap(),2);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_events").fetch_one(&mut c).await.unwrap(),2);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'needs_input:')").fetch_one(&mut c).await.unwrap(),before);
    sqlx::raw_sql("DROP TRIGGER fixture_fail_event ON application_events; DROP FUNCTION fixture_fail_packet_event()").execute(&mut c).await.unwrap();
}

#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn packet_flow_missing_profile_explicit_resume_and_multiple_selection_keep_their_gates(){
    use automated_apply_agents::packet_service;
    let (mut c,job)=packet_service_fixture().await;
    let preview=format!("/api/v1/jobs/{job}/application-preview");
    let request=json!({"questions":[{"question":"Technical skills","field_type":"multi_select","options":["Rust","Go"]}]}).to_string();
    let mut settings=packet_settings();
    for enabled in [false,true] {
        settings.multi_select=enabled;
        assert_eq!(packet_service::dispatch(&mut c,"POST",&preview,None,request.as_bytes(),&settings,&answer_settings()).await.unwrap_err(),Failure("packet_multi_select_unavailable"));
    }
    // A missing explicit selection never falls back to the confirmed primary resume.
    let result=packet_service::dispatch(&mut c,"POST",&preview,None,json!({"resume_resource_id":Uuid::from_u128(999)}).to_string().as_bytes(),&settings,&answer_settings()).await.unwrap().0;
    assert!(result["snapshot"]["resume"]["selected"].is_null());assert_eq!(result["readiness"]["state"],"needs_resume");
    sqlx::query("DELETE FROM candidate_profiles").execute(&mut c).await.unwrap();
    let result=packet_service::dispatch(&mut c,"POST",&preview,None,b"{}",&settings,&answer_settings()).await.unwrap().0;
    assert!(result["candidate_profile_id"].is_null());assert!(result["snapshot"]["candidate"].is_null());assert_eq!(result["readiness"]["state"],"needs_profile");
    assert_eq!(packet_create(&mut c,job,"fictional-no-profile",json!([])).await.unwrap_err(),Failure("packet_profile_required"));
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_packets").fetch_one(&mut c).await.unwrap(),0);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_events").fetch_one(&mut c).await.unwrap(),0);
}

#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn packet_flow_shared_parent_read_waits_for_a_whole_concurrent_revision(){
    use automated_apply_agents::packet_service;
    let (mut c,job)=packet_service_fixture().await;
    let packet=packet_create(&mut c,job,"fictional-reader-001",json!([])).await.unwrap();
    let id=packet["id"].as_str().unwrap().parse::<Uuid>().unwrap();let field=packet["fields"][0]["id"].as_str().unwrap().parse::<Uuid>().unwrap();
    let mut reader=connection().await;let pid:i32=sqlx::query_scalar("SELECT pg_backend_pid()").fetch_one(&mut reader).await.unwrap();let mut observer=connection().await;
    let mut tx=c.begin().await.unwrap();
    sqlx::query("SELECT id FROM application_packets WHERE id=$1 FOR UPDATE").bind(id).fetch_one(&mut *tx).await.unwrap();
    sqlx::query("UPDATE application_packet_fields SET human_answer='Changed factual name' WHERE id=$1").bind(field).execute(&mut *tx).await.unwrap();
    let task=tokio::spawn(async move{packet_service::dispatch(&mut reader,"GET",&format!("/api/v1/application-packets/{id}"),None,b"",&packet_settings(),&answer_settings()).await});
    let start=std::time::Instant::now();
    loop {
        if sqlx::query_scalar::<_,bool>("SELECT cardinality(pg_blocking_pids($1))>0").bind(pid).fetch_one(&mut observer).await.unwrap(){break;}
        assert!(start.elapsed()<std::time::Duration::from_secs(2));
        tokio::time::sleep(std::time::Duration::from_millis(10)).await;
    }
    assert!(!task.is_finished());tx.commit().await.unwrap();
    let result=tokio::time::timeout(std::time::Duration::from_secs(3),task).await.unwrap().unwrap().unwrap().0;
    assert_eq!(result["revision"],2);assert_eq!(result["fields"][0]["effective_answer"],"Changed factual name");assert_eq!(result["fields"][0]["answer_revision"],2);assert_eq!(result["fields"][0]["review_status"],"pending");assert!(result["approved_revision"].is_null());assert_eq!(result["lifecycle_state"],"needs_input");
}

#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn packet_flow_database_rejects_fake_receipts_bad_audits_and_history_changes(){
    let (mut c,job)=packet_service_fixture().await;let packet=packet_create(&mut c,job,"fictional-guards-001",json!([])).await.unwrap();let id=packet["id"].as_str().unwrap().parse::<Uuid>().unwrap();
    for state in ["submitting","submission_unknown","provider_confirmed_submitted","approved_for_manual_handoff"] {
        assert!(sqlx::query("UPDATE application_packets SET lifecycle_state=$2 WHERE id=$1").bind(id).bind(state).execute(&mut c).await.is_err());
    }
    assert!(sqlx::query("INSERT INTO application_events(id,packet_id,event_type,next_state,packet_revision,origin) VALUES($1,$2,'packet_created','reviewed',1,'owner_rest')").bind(Uuid::new_v4()).bind(id).execute(&mut c).await.is_err());
    for query in ["UPDATE application_events SET note='Changed' WHERE packet_id=$1","DELETE FROM application_events WHERE packet_id=$1","DELETE FROM application_packet_fields WHERE packet_id=$1","DELETE FROM application_packets WHERE id=$1"] {assert!(sqlx::query(sqlx::AssertSqlSafe(query)).bind(id).execute(&mut c).await.is_err());}
    assert!(sqlx::query("INSERT INTO application_submission_evidence(id,packet_id,packet_revision,confirmation_source,evidence_confidence,human_confirmed,idempotency_key,request_hash,receipt_reference) VALUES($1,$2,1,'naukri_status_ui','provider_ui_persistent',false,'fictional-fake-receipt',repeat('a',64),'naukri_worker_receipt:123456789012')").bind(Uuid::new_v4()).bind(id).execute(&mut c).await.is_err());
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_submission_evidence").fetch_one(&mut c).await.unwrap(),0);
    assert_eq!(sqlx::query_scalar::<_,String>("SELECT lifecycle_state FROM application_packets WHERE id=$1").bind(id).fetch_one(&mut c).await.unwrap(),"created");
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_events").fetch_one(&mut c).await.unwrap(),1);
    // Naive provenance remains a readable DTO, but must fail closed during eligibility.
    sqlx::query("UPDATE application_packet_fields SET provenance=provenance||'{\"answer_expires_at\":\"2026-11-15T12:00:00\"}'::jsonb WHERE packet_id=$1 AND position=0").bind(id).execute(&mut c).await.unwrap();
    assert_eq!(automated_apply_agents::packet_service::dispatch(&mut c,"GET",&format!("/api/v1/application-packets/{id}/readiness"),None,b"",&packet_settings(),&answer_settings()).await.unwrap_err(),Failure("invalid_packet_saved_record"));
}

#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn packet_flow_conflicting_race_preserves_one_winner_and_a_single_creation_event(){
    let (mut c,job)=packet_service_fixture().await;let mut second=connection().await;
    let (a,b)=tokio::join!(packet_create(&mut c,job,"fictional-race-one",json!([])),packet_create(&mut second,job,"fictional-race-two",json!([])));
    assert_ne!(a.is_ok(),b.is_ok());assert_eq!(a.err().or(b.err()),Some(Failure("packet_idempotency_conflict")));
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_packets").fetch_one(&mut c).await.unwrap(),1);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_events").fetch_one(&mut c).await.unwrap(),1);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_packet_fields").fetch_one(&mut c).await.unwrap(),7);
}
