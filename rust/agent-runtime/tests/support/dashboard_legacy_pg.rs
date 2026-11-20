#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn dashboard_legacy_and_jobs_search_enforce_boundaries_and_match_saved_state() {
    let mut c = knowledge_fixture().await;
    sqlx::raw_sql(
        "ALTER TABLE jobs
            ADD COLUMN IF NOT EXISTS salary_range varchar(100),
            ADD COLUMN IF NOT EXISTS match_score numeric(5,2),
            ADD COLUMN IF NOT EXISTS match_explanation text,
            ADD COLUMN IF NOT EXISTS first_observed_at timestamptz,
            ADD COLUMN IF NOT EXISTS last_observed_at timestamptz,
            ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT clock_timestamp();
         ALTER TABLE application_packets
            ADD COLUMN IF NOT EXISTS tracking_state varchar(100);
         CREATE TABLE IF NOT EXISTS job_source_observations (
            id uuid PRIMARY KEY,
            job_id uuid NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            source varchar(100) NOT NULL,
            source_job_id text NOT NULL,
            original_url text NOT NULL,
            first_observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            last_observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
            verification_status varchar(50) NOT NULL DEFAULT 'observed'
         );
         CREATE TABLE IF NOT EXISTS company_source_observations (
            id uuid PRIMARY KEY,
            company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            source varchar(100) NOT NULL,
            observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            payload jsonb NOT NULL DEFAULT '{}'::jsonb
         );
         CREATE TABLE IF NOT EXISTS provider_connection_checks (
            id uuid PRIMARY KEY,
            provider varchar(100) NOT NULL,
            operation varchar(50) NOT NULL DEFAULT 'sample_jobs',
            configuration_fingerprint varchar(64),
            state varchar(50) NOT NULL DEFAULT 'testing',
            checked_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            finished_at timestamptz,
            http_status integer,
            result_count integer,
            schema_valid boolean,
            evidence_urls jsonb NOT NULL DEFAULT '[]'::jsonb,
            is_live boolean NOT NULL DEFAULT true,
            error_category varchar(100)
         );
         CREATE TABLE IF NOT EXISTS provider_access_windows (
            provider varchar(100) PRIMARY KEY,
            next_allowed_at timestamptz NOT NULL
         );
         CREATE TABLE IF NOT EXISTS connected_accounts (
            id uuid PRIMARY KEY,
            provider varchar(50) NOT NULL,
            google_subject text,
            account_email text,
            granted_scopes jsonb NOT NULL DEFAULT '[]'::jsonb,
            status varchar(50) NOT NULL,
            connected_at timestamptz,
            last_verified_at timestamptz,
            last_refresh_at timestamptz
         );",
    )
    .execute(&mut c)
    .await
    .unwrap();

    let company_id = Uuid::new_v4();
    sqlx::query("INSERT INTO companies(id,name,domain) VALUES($1,'Fictional Acme','fictional-acme.example')")
        .bind(company_id)
        .execute(&mut c)
        .await
        .unwrap();

    let job_rust = Uuid::new_v4();
    let job_other = Uuid::new_v4();
    let job_applied = Uuid::new_v4();
    sqlx::query(
        "INSERT INTO jobs(id,company_id,title,job_url,source_platform,status,location,is_remote,remote_type,experience_level,skills_required,discovery_metadata,first_observed_at,last_observed_at)
         VALUES($1,$2,'Rust Developer','https://www.naukri.com/job-listings-fictional-rust-dev-000000000001','naukri','discovered','Remote',true,'remote','junior',ARRAY['Rust'],'{\"country\":\"India\",\"experience_min_years\":0,\"experience_max_years\":2}'::jsonb,clock_timestamp(),clock_timestamp()),
               ($3,$2,'Fictional Java Role','https://www.naukri.com/job-listings-fictional-java-dev-000000000002','naukri','shortlisted','Bengaluru',false,'onsite','senior',ARRAY['Java'],'{\"country\":\"India\",\"experience_min_years\":5,\"experience_max_years\":8}'::jsonb,clock_timestamp() - interval '1 day',clock_timestamp() - interval '1 day'),
               ($4,$2,'Rust Platform Engineer','https://www.naukri.com/job-listings-fictional-rust-plat-000000000003','naukri','applied','Remote',true,'remote','junior',ARRAY['Rust'],'{\"country\":\"India\"}'::jsonb,clock_timestamp() - interval '2 days',clock_timestamp() - interval '2 days')",
    )
    .bind(job_rust)
    .bind(company_id)
    .bind(job_other)
    .bind(job_applied)
    .execute(&mut c)
    .await
    .unwrap();

    sqlx::query(
        "INSERT INTO job_source_observations(id,job_id,source,source_job_id,original_url,verification_status)
         VALUES($1,$2,'naukri','000000000001','https://www.naukri.com/job-listings-fictional-rust-dev-000000000001','observed')",
    )
    .bind(Uuid::new_v4())
    .bind(job_rust)
    .execute(&mut c)
    .await
    .unwrap();

    let (url, stop, server) = http_fixture().await;
    let http = client();

    for path in [
        "/api/v1/jobs/search",
        "/api/v1/integrations",
        "/api/v1/startups/integrations/status",
        "/api/v1/dashboard/connections",
        "/api/v1/dashboard/onboarding/manifest",
        "/api/v1/dashboard/presets",
        "/api/v1/browser-applications/policy",
    ] {
        assert_eq!(
            http.get(format!("{url}{path}")).send().await.unwrap().status(),
            401
        );
    }

    let search: Value = http
        .get(format!(
            "{url}/api/v1/jobs/search?application_status=not_applied&role=Rust&sort=match&minimum_match_score=50&approved_experience_fit=true&exclude_preferences=false&page=1&limit=20"
        ))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(search["total"], 1);
    assert_eq!(search["jobs"][0]["id"], json!(job_rust.to_string()));
    assert_eq!(search["jobs"][0]["experience_fit"], "within_published_range");
    assert_eq!(search["jobs"][0]["source_observations"].as_array().map(Vec::len), Some(1));

    assert_eq!(
        http.get(format!("{url}/api/v1/jobs/search?sort=invalid"))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        422
    );

    let integrations: Value = http
        .get(format!("{url}/api/v1/integrations"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert!(
        integrations["connectors"]
            .as_array()
            .is_some_and(|rows| rows.iter().any(|r| r["platform"] == "gmail"))
    );
    assert!(integrations["startup_discovery"]["providers"].is_array());

    let startup_status: Value = http
        .get(format!("{url}/api/v1/startups/integrations/status"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(startup_status, integrations["startup_discovery"]);

    let connections: Value = http
        .get(format!("{url}/api/v1/dashboard/connections"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(connections["providers"].as_array().map(Vec::len), Some(4));

    let manifest: Value = http
        .get(format!("{url}/api/v1/dashboard/onboarding/manifest"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(manifest["facts_verified"], json!(false));

    let policy: Value = http
        .get(format!("{url}/api/v1/browser-applications/policy"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(policy["credentials"], json!(false));
    assert!(policy["digest"].as_str().is_some_and(|s| s.len() == 64));

    let saved: Value = http
        .post(format!("{url}/api/v1/dashboard/presets"))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({
            "name": "Early Rust",
            "filters": {"roles": ["Rust Engineer"]}
        }))
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(saved["presets"].as_array().map(Vec::len), Some(1));
    assert_eq!(saved["presets"][0]["name"], "Early Rust");

    let fetched: Value = http
        .get(format!("{url}/api/v1/dashboard/presets"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(fetched, saved);

    stop.cancel();
    server.await.unwrap();
}
