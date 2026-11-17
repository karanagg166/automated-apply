// Deferred local-first owner orchestration and loopback provider acceptance fixtures.
use automated_apply_agents::contacts::enrichment::{
    controller as contact_controller, local as contact_local,
};
async fn contact_controller_schema(c: &mut PgConnection) {
    sqlx::raw_sql("CREATE TABLE contact_identities(id uuid PRIMARY KEY,company_id uuid NOT NULL,contact_id uuid NOT NULL,namespace varchar(100) NOT NULL,identity_key varchar(2048) NOT NULL,discovered_person_id uuid,UNIQUE(company_id,namespace,identity_key))").execute(c).await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_controller_local_only_uses_saved_evidence_and_creates_no_provider_or_credit_intents()
 {
    let (mut c, company) = enrichment_preview_fixture().await;
    contact_controller_schema(&mut c).await;
    let settings = contact_provider_settings();
    let clients = contact_providers::Clients::from_values(&BTreeMap::new(), true).unwrap();
    let eligibility = contact_capabilities::Eligibility::from_values(&BTreeMap::new()).unwrap();
    let service = contact_controller::Service {
        settings: &settings,
        contacts: &contact_settings(),
        clients: &clients,
        eligibility: &eligibility,
    };
    let result=service.enrich(&mut c,company,json!({"allow_paid":false,"max_people":10,"idempotency_key":"fictional_local_controller"})).await.unwrap();
    assert_eq!(result["state"], "completed");
    assert_eq!(result["counts"]["outbound_messages_sent"], 0);
    assert!(result["counts"]["contacts"].as_u64().unwrap() >= 5);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM discovery_monthly_budgets")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'contact_lookup:') OR starts_with(key,'cl_post:')").fetch_one(&mut c).await.unwrap(),0);
    let before = contact_identity_snapshot(&mut c).await;
    let replay=service.enrich(&mut c,company,json!({"allow_paid":false,"max_people":10,"idempotency_key":"fictional_local_controller"})).await.unwrap();
    assert_eq!(replay["id"], result["id"]);
    assert_eq!(contact_identity_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_controller_cached_contact_skips_provider_validation_even_when_paid_option_was_selected()
 {
    let (mut c, company) = enrichment_preview_fixture().await;
    contact_controller_schema(&mut c).await;
    let settings = contact_provider_settings();
    let clients = contact_providers::Clients::from_values(&BTreeMap::new(), true).unwrap();
    let eligibility = contact_capabilities::Eligibility::from_values(&BTreeMap::new()).unwrap();
    let service = contact_controller::Service {
        settings: &settings,
        contacts: &contact_settings(),
        clients: &clients,
        eligibility: &eligibility,
    };
    let result = service
        .enrich(
            &mut c,
            company,
            json!({"allow_paid":true,"target_roles":["recruiter"],"max_people":1}),
        )
        .await
        .unwrap();
    assert_eq!(result["state"], "completed");
    assert_eq!(result["contact_ids"], json!([Uuid::from_u128(502)]));
    assert_eq!(result["usage"], json!([]));
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_controller_provider_admission_result_identity_and_history_work_together_on_loopback()
 {
    let (mut c, company, settings) = contact_lookup_fixture().await;
    contact_controller_schema(&mut c).await;
    let (clients, eligibility, state, task) = contact_provider_http("normal").await;
    let service = contact_controller::Service {
        settings: &settings,
        contacts: &contact_settings(),
        clients: &clients,
        eligibility: &eligibility,
    };
    let input = json!({"allow_paid":true,"target_roles":["founder"],"max_people":1,"idempotency_key":"fictional_complete_controller"});
    let result = service
        .enrich(&mut c, company, input.clone())
        .await
        .unwrap();
    assert_eq!(result["state"], "completed");
    assert_eq!(result["contact_ids"], json!([Uuid::from_u128(505)]));
    assert_eq!(result["usage"].as_array().unwrap().len(), 1);
    assert_eq!(result["usage"][0]["reserved_estimate"], 2);
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 1);
    assert_eq!(state.metadata.load(std::sync::atomic::Ordering::SeqCst), 3);
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM owner_preferences WHERE starts_with(key,'cl_finish:')"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        1
    );
    let before = contact_result_snapshot(&mut c).await;
    assert_eq!(
        service.enrich(&mut c, company, input).await.unwrap()["id"],
        result["id"]
    );
    assert_eq!(contact_result_snapshot(&mut c).await, before);
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 1);
    assert!(!result.to_string().contains("PRIVATE_PROVIDER_PHONE_CANARY"));
    task.abort();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_controller_unknown_provider_result_finishes_qualified_history_without_replay_or_refund()
 {
    let (mut c, company, settings) = contact_lookup_fixture().await;
    contact_controller_schema(&mut c).await;
    let (clients, eligibility, state, task) = contact_provider_http("error").await;
    let service = contact_controller::Service {
        settings: &settings,
        contacts: &contact_settings(),
        clients: &clients,
        eligibility: &eligibility,
    };
    let input = json!({"allow_paid":true,"target_roles":["founder"],"max_people":1,"idempotency_key":"fictional_unknown_controller"});
    let result = service
        .enrich(&mut c, company, input.clone())
        .await
        .unwrap();
    assert_eq!(result["state"], "billing_uncertain");
    assert_eq!(result["counts"]["outbound_messages_sent"], 0);
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
        service.enrich(&mut c, company, input).await.unwrap()["state"],
        "billing_uncertain"
    );
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 1);
    task.abort();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_controller_missing_credentials_returns_qualified_run_without_claims_or_budget() {
    let (mut c, company) = enrichment_preview_fixture().await;
    contact_controller_schema(&mut c).await;
    let settings = contact_provider_settings();
    let clients = contact_providers::Clients::from_values(&BTreeMap::new(), true).unwrap();
    let eligibility = contact_capabilities::Eligibility::from_values(&BTreeMap::new()).unwrap();
    let service = contact_controller::Service {
        settings: &settings,
        contacts: &contact_settings(),
        clients: &clients,
        eligibility: &eligibility,
    };
    let result = service
        .enrich(
            &mut c,
            company,
            json!({"allow_paid":true,"target_roles":["founder"],"max_people":1}),
        )
        .await
        .unwrap();
    assert_eq!(result["state"], "not_configured");
    assert_eq!(result["usage"], json!([]));
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM discovery_monthly_budgets")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_local_public_business_evidence_is_consumed_without_fetching_its_url() {
    let (mut c, company) = enrichment_preview_fixture().await;
    contact_controller_schema(&mut c).await;
    let settings = contact_provider_settings();
    sqlx::query(
        "UPDATE contacts SET email=NULL,email_status='unknown',last_verified_at=NULL WHERE id=$1",
    )
    .bind(Uuid::from_u128(505))
    .execute(&mut c)
    .await
    .unwrap();
    sqlx::query("INSERT INTO contact_evidence(id,company_id,contact_id,source,evidence_type,evidence_url,strength,collected_at,expires_at,user_confirmed,provenance) VALUES($1,$2,$3,'manual','public_business_contact','https://contact-fixture.example/team','strong',clock_timestamp()-interval '1 day',clock_timestamp()+interval '1 day',true,'{\"email\":\"person5@contact-fixture.example\",\"email_kind\":\"person_specific\"}')").bind(Uuid::new_v4()).bind(company).bind(Uuid::from_u128(505)).execute(&mut c).await.unwrap();
    let run = contact_runs::start(
        &mut c,
        company,
        json!({"allow_paid":false,"target_roles":["founder"],"max_people":1}),
        &settings,
    )
    .await
    .unwrap()
    .invocation
    .unwrap();
    let found = contact_local::collect(&mut c, &run, &settings, &contact_settings())
        .await
        .unwrap();
    assert_eq!(found.selected, vec![Uuid::from_u128(505)]);
    let row = contact_identity_row(&mut c, Uuid::from_u128(505)).await;
    assert_eq!(row["email"], "person5@contact-fixture.example");
    assert_eq!(row["email_status"], "provider_reported");
    assert!(row["last_verified_at"].is_null());
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_run_finish_retains_inferred_candidate_labels_and_cannot_overwrite_its_immutable_receipt()
 {
    let (mut c, company) = enrichment_preview_fixture().await;
    contact_controller_schema(&mut c).await;
    let settings = contact_provider_settings();
    let run = contact_runs::start(
        &mut c,
        company,
        json!({"include_candidates":true}),
        &settings,
    )
    .await
    .unwrap()
    .invocation
    .unwrap();
    let result = contact_runs::finish(&mut c, &run, &[Uuid::from_u128(503)], &[], "completed")
        .await
        .unwrap();
    assert_eq!(
        result["counts"]["candidate_research"][0]["candidates"][0]["status"],
        "candidate"
    );
    assert_eq!(result["counts"]["outbound_messages_sent"], 0);
    let before = contact_run_snapshot(&mut c).await;
    assert_eq!(
        contact_runs::finish(&mut c, &run, &[], &[], "failed")
            .await
            .unwrap(),
        result
    );
    assert_eq!(contact_run_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_run_finish_unknown_admission_overrides_requested_success_without_resetting_lease_or_quota()
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
    drop(grant);
    let before = contact_lookup_snapshot(&mut c).await;
    let result = contact_runs::finish(&mut c, &run, &[Uuid::from_u128(505)], &[], "completed")
        .await
        .unwrap();
    assert_eq!(result["state"], "billing_uncertain");
    assert_eq!(contact_lookup_snapshot(&mut c).await, before);
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 0);
    task.abort();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_run_finish_update_or_receipt_ack_faults_preserve_running_run_and_usage() {
    let (mut c, company) = enrichment_preview_fixture().await;
    contact_controller_schema(&mut c).await;
    let settings = contact_provider_settings();
    let run = contact_runs::start(&mut c, company, json!({}), &settings)
        .await
        .unwrap()
        .invocation
        .unwrap();
    let before = contact_run_snapshot(&mut c).await;
    for (table, event, behavior) in [
        (
            "contact_enrichment_runs",
            "UPDATE",
            "NEW.state:='failed';RETURN NEW;",
        ),
        (
            "owner_preferences",
            "INSERT",
            "IF starts_with(NEW.key,'cl_finish:') THEN RETURN NULL;END IF;RETURN NEW;",
        ),
    ] {
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("CREATE FUNCTION fixture_contact_finish_run() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {behavior} END $$;CREATE TRIGGER fixture_contact_finish_run BEFORE {event} ON {table} FOR EACH ROW EXECUTE FUNCTION fixture_contact_finish_run()"))).execute(&mut c).await.unwrap();
        assert_eq!(
            contact_runs::finish(&mut c, &run, &[Uuid::from_u128(501)], &[], "completed")
                .await
                .unwrap_err(),
            Failure("contact_run_write_ack_failed")
        );
        assert_eq!(contact_run_snapshot(&mut c).await, before);
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("DROP TRIGGER fixture_contact_finish_run ON {table};DROP FUNCTION fixture_contact_finish_run()"))).execute(&mut c).await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_owner_http_enrichment_is_authenticated_and_repeated_idempotency_returns_local_history()
 {
    let (mut c, company) = enrichment_preview_fixture().await;
    contact_controller_schema(&mut c).await;
    let (url, stop, task) = http_fixture().await;
    let endpoint = format!("{url}/api/v1/companies/{company}/contacts/enrich");
    let http = client();
    let input = json!({"allow_paid":false,"target_roles":["founder"],"max_people":1,"idempotency_key":"fictional_http_controller"});
    assert_eq!(
        http.post(&endpoint)
            .json(&input)
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    assert_eq!(
        http.post(&endpoint)
            .bearer_auth(HOST_TOKEN)
            .header("x-agent-client", "extension")
            .json(&input)
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    assert_eq!(
        http.get(&endpoint)
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        405
    );
    let response = http
        .post(&endpoint)
        .bearer_auth(HOST_TOKEN)
        .json(&input)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let result: Value = response.json().await.unwrap();
    let response = http
        .post(&endpoint)
        .bearer_auth(HOST_TOKEN)
        .json(&input)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    assert_eq!(response.json::<Value>().await.unwrap()["id"], result["id"]);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM contact_enrichment_runs")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        1
    );
    assert_eq!(
        http.post(format!("{endpoint}?unknown=1"))
            .bearer_auth(HOST_TOKEN)
            .json(&input)
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    stop.cancel();
    task.await.unwrap();
}
