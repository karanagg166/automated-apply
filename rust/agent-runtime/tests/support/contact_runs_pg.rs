//! Deferred local run/invocation fixtures. No run grants provider dispatch.
use automated_apply_agents::contacts::enrichment::runs as contact_runs;
async fn contact_run_start(
    c: &mut PgConnection,
    company: Uuid,
    input: Value,
) -> Result<contact_runs::Start> {
    contact_runs::start(c, company, input, &contact_provider_settings()).await
}
async fn contact_run_snapshot(c: &mut PgConnection) -> Value {
    sqlx::query_scalar("SELECT jsonb_build_object('runs',(SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM contact_enrichment_runs r),'journals',(SELECT jsonb_object_agg(key,value) FROM owner_preferences WHERE starts_with(key,'contact_run:')))").fetch_one(c).await.unwrap()
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_run_start_is_atomic_and_keeps_private_authority_out_of_public_history() {
    let (mut c, company) = enrichment_preview_fixture().await;
    let started = contact_run_start(
        &mut c,
        company,
        json!({"idempotency_key":"fictional_run","allow_paid":true}),
    )
    .await
    .unwrap();
    let run = started.invocation.unwrap();
    assert_eq!(started.record["state"], "running");
    assert_eq!(started.record["live_verified"], false);
    assert!(started.record.get("request_hash").is_none());
    assert!(started.record.get("idempotency_key").is_none());
    assert!(!started.record.to_string().contains("token_hash"));
    assert_eq!(
        contact_runs::check(&mut c, &run, &contact_provider_settings())
            .await
            .unwrap()["id"],
        company.to_string()
    );
    assert_eq!(run.company(), company);
    assert_eq!(run.input()["allow_paid"], true);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM discovery_monthly_budgets")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    let journal = browser_pref(&mut c, &format!("contact_run:{}", run.id().simple())).await;
    assert_eq!(
        journal["authority"],
        "same_process_original_invocation_only"
    );
    assert_eq!(journal["input"]["idempotency_key"], "fictional_run");
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_run_idempotency_replay_never_restores_invocation_or_renews_deadline() {
    let (mut c, company) = enrichment_preview_fixture().await;
    let input = json!({"idempotency_key":"fictional_run_replay"});
    let started = contact_run_start(&mut c, company, input.clone())
        .await
        .unwrap();
    let run = started.invocation.unwrap();
    let before = contact_run_snapshot(&mut c).await;
    for _ in 0..2 {
        let retained = contact_run_start(&mut c, company, input.clone())
            .await
            .unwrap();
        assert!(retained.invocation.is_none());
        assert_eq!(retained.record["id"], run.id().to_string());
        assert_eq!(retained.record["invocation_resumed"], false);
    }
    assert_eq!(contact_run_snapshot(&mut c).await, before);
    assert_eq!(
        contact_run_start(
            &mut c,
            company,
            json!({"idempotency_key":"fictional_run_replay","allow_paid":true})
        )
        .await
        .err()
        .unwrap(),
        Failure("contact_run_idempotency_conflict")
    );
    assert_eq!(contact_run_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_run_legacy_idempotency_returns_qualified_history_without_native_journal_or_authority()
 {
    let (mut c, company) = enrichment_preview_fixture().await;
    let id = Uuid::from_u128(1300001);
    let input = json!({"idempotency_key":"fictional_legacy_run"});
    let hash = contact_runs::request_hash(company, &input).unwrap();
    sqlx::query("INSERT INTO contact_enrichment_runs VALUES($1,$2,$3,'[]','[\"apollo\"]','billing_uncertain','[]','{}','[]','[\"PRIVATE_LEGACY_ERROR_CANARY\"]',clock_timestamp(),NULL,'fictional_legacy_run')").bind(id).bind(company).bind(hash).execute(&mut c).await.unwrap();
    let retained = contact_run_start(&mut c, company, input).await.unwrap();
    assert!(retained.invocation.is_none());
    assert_eq!(retained.record["state"], "billing_uncertain");
    assert!(!retained.record.to_string().contains("PRIVATE_"));
    assert!(retained.record.get("request_hash").is_none());
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM owner_preferences WHERE starts_with(key,'contact_run:')"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        0
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_run_exact_lease_and_company_configuration_facts_cannot_be_rebound_or_renewed() {
    let (mut c, company) = enrichment_preview_fixture().await;
    let run = contact_run_start(&mut c, company, json!({}))
        .await
        .unwrap()
        .invocation
        .unwrap();
    let journal_key = format!("contact_run:{}", run.id().simple());
    let original = browser_pref(&mut c, &journal_key).await;
    for field in [
        "lease_until",
        "started_at",
        "token_hash",
        "company_snapshot",
        "request_hash",
    ] {
        let mut changed = original.clone();
        changed[field] = match field {
            "lease_until" => json!("2099-01-01T00:00:00Z"),
            "started_at" => json!("2000-01-01T00:00:00Z"),
            "company_snapshot" => json!({}),
            _ => json!("altered"),
        };
        browser_save(&mut c, &journal_key, changed).await;
        assert_eq!(
            contact_runs::check(&mut c, &run, &contact_provider_settings())
                .await
                .unwrap_err(),
            Failure("contact_run_context_changed")
        );
    }
    browser_save(&mut c, &journal_key, original).await;
    sqlx::query("UPDATE companies SET domain='changed-contact-fixture.example' WHERE id=$1")
        .bind(company)
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        contact_runs::check(&mut c, &run, &contact_provider_settings())
            .await
            .unwrap_err(),
        Failure("contact_run_context_changed")
    );
    sqlx::query("UPDATE companies SET domain='contact-fixture.example' WHERE id=$1")
        .bind(company)
        .execute(&mut c)
        .await
        .unwrap();
    let mut settings = contact_provider_settings();
    settings.providers[0].lookup_cost = 3;
    assert_eq!(
        contact_runs::check(&mut c, &run, &settings)
            .await
            .unwrap_err(),
        Failure("contact_run_context_changed")
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_run_altered_or_suppressed_insert_ack_rolls_back_journal_and_run() {
    let (mut c, company) = enrichment_preview_fixture().await;
    let before = contact_run_snapshot(&mut c).await;
    for behavior in ["RETURN NULL;", "NEW.state:='completed';RETURN NEW;"] {
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("CREATE FUNCTION fixture_contact_run() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {behavior} END $$;CREATE TRIGGER fixture_contact_run BEFORE INSERT ON contact_enrichment_runs FOR EACH ROW EXECUTE FUNCTION fixture_contact_run()"))).execute(&mut c).await.unwrap();
        assert_eq!(
            contact_run_start(&mut c, company, json!({}))
                .await
                .err()
                .unwrap(),
            Failure("contact_run_write_ack_failed")
        );
        assert_eq!(contact_run_snapshot(&mut c).await, before);
        sqlx::raw_sql("DROP TRIGGER fixture_contact_run ON contact_enrichment_runs;DROP FUNCTION fixture_contact_run()").execute(&mut c).await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_run_journal_ack_failure_rolls_back_saved_run_without_disturbing_conversation() {
    let (mut c, company) = enrichment_preview_fixture().await;
    let before = contact_run_snapshot(&mut c).await;
    let owner = browser_snapshot(&mut c).await;
    for behavior in ["RETURN NULL;", "NEW.value:='{}';RETURN NEW;"] {
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("CREATE FUNCTION fixture_contact_run_journal() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'contact_run:') THEN {behavior} END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_contact_run_journal BEFORE INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_contact_run_journal()"))).execute(&mut c).await.unwrap();
        assert_eq!(
            contact_run_start(&mut c, company, json!({}))
                .await
                .err()
                .unwrap(),
            Failure("contact_run_write_ack_failed")
        );
        assert_eq!(contact_run_snapshot(&mut c).await, before);
        assert_eq!(browser_snapshot(&mut c).await, owner);
        sqlx::raw_sql("DROP TRIGGER fixture_contact_run_journal ON owner_preferences;DROP FUNCTION fixture_contact_run_journal()").execute(&mut c).await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_run_stale_state_or_oversized_idempotency_payload_cannot_create_a_new_invocation() {
    let (mut c, company) = enrichment_preview_fixture().await;
    let input = json!({"idempotency_key":"fictional_stale_run"});
    let run = contact_run_start(&mut c, company, input.clone())
        .await
        .unwrap()
        .invocation
        .unwrap();
    sqlx::query("UPDATE contact_enrichment_runs SET state='completed' WHERE id=$1")
        .bind(run.id())
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        contact_runs::check(&mut c, &run, &contact_provider_settings())
            .await
            .unwrap_err(),
        Failure("contact_run_context_changed")
    );
    sqlx::query("UPDATE contact_enrichment_runs SET target_roles=$2 WHERE id=$1")
        .bind(run.id())
        .bind(json!(["x".repeat(300001)]))
        .execute(&mut c)
        .await
        .unwrap();
    let before = contact_run_snapshot(&mut c).await;
    assert_eq!(
        contact_run_start(&mut c, company, input)
            .await
            .err()
            .unwrap(),
        Failure("invalid_contact_saved_record")
    );
    assert_eq!(contact_run_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_run_same_idempotency_concurrency_can_create_only_one_journal_and_run() {
    let (mut c, company) = enrichment_preview_fixture().await;
    let mut other = connection().await;
    let input = json!({"idempotency_key":"fictional_parallel_run"});
    let (a, b) = tokio::join!(
        contact_run_start(&mut c, company, input.clone()),
        contact_run_start(&mut other, company, input)
    );
    let count = usize::from(a.as_ref().is_ok_and(|s| s.invocation.is_some()))
        + usize::from(b.as_ref().is_ok_and(|s| s.invocation.is_some()));
    assert_eq!(count, 1);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM contact_enrichment_runs")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        1
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM owner_preferences WHERE starts_with(key,'contact_run:')"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        1
    );
}
