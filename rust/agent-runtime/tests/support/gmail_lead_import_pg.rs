// Deferred selected Gmail lead intake: local identity/ACK/history only, no URL/provider request.
async fn gmail_lead_fixture() -> (PgConnection, Uuid, Uuid) {
    let (mut c, _) = listing_fixture().await;
    let (one, two) = seed_gmail_read_accounts(&mut c).await;
    let id = "a".repeat(32);
    gmail_read_seed_evidence(
        &mut c,
        &id,
        one,
        "2099-01-01T00:00:00Z",
        "2020-01-01T00:00:00Z",
    )
    .await;
    let key = format!("gmail_msg:{id}");
    let mut message = browser_pref(&mut c, &key).await;
    message["links"] = json!([
        "https://example.com/jobs/one",
        "https://example.com/jobs/two"
    ]);
    browser_save(&mut c, &key, message).await;
    (c, one, two)
}
fn gmail_lead_path(account: Uuid, evidence: &str) -> String {
    format!(
        "{}/{account}/evidence/{evidence}/import",
        automated_apply_agents::gmail_accounts::PATH
    )
}
fn gmail_lead_input(url: &str) -> Value {
    json!({"job_url":url,"title":"Owner reviewed fictional vacancy","reviewed_job_evidence":true})
}
async fn gmail_lead_call(
    c: &mut PgConnection,
    account: Uuid,
    evidence: &str,
    input: Value,
) -> Result<Value> {
    gmail_read_call(
        c,
        &gmail_lead_path(account, evidence),
        None,
        input,
        &gmail_read_settings(),
    )
    .await
}
async fn gmail_lead_counts(c: &mut PgConnection) -> Value {
    sqlx::query_scalar("SELECT jsonb_build_object('jobs',(SELECT count(*) FROM jobs),'companies',(SELECT count(*) FROM companies),'observations',(SELECT count(*) FROM job_source_observations))").fetch_one(c).await.unwrap()
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_reviewed_lead_creates_only_unverified_local_job_with_unknown_employer_and_per_url_marker()
 {
    let (mut c, one, _) = gmail_lead_fixture().await;
    let result = gmail_lead_call(
        &mut c,
        one,
        &"a".repeat(32),
        gmail_lead_input("https://example.com/jobs/one"),
    )
    .await
    .unwrap();
    assert_eq!(result["inserted_count"], 1);
    assert_eq!(result["failed_count"], 0);
    let id = result["job_ids"][0]
        .as_str()
        .unwrap()
        .parse::<Uuid>()
        .unwrap();
    let job: Value = sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1")
        .bind(id)
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(job["source_platform"], "gmail_alert");
    assert_eq!(job["status"], "discovered");
    assert_eq!(job["company_id"], Value::Null);
    assert_eq!(job["source_verification_status"], "requires_review");
    assert_eq!(job["discovery_metadata"]["is_confirmed_current"], false);
    assert_eq!(
        job["discovery_metadata"]["quality_flags"],
        json!(["company_unknown"])
    );
    let message = browser_pref(&mut c, &format!("gmail_msg:{}", "a".repeat(32))).await;
    assert_eq!(
        message["imported_leads"]["https://example.com/jobs/one"],
        result["job_ids"]
    );
    assert_eq!(message["imported_job_ids"], result["job_ids"]);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'apply_budget:') OR starts_with(key,'provider_receipt:')").fetch_one(&mut c).await.unwrap(),0);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_reviewed_lead_retry_preserves_human_job_decision_and_source_observation_identity() {
    let (mut c, one, _) = gmail_lead_fixture().await;
    let mut input = gmail_lead_input("https://example.com/jobs/one");
    input["company_name"] = json!("Fictional Employer");
    input["company_domain"] = json!("fictional.example");
    let first = gmail_lead_call(&mut c, one, &"a".repeat(32), input.clone())
        .await
        .unwrap();
    let id = first["job_ids"][0]
        .as_str()
        .unwrap()
        .parse::<Uuid>()
        .unwrap();
    sqlx::query("UPDATE jobs SET title='Human retained role',status='applied',match_score=88,match_explanation='Retained review',description='Owner retained description' WHERE id=$1").bind(id).execute(&mut c).await.unwrap();
    let before: Value = sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1")
        .bind(id)
        .fetch_one(&mut c)
        .await
        .unwrap();
    input["title"] = json!("Changed owner observed title");
    let second = gmail_lead_call(&mut c, one, &"a".repeat(32), input)
        .await
        .unwrap();
    assert_eq!(second["job_ids"], first["job_ids"]);
    assert_eq!(second["inserted_count"], 0);
    assert_eq!(second["duplicate_count"], 1);
    let after: Value = sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1")
        .bind(id)
        .fetch_one(&mut c)
        .await
        .unwrap();
    for name in [
        "title",
        "status",
        "match_score",
        "match_explanation",
        "description",
        "skills_required",
        "company_id",
        "discovery_metadata",
    ] {
        assert_eq!(after[name], before[name], "{name}");
    }
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM job_source_observations WHERE source='gmail_alert'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        1
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_reviewed_lead_wrong_account_expired_or_unselected_url_never_marks_evidence_or_creates_job()
 {
    let (mut c, one, two) = gmail_lead_fixture().await;
    let key = format!("gmail_msg:{}", "a".repeat(32));
    let original = browser_pref(&mut c, &key).await;
    for index in 0..3 {
        browser_save(&mut c, &key, original.clone()).await;
        let (mut account, mut input) = (one, gmail_lead_input("https://example.com/jobs/one"));
        let expected = match index {
            0 => {
                account = two;
                "gmail_evidence_not_found"
            }
            1 => {
                let mut expired = original.clone();
                expired["expires_at"] = json!("2000-01-01T00:00:00Z");
                browser_save(&mut c, &key, expired).await;
                "gmail_evidence_not_found"
            }
            _ => {
                input["job_url"] = json!("https://example.com/jobs/not-selected");
                "gmail_lead_not_in_selected_evidence"
            }
        };
        let before = browser_snapshot(&mut c).await;
        let counts = gmail_lead_counts(&mut c).await;
        assert_eq!(
            gmail_lead_call(&mut c, account, &"a".repeat(32), input)
                .await
                .unwrap_err(),
            Failure(expected)
        );
        assert_eq!(browser_snapshot(&mut c).await, before);
        assert_eq!(gmail_lead_counts(&mut c).await, counts);
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_reviewed_lead_changed_employer_for_strong_existing_identity_is_not_merged_or_marked()
{
    let (mut c, one, _) = gmail_lead_fixture().await;
    let mut first = gmail_lead_input("https://example.com/jobs/one");
    first["company_name"] = json!("Original Fictional Employer");
    let imported = gmail_lead_call(&mut c, one, &"a".repeat(32), first.clone())
        .await
        .unwrap();
    let counts = gmail_lead_counts(&mut c).await;
    let before = browser_snapshot(&mut c).await;
    first["company_name"] = json!("Different Fictional Employer");
    assert_eq!(
        gmail_lead_call(&mut c, one, &"a".repeat(32), first)
            .await
            .unwrap_err(),
        Failure("gmail_lead_identity_requires_review")
    );
    assert_eq!(gmail_lead_counts(&mut c).await, counts);
    assert_eq!(browser_snapshot(&mut c).await, before);
    assert_eq!(imported["job_ids"].as_array().unwrap().len(), 1);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_reviewed_lead_concurrent_mailboxes_share_one_job_and_each_retains_exact_link_marker()
{
    let (mut c, one, two) = gmail_lead_fixture().await;
    let other_id = "b".repeat(32);
    gmail_read_seed_evidence(
        &mut c,
        &other_id,
        two,
        "2099-01-01T00:00:00Z",
        "2020-01-01T00:00:00Z",
    )
    .await;
    let mut other = connection().await;
    let input = gmail_lead_input("https://example.com/jobs/one");
    let first_id = "a".repeat(32);
    let (a, b) = tokio::join!(
        gmail_lead_call(&mut c, one, &first_id, input.clone()),
        gmail_lead_call(&mut other, two, &other_id, input.clone())
    );
    let successful = a.as_ref().ok().or(b.as_ref().ok()).unwrap();
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM jobs WHERE canonical_key='https://example.com/jobs/one'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        1
    );
    if a.is_err() {
        gmail_lead_call(&mut c, one, &first_id, input.clone())
            .await
            .unwrap();
    }
    if b.is_err() {
        gmail_lead_call(&mut other, two, &other_id, input)
            .await
            .unwrap();
    }
    for evidence in [first_id, other_id] {
        let message = browser_pref(&mut c, &format!("gmail_msg:{evidence}")).await;
        assert_eq!(
            message["imported_leads"]["https://example.com/jobs/one"],
            successful["job_ids"]
        );
    }
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM job_source_observations WHERE source='gmail_alert'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        1
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_reviewed_lead_similarity_produces_hints_but_distinct_urls_remain_distinct_jobs() {
    let (mut c, one, _) = gmail_lead_fixture().await;
    let mut input = gmail_lead_input("https://example.com/jobs/one");
    input["company_name"] = json!("Fictional Employer");
    let first = gmail_lead_call(&mut c, one, &"a".repeat(32), input.clone())
        .await
        .unwrap();
    input["job_url"] = json!("https://example.com/jobs/two");
    let second = gmail_lead_call(&mut c, one, &"a".repeat(32), input)
        .await
        .unwrap();
    assert_ne!(first["job_ids"], second["job_ids"]);
    assert_eq!(second["inserted_count"], 1);
    let id = second["job_ids"][0].as_str().unwrap();
    assert_eq!(second["possible_duplicates"][id], first["job_ids"]);
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM jobs WHERE source_platform='gmail_alert'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        2
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_reviewed_lead_suppressed_observation_ack_rolls_back_job_company_and_evidence_marker()
{
    let (mut c, one, _) = gmail_lead_fixture().await;
    let counts = gmail_lead_counts(&mut c).await;
    let before = browser_snapshot(&mut c).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_gmail_lead_observation_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.source='gmail_alert' THEN RETURN NULL; END IF; RETURN NEW; END $$; CREATE TRIGGER fixture_gmail_lead_observation_drop BEFORE INSERT OR UPDATE ON job_source_observations FOR EACH ROW EXECUTE FUNCTION fixture_gmail_lead_observation_drop()").execute(&mut c).await.unwrap();
    let mut input = gmail_lead_input("https://example.com/jobs/one");
    input["company_name"] = json!("New Fictional Employer");
    let result = gmail_lead_call(&mut c, one, &"a".repeat(32), input).await;
    sqlx::raw_sql("DROP TRIGGER fixture_gmail_lead_observation_drop ON job_source_observations; DROP FUNCTION fixture_gmail_lead_observation_drop()").execute(&mut c).await.unwrap();
    assert_eq!(result.unwrap_err(), Failure("gmail_read_write_ack_failed"));
    assert_eq!(gmail_lead_counts(&mut c).await, counts);
    assert_eq!(browser_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_reviewed_lead_suppressed_final_message_marker_ack_also_rolls_back_durable_job_and_observation()
 {
    let (mut c, one, _) = gmail_lead_fixture().await;
    let counts = gmail_lead_counts(&mut c).await;
    let before = browser_snapshot(&mut c).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_gmail_lead_marker_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'gmail_msg:') AND NEW.value ? 'imported_leads' THEN RETURN NULL; END IF; RETURN NEW; END $$; CREATE TRIGGER fixture_gmail_lead_marker_drop BEFORE UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_gmail_lead_marker_drop()").execute(&mut c).await.unwrap();
    let result = gmail_lead_call(
        &mut c,
        one,
        &"a".repeat(32),
        gmail_lead_input("https://example.com/jobs/one"),
    )
    .await;
    sqlx::raw_sql("DROP TRIGGER fixture_gmail_lead_marker_drop ON owner_preferences; DROP FUNCTION fixture_gmail_lead_marker_drop()").execute(&mut c).await.unwrap();
    assert_eq!(result.unwrap_err(), Failure("gmail_read_write_ack_failed"));
    assert_eq!(gmail_lead_counts(&mut c).await, counts);
    assert_eq!(browser_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_reviewed_lead_legacy_canonical_url_normalization_preserves_original_url_source_and_human_status()
 {
    let (mut c, one, _) = gmail_lead_fixture().await;
    let existing: Uuid = sqlx::query_scalar("SELECT id FROM jobs ORDER BY id LIMIT 1")
        .fetch_one(&mut c)
        .await
        .unwrap();
    sqlx::query("UPDATE jobs SET job_url='https://example.com/jobs/one/?utm_source=retained',canonical_key=NULL,status='shortlisted',company_id=NULL WHERE id=$1").bind(existing).execute(&mut c).await.unwrap();
    let before: Value = sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1")
        .bind(existing)
        .fetch_one(&mut c)
        .await
        .unwrap();
    let result = gmail_lead_call(
        &mut c,
        one,
        &"a".repeat(32),
        gmail_lead_input("https://example.com/jobs/one"),
    )
    .await
    .unwrap();
    assert_eq!(result["job_ids"], json!([existing]));
    assert_eq!(result["duplicate_count"], 1);
    let after: Value = sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1")
        .bind(existing)
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(after["canonical_key"], "https://example.com/jobs/one");
    for name in ["job_url", "source_platform", "status", "title"] {
        assert_eq!(after[name], before[name]);
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_reviewed_lead_actual_http_owner_auth_method_and_exact_selected_url_are_enforced() {
    let (mut c, one, _) = gmail_lead_fixture().await;
    let (url, stop, server) = http_fixture_values(browser_values()).await;
    let http = client();
    let target = format!("{url}{}", gmail_lead_path(one, &"a".repeat(32)));
    let input = gmail_lead_input("https://example.com/jobs/one");
    assert_eq!(
        http.post(&target)
            .json(&input)
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    assert_eq!(
        http.post(&target)
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
        .get(&target)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(wrong.status(), 405);
    assert_eq!(wrong.headers()["allow"], "POST");
    let response = http
        .post(&target)
        .bearer_auth(HOST_TOKEN)
        .json(&gmail_lead_input("https://example.com/jobs/not-selected"))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 409);
    let response = http
        .post(&target)
        .bearer_auth(HOST_TOKEN)
        .json(&input)
        .send()
        .await
        .unwrap();
    let code = response.status();
    let result: Value = response.json().await.unwrap();
    assert_eq!(code, 200, "{result}");
    assert_eq!(result["inserted_count"], 1);
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
