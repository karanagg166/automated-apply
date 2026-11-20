#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn dashboard_legacy_automation_reads_saved_discovery_without_activating_it() {
    let mut database = knowledge_fixture().await;
    sqlx::raw_sql(
        "CREATE TABLE automation_schedule (
            key text PRIMARY KEY,version int NOT NULL,enabled bool NOT NULL,
            configuration jsonb NOT NULL, next_run_at timestamptz,
            last_run_at timestamptz, heartbeat_at timestamptz
         );
         CREATE TABLE automation_executions (
            id uuid PRIMARY KEY,source text,trigger_type text,state text,created_at timestamptz,
            started_at timestamptz,finished_at timestamptz,diagnostic text,outcome jsonb NOT NULL,
            discovery_run_id uuid,attempts int,available_at timestamptz,lease_until timestamptz
         );
         CREATE TABLE automation_matches (
            job_id uuid PRIMARY KEY,profile_id uuid NOT NULL,profile_version int NOT NULL,
            scored_at timestamptz NOT NULL,result jsonb NOT NULL
         );",
    )
    .execute(&mut database)
    .await
    .unwrap();
    let (base, stop, server) = http_fixture().await;
    let http = client();
    let path = format!("{base}/api/v1/dashboard/automation");
    let authorized = |suffix: &str| http.get(format!("{path}{suffix}")).bearer_auth(HOST_TOKEN);
    let decode = |response: reqwest::Response| async move {
        let status = response.status();
        let value: Value = response.json().await.unwrap();
        assert_eq!(status, 200, "{value}");
        value
    };

    assert_eq!(http.get(&path).send().await.unwrap().status(), 401);
    let empty = decode(authorized("").send().await.unwrap()).await;
    assert_eq!(empty["state"], "disabled");
    assert_eq!(empty["configuration"]["sources"], json!([]));
    assert_eq!(empty["configuration"]["interval_seconds"], 21600);
    assert_eq!(empty["configuration"]["limit"], 20);
    assert_eq!(empty["worker_ready"], false);
    assert_eq!(empty["matching"], "awaiting_profile_approval");
    assert_eq!(
        decode(authorized("/history").send().await.unwrap()).await,
        json!({"executions":[]})
    );
    assert_eq!(
        decode(authorized("/matches").send().await.unwrap()).await,
        json!({"matches":[]})
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM automation_schedule")
            .fetch_one(&mut database)
            .await
            .unwrap(),
        0
    );

    let profile = profile_pin();
    let saved = json!({
        "sources":["arbeitnow"],"interval_seconds":600,
        "approved_profile_id":profile.id,"approved_profile_version":profile.version
    });
    sqlx::query(
        "INSERT INTO automation_schedule VALUES('primary',4,true,$1,NULL,NULL,clock_timestamp())",
    )
    .bind(&saved)
    .execute(&mut database)
    .await
    .unwrap();
    let completed = Uuid::new_v4();
    let active = Uuid::new_v4();
    sqlx::query(
        "INSERT INTO automation_executions(id,source,trigger_type,state,created_at,outcome) VALUES
            ($1,'arbeitnow','manual','completed',clock_timestamp()-interval '1 minute','{}'),
            ($2,'arbeitnow','scheduled','claimed',clock_timestamp(),'{}')",
    )
    .bind(completed)
    .bind(active)
    .execute(&mut database)
    .await
    .unwrap();
    let top_job = Uuid::new_v4();
    let bottom_job = Uuid::new_v4();
    let stale_job = Uuid::new_v4();
    sqlx::query(
        "INSERT INTO automation_matches VALUES
            ($1,$4,$5,clock_timestamp()-interval '1 minute','{\"match_score\":95,\"job_id\":\"untrusted\"}'),
            ($2,$4,$5,clock_timestamp(),'{\"match_score\":70}'),
            ($3,$4,$5-1,clock_timestamp(),'{\"match_score\":100}')",
    )
    .bind(top_job).bind(bottom_job).bind(stale_job).bind(profile.id).bind(profile.version)
    .execute(&mut database).await.unwrap();
    let status = decode(authorized("").send().await.unwrap()).await;
    assert_eq!(status["version"], 4);
    assert_eq!(status["matching"], "approved");
    assert_eq!(status["state"], "awaiting_configuration");
    assert_eq!(status["worker_ready"], false);
    assert_eq!(status["active_executions"], 1);
    let all = decode(authorized("/history?limit=1").send().await.unwrap()).await;
    assert_eq!(all["executions"][0]["id"], json!(active));
    for query in ["/history?state=completed", "/history?limit=1&offset=1"] {
        let filtered = decode(authorized(query).send().await.unwrap()).await;
        assert_eq!(filtered["executions"].as_array().unwrap().len(), 1);
        assert_eq!(filtered["executions"][0]["id"], json!(completed));
    }
    let matches = decode(authorized("/matches").send().await.unwrap()).await;
    assert_eq!(matches["matches"].as_array().unwrap().len(), 2);
    assert_eq!(matches["matches"][0]["job_id"], json!(top_job));
    assert_eq!(matches["matches"][1]["job_id"], json!(bottom_job));
    for suffix in [
        "/history?state=other",
        "/history?limit=101",
        "/history?state=claimed&state=completed",
        "/matches?limit=2",
    ] {
        assert_eq!(authorized(suffix).send().await.unwrap().status(), 422);
    }
    assert_eq!(
        http.put(&path)
            .bearer_auth(HOST_TOKEN)
            .json(&saved)
            .send()
            .await
            .unwrap()
            .status(),
        405
    );
    let retained: Value = sqlx::query_scalar(
        "SELECT configuration FROM automation_schedule WHERE key='primary' AND version=4",
    )
    .fetch_one(&mut database)
    .await
    .unwrap();
    assert_eq!(retained, saved);
    sqlx::query("UPDATE candidate_profiles SET version=version+1 WHERE id=$1")
        .bind(profile.id)
        .execute(&mut database)
        .await
        .unwrap();
    assert_eq!(
        decode(authorized("/matches").send().await.unwrap()).await,
        json!({"matches":[]})
    );
    stop.cancel();
    server.await.unwrap();
}
