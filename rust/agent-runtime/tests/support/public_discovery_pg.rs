#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_feed_reservation_cache_and_failed_outcomes_are_durable_without_job_writes() {
    use automated_apply_agents::public_discovery::{self, Platform, Reservation};
    let (mut c, _job) = packet_service_fixture().await;
    let (token, record) = match public_discovery::reserve(&mut c, Platform::Himalayas, 20)
        .await
        .unwrap()
    {
        Reservation::Fetch { token, record } => (token, record),
        _ => panic!("new feed must reserve"),
    };
    assert_eq!(
        public_discovery::reserve(&mut c, Platform::Himalayas, 20)
            .await
            .err()
            .map(|e| e.0),
        Some("public_feed_cooldown")
    );
    let batch=public_discovery::himalayas(br#"{"jobs":[{"guid":"fixture-source-id","title":"Rust Engineer","companyName":"Example","applicationLink":"https://himalayas.app/companies/example/jobs/engineer","description":"Public fictional source","locationRestrictions":[],"timezoneRestrictions":[],"categories":[]}] }"#).unwrap();
    let response =
        public_discovery::finish(&mut c, Platform::Himalayas, token, record, Ok(batch), 20)
            .await
            .unwrap();
    assert_eq!(response["cached"], false);
    assert_eq!(response["application_dispatch"], false);
    assert_eq!(response["saved_to_job_queue"], false);
    let cached = match public_discovery::reserve(&mut c, Platform::Himalayas, 1)
        .await
        .unwrap()
    {
        Reservation::Cached(value) => value,
        _ => panic!("cached feed must not reserve again"),
    };
    assert_eq!(cached["cached"], true);
    assert_eq!(cached["jobs"], response["jobs"]);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM jobs")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        1
    );
    let (token, record) = match public_discovery::reserve(&mut c, Platform::WeWorkRemotely, 20)
        .await
        .unwrap()
    {
        Reservation::Fetch { token, record } => (token, record),
        _ => unreachable!(),
    };
    assert_eq!(
        public_discovery::finish(
            &mut c,
            Platform::WeWorkRemotely,
            token,
            record,
            Err(Failure("public_feed_rate_limited")),
            20
        )
        .await
        .unwrap_err()
        .0,
        "public_feed_rate_limited"
    );
    assert_eq!(
        public_discovery::reserve(&mut c, Platform::WeWorkRemotely, 20)
            .await
            .err()
            .map(|e| e.0),
        Some("public_feed_cooldown")
    );
    let saved: Value = sqlx::query_scalar(
        "SELECT value FROM owner_preferences WHERE key='public_feed:we_work_remotely'",
    )
    .fetch_one(&mut c)
    .await
    .unwrap();
    assert_eq!(saved["state"], "failed");
    assert_eq!(saved["failure_code"], "public_feed_rate_limited");
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_feed_suppressed_reservation_never_grants_network_admission() {
    use automated_apply_agents::public_discovery::{self, Platform};
    let (mut c, _job) = packet_service_fixture().await;
    sqlx::raw_sql("CREATE FUNCTION suppress_feed_reservation() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN RETURN NULL; END$$; CREATE TRIGGER suppress_feed_reservation BEFORE UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION suppress_feed_reservation()").execute(&mut c).await.unwrap();
    assert_eq!(
        public_discovery::reserve(&mut c, Platform::Himalayas, 20)
            .await
            .err()
            .map(|e| e.0),
        Some("public_feed_write_ack_failed")
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM owner_preferences WHERE key='public_feed:himalayas'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        0
    );
    sqlx::raw_sql("DROP TRIGGER suppress_feed_reservation ON owner_preferences; DROP FUNCTION suppress_feed_reservation()").execute(&mut c).await.unwrap();
}
