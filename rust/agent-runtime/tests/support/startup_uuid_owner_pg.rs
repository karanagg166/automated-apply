//! Deferred UUID startup admission/local completion HTTP. Numeric-loopback providers only.
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_uuid_owner_public_put_get_and_empty_complete_use_original_child_only() {
    let mut c = startup_job_fixture().await;
    let (mut v, f, remote_stop, remote_task) =
        public_job_http(PublicJobSource::Greenhouse, "ok").await;
    v.extend(host_values());
    let (url, stop, task) = http_fixture_values(v).await;
    let http = client();
    let id = Uuid::from_u128(81001);
    let path = format!("{url}/api/v1/startups/discovery/runs/{id}");
    let response = http
        .put(&path)
        .bearer_auth(HOST_TOKEN)
        .json(&startup_job_input())
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let first: Value = response.json().await.unwrap();
    assert_eq!(first["id"], json!(id));
    assert_eq!(first["local_intake_complete"], true);
    let before = startup_job_snapshot(&mut c).await;
    for request in [
        http.get(&path),
        http.put(&path).json(&startup_job_input()),
        http.post(format!("{path}/complete")).json(&json!({})),
    ] {
        let response = request.bearer_auth(HOST_TOKEN).send().await.unwrap();
        assert_eq!(response.status(), 200);
        assert_eq!(response.json::<Value>().await.unwrap(), first);
    }
    assert_eq!(startup_job_snapshot(&mut c).await, before);
    assert_eq!(f.calls.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
    remote_stop.cancel();
    remote_task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_uuid_owner_local_complete_recovers_failed_parent_after_retained_child_without_http()
 {
    let mut c = startup_job_fixture().await;
    let (mut v, f, remote_stop, remote_task) =
        public_job_http(PublicJobSource::Greenhouse, "ok").await;
    v.extend(host_values());
    sqlx::raw_sql("CREATE FUNCTION fixture_startup_uuid_parent() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.source,'startup_') THEN RETURN NULL;END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_startup_uuid_parent BEFORE UPDATE ON discovery_runs FOR EACH ROW EXECUTE FUNCTION fixture_startup_uuid_parent()").execute(&mut c).await.unwrap();
    let (url, stop, task) = http_fixture_values(v).await;
    let http = client();
    let path = format!(
        "{url}/api/v1/startups/discovery/runs/{}",
        Uuid::from_u128(81002)
    );
    assert_eq!(
        http.put(&path)
            .bearer_auth(HOST_TOKEN)
            .json(&startup_job_input())
            .send()
            .await
            .unwrap()
            .status(),
        503
    );
    let saved: Value = http
        .get(&path)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(saved["child_run"]["local_intake_complete"], true);
    assert_eq!(saved["local_intake_complete"], false);
    sqlx::raw_sql("DROP TRIGGER fixture_startup_uuid_parent ON discovery_runs;DROP FUNCTION fixture_startup_uuid_parent()").execute(&mut c).await.unwrap();
    let result: Value = http
        .post(format!("{path}/complete"))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({}))
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(result["local_intake_complete"], true);
    assert_eq!(f.calls.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
    remote_stop.cancel();
    remote_task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_uuid_owner_changed_input_and_manual_put_arbitrary_complete_or_unauthenticated_mutations_are_refused()
 {
    let mut c = startup_job_fixture().await;
    let (mut v, f, remote_stop, remote_task) =
        public_job_http(PublicJobSource::Greenhouse, "ok").await;
    v.extend(host_values());
    let (url, stop, task) = http_fixture_values(v).await;
    let http = client();
    let path = format!(
        "{url}/api/v1/startups/discovery/runs/{}",
        Uuid::from_u128(81003)
    );
    assert_eq!(
        http.put(&path)
            .json(&startup_job_input())
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    assert_eq!(
        http.put(&path)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"source":"manual","mode":"company_first","permission_confirmed":true}))
            .send()
            .await
            .unwrap()
            .status(),
        501
    );
    assert_eq!(
        http.post(format!("{path}/complete"))
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"dispatch":true}))
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    assert_eq!(
        http.put(&path)
            .bearer_auth(HOST_TOKEN)
            .json(&startup_job_input())
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    let before = startup_job_snapshot(&mut c).await;
    let mut changed = startup_job_input();
    changed["query"]["limit"] = json!(21);
    assert_eq!(
        http.put(&path)
            .bearer_auth(HOST_TOKEN)
            .json(&changed)
            .send()
            .await
            .unwrap()
            .status(),
        409
    );
    assert_eq!(startup_job_snapshot(&mut c).await, before);
    assert_eq!(f.calls.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
    remote_stop.cancel();
    remote_task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_uuid_owner_unknown_paid_child_complete_is_a_saved_read_without_start_or_recovery_get()
 {
    let mut c = startup_paid_fixture().await;
    let (v, f, remote_stop, remote_task) = apify_job_http("lost_start").await;
    let mut v = startup_paid_values(v);
    v.extend(host_values());
    let (url, stop, task) = http_fixture_values(v).await;
    let http = client();
    let id = Uuid::from_u128(81004);
    let path = format!("{url}/api/v1/startups/discovery/runs/{id}");
    assert_eq!(
        http.put(&path)
            .bearer_auth(HOST_TOKEN)
            .json(&startup_paid_input())
            .send()
            .await
            .unwrap()
            .status(),
        503
    );
    let before = startup_paid_snapshot(&mut c).await;
    let calls = f.calls.lock().await.len();
    let result: Value = http
        .post(format!("{path}/complete"))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({}))
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(result["local_intake_complete"], false);
    assert_eq!(result["child_run"]["status"], "recovery_required");
    assert_eq!(f.calls.lock().await.len(), calls);
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    assert_eq!(startup_paid_snapshot(&mut c).await, before);
    stop.cancel();
    task.await.unwrap();
    remote_stop.cancel();
    remote_task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_uuid_preview_reports_actual_paid_query_estimate_and_pinned_provider_preferences_without_writes()
 {
    let mut c = startup_paid_fixture().await;
    let (v, f, remote_stop, remote_task) = apify_job_http("ok").await;
    let mut v = startup_paid_values(v);
    v.extend(host_values());
    let (url, stop, task) = http_fixture_values(v).await;
    let http = client();
    let before = startup_paid_snapshot(&mut c).await;
    let mut input = startup_paid_input();
    input["query"]["limit"] = json!(50);
    let result: Value = http
        .post(format!("{url}/api/v1/startups/discovery/preview"))
        .bearer_auth(HOST_TOKEN)
        .json(&input)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(result["query"]["limit"], 50);
    assert_eq!(result["paid_execution"]["estimated_usd"], "0.050000");
    assert_eq!(result["paid_execution"]["run_cap_usd"], "0.100001");
    assert_eq!(result["provider_calls"], 0);
    assert_eq!(result["writes"], 0);
    assert_eq!(result["job_led_available"], true);
    assert_eq!(startup_paid_snapshot(&mut c).await, before);
    assert_eq!(f.calls.lock().await.len(), 0);
    stop.cancel();
    task.await.unwrap();
    remote_stop.cancel();
    remote_task.await.unwrap();
}
