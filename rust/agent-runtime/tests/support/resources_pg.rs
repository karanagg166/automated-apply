// Included in the dedicated PostgreSQL test binary; fictional fixtures only.
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn resource_question_http_returns_scoped_provenance_and_keeps_file_upload_manual(){
    let mut c=resource_fixture().await;
    sqlx::query("UPDATE candidate_profiles SET github_url='https://github.com/fictional'").execute(&mut c).await.unwrap();
    sqlx::query("INSERT INTO candidate_resources(id,candidate_profile_id,resource_type,label,url,user_confirmed,is_primary,source_type) VALUES ($1,$2,'other','Rust showcase','https://example.com/confirmed',true,false,'user')").bind(Uuid::new_v4()).bind(profile_pin().id).execute(&mut c).await.unwrap();
    let before:Value=sqlx::query_scalar("SELECT jsonb_build_object('profile',(SELECT to_jsonb(p) FROM candidate_profiles p),'resources',(SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM candidate_resources r),'confirmation',(SELECT value FROM owner_preferences WHERE key='phase1_profile_confirmation'))").fetch_one(&mut c).await.unwrap();
    let (url,stop,server)=http_fixture().await;let http=client();let target=format!("{url}/api/v1/candidate/resources/resolve");
    let github:Value=http.post(&target).bearer_auth(HOST_TOKEN).json(&json!({"question":" Github URL? "})).send().await.unwrap().json().await.unwrap();
    assert_eq!(github["answer"],"https://github.com/fictional");assert_eq!(github["source"],"candidate_profile");assert_eq!(github["requires_review"],false);assert_eq!(github["used_llm"],false);
    let custom:Value=http.post(&target).bearer_auth(HOST_TOKEN).json(&json!({"question":"Rust showcase"})).send().await.unwrap().json().await.unwrap();assert_eq!(custom["answer"],"https://example.com/confirmed");assert_eq!(custom["source"],"candidate_resource");
    let upload:Value=http.post(&target).bearer_auth(HOST_TOKEN).json(&json!({"question":"Upload CV"})).send().await.unwrap().json().await.unwrap();
    assert_eq!(upload["status"],"file_upload_required");assert!(upload["answer"].is_null());assert_eq!(upload["requires_review"],true);assert_eq!(upload["resources"].as_array().unwrap().len(),1);assert_eq!(upload["resources"][0]["accessibility"],"not_checked");assert_eq!(upload["resources"][0]["url"],"private-resume:20000000-0000-0000-0000-000000000001");
    for question in ["Describe your github experience","Github and linkedin","Github projects","Foreign profile resume"] {
        let response:Value=http.post(&target).bearer_auth(HOST_TOKEN).json(&json!({"question":question})).send().await.unwrap().json().await.unwrap();assert_eq!(response["status"],"needs_input");assert!(response["answer"].is_null());
    }
    let after:Value=sqlx::query_scalar("SELECT jsonb_build_object('profile',(SELECT to_jsonb(p) FROM candidate_profiles p),'resources',(SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM candidate_resources r),'confirmation',(SELECT value FROM owner_preferences WHERE key='phase1_profile_confirmation'))").fetch_one(&mut c).await.unwrap();assert_eq!(after,before);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM rust_agent_runs").fetch_one(&mut c).await.unwrap(),0);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_packets").fetch_one(&mut c).await.unwrap(),0);
    stop.cancel();server.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn resource_question_http_auth_body_method_and_missing_profile_fail_closed(){
    let mut c=resource_fixture().await;let (url,stop,server)=http_fixture().await;let http=client();let target=format!("{url}/api/v1/candidate/resources/resolve");
    assert_eq!(http.post(&target).body("invalid json").send().await.unwrap().status(),401);
    assert_eq!(http.post(&target).bearer_auth(HOST_TOKEN).header("x-agent-client","extension").json(&json!({"question":"github"})).send().await.unwrap().status(),403);
    for body in [json!({}),json!({"question":" "}),json!({"question":4}),json!({"question":"github","approve":true}),json!({"question":"x".repeat(2001)})] {assert_eq!(http.post(&target).bearer_auth(HOST_TOKEN).json(&body).send().await.unwrap().status(),422);}
    let method=http.get(&target).bearer_auth(HOST_TOKEN).send().await.unwrap();assert_eq!(method.status(),405);assert_eq!(method.headers()["allow"],"POST");
    assert_eq!(http.post(format!("{target}?submit=true")).bearer_auth(HOST_TOKEN).json(&json!({"question":"github"})).send().await.unwrap().status(),400);
    sqlx::query("DELETE FROM candidate_profiles").execute(&mut c).await.unwrap();
    assert_eq!(http.post(&target).bearer_auth(HOST_TOKEN).json(&json!({"question":"github"})).send().await.unwrap().status(),404);
    stop.cancel();server.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn resource_writes_commit_before_ack_preserve_noops_and_resolve_beyond_list_page() {
    let mut c=resource_fixture().await;
    let (url,stop,server)=http_fixture().await;
    let http=client();let target=format!("{url}/api/v1/candidate/resources");
    let body=json!({"resource_type":"leetcode","label":" Fictional   practice ","url":"https://example.com/practice","is_primary":true,"user_confirmed":true});
    let response=http.post(&target).bearer_auth(HOST_TOKEN).json(&body).send().await.unwrap();
    assert_eq!(response.status(),200);
    let saved:Value=response.json().await.unwrap();
    assert_eq!(saved["label"],"Fictional   practice");
    assert_eq!(saved["candidate_profile_id"],json!(profile_pin().id));
    let id=saved["id"].as_str().unwrap().parse::<Uuid>().unwrap();
    let mut observer=connection().await;
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM candidate_resources WHERE id=$1").bind(id).fetch_one(&mut observer).await.unwrap(),1);
    let mut change=body.clone();change["id"]=saved["id"].clone();
    let unchanged:Value=http.post(&target).bearer_auth(HOST_TOKEN).json(&change).send().await.unwrap().json().await.unwrap();
    assert_eq!(unchanged,saved);
    assert_eq!(http.post(&target).bearer_auth(HOST_TOKEN).json(&body).send().await.unwrap().status(),409);
    let mut conflict=body.clone();conflict["url"]=json!("https://example.com/conflict");
    assert_eq!(http.post(&target).bearer_auth(HOST_TOKEN).json(&conflict).send().await.unwrap().status(),409);
    change["label"]=json!("Corrected label");change["user_confirmed"]=json!(false);
    let revised:Value=http.post(&target).bearer_auth(HOST_TOKEN).json(&change).send().await.unwrap().json().await.unwrap();
    assert_ne!(revised["updated_at"],saved["updated_at"]);
    assert_eq!(revised["user_confirmed"],false);
    change["user_confirmed"]=json!(true);
    assert_eq!(http.post(&target).bearer_auth(HOST_TOKEN).json(&change).send().await.unwrap().status(),200);
    let list:Value=http.get(format!("{target}?offset=0&limit=1")).bearer_auth(HOST_TOKEN).send().await.unwrap().json().await.unwrap();
    assert_eq!(list["resources"].as_array().unwrap().len(),1);
    let link=list["resolved_links"].as_array().unwrap().iter().find(|r|r["resource_type"]=="leetcode").unwrap();
    assert_eq!(link["url"],body["url"]);assert_eq!(link["resource_id"],saved["id"]);assert_eq!(link["user_confirmed"],true);
    assert_eq!(profile_store::get(&mut c).await.unwrap().version,4);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_packets").fetch_one(&mut c).await.unwrap(),0);
    stop.cancel();server.await.unwrap();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn standard_resource_links_require_owner_confirmation_and_atomic_profile_version() {
    let mut c=resource_fixture().await;
    let (url,stop,server)=http_fixture().await;let http=client();let target=format!("{url}/api/v1/candidate/resources");
    let mut body=json!({"resource_type":"github","label":"Github","url":"https://github.com/fictional","user_confirmed":true});
    assert_eq!(http.post(&target).bearer_auth(HOST_TOKEN).json(&body).send().await.unwrap().status(),428);
    body["expected_profile_version"]=json!(3);
    assert_eq!(http.post(&target).bearer_auth(HOST_TOKEN).json(&body).send().await.unwrap().status(),409);
    body["expected_profile_version"]=json!(4);body["user_confirmed"]=json!(false);
    assert_eq!(http.post(&target).bearer_auth(HOST_TOKEN).json(&body).send().await.unwrap().status(),409);
    body["user_confirmed"]=json!(true);body["id"]=json!("10000000-0000-0000-0000-000000000001");
    assert_eq!(http.post(&target).bearer_auth(HOST_TOKEN).json(&body).send().await.unwrap().status(),409);
    body.as_object_mut().unwrap().remove("id");
    let response=http.post(&target).bearer_auth(HOST_TOKEN).json(&body).send().await.unwrap();assert_eq!(response.status(),200);
    assert_eq!(response.json::<Value>().await.unwrap(),json!({"resource_type":"github","url":"https://github.com/fictional","source":"candidate_profile","resource_id":null,"user_confirmed":true}));
    let saved=profile_store::get(&mut c).await.unwrap();assert_eq!(saved.version,5);assert_eq!(saved.value["github_url"],body["url"]);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM candidate_resources WHERE resource_type='github'").fetch_one(&mut c).await.unwrap(),0);
    assert_eq!(http.post(&target).bearer_auth(HOST_TOKEN).json(&body).send().await.unwrap().status(),409);
    body["expected_profile_version"]=json!(5);
    assert_eq!(http.post(&target).bearer_auth(HOST_TOKEN).json(&body).send().await.unwrap().status(),200);
    assert_eq!(profile_store::get(&mut c).await.unwrap().value["updated_at"],saved.value["updated_at"]);
    let confirmation:Value=sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key='phase1_profile_confirmation'").fetch_one(&mut c).await.unwrap();
    assert_eq!(confirmation["profile_version"],4);
    stop.cancel();server.await.unwrap();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn evidence_corrections_clear_confirmation_and_replace_project_facts_without_inference() {
    let mut c=resource_fixture().await;let (url,stop,server)=http_fixture().await;let http=client();let target=format!("{url}/api/v1/candidate/evidence");
    let body=json!({"evidence_type":"project","title":" Fictional   project ","content":"Owner supplied evidence","user_confirmed":true,"project":{"name":" A   B ","technologies":["Rust","RUST"],"contribution":"Owner implementation"},"source_url":"https://example.com/evidence"});
    let response=http.post(&target).bearer_auth(HOST_TOKEN).json(&body).send().await.unwrap();assert_eq!(response.status(),201);let saved:Value=response.json().await.unwrap();
    assert_eq!(saved["title"],"Fictional   project");assert_eq!(saved["project"]["name"],"A B");assert_eq!(saved["project"]["technologies"],json!(["Rust"]));
    let item=format!("{target}/{}",saved["id"].as_str().unwrap());
    let amended:Value=http.patch(&item).bearer_auth(HOST_TOKEN).json(&json!({"title":"Corrected title"})).send().await.unwrap().json().await.unwrap();assert_eq!(amended["user_confirmed"],false);assert_eq!(amended["project"],saved["project"]);
    let listed:Value=http.get(&target).bearer_auth(HOST_TOKEN).send().await.unwrap().json().await.unwrap();assert_eq!(listed["verified"],json!([]));assert_eq!(listed["unverified"].as_array().unwrap().len(),1);
    let replacement:Value=http.patch(&item).bearer_auth(HOST_TOKEN).json(&json!({"project":{"name":"Different supplied project"},"source_url":null,"user_confirmed":true})).send().await.unwrap().json().await.unwrap();
    assert_eq!(replacement["user_confirmed"],true);assert_eq!(replacement["project"]["technologies"],json!([]));assert!(replacement["project"]["contribution"].is_null());assert!(replacement["source_url"].is_null());
    for invalid in [json!({}),json!({"title":null}),json!({"user_confirmed":null}),json!({"project":{"name":"P","url":"http://example.com"}}),json!({"evidence_type":"other"})] {
        assert_eq!(http.patch(&item).bearer_auth(HOST_TOKEN).json(&invalid).send().await.unwrap().status(),422);
    }
    assert_eq!(profile_store::get(&mut c).await.unwrap().version,4);
    stop.cancel();server.await.unwrap();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn resource_owner_boundary_pagination_and_foreign_ids_reject_without_mutation() {
    let mut c=resource_fixture().await;let (url,stop,server)=http_fixture().await;let http=client();let target=format!("{url}/api/v1/candidate/resources");
    let body=json!({"resource_type":"resume","label":"Unowned","url":"https://example.com/new","id":"10000000-0000-0000-0000-000000000002"});
    assert_eq!(http.post(&target).json(&body).send().await.unwrap().status(),401);
    assert_eq!(http.post(&target).bearer_auth(HOST_TOKEN).header("x-agent-client","extension").json(&body).send().await.unwrap().status(),403);
    assert_eq!(http.post(&target).bearer_auth(HOST_TOKEN).json(&body).send().await.unwrap().status(),404);
    for invalid in [json!({"resource_type":"resume","label":"Injected","url":"private-resume:20000000-0000-0000-0000-000000000001","source_type":"private_upload"}),json!({"resource_type":"other","label":"Bad","url":"https://127.0.0.1"})] {
        assert_eq!(http.post(&target).bearer_auth(HOST_TOKEN).json(&invalid).send().await.unwrap().status(),422);
    }
    for query in ["offset=-1","limit=0","limit=101","offset=100001","limit=1&limit=2","submit=true"] {
        assert_eq!(http.get(format!("{target}?{query}")).bearer_auth(HOST_TOKEN).send().await.unwrap().status(),422);
    }
    let page:Value=http.get(format!("{target}?offset=1.0&limit=1")).bearer_auth(HOST_TOKEN).send().await.unwrap().json().await.unwrap();assert_eq!(page["resources"],json!([]));assert_eq!(page["offset"],1);
    let method=http.delete(&target).bearer_auth(HOST_TOKEN).send().await.unwrap();assert_eq!(method.status(),405);assert_eq!(method.headers()["allow"],"GET, POST");
    let foreign=format!("{url}/api/v1/candidate/evidence/10000000-0000-0000-0000-000000000002");assert_eq!(http.patch(&foreign).bearer_auth(HOST_TOKEN).json(&json!({"title":"Unowned"})).send().await.unwrap().status(),404);
    assert_eq!(sqlx::query_scalar::<_,String>("SELECT label FROM candidate_resources WHERE id='10000000-0000-0000-0000-000000000002'").fetch_one(&mut c).await.unwrap(),"Foreign profile resume");
    stop.cancel();server.await.unwrap();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn resource_and_evidence_result_validation_and_deferred_commit_errors_roll_back() {
    use automated_apply_agents::resource_store;
    let mut c=resource_fixture().await;
    sqlx::raw_sql("CREATE OR REPLACE FUNCTION fixture_resource_invalid_time() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.updated_at='infinity';RETURN NEW;END $$;CREATE TRIGGER fixture_resource_time BEFORE INSERT ON candidate_resources FOR EACH ROW EXECUTE FUNCTION fixture_resource_invalid_time()").execute(&mut c).await.unwrap();
    assert_eq!(resource_store::save_resource(&mut c,json!({"resource_type":"other","label":"New","url":"https://example.com/new"}),false).await.err(),Some(Failure("invalid_resource_record")));
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM candidate_resources WHERE resource_type='other'").fetch_one(&mut c).await.unwrap(),0);
    sqlx::raw_sql("CREATE OR REPLACE FUNCTION fixture_evidence_deferred() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fictional_deferred_write_rejected';RETURN NEW;END $$;CREATE CONSTRAINT TRIGGER fixture_evidence_commit AFTER INSERT ON candidate_evidence DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fixture_evidence_deferred()").execute(&mut c).await.unwrap();
    assert_eq!(resource_store::save_evidence(&mut c,None,json!({"evidence_type":"other","title":"Deferred","content":"Fictional only"})).await.err(),Some(Failure("profile_database_error")));
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM candidate_evidence").fetch_one(&mut c).await.unwrap(),0);
    assert_eq!(profile_store::get(&mut c).await.unwrap().version,4);
}
