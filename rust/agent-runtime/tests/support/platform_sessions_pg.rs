#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn portal_owner_manual_observation_and_forget_route_preserve_gesture_replay() {
    let mut c = browser_fixture().await;
    let (base, stop, service) = http_fixture_values(browser_values()).await;
    let platform_url = format!("{base}/api/v1/local-agent/platforms");
    let native_url = format!("{base}/api/v1/local-agent/chrome");
    let client = client();
    let accepted: Value = client
        .post(format!("{platform_url}/instahyre/accept-manual"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(accepted["state"], "manual_only");
    assert_eq!(accepted["manual_capability_accepted"], true);

    let input = json!({"request_id":Uuid::new_v4(),"command":"observe_platform_session",
        "url":"https://www.instahyre.com/private-path-canary?secret=PORTAL_CANARY","observation":"signed_in_indicator"});
    assert_eq!(
        client
            .post(&native_url)
            .bearer_auth(HOST_TOKEN)
            .json(&input)
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    let native = |input: &Value| {
        client
            .post(&native_url)
            .bearer_auth(HOST_TOKEN)
            .header("x-agent-client", BROWSER_EXTENSION)
            .json(input)
    };
    let observed: Value = native(&input)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(observed["ok"], true);
    assert_eq!(observed["data"]["state"], "browser_session_observed");
    assert_eq!(observed["data"]["identity_verified"], false);
    assert_eq!(observed["data"]["api_connected"], false);
    assert_eq!(observed["data"]["manual_capability_accepted"], true);
    let list: Vec<Value> = client
        .get(&platform_url)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    let row = list
        .iter()
        .find(|row| row["platform"] == "instahyre")
        .unwrap();
    assert_eq!(row["state"], "browser_session_observed");
    assert_eq!(row["submission"], "unsupported");
    assert_eq!(row["owner_acceptance_required"], false);
    assert_eq!(
        row["last_verification_time"],
        observed["data"]["last_verification_time"]
    );
    assert_eq!(
        client
            .delete(format!("{platform_url}/instahyre"))
            .bearer_auth(HOST_TOKEN)
            .header("x-agent-client", BROWSER_EXTENSION)
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    let forgotten: Value = client
        .delete(format!("{platform_url}/instahyre"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(forgotten["state"], "owner_action_required");
    assert_eq!(forgotten["manual_capability_accepted"], false);
    assert!(forgotten["last_verification_time"].is_null());
    let replayed: Value = native(&input)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(replayed, observed);
    assert_eq!(browser_pref(&mut c, "portal_instahyre").await, forgotten);

    let mut changed = input.clone();
    changed["observation"] = json!("login_required");
    let conflict: Value = native(&changed)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(conflict["error_code"], "request_id_conflict");
    let saved: Vec<Value> = sqlx::query_scalar(
        "SELECT result FROM agent_operations WHERE command='observe_platform_session'",
    )
    .fetch_all(&mut c)
    .await
    .unwrap();
    assert_eq!(saved, vec![observed]);
    assert!(!saved[0].to_string().contains("private-path-canary"));
    assert!(!saved[0].to_string().contains("PORTAL_CANARY"));
    stop.cancel();
    service.await.unwrap();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn portal_observation_rolls_back_when_replay_record_changes_its_saved_evidence() {
    let mut c = browser_fixture().await;
    sqlx::raw_sql(
        "CREATE OR REPLACE FUNCTION fixture_portal_replay_drift() RETURNS trigger LANGUAGE plpgsql AS $$
         BEGIN UPDATE owner_preferences SET value='{}' WHERE key='portal_naukri'; RETURN NULL; END $$;
         CREATE TRIGGER fixture_portal_replay_drift AFTER INSERT ON agent_operations
         FOR EACH ROW WHEN (NEW.command='observe_platform_session') EXECUTE FUNCTION fixture_portal_replay_drift()",
    ).execute(&mut c).await.unwrap();
    let input = json!({"request_id":Uuid::new_v4(),"command":"observe_platform_session",
        "url":"https://www.naukri.com/nlogin/login","observation":"signed_in_indicator"});
    let outcome = browser_call(&mut c, BrowserRoute::Native, input).await;
    assert_eq!(
        outcome.unwrap_err(),
        Failure("platform_session_write_ack_failed")
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM owner_preferences WHERE key='portal_naukri'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        0
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM agent_operations WHERE command='observe_platform_session'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        0
    );
    sqlx::raw_sql("DROP TRIGGER fixture_portal_replay_drift ON agent_operations; DROP FUNCTION fixture_portal_replay_drift()")
        .execute(&mut c).await.unwrap();
}
