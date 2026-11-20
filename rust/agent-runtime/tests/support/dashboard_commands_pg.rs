#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn dashboard_commands_commit_one_draft_and_receipt_with_separate_selection() {
    const MEMORY: &str = "dashboard_conversation:primary";
    let (mut database, job) = packet_service_fixture().await;
    sqlx::raw_sql(
        "CREATE TABLE agent_operations(
            key varchar(180) PRIMARY KEY,actor varchar(120) NOT NULL,
            command varchar(50) NOT NULL,payload_hash varchar(64) NOT NULL,
            result jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE agent_policies(key varchar(20) PRIMARY KEY,version integer NOT NULL,preferences jsonb NOT NULL);
        ALTER TABLE jobs ADD COLUMN IF NOT EXISTS match_score numeric;
        UPDATE jobs SET match_score=100,date_posted=clock_timestamp();
        INSERT INTO owner_preferences(key,value) VALUES ('application_queue_policy','{\"state\":\"STOPPED\",\"revision\":162}');",
    )
    .execute(&mut database)
    .await
    .unwrap();
    let telegram = automated_apply_agents::telegram_local::context_key(111);
    let telegram_memory = json!({"fixture":"independent"});
    sqlx::query("INSERT INTO owner_preferences(key,value) VALUES($1,$2)")
        .bind(&telegram)
        .bind(&telegram_memory)
        .execute(&mut database)
        .await
        .unwrap();
    let memory = |key: &str| {
        sqlx::query_scalar::<_, Value>("SELECT value FROM owner_preferences WHERE key=$1")
            .bind(key.to_owned())
    };
    let (base, stop, server) = http_fixture().await;
    let (other_base, other_stop, other_server) = http_fixture().await;
    let route = format!("{base}/api/v1/agent/commands");
    let other_route = format!("{other_base}/api/v1/agent/commands");
    let http = client();
    let post = |url: &str, input: &Value| http.post(url).bearer_auth(HOST_TOKEN).json(input);
    let turn = |text: &str| json!({"text":text,"request_id":Uuid::new_v4()});
    let search = turn("Find Rust jobs");
    assert_eq!(
        http.post(&route)
            .json(&search)
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    assert_eq!(
        post(&route, &search)
            .header("x-agent-client", "extension")
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    assert_eq!(
        post(&route, &search)
            .header("origin", "https://untrusted.example")
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    let method = http
        .get(&route)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(method.status(), 405);
    assert_eq!(method.headers()["allow"], "POST");
    let mut escalation = search.clone();
    escalation["intent"] = json!({"category":"PREPARE_APPLICATION"});
    assert_eq!(
        post(&route, &escalation).send().await.unwrap().status(),
        422
    );
    assert_eq!(
        post(&format!("{route}?owner=telegram"), &search)
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    assert!(
        memory(MEMORY)
            .fetch_optional(&mut database)
            .await
            .unwrap()
            .is_none()
    );

    let parse = |response: reqwest::Response| async move {
        let status = response.status();
        let body: Value = response.json().await.unwrap();
        assert_eq!(status, 200, "{body}");
        assert_eq!(body["capability"], "preview_only");
        assert_eq!(body["data"]["submitted"], false);
        body
    };
    let found = parse(post(&route, &search).send().await.unwrap()).await;
    assert_eq!(found["data"]["status"], "selection_required");
    assert!(
        found["data"]["reply"]
            .as_str()
            .unwrap()
            .contains("Rust Engineer")
    );
    let selected = parse(post(&route, &turn("1")).send().await.unwrap()).await;
    assert_eq!(selected["data"]["status"], "job_details");
    let before = memory(MEMORY).fetch_one(&mut database).await.unwrap();
    assert_eq!(before["selected_job_id"], json!(job));

    let prepare = turn("prepare selected job");
    sqlx::raw_sql(
        "CREATE FUNCTION reject_dashboard_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RETURN NULL; END $$;
        CREATE TRIGGER reject_dashboard_receipt BEFORE INSERT ON agent_operations
        FOR EACH ROW EXECUTE FUNCTION reject_dashboard_receipt();",
    )
    .execute(&mut database)
    .await
    .unwrap();
    let refused = post(&route, &prepare).send().await.unwrap();
    let refused_status = refused.status();
    let refused: Value = refused.json().await.unwrap();
    assert_eq!(refused_status, 409, "{refused}");
    assert_eq!(refused["detail"], "local_command_write_ack_failed");
    assert_eq!(
        memory(MEMORY).fetch_one(&mut database).await.unwrap(),
        before
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM application_packets")
            .fetch_one(&mut database)
            .await
            .unwrap(),
        0
    );
    sqlx::query("DROP TRIGGER reject_dashboard_receipt ON agent_operations")
        .execute(&mut database)
        .await
        .unwrap();
    let (first, replay) = tokio::join!(
        post(&route, &prepare).send(),
        post(&other_route, &prepare).send()
    );
    let first = parse(first.unwrap()).await;
    let replay = parse(replay.unwrap()).await;
    assert_eq!(first, replay);
    assert_eq!(first["data"]["status"], "prepared_for_review");
    assert_eq!(first["data"]["job_id"], json!(job));
    assert!(first["data"]["packet_id"].is_string());
    let mut conflict = prepare.clone();
    conflict["text"] = json!("reset conversation");
    assert_eq!(post(&route, &conflict).send().await.unwrap().status(), 409);
    let unsafe_turn = parse(
        post(&route, &turn("submit and send an email"))
            .send()
            .await
            .unwrap(),
    )
    .await;
    assert_eq!(unsafe_turn["data"]["status"], "help");
    let reset = parse(post(&route, &turn("/reset")).send().await.unwrap()).await;
    assert_eq!(reset["data"]["status"], "context_reset");
    let cleared = memory(MEMORY).fetch_one(&mut database).await.unwrap();
    assert_eq!(cleared["selected_job_id"], Value::Null);
    assert_ne!(cleared["conversation_id"], before["conversation_id"]);
    assert_eq!(
        parse(post(&route, &prepare).send().await.unwrap()).await,
        first
    );
    assert_eq!(
        memory(MEMORY).fetch_one(&mut database).await.unwrap(),
        cleared
    );
    assert_eq!(
        memory(&telegram).fetch_one(&mut database).await.unwrap(),
        telegram_memory
    );
    assert_eq!(
        memory("application_queue_policy")
            .fetch_one(&mut database)
            .await
            .unwrap(),
        json!({"state":"STOPPED","revision":162})
    );
    for (query, expected) in [
        (
            "SELECT count(*) FROM application_packets WHERE approved_revision IS NULL",
            1,
        ),
        (
            "SELECT count(*) FROM application_events WHERE event_type='packet_created'",
            1,
        ),
        ("SELECT count(*) FROM application_submission_evidence", 0),
        (
            "SELECT count(*) FROM owner_preferences WHERE starts_with(key,'apply_budget:')",
            0,
        ),
        (
            "SELECT count(*) FROM agent_operations WHERE actor='owner:primary' AND command='dashboard_conversation'",
            5,
        ),
    ] {
        assert_eq!(
            sqlx::query_scalar::<_, i64>(query)
                .fetch_one(&mut database)
                .await
                .unwrap(),
            expected,
            "{query}"
        );
    }
    stop.cancel();
    other_stop.cancel();
    server.await.unwrap();
    other_server.await.unwrap();
}
