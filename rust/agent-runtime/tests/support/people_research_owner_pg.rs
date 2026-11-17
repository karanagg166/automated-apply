// Deferred actual owner HTTP over disposable PostgreSQL and a loopback-only search provider.
async fn people_research_http(
    mode: &'static str,
) -> (
    String,
    Arc<PeopleSearchHttpFixture>,
    CancellationToken,
    tokio::task::JoinHandle<()>,
    CancellationToken,
    tokio::task::JoinHandle<()>,
) {
    let (search, state, provider_stop, provider_task) = people_search_http(mode).await;
    let mut values = host_values();
    values.extend(search);
    let (url, stop, task) = http_fixture_values(values).await;
    (url, state, stop, task, provider_stop, provider_task)
}
fn research_request_url(root: &str, n: u128) -> String {
    format!(
        "{root}/api/v1/rust-agent/research/people/requests/{}",
        Uuid::from_u128(n)
    )
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_research_owner_status_and_unkeyed_legacy_refusal_do_no_database_or_provider_work() {
    let mut c = people_search_fixture().await;
    let (url, state, stop, task, pstop, ptask) = people_research_http("official").await;
    let before = people_search_snapshot(&mut c).await;
    let data = people_ingest_snapshot(&mut c).await;
    let http = client();
    let response = http
        .get(format!("{url}/api/v1/rust-agent/research/people/status"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let status: Value = response.json().await.unwrap();
    assert_eq!(status["credentials_configured"], true);
    assert_eq!(status["live_verified"], false);
    assert_eq!(status["dispatch_authorized"], false);
    assert!(
        !status
            .to_string()
            .contains("PRIVATE_FICTIONAL_SEARCH_KEY_CANARY")
    );
    let response = http
        .post(format!("{url}/api/v1/discovery/people/search"))
        .bearer_auth(HOST_TOKEN)
        .json(&people_search_input())
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 428);
    let error: Value = response.json().await.unwrap();
    assert_eq!(error["detail"], "public_research_request_id_required");
    assert_eq!(state.calls.load(Ordering::SeqCst), 0);
    assert_eq!(people_search_snapshot(&mut c).await, before);
    assert_eq!(people_ingest_snapshot(&mut c).await, data);
    stop.cancel();
    task.await.unwrap();
    pstop.cancel();
    ptask.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_research_owner_put_get_and_same_uuid_recovery_bind_company_and_one_original_search()
{
    let mut c = people_search_fixture().await;
    let company: Uuid =
        sqlx::query_scalar("SELECT id FROM companies WHERE domain='contact-fixture.example'")
            .fetch_one(&mut c)
            .await
            .unwrap();
    let (url, state, stop, task, pstop, ptask) = people_research_http("official").await;
    let path = research_request_url(&url, 50001);
    let http = client();
    assert_eq!(
        http.get(&path)
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        404
    );
    let response = http
        .put(&path)
        .bearer_auth(HOST_TOKEN)
        .json(&people_search_input())
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    assert_eq!(response.headers()["cache-control"], "private, no-store");
    let result: Value = response.json().await.unwrap();
    assert_eq!(result["recorded_state"], "completed");
    assert_eq!(result["company_id"], json!(company));
    assert_eq!(result["persistence_status"], "imported");
    people_search_no_private(&result);
    let before = people_search_snapshot(&mut c).await;
    let data = people_ingest_snapshot(&mut c).await;
    let saved: Value = http
        .get(&path)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(saved, result);
    let repeat: Value = http
        .put(&path)
        .bearer_auth(HOST_TOKEN)
        .json(&people_search_input())
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(repeat, result);
    let mut changed = people_search_input();
    changed["roles"] = json!(["ceo"]);
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
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    assert_eq!(people_search_snapshot(&mut c).await, before);
    assert_eq!(people_ingest_snapshot(&mut c).await, data);
    stop.cancel();
    task.await.unwrap();
    pstop.cancel();
    ptask.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_research_owner_auth_methods_queries_and_body_caps_refuse_before_any_paid_admission()
{
    let mut c = people_search_fixture().await;
    let before = people_search_snapshot(&mut c).await;
    let (url, state, stop, task, pstop, ptask) = people_research_http("official").await;
    let path = research_request_url(&url, 50002);
    let http = client();
    assert_eq!(
        http.put(&path)
            .json(&people_search_input())
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    assert_eq!(
        http.put(&path)
            .bearer_auth(HOST_TOKEN)
            .header("x-agent-client", "extension")
            .json(&people_search_input())
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    assert_eq!(
        http.put(&path)
            .bearer_auth(HOST_TOKEN)
            .header("origin", "https://untrusted-fixture.example")
            .json(&people_search_input())
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    let response = http
        .post(&path)
        .bearer_auth(HOST_TOKEN)
        .json(&people_search_input())
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 405);
    assert_eq!(response.headers()["allow"], "GET, PUT");
    assert_eq!(
        http.put(format!("{path}?replay=true"))
            .bearer_auth(HOST_TOKEN)
            .json(&people_search_input())
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    assert_eq!(
        http.put(&path)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"private":"x".repeat(65536)}))
            .send()
            .await
            .unwrap()
            .status(),
        413
    );
    assert_eq!(
        http.put(&path)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"company_name":"Fictional","extra":true}))
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    assert_eq!(state.calls.load(Ordering::SeqCst), 0);
    assert_eq!(people_search_snapshot(&mut c).await, before);
    stop.cancel();
    task.await.unwrap();
    pstop.cancel();
    ptask.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_research_owner_remote_wait_uses_shared_transient_slot_while_status_remains_available()
 {
    let _c = people_search_fixture().await;
    let (url, state, stop, task, pstop, ptask) = people_research_http("hold").await;
    let pending_url = research_request_url(&url, 50003);
    let pending = tokio::spawn(async move {
        client()
            .put(pending_url)
            .bearer_auth(HOST_TOKEN)
            .json(&people_search_input())
            .send()
            .await
            .unwrap()
    });
    state.entered.notified().await;
    let http = client();
    assert_eq!(
        http.put(research_request_url(&url, 50004))
            .bearer_auth(HOST_TOKEN)
            .json(&people_search_input())
            .send()
            .await
            .unwrap()
            .status(),
        429
    );
    assert_eq!(
        http.get(format!("{url}/api/v1/rust-agent/research/people/status"))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    state.release.notify_one();
    assert_eq!(pending.await.unwrap().status(), 200);
    stop.cancel();
    task.await.unwrap();
    pstop.cancel();
    ptask.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_research_owner_manual_request_needs_no_remote_settings_and_retains_its_original_uuid()
 {
    let mut c = people_search_fixture().await;
    let (url, stop, task) = http_fixture_values(host_values()).await;
    let http = client();
    let path = research_request_url(&url, 50005);
    let response = http
        .put(&path)
        .bearer_auth(HOST_TOKEN)
        .json(&people_manual())
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let result: Value = response.json().await.unwrap();
    assert_eq!(result["provider_calls"], 0);
    let saved: Value = http
        .get(&path)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(saved, result);
    let n: i64 = sqlx::query_scalar("SELECT count(*)::bigint FROM discovery_budget_reservations")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(n, 0);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_research_owner_client_disconnect_keeps_original_admission_and_recovery_cannot_post_again()
 {
    let _c = people_search_fixture().await;
    let (url, state, stop, task, pstop, ptask) = people_research_http("hold").await;
    let path = research_request_url(&url, 50006);
    let pending_path = path.clone();
    let pending = tokio::spawn(async move {
        client()
            .put(pending_path)
            .bearer_auth(HOST_TOKEN)
            .json(&people_search_input())
            .send()
            .await
    });
    state.entered.notified().await;
    pending.abort();
    let _ = pending.await;
    state.release.notify_one();
    let http = client();
    let mut observed = None;
    for _ in 0..100 {
        let response = http
            .get(&path)
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap();
        if response.status() == 429 {
            tokio::time::sleep(Duration::from_millis(10)).await;
            continue;
        }
        assert_eq!(response.status(), 200);
        observed = Some(response.json::<Value>().await.unwrap());
        break;
    }
    let result = observed.expect(
        "original intent/finding/result must remain readable after the bounded original work ends",
    );
    assert_eq!(result["request_id"], json!(Uuid::from_u128(50006)));
    let response = http
        .put(&path)
        .bearer_auth(HOST_TOKEN)
        .json(&people_search_input())
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
    pstop.cancel();
    ptask.await.unwrap();
}
