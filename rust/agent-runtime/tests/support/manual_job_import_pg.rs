#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn hiringcafe_import_accepts_attributed_slugs_and_reuses_existing_source_evidence() {
    let mut c = public_intake_fixture().await;
    let (base, stop, server) = http_fixture().await;
    let client = client();
    let posting = "https://hiringcafe.com/job/rust-engineer-fictional-abc123abc123abcd?utm_source=claude&utm_medium=mcp";
    let employer = "https://jobs.lever.co/fictional/12345678-1234-4234-8234-123456789012/apply";
    let import = |url: &str, application: Option<&str>| {
        let route = format!("{base}/api/v1/discovery/runs/{}", Uuid::new_v4());
        client.put(route).bearer_auth(HOST_TOKEN).json(&json!({
            "source":"hiringcafe","use_profile":false,"manual_jobs":[{
                "source_name":"hiringcafe","title":"Fictional Rust engineer","original_url":url,
                "application_url":application
            }]
        }))
    };
    let first: Value = import(posting, Some(employer))
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(first["counts"]["inserted"], 1);
    let id: Uuid = first["job_ids"][0].as_str().unwrap().parse().unwrap();
    let job: Value = sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1")
        .bind(id)
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(job["application_url"], employer);
    let original: Vec<(String, String)> =
        sqlx::query_as("SELECT source,original_url FROM job_source_observations WHERE job_id=$1")
            .bind(id)
            .fetch_all(&mut c)
            .await
            .unwrap();
    assert_eq!(original, vec![("hiringcafe".into(), posting.into())]);
    let prepared = automated_apply_agents::packet_platform::select_at(
        &job,
        &original,
        &Default::default(),
        chrono::Utc::now(),
    )
    .unwrap();
    assert_eq!(
        prepared.destination.application_url.as_deref(),
        posting.split_once('?').map(|(link, _)| link)
    );

    for alias in [
        "https://hiringcafe.com/job/abc123abc123abcd",
        "https://www.hiringcafe.com/job/updated-title-abc123abc123abcd",
    ] {
        let reused: Value = import(alias, None)
            .send()
            .await
            .unwrap()
            .error_for_status()
            .unwrap()
            .json()
            .await
            .unwrap();
        assert_eq!(reused["counts"]["duplicate"], 1);
        assert_eq!(reused["job_ids"], json!([id]));
    }
    let conflict = import(
        "https://hiringcafe.com/job/new-title-abc123abc123abcd",
        Some("https://jobs.lever.co/different/12345678-1234-4234-8234-123456789012/apply"),
    )
    .send()
    .await
    .unwrap();
    assert!(!conflict.status().is_success());
    assert_eq!(
        sqlx::query_scalar::<_, Value>("SELECT to_jsonb(j) FROM jobs j WHERE id=$1")
            .bind(id)
            .fetch_one(&mut c)
            .await
            .unwrap(),
        job
    );
    let retained: Vec<(String, String)> =
        sqlx::query_as("SELECT source,original_url FROM job_source_observations WHERE job_id=$1")
            .bind(id)
            .fetch_all(&mut c)
            .await
            .unwrap();
    assert_eq!(retained, original);
    stop.cancel();
    server.await.unwrap();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn manual_platform_discovery_saves_review_evidence_and_replays_without_mutating_duplicates() {
    let mut c = public_intake_fixture().await;
    let (base, stop, server) = http_fixture().await;
    let client = client();
    let request = Uuid::new_v4();
    let route = format!("{base}/api/v1/discovery/runs/{request}");
    let posting = "https://internshala.com/internship/detail/fictional-rust-role1750000000";
    let mut input = json!({"source":"internshala","use_profile":false,"manual_jobs":[
        {"source_name":"internshala","title":"Fictional Rust internship","original_url":posting,
         "application_url":"https://jobs.lever.co/fictional/12345678-1234-4234-8234-123456789012/apply",
         "is_confirmed_current":true,"source_verification_status":"verified",
         "data_provenance":{"private":"INPUT_METADATA_CANARY"}},
        {"source_name":"internshala","title":"Other site","original_url":"https://example.org/other"}
    ]});
    let plan: Value = client
        .post(format!("{base}/api/v1/discovery/preview"))
        .bearer_auth(HOST_TOKEN)
        .json(&input)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(plan["source"]["owner_run_supported"], true);
    assert_eq!(plan["provider_calls"], 0);
    assert_eq!(plan["writes"], 0);
    assert_eq!(
        plan["manual_import"],
        json!({"valid_records":1,"rejected_records":1})
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM discovery_runs")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    let first: Value = client
        .put(&route)
        .bearer_auth(HOST_TOKEN)
        .json(&input)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(first["id"], json!(request));
    assert_eq!(first["status"], "partial");
    assert_eq!(first["counts"]["inserted"], 1);
    assert_eq!(first["counts"]["rejected"], 1);
    assert_eq!(first["usage"]["provider_http_attempts"], 0);
    assert_eq!(first["application_dispatch"], false);
    let replay: Value = client
        .put(&route)
        .bearer_auth(HOST_TOKEN)
        .json(&input)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(first, replay);
    let read: Value = client
        .get(&route)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(read, first);
    let job_id = first["job_ids"][0]
        .as_str()
        .unwrap()
        .parse::<Uuid>()
        .unwrap();
    let job: Value = sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1")
        .bind(job_id)
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(job["source_verification_status"], "requires_review");
    assert_eq!(job["discovery_metadata"]["is_confirmed_current"], false);
    assert_eq!(
        job["discovery_metadata"]["data_provenance"],
        json!({"import_mode":"manual"})
    );
    assert!(job["company_id"].is_null());
    assert!(!job.to_string().contains("INPUT_METADATA_CANARY"));
    let observed: Vec<(String, String)> =
        sqlx::query_as("SELECT source,original_url FROM job_source_observations WHERE job_id=$1")
            .bind(job_id)
            .fetch_all(&mut c)
            .await
            .unwrap();
    let prepared = automated_apply_agents::packet_platform::select_at(
        &job,
        &observed,
        &Default::default(),
        chrono::Utc::now(),
    )
    .unwrap();
    assert!(prepared.destination.valid);
    assert_eq!(
        prepared.destination.application_url.as_deref(),
        Some(posting)
    );

    input["manual_jobs"][0]["title"] = json!("Changed title");
    let conflict = client
        .put(&route)
        .bearer_auth(HOST_TOKEN)
        .json(&input)
        .send()
        .await
        .unwrap();
    assert_eq!(conflict.status(), 409);
    let new_id = Uuid::new_v4();
    let duplicate: Value = client
        .put(format!("{base}/api/v1/discovery/runs/{new_id}"))
        .bearer_auth(HOST_TOKEN)
        .json(&input)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(duplicate["job_ids"], json!([job_id]));
    assert_eq!(duplicate["counts"]["duplicate"], 1);
    assert_eq!(
        sqlx::query_scalar::<_, Value>("SELECT to_jsonb(j) FROM jobs j WHERE id=$1")
            .bind(job_id)
            .fetch_one(&mut c)
            .await
            .unwrap(),
        job
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM job_source_observations WHERE job_id=$1"
        )
        .bind(job_id)
        .fetch_one(&mut c)
        .await
        .unwrap(),
        1
    );
    stop.cancel();
    server.await.unwrap();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn manual_import_receipt_trigger_drift_rolls_back_listing_and_run() {
    let mut c = public_intake_fixture().await;
    sqlx::raw_sql("CREATE OR REPLACE FUNCTION fixture_manual_marker_drift() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN UPDATE jobs SET source_verification_status='verified' WHERE source_platform='hiringcafe'; RETURN NULL; END $$;
        CREATE TRIGGER fixture_manual_marker_drift AFTER INSERT ON owner_preferences FOR EACH ROW
        WHEN (starts_with(NEW.key,'manual_run:')) EXECUTE FUNCTION fixture_manual_marker_drift()")
        .execute(&mut c).await.unwrap();
    let (base, stop, server) = http_fixture().await;
    let id = Uuid::new_v4();
    let response = client().put(format!("{base}/api/v1/discovery/runs/{id}")).bearer_auth(HOST_TOKEN)
        .json(&json!({"source":"hiringcafe","use_profile":false,"manual_jobs":[{
            "source_name":"hiringcafe","title":"Fictional hiringcafe role","original_url":"https://hiringcafe.com/job/fictional1234567"
        }]})).send().await.unwrap();
    assert_eq!(response.status(), 503);
    assert_eq!(
        response.json::<Value>().await.unwrap()["detail"],
        "public_job_write_ack_failed"
    );
    for table in ["jobs", "discovery_runs", "job_source_observations"] {
        assert_eq!(
            sqlx::query_scalar::<_, i64>(sqlx::AssertSqlSafe(format!(
                "SELECT count(*) FROM {table}"
            )))
            .fetch_one(&mut c)
            .await
            .unwrap(),
            0
        );
    }
    stop.cancel();
    server.await.unwrap();
    sqlx::raw_sql("DROP TRIGGER fixture_manual_marker_drift ON owner_preferences; DROP FUNCTION fixture_manual_marker_drift()")
        .execute(&mut c).await.unwrap();
}
