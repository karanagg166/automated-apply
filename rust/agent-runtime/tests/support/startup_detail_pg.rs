//! Deferred derived startup detail fixtures. Fictional PostgreSQL only; no provider IO.
use automated_apply_agents::startup_catalog::detail as startup_detail;
async fn startup_detail_fixture() -> (PgConnection, Uuid, Uuid) {
    let (mut c, company, job) = companies_fixture().await;
    startup_shortlist_schema(&mut c).await;
    sqlx::query("UPDATE companies SET metadata='{\"industry\":\"PRIVATE_LEGACY_INDUSTRY_CANARY\",\"employee_count\":999999,\"raw_vendor\":\"PRIVATE_EMPLOYER_CANARY\"}' WHERE id=$1").bind(company).execute(&mut c).await.unwrap();
    sqlx::query("DELETE FROM company_source_observations WHERE company_id=$1")
        .bind(company)
        .execute(&mut c)
        .await
        .unwrap();
    sqlx::query("INSERT INTO company_source_observations(id,company_id,source,identity_key,content_hash,source_url,observed_at,attributes,verification_status) VALUES($1,$2,'manual','fictional_current_company','fictional_content','https://contact-fixture.example/about',clock_timestamp()-interval '1 day','{\"employee_count\":12,\"team_size_band\":\"11-50\",\"industry\":\"Developer tools\",\"technology_stack\":[\"Rust\"],\"location\":\"Bengaluru\",\"country\":\"India\",\"remote_policy\":\"remote\",\"private\":\"PRIVATE_COMPANY_ATTR_CANARY\"}','source_reported')").bind(Uuid::from_u128(993001)).bind(company).execute(&mut c).await.unwrap();
    sqlx::query("UPDATE jobs SET last_observed_at=clock_timestamp()-interval '1 day',source_platform='manual',source_verification_status='source_reported',discovery_metadata='{\"is_confirmed_current\":true,\"private\":\"PRIVATE_DETAIL_JOB_CANARY\"}' WHERE id=$1").bind(job).execute(&mut c).await.unwrap();
    (c, company, job)
}
async fn startup_shortlist_schema(c: &mut PgConnection) {
    sqlx::raw_sql("DROP TABLE IF EXISTS startup_shortlist_entries;CREATE TABLE startup_shortlist_entries(company_id uuid PRIMARY KEY,run_id uuid,snapshot jsonb NOT NULL DEFAULT '{}',note text,created_at timestamptz NOT NULL DEFAULT now())").execute(c).await.unwrap();
}
async fn startup_read(c: &mut PgConnection, company: Uuid) -> Result<Value> {
    startup_detail::read(c, company, "GET", None, &[], &contact_settings()).await
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_detail_combines_source_qualified_size_hiring_contacts_and_relevance_without_private_facts()
 {
    let (mut c, company, _) = startup_detail_fixture().await;
    let before = companies_snapshot(&mut c).await;
    let result = startup_read(&mut c, company).await.unwrap();
    assert_eq!(result["company_id"], company.to_string());
    assert_eq!(result["employee_count"], 12);
    assert_eq!(result["team_size_band"], "11-50");
    assert_eq!(result["attributes"]["industry"], "Developer tools");
    assert_eq!(result["hiring_status"], "hiring_confirmed");
    assert!(result["current_job_count"].as_u64().unwrap() > 0);
    assert_eq!(result["score_kind"], "relevance_not_probability");
    assert_eq!(result["live_verified"], false);
    for private in [
        "PRIVATE_LEGACY_INDUSTRY_CANARY",
        "PRIVATE_EMPLOYER_CANARY",
        "PRIVATE_COMPANY_ATTR_CANARY",
        "PRIVATE_DETAIL_JOB_CANARY",
        "PRIVATE_CONTACT_VENDOR_CANARY",
        "private-fictional@example.com",
        "fictional-phone-value",
    ] {
        assert!(!result.to_string().contains(private));
    }
    assert!(result.get("contacts").is_none());
    assert_eq!(companies_snapshot(&mut c).await, before);
    use std::io::Write as _;
    let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let mut p=std::process::Command::new(root.join(".venv/bin/python")).current_dir(root).args(["-B","-c","import json,runpy,sys;model=runpy.run_path('rust/scripts/export_startup_contracts.py')['models']()['startup-read'];model.model_validate(json.load(sys.stdin));assert 'backend.app.core.config' not in sys.modules"]).stdin(std::process::Stdio::piped()).stderr(std::process::Stdio::piped()).spawn().unwrap();
    p.stdin
        .take()
        .unwrap()
        .write_all(result.to_string().as_bytes())
        .unwrap();
    let output = p.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_detail_never_promotes_legacy_company_metadata_without_an_attributable_current_observation()
 {
    let (mut c, company, _) = startup_detail_fixture().await;
    sqlx::query("DELETE FROM company_source_observations WHERE company_id=$1")
        .bind(company)
        .execute(&mut c)
        .await
        .unwrap();
    let result = startup_read(&mut c, company).await.unwrap();
    assert_eq!(result["attributes"], json!({}));
    assert!(result["employee_count"].is_null());
    assert_eq!(result["team_size_band"], "unknown");
    assert!(
        !result
            .to_string()
            .contains("PRIVATE_LEGACY_INDUSTRY_CANARY")
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_detail_ignores_future_old_historical_and_review_required_attributes_and_prefers_human_source()
 {
    let (mut c, company, _) = startup_detail_fixture().await;
    for (sql, missing) in [
        (
            "UPDATE company_source_observations SET observed_at=clock_timestamp()+interval '1 day'",
            true,
        ),
        (
            "UPDATE company_source_observations SET observed_at=clock_timestamp()-interval '200 days'",
            false,
        ),
        (
            "UPDATE company_source_observations SET observed_at=clock_timestamp()-interval '1 day',attributes=jsonb_set(attributes,'{historical}','true')",
            false,
        ),
        (
            "UPDATE company_source_observations SET attributes=attributes-'historical',verification_status='requires_review'",
            false,
        ),
    ] {
        sqlx::raw_sql(sqlx::AssertSqlSafe(sql.to_owned()))
            .execute(&mut c)
            .await
            .unwrap();
        let result = startup_read(&mut c, company).await.unwrap();
        assert_eq!(result["attributes"], json!({}));
        assert_eq!(result["team_size_band"], "unknown");
        assert_eq!(
            result["missing_information"]
                .as_array()
                .unwrap()
                .contains(&json!("future_company_observation_requires_review")),
            missing
        );
    }
    sqlx::query("UPDATE company_source_observations SET verification_status='human_confirmed',observed_at=clock_timestamp()-interval '2 days'").execute(&mut c).await.unwrap();
    sqlx::query("INSERT INTO company_source_observations(id,company_id,source,identity_key,content_hash,source_url,observed_at,attributes,verification_status) VALUES($1,$2,'public_source','another_claim','fictional_hash','https://contact-fixture.example/new',clock_timestamp()-interval '1 day','{\"industry\":\"Other industry\",\"employee_count\":100,\"team_size_band\":\"51-200\"}','source_reported')").bind(Uuid::from_u128(993002)).bind(company).execute(&mut c).await.unwrap();
    let result = startup_read(&mut c, company).await.unwrap();
    assert_eq!(result["employee_count"], 12);
    assert_eq!(result["attributes"]["industry"], "Developer tools");
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_detail_current_job_board_expiry_and_no_jobs_keep_hiring_facts_distinct_from_relevance()
 {
    let (mut c, company, _) = startup_detail_fixture().await;
    sqlx::query(
        "UPDATE jobs SET discovery_metadata='{\"listing_status\":\"closed\"}' WHERE company_id=$1",
    )
    .bind(company)
    .execute(&mut c)
    .await
    .unwrap();
    let result = startup_read(&mut c, company).await.unwrap();
    assert_eq!(result["hiring_status"], "hiring_unknown");
    assert_eq!(result["current_job_count"], 0);
    sqlx::query("UPDATE jobs SET company_id=NULL WHERE company_id=$1")
        .bind(company)
        .execute(&mut c)
        .await
        .unwrap();
    let result = startup_read(&mut c, company).await.unwrap();
    assert_eq!(result["hiring_status"], "hiring_unknown");
    assert_eq!(result["current_job_count"], 0);
    assert!(result["hiring_evidence"].as_array().unwrap().is_empty());
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_detail_suppressed_conflicting_and_future_contacts_do_not_establish_professional_evidence()
 {
    let (mut c, company, _) = startup_detail_fixture().await;
    sqlx::query("UPDATE contacts SET metadata='{\"evidence_strength\":\"strong\"}',last_checked_at=clock_timestamp()-interval '1 minute',do_not_contact=false WHERE company_id=$1").bind(company).execute(&mut c).await.unwrap();
    let before = startup_read(&mut c, company).await.unwrap();
    assert!(before["professional_contact_count"].as_u64().unwrap() > 0);
    for sql in [
        "UPDATE contacts SET do_not_contact=true",
        "UPDATE contacts SET do_not_contact=false,metadata='{\"identity_review_required\":true,\"evidence_strength\":\"strong\"}'",
        "UPDATE contacts SET metadata='{\"evidence_strength\":\"strong\"}',last_checked_at=clock_timestamp()+interval '1 day'",
    ] {
        sqlx::raw_sql(sqlx::AssertSqlSafe(sql.to_owned()))
            .execute(&mut c)
            .await
            .unwrap();
        let result = startup_read(&mut c, company).await.unwrap();
        assert_eq!(result["professional_contact_count"], 0);
        assert_eq!(result["leader_evidence_count"], 0);
        assert_eq!(result["technical_staff_count"], 0);
        assert_eq!(result["qualified_business_mailbox_count"], 0);
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_detail_missing_profile_retains_evidence_and_explicit_missing_facts_without_inferred_suitability()
 {
    let (mut c, company, _) = startup_detail_fixture().await;
    sqlx::query("UPDATE candidate_profiles SET singleton_key='archived'")
        .execute(&mut c)
        .await
        .unwrap();
    let result = startup_read(&mut c, company).await.unwrap();
    assert_eq!(result["employee_count"], 12);
    assert!(result["profile_version"].is_null());
    assert!(
        result["missing_information"]
            .as_array()
            .unwrap()
            .contains(&json!("saved_candidate_profile"))
    );
    assert_eq!(
        result["profile_basis"],
        "saved_profile_not_application_authority"
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_detail_rejects_malformed_expanded_evidence_and_missing_employer_without_mutation()
{
    let (mut c, company, _) = startup_detail_fixture().await;
    assert_eq!(
        startup_read(&mut c, Uuid::nil()).await.unwrap_err(),
        Failure("startup_catalog_not_found")
    );
    sqlx::query("UPDATE company_source_observations SET attributes=jsonb_build_object('description',repeat('x',262145))").execute(&mut c).await.unwrap();
    assert_eq!(
        startup_read(&mut c, company).await.unwrap_err(),
        Failure("invalid_startup_catalog_record")
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_detail_read_does_not_wait_for_owner_mutex_or_change_runtime_and_saved_evidence() {
    let (mut c, company, _) = startup_detail_fixture().await;
    let before = browser_snapshot(&mut c).await;
    let saved = companies_snapshot(&mut c).await;
    let mut other = connection().await;
    let mut tx = other.begin().await.unwrap();
    sqlx::query(
        "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
    )
    .execute(&mut *tx)
    .await
    .unwrap();
    sqlx::query("SET lock_timeout='100ms'")
        .execute(&mut c)
        .await
        .unwrap();
    startup_read(&mut c, company).await.unwrap();
    assert_eq!(browser_snapshot(&mut c).await, before);
    assert_eq!(companies_snapshot(&mut c).await, saved);
    tx.rollback().await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_detail_owner_http_uses_saved_contract_and_refuses_auth_method_and_query_substitution()
 {
    let (mut c, company, _) = startup_detail_fixture().await;
    let before = companies_snapshot(&mut c).await;
    let (url, stop, task) = http_fixture_values(host_values()).await;
    let http = client();
    let endpoint = format!("{url}/api/v1/startups/{company}");
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
    assert_eq!(
        http.get(&endpoint)
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    assert_eq!(
        http.post(&endpoint)
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        405
    );
    assert_eq!(
        http.get(format!("{endpoint}?use_profile=false"))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    assert_eq!(companies_snapshot(&mut c).await, before);
    stop.cancel();
    task.await.unwrap().unwrap();
}
