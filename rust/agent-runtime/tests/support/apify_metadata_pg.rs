// Deferred disposable PG + numeric loopback fixtures. No real account, budgets or Actor execution.
use automated_apply_agents::apify_metadata::{
    owner as apify_owner, transport::Client as ApifyMetadataClient,
};
async fn apify_metadata_fixture() -> PgConnection {
    let mut c = contact_budget_fixture().await;
    sqlx::raw_sql("DROP TABLE IF EXISTS provider_access_windows;CREATE TABLE provider_access_windows(provider varchar(100) PRIMARY KEY,next_allowed_at timestamptz NOT NULL);DELETE FROM owner_preferences WHERE key IN ('rust_apify_capabilities','apify_capabilities')").execute(&mut c).await.unwrap();
    c
}
struct ApifyMetadataFixture {
    calls: AtomicUsize,
    hold: bool,
    entered: tokio::sync::Notify,
    release: tokio::sync::Notify,
}
async fn apify_metadata_response(
    axum::extract::State(f): axum::extract::State<Arc<ApifyMetadataFixture>>,
    r: axum::extract::Request,
) -> axum::response::Response {
    use axum::response::IntoResponse;
    let n = f.calls.fetch_add(1, Ordering::SeqCst);
    assert_eq!(r.method(), "GET");
    let path = r.uri().path();
    assert!(r.uri().query().is_none());
    if path.contains("users/me/") {
        assert_eq!(
            r.headers()["authorization"],
            "Bearer PRIVATE_APIFY_OWNER_CANARY"
        );
    } else {
        assert!(!r.headers().contains_key("authorization"));
    }
    if n == 0 && f.hold {
        f.entered.notify_one();
        f.release.notified().await;
    }
    let cycle = json!({"startAt":"2026-11-01T00:00:00Z","endAt":"2026-12-01T00:00:00Z"});
    axum::Json(match path {
        "/v2/users/me/limits"=>json!({"data":{"monthlyUsageCycle":cycle,"limits":{"maxMonthlyUsageUsd":25},"current":{"monthlyUsageUsd":2},"email":"PRIVATE_ACCOUNT_CANARY"}}),
        "/v2/users/me/usage/monthly"=>json!({"data":{"usageCycle":cycle,"totalUsageCreditsUsdBeforeVolumeDiscount":2,"totalUsageCreditsUsdAfterVolumeDiscount":2,"dailyServiceUsages":[{"private":"PRIVATE_DAILY_CANARY"}]}}),
        "/v2/actors/fictional~public-jobs"=>json!({"data":{"title":"Fictional actor","pricingInfos":[]}}),
        "/v2/actors/fictional~public-jobs/builds/default/openapi.json"=>json!({"paths":{}}),
        _=>panic!("metadata fixture refused unexpected endpoint"),
    }).into_response()
}
async fn apify_metadata_http(
    hold: bool,
) -> (
    BTreeMap<String, String>,
    Arc<ApifyMetadataFixture>,
    CancellationToken,
    tokio::task::JoinHandle<()>,
) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let state = Arc::new(ApifyMetadataFixture {
        calls: AtomicUsize::new(0),
        hold,
        entered: tokio::sync::Notify::new(),
        release: tokio::sync::Notify::new(),
    });
    let router = axum::Router::new()
        .fallback(apify_metadata_response)
        .with_state(state.clone());
    let stop = CancellationToken::new();
    let shutdown = stop.clone();
    let task = tokio::spawn(async move {
        axum::serve(listener, router)
            .with_graceful_shutdown(shutdown.cancelled_owned())
            .await
            .unwrap();
    });
    let values = BTreeMap::from([
        (
            "RUST_APIFY_METADATA_FIXTURE_ORIGIN".into(),
            format!("http://{addr}/v2/"),
        ),
        (
            "APIFY_API_TOKEN".into(),
            "PRIVATE_APIFY_OWNER_CANARY".into(),
        ),
        ("APIFY_MONTHLY_LIMIT_USD".into(), "10".into()),
        ("APIFY_PER_RUN_CAP_USD".into(), "1".into()),
        (
            "APIFY_SOURCES".into(),
            json!({"naukri":{"actor_id":"fictional/public-jobs"}}).to_string(),
        ),
    ]);
    (values, state, stop, task)
}
async fn apify_metadata_snapshot(c: &mut PgConnection) -> Value {
    sqlx::query_scalar("SELECT jsonb_build_object('preferences',(SELECT jsonb_agg(to_jsonb(p) ORDER BY key) FROM owner_preferences p),'pace',(SELECT jsonb_agg(to_jsonb(w) ORDER BY provider) FROM provider_access_windows w),'budget',(SELECT jsonb_agg(to_jsonb(b) ORDER BY provider,month) FROM discovery_monthly_budgets b))").fetch_one(c).await.unwrap()
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_metadata_owner_inspection_saves_closed_account_projection_and_status_never_refreshes_or_writes()
 {
    let mut c = apify_metadata_fixture().await;
    let (v, f, stop, task) = apify_metadata_http(false).await;
    let settings = automated_apply_agents::source_registry::Settings::from_values(&v).unwrap();
    let client = ApifyMetadataClient::from_values(&v, true).unwrap();
    let initial = apify_owner::status(&mut c, &settings, &client)
        .await
        .unwrap();
    assert_eq!(initial["inspection_cache_state"], "not_inspected");
    assert_eq!(f.calls.load(Ordering::SeqCst), 0);
    let result = apify_owner::inspect(&mut c, &settings, &client, None)
        .await
        .unwrap();
    assert!(!result.to_string().contains("CANARY"));
    assert_eq!(result["execution_authorized"], false);
    sqlx::query("INSERT INTO discovery_monthly_budgets(provider,month,reserved) VALUES('apify',to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM'),3)").execute(&mut c).await.unwrap();
    let before = apify_metadata_snapshot(&mut c).await;
    let status = apify_owner::status(&mut c, &settings, &client)
        .await
        .unwrap();
    assert_eq!(status["last_account_inspection"], result);
    assert_eq!(status["inspection_cache_state"], "saved");
    assert_eq!(status["local_budget"]["reserved_usd"], 3.0);
    assert_eq!(status["local_budget"]["remaining_local_usd"], 7.0);
    assert_eq!(
        status["local_budget"]["accounting"],
        "local_reservations_not_provider_credit"
    );
    assert_eq!(status["live_verified"], false);
    assert_eq!(status["execution_authorized"], false);
    assert_eq!(status["sources"].as_array().unwrap().len(), 9);
    assert!(!status.to_string().contains("CANARY"));
    assert_eq!(f.calls.load(Ordering::SeqCst), 2);
    assert_eq!(before, apify_metadata_snapshot(&mut c).await);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_metadata_owner_refuses_unlisted_actor_and_missing_token_before_pacing_or_network() {
    let mut c = apify_metadata_fixture().await;
    let (mut v, f, stop, task) = apify_metadata_http(false).await;
    v.remove("APIFY_API_TOKEN");
    let settings = automated_apply_agents::source_registry::Settings::from_values(&v).unwrap();
    let client = ApifyMetadataClient::from_values(&v, true).unwrap();
    let before = apify_metadata_snapshot(&mut c).await;
    assert_eq!(
        apify_owner::inspect(&mut c, &settings, &client, None).await,
        Err(Failure("apify_local_token_not_configured"))
    );
    assert_eq!(
        apify_owner::inspect(&mut c, &settings, &client, Some("fictional/unlisted")).await,
        Err(Failure("apify_actor_metadata_not_allowlisted"))
    );
    assert_eq!(apify_metadata_snapshot(&mut c).await, before);
    assert_eq!(f.calls.load(Ordering::SeqCst), 0);
    let actor = apify_owner::inspect(&mut c, &settings, &client, Some("fictional/public-jobs"))
        .await
        .unwrap();
    assert_eq!(actor["collection_status"], "disabled_pending_review");
    assert_eq!(f.calls.load(Ordering::SeqCst), 2);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_metadata_pacing_is_committed_before_get_and_owner_mutex_is_free_during_transport() {
    let mut c = apify_metadata_fixture().await;
    let (v, f, stop, task) = apify_metadata_http(true).await;
    let dispatch = tokio::spawn({
        let v = v.clone();
        async move {
            let mut c = connection().await;
            let settings =
                automated_apply_agents::source_registry::Settings::from_values(&v).unwrap();
            let client = ApifyMetadataClient::from_values(&v, true).unwrap();
            apify_owner::inspect(&mut c, &settings, &client, None).await
        }
    });
    f.entered.notified().await;
    let settings = automated_apply_agents::source_registry::Settings::from_values(&v).unwrap();
    let client = ApifyMetadataClient::from_values(&v, true).unwrap();
    assert_eq!(
        apify_owner::inspect(&mut c, &settings, &client, None).await,
        Err(Failure("apify_metadata_access_rate_limited"))
    );
    assert_eq!(f.calls.load(Ordering::SeqCst), 1);
    let mut tx = c.begin().await.unwrap();
    sqlx::query("SET LOCAL lock_timeout='250ms'")
        .execute(&mut *tx)
        .await
        .unwrap();
    sqlx::query(
        "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
    )
    .fetch_one(&mut *tx)
    .await
    .unwrap();
    tx.rollback().await.unwrap();
    f.release.notify_one();
    dispatch.await.unwrap().unwrap();
    assert_eq!(f.calls.load(Ordering::SeqCst), 2);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_metadata_pacing_post_trigger_ack_rolls_back_without_provider_request() {
    let mut c = apify_metadata_fixture().await;
    let (v, f, stop, task) = apify_metadata_http(false).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_apify_pace() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF pg_trigger_depth()=1 THEN UPDATE provider_access_windows SET next_allowed_at=next_allowed_at+interval '1 second' WHERE provider=NEW.provider; END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_apify_pace AFTER INSERT OR UPDATE ON provider_access_windows FOR EACH ROW EXECUTE FUNCTION fixture_apify_pace()").execute(&mut c).await.unwrap();
    let settings = automated_apply_agents::source_registry::Settings::from_values(&v).unwrap();
    let client = ApifyMetadataClient::from_values(&v, true).unwrap();
    assert_eq!(
        apify_owner::inspect(&mut c, &settings, &client, None).await,
        Err(Failure("apify_metadata_write_ack_failed"))
    );
    assert_eq!(f.calls.load(Ordering::SeqCst), 0);
    let count: i64 = sqlx::query_scalar("SELECT count(*) FROM provider_access_windows")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(count, 0);
    sqlx::raw_sql("DROP FUNCTION fixture_apify_pace() CASCADE")
        .execute(&mut c)
        .await
        .unwrap();
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_metadata_cache_post_trigger_ack_retains_original_pacing_and_rolls_back_cache() {
    let mut c = apify_metadata_fixture().await;
    let (v, f, stop, task) = apify_metadata_http(false).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_apify_cache() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.key='rust_apify_capabilities' AND pg_trigger_depth()=1 THEN UPDATE owner_preferences SET value=value||'{\"private\":\"PRIVATE_CACHE_CANARY\"}' WHERE key=NEW.key; END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_apify_cache AFTER INSERT OR UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_apify_cache()").execute(&mut c).await.unwrap();
    let settings = automated_apply_agents::source_registry::Settings::from_values(&v).unwrap();
    let client = ApifyMetadataClient::from_values(&v, true).unwrap();
    assert_eq!(
        apify_owner::inspect(&mut c, &settings, &client, None).await,
        Err(Failure("apify_metadata_write_ack_failed"))
    );
    assert_eq!(f.calls.load(Ordering::SeqCst), 2);
    let count: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM owner_preferences WHERE key='rust_apify_capabilities'",
    )
    .fetch_one(&mut c)
    .await
    .unwrap();
    assert_eq!(count, 0);
    assert_eq!(
        apify_owner::inspect(&mut c, &settings, &client, None).await,
        Err(Failure("apify_metadata_access_rate_limited"))
    );
    assert_eq!(f.calls.load(Ordering::SeqCst), 2);
    sqlx::raw_sql("DROP FUNCTION fixture_apify_cache() CASCADE")
        .execute(&mut c)
        .await
        .unwrap();
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_metadata_changed_credential_tamper_and_legacy_raw_cache_are_qualified_without_network()
 {
    let mut c = apify_metadata_fixture().await;
    let (mut v, f, stop, task) = apify_metadata_http(false).await;
    let settings = automated_apply_agents::source_registry::Settings::from_values(&v).unwrap();
    let client = ApifyMetadataClient::from_values(&v, true).unwrap();
    let mut result = apify_owner::inspect(&mut c, &settings, &client, None)
        .await
        .unwrap();
    v.insert(
        "APIFY_API_TOKEN".into(),
        "PRIVATE_DIFFERENT_KEY_CANARY".into(),
    );
    let changed = ApifyMetadataClient::from_values(&v, true).unwrap();
    let status = apify_owner::status(&mut c, &settings, &changed)
        .await
        .unwrap();
    assert_eq!(status["inspection_cache_state"], "configuration_changed");
    assert!(status["last_account_inspection"].is_null());
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{content_hash}','\"tampered\"') WHERE key='rust_apify_capabilities'").execute(&mut c).await.unwrap();
    assert_eq!(
        apify_owner::status(&mut c, &settings, &client)
            .await
            .unwrap()["inspection_cache_state"],
        "invalid"
    );
    sqlx::query("DELETE FROM owner_preferences WHERE key='rust_apify_capabilities'")
        .execute(&mut c)
        .await
        .unwrap();
    result["limits"]["email"] = json!("PRIVATE_LEGACY_ACCOUNT_CANARY");
    sqlx::query("INSERT INTO owner_preferences(key,value) VALUES('apify_capabilities',$1)")
        .bind(result)
        .execute(&mut c)
        .await
        .unwrap();
    let before = apify_metadata_snapshot(&mut c).await;
    let status = apify_owner::status(&mut c, &settings, &client)
        .await
        .unwrap();
    assert_eq!(
        status["inspection_cache_state"],
        "legacy_context_unverified"
    );
    assert!(!status.to_string().contains("CANARY"));
    assert_eq!(apify_metadata_snapshot(&mut c).await, before);
    assert_eq!(f.calls.load(Ordering::SeqCst), 2);
    sqlx::query("INSERT INTO owner_preferences(key,value) VALUES('rust_apify_capabilities',$1)")
        .bind(json!({"private":"x".repeat(1048577)}))
        .execute(&mut c)
        .await
        .unwrap();
    let status = apify_owner::status(&mut c, &settings, &client)
        .await
        .unwrap();
    assert_eq!(status["inspection_cache_state"], "invalid");
    assert!(status["last_account_inspection"].is_null());
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_metadata_older_inspection_cannot_overwrite_a_newer_committed_claim() {
    let mut c = apify_metadata_fixture().await;
    let (v, f, stop, task) = apify_metadata_http(true).await;
    let first = tokio::spawn({
        let v = v.clone();
        async move {
            let mut c = connection().await;
            let settings =
                automated_apply_agents::source_registry::Settings::from_values(&v).unwrap();
            let client = ApifyMetadataClient::from_values(&v, true).unwrap();
            apify_owner::inspect(&mut c, &settings, &client, None).await
        }
    });
    f.entered.notified().await;
    sqlx::query("UPDATE provider_access_windows SET next_allowed_at=clock_timestamp()-interval '1 second' WHERE provider='apify_metadata'").execute(&mut c).await.unwrap();
    let settings = automated_apply_agents::source_registry::Settings::from_values(&v).unwrap();
    let client = ApifyMetadataClient::from_values(&v, true).unwrap();
    apify_owner::inspect(&mut c, &settings, &client, None)
        .await
        .unwrap();
    let saved = apify_metadata_snapshot(&mut c).await;
    f.release.notify_one();
    assert_eq!(
        first.await.unwrap(),
        Err(Failure("apify_metadata_inspection_superseded"))
    );
    let after = apify_metadata_snapshot(&mut c).await;
    assert_eq!(after["pace"], saved["pace"]);
    let cached: Value = sqlx::query_scalar(
        "SELECT value FROM owner_preferences WHERE key='rust_apify_capabilities'",
    )
    .fetch_one(&mut c)
    .await
    .unwrap();
    let expected = saved["preferences"]
        .as_array()
        .unwrap()
        .iter()
        .find(|v| v["key"] == "rust_apify_capabilities")
        .unwrap()["value"]
        .clone();
    assert_eq!(cached, expected);
    assert_eq!(f.calls.load(Ordering::SeqCst), 4);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_metadata_owner_http_preserves_auth_methods_body_bounds_and_saved_only_get() {
    let _c = apify_metadata_fixture().await;
    let (v, f, pstop, ptask) = apify_metadata_http(false).await;
    let mut values = host_values();
    values.extend(v);
    let (url, stop, task) = http_fixture_values(values).await;
    let http = client();
    let base = format!("{url}/api/v1/integrations/providers/apify");
    assert_eq!(http.get(&base).send().await.unwrap().status(), 401);
    assert_eq!(
        http.put(&base)
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        405
    );
    assert_eq!(
        http.get(format!("{base}?probe=true"))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    assert_eq!(
        http.post(format!("{base}/actors/inspect"))
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"actor_id":"fictional/unlisted"}))
            .send()
            .await
            .unwrap()
            .status(),
        409
    );
    assert_eq!(f.calls.load(Ordering::SeqCst), 0);
    let response = http
        .post(format!("{base}/inspect"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let status: Value = http
        .get(&base)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(status["inspection_cache_state"], "saved");
    assert_eq!(status["execution_authorized"], false);
    assert!(!status.to_string().contains("CANARY"));
    assert_eq!(f.calls.load(Ordering::SeqCst), 2);
    assert_eq!(
        http.post(format!("{base}/inspect"))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        429
    );
    assert_eq!(f.calls.load(Ordering::SeqCst), 2);
    stop.cancel();
    task.await.unwrap();
    pstop.cancel();
    ptask.await.unwrap();
}
