async fn packet_edit(c:&mut PgConnection,packet:Uuid,suffix:&str,body:Value)->Result<Value>{
    automated_apply_agents::packet_service::dispatch(c,if suffix=="/questions"{"POST"}else{"PATCH"},&format!("/api/v1/application-packets/{packet}{suffix}"),None,body.to_string().as_bytes(),&packet_settings(),&answer_settings()).await.map(|(v,created)|{assert!(!created);v})
}
async fn packet_archive_value(c:&mut PgConnection,id:Uuid,revision:i32)->Value{
    sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1").bind(automated_apply_agents::packet_archive::key(id,revision).unwrap()).fetch_one(c).await.unwrap()
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn packet_edits_http_add_answer_refresh_and_preserve_original_revisions(){
    let (mut c,job)=packet_service_fixture().await;
    let original=packet_create(&mut c,job,"fictional-edit-http",json!([{"question":"Describe a project"}])).await.unwrap();
    let id=original["id"].as_str().unwrap().parse::<Uuid>().unwrap();let narrative=original["fields"][7]["id"].as_str().unwrap();
    let (url,stop,server)=http_fixture().await;let http=client();let root=format!("{url}/api/v1/application-packets/{id}");
    let response=http.patch(format!("{root}/questions/{narrative}")).bearer_auth(HOST_TOKEN).json(&json!({"expected_revision":1,"answer":" I built fictional Rust workers. "})).send().await.unwrap();let status=response.status();let answer:Value=response.json().await.unwrap();assert_eq!(status,200,"{answer}");
    assert_eq!(answer["revision"],2);assert_eq!(answer["fields"][7]["effective_answer"],"I built fictional Rust workers.");assert_eq!(answer["fields"][7]["provenance"]["source"],"human");assert_eq!(answer["fields"][7]["review_status"],"pending");assert_eq!(answer["fields"][7]["answer_revision"],2);assert!(answer["approved_revision"].is_null());
    let archived=packet_archive_value(&mut c,id,1).await;assert_eq!(archived["snapshot"],original["snapshot"]);assert_eq!(archived["fields"],original["fields"]);
    let repeated=http.patch(format!("{root}/questions/{narrative}")).bearer_auth(HOST_TOKEN).json(&json!({"expected_revision":1,"answer":"Another answer"})).send().await.unwrap();assert_eq!(repeated.status(),409);
    assert_eq!(packet_archive_value(&mut c,id,1).await,archived);
    let response=http.post(format!("{root}/questions")).bearer_auth(HOST_TOKEN).json(&json!({"expected_revision":2,"questions":[{"question":"Preferred interview time?"}]})).send().await.unwrap();let status=response.status();let added:Value=response.json().await.unwrap();assert_eq!(status,200,"{added}");
    assert_eq!(added["revision"],3);assert_eq!(added["fields"].as_array().unwrap().len(),9);assert_eq!(added["fields"][8]["provenance"]["origin"],"user_provided");assert!(added["fields"][8]["provenance"]["missing_input_id"].is_string());assert_eq!(packet_archive_value(&mut c,id,2).await["fields"],answer["fields"]);
    sqlx::query("UPDATE candidate_profiles SET full_name='Updated factual owner name',version=5 WHERE singleton_key='primary'").execute(&mut c).await.unwrap();
    let response=http.patch(&root).bearer_auth(HOST_TOKEN).json(&json!({"expected_revision":3,"refresh_saved_data":true})).send().await.unwrap();let status=response.status();let fresh:Value=response.json().await.unwrap();assert_eq!(status,200,"{fresh}");
    assert_eq!(fresh["revision"],4);assert_eq!(fresh["candidate_profile_version"],5);assert_eq!(fresh["snapshot"]["candidate"]["full_name"],"Updated factual owner name");assert_eq!(fresh["fields"][0]["proposed_answer"],"Updated factual owner name");assert!(fresh["fields"][7]["human_answer"].is_null());assert!(fresh["fields"][7]["proposed_answer"].is_null());assert_eq!(fresh["fields"][7]["answer_revision"],3);assert_eq!(fresh["readiness"]["stale"],false);
    assert_eq!(packet_archive_value(&mut c,id,3).await["fields"],added["fields"]);
    let read:Value=http.get(&root).bearer_auth(HOST_TOKEN).send().await.unwrap().json().await.unwrap();assert_eq!(read,fresh);
    let events:Value=http.get(format!("{root}/events")).bearer_auth(HOST_TOKEN).send().await.unwrap().json().await.unwrap();assert_eq!(events.as_array().unwrap().iter().map(|e|e["event_type"].as_str().unwrap()).collect::<Vec<_>>(),vec!["packet_created","answer_edited","questions_added","packet_refreshed"]);
    assert_eq!(http.patch(&root).bearer_auth(HOST_TOKEN).json(&json!({"expected_revision":4})).send().await.unwrap().status(),422);
    assert_eq!(http.post(format!("{root}/questions")).bearer_auth(HOST_TOKEN).json(&json!({"expected_revision":4,"questions":[]})).send().await.unwrap().status(),422);
    assert_eq!(http.post(format!("{root}/questions/{narrative}")).bearer_auth(HOST_TOKEN).json(&json!({"expected_revision":4,"answer":"Not an allowed method"})).send().await.unwrap().status(),405);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_submission_evidence").fetch_one(&mut c).await.unwrap(),0);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM llm_monthly_usage").fetch_one(&mut c).await.unwrap(),0);
    stop.cancel();server.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn packet_edits_concurrent_cas_has_one_winner_and_one_original_archive(){
    let (mut c,job)=packet_service_fixture().await;let original=packet_create(&mut c,job,"fictional-edit-race",json!([])).await.unwrap();let packet=original["id"].as_str().unwrap().parse().unwrap();let suffix=format!("/questions/{}",original["fields"][0]["id"].as_str().unwrap());let mut second=connection().await;
    let (a,b)=tokio::join!(packet_edit(&mut c,packet,&suffix,json!({"expected_revision":1,"answer":"Factual name one"})),packet_edit(&mut second,packet,&suffix,json!({"expected_revision":1,"answer":"Factual name two"})));
    assert_ne!(a.is_ok(),b.is_ok());assert_eq!(a.as_ref().err().or(b.as_ref().err()),Some(&Failure("packet_revision_conflict")));
    let winner=a.or(b).unwrap();assert_eq!(winner["revision"],2);assert_eq!(winner["fields"][0]["answer_revision"],2);
    assert_eq!(packet_archive_value(&mut c,packet,1).await["fields"],original["fields"]);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'prv:')").fetch_one(&mut c).await.unwrap(),1);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_events").fetch_one(&mut c).await.unwrap(),2);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn packet_edits_reject_stale_closed_foreign_upload_and_option_answers_without_archiving(){
    let (mut c,job)=packet_service_fixture().await;let original=packet_create(&mut c,job,"fictional-edit-denials",json!([{"question":"Choose role","field_type":"multiple_choice","options":["Rust","Go"],"max_characters":4}])).await.unwrap();let packet=original["id"].as_str().unwrap().parse().unwrap();
    for (field,answer,expected) in [(original["fields"][6]["id"].as_str().unwrap().to_owned(),"Uploaded",Failure("packet_upload_attestation_denied")),(Uuid::new_v4().to_string(),"Fact",Failure("packet_field_not_found")),(original["fields"][7]["id"].as_str().unwrap().to_owned(),"Python",Failure("packet_answer_invalid")),(original["fields"][7]["id"].as_str().unwrap().to_owned(),"rust",Failure("packet_answer_invalid"))] {
        assert_eq!(packet_edit(&mut c,packet,&format!("/questions/{field}"),json!({"expected_revision":1,"answer":answer})).await.unwrap_err(),expected);
    }
    sqlx::query("UPDATE candidate_profiles SET full_name='Concurrent raw factual correction' WHERE singleton_key='primary'").execute(&mut c).await.unwrap();
    assert_eq!(packet_edit(&mut c,packet,"/questions",json!({"expected_revision":1,"questions":[{"question":"Email"}]})).await.unwrap_err(),Failure("packet_context_changed"));
    sqlx::query("UPDATE application_packets SET lifecycle_state='abandoned' WHERE id=$1").bind(packet).execute(&mut c).await.unwrap();
    assert_eq!(packet_edit(&mut c,packet,"",json!({"expected_revision":1,"refresh_saved_data":true})).await.unwrap_err(),Failure("packet_closed"));
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'prv:')").fetch_one(&mut c).await.unwrap(),0);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_events").fetch_one(&mut c).await.unwrap(),1);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn packet_edits_field_and_event_failures_rollback_archives_questions_and_parent_cas(){
    let (mut c,job)=packet_service_fixture().await;let original=packet_create(&mut c,job,"fictional-edit-rollback",json!([])).await.unwrap();let packet=original["id"].as_str().unwrap().parse().unwrap();
    let before:i64=sqlx::query_scalar("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'needs_input:')").fetch_one(&mut c).await.unwrap();
    sqlx::raw_sql("CREATE FUNCTION fixture_edit_fail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fictional edit failure'; END $$; CREATE TRIGGER fixture_edit_field_fail BEFORE INSERT ON application_packet_fields FOR EACH ROW EXECUTE FUNCTION fixture_edit_fail()").execute(&mut c).await.unwrap();
    let input=json!({"expected_revision":1,"questions":[{"question":"Preferred relocation city?"}]});
    assert_eq!(packet_edit(&mut c,packet,"/questions",input.clone()).await.unwrap_err(),Failure("packet_database_error"));
    sqlx::raw_sql("DROP TRIGGER fixture_edit_field_fail ON application_packet_fields; CREATE TRIGGER fixture_edit_event_fail BEFORE INSERT ON application_events FOR EACH ROW EXECUTE FUNCTION fixture_edit_fail()").execute(&mut c).await.unwrap();
    assert_eq!(packet_edit(&mut c,packet,"/questions",input.clone()).await.unwrap_err(),Failure("packet_database_error"));
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'prv:')").fetch_one(&mut c).await.unwrap(),0);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'needs_input:')").fetch_one(&mut c).await.unwrap(),before);
    let restored=automated_apply_agents::packet_service::dispatch(&mut c,"GET",&format!("/api/v1/application-packets/{packet}"),None,b"",&packet_settings(),&answer_settings()).await.unwrap().0;assert_eq!(restored,original);
    sqlx::raw_sql("DROP TRIGGER fixture_edit_event_fail ON application_events; DROP FUNCTION fixture_edit_fail()").execute(&mut c).await.unwrap();
    assert_eq!(packet_edit(&mut c,packet,"/questions",input).await.unwrap()["revision"],2);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn packet_edits_exact_field_capacity_and_explicit_resume_selection_do_not_fall_back(){
    let (mut c,job)=packet_service_fixture().await;let original=packet_create(&mut c,job,"fictional-edit-capacity",json!([])).await.unwrap();let packet=original["id"].as_str().unwrap().parse().unwrap();
    for (revision,count) in [(1,50),(2,43)] {
        let questions=(0..count).map(|i|json!({"question":format!("Describe a project {revision} {i}")})).collect::<Vec<_>>();
        let result=packet_edit(&mut c,packet,"/questions",json!({"expected_revision":revision,"questions":questions})).await.unwrap();assert_eq!(result["revision"],revision+1);
    }
    assert_eq!(packet_edit(&mut c,packet,"/questions",json!({"expected_revision":3,"questions":[{"question":"One too many"}]})).await.unwrap_err(),Failure("packet_field_limit"));
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_packet_fields").fetch_one(&mut c).await.unwrap(),100);
    let result=packet_edit(&mut c,packet,"",json!({"expected_revision":3,"resume_resource_id":Uuid::from_u128(999)})).await.unwrap();assert_eq!(result["revision"],4);assert!(result["snapshot"]["resume"]["selected"].is_null());assert_eq!(result["readiness"]["state"],"needs_resume");assert!(sqlx::query_scalar::<_,Option<Uuid>>("SELECT resume_resource_id FROM application_packets WHERE id=$1").bind(packet).fetch_one(&mut c).await.unwrap().is_none());
    let restored=packet_edit(&mut c,packet,"",json!({"expected_revision":4,"resume_resource_id":null})).await.unwrap();assert!(restored["snapshot"]["resume"]["selected"].is_object());assert_eq!(restored["revision"],5);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn packet_edits_clear_real_database_approval_and_archive_the_reviewed_revision(){
    let (mut c,job)=packet_service_fixture().await;let original=packet_create(&mut c,job,"fictional-edit-approval",json!([])).await.unwrap();let packet=original["id"].as_str().unwrap().parse().unwrap();
    sqlx::query("UPDATE application_packets SET lifecycle_state='preparing' WHERE id=$1").bind(packet).execute(&mut c).await.unwrap();
    sqlx::query("UPDATE application_packet_fields SET review_status='reviewed' WHERE packet_id=$1 AND COALESCE(human_answer,proposed_answer) IS NOT NULL").bind(packet).execute(&mut c).await.unwrap();
    sqlx::query("UPDATE application_packets SET lifecycle_state='approved_for_manual_handoff',approved_revision=revision,readiness_state='ready_for_manual_handoff' WHERE id=$1").bind(packet).execute(&mut c).await.unwrap();
    let suffix=format!("/questions/{}",original["fields"][0]["id"].as_str().unwrap());
    let result=packet_edit(&mut c,packet,&suffix,json!({"expected_revision":1,"answer":"Explicit corrected owner name"})).await.unwrap();assert_eq!(result["revision"],2);assert!(result["approved_revision"].is_null());assert_eq!(result["fields"][0]["review_status"],"pending");assert_ne!(result["readiness"]["state"],"ready_for_manual_handoff");
    let archived=packet_archive_value(&mut c,packet,1).await;assert_eq!(archived["approved_revision"],1);assert_eq!(archived["lifecycle_state"],"approved_for_manual_handoff");assert_eq!(archived["fields"][0]["review_status"],"reviewed");assert_eq!(archived["fields"][0]["human_answer"],Value::Null);
}

#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn packet_edits_wait_for_profile_correction_and_refuse_the_old_context(){
    let (mut c,job)=packet_service_fixture().await;let original=packet_create(&mut c,job,"fictional-edit-profile-lock",json!([])).await.unwrap();let packet=original["id"].as_str().unwrap().parse().unwrap();
    let mut other=connection().await;let pid:i32=sqlx::query_scalar("SELECT pg_backend_pid()").fetch_one(&mut other).await.unwrap();let mut observer=connection().await;
    let mut tx=c.begin().await.unwrap();sqlx::query("UPDATE candidate_profiles SET full_name='New confirmed factual name' WHERE singleton_key='primary'").execute(&mut *tx).await.unwrap();
    let suffix=format!("/questions/{}",original["fields"][0]["id"].as_str().unwrap());
    let task=tokio::spawn(async move{packet_edit(&mut other,packet,&suffix,json!({"expected_revision":1,"answer":"Old context answer"})).await});
    let start=std::time::Instant::now();loop{
        if sqlx::query_scalar::<_,bool>("SELECT cardinality(pg_blocking_pids($1))>0").bind(pid).fetch_one(&mut observer).await.unwrap(){break;}
        assert!(start.elapsed()<std::time::Duration::from_secs(2));tokio::time::sleep(std::time::Duration::from_millis(10)).await;
    }
    assert!(!task.is_finished());tx.commit().await.unwrap();
    assert_eq!(tokio::time::timeout(std::time::Duration::from_secs(3),task).await.unwrap().unwrap().unwrap_err(),Failure("packet_context_changed"));
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'prv:')").fetch_one(&mut c).await.unwrap(),0);
    let result=packet_edit(&mut c,packet,"",json!({"expected_revision":1,"refresh_saved_data":true})).await.unwrap();assert_eq!(result["fields"][0]["proposed_answer"],"New confirmed factual name");assert_eq!(result["revision"],2);
}

#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn packet_edits_suppressed_field_event_and_refresh_writes_cannot_acknowledge_success(){
    let (mut c,job)=packet_service_fixture().await;
    sqlx::raw_sql("CREATE FUNCTION fixture_suppress_packet() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NULL; END $$; CREATE TRIGGER fixture_suppress_field BEFORE INSERT ON application_packet_fields FOR EACH ROW EXECUTE FUNCTION fixture_suppress_packet()").execute(&mut c).await.unwrap();
    assert_eq!(packet_create(&mut c,job,"fictional-suppress-create",json!([])).await.unwrap_err(),Failure("packet_write_ack_failed"));
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_packets").fetch_one(&mut c).await.unwrap(),0);
    sqlx::raw_sql("DROP TRIGGER fixture_suppress_field ON application_packet_fields; CREATE TRIGGER fixture_suppress_event BEFORE INSERT ON application_events FOR EACH ROW EXECUTE FUNCTION fixture_suppress_packet()").execute(&mut c).await.unwrap();
    assert_eq!(packet_create(&mut c,job,"fictional-suppress-create",json!([])).await.unwrap_err(),Failure("packet_write_ack_failed"));
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_packets").fetch_one(&mut c).await.unwrap(),0);
    sqlx::raw_sql("DROP TRIGGER fixture_suppress_event ON application_events").execute(&mut c).await.unwrap();
    let original=packet_create(&mut c,job,"fictional-suppress-create",json!([])).await.unwrap();let packet=original["id"].as_str().unwrap().parse().unwrap();
    sqlx::raw_sql("CREATE TRIGGER fixture_suppress_field_update BEFORE UPDATE ON application_packet_fields FOR EACH ROW EXECUTE FUNCTION fixture_suppress_packet()").execute(&mut c).await.unwrap();
    assert_eq!(packet_edit(&mut c,packet,&format!("/questions/{}",original["fields"][0]["id"].as_str().unwrap()),json!({"expected_revision":1,"answer":"Owner factual answer"})).await.unwrap_err(),Failure("packet_write_ack_failed"));
    sqlx::raw_sql("DROP TRIGGER fixture_suppress_field_update ON application_packet_fields").execute(&mut c).await.unwrap();
    let input=json!({"expected_revision":1,"questions":[{"question":"Preferred relocation city?"}]});
    for trigger in ["CREATE TRIGGER fixture_suppress_field BEFORE INSERT ON application_packet_fields FOR EACH ROW EXECUTE FUNCTION fixture_suppress_packet()","CREATE TRIGGER fixture_suppress_event BEFORE INSERT ON application_events FOR EACH ROW EXECUTE FUNCTION fixture_suppress_packet()"] {
        sqlx::raw_sql(sqlx::AssertSqlSafe(trigger)).execute(&mut c).await.unwrap();
        assert_eq!(packet_edit(&mut c,packet,"/questions",input.clone()).await.unwrap_err(),Failure("packet_write_ack_failed"));
        sqlx::raw_sql("DROP TRIGGER IF EXISTS fixture_suppress_field ON application_packet_fields; DROP TRIGGER IF EXISTS fixture_suppress_event ON application_events").execute(&mut c).await.unwrap();
    }
    sqlx::raw_sql("CREATE FUNCTION fixture_suppress_refresh() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.snapshot IS DISTINCT FROM OLD.snapshot THEN RETURN NULL; END IF; RETURN NEW; END $$; CREATE TRIGGER fixture_suppress_refresh BEFORE UPDATE ON application_packets FOR EACH ROW EXECUTE FUNCTION fixture_suppress_refresh()").execute(&mut c).await.unwrap();
    sqlx::query("UPDATE candidate_profiles SET full_name='Updated factual name' WHERE singleton_key='primary'").execute(&mut c).await.unwrap();
    assert_eq!(packet_edit(&mut c,packet,"",json!({"expected_revision":1,"refresh_saved_data":true})).await.unwrap_err(),Failure("packet_write_ack_failed"));
    assert_eq!(sqlx::query_scalar::<_,i32>("SELECT revision FROM application_packets WHERE id=$1").bind(packet).fetch_one(&mut c).await.unwrap(),1);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'prv:')").fetch_one(&mut c).await.unwrap(),0);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_events").fetch_one(&mut c).await.unwrap(),1);
    sqlx::raw_sql("DROP TRIGGER fixture_suppress_refresh ON application_packets; DROP FUNCTION fixture_suppress_refresh(); DROP FUNCTION fixture_suppress_packet()").execute(&mut c).await.unwrap();
}
