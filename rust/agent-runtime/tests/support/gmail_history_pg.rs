//! Deferred local Gmail history API, isolation, CAS and retention. No mailbox/provider IO.
const HISTORY_ACCOUNT_1: &str = "00000000-0000-4000-8000-000000000001";
const HISTORY_ACCOUNT_2: &str = "00000000-0000-4000-8000-000000000002";
async fn gmail_history_call(c: &mut PgConnection, path: &str, value: Value) -> Result<Value> {
    let route = automated_apply_agents::gmail_history::route(path).unwrap();
    automated_apply_agents::gmail_history::dispatch(
        c,
        route,
        route.method(),
        None,
        value.to_string().as_bytes(),
    )
    .await
}
fn gmail_history_review(account: &str, evidence: &str) -> Value {
    json!({"expected_version":0,"company":" Fictional Employer ","role":" Rust Engineer ","applied_at":"2000-01-01T00:00:00Z","job_url":null,"evidence":{account:[evidence]},"status":"applied","confirmed_application":true,"retention_days":365,"owner_reviewed":true})
}
async fn gmail_history_seed_message(c: &mut PgConnection, id: &str, account: &str) {
    browser_save(c,&format!("gmail_msg:{id}"),json!({"id":id,"account_id":account,"expires_at":"2099-01-01T00:00:00Z","subject":"PRIVATE_MAIL_SUBJECT_CANARY","body":"PRIVATE_MAIL_BODY_CANARY"})).await;
}
async fn gmail_history_fixture() -> PgConnection {
    let (mut c, _, _) = browser_command_fixture().await;
    gmail_history_seed_message(&mut c, &"a".repeat(32), HISTORY_ACCOUNT_1).await;
    gmail_history_seed_message(&mut c, &"b".repeat(32), HISTORY_ACCOUNT_2).await;
    c
}
fn gmail_history_path(id: &Value, action: &str) -> String {
    format!(
        "{}/{}/{action}",
        automated_apply_agents::gmail_history::PATH,
        id.as_str().unwrap()
    )
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_history_review_merges_selected_mailboxes_and_retains_confirmed_status_without_raw_mail()
 {
    let mut c = gmail_history_fixture().await;
    let input = gmail_history_review(HISTORY_ACCOUNT_1, &"a".repeat(32));
    let first = gmail_history_call(
        &mut c,
        &format!("{}/review", automated_apply_agents::gmail_history::PATH),
        input.clone(),
    )
    .await
    .unwrap();
    assert_eq!(first["version"], 1);
    assert_eq!(first["company"], "Fictional Employer");
    let mut update = gmail_history_review(HISTORY_ACCOUNT_2, &"b".repeat(32));
    update["expected_version"] = json!(1);
    update["confirmed_application"] = json!(false);
    update["status"] = json!("uncertain");
    let second = gmail_history_call(
        &mut c,
        &format!("{}/review", automated_apply_agents::gmail_history::PATH),
        update,
    )
    .await
    .unwrap();
    assert_eq!(second["id"], first["id"]);
    assert_eq!(second["version"], 2);
    assert_eq!(second["confirmed_application"], true);
    assert_eq!(second["status"], "applied");
    assert_eq!(second["evidence"].as_object().unwrap().len(), 2);
    assert!(!second.to_string().contains("PRIVATE_MAIL"));
    assert!(second.get("owner_reviewed").is_none());
    let list = gmail_history_call(
        &mut c,
        automated_apply_agents::gmail_history::PATH,
        Value::Null,
    )
    .await
    .unwrap();
    assert_eq!(list["history"], json!([second]));
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'apply_budget:') OR starts_with(key,'provider_receipt:')").fetch_one(&mut c).await.unwrap(),0);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_history_wrong_account_expired_evidence_and_stale_version_roll_back_complete_review()
{
    let mut c = gmail_history_fixture().await;
    let path = format!("{}/review", automated_apply_agents::gmail_history::PATH);
    let input = gmail_history_review(HISTORY_ACCOUNT_1, &"a".repeat(32));
    let saved = gmail_history_call(&mut c, &path, input.clone())
        .await
        .unwrap();
    for index in 0..3 {
        let mut bad = input.clone();
        bad["expected_version"] = json!(1);
        let expected = match index {
            0 => {
                bad["evidence"] = json!({HISTORY_ACCOUNT_2:["a".repeat(32)]});
                "gmail_history_evidence_unavailable"
            }
            1 => {
                let key = format!("gmail_msg:{}", "a".repeat(32));
                let mut raw = browser_pref(&mut c, &key).await;
                raw["expires_at"] = json!("2000-01-01T00:00:00Z");
                browser_save(&mut c, &key, raw).await;
                "gmail_history_evidence_unavailable"
            }
            _ => {
                bad["expected_version"] = json!(0);
                "gmail_history_version_conflict"
            }
        };
        let before = browser_snapshot(&mut c).await;
        assert_eq!(
            gmail_history_call(&mut c, &path, bad).await.unwrap_err(),
            Failure(expected)
        );
        assert_eq!(browser_snapshot(&mut c).await, before);
        assert_eq!(
            browser_pref(
                &mut c,
                &format!("gmail_application:{}", saved["id"].as_str().unwrap())
            )
            .await,
            saved
        );
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_history_concurrent_same_opportunity_reviews_commit_exactly_one_version() {
    let mut c = gmail_history_fixture().await;
    let mut other = connection().await;
    let input = gmail_history_review(HISTORY_ACCOUNT_1, &"a".repeat(32));
    let path = format!("{}/review", automated_apply_agents::gmail_history::PATH);
    let (a, b) = tokio::join!(
        gmail_history_call(&mut c, &path, input.clone()),
        gmail_history_call(&mut other, &path, input)
    );
    assert_eq!(usize::from(a.is_ok()) + usize::from(b.is_ok()), 1);
    let rows: Vec<Value> = sqlx::query_scalar(
        "SELECT value FROM owner_preferences WHERE starts_with(key,'gmail_application:')",
    )
    .fetch_all(&mut c)
    .await
    .unwrap();
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0]["version"], 1);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_history_get_is_read_only_and_avoids_owner_lock_while_omitting_expired_records() {
    let mut c = gmail_history_fixture().await;
    let saved = gmail_history_call(
        &mut c,
        &format!("{}/review", automated_apply_agents::gmail_history::PATH),
        gmail_history_review(HISTORY_ACCOUNT_1, &"a".repeat(32)),
    )
    .await
    .unwrap();
    let mut expired = saved.clone();
    expired["id"] = json!("e".repeat(32));
    expired["expires_at"] = json!("2000-01-01T00:00:00Z");
    browser_save(
        &mut c,
        &format!("gmail_application:{}", "e".repeat(32)),
        expired,
    )
    .await;
    let before = browser_snapshot(&mut c).await;
    let mut other = connection().await;
    let mut lock = other.begin().await.unwrap();
    sqlx::query(
        "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
    )
    .execute(&mut *lock)
    .await
    .unwrap();
    sqlx::query("SET lock_timeout='100ms'")
        .execute(&mut c)
        .await
        .unwrap();
    let list = gmail_history_call(
        &mut c,
        automated_apply_agents::gmail_history::PATH,
        Value::Null,
    )
    .await
    .unwrap();
    assert_eq!(list["history"], json!([saved]));
    assert_eq!(browser_snapshot(&mut c).await, before);
    lock.rollback().await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_history_retention_and_forget_use_versions_and_preserve_only_tombstone_after_forget()
{
    let mut c = gmail_history_fixture().await;
    let saved = gmail_history_call(
        &mut c,
        &format!("{}/review", automated_apply_agents::gmail_history::PATH),
        gmail_history_review(HISTORY_ACCOUNT_1, &"a".repeat(32)),
    )
    .await
    .unwrap();
    let retain = gmail_history_path(&saved["id"], "retention");
    let forgotten = gmail_history_path(&saved["id"], "forget");
    let extended = gmail_history_call(
        &mut c,
        &retain,
        json!({"expected_version":1,"retention_days":7300}),
    )
    .await
    .unwrap();
    assert_eq!(extended["version"], 2);
    assert_eq!(extended["retention_days"], 7300);
    let before = browser_snapshot(&mut c).await;
    assert_eq!(
        gmail_history_call(&mut c, &forgotten, json!({"expected_version":1}))
            .await
            .unwrap_err(),
        Failure("gmail_history_version_conflict")
    );
    assert_eq!(browser_snapshot(&mut c).await, before);
    assert_eq!(
        gmail_history_call(&mut c, &forgotten, json!({"expected_version":2}))
            .await
            .unwrap(),
        json!({"deleted":true})
    );
    assert_eq!(
        browser_pref(
            &mut c,
            &format!("gmail_application:{}", saved["id"].as_str().unwrap())
        )
        .await,
        json!({"deleted":true,"version":3})
    );
    assert_eq!(
        gmail_history_call(
            &mut c,
            &retain,
            json!({"expected_version":3,"retention_days":365})
        )
        .await
        .unwrap_err(),
        Failure("gmail_history_version_conflict")
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_history_same_canonical_url_deduplicates_explicit_owner_corrections_without_new_status_inference()
 {
    let mut c = gmail_history_fixture().await;
    let path = format!("{}/review", automated_apply_agents::gmail_history::PATH);
    let mut first = gmail_history_review(HISTORY_ACCOUNT_1, &"a".repeat(32));
    first["job_url"] = json!("https://boards.greenhouse.io/fictional/jobs/123?utm_source=mail");
    let saved = gmail_history_call(&mut c, &path, first.clone())
        .await
        .unwrap();
    first["expected_version"] = json!(1);
    first["company"] = json!("Owner corrected fictional employer");
    first["role"] = json!("Owner corrected role");
    first["job_url"] = json!("https://job-boards.greenhouse.io/fictional/jobs/123/");
    first["status"] = json!("recruiter_response");
    let updated = gmail_history_call(&mut c, &path, first).await.unwrap();
    assert_eq!(updated["id"], saved["id"]);
    assert_eq!(
        updated["job_url"],
        "https://job-boards.greenhouse.io/fictional/jobs/123"
    );
    assert_eq!(updated["status"], "recruiter_response");
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM owner_preferences WHERE starts_with(key,'gmail_application:')"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        1
    );
    assert!(updated.get("worker_dispatched").is_none());
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_history_ambiguous_legacy_duplicates_are_not_arbitrarily_merged() {
    let mut c = gmail_history_fixture().await;
    let path = format!("{}/review", automated_apply_agents::gmail_history::PATH);
    let input = gmail_history_review(HISTORY_ACCOUNT_1, &"a".repeat(32));
    let saved = gmail_history_call(&mut c, &path, input.clone())
        .await
        .unwrap();
    let mut duplicate = saved.clone();
    duplicate["id"] = json!("c".repeat(32));
    browser_save(
        &mut c,
        &format!("gmail_application:{}", "c".repeat(32)),
        duplicate,
    )
    .await;
    let before = browser_snapshot(&mut c).await;
    let mut update = input;
    update["expected_version"] = json!(1);
    assert_eq!(
        gmail_history_call(&mut c, &path, update).await.unwrap_err(),
        Failure("gmail_history_identity_conflict")
    );
    assert_eq!(browser_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_history_suppressed_review_ack_rolls_back_history_and_owner_mutation() {
    let mut c = gmail_history_fixture().await;
    let before = browser_snapshot(&mut c).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_gmail_history_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'gmail_application:') THEN RETURN NULL; END IF; RETURN NEW; END $$; CREATE TRIGGER fixture_gmail_history_drop BEFORE INSERT OR UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_gmail_history_drop()").execute(&mut c).await.unwrap();
    let result = gmail_history_call(
        &mut c,
        &format!("{}/review", automated_apply_agents::gmail_history::PATH),
        gmail_history_review(HISTORY_ACCOUNT_1, &"a".repeat(32)),
    )
    .await;
    sqlx::raw_sql("DROP TRIGGER fixture_gmail_history_drop ON owner_preferences; DROP FUNCTION fixture_gmail_history_drop()").execute(&mut c).await.unwrap();
    assert_eq!(
        result.unwrap_err(),
        Failure("gmail_history_write_ack_failed")
    );
    assert_eq!(browser_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_history_retention_scrubs_only_expired_metadata_in_bounded_batches_and_noop_avoids_owner_lock()
 {
    let mut c = gmail_history_fixture().await;
    let path = format!("{}/review", automated_apply_agents::gmail_history::PATH);
    let mut saved = gmail_history_call(
        &mut c,
        &path,
        gmail_history_review(HISTORY_ACCOUNT_1, &"a".repeat(32)),
    )
    .await
    .unwrap();
    saved["expires_at"] = json!("2000-01-01T00:00:00Z");
    browser_save(
        &mut c,
        &format!("gmail_application:{}", saved["id"].as_str().unwrap()),
        saved.clone(),
    )
    .await;
    for i in 0..100 {
        browser_save(
            &mut c,
            &format!("gmail_msg:{i:032x}"),
            json!({"expires_at":"2000-01-01T00:00:00Z","body":"PRIVATE_EXPIRED_CANARY"}),
        )
        .await;
    }
    browser_save(
        &mut c,
        "gmail_draft_oauth:expired",
        json!({"expires_at":"2000-01-01T00:00:00Z","verifier":"PRIVATE_VERIFIER_CANARY"}),
    )
    .await;
    let retained = json!({"expires_at":"2099-01-01T00:00:00Z","token":"PRIVATE_RETAINED_CANARY","state":"outcome_unknown"});
    browser_save(&mut c, "gm54_account:1", retained.clone()).await;
    assert_eq!(
        automated_apply_agents::gmail_history::maintenance(&mut c)
            .await
            .unwrap(),
        100
    );
    assert_eq!(
        automated_apply_agents::gmail_history::maintenance(&mut c)
            .await
            .unwrap(),
        2
    );
    assert_eq!(
        browser_pref(
            &mut c,
            &format!("gmail_application:{}", saved["id"].as_str().unwrap())
        )
        .await,
        json!({"deleted":true,"version":2})
    );
    assert_eq!(
        browser_pref(&mut c, "gmail_draft_oauth:expired").await,
        json!({"consumed":true,"expired":true})
    );
    assert_eq!(browser_pref(&mut c, "gm54_account:1").await, retained);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'gmail_msg:') AND value->>'status'='purged'").fetch_one(&mut c).await.unwrap(),100);
    let mut other = connection().await;
    let mut lock = other.begin().await.unwrap();
    sqlx::query(
        "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
    )
    .execute(&mut *lock)
    .await
    .unwrap();
    sqlx::query("SET lock_timeout='100ms'")
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        automated_apply_agents::gmail_history::maintenance(&mut c)
            .await
            .unwrap(),
        0
    );
    lock.rollback().await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_history_expired_record_cannot_be_revived_by_retention_or_carry_old_confirmed_evidence_into_new_review()
 {
    let mut c = gmail_history_fixture().await;
    let path = format!("{}/review", automated_apply_agents::gmail_history::PATH);
    let mut saved = gmail_history_call(
        &mut c,
        &path,
        gmail_history_review(HISTORY_ACCOUNT_1, &"a".repeat(32)),
    )
    .await
    .unwrap();
    saved["expires_at"] = json!("2000-01-01T00:00:00Z");
    browser_save(
        &mut c,
        &format!("gmail_application:{}", saved["id"].as_str().unwrap()),
        saved.clone(),
    )
    .await;
    let before = browser_snapshot(&mut c).await;
    assert_eq!(
        gmail_history_call(
            &mut c,
            &gmail_history_path(&saved["id"], "retention"),
            json!({"expected_version":1,"retention_days":365})
        )
        .await
        .unwrap_err(),
        Failure("gmail_history_expired_record")
    );
    assert_eq!(browser_snapshot(&mut c).await, before);
    let mut review = gmail_history_review(HISTORY_ACCOUNT_2, &"b".repeat(32));
    review["expected_version"] = json!(1);
    review["confirmed_application"] = json!(false);
    review["status"] = json!("uncertain");
    let fresh = gmail_history_call(&mut c, &path, review).await.unwrap();
    assert_eq!(fresh["version"], 2);
    assert_eq!(fresh["confirmed_application"], false);
    assert_eq!(fresh["status"], "uncertain");
    assert_eq!(fresh["evidence"].as_object().unwrap().len(), 1);
    assert!(fresh["evidence"].get(HISTORY_ACCOUNT_1).is_none());
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_history_actual_http_keeps_owner_auth_and_exact_methods_for_local_only_review() {
    let mut c = gmail_history_fixture().await;
    let (url, stop, server) = http_fixture_values(browser_values()).await;
    let http = client();
    let endpoint = format!(
        "{url}{}/review",
        automated_apply_agents::gmail_history::PATH
    );
    let input = gmail_history_review(HISTORY_ACCOUNT_1, &"a".repeat(32));
    assert_eq!(
        http.post(&endpoint)
            .json(&input)
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    assert_eq!(
        http.post(&endpoint)
            .bearer_auth(HOST_TOKEN)
            .header("x-agent-client", BROWSER_EXTENSION)
            .json(&input)
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    let wrong = http
        .get(&endpoint)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(wrong.status(), 405);
    assert_eq!(wrong.headers()["allow"], "POST");
    let invalid = http
        .post(&endpoint)
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"owner_reviewed":true}))
        .send()
        .await
        .unwrap();
    assert_eq!(invalid.status(), 422);
    let result = http
        .post(&endpoint)
        .bearer_auth(HOST_TOKEN)
        .json(&input)
        .send()
        .await
        .unwrap();
    let status = result.status();
    let result: Value = result.json().await.unwrap();
    assert_eq!(status, 200, "{result}");
    assert_eq!(result["version"], 1);
    let list: Value = http
        .get(format!(
            "{url}{}",
            automated_apply_agents::gmail_history::PATH
        ))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(list["history"].as_array().unwrap().len(), 1);
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM owner_preferences WHERE starts_with(key,'apply_budget:')"
        )
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
async fn gmail_history_new_review_blocks_duplicate_local_preparation_without_a_mailbox_read_or_provider_receipt()
 {
    let (mut c, job, intent) = legacy_fixture().await;
    gmail_history_seed_message(&mut c, &"a".repeat(32), HISTORY_ACCOUNT_1).await;
    let mut input = gmail_history_review(HISTORY_ACCOUNT_1, &"a".repeat(32));
    input["job_url"] = json!("https://www.naukri.com/job-listings-fictional-923456789012");
    let review = gmail_history_call(
        &mut c,
        &format!("{}/review", automated_apply_agents::gmail_history::PATH),
        input,
    )
    .await
    .unwrap();
    assert_eq!(review["confirmed_application"], true);
    let claim = automated_apply_agents::execution::legacy_work::claim(&mut c)
        .await
        .unwrap()
        .unwrap();
    legacy_prepare_claim(&mut c, claim).await.unwrap();
    let saved = browser_pref(&mut c, &format!("exec:{}", intent["id"].as_str().unwrap())).await;
    assert_eq!(saved["state"], "REJECTED");
    assert_eq!(
        saved["diagnostic"],
        "previous_application_or_unknown_submission"
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM application_packets WHERE job_id=$1")
            .bind(job)
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    assert!(saved["worker_dispatched"].is_null());
}
