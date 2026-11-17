//! Deferred original paid execution through numeric loopback. No real Actors, tokens or money.
use automated_apply_agents::apify_jobs::{
    controller::Service as ApifyJobService, transport::Client as ApifyJobClient,
};
struct ApifyJobHttp {
    mode: &'static str,
    started: chrono::DateTime<chrono::Utc>,
    calls: tokio::sync::Mutex<Vec<String>>,
    starts: AtomicUsize,
    statuses: AtomicUsize,
    aborts: AtomicUsize,
    entered: tokio::sync::Notify,
    release: tokio::sync::Notify,
}
fn apify_job_schema() -> Value {
    json!({"type":"object","required":["maxItems"],"additionalProperties":false,"properties":{"maxItems":{"type":"integer","minimum":1,"maximum":100}}})
}
fn apify_http_run(status: &str, started: chrono::DateTime<chrono::Utc>) -> Value {
    let now = chrono::Utc::now();
    json!({"data":{"id":"originalRun","actId":"originalActor","buildId":"originalBuild","buildNumber":"1.2.3","status":status,"defaultDatasetId":"originalDataset","startedAt":started.to_rfc3339(),"finishedAt":if matches!(status,"SUCCEEDED"|"ABORTED"){json!(now.to_rfc3339())}else{Value::Null},"options":{"build":"1.2.3","timeoutSecs":60,"restartOnError":false,"maxTotalChargeUsd":0.100001,"maxItems":20},"usageTotalUsd":0.01,"meta":{"private":"PRIVATE_APIFY_RUN_CANARY"},"containerUrl":"https://private-fixture.example/never-read"}})
}
async fn apify_job_response(
    axum::extract::State(f): axum::extract::State<Arc<ApifyJobHttp>>,
    r: axum::extract::Request,
) -> axum::response::Response {
    use axum::response::IntoResponse;
    assert_eq!(
        r.headers()["authorization"],
        "Bearer PRIVATE_APIFY_INTENT_TOKEN_CANARY"
    );
    assert!(!r.headers().contains_key("cookie"));
    let path = r.uri().path().to_owned();
    let query = r.uri().query().unwrap_or("").to_owned();
    f.calls
        .lock()
        .await
        .push(format!("{} {}", r.method(), r.uri()));
    assert!(!query.contains("token"));
    if path == "/v2/actors/fictional~public-jobs" {
        assert_eq!(r.method(), "GET");
        assert!(query.is_empty());
        if f.mode == "auth" {
            return (
                axum::http::StatusCode::UNAUTHORIZED,
                "PRIVATE_AUTH_ERROR_CANARY",
            )
                .into_response();
        }
        if f.mode == "redirect" {
            return (
                axum::http::StatusCode::FOUND,
                [("location", "https://private-fixture.example/never-read")],
                "PRIVATE_REDIRECT_CANARY",
            )
                .into_response();
        }
        return axum::Json(json!({"data":{"id":"originalActor","username":"fictional","name":"public-jobs","private":"PRIVATE_ACTOR_CANARY"}})).into_response();
    }
    if path == "/v2/actor-builds/originalBuild" {
        assert_eq!(r.method(), "GET");
        assert!(query.is_empty());
        let schema = if f.mode == "schema_changed" {
            json!({"type":"string"})
        } else {
            apify_job_schema()
        };
        return axum::Json(json!({"data":{"id":"originalBuild","actId":"originalActor","buildNumber":"1.2.3","status":"SUCCEEDED","inputSchema":schema.to_string(),"imageDigest":"a".repeat(64),"private":"PRIVATE_BUILD_CANARY"}})).into_response();
    }
    if path == "/v2/actors/originalActor/runs" {
        assert_eq!(r.method(), "POST");
        f.starts.fetch_add(1, Ordering::SeqCst);
        if f.mode == "hold_start" {
            f.entered.notify_one();
            f.release.notified().await;
        }
        assert!(query.contains("maxTotalChargeUsd=0.100001"));
        assert!(query.contains("restartOnError=false"));
        assert!(query.contains("timeout=60"));
        assert!(query.contains("build=1.2.3"));
        let bytes = axum::body::to_bytes(r.into_body(), 65536).await.unwrap();
        assert_eq!(
            serde_json::from_slice::<Value>(&bytes).unwrap(),
            json!({"maxItems":20})
        );
        if f.mode == "rate" {
            return (
                axum::http::StatusCode::TOO_MANY_REQUESTS,
                [("retry-after", "3600")],
                "PRIVATE_RATE_ERROR_CANARY",
            )
                .into_response();
        }
        if f.mode == "lost_start" {
            return (
                [("content-type", "application/json")],
                "PRIVATE_BROKEN_START_CANARY",
            )
                .into_response();
        }
        let mut run = apify_http_run(
            if matches!(f.mode, "poll" | "stuck") {
                "RUNNING"
            } else {
                "SUCCEEDED"
            },
            f.started,
        );
        if f.mode == "foreign_run" {
            run["data"]["actId"] = json!("otherActor")
        }
        return (axum::http::StatusCode::CREATED, axum::Json(run)).into_response();
    }
    if path == "/v2/actor-runs/originalRun" {
        assert_eq!(r.method(), "GET");
        assert!(query.contains("waitForFinish=10"));
        f.statuses.fetch_add(1, Ordering::SeqCst);
        return axum::Json(apify_http_run(
            if f.mode == "stuck" {
                "RUNNING"
            } else {
                "SUCCEEDED"
            },
            f.started,
        ))
        .into_response();
    }
    if path == "/v2/actor-runs/originalRun/abort" {
        assert_eq!(r.method(), "POST");
        assert!(query.contains("gracefully=false"));
        f.aborts.fetch_add(1, Ordering::SeqCst);
        return axum::Json(apify_http_run("ABORTED", f.started)).into_response();
    }
    if path == "/v2/datasets/originalDataset/items" {
        assert_eq!(r.method(), "GET");
        assert!(query.contains("format=json"));
        assert!(query.contains("offset=0"));
        assert!(query.contains("limit=20"));
        if f.mode == "oversized" {
            return ([("content-type", "application/json")], "x".repeat(1048577)).into_response();
        }
        if f.mode == "too_many" {
            return axum::Json(vec![json!({}); 21]).into_response();
        }
        let row = json!({"id":"fixture_job","url":"https://job-fixture.example/12345","companyName":"Fictional Public Employer","title":"Fictional Engineer","description":"Fictional Rust role","location":"Remote","private_token":"PRIVATE_DATASET_CANARY"});
        let mut rows = vec![row.clone()];
        if f.mode == "duplicate" {
            rows.push(row.clone())
        }
        if f.mode == "conflict" {
            let mut changed = row;
            changed["title"] = json!("Conflicting title");
            rows.push(changed)
        }
        return axum::Json(rows).into_response();
    }
    panic!("unpermitted fixture path")
}
async fn apify_job_http(
    mode: &'static str,
) -> (
    BTreeMap<String, String>,
    Arc<ApifyJobHttp>,
    CancellationToken,
    tokio::task::JoinHandle<()>,
) {
    use sha2::Digest;
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let f = Arc::new(ApifyJobHttp {
        mode,
        started: chrono::Utc::now(),
        calls: tokio::sync::Mutex::new(vec![]),
        starts: AtomicUsize::new(0),
        statuses: AtomicUsize::new(0),
        aborts: AtomicUsize::new(0),
        entered: tokio::sync::Notify::new(),
        release: tokio::sync::Notify::new(),
    });
    let app = axum::Router::new()
        .fallback(apify_job_response)
        .with_state(f.clone());
    let stop = CancellationToken::new();
    let shutdown = stop.clone();
    let task = tokio::spawn(async move {
        axum::serve(listener, app)
            .with_graceful_shutdown(shutdown.cancelled_owned())
            .await
            .unwrap()
    });
    let mut values = apify_job_values();
    values.insert(
        "RUST_APIFY_EXECUTION_FIXTURE_ORIGIN".into(),
        format!("http://{address}/v2/"),
    );
    let digest = format!(
        "{:x}",
        sha2::Sha256::digest(
            automated_apply_agents::python_json::serialize(&apify_job_schema(), false, true)
                .as_bytes()
        )
    );
    values.insert(
        "APIFY_BUILD_REVIEWS".into(),
        json!({"naukri":{"build_id":"originalBuild","schema_digest":digest}}).to_string(),
    );
    (values, f, stop, task)
}
async fn apify_transport_acquire(
    c: &mut PgConnection,
    values: &BTreeMap<String, String>,
    n: u128,
) -> Result<Value> {
    let settings = ApifyJobSettings::from_values(values)?;
    let client = ApifyJobClient::from_values(values, true)?;
    ApifyJobService {
        settings: &settings,
        client: &client,
    }
    .acquire(c, apify_job_input(), Uuid::from_u128(n))
    .await
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_original_transport_retains_selected_finding_and_bound_run_before_replay_without_new_calls()
 {
    let mut c = apify_job_admission_fixture().await;
    let (v, f, stop, task) = apify_job_http("ok").await;
    let result = apify_transport_acquire(&mut c, &v, 70001).await.unwrap();
    assert_eq!(result["status"], "success");
    assert_eq!(result["recorded_state"], "finding_retained");
    assert_eq!(result["jobs"].as_array().unwrap().len(), 1);
    assert_eq!(result["local_intake_complete"], false);
    assert_eq!(result["reservation"]["reserved_usd"], "0.100001");
    assert_eq!(result["billing_final"], false);
    assert!(!result.to_string().contains("CANARY"));
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    assert_eq!(f.calls.lock().await.len(), 5);
    let run: Option<String> = sqlx::query_scalar(
        "SELECT provider_run_id FROM discovery_budget_reservations WHERE provider='apify'",
    )
    .fetch_one(&mut c)
    .await
    .unwrap();
    assert_eq!(run.as_deref(), Some("originalRun"));
    let before = apify_job_intent_snapshot(&mut c).await;
    assert_eq!(
        apify_transport_acquire(&mut c, &v, 70001).await.unwrap(),
        result
    );
    assert_eq!(apify_job_intent_snapshot(&mut c).await, before);
    assert_eq!(f.calls.lock().await.len(), 5);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_lost_start_response_never_repeats_billable_post_and_retains_full_unknown_reservation()
 {
    let mut c = apify_job_admission_fixture().await;
    let (v, f, stop, task) = apify_job_http("lost_start").await;
    assert_eq!(
        apify_transport_acquire(&mut c, &v, 70002)
            .await
            .unwrap_err(),
        Failure("apify_execution_json_invalid")
    );
    let saved = apify_admission::read(&mut c, Uuid::from_u128(70002))
        .await
        .unwrap();
    assert_eq!(saved["status"], "outcome_unknown");
    assert_eq!(saved["provider_start_attempted"], true);
    assert!(saved["run_id"].is_null());
    assert_eq!(saved["reservation"]["reserved_usd"], "0.100001");
    assert!(!saved.to_string().contains("CANARY"));
    let before = apify_job_intent_snapshot(&mut c).await;
    assert_eq!(
        apify_transport_acquire(&mut c, &v, 70002).await.unwrap(),
        saved
    );
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    assert_eq!(apify_job_intent_snapshot(&mut c).await, before);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_current_reviewed_build_schema_is_checked_before_original_start() {
    let mut c = apify_job_admission_fixture().await;
    let (v, f, stop, task) = apify_job_http("schema_changed").await;
    assert_eq!(
        apify_transport_acquire(&mut c, &v, 70003)
            .await
            .unwrap_err(),
        Failure("apify_reviewed_schema_changed")
    );
    assert_eq!(f.starts.load(Ordering::SeqCst), 0);
    let saved = apify_admission::read(&mut c, Uuid::from_u128(70003))
        .await
        .unwrap();
    assert_eq!(saved["provider_start_attempted"], false);
    assert_eq!(saved["reservation"]["reserved_usd"], "0.100001");
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_auth_redirect_foreign_run_and_dataset_byte_or_count_errors_do_not_expose_private_bodies_or_follow_urls()
 {
    for (n, mode) in [
        (70004, "auth"),
        (70005, "redirect"),
        (70006, "foreign_run"),
        (70007, "oversized"),
        (70008, "too_many"),
    ] {
        let mut c = apify_job_admission_fixture().await;
        let (v, f, stop, task) = apify_job_http(mode).await;
        assert!(apify_transport_acquire(&mut c, &v, n).await.is_err());
        let saved = apify_admission::read(&mut c, Uuid::from_u128(n))
            .await
            .unwrap();
        assert_ne!(saved["status"], "success");
        assert!(!saved.to_string().contains("CANARY"));
        assert_eq!(saved["reservation"]["reserved_usd"], "0.100001");
        assert!(f.starts.load(Ordering::SeqCst) <= 1);
        assert_eq!(f.aborts.load(Ordering::SeqCst), 0);
        stop.cancel();
        task.await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_run_polling_is_bounded_and_one_abort_intent_is_qualified_without_billing_finality() {
    let mut c = apify_job_admission_fixture().await;
    let (v, f, stop, task) = apify_job_http("stuck").await;
    assert_eq!(
        apify_transport_acquire(&mut c, &v, 70009)
            .await
            .unwrap_err(),
        Failure("apify_original_run_not_succeeded")
    );
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    assert_eq!(f.statuses.load(Ordering::SeqCst), 3);
    assert_eq!(f.aborts.load(Ordering::SeqCst), 1);
    let saved = apify_admission::read(&mut c, Uuid::from_u128(70009))
        .await
        .unwrap();
    assert_ne!(saved["status"], "success");
    assert_eq!(saved["reservation"]["billing_final"], false);
    let before = f.calls.lock().await.len();
    apify_transport_acquire(&mut c, &v, 70009).await.unwrap();
    assert_eq!(f.calls.lock().await.len(), before);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_provider_rate_response_monotonically_holds_future_admissions_without_refunding_unknown_start()
 {
    let mut c = apify_job_admission_fixture().await;
    let (v, f, stop, task) = apify_job_http("rate").await;
    assert_eq!(
        apify_transport_acquire(&mut c, &v, 70010)
            .await
            .unwrap_err(),
        Failure("apify_execution_rate_limited")
    );
    assert!(sqlx::query_scalar::<_,bool>("SELECT cooldown_until>clock_timestamp()+interval '59 minutes' FROM discovery_monthly_budgets WHERE provider='apify'").fetch_one(&mut c).await.unwrap());
    let before = apify_job_intent_snapshot(&mut c).await;
    assert_eq!(
        apify_transport_acquire(&mut c, &v, 70011)
            .await
            .unwrap_err(),
        Failure("apify_execution_cooling_down")
    );
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    assert_eq!(apify_job_intent_snapshot(&mut c).await, before);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_start_admission_trigger_failure_holds_before_billable_http_while_prior_metadata_stays_retained()
 {
    let mut c = apify_job_admission_fixture().await;
    let (v, f, stop, task) = apify_job_http("ok").await;
    sqlx::raw_sql("CREATE FUNCTION fixture_apify_start_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'apify_job:') AND NEW.value->'operation'->>'kind'='start' AND NEW.value->'operation'->>'state'='admitted' THEN RETURN NULL;END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_apify_start_drop BEFORE UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_apify_start_drop()").execute(&mut c).await.unwrap();
    assert_eq!(
        apify_transport_acquire(&mut c, &v, 70012)
            .await
            .unwrap_err(),
        Failure("apify_execution_write_ack_failed")
    );
    assert_eq!(f.starts.load(Ordering::SeqCst), 0);
    assert_eq!(f.calls.lock().await.len(), 2);
    let saved = apify_admission::read(&mut c, Uuid::from_u128(70012))
        .await
        .unwrap();
    assert_eq!(saved["recorded_state"], "response_retained");
    assert_eq!(saved["provider_start_attempted"], false);
    sqlx::raw_sql("DROP TRIGGER fixture_apify_start_drop ON owner_preferences;DROP FUNCTION fixture_apify_start_drop()").execute(&mut c).await.unwrap();
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_run_attachment_failed_ack_never_allows_poll_or_dataset_or_repeated_start() {
    let mut c = apify_job_admission_fixture().await;
    let (v, f, stop, task) = apify_job_http("ok").await;
    sqlx::raw_sql("CREATE FUNCTION fixture_apify_attach_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.provider='apify' THEN RETURN NULL;END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_apify_attach_drop BEFORE UPDATE ON discovery_budget_reservations FOR EACH ROW EXECUTE FUNCTION fixture_apify_attach_drop()").execute(&mut c).await.unwrap();
    assert_eq!(
        apify_transport_acquire(&mut c, &v, 70013)
            .await
            .unwrap_err(),
        Failure("apify_execution_write_ack_failed")
    );
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    assert_eq!(f.calls.lock().await.len(), 3);
    let saved = apify_admission::read(&mut c, Uuid::from_u128(70013))
        .await
        .unwrap();
    assert_eq!(saved["recorded_state"], "operation_admitted");
    assert!(saved["provider_start_attempted"].is_null());
    assert!(saved["run_id"].is_null());
    let before = apify_job_intent_snapshot(&mut c).await;
    apify_transport_acquire(&mut c, &v, 70013).await.unwrap();
    assert_eq!(apify_job_intent_snapshot(&mut c).await, before);
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    sqlx::raw_sql("DROP TRIGGER fixture_apify_attach_drop ON discovery_budget_reservations;DROP FUNCTION fixture_apify_attach_drop()").execute(&mut c).await.unwrap();
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_selected_record_dedup_keeps_identical_and_quarantines_all_conflicting_source_identities()
 {
    for (n, mode, status, count, rejected, duplicates) in [
        (70014, "duplicate", "success", 1, 0, 1),
        (70015, "conflict", "partial", 0, 2, 0),
    ] {
        let mut c = apify_job_admission_fixture().await;
        let (v, _, stop, task) = apify_job_http(mode).await;
        let saved = apify_transport_acquire(&mut c, &v, n).await.unwrap();
        assert_eq!(saved["status"], status);
        assert_eq!(saved["jobs"].as_array().unwrap().len(), count);
        assert_eq!(saved["rejected_count"], rejected);
        assert_eq!(saved["duplicate_count"], duplicates);
        stop.cancel();
        task.await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_cancelled_original_start_keeps_durable_unknown_intent_and_cannot_be_rehydrated_for_another_post()
 {
    let mut c = apify_job_admission_fixture().await;
    let (v, f, stop, task) = apify_job_http("hold_start").await;
    let values = v.clone();
    let pending = tokio::spawn(async move {
        let mut c = connection().await;
        apify_transport_acquire(&mut c, &values, 70016).await
    });
    tokio::time::timeout(Duration::from_secs(5), f.entered.notified())
        .await
        .unwrap();
    pending.abort();
    assert!(pending.await.unwrap_err().is_cancelled());
    let before = apify_job_intent_snapshot(&mut c).await;
    let saved = apify_admission::read(&mut c, Uuid::from_u128(70016))
        .await
        .unwrap();
    assert_eq!(saved["recorded_state"], "operation_admitted");
    assert!(saved["provider_start_attempted"].is_null());
    assert_eq!(saved["reservation"]["reserved_usd"], "0.100001");
    assert_eq!(
        apify_transport_acquire(&mut c, &v, 70016).await.unwrap(),
        saved
    );
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    assert_eq!(apify_job_intent_snapshot(&mut c).await, before);
    f.release.notify_one();
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_original_matching_run_poll_can_finish_with_one_status_read_without_second_start() {
    let mut c = apify_job_admission_fixture().await;
    let (v, f, stop, task) = apify_job_http("poll").await;
    let result = apify_transport_acquire(&mut c, &v, 70017).await.unwrap();
    assert_eq!(result["status"], "success");
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    assert_eq!(f.statuses.load(Ordering::SeqCst), 1);
    assert_eq!(f.aborts.load(Ordering::SeqCst), 0);
    stop.cancel();
    task.await.unwrap();
}
