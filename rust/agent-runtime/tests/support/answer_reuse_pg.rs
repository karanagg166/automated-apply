async fn reusable_draft_fixture() -> (PgConnection, Uuid) {
    use automated_apply_agents::{answer_service, answer_store};
    let mut c = narrative_fixture().await;
    let result = answer_service::generate(
        &mut c,
        json!({"question":"Describe a project you built","save_draft":true}),
        &answer_settings(),
    )
    .await
    .unwrap();
    let id = result["draft_id"]
        .as_str()
        .unwrap()
        .parse::<Uuid>()
        .unwrap();
    answer_store::review(
        &mut c,
        id,
        answer_store::Review {
            review_status: answer_store::ReviewStatus::Reviewed,
        },
    )
    .await
    .unwrap();
    (c, id)
}
fn reuse_body(scope: &str) -> Value {
    json!({"expected_profile_version":4,"scope":scope,"confirm_reviewed_answer":true})
}
fn reuse_proof(id: Uuid, body: &Value, nonce: &str) -> automated_apply_agents::owner_proof::Proof {
    missing_proof(
        &format!("/api/v1/application-answers/drafts/{id}/approve-reuse"),
        body.to_string().as_bytes(),
        nonce,
    )
}
async fn approve_reuse(c: &mut PgConnection, id: Uuid, scope: &str, nonce: &str) -> Result<Value> {
    use automated_apply_agents::answer_reuse;
    let body = reuse_body(scope);
    answer_reuse::approve(
        c,
        id,
        answer_reuse::approval_input(body.clone()).unwrap(),
        reuse_proof(id, &body, nonce),
        true,
        false,
    )
    .await
}
fn reuse_settings() -> automated_apply_agents::answer_service::Settings {
    automated_apply_agents::answer_service::Settings::from_values(
        &BTreeMap::from([("APPROVED_ANSWER_REUSE_ENABLED".into(), "true".into())]),
        true,
        BTreeMap::new(),
    )
    .unwrap()
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn reusable_narrative_approval_is_durable_scoped_and_revocable_without_extra_draft_or_inference()
 {
    use automated_apply_agents::{answer_reuse, answer_service};
    let (mut c, id) = reusable_draft_fixture().await;
    let nonce = Uuid::new_v4().simple().to_string();
    let approved = approve_reuse(&mut c, id, "general_profile", &nonce)
        .await
        .unwrap();
    assert_eq!(approved["approved"], true);
    let mut observer = connection().await;
    let saved: Value = sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(format!("answer:{id}"))
        .fetch_one(&mut observer)
        .await
        .unwrap();
    assert_eq!(saved["approved"], true);
    assert_eq!(saved["profile_version"], 4);
    let result = answer_service::generate(
        &mut c,
        json!({"question":"Walk me through a project","save_draft":true}),
        &reuse_settings(),
    )
    .await
    .unwrap();
    assert_eq!(result["source"], "approved_answer");
    assert_eq!(result["reused_draft_id"], json!(id));
    assert_eq!(result["requires_review"], true);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM application_answer_drafts")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        4
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM llm_monthly_usage")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    let list = answer_reuse::approvals(&mut c, true, true).await.unwrap();
    assert_eq!(list["approvals"][id.to_string()]["approved"], true);
    answer_reuse::revoke(&mut c, id).await.unwrap();
    let result = answer_service::generate(
        &mut c,
        json!({"question":"Walk me through a project"}),
        &reuse_settings(),
    )
    .await
    .unwrap();
    assert!(result["reused_draft_id"].is_null());
    assert_eq!(result["source"], "deterministic_extractive");
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn reusable_narrative_never_reuses_a_changed_draft_evidence_or_profile() {
    use automated_apply_agents::answer_service;
    for change in ["draft", "evidence", "profile"] {
        let (mut c, id) = reusable_draft_fixture().await;
        approve_reuse(
            &mut c,
            id,
            "general_profile",
            &Uuid::new_v4().simple().to_string(),
        )
        .await
        .unwrap();
        match change {
            "draft" => {
                sqlx::query("UPDATE application_answer_drafts SET answer=answer||' Changed text.' WHERE id=$1").bind(id).execute(&mut c).await.unwrap();
            }
            "evidence" => {
                sqlx::query("INSERT INTO candidate_evidence(id,candidate_profile_id,evidence_type,title,content,user_confirmed,created_at,updated_at) VALUES($1,$2,'other','Changed context','New factual evidence',false,clock_timestamp(),clock_timestamp())").bind(Uuid::new_v4()).bind(profile_pin().id).execute(&mut c).await.unwrap();
            }
            _ => {
                sqlx::query(
                    "UPDATE candidate_profiles SET version=5 WHERE singleton_key='primary'",
                )
                .execute(&mut c)
                .await
                .unwrap();
            }
        }
        let result = answer_service::generate(
            &mut c,
            json!({"question":"Walk me through a project"}),
            &reuse_settings(),
        )
        .await
        .unwrap();
        assert!(result["reused_draft_id"].is_null(), "{change}");
        assert_eq!(result["used_llm"], false);
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn reusable_approval_requires_current_review_owner_signature_scope_and_non_replayed_nonce() {
    use automated_apply_agents::{answer_reuse, answer_store};
    let (mut c, id) = reusable_draft_fixture().await;
    let nonce = Uuid::new_v4().simple().to_string();
    let body = reuse_body("general_profile");
    assert_eq!(
        answer_reuse::approve(
            &mut c,
            id,
            answer_reuse::approval_input(body.clone()).unwrap(),
            reuse_proof(id, &body, &nonce),
            false,
            false
        )
        .await
        .err(),
        Some(Failure("answer_reuse_disabled"))
    );
    assert_eq!(
        approve_reuse(&mut c, id, "same_job", &nonce).await.err(),
        Some(Failure("answer_reuse_job_required"))
    );
    answer_store::review(
        &mut c,
        id,
        answer_store::Review {
            review_status: answer_store::ReviewStatus::Draft,
        },
    )
    .await
    .unwrap();
    assert_eq!(
        approve_reuse(&mut c, id, "general_profile", &nonce)
            .await
            .err(),
        Some(Failure("answer_reuse_current_review_required"))
    );
    answer_store::review(
        &mut c,
        id,
        answer_store::Review {
            review_status: answer_store::ReviewStatus::Reviewed,
        },
    )
    .await
    .unwrap();
    approve_reuse(&mut c, id, "general_profile", &nonce)
        .await
        .unwrap();
    assert_eq!(
        approve_reuse(&mut c, id, "general_profile", &nonce)
            .await
            .err(),
        Some(Failure("owner_approval_already_used"))
    );
    let foreign = Uuid::from_u128(0x30000000000000000000000000000003);
    assert_eq!(
        approve_reuse(
            &mut c,
            foreign,
            "general_profile",
            &Uuid::new_v4().simple().to_string()
        )
        .await
        .err(),
        Some(Failure("answer_draft_not_found"))
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM owner_preferences WHERE starts_with(key,'owner-proof:')"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        1
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn reusable_approval_and_owner_nonce_rollback_together_on_deferred_commit_failure() {
    let (mut c, id) = reusable_draft_fixture().await;
    let nonce = Uuid::new_v4().simple().to_string();
    sqlx::raw_sql("CREATE OR REPLACE FUNCTION fixture_reuse_commit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.key LIKE 'answer:%' THEN RAISE EXCEPTION 'fictional_reuse_commit_failure';END IF;RETURN NEW;END $$;CREATE CONSTRAINT TRIGGER fixture_reuse_commit AFTER INSERT ON owner_preferences DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fixture_reuse_commit()").execute(&mut c).await.unwrap();
    assert_eq!(
        approve_reuse(&mut c, id, "general_profile", &nonce)
            .await
            .err(),
        Some(Failure("profile_database_error"))
    );
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'answer:') OR starts_with(key,'owner-proof:')").fetch_one(&mut c).await.unwrap(),0);
    sqlx::query("DROP TRIGGER fixture_reuse_commit ON owner_preferences")
        .execute(&mut c)
        .await
        .unwrap();
    approve_reuse(&mut c, id, "general_profile", &nonce)
        .await
        .unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn answer_generation_and_reuse_http_preserve_owner_auth_body_and_signature_boundaries() {
    let mut c = narrative_fixture().await;
    let mut values = host_values();
    values.insert("APPROVED_ANSWER_REUSE_ENABLED".into(), "true".into());
    values.insert(
        "BROWSER_OWNER_APPROVAL_KEY".into(),
        MISSING_SIGNING_KEY.into(),
    );
    let (url, stop, server) = http_fixture_values(values).await;
    let http = client();
    let generate = format!("{url}/api/v1/application-answers/generate");
    assert_eq!(
        http.post(&generate)
            .body("bad json")
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    assert_eq!(
        http.get(&generate)
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        405
    );
    assert_eq!(
        http.post(&generate)
            .bearer_auth(HOST_TOKEN)
            .header("x-agent-client", "extension")
            .json(&json!({"question":"Email"}))
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    assert_eq!(
        http.post(&generate)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"question":"Email","approved":true}))
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    let response = http
        .post(&generate)
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"question":"Describe a project you built","save_draft":true}))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let result: Value = response.json().await.unwrap();
    let id = result["draft_id"].as_str().unwrap();
    let draft = format!("{url}/api/v1/application-answers/drafts/{id}");
    assert_eq!(
        http.patch(&draft)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"review_status":"reviewed","answer":"Changed answer"}))
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    assert_eq!(
        http.patch(&draft)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"review_status":"reviewed"}))
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    let path = format!("/api/v1/application-answers/drafts/{id}/approve-reuse");
    let body = reuse_body("general_profile").to_string();
    assert_eq!(
        http.post(format!("{url}{path}"))
            .bearer_auth(HOST_TOKEN)
            .body(body.clone())
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    let signature = missing_signature(
        &path,
        body.as_bytes(),
        &Uuid::new_v4().simple().to_string(),
        0,
    );
    assert_eq!(
        http.post(format!("{url}{path}"))
            .bearer_auth(HOST_TOKEN)
            .header("X-Browser-Owner-Approval", signature)
            .body(body)
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    let list: Value = http
        .get(format!("{url}/api/v1/application-answers/reuse-approvals"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(list["approvals"][id]["approved"], true);
    let reused: Value = http
        .post(&generate)
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"question":"Walk me through a project","save_draft":true}))
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(reused["reused_draft_id"], id);
    assert_eq!(
        http.post(format!("{draft}/revoke-reuse"))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    let evidence: Value = http
        .get(format!("{draft}/opportunity-evidence"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(evidence, json!({"evidence":[]}));
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM application_packets")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    stop.cancel();
    server.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn same_job_reuse_cannot_cross_job_identity_or_survive_saved_listing_corrections() {
    use automated_apply_agents::answer_service;
    let (mut c, id) = reusable_draft_fixture().await;
    let a = Uuid::new_v4();
    let b = Uuid::new_v4();
    for job in [a, b] {
        sqlx::query("INSERT INTO jobs(id,title,description,job_url,source_platform) VALUES($1,'Fictional Rust role','Saved description','https://example.com/role','greenhouse')").bind(job).execute(&mut c).await.unwrap();
    }
    sqlx::query("UPDATE application_answer_drafts SET job_id=$1 WHERE id=$2")
        .bind(a)
        .bind(id)
        .execute(&mut c)
        .await
        .unwrap();
    approve_reuse(&mut c, id, "same_job", &Uuid::new_v4().simple().to_string())
        .await
        .unwrap();
    let same = answer_service::generate(
        &mut c,
        json!({"question":"Walk me through a project","job_id":a}),
        &reuse_settings(),
    )
    .await
    .unwrap();
    assert_eq!(same["reused_draft_id"], json!(id));
    let other = answer_service::generate(
        &mut c,
        json!({"question":"Walk me through a project","job_id":b}),
        &reuse_settings(),
    )
    .await
    .unwrap();
    assert!(other["reused_draft_id"].is_null());
    sqlx::query("UPDATE jobs SET description='Corrected description' WHERE id=$1")
        .bind(a)
        .execute(&mut c)
        .await
        .unwrap();
    let changed = answer_service::generate(
        &mut c,
        json!({"question":"Walk me through a project","job_id":a}),
        &reuse_settings(),
    )
    .await
    .unwrap();
    assert!(changed["reused_draft_id"].is_null());
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn historical_opportunity_reads_verify_full_hash_and_reuse_keeps_employer_scope_current() {
    use automated_apply_agents::{answer_reuse, job_context::Reviewed, python_json};
    let (mut c, id) = reusable_draft_fixture().await;
    let job = Uuid::new_v4();
    let raw = json!({"id":job,"company_id":null,"title":"Fictional role","description":"The employer builds Rust APIs.","job_url":"https://example.com/job","application_url":null,"source_platform":"greenhouse","discovery_metadata":{}});
    let view = Reviewed::new(raw.clone(), None).unwrap();
    let reviewed:String=sqlx::query_scalar("SELECT to_char((clock_timestamp()-interval '1 minute') AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.US')||'+00:00'").fetch_one(&mut c).await.unwrap();
    let mut material = json!({"binding":view.binding().unwrap(),"reviewed_at":reviewed,"source_url":"https://example.com/job?private=fictional","company_source_url":"https://example.com/company","job_text":"The employer builds Rust APIs.","company_text":"The employer develops queue software."});
    let digest = python_json::digest(&material);
    material["digest"] = json!(digest);
    sqlx::query("INSERT INTO jobs(id,title,description,job_url,source_platform,discovery_metadata) VALUES($1,$2,$3,$4,'greenhouse',$5)").bind(job).bind(raw["title"].as_str().unwrap()).bind(raw["description"].as_str().unwrap()).bind(raw["job_url"].as_str().unwrap()).bind(json!({"application_opportunity":material})).execute(&mut c).await.unwrap();
    let mut stored = material.clone();
    stored["job_id"] = json!(job);
    sqlx::query("INSERT INTO owner_preferences(key,value) VALUES($1,$2)")
        .bind(format!("opp:{}", &digest[..40]))
        .bind(stored)
        .execute(&mut c)
        .await
        .unwrap();
    let references = json!([{"source_type":"verified_project","source_id":format!("{}:project:0",profile_pin().id)},{"source_type":"opportunity_job","source_id":format!("{digest}:job")}]);
    sqlx::query(
        "UPDATE application_answer_drafts SET job_id=$1,evidence_references=$2 WHERE id=$3",
    )
    .bind(job)
    .bind(references)
    .bind(id)
    .execute(&mut c)
    .await
    .unwrap();
    let read = answer_reuse::opportunity_evidence(&mut c, id)
        .await
        .unwrap();
    assert_eq!(
        read["evidence"][0]["excerpt"],
        "The employer builds Rust APIs."
    );
    assert_eq!(
        read["evidence"][0]["source_url"],
        "https://example.com/job?private=fictional"
    );
    let nonce = Uuid::new_v4().simple().to_string();
    assert_eq!(
        approve_reuse(&mut c, id, "general_profile", &nonce)
            .await
            .err(),
        Some(Failure("answer_reuse_exact_job_required"))
    );
    assert_eq!(
        approve_reuse(&mut c, id, "same_job", &nonce).await.err(),
        Some(Failure("answer_reuse_context_changed"))
    );
    let body = reuse_body("same_job");
    answer_reuse::approve(
        &mut c,
        id,
        answer_reuse::approval_input(body.clone()).unwrap(),
        reuse_proof(id, &body, &nonce),
        true,
        true,
    )
    .await
    .unwrap();
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{job_text}','\"Tampered excerpt\"') WHERE key=$1").bind(format!("opp:{}",&digest[..40])).execute(&mut c).await.unwrap();
    assert!(
        answer_reuse::opportunity_evidence(&mut c, id)
            .await
            .unwrap()["evidence"]
            .as_array()
            .unwrap()
            .is_empty()
    );
}
