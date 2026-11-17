#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn saved_feed_packet_keeps_its_source_link_and_requires_manual_handoff() {
    let (mut c, job) = packet_service_fixture().await;
    let canonical = "https://himalayas.app/companies/fictional/jobs/rust-engineer";
    let application =
        "https://himalayas.app/companies/fictional/jobs/rust-engineer?source=feed%2Bfixture#apply";
    let metadata = json!({"source_name":"himalayas","source_job_id":"fictional-id","original_url":application});
    sqlx::query("UPDATE jobs SET source_platform='himalayas',job_url=$2,application_url=$3,
         source_verification_status='source_reported',status='discovered',discovery_metadata=$4 WHERE id=$1")
        .bind(job).bind(canonical).bind(application).bind(metadata).execute(&mut c).await.unwrap();
    sqlx::query("INSERT INTO job_source_observations(id,job_id,source,original_url) VALUES($1,$2,'himalayas',$3)")
        .bind(Uuid::new_v4()).bind(job).bind(application).execute(&mut c).await.unwrap();
    let packet = packet_create(&mut c, job, "fictional-feed-packet", json!([]))
        .await
        .unwrap();
    assert_eq!(packet["snapshot"]["platform"], "himalayas");
    assert_eq!(packet["snapshot"]["original_job_url"], canonical);
    assert_eq!(
        packet["snapshot"]["destination"]["application_url"],
        application
    );
    assert_eq!(packet["snapshot"]["destination"]["valid"], true);
    assert_eq!(packet["tracking_state"], "not_applied");

    let context = browser_context();
    browser_connect(&mut c, &context).await;
    browser_call(
        &mut c,
        BrowserRoute::Select,
        json!({"expected_version":0,"profile_binding_id":context["profile_binding_id"]}),
    )
    .await
    .unwrap();
    let heartbeat = browser_native(
        &mut c,
        "heartbeat_chrome_profile",
        &context,
        json!({"profile_commands_enabled":true}),
    )
    .await
    .unwrap();
    assert_eq!(heartbeat["ok"], true);
    let request = browser_enqueue_input(&context, &packet);
    assert_eq!(
        browser_call(&mut c, BrowserRoute::Enqueue, request)
            .await
            .unwrap_err(),
        Failure("unsupported_form_adapter")
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM owner_preferences WHERE starts_with(key,'chr_cmd:')"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        0
    );

    sqlx::query(
        "UPDATE job_source_observations SET original_url=$2 WHERE job_id=$1 AND source='himalayas'",
    )
    .bind(job)
    .bind(canonical)
    .execute(&mut c)
    .await
    .unwrap();
    let read = automated_apply_agents::packet_service::dispatch(
        &mut c,
        "GET",
        &format!(
            "/api/v1/application-packets/{}",
            packet["id"].as_str().unwrap()
        ),
        None,
        b"",
        &packet_settings(),
        &answer_settings(),
    )
    .await
    .unwrap()
    .0;
    assert_eq!(read["readiness"]["stale"], true);
    assert_eq!(read["tracking_state"], "not_applied");
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn hiringcafe_packet_keeps_the_source_posting_and_invalidates_changed_employer_evidence() {
    let (mut c, job) = packet_service_fixture().await;
    let listing = "https://hiringcafe.com/job/rust-fictional-abc123abc123abcd";
    let attributed = format!("{listing}?utm_source=claude");
    let canonical = "https://jobs.lever.co/fictional/12345678-1234-4234-8234-123456789012";
    let employer = format!("{canonical}/apply");
    let metadata = json!({
        "source_name":"hiringcafe","original_url":attributed,"canonical_url":canonical,
        "application_url":employer,"data_provenance":{"import_mode":"manual"}
    });
    sqlx::query("UPDATE jobs SET source_platform='hiringcafe',job_url=$2,application_url=$3,
         source_verification_status='requires_review',status='discovered',discovery_metadata=$4 WHERE id=$1")
        .bind(job).bind(canonical).bind(&employer).bind(metadata).execute(&mut c).await.unwrap();
    sqlx::query("INSERT INTO job_source_observations(id,job_id,source,original_url) VALUES($1,$2,'hiringcafe',$3)")
        .bind(Uuid::new_v4()).bind(job).bind(attributed).execute(&mut c).await.unwrap();
    let packet = packet_create(&mut c, job, "fictional-employer-packet", json!([]))
        .await
        .unwrap();
    assert_eq!(packet["snapshot"]["original_job_url"], listing);
    assert_eq!(
        packet["snapshot"]["destination"]["application_url"],
        employer
    );
    assert_eq!(packet["snapshot"]["destination"]["valid"], true);
    assert_eq!(packet["tracking_state"], "not_applied");

    sqlx::query("UPDATE jobs SET application_url=$2 WHERE id=$1")
        .bind(job)
        .bind("https://jobs.lever.co/other/12345678-1234-4234-8234-123456789012/apply")
        .execute(&mut c)
        .await
        .unwrap();
    let path = format!(
        "/api/v1/application-packets/{}",
        packet["id"].as_str().unwrap()
    );
    let read = automated_apply_agents::packet_service::dispatch(
        &mut c,
        "GET",
        &path,
        None,
        b"",
        &packet_settings(),
        &answer_settings(),
    )
    .await
    .unwrap()
    .0;
    assert_eq!(read["readiness"]["stale"], true);
    assert_eq!(read["tracking_state"], "not_applied");
    let snapshot = &read["snapshot"];
    assert_ne!(
        snapshot["destination"]["application_url"],
        "https://jobs.lever.co/other/12345678-1234-4234-8234-123456789012/apply"
    );
}
