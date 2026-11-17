// Deferred owner-authenticated loopback API and local saved discovery evidence only.
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_owner_preview_is_read_only_and_does_not_take_a_blocked_owner_fence() {
    let mut c = public_intake_fixture().await;
    let before = public_intake_snapshot(&mut c).await;
    let mut holder = connection().await;
    let mut lock = holder.begin().await.unwrap();
    sqlx::query(
        "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
    )
    .fetch_one(&mut *lock)
    .await
    .unwrap();
    let value = tokio::time::timeout(
        Duration::from_secs(1),
        automated_apply_agents::job_sources::owner::preview(
            &mut c,
            &public_job_settings(),
            public_result_input(),
        ),
    )
    .await
    .unwrap()
    .unwrap();
    assert_eq!(value["writes"], 0);
    assert_eq!(value["provider_calls"], 0);
    assert_eq!(value["dispatch_authorized"], false);
    assert!(value.get("profile_pin").is_none());
    assert!(value.get("email").is_none());
    lock.rollback().await.unwrap();
    assert_eq!(public_intake_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_owner_uuid_http_put_and_get_return_one_original_loopback_result_without_more_dispatch()
 {
    let mut c = public_intake_fixture().await;
    let (mut v, remote, remote_stop, remote_task) =
        public_job_http(PublicJobSource::Greenhouse, "ok").await;
    v.extend(host_values());
    let (url, stop, task) = http_fixture_values(v).await;
    let id = Uuid::from_u128(67001);
    let path = format!("{url}/api/v1/discovery/runs/{id}");
    let http = client();
    let reply = http
        .put(&path)
        .bearer_auth(HOST_TOKEN)
        .json(&public_intake_input())
        .send()
        .await
        .unwrap();
    assert_eq!(reply.status(), 200);
    let first: Value = reply.json().await.unwrap();
    assert_eq!(first["id"], json!(id));
    assert_eq!(first["local_intake_complete"], true);
    assert_eq!(first["rankings_complete"], true);
    assert_eq!(remote.calls.load(Ordering::SeqCst), 1);
    assert!(!first.to_string().contains("CANARY"));
    let before = public_intake_snapshot(&mut c).await;
    for method in ["GET", "PUT"] {
        let request = if method == "GET" {
            http.get(&path)
        } else {
            http.put(&path).json(&public_intake_input())
        };
        let response = request.bearer_auth(HOST_TOKEN).send().await.unwrap();
        assert_eq!(response.status(), 200);
        assert_eq!(response.json::<Value>().await.unwrap(), first);
    }
    assert_eq!(remote.calls.load(Ordering::SeqCst), 1);
    assert_eq!(public_intake_snapshot(&mut c).await, before);
    stop.cancel();
    task.await.unwrap();
    remote_stop.cancel();
    remote_task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_owner_original_post_maps_compatibility_key_and_rejects_changed_request_without_another_get()
 {
    let mut c = public_intake_fixture().await;
    let (mut v, remote, remote_stop, remote_task) =
        public_job_http(PublicJobSource::Greenhouse, "ok").await;
    v.extend(host_values());
    let (url, stop, task) = http_fixture_values(v).await;
    let path = format!("{url}/api/v1/discovery/runs");
    let mut input = public_intake_input();
    input["idempotency_key"] = json!("fictional_http_compatibility_key");
    let http = client();
    let reply = http
        .post(&path)
        .bearer_auth(HOST_TOKEN)
        .json(&input)
        .send()
        .await
        .unwrap();
    assert_eq!(reply.status(), 200);
    let first: Value = reply.json().await.unwrap();
    let replay = http
        .post(&path)
        .bearer_auth(HOST_TOKEN)
        .json(&input)
        .send()
        .await
        .unwrap();
    assert_eq!(replay.status(), 200);
    assert_eq!(replay.json::<Value>().await.unwrap(), first);
    let before = public_intake_snapshot(&mut c).await;
    input["query"]["keywords"] = json!(["Changed query"]);
    let changed = http
        .post(&path)
        .bearer_auth(HOST_TOKEN)
        .json(&input)
        .send()
        .await
        .unwrap();
    assert_eq!(changed.status(), 409);
    assert_eq!(remote.calls.load(Ordering::SeqCst), 1);
    assert_eq!(public_intake_snapshot(&mut c).await, before);
    stop.cancel();
    task.await.unwrap();
    remote_stop.cancel();
    remote_task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_owner_legacy_get_is_sanitized_saved_history_without_native_adoption_or_remote_authority()
 {
    let mut c = public_intake_fixture().await;
    let id = Uuid::from_u128(67002);
    sqlx::query("INSERT INTO discovery_runs(id,source,request_hash,status,counts,errors,usage,query_summary) VALUES($1,'manual','legacy','running','{\"inserted\":2}','[\"PRIVATE_LEGACY_ERROR_CANARY\"]','{\"private\":\"PRIVATE_LEGACY_USAGE_CANARY\"}','{\"job_ids\":[]}')").bind(id).execute(&mut c).await.unwrap();
    let before = public_intake_snapshot(&mut c).await;
    let value = automated_apply_agents::job_sources::owner::read(&mut c, id)
        .await
        .unwrap();
    assert_eq!(value["status"], "recovery_required");
    assert_eq!(value["counts"]["inserted"], 2);
    assert_eq!(value["original_scope_available"], false);
    assert!(value["local_intake_complete"].is_null());
    assert!(!value.to_string().contains("CANARY"));
    assert_eq!(public_intake_snapshot(&mut c).await, before);
    assert_eq!(
        public_owner_runs::finish(&mut c, &public_job_settings(), id)
            .await
            .unwrap_err(),
        Failure("discovery_run_original_scope_missing")
    );
    assert_eq!(public_intake_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_owner_local_completion_endpoint_cannot_admit_or_dispatch_and_get_cannot_complete_retained_findings()
 {
    let mut c = public_intake_fixture().await;
    let at = public_intake_time(&mut c).await;
    public_intake_observation(
        &mut c,
        67003,
        public_intake_input(),
        vec![public_intake_job(at)],
        at,
    )
    .await;
    let mut v = host_values();
    v.insert(
        "GREENHOUSE_BOARDS".into(),
        json!({"fictional":"Fictional Public Employer"}).to_string(),
    );
    let (url, stop, task) = http_fixture_values(v).await;
    let path = format!("{url}/api/v1/discovery/runs/{}", Uuid::from_u128(67003));
    let http = client();
    let before = public_intake_snapshot(&mut c).await;
    let saved = http
        .get(&path)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(saved.status(), 200);
    assert_eq!(
        saved.json::<Value>().await.unwrap()["local_intake_complete"],
        false
    );
    assert_eq!(public_intake_snapshot(&mut c).await, before);
    let result = http
        .post(format!("{path}/complete"))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({}))
        .send()
        .await
        .unwrap();
    assert_eq!(result.status(), 200);
    assert_eq!(
        result.json::<Value>().await.unwrap()["counts"]["inserted"],
        1
    );
    let unknown = http
        .post(format!(
            "{url}/api/v1/discovery/runs/{}/complete",
            Uuid::from_u128(67999)
        ))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({}))
        .send()
        .await
        .unwrap();
    assert_eq!(unknown.status(), 404);
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM owner_preferences WHERE starts_with(key,'public_jobs:')"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        1
    );
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_owner_auth_methods_queries_unsupported_sources_and_missing_keys_fail_without_admission()
 {
    let mut c = public_intake_fixture().await;
    let (url, stop, task) = http_fixture_values(host_values()).await;
    let http = client();
    let root = format!("{url}/api/v1/discovery");
    let path = format!("{root}/runs/{}", Uuid::from_u128(67004));
    let before = public_intake_snapshot(&mut c).await;
    assert_eq!(
        http.put(&path)
            .json(&public_intake_input())
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    assert_eq!(
        http.post(format!("{root}/runs"))
            .bearer_auth(HOST_TOKEN)
            .json(&public_intake_input())
            .send()
            .await
            .unwrap()
            .status(),
        428
    );
    assert_eq!(
        http.put(format!("{path}?replay=true"))
            .bearer_auth(HOST_TOKEN)
            .json(&public_intake_input())
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    assert_eq!(
        http.delete(&path)
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        405
    );
    for (source, status) in [("manual", 501), ("naukri", 422)] {
        assert_eq!(
            http.put(&path)
                .bearer_auth(HOST_TOKEN)
                .json(&json!({"source":source}))
                .send()
                .await
                .unwrap()
                .status(),
            status
        );
    }
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
    assert_eq!(public_intake_snapshot(&mut c).await, before);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_owner_discovery_shares_existing_transient_permit_while_source_metadata_stays_readable()
 {
    let mut c = public_intake_fixture().await;
    let (mut v, remote, remote_stop, remote_task) =
        public_job_http(PublicJobSource::Greenhouse, "ok").await;
    v.extend(host_values());
    let (url, stop, task) = http_fixture_values(v).await;
    let mut holder = connection().await;
    let mut lock = holder.begin().await.unwrap();
    sqlx::query(
        "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
    )
    .fetch_one(&mut *lock)
    .await
    .unwrap();
    let path = format!("{url}/api/v1/discovery/runs/{}", Uuid::from_u128(67005));
    let pending = tokio::spawn(async move {
        client()
            .put(path)
            .bearer_auth(HOST_TOKEN)
            .json(&public_intake_input())
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
    assert!(waiting);
    let http = client();
    assert_eq!(
        http.post(format!("{url}/api/v1/startups/discovery/preview"))
            .bearer_auth(HOST_TOKEN)
            .json(&json!({}))
            .send()
            .await
            .unwrap()
            .status(),
        429
    );
    assert_eq!(
        http.get(format!("{url}/api/v1/discovery/sources"))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    lock.rollback().await.unwrap();
    assert_eq!(pending.await.unwrap().status(), 200);
    assert_eq!(remote.calls.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
    remote_stop.cancel();
    remote_task.await.unwrap();
}
