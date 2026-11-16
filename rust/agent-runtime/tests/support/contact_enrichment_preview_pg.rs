//! Deferred local planning/saved-provider fixtures; no HTTP transport to a provider.
async fn enrichment_preview_fixture() -> (PgConnection, Uuid) {
    let (mut c, company, _) = contacts_fixture().await;
    sqlx::raw_sql("DROP TABLE IF EXISTS discovered_company_people,discovery_monthly_budgets,contact_enrichment_runs CASCADE;CREATE TABLE discovered_company_people(id uuid PRIMARY KEY,company_id uuid NOT NULL,name varchar(255),role varchar(255),linkedin_url text,evidence_url text,source varchar(50),observed_at timestamptz NOT NULL,verification_status varchar(50),evidence jsonb NOT NULL DEFAULT '{}');CREATE TABLE discovery_monthly_budgets(provider varchar(50),month varchar(7),reserved numeric(16,6) NOT NULL,cooldown_until timestamptz,PRIMARY KEY(provider,month));CREATE TABLE contact_enrichment_runs(id uuid PRIMARY KEY,company_id uuid NOT NULL,request_hash varchar(64),target_roles jsonb NOT NULL,provider_plan jsonb NOT NULL,state text NOT NULL,contact_ids jsonb NOT NULL,counts jsonb NOT NULL,usage jsonb NOT NULL,errors jsonb NOT NULL,started_at timestamptz NOT NULL,completed_at timestamptz,idempotency_key varchar(100) UNIQUE)").execute(&mut c).await.unwrap();
    for (n, name, role, link) in [
        (
            1,
            Some("Fictional Existing CTO"),
            "Chief Technology Officer",
            Some("https://www.linkedin.com/in/fictional-contact-1"),
        ),
        (
            2,
            Some("Fictional New Engineer"),
            "Engineer",
            Some("https://www.linkedin.com/in/fictional-new-engineer"),
        ),
        (3, None, "Engineer", None),
    ] {
        sqlx::query("INSERT INTO discovered_company_people(id,company_id,name,role,linkedin_url,source,observed_at,evidence) VALUES($1,$2,$3,$4,$5,'public_search',clock_timestamp(),'{\"private\":\"PRIVATE_PERSON_VENDOR_CANARY\"}')").bind(Uuid::from_u128(870000+n)).bind(company).bind(name).bind(role).bind(link).execute(&mut c).await.unwrap();
    }
    (c, company)
}
fn contact_provider_settings() -> contacts::enrichment::Settings {
    contacts::enrichment::Settings::from_values(&BTreeMap::new()).unwrap()
}
async fn enrichment_preview(c: &mut PgConnection, company: Uuid, input: Value) -> Result<Value> {
    contacts::enrichment::dispatch(
        c,
        contacts::enrichment::Route::Preview(company),
        "POST",
        None,
        &serde_json::to_vec(&input).unwrap(),
        &contact_provider_settings(),
        &contact_settings(),
    )
    .await
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_enrichment_preview_reads_local_targets_without_credit_reservation_or_owner_writes()
{
    let (mut c, company) = enrichment_preview_fixture().await;
    let before = browser_snapshot(&mut c).await;
    let value = enrichment_preview(&mut c, company, json!({"allow_paid":true}))
        .await
        .unwrap();
    assert_eq!(
        value["targets"],
        json!([Uuid::from_u128(503), Uuid::from_u128(505)])
    );
    assert_eq!(
        value["discovered_targets"],
        json!([Uuid::from_u128(870002)])
    );
    assert_eq!(value["provider_plan"][0]["lookup_count_upper_bound"], 3);
    assert!(value["provider_plan"][0]["reserved_credit_upper_bound"].is_null());
    assert_eq!(value["read_only"], true);
    assert_eq!(value["billable_calls"], 0);
    assert_eq!(value["provider_requests"], 0);
    assert_eq!(value["live_eligibility_verified"], false);
    assert_eq!(browser_snapshot(&mut c).await, before);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM discovery_monthly_budgets")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM contact_enrichment_runs")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    assert!(!value.to_string().contains("PRIVATE_PERSON_VENDOR_CANARY"));
    assert!(!value.to_string().contains("PRIVATE_CONTACT_VENDOR_CANARY"));
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_enrichment_preview_role_aliases_and_corrected_contacts_prevent_unnecessary_lookups()
 {
    let (mut c, company) = enrichment_preview_fixture().await;
    let value = enrichment_preview(&mut c, company, json!({"target_roles":["cto"]}))
        .await
        .unwrap();
    assert_eq!(value["cached_contacts"].as_array().unwrap().len(), 1);
    assert_eq!(value["targets"], json!([]));
    assert_eq!(value["discovered_targets"], json!([]));
    assert_eq!(value["provider_plan"][0]["lookup_count_upper_bound"], 0);
    sqlx::query("UPDATE contacts SET human_corrected=true WHERE id=$1")
        .bind(Uuid::from_u128(505))
        .execute(&mut c)
        .await
        .unwrap();
    let value = enrichment_preview(&mut c, company, json!({}))
        .await
        .unwrap();
    assert_eq!(value["targets"], json!([Uuid::from_u128(503)]));
    assert!(
        value["no_lookup_needed"]
            .as_array()
            .unwrap()
            .contains(&json!(Uuid::from_u128(505)))
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_enrichment_empty_company_search_plan_is_qualified_and_has_no_implicit_fallback() {
    let (mut c, _) = enrichment_preview_fixture().await;
    let company = Uuid::from_u128(880001);
    sqlx::query("INSERT INTO companies(id,name,domain,metadata) VALUES($1,'Fictional Empty Employer','empty-contact.example','{}')").bind(company).execute(&mut c).await.unwrap();
    let value = enrichment_preview(
        &mut c,
        company,
        json!({"providers":["apollo","signalhire"],"max_people":25,"allow_fallback":false}),
    )
    .await
    .unwrap();
    assert_eq!(value["max_people"], 10);
    assert_eq!(value["provider_plan"][0]["lookup_count_upper_bound"], 10);
    assert_eq!(value["provider_plan"][0]["search_if_no_targets"], true);
    assert_eq!(value["provider_plan"][0]["search_credits"], 0);
    assert_eq!(
        value["provider_plan"][0]["live_eligibility_verified"],
        false
    );
    assert_eq!(value["provider_plan"][1]["fallback_requires_opt_in"], true);
    assert_eq!(value["billable_calls"], 0);
    let value = enrichment_preview(&mut c, company, json!({"providers":["signalhire"]}))
        .await
        .unwrap();
    assert_eq!(value["provider_plan"][0]["lookup_count_upper_bound"], 0);
    assert_eq!(value["provider_plan"][0]["search_if_no_targets"], false);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_provider_saved_status_separates_credentials_budget_and_live_entitlement_without_exposing_keys()
 {
    let (mut c, _) = enrichment_preview_fixture().await;
    sqlx::query("INSERT INTO discovery_monthly_budgets VALUES('apollo',to_char(clock_timestamp(),'YYYY-MM'),2.5,clock_timestamp()+interval '1 day')").execute(&mut c).await.unwrap();
    let values = BTreeMap::from([
        (
            "APOLLO_API_KEY".into(),
            "PRIVATE_PROVIDER_KEY_CANARY".into(),
        ),
        ("APOLLO_ENRICHMENT_ENABLED".into(), "true".into()),
        ("APOLLO_CREDITS_PER_LOOKUP".into(), "2".into()),
    ]);
    let settings = contacts::enrichment::Settings::from_values(&values).unwrap();
    let value = contacts::enrichment::dispatch(
        &mut c,
        contacts::enrichment::Route::Providers,
        "GET",
        None,
        &[],
        &settings,
        &contact_settings(),
    )
    .await
    .unwrap();
    let apollo = &value["providers"][0];
    assert_eq!(apollo["configuration_status"], "completed");
    assert_eq!(apollo["budget"]["reserved_estimate"], 2.5);
    assert_eq!(apollo["budget"]["remaining_local_budget"], 47.5);
    assert!(apollo["budget"]["provider_balance"].is_null());
    assert_eq!(apollo["live_verification"], "not_checked");
    assert_eq!(apollo["native_lookup_execution_ready"], false);
    assert_eq!(
        value["providers"][1]["configuration_status"],
        "not_configured"
    );
    assert!(!value.to_string().contains("PRIVATE_PROVIDER_KEY_CANARY"));
    sqlx::query("UPDATE discovery_monthly_budgets SET reserved=-1")
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        contacts::enrichment::dispatch(
            &mut c,
            contacts::enrichment::Route::Providers,
            "GET",
            None,
            &[],
            &settings,
            &contact_settings()
        )
        .await
        .unwrap_err(),
        Failure("invalid_contact_saved_record")
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_enrichment_preview_truncation_is_disclosed_and_company_evidence_is_whitelisted() {
    let (mut c, company) = enrichment_preview_fixture().await;
    sqlx::query("INSERT INTO contacts(id,company_id,full_name,role_title,email_status,enrichment_source,last_checked_at,metadata) SELECT lpad(to_hex(1100000+n),32,'0')::uuid,$1,'Fictional bounded person','Engineer','unknown','manual',clock_timestamp(),'{}' FROM generate_series(1,1005) n").bind(company).execute(&mut c).await.unwrap();
    sqlx::query("INSERT INTO discovered_company_people(id,company_id,name,role,linkedin_url,observed_at) SELECT lpad(to_hex(1200000+n),32,'0')::uuid,$1,'Fictional bounded discovered person','Engineer','https://contact-fixture.example/person/'||n,clock_timestamp() FROM generate_series(1,105) n").bind(company).execute(&mut c).await.unwrap();
    sqlx::query("INSERT INTO contact_evidence(id,company_id,source,evidence_type,evidence_url,strength,collected_at,expires_at,provenance) VALUES($1,$2,'official_company','company_general_mailbox','https://contact-fixture.example/team','strong',clock_timestamp(),clock_timestamp()+interval '1 day','{\"email\":\"jobs@contact-fixture.example\",\"requires_review\":true,\"vendor\":\"PRIVATE_COMPANY_EVIDENCE_CANARY\"}')").bind(Uuid::new_v4()).bind(company).execute(&mut c).await.unwrap();
    let value = enrichment_preview(&mut c, company, json!({}))
        .await
        .unwrap();
    assert_eq!(value["contact_inventory_truncated"], true);
    assert_eq!(value["people_inventory_truncated"], true);
    assert_eq!(value["cached_contacts"].as_array().unwrap().len(), 100);
    assert_eq!(value["discovered_people"].as_array().unwrap().len(), 100);
    assert_eq!(value["targets"].as_array().unwrap().len(), 5);
    assert_eq!(
        value["company_evidence"][0]["provenance"]["email"],
        "jobs@contact-fixture.example"
    );
    assert!(
        !value
            .to_string()
            .contains("PRIVATE_COMPANY_EVIDENCE_CANARY")
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_enrichment_saved_run_hides_internal_errors_and_usage_payloads_and_keeps_candidates_unverified()
 {
    let (mut c, company) = enrichment_preview_fixture().await;
    let run = Uuid::from_u128(890001);
    let counts = json!({"contacts":1,"outbound_messages_sent":0,"candidate_research":[{"contact_id":Uuid::from_u128(501),"candidates":[{"email":"fictional.person@contact-fixture.example","pattern_used":"{first}.{last}@{domain}","status":"candidate","confidence_score":0.4,"private":"PRIVATE_PATTERN_VENDOR_CANARY"}]}]});
    let usage = json!([{"provider":"apollo","operation":"enrich_person","state":"billing_uncertain","reserved_estimate":2,"confirmed_provider_credits":null,"reservation_id":"PRIVATE_RESERVATION_CANARY","vendor":"PRIVATE_USAGE_CANARY"}]);
    sqlx::query("INSERT INTO contact_enrichment_runs VALUES($1,$2,$3,'[\"cto\"]','[\"apollo\"]','billing_uncertain',$4,$5,$6,'[\"PRIVATE_RUN_ERROR_CANARY\"]',clock_timestamp(),NULL,'PRIVATE_IDEMPOTENCY_CANARY')").bind(run).bind(company).bind("a".repeat(64)).bind(json!([Uuid::from_u128(501)])).bind(counts).bind(usage).execute(&mut c).await.unwrap();
    let value = contacts::enrichment::dispatch(
        &mut c,
        contacts::enrichment::Route::Run(run),
        "GET",
        None,
        &[],
        &contact_provider_settings(),
        &contact_settings(),
    )
    .await
    .unwrap();
    assert_eq!(value["state"], "billing_uncertain");
    assert_eq!(
        value["errors"],
        json!(["historical_provider_error_requires_review"])
    );
    assert_eq!(value["retained_error_count"], 1);
    assert_eq!(
        value["counts"]["candidate_research"][0]["candidates"][0]["status"],
        "candidate"
    );
    assert_eq!(value["live_verified"], false);
    assert!(!value.to_string().contains("PRIVATE_"));
    sqlx::query("UPDATE contact_enrichment_runs SET target_roles=$2 WHERE id=$1")
        .bind(run)
        .bind(json!(["x".repeat(300000)]))
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        contacts::enrichment::dispatch(
            &mut c,
            contacts::enrichment::Route::Run(run),
            "GET",
            None,
            &[],
            &contact_provider_settings(),
            &contact_settings()
        )
        .await
        .unwrap_err(),
        Failure("invalid_contact_saved_record")
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_enrichment_read_paths_do_not_wait_on_owner_fence_or_mutate_saved_rows() {
    let (mut c, company) = enrichment_preview_fixture().await;
    let mut other = connection().await;
    let mut lock = other.begin().await.unwrap();
    sqlx::query(
        "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
    )
    .execute(&mut *lock)
    .await
    .unwrap();
    sqlx::query("SET lock_timeout='100ms'")
        .execute(&mut c)
        .await
        .unwrap();
    let before = browser_snapshot(&mut c).await;
    enrichment_preview(&mut c, company, json!({"allow_paid":true}))
        .await
        .unwrap();
    contacts::enrichment::dispatch(
        &mut c,
        contacts::enrichment::Route::Providers,
        "GET",
        None,
        &[],
        &contact_provider_settings(),
        &contact_settings(),
    )
    .await
    .unwrap();
    assert_eq!(browser_snapshot(&mut c).await, before);
    lock.rollback().await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contact_enrichment_owner_http_preview_requires_auth_and_rejects_invalid_contracts_queries_and_methods()
 {
    let (_c, company) = enrichment_preview_fixture().await;
    let (url, stop, task) = http_fixture().await;
    let endpoint = format!("{url}/api/v1/companies/{company}/contacts/preview");
    let http = client();
    assert_eq!(
        http.post(&endpoint)
            .json(&json!({}))
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    let denied = http
        .get(&endpoint)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(denied.status(), 405);
    assert_eq!(denied.headers()["allow"], "POST");
    assert_eq!(
        http.post(&endpoint)
            .bearer_auth(HOST_TOKEN)
            .header("x-agent-client", "extension")
            .json(&json!({}))
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    for input in [
        json!({"providers":["apollo","apollo"]}),
        json!({"max_people":26}),
        json!({"unexpected":true}),
    ] {
        assert_eq!(
            http.post(&endpoint)
                .bearer_auth(HOST_TOKEN)
                .json(&input)
                .send()
                .await
                .unwrap()
                .status(),
            422
        );
    }
    assert_eq!(
        http.post(format!("{endpoint}?unknown=1"))
            .bearer_auth(HOST_TOKEN)
            .json(&json!({}))
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    assert_eq!(
        http.post(&endpoint)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({}))
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    assert_eq!(
        http.get(format!(
            "{url}/api/v1/contact-enrichment/runs/{}",
            Uuid::new_v4()
        ))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .status(),
        404
    );
    stop.cancel();
    task.await.unwrap();
}
