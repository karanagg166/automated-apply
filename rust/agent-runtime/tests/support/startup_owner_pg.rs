//! Deferred owner startup boundary fixtures. Disposable PostgreSQL and loopback HTTP only.
use automated_apply_agents::startup_catalog::owner as startup_owner;
fn startup_sources_settings() -> automated_apply_agents::source_registry::Settings {
    automated_apply_agents::source_registry::Settings::from_values(&BTreeMap::new()).unwrap()
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_owner_http_reuses_the_transient_permit_while_source_metadata_remains_readable() {
    let mut c = startup_run_fixture().await;
    let (url, stop, task) = http_fixture_values(host_values()).await;
    let mut holder = connection().await;
    let mut lock = holder.begin().await.unwrap();
    sqlx::query(
        "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
    )
    .fetch_one(&mut *lock)
    .await
    .unwrap();
    let request_url = format!("{url}/api/v1/startups/discovery/runs");
    let pending = tokio::spawn(async move {
        client()
            .post(request_url)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"idempotency_key":"fictional_shared_startup_permit"}))
            .send()
            .await
            .unwrap()
    });
    let mut waiting = false;
    for _ in 0..50 {
        waiting=sqlx::query_scalar::<_,bool>("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE application_name='automated-apply:api' AND wait_event_type='Lock' AND query LIKE '%agent_conversation:primary%')").fetch_one(&mut c).await.unwrap();
        if waiting {
            break;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    assert!(
        waiting,
        "original request must have acquired the shared transient permit before the contention assertion"
    );
    let http = client();
    let response = http
        .post(format!("{url}/api/v1/startups/discovery/preview"))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({}))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 429);
    let value: Value = response.json().await.unwrap();
    assert_eq!(value["detail"], "bounded_background_request_running");
    assert_eq!(
        http.get(format!("{url}/api/v1/startups/sources"))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    lock.rollback().await.unwrap();
    let response = pending.await.unwrap();
    assert_eq!(response.status(), 200);
    let result: Value = response.json().await.unwrap();
    assert_eq!(result["status"], "manual_input_required");
    stop.cancel();
    task.await.unwrap();
}
async fn startup_owner_preview(c: &mut PgConnection, input: Value) -> Result<Value> {
    startup_owner::preview(c, input, &startup_sources_settings()).await
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_owner_preview_uses_one_saved_profile_without_writes_or_execution_authority() {
    let mut c = startup_run_fixture().await;
    let before = browser_snapshot(&mut c).await;
    let runs_before = startup_run_snapshot(&mut c).await;
    let profile = automated_apply_agents::profile_store::get(&mut c)
        .await
        .unwrap()
        .value;
    let p = startup_owner_preview(&mut c, json!({})).await.unwrap();
    assert_eq!(p["profile_version"], profile["version"]);
    assert_eq!(
        p["effective_roles"],
        profile["preferences"]["target_titles"]
    );
    assert_eq!(
        p["effective_locations"],
        profile["preferences"]["preferred_locations"]
    );
    assert_eq!(p["mode"], "company_first");
    assert_eq!(p["company_first_available"], true);
    assert_eq!(p["provider_calls"], 0);
    assert_eq!(p["writes"], 0);
    assert_eq!(p["dispatch_authorized"], false);
    assert_eq!(p["live_verified"], false);
    for private in ["full_name", "verified_skills", "email", "projects", "phone"] {
        assert!(p.get(private).is_none());
    }
    assert_eq!(browser_snapshot(&mut c).await, before);
    assert_eq!(startup_run_snapshot(&mut c).await, runs_before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_owner_preview_explicit_preferences_and_no_profile_are_distinct_from_saved_facts() {
    let mut c = startup_run_fixture().await;
    let p=startup_owner_preview(&mut c,json!({"source":"greenhouse","mode":"job_led","filters":{"roles":["CTO"],"locations":["India"]}})).await.unwrap();
    assert_eq!(p["effective_roles"], json!(["CTO"]));
    assert_eq!(p["effective_locations"], json!(["India"]));
    assert_eq!(p["source"]["availability"], "configuration_required");
    let p = startup_owner_preview(&mut c, json!({"filters":{"use_profile":false}}))
        .await
        .unwrap();
    assert_eq!(p["profile_version"], Value::Null);
    assert_eq!(p["effective_roles"], json!([]));
    sqlx::query("DELETE FROM candidate_profiles")
        .execute(&mut c)
        .await
        .unwrap();
    let p = startup_owner_preview(&mut c, json!({})).await.unwrap();
    assert_eq!(p["profile_version"], Value::Null);
    assert_eq!(p["effective_roles"], json!([]));
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_owner_preview_does_not_take_the_owner_fence_and_cannot_modify_invalid_requests() {
    let mut c = startup_run_fixture().await;
    let before = browser_snapshot(&mut c).await;
    let mut holder = connection().await;
    let mut tx = holder.begin().await.unwrap();
    sqlx::query(
        "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
    )
    .fetch_one(&mut *tx)
    .await
    .unwrap();
    let p = tokio::time::timeout(
        Duration::from_secs(1),
        startup_owner_preview(&mut c, json!({"filters":{"use_profile":false}})),
    )
    .await
    .unwrap()
    .unwrap();
    assert_eq!(p["writes"], 0);
    tx.rollback().await.unwrap();
    for bad in [
        json!({"source":"unknown"}),
        json!({"filters":{"min_employees":100,"max_employees":10}}),
        json!({"extra":true}),
    ] {
        assert!(startup_owner_preview(&mut c, bad).await.is_err());
    }
    assert_eq!(browser_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_owner_source_http_requires_owner_auth_and_excludes_private_configuration() {
    let mut c = startup_run_fixture().await;
    let mut values = host_values();
    values.insert(
        "APIFY_API_TOKEN".into(),
        "PRIVATE_STARTUP_CONFIG_CANARY".into(),
    );
    values.insert(
        "GREENHOUSE_BOARDS".into(),
        "{\"fictional\":\"PRIVATE_STARTUP_EMPLOYER_CANARY\"}".into(),
    );
    let before = browser_snapshot(&mut c).await;
    let (url, stop, task) = http_fixture_values(values).await;
    let http = client();
    for path in ["/api/v1/startups/sources", "/api/v1/discovery/sources"] {
        let path = format!("{url}{path}");
        assert_eq!(http.get(&path).send().await.unwrap().status(), 401);
        assert_eq!(
            http.get(&path)
                .bearer_auth(HOST_TOKEN)
                .header("x-agent-client", "extension")
                .send()
                .await
                .unwrap()
                .status(),
            403
        );
        assert_eq!(
            http.get(&path)
                .bearer_auth(HOST_TOKEN)
                .header("origin", "https://untrusted-fixture.example")
                .send()
                .await
                .unwrap()
                .status(),
            403
        );
        let response = http
            .get(&path)
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap();
        assert_eq!(response.status(), 200);
        assert_eq!(response.headers()["cache-control"], "private, no-store");
        let v: Value = response.json().await.unwrap();
        assert_eq!(v["provider_calls"], 0);
        assert_eq!(v["writes"], 0);
        assert!(!v.to_string().contains("PRIVATE_STARTUP_CONFIG_CANARY"));
        assert!(!v.to_string().contains("PRIVATE_STARTUP_EMPLOYER_CANARY"));
        let response = http
            .post(&path)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({}))
            .send()
            .await
            .unwrap();
        assert_eq!(response.status(), 405);
        assert_eq!(response.headers()["allow"], "GET");
        assert_eq!(
            http.get(format!("{path}?probe=true"))
                .bearer_auth(HOST_TOKEN)
                .send()
                .await
                .unwrap()
                .status(),
            422
        );
    }
    assert_eq!(browser_snapshot(&mut c).await, before);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_owner_http_manual_import_and_get_retain_the_original_request_hash_and_immutable_replay()
 {
    let mut c = startup_run_fixture().await;
    let (url, stop, task) = http_fixture_values(host_values()).await;
    let http = client();
    let root = format!("{url}/api/v1/startups/discovery/runs");
    let input = startup_run_input("fictional_owner_manual_request");
    let response = http
        .post(&root)
        .bearer_auth(HOST_TOKEN)
        .json(&input)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let first: Value = response.json().await.unwrap();
    assert_eq!(first["status"], "success");
    let id: Uuid = first["id"].as_str().unwrap().parse().unwrap();
    let hash: String = sqlx::query_scalar("SELECT request_hash FROM discovery_runs WHERE id=$1")
        .bind(id)
        .fetch_one(&mut c)
        .await
        .unwrap();
    let now = chrono::Utc::now();
    let expected = automated_apply_agents::research_contract::normalize(
        automated_apply_agents::research_contract::Kind::StartupRun,
        input.clone(),
        now,
    )
    .unwrap();
    assert_eq!(
        hash,
        startup_runs::request_hash(&expected).unwrap(),
        "host cannot normalize defaults twice before claiming"
    );
    let before = startup_run_snapshot(&mut c).await;
    let repeat: Value = http
        .post(&root)
        .bearer_auth(HOST_TOKEN)
        .json(&input)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(repeat, first);
    let saved: Value = http
        .get(format!("{root}/{id}"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(saved, first);
    assert_eq!(startup_run_snapshot(&mut c).await, before);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_owner_http_contract_conflicts_and_unported_provider_runs_do_not_admit_new_work() {
    let mut c = startup_run_fixture().await;
    let (url, stop, task) = http_fixture_values(host_values()).await;
    let http = client();
    let root = format!("{url}/api/v1/startups/discovery/runs");
    let input = startup_run_input("fictional_owner_conflict");
    assert_eq!(
        http.post(&root).json(&input).send().await.unwrap().status(),
        401
    );
    assert_eq!(
        http.post(&root)
            .bearer_auth(HOST_TOKEN)
            .json(&input)
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    let before = startup_run_snapshot(&mut c).await;
    let mut changed = input;
    changed["filters"]["early_stage"] = json!(true);
    assert_eq!(
        http.post(&root)
            .bearer_auth(HOST_TOKEN)
            .json(&changed)
            .send()
            .await
            .unwrap()
            .status(),
        409
    );
    assert_eq!(
        http.post(&root)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({}))
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    assert_eq!(http.post(&root).bearer_auth(HOST_TOKEN).json(&json!({"idempotency_key":"fictional_unported","source":"himalayas","mode":"job_led"})).send().await.unwrap().status(),501);
    assert_eq!(
        http.post(&root)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"idempotency_key":"fictional_unknown","source":"unknown"}))
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    assert_eq!(
        http.post(&root)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"extra":true}))
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    assert_eq!(
        http.get(format!("{root}/{}", Uuid::nil()))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        404
    );
    assert_eq!(
        http.post(format!("{root}/{}", Uuid::nil()))
            .bearer_auth(HOST_TOKEN)
            .json(&json!({}))
            .send()
            .await
            .unwrap()
            .status(),
        405
    );
    assert_eq!(startup_run_snapshot(&mut c).await, before);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_owner_preview_http_rejects_queries_methods_and_oversized_input_without_writes() {
    let mut c = startup_run_fixture().await;
    let before = browser_snapshot(&mut c).await;
    let run_before = startup_run_snapshot(&mut c).await;
    let (url, stop, task) = http_fixture_values(host_values()).await;
    let http = client();
    let path = format!("{url}/api/v1/startups/discovery/preview");
    assert_eq!(
        http.post(&path)
            .json(&json!({}))
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    let response = http
        .post(&path)
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"source":"manual","filters":{"use_profile":false}}))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let p: Value = response.json().await.unwrap();
    assert_eq!(p["provider_calls"], 0);
    assert_eq!(p["writes"], 0);
    let response = http
        .get(&path)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 405);
    assert_eq!(response.headers()["allow"], "POST");
    assert_eq!(
        http.post(format!("{path}?probe=true"))
            .bearer_auth(HOST_TOKEN)
            .json(&json!({}))
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    assert_eq!(
        http.post(&path)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"private":"x".repeat(65536)}))
            .send()
            .await
            .unwrap()
            .status(),
        413
    );
    assert_eq!(browser_snapshot(&mut c).await, before);
    assert_eq!(startup_run_snapshot(&mut c).await, run_before);
    stop.cancel();
    task.await.unwrap();
}
