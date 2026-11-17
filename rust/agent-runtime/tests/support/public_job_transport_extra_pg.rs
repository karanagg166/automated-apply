//! Deferred pagination, response-loss and original-context/cancellation fixtures.
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_job_incomplete_second_board_retains_only_observed_jobs_without_a_skip_cursor() {
    let mut c = public_job_access_fixture().await;
    let (mut v, f, stop, task) = public_job_http(PublicJobSource::Greenhouse, "partial").await;
    v.insert(
        "GREENHOUSE_BOARDS".into(),
        json!({"fictional":"Fictional Employer","zeta":"Fictional Zeta Employer"}).to_string(),
    );
    let result = public_job_acquire(
        &mut c,
        &v,
        PublicJobSource::Greenhouse,
        json!({"limit":2}),
        63200,
    )
    .await
    .unwrap();
    assert_eq!(result["status"], "partial");
    assert_eq!(result["transport_state"], "upstream_error");
    assert_eq!(result["batch_complete"], false);
    assert_eq!(result["jobs"].as_array().unwrap().len(), 1);
    assert!(result["next_cursor"].is_null());
    assert!(!result.to_string().contains("CANARY"));
    assert_eq!(f.calls.load(Ordering::SeqCst), 2);
    let replay = public_job_acquire(
        &mut c,
        &v,
        PublicJobSource::Greenhouse,
        json!({"limit":2}),
        63200,
    )
    .await
    .unwrap();
    assert_eq!(replay, result);
    assert_eq!(f.calls.load(Ordering::SeqCst), 2);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_job_sorted_cross_board_pagination_clears_stale_next_cursor_after_final_inventory() {
    let mut c = public_job_access_fixture().await;
    let (mut v, f, stop, task) = public_job_http(PublicJobSource::Greenhouse, "ok").await;
    v.insert(
        "GREENHOUSE_BOARDS".into(),
        json!({"zeta":"Fictional Zeta Employer","fictional":"Fictional Employer"}).to_string(),
    );
    let jobs_before: Value =
        sqlx::query_scalar("SELECT jsonb_agg(to_jsonb(j) ORDER BY id) FROM jobs j")
            .fetch_one(&mut c)
            .await
            .unwrap();
    let result = public_job_acquire(
        &mut c,
        &v,
        PublicJobSource::Greenhouse,
        json!({"limit":2}),
        62800,
    )
    .await
    .unwrap();
    assert_eq!(result["jobs"].as_array().unwrap().len(), 2);
    assert!(result["next_cursor"].is_null());
    assert_eq!(result["jobs"][0]["company_name"], "Fictional Employer");
    assert_eq!(result["jobs"][1]["company_name"], "Fictional Zeta Employer");
    assert_eq!(f.calls.load(Ordering::SeqCst), 2);
    sqlx::query("UPDATE provider_access_windows SET next_allowed_at=clock_timestamp()-interval '1 second' WHERE provider='greenhouse'").execute(&mut c).await.unwrap();
    let result = public_job_acquire(
        &mut c,
        &v,
        PublicJobSource::Greenhouse,
        json!({"limit":1,"page":2}),
        62801,
    )
    .await
    .unwrap();
    assert_eq!(result["jobs"].as_array().unwrap().len(), 1);
    assert_eq!(result["jobs"][0]["company_name"], "Fictional Zeta Employer");
    assert!(result["next_cursor"].is_null());
    assert_eq!(f.calls.load(Ordering::SeqCst), 4);
    let jobs_after: Value =
        sqlx::query_scalar("SELECT jsonb_agg(to_jsonb(j) ORDER BY id) FROM jobs j")
            .fetch_one(&mut c)
            .await
            .unwrap();
    assert_eq!(jobs_after, jobs_before);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_job_incomplete_http_response_is_retained_unknown_and_same_uuid_never_reissues_get()
{
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let mut c = public_job_access_fixture().await;
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let task = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut bytes = vec![0; 16384];
        let n = stream.read(&mut bytes).await.unwrap();
        assert!(
            String::from_utf8_lossy(&bytes[..n])
                .starts_with("GET /fixtures/arbeitnow/www.arbeitnow.com/api/job-board-api?page=1 ")
        );
        stream.write_all(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 500\r\nConnection: close\r\n\r\n{\"private\":\"PRIVATE_SOCKET_RESPONSE_CANARY\"").await.unwrap();
        stream.shutdown().await.unwrap();
    });
    let values = BTreeMap::from([(
        "RUST_PUBLIC_JOBS_FIXTURE_ORIGIN".into(),
        format!("http://{addr}/"),
    )]);
    let result = public_job_acquire(
        &mut c,
        &values,
        PublicJobSource::Arbeitnow,
        json!({}),
        62900,
    )
    .await
    .unwrap();
    task.await.unwrap();
    assert_eq!(result["status"], "outcome_unknown");
    assert_eq!(result["transport_state"], "outcome_unknown");
    assert_eq!(result["provider_http_attempts"], 1);
    assert_eq!(result["provider_responses_observed"], 1);
    assert!(!result.to_string().contains("CANARY"));
    let before = public_job_access_snapshot(&mut c).await;
    let replay = public_job_acquire(
        &mut c,
        &values,
        PublicJobSource::Arbeitnow,
        json!({}),
        62900,
    )
    .await
    .unwrap();
    assert_eq!(replay, result);
    assert_eq!(public_job_access_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_job_transport_changed_employer_context_is_not_dispatched_and_does_not_refund_pace()
{
    let mut c = public_job_access_fixture().await;
    let (v, f, stop, task) = public_job_http(PublicJobSource::Greenhouse, "ok").await;
    let settings = automated_apply_agents::source_registry::Settings::from_values(&v).unwrap();
    let mut changed = v.clone();
    changed.insert(
        "GREENHOUSE_BOARDS".into(),
        json!({"fictional":"Different Fictional Employer"}).to_string(),
    );
    let client = PublicJobClient::from_values(&changed, true).unwrap();
    let result = PublicJobService {
        settings: &settings,
        client: &client,
    }
    .acquire(
        &mut c,
        PublicJobSource::Greenhouse,
        json!({}),
        Uuid::from_u128(63100),
    )
    .await
    .unwrap();
    assert_eq!(result["status"], "not_dispatched");
    assert_eq!(
        result["errors"],
        json!(["public_job_original_grant_changed"])
    );
    assert_eq!(result["provider_http_attempts"], 0);
    assert_eq!(result["provider_response_retained"], false);
    assert_eq!(result["finding_retained"], true);
    assert_eq!(f.calls.load(Ordering::SeqCst), 0);
    assert_eq!(
        public_job_acquire(&mut c, &v, PublicJobSource::Greenhouse, json!({}), 63101).await,
        Err(Failure("public_job_source_rate_limited"))
    );
    stop.cancel();
    task.await.unwrap();
}
