#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn telegram_saved_search_checks_history_and_revalidates_a_displayed_selection() {
    let (mut c, settings, identity) = telegram_local_fixture().await;
    sqlx::raw_sql(
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS match_score numeric(5,2);
         UPDATE jobs SET title = 'Fictional data engineering role';
         UPDATE candidate_profiles SET preferences = '{\"remote_preference\":\"remote\"}'",
    )
    .execute(&mut c)
    .await
    .unwrap();
    let selected = Uuid::new_v4();
    let uncertain = Uuid::new_v4();
    for (id, title, url) in [
        (
            selected,
            "Fictional Rust Engineer",
            "https://www.naukri.com/job-listings-fictional-123456789012?secret=QUERY_CANARY#FRAGMENT_CANARY",
        ),
        (
            uncertain,
            "Quarantined Rust Engineer",
            "https://www.naukri.com/job-listings-uncertain-123456789013",
        ),
    ] {
        sqlx::query(
            "INSERT INTO jobs(id, title, job_url, date_posted, created_at, match_score)
             VALUES($1,$2,$3,clock_timestamp(),clock_timestamp(),85)",
        )
        .bind(id)
        .bind(title)
        .bind(url)
        .execute(&mut c)
        .await
        .unwrap();
    }
    let work_key = format!("apply_work:{}", Uuid::new_v4());
    let work = json!({"job_id":uncertain,"stage":"SUBMISSION_UNKNOWN","admitted_actions":[]});
    browser_save(&mut c, &work_key, work.clone()).await;
    let packets: i64 = sqlx::query_scalar("SELECT count(*) FROM application_packets")
        .fetch_one(&mut c)
        .await
        .unwrap();

    let mut stranger = telegram_update(780, "Find Rust jobs");
    stranger["message"]["from"]["id"] = json!(999);
    assert!(
        !telegram_answer_update(&mut c, &settings, &identity, stranger)
            .await
            .unwrap()
    );
    let search = telegram_update(781, "Find Rust jobs");
    assert!(
        telegram_answer_update(&mut c, &settings, &identity, search.clone())
            .await
            .unwrap()
    );
    let outcome = telegram_local_result(&mut c, 781).await;
    assert_eq!(outcome["data"]["status"], "selection_required");
    let reply = outcome["data"]["reply"].as_str().unwrap();
    assert!(reply.contains("Fictional Rust Engineer"));
    for excluded in [
        "Quarantined Rust Engineer",
        "QUERY_CANARY",
        "FRAGMENT_CANARY",
    ] {
        assert!(!reply.contains(excluded));
    }
    let key = automated_apply_agents::telegram_local::context_key(11);
    assert_eq!(
        browser_pref(&mut c, &key).await["job_ids"],
        json!([selected])
    );
    assert!(
        !telegram_answer_update(&mut c, &settings, &identity, search)
            .await
            .unwrap()
    );
    assert_eq!(telegram_local_result(&mut c, 781).await, outcome);

    assert!(
        telegram_answer_update(&mut c, &settings, &identity, telegram_update(782, "show 1"))
            .await
            .unwrap()
    );
    assert_eq!(
        telegram_local_result(&mut c, 782).await["data"]["status"],
        "job_details"
    );
    sqlx::query("UPDATE jobs SET status='applied' WHERE id=$1")
        .bind(selected)
        .execute(&mut c)
        .await
        .unwrap();
    assert!(
        telegram_answer_update(&mut c, &settings, &identity, telegram_update(783, "show 1"))
            .await
            .unwrap()
    );
    let blocked = telegram_local_result(&mut c, 783).await;
    assert_eq!(blocked["data"]["status"], "selection_required");
    assert_eq!(blocked["data"]["submitted"], false);
    assert_eq!(browser_pref(&mut c, &work_key).await, work);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM application_packets")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        packets
    );
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn cached_search_preferences_http_replacement_and_trigger_ack() {
    let (mut c, _) = packet_service_fixture().await;
    let (base, stop, server) = http_fixture().await;
    let endpoint = format!("{base}/api/v1/local-agent/search-preferences");
    let client = client();
    assert_eq!(client.get(&endpoint).send().await.unwrap().status(), 401);
    let defaults: Value = client
        .get(&endpoint)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(defaults["application_status"], "not_applied");

    let first: Value = client
        .put(&endpoint)
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"target_titles":["Rust Engineer"],"remote_preference":"remote"}))
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(first["target_titles"], json!(["Rust Engineer"]));
    let second: Value = client
        .put(&endpoint)
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"remote_preference":"onsite"}))
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(second["target_titles"], defaults["target_titles"]);
    assert_eq!(second["remote_preference"], "onsite");
    assert_eq!(
        client
            .put(&endpoint)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"require_known_properties":false}))
            .send()
            .await
            .unwrap()
            .status(),
        422
    );

    sqlx::raw_sql(
        "CREATE FUNCTION pg_temp.suppress_cached_search_preferences() RETURNS trigger
         LANGUAGE plpgsql AS $$ BEGIN RETURN NULL; END $$;
         CREATE TRIGGER suppress_cached_search_preferences BEFORE UPDATE ON owner_preferences
         FOR EACH ROW WHEN (NEW.key = 'agent_search_preferences')
         EXECUTE FUNCTION pg_temp.suppress_cached_search_preferences()",
    )
    .execute(&mut c)
    .await
    .unwrap();
    assert_eq!(
        client
            .put(&endpoint)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"remote_preference":"hybrid"}))
            .send()
            .await
            .unwrap()
            .status(),
        409
    );
    assert_eq!(
        browser_pref(&mut c, "agent_search_preferences").await,
        second
    );
    stop.cancel();
    server.await.unwrap();
}
