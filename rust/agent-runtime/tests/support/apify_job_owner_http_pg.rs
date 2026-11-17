//! Deferred owner HTTP paid lifecycle: numeric loopback only, no real token/account or paid execution.
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_owner_http_preview_is_read_only_without_owner_lock_or_provider_calls_and_shows_exact_saved_caps()
 {
    let mut c = apify_owner_fixture().await;
    let (mut v, f, remote_stop, remote_task) = apify_job_http("ok").await;
    v.extend(host_values());
    let (url, stop, task) = http_fixture_values(v).await;
    let before = apify_owner_snapshot(&mut c).await;
    let mut holder = connection().await;
    let mut locked = holder.begin().await.unwrap();
    sqlx::query(
        "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
    )
    .fetch_one(&mut *locked)
    .await
    .unwrap();
    let response = tokio::time::timeout(
        Duration::from_secs(2),
        client()
            .post(format!("{url}/api/v1/discovery/preview"))
            .bearer_auth(HOST_TOKEN)
            .json(&apify_job_input())
            .send(),
    )
    .await
    .unwrap()
    .unwrap();
    assert_eq!(response.status(), 200);
    let preview: Value = response.json().await.unwrap();
    assert_eq!(preview["writes"], 0);
    assert_eq!(preview["provider_calls"], 0);
    assert_eq!(preview["paid_execution"]["ready"], true);
    assert_eq!(preview["paid_execution"]["run_cap_usd"], "0.100001");
    assert_eq!(preview["paid_execution"]["monthly_limit_usd"], "2.000001");
    assert_eq!(preview["paid_execution"]["estimated_usd"], "0.020000");
    assert_eq!(preview["dispatch_authorized"], false);
    assert_eq!(f.calls.lock().await.len(), 0);
    assert!(!preview.to_string().contains("CANARY"));
    locked.rollback().await.unwrap();
    assert_eq!(apify_owner_snapshot(&mut c).await, before);
    stop.cancel();
    task.await.unwrap();
    remote_stop.cancel();
    remote_task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_owner_http_original_put_get_replay_and_local_complete_use_one_original_paid_run() {
    let mut c = apify_owner_fixture().await;
    let (mut v, f, remote_stop, remote_task) = apify_job_http("ok").await;
    v.extend(host_values());
    let (url, stop, task) = http_fixture_values(v).await;
    let http = client();
    let id = Uuid::from_u128(73001);
    let path = format!("{url}/api/v1/discovery/runs/{id}");
    let response = http
        .put(&path)
        .bearer_auth(HOST_TOKEN)
        .json(&apify_job_input())
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let result: Value = response.json().await.unwrap();
    assert_eq!(result["id"], json!(id));
    assert_eq!(result["local_intake_complete"], true);
    assert_eq!(result["rankings_complete"], true);
    assert_eq!(result["provider_run_id"], "originalRun");
    assert!(!result.to_string().contains("CANARY"));
    let before = apify_owner_snapshot(&mut c).await;
    for request in [
        http.get(&path),
        http.put(&path).json(&apify_job_input()),
        http.post(format!("{path}/complete")).json(&json!({})),
    ] {
        let response = request.bearer_auth(HOST_TOKEN).send().await.unwrap();
        assert_eq!(response.status(), 200);
        assert_eq!(response.json::<Value>().await.unwrap(), result);
    }
    assert_eq!(apify_owner_snapshot(&mut c).await, before);
    assert_eq!(f.calls.lock().await.len(), 5);
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
    remote_stop.cancel();
    remote_task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_owner_http_keyed_post_uses_paid_namespace_and_changed_body_cannot_admit_again() {
    let mut c = apify_owner_fixture().await;
    let (mut v, f, remote_stop, remote_task) = apify_job_http("ok").await;
    v.extend(host_values());
    let (url, stop, task) = http_fixture_values(v).await;
    let http = client();
    let path = format!("{url}/api/v1/discovery/runs");
    let mut input = apify_job_input();
    input["idempotency_key"] = json!("fictional_apify_http_key");
    let response = http
        .post(&path)
        .bearer_auth(HOST_TOKEN)
        .json(&input)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let result: Value = response.json().await.unwrap();
    assert_eq!(
        result["id"],
        json!(Uuid::new_v5(
            &Uuid::NAMESPACE_URL,
            b"automated-apply:apify-discovery:fictional_apify_http_key"
        ))
    );
    let before = apify_owner_snapshot(&mut c).await;
    let response = http
        .post(&path)
        .bearer_auth(HOST_TOKEN)
        .json(&input)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    assert_eq!(response.json::<Value>().await.unwrap(), result);
    input["query"]["limit"] = json!(21);
    assert_eq!(
        http.post(&path)
            .bearer_auth(HOST_TOKEN)
            .json(&input)
            .send()
            .await
            .unwrap()
            .status(),
        409
    );
    assert_eq!(apify_owner_snapshot(&mut c).await, before);
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
    remote_stop.cancel();
    remote_task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_owner_http_failed_parent_finish_recovers_retained_finding_by_empty_local_complete_without_another_start()
 {
    let mut c = apify_owner_fixture().await;
    let (mut v, f, remote_stop, remote_task) = apify_job_http("ok").await;
    v.extend(host_values());
    let (url, stop, task) = http_fixture_values(v).await;
    let http = client();
    let id = Uuid::from_u128(73002);
    let path = format!("{url}/api/v1/discovery/runs/{id}");
    sqlx::raw_sql("CREATE FUNCTION fixture_apify_http_finish() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NULL;END $$;CREATE TRIGGER fixture_apify_http_finish BEFORE UPDATE ON discovery_runs FOR EACH ROW EXECUTE FUNCTION fixture_apify_http_finish()").execute(&mut c).await.unwrap();
    assert_eq!(
        http.put(&path)
            .bearer_auth(HOST_TOKEN)
            .json(&apify_job_input())
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
    assert_eq!(saved["usage"]["finding_retained"], true);
    assert_eq!(saved["local_intake_complete"], false);
    sqlx::raw_sql("DROP TRIGGER fixture_apify_http_finish ON discovery_runs;DROP FUNCTION fixture_apify_http_finish()").execute(&mut c).await.unwrap();
    let response = http
        .post(format!("{path}/complete"))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({}))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let result: Value = response.json().await.unwrap();
    assert_eq!(result["local_intake_complete"], true);
    assert_eq!(result["rankings_complete"], true);
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    assert_eq!(f.calls.lock().await.len(), 5);
    stop.cancel();
    task.await.unwrap();
    remote_stop.cancel();
    remote_task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_owner_http_unknown_start_remains_saved_without_second_post_even_after_put_replay_and_complete()
 {
    let mut c = apify_owner_fixture().await;
    let (mut v, f, remote_stop, remote_task) = apify_job_http("lost_start").await;
    v.extend(host_values());
    let (url, stop, task) = http_fixture_values(v).await;
    let http = client();
    let id = Uuid::from_u128(73003);
    let path = format!("{url}/api/v1/discovery/runs/{id}");
    assert_eq!(
        http.put(&path)
            .bearer_auth(HOST_TOKEN)
            .json(&apify_job_input())
            .send()
            .await
            .unwrap()
            .status(),
        503
    );
    let before = apify_owner_snapshot(&mut c).await;
    let response = http
        .get(&path)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let result: Value = response.json().await.unwrap();
    assert_eq!(result["status"], "recovery_required");
    assert_eq!(result["usage"]["finding_retained"], false);
    assert_eq!(result["reservation"]["reserved_usd"], "0.100001");
    assert_eq!(
        http.post(format!("{path}/complete"))
            .bearer_auth(HOST_TOKEN)
            .json(&json!({}))
            .send()
            .await
            .unwrap()
            .status(),
        409
    );
    assert_eq!(
        http.put(&path)
            .bearer_auth(HOST_TOKEN)
            .json(&apify_job_input())
            .send()
            .await
            .unwrap()
            .status(),
        409
    );
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    assert_eq!(apify_owner_snapshot(&mut c).await, before);
    stop.cancel();
    task.await.unwrap();
    remote_stop.cancel();
    remote_task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_owner_http_auth_paid_optin_method_and_empty_complete_guards_prevent_remote_dispatch()
{
    let mut c = apify_owner_fixture().await;
    let (mut v, f, remote_stop, remote_task) = apify_job_http("ok").await;
    v.extend(host_values());
    let (url, stop, task) = http_fixture_values(v).await;
    let http = client();
    let path = format!("{url}/api/v1/discovery/runs/{}", Uuid::from_u128(73004));
    let before = apify_owner_snapshot(&mut c).await;
    assert_eq!(
        http.put(&path)
            .json(&apify_job_input())
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    let mut no_consent = apify_job_input();
    no_consent["allow_paid"] = json!(false);
    assert_eq!(
        http.put(&path)
            .bearer_auth(HOST_TOKEN)
            .json(&no_consent)
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
    assert_eq!(
        http.post(format!("{path}/complete"))
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"run_id":"foreignRun"}))
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    assert_eq!(f.calls.lock().await.len(), 0);
    assert_eq!(apify_owner_snapshot(&mut c).await, before);
    stop.cancel();
    task.await.unwrap();
    remote_stop.cancel();
    remote_task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_owner_http_legacy_paid_rows_and_ambiguous_native_scopes_cannot_be_adopted_or_dispatch_provider()
 {
    let mut c = apify_owner_fixture().await;
    let (mut v, f, remote_stop, remote_task) = apify_job_http("ok").await;
    let id = Uuid::from_u128(73005);
    sqlx::query("INSERT INTO discovery_runs(id,source,request_hash,status,counts,errors,usage,query_summary) VALUES($1,'naukri','legacy','running','{}','[\"PRIVATE_LEGACY_CANARY\"]','{}','{}')").bind(id).execute(&mut c).await.unwrap();
    v.extend(host_values());
    let (url, stop, task) = http_fixture_values(v).await;
    let http = client();
    let path = format!("{url}/api/v1/discovery/runs/{id}");
    let before = apify_owner_snapshot(&mut c).await;
    let response = http
        .get(&path)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let result: Value = response.json().await.unwrap();
    assert_eq!(result["original_scope_available"], false);
    assert_eq!(result["status"], "recovery_required");
    assert!(!result.to_string().contains("CANARY"));
    assert_eq!(
        http.put(&path)
            .bearer_auth(HOST_TOKEN)
            .json(&apify_job_input())
            .send()
            .await
            .unwrap()
            .status(),
        409
    );
    assert_eq!(apify_owner_snapshot(&mut c).await, before);
    assert_eq!(f.calls.lock().await.len(), 0);
    for prefix in ["job_run:", "apify_owner:"] {
        sqlx::query("INSERT INTO owner_preferences(key,value) VALUES($1,'{}')")
            .bind(format!("{prefix}{}", id.simple()))
            .execute(&mut c)
            .await
            .unwrap();
    }
    assert_eq!(
        http.get(&path)
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        409
    );
    assert_eq!(f.calls.lock().await.len(), 0);
    stop.cancel();
    task.await.unwrap();
    remote_stop.cancel();
    remote_task.await.unwrap();
}
