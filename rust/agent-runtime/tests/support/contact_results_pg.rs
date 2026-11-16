//! Deferred actual admission/loopback/result/identity fixtures; no provider account is accessed.
use automated_apply_agents::contacts::enrichment::results as contact_results;
async fn contact_result_fixture(
    mode: &'static str,
) -> (
    PgConnection,
    contacts::enrichment::Settings,
    contact_runs::Run,
    contact_lookups::Claim,
    contact_providers::Outcome,
    Arc<ContactProviderHttp>,
    tokio::task::JoinHandle<()>,
) {
    let (mut c, settings, run, claim) = if mode == "no_email" {
        let (mut c, company, settings) = contact_lookup_fixture().await;
        sqlx::query("UPDATE contacts SET email=NULL,email_status='unknown',last_verified_at=NULL WHERE id=$1").bind(Uuid::from_u128(505)).execute(&mut c).await.unwrap();
        let run = contact_lookup_run(
            &mut c,
            company,
            &settings,
            json!({"providers":["apollo","signalhire"],"allow_fallback":true}),
        )
        .await;
        let claim = contact_lookup_prepare(&mut c, &run, &settings, "apollo", 505)
            .await
            .unwrap();
        (c, settings, run, claim)
    } else {
        contact_dispatch_fixture().await
    };
    sqlx::raw_sql("CREATE TABLE contact_identities(id uuid PRIMARY KEY,company_id uuid NOT NULL,contact_id uuid NOT NULL,namespace varchar(100) NOT NULL,identity_key varchar(2048) NOT NULL,discovered_person_id uuid,UNIQUE(company_id,namespace,identity_key))").execute(&mut c).await.unwrap();
    let (clients, eligibility, state, task) = contact_provider_http(mode).await;
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
    (c, settings, run, claim, outcome, state, task)
}
async fn contact_result_snapshot(c: &mut PgConnection) -> Value {
    sqlx::query_scalar("SELECT jsonb_build_object('contacts',(SELECT jsonb_agg(to_jsonb(c) ORDER BY id) FROM contacts c),'identities',(SELECT jsonb_agg(to_jsonb(i) ORDER BY id) FROM contact_identities i),'evidence',(SELECT jsonb_agg(to_jsonb(e) ORDER BY id) FROM contact_evidence e),'lookups',(SELECT jsonb_agg(to_jsonb(l) ORDER BY id) FROM contact_provider_lookups l),'budgets',(SELECT jsonb_agg(to_jsonb(b) ORDER BY provider,month) FROM discovery_monthly_budgets b),'reservations',(SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM discovery_budget_reservations r),'runs',(SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM contact_enrichment_runs r),'journals',(SELECT jsonb_object_agg(key,value) FROM owner_preferences WHERE starts_with(key,'contact_lookup:') OR starts_with(key,'cl_result:') OR starts_with(key,'cl_ingest:') OR starts_with(key,'cl_obs:')))").fetch_one(c).await.unwrap()
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_result_record_commits_finding_budget_and_usage_before_identity_ingestion() {
    let (mut c, settings, run, claim, outcome, state, task) =
        contact_result_fixture("normal").await;
    let before = contact_identity_row(&mut c, Uuid::from_u128(505)).await;
    let result = contact_results::record(&mut c, &run, &claim, &outcome)
        .await
        .unwrap();
    assert_eq!(result["state"], "completed");
    assert_eq!(result["identity_ingested"], false);
    assert_eq!(
        contact_identity_row(&mut c, Uuid::from_u128(505)).await,
        before
    );
    assert_eq!(
        sqlx::query_scalar::<_, String>("SELECT state FROM discovery_budget_reservations")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        "completed"
    );
    assert_eq!(
        sqlx::query_scalar::<_, String>(
            "SELECT reserved::text FROM discovery_monthly_budgets WHERE provider='apollo'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        "2.000000"
    );
    let finding = contact_results::ingest(&mut c, &run, &claim, &settings, &contact_settings())
        .await
        .unwrap();
    assert_eq!(finding["usable_profile_result"], true);
    assert_eq!(finding["missing_business_email"], false);
    assert!(finding["held_reason"].is_null());
    assert_eq!(
        finding["findings"][0]["contact_id"],
        Uuid::from_u128(505).to_string()
    );
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 1);
    task.abort();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_result_same_outcome_and_ingestion_replay_do_not_append_usage_or_refresh_identity()
{
    let (mut c, settings, run, claim, outcome, state, task) =
        contact_result_fixture("normal").await;
    contact_results::record(&mut c, &run, &claim, &outcome)
        .await
        .unwrap();
    let finding = contact_results::ingest(&mut c, &run, &claim, &settings, &contact_settings())
        .await
        .unwrap();
    let before = contact_result_snapshot(&mut c).await;
    contact_results::record(&mut c, &run, &claim, &outcome)
        .await
        .unwrap();
    assert_eq!(
        contact_results::ingest(&mut c, &run, &claim, &settings, &contact_settings())
            .await
            .unwrap(),
        finding
    );
    assert_eq!(contact_result_snapshot(&mut c).await, before);
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT jsonb_array_length(usage)::bigint FROM contact_enrichment_runs"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        1
    );
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 1);
    task.abort();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_result_mutated_transport_outcome_cannot_change_bound_findings_or_mailbox_status() {
    let (mut c, _, run, claim, mut outcome, state, task) = contact_result_fixture("normal").await;
    let before = contact_result_snapshot(&mut c).await;
    outcome.observations[0]["email_status"] = json!("verified");
    assert_eq!(
        contact_results::record(&mut c, &run, &claim, &outcome)
            .await
            .unwrap_err(),
        Failure("contact_provider_result_changed")
    );
    assert_eq!(contact_result_snapshot(&mut c).await, before);
    outcome.observations[0]["email_status"] = json!("provider_reported");
    outcome.state = "not_found";
    assert_eq!(
        contact_results::record(&mut c, &run, &claim, &outcome)
            .await
            .unwrap_err(),
        Failure("contact_provider_result_changed")
    );
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 1);
    task.abort();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_result_changed_contact_is_held_after_remote_finding_without_losing_accounting() {
    let (mut c, settings, run, claim, outcome, state, task) =
        contact_result_fixture("normal").await;
    sqlx::query(
        "UPDATE contacts SET human_corrected=true,role_title='Owner retained role' WHERE id=$1",
    )
    .bind(Uuid::from_u128(505))
    .execute(&mut c)
    .await
    .unwrap();
    let before = contact_identity_row(&mut c, Uuid::from_u128(505)).await;
    contact_results::record(&mut c, &run, &claim, &outcome)
        .await
        .unwrap();
    let finding = contact_results::ingest(&mut c, &run, &claim, &settings, &contact_settings())
        .await
        .unwrap();
    assert_eq!(
        finding["held_reason"],
        "contact_result_target_changed_requires_review"
    );
    assert_eq!(finding["usable_profile_result"], false);
    assert_eq!(
        contact_identity_row(&mut c, Uuid::from_u128(505)).await,
        before
    );
    assert_eq!(
        sqlx::query_scalar::<_, String>("SELECT state FROM discovery_budget_reservations")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        "completed"
    );
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 1);
    task.abort();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_result_expired_or_changed_run_can_retain_remote_outcome_but_cannot_mutate_facts() {
    let (mut c, settings, run, claim, outcome, state, task) =
        contact_result_fixture("normal").await;
    let key = format!("contact_run:{}", run.id().simple());
    let mut journal = browser_pref(&mut c, &key).await;
    journal["lease_until"] = json!("2000-01-01T00:00:00Z");
    browser_save(&mut c, &key, journal).await;
    let before = contact_identity_row(&mut c, Uuid::from_u128(505)).await;
    contact_results::record(&mut c, &run, &claim, &outcome)
        .await
        .unwrap();
    let finding = contact_results::ingest(&mut c, &run, &claim, &settings, &contact_settings())
        .await
        .unwrap();
    assert_eq!(
        finding["held_reason"],
        "contact_result_context_requires_review"
    );
    assert_eq!(
        contact_identity_row(&mut c, Uuid::from_u128(505)).await,
        before
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM owner_preferences WHERE starts_with(key,'cl_result:')"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        1
    );
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 1);
    task.abort();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_result_unknown_post_preserves_full_reservation_and_has_no_usable_fallback() {
    let (mut c, settings, run, claim, outcome, state, task) = contact_result_fixture("error").await;
    let before = contact_identity_row(&mut c, Uuid::from_u128(505)).await;
    let result = contact_results::record(&mut c, &run, &claim, &outcome)
        .await
        .unwrap();
    assert_eq!(result["state"], "billing_uncertain");
    assert_eq!(result["outcome_unknown"], true);
    let finding = contact_results::ingest(&mut c, &run, &claim, &settings, &contact_settings())
        .await
        .unwrap();
    assert_eq!(finding["usable_profile_result"], false);
    assert_eq!(finding["missing_business_email"], false);
    assert_eq!(
        contact_identity_row(&mut c, Uuid::from_u128(505)).await,
        before
    );
    assert_eq!(
        sqlx::query_scalar::<_, String>("SELECT state FROM discovery_budget_reservations")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        "billing_uncertain"
    );
    assert_eq!(
        sqlx::query_scalar::<_, String>("SELECT reserved::text FROM discovery_monthly_budgets")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        "2.000000"
    );
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 1);
    task.abort();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_result_missing_or_mismatched_immutable_post_cannot_publish_or_finish_budget() {
    let (mut c, _, run, claim, outcome, state, task) = contact_result_fixture("normal").await;
    let key = format!("cl_post:{}", claim.id());
    let original = browser_pref(&mut c, &key).await;
    let mut altered = original;
    altered["invocation"] = json!(Uuid::new_v4());
    browser_save(&mut c, &key, altered).await;
    let before = contact_result_snapshot(&mut c).await;
    assert_eq!(
        contact_results::record(&mut c, &run, &claim, &outcome)
            .await
            .unwrap_err(),
        Failure("contact_provider_result_context_changed")
    );
    assert_eq!(contact_result_snapshot(&mut c).await, before);
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 1);
    task.abort();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_result_immutable_result_ack_failure_rolls_back_usage_and_budget_finding() {
    let (mut c, _, run, claim, outcome, state, task) = contact_result_fixture("normal").await;
    let before = contact_result_snapshot(&mut c).await;
    for behavior in ["RETURN NULL;", "NEW.value:='{}';RETURN NEW;"] {
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("CREATE FUNCTION fixture_contact_result() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'cl_result:') THEN {behavior} END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_contact_result BEFORE INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_contact_result()"))).execute(&mut c).await.unwrap();
        assert_eq!(
            contact_results::record(&mut c, &run, &claim, &outcome)
                .await
                .unwrap_err(),
            Failure("contact_provider_result_write_ack_failed")
        );
        assert_eq!(contact_result_snapshot(&mut c).await, before);
        sqlx::raw_sql("DROP TRIGGER fixture_contact_result ON owner_preferences;DROP FUNCTION fixture_contact_result()").execute(&mut c).await.unwrap();
    }
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 1);
    task.abort();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_result_lookup_full_ack_detects_expiry_mutation_and_rolls_back_result() {
    let (mut c, _, run, claim, outcome, state, task) = contact_result_fixture("normal").await;
    let before = contact_result_snapshot(&mut c).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_contact_result_lookup() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.expires_at:=clock_timestamp()+interval '1000 days';RETURN NEW;END $$;CREATE TRIGGER fixture_contact_result_lookup BEFORE UPDATE ON contact_provider_lookups FOR EACH ROW EXECUTE FUNCTION fixture_contact_result_lookup()").execute(&mut c).await.unwrap();
    assert_eq!(
        contact_results::record(&mut c, &run, &claim, &outcome)
            .await
            .unwrap_err(),
        Failure("contact_provider_result_write_ack_failed")
    );
    assert_eq!(contact_result_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP TRIGGER fixture_contact_result_lookup ON contact_provider_lookups;DROP FUNCTION fixture_contact_result_lookup()").execute(&mut c).await.unwrap();
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 1);
    task.abort();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_result_usage_or_budget_finish_ack_failure_preserves_original_dispatch_unknown() {
    let (mut c, _, run, claim, outcome, state, task) = contact_result_fixture("normal").await;
    let before = contact_result_snapshot(&mut c).await;
    for (table, behavior, expected) in [
        (
            "contact_enrichment_runs",
            "RETURN NULL;",
            "contact_provider_result_write_ack_failed",
        ),
        (
            "discovery_budget_reservations",
            "NEW.reserved:=0;RETURN NEW;",
            "contact_budget_write_ack_failed",
        ),
    ] {
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("CREATE FUNCTION fixture_contact_result_usage() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {behavior} END $$;CREATE TRIGGER fixture_contact_result_usage BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION fixture_contact_result_usage()"))).execute(&mut c).await.unwrap();
        assert_eq!(
            contact_results::record(&mut c, &run, &claim, &outcome)
                .await
                .unwrap_err()
                .0,
            expected
        );
        assert_eq!(contact_result_snapshot(&mut c).await, before);
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("DROP TRIGGER fixture_contact_result_usage ON {table};DROP FUNCTION fixture_contact_result_usage()"))).execute(&mut c).await.unwrap();
    }
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 1);
    task.abort();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_result_identity_write_failure_cannot_erase_already_committed_remote_finding() {
    let (mut c, settings, run, claim, outcome, state, task) =
        contact_result_fixture("normal").await;
    contact_results::record(&mut c, &run, &claim, &outcome)
        .await
        .unwrap();
    let before = contact_result_snapshot(&mut c).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_contact_result_identity() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NULL;END $$;CREATE TRIGGER fixture_contact_result_identity BEFORE INSERT ON contact_evidence FOR EACH ROW EXECUTE FUNCTION fixture_contact_result_identity()").execute(&mut c).await.unwrap();
    assert_eq!(
        contact_results::ingest(&mut c, &run, &claim, &settings, &contact_settings())
            .await
            .unwrap_err(),
        Failure("contact_identity_write_ack_failed")
    );
    assert_eq!(contact_result_snapshot(&mut c).await, before);
    assert_eq!(
        sqlx::query_scalar::<_, String>("SELECT state FROM discovery_budget_reservations")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        "completed"
    );
    sqlx::raw_sql("DROP TRIGGER fixture_contact_result_identity ON contact_evidence;DROP FUNCTION fixture_contact_result_identity()").execute(&mut c).await.unwrap();
    let finding = contact_results::ingest(&mut c, &run, &claim, &settings, &contact_settings())
        .await
        .unwrap();
    assert_eq!(finding["usable_profile_result"], true);
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 1);
    task.abort();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_result_ingestion_receipt_ack_failure_rolls_back_identity_only_and_keeps_result() {
    let (mut c, settings, run, claim, outcome, state, task) =
        contact_result_fixture("normal").await;
    contact_results::record(&mut c, &run, &claim, &outcome)
        .await
        .unwrap();
    let before = contact_result_snapshot(&mut c).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_contact_ingest_receipt() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'cl_ingest:') THEN RETURN NULL;END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_contact_ingest_receipt BEFORE INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_contact_ingest_receipt()").execute(&mut c).await.unwrap();
    assert_eq!(
        contact_results::ingest(&mut c, &run, &claim, &settings, &contact_settings())
            .await
            .unwrap_err(),
        Failure("contact_provider_result_write_ack_failed")
    );
    assert_eq!(contact_result_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP TRIGGER fixture_contact_ingest_receipt ON owner_preferences;DROP FUNCTION fixture_contact_ingest_receipt()").execute(&mut c).await.unwrap();
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 1);
    task.abort();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_result_only_completed_reconciled_no_email_profile_can_justify_reviewed_fallback() {
    let (mut c, settings, run, claim, outcome, state, task) =
        contact_result_fixture("no_email").await;
    contact_results::record(&mut c, &run, &claim, &outcome)
        .await
        .unwrap();
    assert_eq!(
        contact_lookup_prepare(&mut c, &run, &settings, "signalhire", 505)
            .await
            .err()
            .unwrap(),
        Failure("contact_fallback_evidence_required")
    );
    let finding = contact_results::ingest(&mut c, &run, &claim, &settings, &contact_settings())
        .await
        .unwrap();
    assert_eq!(finding["usable_profile_result"], true);
    assert_eq!(finding["missing_business_email"], true);
    let fallback = contact_lookup_prepare(&mut c, &run, &settings, "signalhire", 505)
        .await
        .unwrap();
    assert_eq!(fallback.reservation().unwrap().amount(), 1);
    let intent = browser_pref(
        &mut c,
        &format!("{}{}", contact_lookups::prefix(run.id()), fallback.id()),
    )
    .await;
    assert_eq!(intent["fallback"], true);
    assert_eq!(intent["post_admissions"], 0);
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 1);
    task.abort();
}
