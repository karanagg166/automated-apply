//! Deferred company people/jobs/evidence saved-read fixtures. No provider requests.
use automated_apply_agents::companies as saved_companies;
async fn companies_fixture() -> (PgConnection, Uuid, Uuid) {
    let (mut c, company, job) = contacts_fixture().await;
    sqlx::raw_sql("DROP TABLE IF EXISTS discovered_people,company_source_observations CASCADE;CREATE TABLE discovered_people(id uuid PRIMARY KEY,company_id uuid NOT NULL,name text,role text,linkedin_url text,evidence_url text,source text,observed_at timestamptz,verification_status text,evidence jsonb NOT NULL DEFAULT '{}');CREATE TABLE company_source_observations(id uuid PRIMARY KEY,company_id uuid NOT NULL,run_id uuid,source text NOT NULL,identity_key text NOT NULL,content_hash text NOT NULL,source_url text NOT NULL,observed_at timestamptz NOT NULL,attributes jsonb NOT NULL DEFAULT '{}',verification_status text NOT NULL)").execute(&mut c).await.unwrap();
    for (n, days) in [(1, -1.0), (2, -200.0), (3, 2.0)] {
        sqlx::query("INSERT INTO discovered_people(id,company_id,name,role,linkedin_url,evidence_url,source,observed_at,verification_status,evidence) VALUES($1,$2,$3,'CTO',$4,'https://contact-fixture.example/team','public_search',clock_timestamp()+($5::double precision*interval '1 day'),'human_confirmed','{\"text\":\"Saved fictional professional finding\",\"phone\":\"PRIVATE_SAVED_PHONE_CANARY\",\"token\":\"PRIVATE_SAVED_TOKEN_CANARY\"}')").bind(Uuid::from_u128(990000+n)).bind(company).bind(format!("Fictional Professional {n}")).bind(format!("https://www.linkedin.com/in/fictional-professional-{n}")).bind(days).execute(&mut c).await.unwrap();
    }
    for (n, days) in [(1, -1.0), (2, -200.0), (3, 2.0)] {
        sqlx::query("INSERT INTO company_source_observations(id,company_id,source,identity_key,content_hash,source_url,observed_at,attributes,verification_status) VALUES($1,$2,'manual',$3,'fictional_content','https://contact-fixture.example/about',clock_timestamp()+($4::double precision*interval '1 day'),'{\"employee_count\":12,\"team_size_band\":\"11-50\",\"industry\":\"Developer tools\",\"technology_stack\":[\"Rust\"],\"private_billing_key\":\"PRIVATE_BILLING_CANARY\",\"raw_vendor\":\"PRIVATE_COMPANY_VENDOR_CANARY\"}','source_reported')").bind(Uuid::from_u128(991000+n)).bind(company).bind(format!("fictional-{n}")).bind(days).execute(&mut c).await.unwrap();
    }
    sqlx::query("UPDATE jobs SET discovery_metadata='{\"private\":\"PRIVATE_JOB_METADATA_CANARY\"}' WHERE id=$1").bind(job).execute(&mut c).await.unwrap();
    (c, company, job)
}
fn companies_path(company: Uuid, kind: &str) -> String {
    format!(
        "/api/v1/{}/{company}/{kind}",
        if kind == "people" {
            "companies"
        } else {
            "startups"
        }
    )
}
async fn company_saved_call(
    c: &mut PgConnection,
    company: Uuid,
    kind: &str,
    query: Option<&str>,
) -> Result<Value> {
    saved_companies::dispatch(
        c,
        saved_companies::route(&companies_path(company, kind)).unwrap(),
        "GET",
        query,
        &[],
    )
    .await
}
async fn companies_snapshot(c: &mut PgConnection) -> Value {
    sqlx::query_scalar("SELECT jsonb_build_object('companies',(SELECT jsonb_agg(to_jsonb(c) ORDER BY id) FROM companies c),'people',(SELECT jsonb_agg(to_jsonb(p) ORDER BY id) FROM discovered_people p),'observations',(SELECT jsonb_agg(to_jsonb(o) ORDER BY id) FROM company_source_observations o),'jobs',(SELECT jsonb_agg(to_jsonb(j) ORDER BY id) FROM jobs j))").fetch_one(c).await.unwrap()
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn company_saved_people_and_observations_expose_only_selected_professional_evidence_without_vendor_fields()
 {
    let (mut c, company, _) = companies_fixture().await;
    let before = companies_snapshot(&mut c).await;
    let people = company_saved_call(&mut c, company, "people", None)
        .await
        .unwrap();
    assert_eq!(people["total"], 3);
    assert_eq!(people["people"].as_array().unwrap().len(), 3);
    assert!(
        people["people"]
            .as_array()
            .unwrap()
            .iter()
            .all(|p| p["outreach_mode"] == "manual"
                && p["live_verified"] == false
                && p["email_send_ready"] == false)
    );
    assert!(!people.to_string().contains("PRIVATE_SAVED_PHONE_CANARY"));
    assert!(!people.to_string().contains("PRIVATE_SAVED_TOKEN_CANARY"));
    let evidence = company_saved_call(&mut c, company, "evidence", None)
        .await
        .unwrap();
    assert_eq!(evidence["total"], 3);
    assert_eq!(
        evidence["observations"][0]["attributes"]["employee_count"],
        12
    );
    assert!(!evidence.to_string().contains("PRIVATE_BILLING_CANARY"));
    assert!(
        !evidence
            .to_string()
            .contains("PRIVATE_COMPANY_VENDOR_CANARY")
    );
    assert_eq!(companies_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn company_saved_future_and_stale_evidence_remain_visible_with_explicit_review_qualification()
{
    let (mut c, company, _) = companies_fixture().await;
    for kind in ["people", "evidence"] {
        let result = company_saved_call(&mut c, company, kind, None)
            .await
            .unwrap();
        let records = result[if kind == "people" {
            "people"
        } else {
            "observations"
        }]
        .as_array()
        .unwrap();
        assert_eq!(records[0]["stale"], true);
        assert_eq!(records[0]["verification_status"], "requires_review");
        assert_eq!(records[1]["stale"], false);
        assert_eq!(records[2]["stale"], true);
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn company_saved_stable_paging_keeps_the_full_total_and_never_loads_other_employers() {
    let (mut c, company, _) = companies_fixture().await;
    let foreign = Uuid::from_u128(992001);
    sqlx::query("INSERT INTO companies(id,name,domain) VALUES($1,'Other fictional employer','other-fixture.example')").bind(foreign).execute(&mut c).await.unwrap();
    sqlx::query("INSERT INTO discovered_people(id,company_id,name,role,linkedin_url,evidence_url,source,observed_at,verification_status,evidence) VALUES($1,$2,'PRIVATE_FOREIGN_PERSON_CANARY','CTO','https://linkedin.com/in/foreign-fictional','https://other-fixture.example/team','manual',clock_timestamp(),'requires_review','{}')").bind(Uuid::from_u128(992002)).bind(foreign).execute(&mut c).await.unwrap();
    for kind in ["people", "evidence"] {
        let all = company_saved_call(&mut c, company, kind, None)
            .await
            .unwrap();
        let page = company_saved_call(&mut c, company, kind, Some("limit=1&offset=1"))
            .await
            .unwrap();
        let key = if kind == "people" {
            "people"
        } else {
            "observations"
        };
        assert_eq!(page[key][0], all[key][1]);
        assert_eq!(page["total"], 3);
        assert_eq!(page["has_more"], true);
        assert!(!page.to_string().contains("PRIVATE_FOREIGN_PERSON_CANARY"));
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn company_saved_jobs_reuse_actual_catalog_dto_without_private_discovery_payloads_or_mutation()
 {
    let (mut c, company, job) = companies_fixture().await;
    let before = companies_snapshot(&mut c).await;
    let result = company_saved_call(&mut c, company, "jobs", None)
        .await
        .unwrap();
    let item = result["jobs"]
        .as_array()
        .unwrap()
        .iter()
        .find(|v| v["id"] == job.to_string())
        .unwrap();
    assert!(item["skills_required"].is_array());
    assert!(item["updated_at"].is_string());
    assert!(!result.to_string().contains("PRIVATE_JOB_METADATA_CANARY"));
    assert_eq!(item["company_id"], company.to_string());
    assert_eq!(companies_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn company_saved_reads_do_not_wait_on_owner_mutex_or_change_other_runtime_state() {
    let (mut c, company, _) = companies_fixture().await;
    let before = browser_snapshot(&mut c).await;
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
    for kind in ["people", "evidence", "jobs"] {
        company_saved_call(&mut c, company, kind, None)
            .await
            .unwrap();
    }
    assert_eq!(browser_snapshot(&mut c).await, before);
    tx.rollback().await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn company_saved_missing_employer_is_distinct_from_missing_or_malformed_saved_evidence() {
    let (mut c, company, _) = companies_fixture().await;
    assert_eq!(
        company_saved_call(&mut c, Uuid::nil(), "people", None)
            .await
            .unwrap_err(),
        Failure("company_saved_not_found")
    );
    sqlx::query("UPDATE company_source_observations SET attributes='{\"technology_stack\":[123]}'")
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        company_saved_call(&mut c, company, "evidence", None)
            .await
            .unwrap_err(),
        Failure("invalid_company_saved_record")
    );
    sqlx::query("DROP TABLE discovered_people")
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        company_saved_call(&mut c, company, "people", None)
            .await
            .unwrap_err(),
        Failure("company_saved_database_error")
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn company_saved_query_method_body_and_expanded_json_limits_fail_closed_without_writes() {
    let (mut c, company, _) = companies_fixture().await;
    let before = companies_snapshot(&mut c).await;
    for query in [
        "limit=0",
        "limit=101",
        "offset=-1",
        "offset=100001",
        "limit=1&limit=2",
        "unknown=true",
    ] {
        assert_eq!(
            company_saved_call(&mut c, company, "people", Some(query))
                .await
                .unwrap_err(),
            Failure("invalid_company_saved_query")
        );
    }
    assert_eq!(
        saved_companies::dispatch(
            &mut c,
            saved_companies::Route::People(company),
            "POST",
            None,
            &[]
        )
        .await
        .unwrap_err(),
        Failure("company_saved_method_not_allowed")
    );
    assert_eq!(
        saved_companies::dispatch(
            &mut c,
            saved_companies::Route::People(company),
            "GET",
            None,
            b"{}"
        )
        .await
        .unwrap_err(),
        Failure("invalid_company_saved_query")
    );
    assert_eq!(companies_snapshot(&mut c).await, before);
    sqlx::query("UPDATE company_source_observations SET attributes=jsonb_build_object('description',repeat('x',262145))").execute(&mut c).await.unwrap();
    assert_eq!(
        company_saved_call(&mut c, company, "evidence", None)
            .await
            .unwrap_err(),
        Failure("invalid_company_saved_record")
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn company_saved_owner_http_routes_require_owner_auth_and_keep_unsupported_methods_read_only()
{
    let (mut c, company, _) = companies_fixture().await;
    let before = companies_snapshot(&mut c).await;
    let (url, stop, task) = http_fixture_values(host_values()).await;
    let http = client();
    for kind in ["people", "evidence", "jobs"] {
        let endpoint = format!("{url}{}", companies_path(company, kind));
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
            http.get(format!("{endpoint}?unknown=true"))
                .bearer_auth(HOST_TOKEN)
                .send()
                .await
                .unwrap()
                .status(),
            422
        );
    }
    assert_eq!(companies_snapshot(&mut c).await, before);
    stop.cancel();
    task.await.unwrap().unwrap();
}
