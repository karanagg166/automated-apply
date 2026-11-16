//! Deferred atomic lookup preparation. No actual provider transport or dispatch permission.
use automated_apply_agents::contacts::enrichment::lookups as contact_lookups;
async fn contact_lookup_fixture() -> (PgConnection, Uuid, contacts::enrichment::Settings) {
    let (mut c, company) = enrichment_preview_fixture().await;
    sqlx::raw_sql("DROP TABLE IF EXISTS contact_provider_lookups,discovery_budget_reservations;CREATE TABLE contact_provider_lookups(id uuid PRIMARY KEY,company_id uuid NOT NULL,provider varchar(50) NOT NULL,identity_key varchar(64) NOT NULL,reservation_id varchar(100) NOT NULL UNIQUE,state varchar(50) NOT NULL,expires_at timestamptz NOT NULL,UNIQUE(company_id,provider,identity_key));CREATE TABLE discovery_budget_reservations(id varchar(100) PRIMARY KEY,provider varchar(50) NOT NULL,month varchar(7) NOT NULL,reserved numeric(16,6) NOT NULL,provider_run_id varchar(255),reported_actual numeric(16,6),state varchar(50) NOT NULL,created_at timestamptz NOT NULL)").execute(&mut c).await.unwrap();
    let values = BTreeMap::from([
        ("APOLLO_ENRICHMENT_ENABLED".into(), "true".into()),
        ("APOLLO_API_KEY".into(), "fictional-apollo-key".into()),
        ("APOLLO_CREDITS_PER_LOOKUP".into(), "2".into()),
        ("SIGNALHIRE_ENRICHMENT_ENABLED".into(), "true".into()),
        (
            "SIGNALHIRE_API_KEY".into(),
            "fictional-signalhire-key".into(),
        ),
        ("SIGNALHIRE_CREDITS_PER_LOOKUP".into(), "1".into()),
    ]);
    (
        c,
        company,
        contacts::enrichment::Settings::from_values(&values).unwrap(),
    )
}
async fn contact_lookup_run(
    c: &mut PgConnection,
    company: Uuid,
    settings: &contacts::enrichment::Settings,
    extra: Value,
) -> contact_runs::Run {
    let mut input = json!({"allow_paid":true});
    input
        .as_object_mut()
        .unwrap()
        .extend(extra.as_object().unwrap().clone());
    contact_runs::start(c, company, input, settings)
        .await
        .unwrap()
        .invocation
        .unwrap()
}
async fn contact_lookup_snapshot(c: &mut PgConnection) -> Value {
    sqlx::query_scalar("SELECT jsonb_build_object('lookups',(SELECT jsonb_agg(to_jsonb(l) ORDER BY id) FROM contact_provider_lookups l),'intents',(SELECT jsonb_object_agg(key,value) FROM owner_preferences WHERE starts_with(key,'contact_lookup:') OR starts_with(key,'cl_prior:')),'budgets',(SELECT jsonb_agg(to_jsonb(b) ORDER BY provider,month) FROM discovery_monthly_budgets b),'reservations',(SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM discovery_budget_reservations r))").fetch_one(c).await.unwrap()
}
async fn contact_lookup_prepare(
    c: &mut PgConnection,
    run: &contact_runs::Run,
    settings: &contacts::enrichment::Settings,
    name: &str,
    target: u128,
) -> Result<contact_lookups::Claim> {
    contact_lookups::prepare(
        c,
        run,
        name,
        contact_lookups::Target::Contact(Uuid::from_u128(target)),
        settings,
        &contact_settings(),
    )
    .await
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_lookup_preparation_commits_exact_claim_intent_and_budget_without_dispatch() {
    let (mut c, company, settings) = contact_lookup_fixture().await;
    let run = contact_lookup_run(&mut c, company, &settings, json!({})).await;
    let claim = contact_lookup_prepare(&mut c, &run, &settings, "apollo", 505)
        .await
        .unwrap();
    assert_eq!(claim.run_id(), run.id());
    assert_eq!(claim.provider(), "apollo");
    assert_eq!(claim.reservation().unwrap().amount(), 2);
    assert_eq!(
        claim.request()["linkedin_url"],
        "https://www.linkedin.com/in/fictional-contact-5/"
    );
    assert!(!claim.target_version().is_empty());
    let intent = browser_pref(
        &mut c,
        &format!("{}{}", contact_lookups::prefix(run.id()), claim.id()),
    )
    .await;
    assert_eq!(intent["state"], "prepared");
    assert_eq!(intent["post_admissions"], 0);
    assert_eq!(intent["dispatch_authorized"], false);
    assert_eq!(
        sqlx::query_scalar::<_, String>(
            "SELECT reserved::text FROM discovery_monthly_budgets WHERE provider='apollo'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        "2.000000"
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM contact_provider_lookups")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        1
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_lookup_repeated_preparation_or_abandoned_claim_never_reserves_twice() {
    let (mut c, company, settings) = contact_lookup_fixture().await;
    let run = contact_lookup_run(&mut c, company, &settings, json!({})).await;
    contact_lookup_prepare(&mut c, &run, &settings, "apollo", 505)
        .await
        .unwrap();
    let before = contact_lookup_snapshot(&mut c).await;
    assert_eq!(
        contact_lookup_prepare(&mut c, &run, &settings, "apollo", 505)
            .await
            .err()
            .unwrap(),
        Failure("contact_lookup_already_claimed")
    );
    assert_eq!(contact_lookup_snapshot(&mut c).await, before);
    let new_run = contact_lookup_run(&mut c, company, &settings, json!({})).await;
    assert_eq!(
        contact_lookup_prepare(&mut c, &new_run, &settings, "apollo", 505)
            .await
            .err()
            .unwrap(),
        Failure("contact_lookup_already_claimed")
    );
    assert_eq!(contact_lookup_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_lookup_unknown_failed_and_billing_uncertain_expired_claims_remain_quarantined() {
    let (mut c, company, settings) = contact_lookup_fixture().await;
    let run = contact_lookup_run(&mut c, company, &settings, json!({})).await;
    contact_lookup_prepare(&mut c, &run, &settings, "apollo", 505)
        .await
        .unwrap();
    for state in ["running", "billing_uncertain", "failed", "queued"] {
        sqlx::query("UPDATE contact_provider_lookups SET state=$1,expires_at=clock_timestamp()-interval '1 day'").bind(state).execute(&mut c).await.unwrap();
        let before = contact_lookup_snapshot(&mut c).await;
        let new_run = contact_lookup_run(&mut c, company, &settings, json!({})).await;
        assert_eq!(
            contact_lookup_prepare(&mut c, &new_run, &settings, "apollo", 505)
                .await
                .err()
                .unwrap(),
            Failure("contact_lookup_already_claimed")
        );
        assert_eq!(contact_lookup_snapshot(&mut c).await, before);
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_lookup_known_completed_expired_cache_replacement_preserves_old_claim_and_full_budget()
 {
    let (mut c, company, settings) = contact_lookup_fixture().await;
    let run = contact_lookup_run(&mut c, company, &settings, json!({})).await;
    let original = contact_lookup_prepare(&mut c, &run, &settings, "apollo", 505)
        .await
        .unwrap();
    contact_budget::finish(
        &mut c,
        original.reservation().unwrap(),
        "completed",
        Some(0),
        None,
    )
    .await
    .unwrap();
    sqlx::query("UPDATE contact_provider_lookups SET state='completed',expires_at=clock_timestamp()-interval '1 day'").execute(&mut c).await.unwrap();
    let old: Value = sqlx::query_scalar("SELECT to_jsonb(l) FROM contact_provider_lookups l")
        .fetch_one(&mut c)
        .await
        .unwrap();
    let new_run = contact_lookup_run(&mut c, company, &settings, json!({})).await;
    let replacement = contact_lookup_prepare(&mut c, &new_run, &settings, "apollo", 505)
        .await
        .unwrap();
    assert_ne!(original.id(), replacement.id());
    assert_eq!(
        sqlx::query_scalar::<_, Value>(
            "SELECT value FROM owner_preferences WHERE starts_with(key,'cl_prior:')"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        old
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM owner_preferences WHERE starts_with(key,'contact_lookup:')"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        2
    );
    assert_eq!(
        sqlx::query_scalar::<_, String>(
            "SELECT reserved::text FROM discovery_monthly_budgets WHERE provider='apollo'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        "4.000000"
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_lookup_current_policy_profile_and_role_guards_precede_credit_accounting() {
    let (mut c, company, settings) = contact_lookup_fixture().await;
    let run = contact_lookup_run(&mut c, company, &settings, json!({})).await;
    let before = contact_lookup_snapshot(&mut c).await;
    assert_eq!(
        contact_lookup_prepare(&mut c, &run, &settings, "apollo", 501)
            .await
            .err()
            .unwrap(),
        Failure("contact_lookup_not_needed")
    );
    assert_eq!(
        contact_lookup_prepare(&mut c, &run, &settings, "apollo", 503)
            .await
            .err()
            .unwrap(),
        Failure("contact_professional_identifier_required")
    );
    assert_eq!(contact_lookup_snapshot(&mut c).await, before);
    let mut input = json!({"allow_paid":false});
    let denied = contact_runs::start(&mut c, company, input.clone(), &settings)
        .await
        .unwrap()
        .invocation
        .unwrap();
    assert_eq!(
        contact_lookup_prepare(&mut c, &denied, &settings, "apollo", 505)
            .await
            .err()
            .unwrap(),
        Failure("contact_paid_lookup_authorization_required")
    );
    input = json!({"allow_paid":true,"target_roles":["recruiter"]});
    let denied = contact_runs::start(&mut c, company, input, &settings)
        .await
        .unwrap()
        .invocation
        .unwrap();
    assert_eq!(
        contact_lookup_prepare(&mut c, &denied, &settings, "apollo", 505)
            .await
            .err()
            .unwrap(),
        Failure("contact_lookup_not_needed")
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_lookup_person_limits_and_provider_order_have_no_implicit_fallback() {
    let (mut c, company, settings) = contact_lookup_fixture().await;
    let run = contact_lookup_run(
        &mut c,
        company,
        &settings,
        json!({"max_people":1,"providers":["apollo","signalhire"],"allow_fallback":true}),
    )
    .await;
    contact_lookup_prepare(&mut c, &run, &settings, "apollo", 505)
        .await
        .unwrap();
    let before = contact_lookup_snapshot(&mut c).await;
    assert_eq!(
        contact_lookup_prepare(&mut c, &run, &settings, "signalhire", 505)
            .await
            .err()
            .unwrap(),
        Failure("contact_fallback_evidence_required")
    );
    sqlx::query("UPDATE contacts SET linkedin_url='https://www.linkedin.com/in/fictional-contact-3' WHERE id=$1").bind(Uuid::from_u128(503)).execute(&mut c).await.unwrap();
    assert_eq!(
        contact_lookup_prepare(&mut c, &run, &settings, "apollo", 503)
            .await
            .err()
            .unwrap(),
        Failure("contact_run_person_limit_reached")
    );
    assert_eq!(contact_lookup_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_lookup_monthly_budget_failure_is_atomic_with_the_prepared_claim() {
    let (mut c, company, mut settings) = contact_lookup_fixture().await;
    settings.providers[0].monthly_limit = 2;
    sqlx::query("INSERT INTO discovery_monthly_budgets VALUES('apollo',to_char(clock_timestamp(),'YYYY-MM'),1,NULL)").execute(&mut c).await.unwrap();
    let run = contact_lookup_run(&mut c, company, &settings, json!({})).await;
    let before = contact_lookup_snapshot(&mut c).await;
    assert_eq!(
        contact_lookup_prepare(&mut c, &run, &settings, "apollo", 505)
            .await
            .err()
            .unwrap(),
        Failure("contact_provider_budget_exhausted")
    );
    assert_eq!(contact_lookup_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_lookup_row_ack_failure_rolls_back_already_inserted_credit_reservation() {
    let (mut c, company, settings) = contact_lookup_fixture().await;
    let run = contact_lookup_run(&mut c, company, &settings, json!({})).await;
    let before = contact_lookup_snapshot(&mut c).await;
    for behavior in [
        "RETURN NULL;",
        "NEW.identity_key:=repeat('a',64);RETURN NEW;",
    ] {
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("CREATE FUNCTION fixture_contact_lookup() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {behavior} END $$;CREATE TRIGGER fixture_contact_lookup BEFORE INSERT ON contact_provider_lookups FOR EACH ROW EXECUTE FUNCTION fixture_contact_lookup()"))).execute(&mut c).await.unwrap();
        assert_eq!(
            contact_lookup_prepare(&mut c, &run, &settings, "apollo", 505)
                .await
                .err()
                .unwrap(),
            Failure("contact_lookup_write_ack_failed")
        );
        assert_eq!(contact_lookup_snapshot(&mut c).await, before);
        sqlx::raw_sql("DROP TRIGGER fixture_contact_lookup ON contact_provider_lookups;DROP FUNCTION fixture_contact_lookup()").execute(&mut c).await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_lookup_intent_ack_failure_rolls_back_claim_month_and_reservation() {
    let (mut c, company, settings) = contact_lookup_fixture().await;
    let run = contact_lookup_run(&mut c, company, &settings, json!({})).await;
    let before = contact_lookup_snapshot(&mut c).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_contact_lookup_intent() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'contact_lookup:') THEN RETURN NULL;END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_contact_lookup_intent BEFORE INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_contact_lookup_intent()").execute(&mut c).await.unwrap();
    assert_eq!(
        contact_lookup_prepare(&mut c, &run, &settings, "apollo", 505)
            .await
            .err()
            .unwrap(),
        Failure("contact_lookup_write_ack_failed")
    );
    assert_eq!(contact_lookup_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP TRIGGER fixture_contact_lookup_intent ON owner_preferences;DROP FUNCTION fixture_contact_lookup_intent()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_lookup_zero_credit_search_requires_empty_local_inventory_and_has_no_credit_or_post_grant()
 {
    let (mut c, company, settings) = contact_lookup_fixture().await;
    let run = contact_lookup_run(&mut c, company, &settings, json!({})).await;
    assert_eq!(
        contact_lookups::prepare(
            &mut c,
            &run,
            "apollo",
            contact_lookups::Target::Search,
            &settings,
            &contact_settings()
        )
        .await
        .err()
        .unwrap(),
        Failure("contact_local_inventory_requires_review")
    );
    let empty = Uuid::from_u128(1400001);
    sqlx::query("INSERT INTO companies(id,name,domain,metadata) VALUES($1,'Fictional Empty Lookup Employer','lookup-empty.example','{}')").bind(empty).execute(&mut c).await.unwrap();
    let run = contact_lookup_run(&mut c, empty, &settings, json!({})).await;
    let claim = contact_lookups::prepare(
        &mut c,
        &run,
        "apollo",
        contact_lookups::Target::Search,
        &settings,
        &contact_settings(),
    )
    .await
    .unwrap();
    assert!(claim.reservation().is_none());
    let intent = browser_pref(
        &mut c,
        &format!("{}{}", contact_lookups::prefix(run.id()), claim.id()),
    )
    .await;
    assert_eq!(intent["estimated_cost"], 0);
    assert_eq!(intent["post_admissions"], 0);
    assert_eq!(intent["dispatch_authorized"], false);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM discovery_budget_reservations")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
}
