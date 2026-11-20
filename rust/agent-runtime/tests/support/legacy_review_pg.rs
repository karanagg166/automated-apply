#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn legacy_review_http_preserves_saved_campaign_submission_and_packet_evidence() {
    let (mut database, job) = packet_service_fixture().await;
    let packet = packet_create(&mut database, job, "fictional-legacy-review", json!([]))
        .await
        .unwrap();
    let packet_id = packet["id"].as_str().unwrap();
    let campaign_id = Uuid::new_v4();
    let timestamp = "2026-11-20T00:00:00Z";
    let saved_campaign = json!({"id":campaign_id,"created_at":timestamp,"updated_at":timestamp,
        "message":"Fictional saved request","state":"awaiting_approval",
        "plan":{"intent":"search","filters":{}}});
    let digest = "a".repeat(64);
    let saved_submission = json!({"application_id":packet_id,"job_id":job,
        "employer_id":Uuid::new_v4(),"employer":"Fictional employer", "job_title":"Fictional engineer",
        "plan_id":Uuid::new_v4(),"campaign_id":campaign_id,"campaign_revision":1,
        "candidate_profile_id":packet["candidate_profile_id"],"candidate_version":packet["candidate_profile_version"],
        "context_digest":digest,"packet_revision":1,"project_digest":digest,
        "document_id":"fixture-document","document_digest":digest,"adapter":"lever",
        "origin":"http://127.0.0.1:49151","application_url":"http://127.0.0.1:49151/fictional/apply",
        "request_url":"http://127.0.0.1:49151/fictional/submit","confirmation_url":"http://127.0.0.1:49151/fictional/confirmation",
        "receipt_url":"http://127.0.0.1:49151/fictional/receipt","expires_at":timestamp,
        "state":"submission_uncertain","reason":"retained_for_reconciliation"});
    let saved_analysis =
        json!({"diagnostic":"step_started", "fields":[],"warnings":["Fictional retained warning"]});
    for (key, value) in [
        (format!("campaign:{campaign_id}"), &saved_campaign),
        (format!("submission:{packet_id}"), &saved_submission),
        (format!("browser:{packet_id}"), &saved_analysis),
        (
            "agent_worker:primary".to_owned(),
            &json!({"heartbeat_at":timestamp}),
        ),
    ] {
        sqlx::query("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES ($1,$2,clock_timestamp(),clock_timestamp())")
            .bind(key).bind(value).execute(&mut database).await.unwrap();
    }
    sqlx::raw_sql(
        "UPDATE rust_agent_control SET heartbeat_at=clock_timestamp(),mode='STOPPED';
        INSERT INTO llm_monthly_usage(provider,month,requests,input_tokens,output_tokens)
        VALUES ('cohere',to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM'),4,300,20)",
    )
    .execute(&mut database)
    .await
    .unwrap();

    let (url, stop, service) = http_fixture().await;
    let http = client();
    let get = |path: &str| {
        http.get(format!("{url}/api/v1/{path}"))
            .bearer_auth(HOST_TOKEN)
    };
    let status: Value = get("agent/status")
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(status["native_worker_online"], true);
    assert_eq!(status["native_worker_mode"], "STOPPED");
    assert_eq!(status["worker_ready"], false);
    assert_eq!(status["worker_last_heartbeat"], timestamp);
    assert_eq!(status["local_requests_remaining"], 25);
    assert_eq!(status["provider_quota_remaining"], Value::Null);
    assert_eq!(status["email_sending_enabled"], false);
    let history: Value = get("agent/campaigns")
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(history[0]["id"], campaign_id.to_string());
    assert_eq!(history[0]["message"], saved_campaign["message"]);
    assert_eq!(
        get(&format!("agent/campaigns/{campaign_id}"))
            .send()
            .await
            .unwrap()
            .json::<Value>()
            .await
            .unwrap(),
        history[0]
    );
    assert_eq!(
        get(&format!("agent/campaigns/{}", Uuid::new_v4()))
            .send()
            .await
            .unwrap()
            .status(),
        404
    );
    let submission: Value = get("browser/submissions")
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(submission[0]["state"], "submission_uncertain");
    assert_eq!(submission[0]["application_id"], packet_id);
    let review: Value = get(&format!("browser-applications/{packet_id}"))
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(review["analysis"], saved_analysis);
    assert_eq!(review["packet"]["id"], packet_id);
    assert_eq!(review["connected"], false);
    assert_eq!(review["automated_submission_enabled"], false);
    let progress: Value = get(&format!("browser-applications/{packet_id}/operation"))
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(
        progress,
        json!({"packet_revision":1,"active_operation":null,"cancellation_pending":false})
    );
    assert_eq!(
        http.get(format!("{url}/api/v1/browser/submissions"))
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    assert_eq!(
        get("browser/submissions")
            .header("x-agent-client", "extension")
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    let method = http
        .post(format!("{url}/api/v1/browser/submissions"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(method.status(), 405);
    assert_eq!(method.headers()["allow"], "GET");
    assert_eq!(
        get(&format!(
            "browser-applications/{}/operation",
            Uuid::new_v4()
        ))
        .send()
        .await
        .unwrap()
        .status(),
        404
    );

    // Reads must never take the owner fence or change the uncertain outcome.
    assert_eq!(
        browser_pref(&mut database, &format!("campaign:{campaign_id}")).await,
        saved_campaign
    );
    assert_eq!(
        browser_pref(&mut database, &format!("submission:{packet_id}")).await,
        saved_submission
    );
    assert_eq!(
        browser_pref(&mut database, &format!("browser:{packet_id}")).await,
        saved_analysis
    );
    let receipts: i64 = sqlx::query_scalar("SELECT count(*) FROM application_submission_evidence")
        .fetch_one(&mut database)
        .await
        .unwrap();
    assert_eq!(receipts, 0);
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{id}',to_jsonb($2::text)) WHERE key=$1")
        .bind(format!("campaign:{campaign_id}")).bind(Uuid::new_v4().to_string()).execute(&mut database).await.unwrap();
    assert_eq!(get("agent/campaigns").send().await.unwrap().status(), 503);
    stop.cancel();
    service.await.unwrap();
}
