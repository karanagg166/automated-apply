// Deferred saved professional-contact API fixtures. No paid requests or real person records.
use automated_apply_agents::contacts;
async fn contacts_fixture() -> (PgConnection, Uuid, Uuid) {
    let (mut c, _) = listing_fixture().await;
    sqlx::raw_sql("DROP TABLE IF EXISTS contact_evidence,contact_identities,contacts CASCADE;CREATE TABLE contacts(id uuid PRIMARY KEY,company_id uuid NOT NULL,full_name varchar(255) NOT NULL,first_name varchar(100),last_name varchar(100),role_title varchar(255) NOT NULL,linkedin_url text,email varchar(255),email_status varchar(50) NOT NULL,confidence_score numeric(5,2),enrichment_source varchar(100),last_verified_at timestamptz,metadata jsonb NOT NULL DEFAULT '{}',do_not_contact boolean NOT NULL DEFAULT false,suppression_reason text,last_reviewed_at timestamptz,last_checked_at timestamptz,human_review_notes text,human_corrected boolean NOT NULL DEFAULT false,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),updated_at timestamptz NOT NULL DEFAULT clock_timestamp());CREATE TABLE contact_evidence(id uuid PRIMARY KEY,contact_id uuid,company_id uuid NOT NULL,source varchar(100),evidence_type varchar(50),evidence_url text,observed_role varchar(255),observed_company varchar(255),provider_verification_claim varchar(100),strength varchar(20),collected_at timestamptz,expires_at timestamptz,provenance jsonb NOT NULL DEFAULT '{}',user_confirmed boolean NOT NULL DEFAULT false)").execute(&mut c).await.unwrap();
    let (job, company): (Uuid, Uuid) = sqlx::query_as(
        "SELECT id,company_id FROM jobs WHERE company_id IS NOT NULL ORDER BY id LIMIT 1",
    )
    .fetch_one(&mut c)
    .await
    .unwrap();
    sqlx::query("UPDATE companies SET name='Fictional Contact Employer',domain='contact-fixture.example',metadata='{\"employee_count\":20}' WHERE id=$1").bind(company).execute(&mut c).await.unwrap();
    for (n, role, status, suppressed, stale, strength) in [
        (1, "CTO", "verified", false, false, "strong"),
        (
            2,
            "Technical Recruiter",
            "provider_reported",
            false,
            false,
            "moderate",
        ),
        (3, "Rust Engineer", "unknown", false, false, "weak"),
        (4, "HR Manager", "verified", true, false, "strong"),
        (5, "Founder", "verified", false, true, "strong"),
    ] {
        let id = Uuid::from_u128(500 + n);
        sqlx::query("INSERT INTO contacts(id,company_id,full_name,role_title,linkedin_url,email,email_status,confidence_score,enrichment_source,last_verified_at,last_reviewed_at,last_checked_at,do_not_contact,metadata) VALUES($1,$2,$3,$4,$5,$6,$7,70,'apollo',clock_timestamp()-interval '1 day',clock_timestamp()-interval '1 day',clock_timestamp()-($8::double precision*interval '1 day'),$9,$10)").bind(id).bind(company).bind(format!("Fictional Contact {n}")).bind(role).bind(if n==2||n==3{None}else{Some(format!("https://www.linkedin.com/in/fictional-contact-{n}"))}).bind(if n==3{None}else{Some(format!("person{n}@contact-fixture.example"))}).bind(status).bind(if stale{200.0}else{1.0}).bind(suppressed).bind(json!({"evidence_strength":strength,"job_ids":[],"private_vendor_payload":"PRIVATE_CONTACT_VENDOR_CANARY"})).execute(&mut c).await.unwrap();
    }
    for (n, contact, source, strength, expired) in [
        (1, 501, "apollo", "weak", false),
        (2, 501, "manual", "strong", false),
        (3, 502, "apollo", "strong", false),
        (4, 503, "apollo", "strong", true),
    ] {
        sqlx::query("INSERT INTO contact_evidence(id,contact_id,company_id,source,evidence_type,evidence_url,observed_role,observed_company,provider_verification_claim,strength,collected_at,expires_at,provenance,user_confirmed) VALUES($1,$2,$3,$4,'provider_identity','https://contact-fixture.example/team','CTO','Fictional Contact Employer','provider_reported',$5,clock_timestamp(),clock_timestamp()+($6::double precision*interval '1 day'),$7,false)").bind(Uuid::from_u128(600000+n)).bind(Uuid::from_u128(contact)).bind(company).bind(source).bind(strength).bind(if expired{-1.0}else{14.0}).bind(if expired{json!({"private":"PRIVATE_EXPIRED_CONTACT_CANARY"})}else{json!({"evidence":"Fictional retained source"})}).execute(&mut c).await.unwrap();
    }
    (c, company, job)
}
fn contact_settings() -> contacts::Settings {
    contacts::Settings::from_values(&BTreeMap::new()).unwrap()
}
async fn contacts_call(c: &mut PgConnection, path: &str, query: Option<&str>) -> Result<Value> {
    contacts::dispatch(
        c,
        contacts::route(path).unwrap(),
        "GET",
        query,
        &[],
        &contact_settings(),
    )
    .await
}
fn company_contacts_path(company: Uuid) -> String {
    format!("/api/v1/companies/{company}/contacts")
}
fn contact_detail_path(id: u128) -> String {
    format!("/api/v1/contacts/{}", Uuid::from_u128(id))
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contacts_saved_list_preserves_suppression_retention_and_provider_claims_without_raw_vendor_data()
 {
    let (mut c, company, _) = contacts_fixture().await;
    let result = contacts_call(&mut c, &company_contacts_path(company), None)
        .await
        .unwrap();
    assert_eq!(result["total"], 5);
    assert_eq!(result["contacts"].as_array().unwrap().len(), 5);
    assert_eq!(
        result["contacts"][1]["email_evidence_status"],
        "provider_reported"
    );
    assert_eq!(result["contacts"][3]["priority"], "suppressed");
    assert_eq!(
        result["contacts"][3]["manual_outreach_review_available"],
        false
    );
    assert_eq!(result["contacts"][4]["retention_expired"], true);
    assert!(result["contacts"][4]["email"].is_null());
    assert!(result["contacts"][4]["linkedin_url"].is_null());
    assert_eq!(result["contacts"][4]["email_status"], "unknown");
    assert!(!result.to_string().contains("PRIVATE_CONTACT_VENDOR_CANARY"));
    assert!(
        result["contacts"]
            .as_array()
            .unwrap()
            .iter()
            .all(|contact| contact["email_send_ready"] == false)
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contacts_filters_paging_counts_and_literal_role_patterns_share_one_saved_snapshot() {
    let (mut c, company, _) = contacts_fixture().await;
    let path = company_contacts_path(company);
    let page = contacts_call(&mut c, &path, Some("offset=1&limit=1"))
        .await
        .unwrap();
    assert_eq!(page["total"], 5);
    assert_eq!(page["contacts"][0]["id"], Uuid::from_u128(502).to_string());
    assert_eq!(
        contacts_call(
            &mut c,
            &path,
            Some("suppressed=false&has_business_email=true")
        )
        .await
        .unwrap()["total"],
        3
    );
    assert_eq!(
        contacts_call(&mut c, &path, Some("has_linkedin=false"))
            .await
            .unwrap()["total"],
        2
    );
    assert_eq!(
        contacts_call(&mut c, &path, Some("email_status=unknown"))
            .await
            .unwrap()["total"],
        1
    );
    sqlx::query("UPDATE contacts SET role_title='CTO_%\\' WHERE id=$1")
        .bind(Uuid::from_u128(501))
        .execute(&mut c)
        .await
        .unwrap();
    let filtered = contacts_call(&mut c, &path, Some("role=_%25%5C"))
        .await
        .unwrap();
    assert_eq!(filtered["total"], 1);
    assert_eq!(
        filtered["contacts"][0]["id"],
        Uuid::from_u128(501).to_string()
    );
    let after = (chrono::Utc::now() - chrono::Duration::days(2))
        .format("%Y-%m-%dT%H:%M:%SZ")
        .to_string();
    assert_eq!(
        contacts_call(&mut c, &path, Some(&format!("last_observed_after={after}")))
            .await
            .unwrap()["total"],
        4
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contacts_provider_and_strength_filters_require_one_matching_evidence_record_and_strength_freshness()
 {
    let (mut c, company, _) = contacts_fixture().await;
    let path = company_contacts_path(company);
    assert_eq!(
        contacts_call(&mut c, &path, Some("provider=apollo"))
            .await
            .unwrap()["total"],
        3
    );
    assert_eq!(
        contacts_call(&mut c, &path, Some("min_evidence_strength=strong"))
            .await
            .unwrap()["total"],
        2
    );
    let both = contacts_call(
        &mut c,
        &path,
        Some("provider=apollo&min_evidence_strength=strong"),
    )
    .await
    .unwrap();
    assert_eq!(both["total"], 1);
    assert_eq!(both["contacts"][0]["id"], Uuid::from_u128(502).to_string());
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contacts_detail_scrubs_expired_provenance_without_get_writes_and_bounds_evidence() {
    let (mut c, company, _) = contacts_fixture().await;
    let before: Value =
        sqlx::query_scalar("SELECT jsonb_agg(to_jsonb(e) ORDER BY id) FROM contact_evidence e")
            .fetch_one(&mut c)
            .await
            .unwrap();
    let value = contacts_call(&mut c, &contact_detail_path(503), None)
        .await
        .unwrap();
    assert_eq!(value["evidence"][0]["provenance"], json!({"expired":true}));
    assert!(!value.to_string().contains("PRIVATE_EXPIRED_CONTACT_CANARY"));
    assert_eq!(
        sqlx::query_scalar::<_, Value>(
            "SELECT jsonb_agg(to_jsonb(e) ORDER BY id) FROM contact_evidence e"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        before
    );
    sqlx::query("INSERT INTO contact_evidence(id,contact_id,company_id,source,evidence_type,strength,collected_at,expires_at,provenance) SELECT lpad(to_hex(700000+n),32,'0')::uuid,$1,$2,'manual','human_correction','strong','2026-11-01T00:00:00Z'::timestamptz,clock_timestamp()+interval '14 days','{}'::jsonb FROM generate_series(1,105) n").bind(Uuid::from_u128(501)).bind(company).execute(&mut c).await.unwrap();
    assert_eq!(
        contacts_call(&mut c, &contact_detail_path(501), None)
            .await
            .unwrap()["evidence"]
            .as_array()
            .unwrap()
            .len(),
        100
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contacts_recommendation_is_stable_excludes_suppression_and_preserves_job_association_beyond_public_reference_cap()
 {
    let (mut c, _company, job) = contacts_fixture().await;
    let references = (0..100)
        .map(|n| Uuid::from_u128(800000 + n).to_string())
        .chain(std::iter::once(job.to_string()))
        .collect::<Vec<_>>();
    sqlx::query("UPDATE contacts SET metadata=$2 WHERE id=$1").bind(Uuid::from_u128(503)).bind(json!({"evidence_strength":"strong","job_ids":references,"hiring_responsibility_confirmed":true})).execute(&mut c).await.unwrap();
    let result = contacts_call(
        &mut c,
        &format!("/api/v1/jobs/{job}/recommended-contacts"),
        Some("limit=2"),
    )
    .await
    .unwrap();
    assert_eq!(
        result["contacts"][0]["id"],
        Uuid::from_u128(503).to_string()
    );
    assert_eq!(
        result["contacts"][0]["associated_job_ids"]
            .as_array()
            .unwrap()
            .len(),
        100
    );
    assert!(
        result["contacts"][0]["reasons"]
            .as_array()
            .unwrap()
            .contains(&json!("Explicitly associated with this opening"))
    );
    assert_eq!(result["candidate_inventory_truncated"], false);
    assert_eq!(result["outbound_messages_sent"], 0);
    assert!(
        result["contacts"]
            .as_array()
            .unwrap()
            .iter()
            .all(|contact| contact["id"] != Uuid::from_u128(504).to_string())
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contacts_reads_never_acquire_owner_lock_or_change_profile_queue_and_contact_rows() {
    let (mut c, company, job) = contacts_fixture().await;
    let before = browser_snapshot(&mut c).await;
    let rows: Value =
        sqlx::query_scalar("SELECT jsonb_agg(to_jsonb(c) ORDER BY id) FROM contacts c")
            .fetch_one(&mut c)
            .await
            .unwrap();
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
    for path in [
        company_contacts_path(company),
        contact_detail_path(501),
        format!("/api/v1/jobs/{job}/recommended-contacts"),
    ] {
        contacts_call(&mut c, &path, None).await.unwrap();
    }
    assert_eq!(browser_snapshot(&mut c).await, before);
    assert_eq!(
        sqlx::query_scalar::<_, Value>("SELECT jsonb_agg(to_jsonb(c) ORDER BY id) FROM contacts c")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        rows
    );
    lock.rollback().await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contacts_unsafe_profile_links_and_oversized_or_malformed_metadata_do_not_claim_available_review()
 {
    let (mut c, company, _) = contacts_fixture().await;
    sqlx::query("UPDATE contacts SET linkedin_url='javascript:private-canary' WHERE id=$1")
        .bind(Uuid::from_u128(501))
        .execute(&mut c)
        .await
        .unwrap();
    let value = contacts_call(&mut c, &contact_detail_path(501), None)
        .await
        .unwrap();
    assert!(value["linkedin_url"].is_null());
    assert_eq!(value["manual_linkedin_available"], false);
    sqlx::query("UPDATE contacts SET metadata=$2 WHERE id=$1")
        .bind(Uuid::from_u128(501))
        .bind(json!({"vendor":"x".repeat(262145)}))
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        contacts_call(&mut c, &company_contacts_path(company), None)
            .await
            .unwrap_err(),
        Failure("invalid_contact_saved_record")
    );
    sqlx::query("UPDATE contacts SET metadata='{\"job_ids\":{\"invalid\":true}}' WHERE id=$1")
        .bind(Uuid::from_u128(501))
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        contacts_call(&mut c, &contact_detail_path(501), None)
            .await
            .unwrap_err(),
        Failure("invalid_contact_saved_record")
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contacts_missing_identity_and_employer_are_explicit_and_unaffiliated_job_has_no_recommendations()
 {
    let (mut c, _company, job) = contacts_fixture().await;
    assert_eq!(
        contacts_call(&mut c, &company_contacts_path(Uuid::new_v4()), None)
            .await
            .unwrap_err(),
        Failure("contact_company_not_found")
    );
    assert_eq!(
        contacts_call(&mut c, &contact_detail_path(999999), None)
            .await
            .unwrap_err(),
        Failure("contact_not_found")
    );
    assert_eq!(
        contacts_call(
            &mut c,
            &format!("/api/v1/jobs/{}/recommended-contacts", Uuid::new_v4()),
            None
        )
        .await
        .unwrap_err(),
        Failure("contact_job_not_found")
    );
    sqlx::query("UPDATE jobs SET company_id=NULL WHERE id=$1")
        .bind(job)
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        contacts_call(
            &mut c,
            &format!("/api/v1/jobs/{job}/recommended-contacts"),
            None
        )
        .await
        .unwrap(),
        json!({"contacts":[]})
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contacts_owner_http_auth_methods_and_query_bounds_precede_data_projection() {
    let (_c, company, _) = contacts_fixture().await;
    let (url, stop, task) = http_fixture().await;
    let endpoint = format!("{url}{}", company_contacts_path(company));
    let http = client();
    assert_eq!(http.get(&endpoint).send().await.unwrap().status(), 401);
    assert_eq!(
        http.get(&endpoint)
            .bearer_auth(HOST_TOKEN)
            .header("x-agent-client", "extension")
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    let denied = http
        .delete(&endpoint)
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"email_status":"verified"}))
        .send()
        .await
        .unwrap();
    assert_eq!(denied.status(), 405);
    assert_eq!(denied.headers()["allow"], "GET");
    for query in ["limit=101", "limit=1&limit=2", "unknown=1"] {
        assert_eq!(
            http.get(format!("{endpoint}?{query}"))
                .bearer_auth(HOST_TOKEN)
                .send()
                .await
                .unwrap()
                .status(),
            400
        );
    }
    let response = http
        .get(format!("{endpoint}?limit=1&suppressed=false"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let value: Value = response.json().await.unwrap();
    assert_eq!(value["contacts"].as_array().unwrap().len(), 1);
    assert_eq!(value["total"], 4);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn contacts_recommendation_inventory_cap_is_disclosed_and_public_pages_stay_bounded() {
    let (mut c, company, job) = contacts_fixture().await;
    sqlx::query("INSERT INTO contacts(id,company_id,full_name,role_title,email_status,enrichment_source,last_checked_at,metadata) SELECT lpad(to_hex(900000+n),32,'0')::uuid,$1,'Fictional bounded contact','Engineer','unknown','manual',clock_timestamp(),'{\"evidence_strength\":\"weak\"}'::jsonb FROM generate_series(1,1005) n").bind(company).execute(&mut c).await.unwrap();
    let result = contacts_call(
        &mut c,
        &format!("/api/v1/jobs/{job}/recommended-contacts"),
        Some("limit=25"),
    )
    .await
    .unwrap();
    assert_eq!(result["candidate_inventory_limit"], 1000);
    assert_eq!(result["candidate_inventory_truncated"], true);
    assert_eq!(result["contacts"].as_array().unwrap().len(), 25);
    let result = contacts_call(&mut c, &company_contacts_path(company), Some("limit=100"))
        .await
        .unwrap();
    assert_eq!(result["contacts"].as_array().unwrap().len(), 100);
    assert_eq!(result["total"], 1010);
}
