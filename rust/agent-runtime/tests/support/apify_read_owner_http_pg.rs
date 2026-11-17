// Deferred owner-authenticated acknowledged-read resource and local-only completion. Numeric loopback only.
async fn apify_read_owner_seed(
    c: &mut PgConnection,
    v: &BTreeMap<String, String>,
    f: &ApifyJobHttp,
    n: u128,
) {
    assert_eq!(
        apify_owner_acquire(c, v, n, false).await.unwrap_err(),
        Failure("apify_execution_response_limit")
    );
    let parent = Uuid::from_u128(n);
    apify_read_age_original(c, parent).await;
    let original = apify_intake_journal(c, parent).await;
    let at = chrono::DateTime::parse_from_rfc3339(original["started_at"].as_str().unwrap())
        .unwrap()
        .to_utc()
        + chrono::Duration::seconds(1);
    // Age the fictional parent consistently with its expired original child. No production history is rewritten.
    sqlx::query("UPDATE discovery_runs SET started_at=$2 WHERE id=$1")
        .bind(parent)
        .bind(at)
        .execute(&mut *c)
        .await
        .unwrap();
    let row: Value = sqlx::query_scalar("SELECT to_jsonb(r) FROM discovery_runs r WHERE id=$1")
        .bind(parent)
        .fetch_one(&mut *c)
        .await
        .unwrap();
    let key = format!("apify_owner:{}", parent.simple());
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{row}',$2) WHERE key=$1")
        .bind(key)
        .bind(row)
        .execute(c)
        .await
        .unwrap();
    f.recovering.store(true, Ordering::SeqCst);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_read_http_requires_explicit_put_saved_get_is_local_and_parent_completion_remains_separate()
 {
    let mut c = apify_owner_fixture().await;
    let (mut v, f, remote_stop, remote_task) = apify_job_http("read_ok").await;
    let parent = Uuid::from_u128(78001);
    let read = Uuid::from_u128(79001);
    apify_read_owner_seed(&mut c, &v, &f, 78001).await;
    v.extend(host_values());
    let (url, stop, task) = http_fixture_values(v).await;
    let http = client();
    let base = format!("{url}/api/v1/discovery/runs/{parent}");
    let path = format!("{base}/reads/{read}");
    let calls = f.calls.lock().await.len();
    assert_eq!(
        http.get(&path)
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        404
    );
    assert_eq!(f.calls.lock().await.len(), calls);
    assert_eq!(
        http.post(format!("{base}/complete"))
            .bearer_auth(HOST_TOKEN)
            .json(&json!({}))
            .send()
            .await
            .unwrap()
            .status(),
        409
    );
    assert_eq!(f.calls.lock().await.len(), calls);
    let response = http
        .put(&path)
        .bearer_auth(HOST_TOKEN)
        .json(&json!({}))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let result: Value = response.json().await.unwrap();
    assert_eq!(result["request_id"], json!(parent));
    assert_eq!(result["read_request_id"], json!(read));
    assert_eq!(result["finding_retained"], true);
    assert_eq!(result["http_attempts"], 3);
    let after = f.calls.lock().await.len();
    assert_eq!(after, calls + 3);
    for request in [
        http.get(&path),
        http.put(&path).json(&json!({})),
        http.post(format!("{path}/complete")).json(&json!({})),
    ] {
        let response = request.bearer_auth(HOST_TOKEN).send().await.unwrap();
        assert_eq!(response.status(), 200);
        assert_eq!(response.json::<Value>().await.unwrap(), result);
    }
    assert_eq!(f.calls.lock().await.len(), after);
    let saved: Value = http
        .get(&base)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(saved["usage"]["finding_retained"], true);
    assert_eq!(saved["local_intake_complete"], false);
    assert_eq!(saved["usage"]["last_read_request_id"], json!(read));
    assert_eq!(saved["usage"]["read_rounds_admitted"], 1);
    let completed: Value = http
        .post(format!("{base}/complete"))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({}))
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(completed["local_intake_complete"], true);
    assert_eq!(completed["rankings_complete"], true);
    assert_eq!(f.calls.lock().await.len(), after);
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
    remote_stop.cancel();
    remote_task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_read_http_auth_methods_queries_and_arbitrary_provider_fields_cannot_admit_or_dispatch()
 {
    let mut c = apify_owner_fixture().await;
    let (mut v, f, remote_stop, remote_task) = apify_job_http("read_ok").await;
    let parent = Uuid::from_u128(78002);
    let read = Uuid::from_u128(79002);
    apify_read_owner_seed(&mut c, &v, &f, 78002).await;
    v.extend(host_values());
    let (url, stop, task) = http_fixture_values(v).await;
    let http = client();
    let path = format!("{url}/api/v1/discovery/runs/{parent}/reads/{read}");
    let before = apify_owner_snapshot(&mut c).await;
    let calls = f.calls.lock().await.len();
    assert_eq!(
        http.put(&path)
            .json(&json!({}))
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    assert_eq!(
        http.post(&path)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({}))
            .send()
            .await
            .unwrap()
            .status(),
        405
    );
    assert_eq!(
        http.put(format!("{path}?run_id=foreignRun"))
            .bearer_auth(HOST_TOKEN)
            .json(&json!({}))
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    for body in [
        json!({"run_id":"foreignRun"}),
        json!({"dataset_id":"foreignDataset"}),
        json!({"allow_paid":true}),
        json!({"restart":true}),
    ] {
        assert_eq!(
            http.put(&path)
                .bearer_auth(HOST_TOKEN)
                .json(&body)
                .send()
                .await
                .unwrap()
                .status(),
            422
        );
        assert_eq!(
            http.post(format!("{path}/complete"))
                .bearer_auth(HOST_TOKEN)
                .json(&body)
                .send()
                .await
                .unwrap()
                .status(),
            422
        );
    }
    assert_eq!(f.calls.lock().await.len(), calls);
    assert_eq!(apify_owner_snapshot(&mut c).await, before);
    stop.cancel();
    task.await.unwrap();
    remote_stop.cancel();
    remote_task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_read_http_legacy_and_public_parents_cannot_gain_paid_recovery_scope() {
    let mut c = public_intake_fixture().await;
    let legacy = Uuid::from_u128(78003);
    let public = Uuid::from_u128(78004);
    sqlx::query("INSERT INTO discovery_runs(id,source,request_hash,status) VALUES($1,'naukri','legacy','running')").bind(legacy).execute(&mut c).await.unwrap();
    public_owner_runs::admit(
        &mut c,
        &public_job_settings(),
        public_intake_input(),
        public,
        90.0,
    )
    .await
    .unwrap();
    let (url, stop, task) = http_fixture_values(host_values()).await;
    let http = client();
    let before = public_intake_snapshot(&mut c).await;
    for parent in [legacy, public] {
        let path = format!(
            "{url}/api/v1/discovery/runs/{parent}/reads/{}",
            Uuid::from_u128(79003)
        );
        for request in [
            http.get(&path),
            http.put(&path).json(&json!({})),
            http.post(format!("{path}/complete")).json(&json!({})),
        ] {
            assert_eq!(
                request
                    .bearer_auth(HOST_TOKEN)
                    .send()
                    .await
                    .unwrap()
                    .status(),
                409
            );
        }
    }
    assert_eq!(public_intake_snapshot(&mut c).await, before);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_read_http_recovers_complete_pages_locally_after_failed_finding_commit_without_new_gets()
 {
    let mut c = apify_owner_fixture().await;
    let (mut v, f, remote_stop, remote_task) = apify_job_http("read_ok").await;
    let parent = Uuid::from_u128(78005);
    let read = Uuid::from_u128(79005);
    apify_read_owner_seed(&mut c, &v, &f, 78005).await;
    apify_read_hold_final(&mut c).await;
    v.extend(host_values());
    let (url, stop, task) = http_fixture_values(v).await;
    let http = client();
    let path = format!("{url}/api/v1/discovery/runs/{parent}/reads/{read}");
    assert_eq!(
        http.put(&path)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({}))
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
    assert_eq!(saved["local_merge_available"], true);
    let calls = f.calls.lock().await.len();
    apify_read_release_final(&mut c).await;
    let response = http
        .post(format!("{path}/complete"))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({}))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    assert_eq!(
        response.json::<Value>().await.unwrap()["finding_retained"],
        true
    );
    assert_eq!(f.calls.lock().await.len(), calls);
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
    remote_stop.cancel();
    remote_task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_read_http_unknown_paid_start_is_refused_with_held_cap_without_any_new_get_or_post() {
    let mut c = apify_owner_fixture().await;
    let (mut v, f, remote_stop, remote_task) = apify_job_http("lost_start").await;
    let parent = Uuid::from_u128(78006);
    let read = Uuid::from_u128(79006);
    assert!(apify_owner_acquire(&mut c, &v, 78006, false).await.is_err());
    v.extend(host_values());
    let (url, stop, task) = http_fixture_values(v).await;
    let http = client();
    let path = format!("{url}/api/v1/discovery/runs/{parent}/reads/{read}");
    let calls = f.calls.lock().await.len();
    let before = apify_owner_snapshot(&mut c).await;
    assert_eq!(
        http.put(&path)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({}))
            .send()
            .await
            .unwrap()
            .status(),
        409
    );
    assert_eq!(f.calls.lock().await.len(), calls);
    assert_eq!(apify_owner_snapshot(&mut c).await, before);
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
    remote_stop.cancel();
    remote_task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_read_http_uses_existing_transient_slot_while_metadata_remains_local_and_readable() {
    let mut c = apify_owner_fixture().await;
    let (mut v, f, remote_stop, remote_task) = apify_job_http("read_hold").await;
    let parent = Uuid::from_u128(78007);
    let read = Uuid::from_u128(79007);
    apify_read_owner_seed(&mut c, &v, &f, 78007).await;
    v.extend(host_values());
    let (url, stop, task) = http_fixture_values(v).await;
    let http = client();
    let path = format!("{url}/api/v1/discovery/runs/{parent}/reads/{read}");
    let pending = http.put(&path).bearer_auth(HOST_TOKEN).json(&json!({}));
    let work = tokio::spawn(async move { pending.send().await });
    tokio::time::timeout(Duration::from_secs(3), f.entered.notified())
        .await
        .unwrap();
    assert_eq!(
        http.get(&path)
            .bearer_auth(HOST_TOKEN)
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
    f.release.notify_one();
    assert_eq!(work.await.unwrap().unwrap().status(), 200);
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
    remote_stop.cancel();
    remote_task.await.unwrap();
}
