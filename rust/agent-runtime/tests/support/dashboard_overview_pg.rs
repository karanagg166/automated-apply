#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn dashboard_runtime_and_overview_project_saved_counts_and_enforce_owner_boundaries() {
    let mut c = knowledge_fixture().await;
    sqlx::raw_sql(
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS match_score numeric(5,2);
         CREATE TABLE IF NOT EXISTS startup_shortlist_entries (
             company_id uuid PRIMARY KEY REFERENCES companies(id) ON DELETE CASCADE,
             run_id uuid,
             snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
             note text,
             created_at timestamptz NOT NULL DEFAULT clock_timestamp()
         );
         CREATE TABLE IF NOT EXISTS outreach_logs (
             id uuid PRIMARY KEY,
             approval_status varchar(50) NOT NULL DEFAULT 'draft_created'
         );",
    )
    .execute(&mut c)
    .await
    .unwrap();

    let company1 = Uuid::new_v4();
    let company2 = Uuid::new_v4();
    for (id, name) in [(company1, "Fictional One"), (company2, "Fictional Two")] {
        sqlx::query("INSERT INTO companies(id,name) VALUES($1,$2)")
            .bind(id)
            .bind(name)
            .execute(&mut c)
            .await
            .unwrap();
    }
    sqlx::query("INSERT INTO startup_shortlist_entries(company_id) VALUES($1)")
        .bind(company1)
        .execute(&mut c)
        .await
        .unwrap();

    let profile_id = profile_pin().id;
    let job_ids = [
        Uuid::new_v4(),
        Uuid::new_v4(),
        Uuid::new_v4(),
        Uuid::new_v4(),
        Uuid::new_v4(),
    ];
    let specs: [(usize, Option<f64>, &str, Option<&str>); 5] = [
        (0, Some(85.0), "discovered", Some("needs_input")),
        (1, Some(70.0), "applied", None),
        (2, Some(69.9), "discovered", Some("user_reported_submitted")),
        (3, None, "discovered", Some("provider_confirmed_submitted")),
        (4, Some(92.0), "shortlisted", Some("ready_for_review")),
    ];
    for (idx, score, status, packet_state) in specs {
        let jid = job_ids[idx];
        sqlx::query(
            "INSERT INTO jobs(id,company_id,title,job_url,source_platform,status,match_score)
             VALUES($1,$2,$3,$4,'naukri',$5,$6)",
        )
        .bind(jid)
        .bind(company1)
        .bind(format!("Fictional Rust Role {idx}"))
        .bind(format!(
            "https://www.naukri.com/job-listings-fictional-overview-{idx:012}"
        ))
        .bind(status)
        .bind(score)
        .execute(&mut c)
        .await
        .unwrap();
        if let Some(state) = packet_state {
            sqlx::query(
                "INSERT INTO application_packets(id,job_id,candidate_profile_id,lifecycle_state)
                 VALUES($1,$2,$3,$4)",
            )
            .bind(Uuid::new_v4())
            .bind(jid)
            .bind(profile_id)
            .bind(state)
            .execute(&mut c)
            .await
            .unwrap();
        }
    }
    for status in ["approved", "draft_created"] {
        sqlx::query("INSERT INTO outreach_logs(id,approval_status) VALUES($1,$2)")
            .bind(Uuid::new_v4())
            .bind(status)
            .execute(&mut c)
            .await
            .unwrap();
    }

    let (url, stop, server) = http_fixture().await;
    let http = client();

    for path in ["/api/v1/dashboard/runtime", "/api/v1/dashboard/overview"] {
        let endpoint = format!("{url}{path}");
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
        let post_resp = http
            .post(&endpoint)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({}))
            .send()
            .await
            .unwrap();
        assert_eq!(post_resp.status(), 405);
        assert_eq!(post_resp.headers()["allow"], "GET");
        assert_eq!(
            http.get(format!("{endpoint}?extra=1"))
                .bearer_auth(HOST_TOKEN)
                .send()
                .await
                .unwrap()
                .status(),
            422
        );
    }

    let runtime: Value = http
        .get(format!("{url}/api/v1/dashboard/runtime"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(
        runtime,
        json!({
            "demo_mode": false,
            "external_notifications_enabled": false,
        })
    );

    let overview: Value = http
        .get(format!("{url}/api/v1/dashboard/overview"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(
        overview,
        json!({
            "startups_discovered": 2,
            "saved_jobs": 5,
            "relevant_jobs": 3,
            "not_yet_applied": 2,
            "shortlisted": 1,
            "applications_prepared": 4,
            "applications_reported_submitted": 1,
            "applications_provider_confirmed": 1,
            "approved_gmail_messages": 1,
            "outstanding_reviews": 2,
        })
    );

    stop.cancel();
    server.await.unwrap();
}
