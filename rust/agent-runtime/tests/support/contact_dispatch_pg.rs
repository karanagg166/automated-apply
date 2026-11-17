// Deferred committed dispatch plus loopback provider evidence; no real contact/account request.
use automated_apply_agents::contacts::enrichment::{
    capabilities as contact_capabilities, dispatch as contact_dispatch,
    providers as contact_providers,
};
struct ContactProviderHttp {
    posts: std::sync::atomic::AtomicUsize,
    metadata: std::sync::atomic::AtomicUsize,
    mode: &'static str,
}
async fn contact_provider_handler(
    axum::extract::State(state): axum::extract::State<Arc<ContactProviderHttp>>,
    request: axum::extract::Request,
) -> axum::response::Response {
    use axum::response::IntoResponse as _;
    let path = request.uri().path().to_owned();
    let body = axum::body::to_bytes(request.into_body(), 65536)
        .await
        .unwrap();
    let body: Value = serde_json::from_slice(&body).unwrap_or(Value::Null);
    if path == "/people/match" {
        state
            .posts
            .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        if state.mode == "error" {
            return axum::http::StatusCode::INTERNAL_SERVER_ERROR.into_response();
        }
        return axum::Json(json!({"person":{"name":body["name"],"title":"Founder","organization":{"primary_domain":body["domain"]},"linkedin_url":body["linkedin_url"],"email":if state.mode=="no_email"{None}else{Some("person5@contact-fixture.example")},"id":"fictional-provider-person-five","email_status":"verified","phone":"PRIVATE_PROVIDER_PHONE_CANARY"}})).into_response();
    }
    state
        .metadata
        .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
    let rates = json!({"minute":{"limit":1000,"consumed":0,"left_over":1000},"hour":{"limit":1000,"consumed":0,"left_over":1000},"day":{"limit":1000,"consumed":0,"left_over":1000}});
    axum::Json(match path.as_str() {
        "/auth/health" => json!({"healthy":true,"is_logged_in":true}),
        "/usage_stats/api_usage_stats" => json!({"api/v1/people/match":rates}),
        "/usage_stats/credit_usage_stats" => {
            json!({"credit_usage_stats":{"lead_credit":{"limit":100,"consumed":0,"left_over":100}}})
        }
        _ => Value::Null,
    })
    .into_response()
}
async fn contact_provider_http(
    mode: &'static str,
) -> (
    contact_providers::Clients,
    contact_capabilities::Eligibility,
    Arc<ContactProviderHttp>,
    tokio::task::JoinHandle<()>,
) {
    let state = Arc::new(ContactProviderHttp {
        posts: std::sync::atomic::AtomicUsize::new(0),
        metadata: std::sync::atomic::AtomicUsize::new(0),
        mode,
    });
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let router = axum::Router::new()
        .fallback(contact_provider_handler)
        .with_state(state.clone());
    let task = tokio::spawn(async move {
        axum::serve(listener, router).await.unwrap();
    });
    let values = BTreeMap::from([
        ("APOLLO_ENRICHMENT_ENABLED".into(), "true".into()),
        ("APOLLO_API_KEY".into(), "fictional-provider-key".into()),
        (
            "RUST_CONTACT_APOLLO_FIXTURE_ENDPOINT".into(),
            format!("http://{address}/"),
        ),
        ("APOLLO_FREE_ACCOUNT_CONFIRMED".into(), "true".into()),
        ("APOLLO_WORK_EMAIL_CONFIRMED".into(), "true".into()),
        (
            "APOLLO_ELIGIBILITY_REVIEWED_AT".into(),
            chrono::Utc::now().to_rfc3339(),
        ),
        (
            "APOLLO_ELIGIBILITY_EVIDENCE_URL".into(),
            "https://contact-fixture.example/review".into(),
        ),
        (
            "APOLLO_REVIEWED_ENDPOINTS".into(),
            json!(["api/v1/people/match"]).to_string(),
        ),
        ("APOLLO_CREDIT_POOL".into(), "lead_credit".into()),
    ]);
    (
        contact_providers::Clients::from_values(&values, true).unwrap(),
        contact_capabilities::Eligibility::from_values(&values).unwrap(),
        state,
        task,
    )
}
async fn contact_dispatch_proof(
    client: &contact_providers::Client,
    eligibility: &contact_capabilities::Eligibility,
) -> contact_providers::LiveProof {
    client
        .introspect(contact_capabilities::Operation::Enrich, 2, eligibility)
        .await
        .unwrap()
}
async fn contact_dispatch_fixture() -> (
    PgConnection,
    contacts::enrichment::Settings,
    contact_runs::Run,
    contact_lookups::Claim,
) {
    let (mut c, company, settings) = contact_lookup_fixture().await;
    let run = contact_lookup_run(&mut c, company, &settings, json!({})).await;
    let claim = contact_lookup_prepare(&mut c, &run, &settings, "apollo", 505)
        .await
        .unwrap();
    (c, settings, run, claim)
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_dispatch_commits_one_admission_before_loopback_post_and_never_promotes_provider_mailbox_claim()
 {
    let (mut c, settings, run, claim) = contact_dispatch_fixture().await;
    let (clients, eligibility, state, task) = contact_provider_http("normal").await;
    let client = clients.get("apollo").unwrap();
    let proof = contact_dispatch_proof(client, &eligibility).await;
    let grant = contact_dispatch::authorize(
        &mut c,
        &run,
        &claim,
        proof,
        client,
        &settings,
        &contact_settings(),
    )
    .await
    .unwrap();
    assert_eq!(grant.reservation(), claim.id());
    let intent = browser_pref(
        &mut c,
        &format!("{}{}", contact_lookups::prefix(run.id()), claim.id()),
    )
    .await;
    assert_eq!(intent["post_admissions"], 1);
    assert_eq!(intent["state"], "dispatch_unknown");
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 0);
    let immutable = browser_pref(&mut c, &format!("cl_post:{}", claim.id())).await;
    assert_eq!(immutable["invocation"], grant.invocation().to_string());
    assert_eq!(immutable["admission_only"], true);
    let result = client.execute(grant).await;
    assert_eq!(result.state, "completed");
    assert_eq!(result.observations[0]["email_status"], "provider_reported");
    assert!(
        !json!(result.observations)
            .to_string()
            .contains("PRIVATE_PROVIDER_PHONE_CANARY")
    );
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 1);
    assert_eq!(state.metadata.load(std::sync::atomic::Ordering::SeqCst), 3);
    task.abort();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_dispatch_lost_grant_response_cannot_reconstruct_authority_or_repeat_post() {
    let (mut c, settings, run, claim) = contact_dispatch_fixture().await;
    let (clients, eligibility, state, task) = contact_provider_http("normal").await;
    let client = clients.get("apollo").unwrap();
    let proof = contact_dispatch_proof(client, &eligibility).await;
    let grant = contact_dispatch::authorize(
        &mut c,
        &run,
        &claim,
        proof,
        client,
        &settings,
        &contact_settings(),
    )
    .await
    .unwrap();
    drop(grant);
    let before = contact_lookup_snapshot(&mut c).await;
    let proof = contact_dispatch_proof(client, &eligibility).await;
    assert_eq!(
        contact_dispatch::authorize(
            &mut c,
            &run,
            &claim,
            proof,
            client,
            &settings,
            &contact_settings()
        )
        .await
        .err()
        .unwrap(),
        Failure("contact_lookup_dispatch_context_changed")
    );
    assert_eq!(contact_lookup_snapshot(&mut c).await, before);
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 0);
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM owner_preferences WHERE starts_with(key,'cl_post:')"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        1
    );
    task.abort();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_dispatch_changed_contact_version_requires_review_before_any_post_admission() {
    let (mut c, settings, run, claim) = contact_dispatch_fixture().await;
    let (clients, eligibility, state, task) = contact_provider_http("normal").await;
    let client = clients.get("apollo").unwrap();
    let proof = contact_dispatch_proof(client, &eligibility).await;
    sqlx::query(
        "UPDATE contacts SET human_review_notes='Fictional concurrent owner review' WHERE id=$1",
    )
    .bind(Uuid::from_u128(505))
    .execute(&mut c)
    .await
    .unwrap();
    let before = contact_lookup_snapshot(&mut c).await;
    assert_eq!(
        contact_dispatch::authorize(
            &mut c,
            &run,
            &claim,
            proof,
            client,
            &settings,
            &contact_settings()
        )
        .await
        .err()
        .unwrap(),
        Failure("contact_lookup_dispatch_context_changed")
    );
    assert_eq!(contact_lookup_snapshot(&mut c).await, before);
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 0);
    task.abort();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_dispatch_changed_run_configuration_or_company_facts_refuse_before_post() {
    let (mut c, settings, run, claim) = contact_dispatch_fixture().await;
    let (clients, eligibility, state, task) = contact_provider_http("normal").await;
    let client = clients.get("apollo").unwrap();
    let proof = contact_dispatch_proof(client, &eligibility).await;
    sqlx::query("UPDATE companies SET domain='different-contact-fixture.example' WHERE id=$1")
        .bind(run.company())
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        contact_dispatch::authorize(
            &mut c,
            &run,
            &claim,
            proof,
            client,
            &settings,
            &contact_settings()
        )
        .await
        .err()
        .unwrap(),
        Failure("contact_run_context_changed")
    );
    sqlx::query("UPDATE companies SET domain='contact-fixture.example' WHERE id=$1")
        .bind(run.company())
        .execute(&mut c)
        .await
        .unwrap();
    let mut changed = contact_provider_settings();
    changed.providers[0].lookup_cost = 3;
    let proof = contact_dispatch_proof(client, &eligibility).await;
    assert_eq!(
        contact_dispatch::authorize(
            &mut c,
            &run,
            &claim,
            proof,
            client,
            &changed,
            &contact_settings()
        )
        .await
        .err()
        .unwrap(),
        Failure("contact_run_context_changed")
    );
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 0);
    task.abort();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_dispatch_requires_reserved_credit_current_ledger_and_original_lookup_pointer() {
    let (mut c, settings, run, claim) = contact_dispatch_fixture().await;
    let (clients, eligibility, state, task) = contact_provider_http("normal").await;
    let client = clients.get("apollo").unwrap();
    for sql in [
        "UPDATE discovery_budget_reservations SET state='completed'",
        "UPDATE discovery_monthly_budgets SET reserved=0",
        "UPDATE contact_provider_lookups SET state='completed'",
    ] {
        sqlx::query(sql).execute(&mut c).await.unwrap();
        let proof = contact_dispatch_proof(client, &eligibility).await;
        assert_eq!(
            contact_dispatch::authorize(
                &mut c,
                &run,
                &claim,
                proof,
                client,
                &settings,
                &contact_settings()
            )
            .await
            .err()
            .unwrap(),
            Failure("contact_lookup_dispatch_context_changed")
        );
        sqlx::raw_sql("UPDATE discovery_budget_reservations SET state='reserved';UPDATE discovery_monthly_budgets SET reserved=2;UPDATE contact_provider_lookups SET state='running'").execute(&mut c).await.unwrap();
    }
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 0);
    task.abort();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_dispatch_intent_update_ack_failure_keeps_prepared_intent_and_credit_ledger() {
    let (mut c, settings, run, claim) = contact_dispatch_fixture().await;
    let (clients, eligibility, state, task) = contact_provider_http("normal").await;
    let client = clients.get("apollo").unwrap();
    let before = contact_lookup_snapshot(&mut c).await;
    for behavior in [
        "RETURN NULL;",
        "NEW.value:=jsonb_set(NEW.value::jsonb,'{post_admissions}','2');RETURN NEW;",
    ] {
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("CREATE FUNCTION fixture_contact_dispatch() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'contact_lookup:') THEN {behavior} END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_contact_dispatch BEFORE UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_contact_dispatch()"))).execute(&mut c).await.unwrap();
        let proof = contact_dispatch_proof(client, &eligibility).await;
        assert_eq!(
            contact_dispatch::authorize(
                &mut c,
                &run,
                &claim,
                proof,
                client,
                &settings,
                &contact_settings()
            )
            .await
            .err()
            .unwrap(),
            Failure("contact_lookup_write_ack_failed")
        );
        assert_eq!(contact_lookup_snapshot(&mut c).await, before);
        sqlx::raw_sql("DROP TRIGGER fixture_contact_dispatch ON owner_preferences;DROP FUNCTION fixture_contact_dispatch()").execute(&mut c).await.unwrap();
    }
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM owner_preferences WHERE starts_with(key,'cl_post:')"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        0
    );
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 0);
    task.abort();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_dispatch_immutable_post_ack_failure_rolls_back_admission_and_preserves_private_owner_json()
 {
    let (mut c, settings, run, claim) = contact_dispatch_fixture().await;
    let (clients, eligibility, state, task) = contact_provider_http("normal").await;
    let client = clients.get("apollo").unwrap();
    let before = contact_lookup_snapshot(&mut c).await;
    let owner = browser_snapshot(&mut c).await;
    for behavior in ["RETURN NULL;", "NEW.value:='{}';RETURN NEW;"] {
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("CREATE FUNCTION fixture_contact_dispatch_post() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'cl_post:') THEN {behavior} END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_contact_dispatch_post BEFORE INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_contact_dispatch_post()"))).execute(&mut c).await.unwrap();
        let proof = contact_dispatch_proof(client, &eligibility).await;
        assert_eq!(
            contact_dispatch::authorize(
                &mut c,
                &run,
                &claim,
                proof,
                client,
                &settings,
                &contact_settings()
            )
            .await
            .err()
            .unwrap(),
            Failure("contact_lookup_write_ack_failed")
        );
        assert_eq!(contact_lookup_snapshot(&mut c).await, before);
        assert_eq!(browser_snapshot(&mut c).await, owner);
        sqlx::raw_sql("DROP TRIGGER fixture_contact_dispatch_post ON owner_preferences;DROP FUNCTION fixture_contact_dispatch_post()").execute(&mut c).await.unwrap();
    }
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 0);
    task.abort();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_dispatch_unconfirmed_provider_post_retains_admission_and_never_receives_another_grant()
 {
    let (mut c, settings, run, claim) = contact_dispatch_fixture().await;
    let (clients, eligibility, state, task) = contact_provider_http("error").await;
    let client = clients.get("apollo").unwrap();
    let proof = contact_dispatch_proof(client, &eligibility).await;
    let grant = contact_dispatch::authorize(
        &mut c,
        &run,
        &claim,
        proof,
        client,
        &settings,
        &contact_settings(),
    )
    .await
    .unwrap();
    let outcome = client.execute(grant).await;
    assert_eq!(outcome.state, "billing_uncertain");
    assert!(outcome.outcome_unknown);
    let proof = contact_dispatch_proof(client, &eligibility).await;
    assert_eq!(
        contact_dispatch::authorize(
            &mut c,
            &run,
            &claim,
            proof,
            client,
            &settings,
            &contact_settings()
        )
        .await
        .err()
        .unwrap(),
        Failure("contact_lookup_dispatch_context_changed")
    );
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 1);
    assert_eq!(
        sqlx::query_scalar::<_, String>(
            "SELECT reserved::text FROM discovery_monthly_budgets WHERE provider='apollo'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        "2.000000"
    );
    task.abort();
}
