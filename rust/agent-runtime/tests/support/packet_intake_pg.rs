#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn packet_intake_http_prepares_one_draft_and_preserves_submission_authority() {
    let (mut database, _) = packet_service_fixture().await;
    sqlx::raw_sql(
        "ALTER TABLE jobs ADD COLUMN canonical_key text UNIQUE,
        ADD COLUMN content_identity text UNIQUE, ADD UNIQUE (job_url)",
    )
    .execute(&mut database)
    .await
    .unwrap();
    let (url, stop, service) = http_fixture().await;
    let (other_url, other_stop, other_service) = http_fixture().await;
    let http = client();
    let intake = format!("{url}/api/v1/application-packets/intake");
    let alias = format!("{other_url}/api/v1/browser-applications");
    let submit =
        |path: &str, payload: &Value| http.post(path).bearer_auth(HOST_TOKEN).json(payload);
    let payload = json!({
        "application_url":"https://jobs.lever.co/fictional/engineer-100/apply",
        "company_name":"  Fictional Intake Company  ","job_title":"  Platform Engineer  ",
        "idempotency_key":"fictional-intake-draft-100",
    });
    assert_eq!(
        http.post(&intake)
            .json(&payload)
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    assert_eq!(
        submit(&intake, &payload)
            .header("x-agent-client", "extension")
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    let forbidden_method = http
        .get(&intake)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(forbidden_method.status(), 405);
    assert_eq!(forbidden_method.headers()["allow"], "POST");
    for bad_url in [
        "http://127.0.0.1/fictional",
        "https://www.linkedin.com/jobs/fictional",
        "https://jobs.lever.co/fictional/engineer-100/apply?token=fixture",
        "https://employer.example/unspecified",
    ] {
        let mut invalid = payload.clone();
        invalid["application_url"] = json!(bad_url);
        assert_eq!(
            submit(&intake, &invalid).send().await.unwrap().status(),
            422
        );
    }

    let (canonical, browser_alias) = tokio::join!(
        submit(&intake, &payload).send(),
        submit(&alias, &payload).send()
    );
    let canonical = canonical.unwrap();
    let code = canonical.status();
    let prepared: Value = canonical.json().await.unwrap();
    assert_eq!(code, 201, "{prepared}");
    let browser_alias = browser_alias.unwrap();
    assert_eq!(browser_alias.status(), 200);
    let replay: Value = browser_alias.json().await.unwrap();
    assert_eq!(prepared["id"], replay["id"]);
    assert_eq!(prepared["platform"], "owner_extension");
    assert_eq!(prepared["lifecycle_state"], "created");
    assert_eq!(prepared["tracking_state"], "not_applied");
    assert_eq!(prepared["submission_mode"], "manual_handoff");
    assert_eq!(
        prepared["snapshot"]["destination"]["application_url"],
        payload["application_url"]
    );
    assert_eq!(
        prepared["snapshot"]["destination"]["source_confidence"],
        "unverified"
    );
    let saved: Value = sqlx::query_scalar("SELECT discovery_metadata FROM jobs WHERE job_url=$1")
        .bind(payload["application_url"].as_str().unwrap())
        .fetch_one(&mut database)
        .await
        .unwrap();
    assert_eq!(saved["employer_identity_verified"], false);

    let mut wrong_context = payload.clone();
    wrong_context["company_name"] = json!("Unrelated fictional company");
    assert_eq!(
        submit(&intake, &wrong_context)
            .send()
            .await
            .unwrap()
            .status(),
        409
    );

    let mut other_url = payload.clone();
    other_url["application_url"] = json!("https://jobs.lever.co/fictional/engineer-200/apply");
    other_url["idempotency_key"] = json!("fictional-intake-draft-200");
    assert_eq!(
        submit(&intake, &other_url).send().await.unwrap().status(),
        409
    );

    let company_count: i64 = sqlx::query_scalar("SELECT count(*) FROM companies")
        .fetch_one(&mut database)
        .await
        .unwrap();
    let mut reused = other_url.clone();
    reused["company_name"] = json!("Fictional Rollback Company");
    reused["idempotency_key"] = payload["idempotency_key"].clone();
    assert_eq!(submit(&intake, &reused).send().await.unwrap().status(), 409);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM companies")
            .fetch_one(&mut database)
            .await
            .unwrap(),
        company_count
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM jobs WHERE source_platform='owner_extension'"
        )
        .fetch_one(&mut database)
        .await
        .unwrap(),
        1
    );
    for (table, rows) in [
        ("SELECT count(*) FROM application_packets", 1),
        (
            "SELECT count(*) FROM application_events WHERE event_type='packet_created'",
            1,
        ),
        ("SELECT count(*) FROM application_submission_evidence", 0),
        (
            "SELECT count(*) FROM owner_preferences WHERE starts_with(key,'apply_budget:')",
            0,
        ),
    ] {
        assert_eq!(
            sqlx::query_scalar::<_, i64>(table)
                .fetch_one(&mut database)
                .await
                .unwrap(),
            rows
        );
    }
    stop.cancel();
    other_stop.cancel();
    service.await.unwrap();
    other_service.await.unwrap();
}
