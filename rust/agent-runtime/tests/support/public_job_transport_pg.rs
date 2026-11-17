// Deferred fixed public GETs through original DB admission; all remote targets map to numeric loopback.
use automated_apply_agents::job_sources::{
    controller::Service as PublicJobService, transport::Client as PublicJobClient,
};
struct PublicJobHttpFixture {
    source: PublicJobSource,
    mode: &'static str,
    calls: AtomicUsize,
    paths: tokio::sync::Mutex<Vec<String>>,
    entered: tokio::sync::Notify,
    release: tokio::sync::Notify,
}
fn public_job_fixture_record(source: PublicJobSource, board: &str) -> Value {
    match source {
        PublicJobSource::Greenhouse => {
            json!({"id":12345,"absolute_url":format!("https://boards.greenhouse.io/{board}/jobs/12345"),"title":"Fictional Engineer","content":"Public fictional role","location":{"name":"Remote"},"first_published":"2026-11-01T00:00:00Z"})
        }
        PublicJobSource::Lever => {
            json!({"id":"abcdefghij-12345","hostedUrl":format!("https://jobs.lever.co/{board}/abcdefghij-12345"),"text":"Fictional Engineer","descriptionPlain":"Public fictional role","categories":{"location":"Remote"},"workplaceType":"remote"})
        }
        PublicJobSource::Ashby => {
            json!({"jobUrl":format!("https://jobs.ashbyhq.com/{board}/abcdefghij-12345"),"title":"Fictional Engineer","descriptionPlain":"Public fictional role","isListed":true,"workplaceType":"Remote","isRemote":true,"publishedAt":"2026-11-01T00:00:00Z"})
        }
        PublicJobSource::Smartrecruiters => {
            json!({"id":"12345","active":true,"company":{"identifier":board},"postingUrl":format!("https://jobs.smartrecruiters.com/{board}/12345-fictional-role"),"name":"Fictional Engineer","jobAd":{"sections":{"jobDescription":{"text":"Public fictional role"}}},"location":{"city":"Remote","remote":true},"releasedDate":"2026-11-01T00:00:00Z","recruiter":{"email":"PRIVATE_RECRUITER_CANARY"}})
        }
        PublicJobSource::Remotive => {
            json!({"id":12345,"url":"https://remotive.com/remote-jobs/fictional-role","title":"Fictional Engineer","company_name":"Fictional Employer","description":"Public fictional role","candidate_required_location":"Worldwide","publication_date":"2026-11-01T00:00:00Z"})
        }
        PublicJobSource::Arbeitnow => {
            json!({"slug":"fictional-role","url":"https://www.arbeitnow.com/jobs/fictional-role","title":"Fictional Engineer","company_name":"Fictional Employer","description":"Public fictional role","created_at":1793491200,"remote":true})
        }
        PublicJobSource::HackerNews => {
            json!({"objectID":"12345","parent_id":98765,"comment_text":"Fictional Employer | Fictional Engineer | Remote\nPublic fictional role","created_at":"2026-11-01T00:00:00Z"})
        }
    }
}
async fn public_job_http_response(
    axum::extract::State(f): axum::extract::State<Arc<PublicJobHttpFixture>>,
    r: axum::extract::Request,
) -> axum::response::Response {
    use axum::response::IntoResponse;
    assert_eq!(r.method(), "GET");
    assert!(!r.headers().contains_key("authorization"));
    assert!(!r.headers().contains_key("cookie"));
    let path = r.uri().path().to_owned();
    assert!(path.starts_with(&format!("/fixtures/{}/", f.source.name())));
    let n = f.calls.fetch_add(1, Ordering::SeqCst);
    f.paths.lock().await.push(r.uri().to_string());
    f.entered.notify_one();
    if f.mode == "hold" && n == 0 {
        f.release.notified().await;
    }
    match f.mode {
        "partial" if n > 0 => {
            return (
                axum::http::StatusCode::SERVICE_UNAVAILABLE,
                axum::Json(json!({"private":"PRIVATE_PARTIAL_BODY_CANARY"})),
            )
                .into_response();
        }
        "auth" => {
            return (
                axum::http::StatusCode::FORBIDDEN,
                axum::Json(json!({"private":"PRIVATE_PROVIDER_ERROR_CANARY"})),
            )
                .into_response();
        }
        "rate" => {
            return (
                axum::http::StatusCode::TOO_MANY_REQUESTS,
                [("retry-after", "7200")],
                axum::Json(json!({"private":"PRIVATE_PROVIDER_ERROR_CANARY"})),
            )
                .into_response();
        }
        "redirect" => {
            return (
                axum::http::StatusCode::FOUND,
                [("location", "https://private-fixture.example/unpermitted")],
                "PRIVATE_REDIRECT_CANARY",
            )
                .into_response();
        }
        "invalid" => {
            return (
                [("content-type", "application/json")],
                "PRIVATE_INVALID_JSON_CANARY",
            )
                .into_response();
        }
        "oversized" => {
            return ([("content-type", "application/json")], "x".repeat(8388609)).into_response();
        }
        "html" => return "PRIVATE_HTML_CANARY".into_response(),
        _ => {}
    }
    let board = if path.contains("/zeta/") {
        "zeta"
    } else {
        "fictional"
    };
    let mut record = public_job_fixture_record(f.source, board);
    record["private_provider_key"] = json!("PRIVATE_PROVIDER_KEY_CANARY");
    if f.mode == "invalid_record" {
        record["title"] = json!("");
        record["text"] = json!("");
        record["name"] = json!("");
        record["comment_text"] = json!("unattributed");
    }
    let mut rows = vec![record.clone()];
    if matches!(f.mode, "duplicate" | "inconsistent") {
        let mut duplicate = record;
        if f.mode == "inconsistent" {
            duplicate["title"] = json!("Changed title");
        }
        rows.push(duplicate);
    }
    axum::Json(match f.source{
        PublicJobSource::Greenhouse=>{assert!(r.uri().query().unwrap().contains("content=true"));json!({"jobs":rows})},
        PublicJobSource::Lever=>{assert!(r.uri().query().unwrap().contains("mode=json"));json!(rows)},
        PublicJobSource::Ashby=>{assert!(r.uri().query().unwrap().contains("includeCompensation=true"));if f.mode=="unlisted"{rows[0]["isListed"]=json!(false);}json!({"apiVersion":"1","jobs":rows})},
        PublicJobSource::Smartrecruiters=>{
            if path.ends_with("/postings"){
                let q=reqwest::Url::parse(&format!("http://fixture.example{}",r.uri())).unwrap();let p=q.query_pairs().collect::<BTreeMap<_,_>>();let offset=p["offset"].parse::<usize>().unwrap();let limit=p["limit"].parse::<usize>().unwrap();
                let content=if offset==0{vec![json!({"id":"12345","ref":"https://private-fixture.example/never-read"})]}else{vec![]};
                if f.mode=="bad_page"{json!({"offset":offset+1,"limit":limit,"totalFound":1,"content":content})}else{json!({"offset":offset,"limit":limit,"totalFound":1,"content":content})}
            }else{assert!(path.ends_with("/postings/12345"));let mut r=rows[0].clone();if f.mode=="foreign"{r["company"]["identifier"]=json!("unreviewed");}r}
        },
        PublicJobSource::Remotive=>{let query=r.uri().query().unwrap();assert!(query.contains("category=software-dev"));assert!(query.contains("search="));json!({"jobs":rows})},
        PublicJobSource::Arbeitnow=>json!({"data":rows,"links":{"next":if f.mode=="more"{json!("https://private-fixture.example/never-read")}else{Value::Null}}}),
        PublicJobSource::HackerNews=>{
            if path.ends_with("/search_by_date"){json!({"hits":[{"objectID":"98765","title":"Ask HN: Who is hiring? (November 2026)"}]})}
            else {assert!(r.uri().query().unwrap().contains("numericFilters=parent_id%3D98765"));json!({"hits":rows,"nbPages":1})}
        },
    }).into_response()
}
async fn public_job_http(
    source: PublicJobSource,
    mode: &'static str,
) -> (
    BTreeMap<String, String>,
    Arc<PublicJobHttpFixture>,
    CancellationToken,
    tokio::task::JoinHandle<()>,
) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let f = Arc::new(PublicJobHttpFixture {
        source,
        mode,
        calls: AtomicUsize::new(0),
        paths: tokio::sync::Mutex::new(Vec::new()),
        entered: tokio::sync::Notify::new(),
        release: tokio::sync::Notify::new(),
    });
    let app = axum::Router::new()
        .fallback(public_job_http_response)
        .with_state(f.clone());
    let stop = CancellationToken::new();
    let shutdown = stop.clone();
    let task = tokio::spawn(async move {
        axum::serve(listener, app)
            .with_graceful_shutdown(shutdown.cancelled_owned())
            .await
            .unwrap();
    });
    let mut values = BTreeMap::from([(
        "RUST_PUBLIC_JOBS_FIXTURE_ORIGIN".into(),
        format!("http://{addr}/"),
    )]);
    for key in [
        "GREENHOUSE_BOARDS",
        "LEVER_BOARDS",
        "ASHBY_BOARDS",
        "SMARTRECRUITERS_BOARDS",
    ] {
        values.insert(
            key.into(),
            json!({"fictional":"Fictional Employer"}).to_string(),
        );
    }
    (values, f, stop, task)
}
async fn public_job_acquire(
    c: &mut PgConnection,
    values: &BTreeMap<String, String>,
    source: PublicJobSource,
    query: Value,
    n: u128,
) -> Result<Value> {
    let settings = automated_apply_agents::source_registry::Settings::from_values(values)?;
    let client = PublicJobClient::from_values(values, true)?;
    PublicJobService {
        settings: &settings,
        client: &client,
    }
    .acquire(c, source, query, Uuid::from_u128(n))
    .await
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_job_all_seven_sources_retain_fixed_get_observations_and_replay_without_another_request()
 {
    for (index, source) in [
        PublicJobSource::Greenhouse,
        PublicJobSource::Lever,
        PublicJobSource::Ashby,
        PublicJobSource::Smartrecruiters,
        PublicJobSource::Remotive,
        PublicJobSource::Arbeitnow,
        PublicJobSource::HackerNews,
    ]
    .into_iter()
    .enumerate()
    {
        let mut c = public_job_access_fixture().await;
        let (v, f, stop, task) = public_job_http(source, "ok").await;
        let value = public_job_acquire(
            &mut c,
            &v,
            source,
            json!({"limit":2}),
            62000 + index as u128,
        )
        .await
        .unwrap();
        assert_eq!(value["status"], "success");
        assert_eq!(value["batch_complete"], true);
        assert_eq!(value["recorded_state"], "finding_retained");
        assert_eq!(value["jobs"].as_array().unwrap().len(), 1);
        assert_eq!(value["writes_to_job_queue"], 0);
        assert_eq!(value["application_dispatch"], false);
        assert!(!value.to_string().contains("CANARY"));
        let calls = f.calls.load(Ordering::SeqCst);
        assert_eq!(
            calls,
            if matches!(
                source,
                PublicJobSource::Smartrecruiters | PublicJobSource::HackerNews
            ) {
                2
            } else {
                1
            }
        );
        let before = public_job_access_snapshot(&mut c).await;
        let replay = public_job_acquire(
            &mut c,
            &v,
            source,
            json!({"limit":2}),
            62000 + index as u128,
        )
        .await
        .unwrap();
        assert_eq!(replay, value);
        assert_eq!(f.calls.load(Ordering::SeqCst), calls);
        assert_eq!(public_job_access_snapshot(&mut c).await, before);
        stop.cancel();
        task.await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_job_redirect_auth_json_type_and_size_failures_are_retained_without_retries_or_private_errors()
 {
    for (index, mode, status) in [
        (0, "auth", "authentication_required"),
        (1, "redirect", "upstream_error"),
        (2, "invalid", "upstream_error"),
        (3, "html", "upstream_error"),
        (4, "oversized", "upstream_error"),
    ] {
        let mut c = public_job_access_fixture().await;
        let (v, f, stop, task) = public_job_http(PublicJobSource::Arbeitnow, mode).await;
        let result = public_job_acquire(
            &mut c,
            &v,
            PublicJobSource::Arbeitnow,
            json!({}),
            62100 + index,
        )
        .await
        .unwrap();
        assert_eq!(result["status"], status);
        assert_eq!(result["batch_complete"], false);
        assert_eq!(result["jobs"], json!([]));
        assert!(!result.to_string().contains("CANARY"));
        assert_eq!(f.calls.load(Ordering::SeqCst), 1);
        public_job_acquire(
            &mut c,
            &v,
            PublicJobSource::Arbeitnow,
            json!({}),
            62100 + index,
        )
        .await
        .unwrap();
        assert_eq!(f.calls.load(Ordering::SeqCst), 1);
        stop.cancel();
        task.await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_job_rate_response_extends_shared_window_monotonically_and_never_refunds_original_interval()
 {
    let mut c = public_job_access_fixture().await;
    let (v, f, stop, task) = public_job_http(PublicJobSource::Arbeitnow, "rate").await;
    let result = public_job_acquire(&mut c, &v, PublicJobSource::Arbeitnow, json!({}), 62200)
        .await
        .unwrap();
    assert_eq!(result["status"], "rate_limited");
    assert_eq!(
        result["errors"],
        json!(["public_job_provider_rate_limited"])
    );
    let seconds:f64=sqlx::query_scalar("SELECT extract(epoch FROM (next_allowed_at-clock_timestamp()))::double precision FROM provider_access_windows WHERE provider='arbeitnow'").fetch_one(&mut c).await.unwrap();
    assert!(seconds > 7190.0);
    assert_eq!(
        public_job_acquire(&mut c, &v, PublicJobSource::Arbeitnow, json!({}), 62201).await,
        Err(Failure("public_job_source_rate_limited"))
    );
    assert_eq!(f.calls.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_job_duplicate_observations_deduplicate_but_conflicting_identity_is_quarantined_from_results()
 {
    for (n, mode, status, jobs, rejected) in [
        (62300, "duplicate", "success", 1, 0),
        (62301, "inconsistent", "upstream_error", 0, 2),
    ] {
        let mut c = public_job_access_fixture().await;
        let (v, _, stop, task) = public_job_http(PublicJobSource::Greenhouse, mode).await;
        let result = public_job_acquire(
            &mut c,
            &v,
            PublicJobSource::Greenhouse,
            json!({"limit":2}),
            n,
        )
        .await
        .unwrap();
        assert_eq!(result["status"], status);
        assert_eq!(result["jobs"].as_array().unwrap().len(), jobs);
        assert_eq!(result["rejected_count"], rejected);
        assert_eq!(result["duplicate_count"], 1);
        stop.cancel();
        task.await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_job_unlisted_ashby_and_foreign_smartrecruiters_postings_never_become_saved_jobs() {
    for (n, source, mode, status) in [
        (62400, PublicJobSource::Ashby, "unlisted", "no_results"),
        (
            62401,
            PublicJobSource::Smartrecruiters,
            "foreign",
            "upstream_error",
        ),
        (
            62402,
            PublicJobSource::Smartrecruiters,
            "bad_page",
            "upstream_error",
        ),
    ] {
        let mut c = public_job_access_fixture().await;
        let (v, _, stop, task) = public_job_http(source, mode).await;
        let result = public_job_acquire(&mut c, &v, source, json!({}), n)
            .await
            .unwrap();
        assert_eq!(result["status"], status);
        assert_eq!(result["jobs"], json!([]));
        stop.cancel();
        task.await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_job_untrusted_pagination_link_is_only_a_bounded_cursor_and_is_never_requested() {
    let mut c = public_job_access_fixture().await;
    let (v, f, stop, task) = public_job_http(PublicJobSource::Arbeitnow, "more").await;
    let result = public_job_acquire(&mut c, &v, PublicJobSource::Arbeitnow, json!({}), 62500)
        .await
        .unwrap();
    assert_eq!(result["next_cursor"], "2");
    assert_eq!(f.calls.load(Ordering::SeqCst), 1);
    assert!(
        f.paths
            .lock()
            .await
            .iter()
            .all(|s| !s.contains("private-fixture"))
    );
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_job_transport_holds_no_owner_mutex_and_cancellation_preserves_admission_without_dispatch_replay()
 {
    let mut c = public_job_access_fixture().await;
    let (v, f, stop, task) = public_job_http(PublicJobSource::Arbeitnow, "hold").await;
    let dispatch = tokio::spawn({
        let v = v.clone();
        async move {
            let mut c = connection().await;
            public_job_acquire(&mut c, &v, PublicJobSource::Arbeitnow, json!({}), 62600).await
        }
    });
    f.entered.notified().await;
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
    dispatch.abort();
    assert!(dispatch.await.unwrap_err().is_cancelled());
    let before = public_job_access_snapshot(&mut c).await;
    let saved = public_job_access::read(&mut c, Uuid::from_u128(62600))
        .await
        .unwrap();
    let replay = public_job_acquire(&mut c, &v, PublicJobSource::Arbeitnow, json!({}), 62600)
        .await
        .unwrap();
    assert_eq!(replay["recorded_state"], "dispatch_admitted");
    assert_eq!(replay, saved);
    assert_eq!(public_job_access_snapshot(&mut c).await, before);
    assert_eq!(f.calls.load(Ordering::SeqCst), 1);
    f.release.notify_one();
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_job_finding_ack_failure_preserves_original_unknown_intent_and_prevents_a_second_provider_batch()
 {
    let mut c = public_job_access_fixture().await;
    let (v, f, stop, task) = public_job_http(PublicJobSource::Arbeitnow, "ok").await;
    sqlx::raw_sql("CREATE FUNCTION fixture_public_job_finding() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'public_jobs:') AND NEW.value->>'state'='finding_retained' THEN RETURN NULL;END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_public_job_finding BEFORE UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_public_job_finding()").execute(&mut c).await.unwrap();
    assert_eq!(
        public_job_acquire(&mut c, &v, PublicJobSource::Arbeitnow, json!({}), 62700).await,
        Err(Failure("public_job_write_ack_failed"))
    );
    assert_eq!(f.calls.load(Ordering::SeqCst), 1);
    sqlx::raw_sql("DROP FUNCTION fixture_public_job_finding() CASCADE")
        .execute(&mut c)
        .await
        .unwrap();
    let replay = public_job_acquire(&mut c, &v, PublicJobSource::Arbeitnow, json!({}), 62700)
        .await
        .unwrap();
    assert_eq!(replay["recorded_state"], "dispatch_admitted");
    assert_eq!(f.calls.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
