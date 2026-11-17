#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn owner_commands_restore_extension_preview_and_keep_history_private() {
    let mut c = browser_fixture().await;
    sqlx::raw_sql("CREATE TABLE IF NOT EXISTS agent_policies(key varchar(20) PRIMARY KEY,version integer NOT NULL,preferences jsonb NOT NULL); DELETE FROM agent_policies")
        .execute(&mut c).await.unwrap();
    let (base, stop, service) = http_fixture_values(browser_values()).await;
    let owner = format!("{base}/api/v1/local-agent/commands");
    let native = format!("{base}/api/v1/local-agent/chrome");
    let history = format!("{base}/api/v1/local-agent/history");
    let client = client();
    let request = Uuid::new_v4();
    let input = json!({"request_id":request,"command":"preview_application_url",
        "url":"https://www.instahyre.com/fictional?token=PRIVATE_URL_CANARY#PRIVATE_FRAGMENT",
        "title":"UNTRUSTED_TITLE_CANARY"});
    assert_eq!(
        client
            .post(&owner)
            .json(&input)
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    assert_eq!(
        client
            .post(&owner)
            .bearer_auth(HOST_TOKEN)
            .header("x-agent-client", BROWSER_EXTENSION)
            .json(&input)
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    assert_eq!(
        client
            .post(&native)
            .bearer_auth(HOST_TOKEN)
            .json(&input)
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    let owner_call = |body: &Value| client.post(&owner).bearer_auth(HOST_TOKEN).json(body);
    let native_call = |body: &Value| {
        client
            .post(&native)
            .bearer_auth(HOST_TOKEN)
            .header("x-agent-client", BROWSER_EXTENSION)
            .json(body)
    };
    let first: Value = owner_call(&input)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    let replay: Value = owner_call(&input)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(first, replay);
    assert_eq!(first["data"]["url"], input["url"]);
    assert_eq!(first["data"]["page_inspected"], false);
    assert_eq!(first["data"]["submitted"], false);
    assert_eq!(first["data"]["policy"]["paid_calls_allowed"], false);
    assert!(!first.to_string().contains("UNTRUSTED_TITLE_CANARY"));
    let preview: Value = native_call(&input)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(preview["data"], first["data"]);
    assert_ne!(preview["correlation_id"], first["correlation_id"]);
    let connection_status: Value = native_call(&json!({"command":"connection_status"}))
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    let connections = connection_status["data"]["connections"].as_array().unwrap();
    assert!(connections.iter().any(|row| row["name"] == "Rust API"));
    assert!(
        connections
            .iter()
            .all(|row| row.as_object().unwrap().len() == 3)
    );
    let mut changed = input.clone();
    changed["url"] = json!("https://www.instahyre.com/different");
    let conflict: Value = owner_call(&changed)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(conflict["error_code"], "request_id_conflict");

    let url_filter: Value = owner_call(&json!({"command":"preview_job_filters"}))
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(url_filter["data"]["executed"], false);
    assert_eq!(
        url_filter["data"]["preferences"]["application_status"],
        "not_applied"
    );
    let policy: Value = owner_call(&json!({"command":"get_application_policy"}))
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(policy["data"]["version"], 1);
    let discovery: Value = owner_call(&json!({"command":"get_discovery_status"}))
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(discovery["data"]["discovery_executed"], false);
    let denied: Value = owner_call(&json!({"command":"naukri_queue_control","queue_action":"start","expected_queue_revision":0}))
        .send().await.unwrap().error_for_status().unwrap().json().await.unwrap();
    assert_eq!(denied["error_code"], "extension_identity_required");
    let denied: Value = owner_call(&json!({"command":"conversation"}))
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(denied["error_code"], "telegram_identity_required");
    let rows: Vec<Value> = client
        .get(&history)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    let previews = rows
        .iter()
        .filter(|row| row["command"] == "preview_application_url")
        .collect::<Vec<_>>();
    assert_eq!(previews.len(), 2);
    assert!(previews.iter().any(|row| row["actor"] == "owner:primary"));
    assert!(
        previews
            .iter()
            .all(|row| row["result"]["data"]["platform"] == "instahyre")
    );
    let history_text = serde_json::to_string(&rows).unwrap();
    assert!(!history_text.contains("PRIVATE_URL_CANARY"));
    assert!(!history_text.contains("PRIVATE_FRAGMENT"));
    assert!(!history_text.contains("UNTRUSTED_TITLE_CANARY"));
    let retained: Value = sqlx::query_scalar("SELECT result FROM agent_operations WHERE key=$1")
        .bind(format!("owner:primary:{request}"))
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(retained, first);
    stop.cancel();
    service.await.unwrap();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn concurrent_owner_commands_return_one_durable_receipt_and_reject_after_trigger_drift() {
    let mut c = browser_fixture().await;
    let (first, stop_first, service_first) = http_fixture().await;
    let (second, stop_second, service_second) = http_fixture().await;
    let input = json!({"command":"get_agent_capabilities","request_id":Uuid::new_v4()});
    sqlx::raw_sql(
        "CREATE OR REPLACE FUNCTION fixture_local_command_race() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN PERFORM pg_advisory_xact_lock(426802,1); RETURN NEW; END $$;
         CREATE TRIGGER fixture_local_command_race BEFORE INSERT ON agent_operations
          FOR EACH ROW WHEN (NEW.command='get_agent_capabilities') EXECUTE FUNCTION fixture_local_command_race()",
    ).execute(&mut c).await.unwrap();
    let mut holder = connection().await;
    let mut hold = holder.begin().await.unwrap();
    sqlx::query("SELECT pg_advisory_xact_lock(426802,1)")
        .execute(&mut *hold)
        .await
        .unwrap();
    let call = |base: String| {
        let input = input.clone();
        tokio::spawn(async move {
            client()
                .post(format!("{base}/api/v1/local-agent/commands"))
                .bearer_auth(HOST_TOKEN)
                .json(&input)
                .send()
                .await
                .unwrap()
                .error_for_status()
                .unwrap()
                .json::<Value>()
                .await
                .unwrap()
        })
    };
    let a = call(first.clone());
    let b = call(second);
    tokio::time::timeout(Duration::from_secs(1), async {
        loop {
            let waiting: i64 = sqlx::query_scalar("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND classid=426802 AND objid=1 AND NOT granted")
                .fetch_one(&mut c).await.unwrap();
            if waiting == 2 { break; }
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    }).await.unwrap();
    hold.rollback().await.unwrap();
    assert_eq!(a.await.unwrap(), b.await.unwrap());
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM agent_operations")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        1
    );
    sqlx::raw_sql(
        "DROP TRIGGER fixture_local_command_race ON agent_operations; DROP FUNCTION fixture_local_command_race();
         CREATE OR REPLACE FUNCTION fixture_local_command_drift() RETURNS trigger LANGUAGE plpgsql AS $$
         BEGIN UPDATE agent_operations SET result='{}' WHERE key=NEW.key; RETURN NULL; END $$;
         CREATE TRIGGER fixture_local_command_drift AFTER INSERT ON agent_operations
          FOR EACH ROW WHEN (NEW.command='get_agent_capabilities') EXECUTE FUNCTION fixture_local_command_drift()",
    ).execute(&mut c).await.unwrap();
    let drift = client()
        .post(format!("{first}/api/v1/local-agent/commands"))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"request_id":Uuid::new_v4(),"command":"get_agent_capabilities"}))
        .send()
        .await
        .unwrap();
    assert_eq!(drift.status(), 409);
    assert_eq!(
        drift.json::<Value>().await.unwrap()["detail"],
        "local_command_write_ack_failed"
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM agent_operations")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        1
    );
    stop_first.cancel();
    stop_second.cancel();
    service_first.await.unwrap();
    service_second.await.unwrap();
    sqlx::raw_sql("DROP TRIGGER fixture_local_command_drift ON agent_operations; DROP FUNCTION fixture_local_command_drift()")
        .execute(&mut c).await.unwrap();
}
