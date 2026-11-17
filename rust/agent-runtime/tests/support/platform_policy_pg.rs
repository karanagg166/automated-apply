async fn platform_policy_fixture(c: &mut PgConnection) {
    let migration = include_str!("../../../../supabase/fresh_public/001_phase1_public.sql");
    let ddl = migration
        .split_once("CREATE TABLE public.agent_policy_events ")
        .unwrap()
        .1
        .split_once("CREATE TABLE public.agent_operations ")
        .unwrap()
        .0;
    sqlx::raw_sql("DROP TABLE IF EXISTS agent_policy_events")
        .execute(&mut *c)
        .await
        .unwrap();
    sqlx::raw_sql(sqlx::AssertSqlSafe(format!(
        "CREATE TABLE public.agent_policy_events {ddl}"
    )))
    .execute(&mut *c)
    .await
    .unwrap();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn dashboard_platform_policy_cas_blocks_extension_fixed_mode_and_stale_edits() {
    let (mut c, settings, identity) = telegram_local_fixture().await;
    platform_policy_fixture(&mut c).await;
    let (base, stop, server) = http_fixture().await;
    let url = format!("{base}/api/v1/local-agent/policy");
    let client = client();
    let defaults: Value = client
        .get(&url)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(defaults["version"], 1);
    assert_eq!(defaults["platforms"]["naukri"], "automatic_preferred");
    assert_eq!(defaults["platforms"]["gmail"], "draft_only");
    assert_eq!(defaults["platforms"]["linkedin"], "manual_only");
    let mut input = json!({"expected_version":1,"platforms":defaults["platforms"]});
    input["platforms"]["wellfound"] = json!("disabled");
    assert_eq!(
        client
            .put(&url)
            .header("x-agent-client", "extension")
            .bearer_auth(HOST_TOKEN)
            .json(&input)
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    let mut invalid = input.clone();
    invalid["platforms"]["gmail"] = json!("automatic_preferred");
    let denied = client
        .put(&url)
        .bearer_auth(HOST_TOKEN)
        .json(&invalid)
        .send()
        .await
        .unwrap();
    assert_eq!(denied.status(), 409);
    assert_eq!(
        denied.json::<Value>().await.unwrap()["detail"],
        "fixed_platform_policy"
    );
    let saved: Value = client
        .put(&url)
        .bearer_auth(HOST_TOKEN)
        .json(&input)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(
        saved,
        json!({"version":2,"default":"approve","platforms":input["platforms"]})
    );
    let stale = client
        .put(&url)
        .bearer_auth(HOST_TOKEN)
        .json(&input)
        .send()
        .await
        .unwrap();
    assert_eq!(stale.status(), 409);
    assert_eq!(
        stale.json::<Value>().await.unwrap()["detail"],
        "policy_version_conflict"
    );
    let events: Vec<(i32, Value)> =
        sqlx::query_as("SELECT version,preferences FROM agent_policy_events")
            .fetch_all(&mut c)
            .await
            .unwrap();
    assert_eq!(
        events,
        vec![(
            2,
            json!({"default":"approve","platforms":input["platforms"]})
        )]
    );
    assert!(
        telegram_answer_update(
            &mut c,
            &settings,
            &identity,
            telegram_update(790, "/apply https://wellfound.com/jobs/fictional")
        )
        .await
        .unwrap()
    );
    assert_eq!(
        telegram_local_result(&mut c, 790).await["error_code"],
        "connection_disabled"
    );
    stop.cancel();
    server.await.unwrap();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn dashboard_platform_policy_event_trigger_drift_rolls_back_policy_and_history() {
    let (mut c, _, _) = telegram_local_fixture().await;
    platform_policy_fixture(&mut c).await;
    sqlx::raw_sql(
        "CREATE OR REPLACE FUNCTION fixture_platform_policy_event_drift() RETURNS trigger LANGUAGE plpgsql AS $$
         BEGIN UPDATE agent_policies SET preferences = jsonb_set(preferences, '{default}', '\"disabled\"') WHERE key='primary'; RETURN NULL; END $$;
         CREATE TRIGGER fixture_platform_policy_event_drift AFTER INSERT ON agent_policy_events
         FOR EACH ROW EXECUTE FUNCTION fixture_platform_policy_event_drift()",
    ).execute(&mut c).await.unwrap();
    let (base, stop, server) = http_fixture().await;
    let url = format!("{base}/api/v1/local-agent/policy");
    let client = client();
    let defaults: Value = client
        .get(&url)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    let response = client
        .put(&url)
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"expected_version":1,"platforms":defaults["platforms"]}))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 409);
    assert_eq!(
        response.json::<Value>().await.unwrap()["detail"],
        "platform_policy_write_ack_failed"
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM agent_policies")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM agent_policy_events")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    stop.cancel();
    server.await.unwrap();
    sqlx::raw_sql("DROP TRIGGER fixture_platform_policy_event_drift ON agent_policy_events; DROP FUNCTION fixture_platform_policy_event_drift()")
        .execute(&mut c).await.unwrap();
}
