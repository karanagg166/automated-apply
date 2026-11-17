// Deferred primary-account saved metadata and policy refusal fixtures. No provider IO.
async fn legacy_gmail_fixture() -> PgConnection {
    let (mut c, _, _) = workspace_fixture().await;
    sqlx::raw_sql("CREATE TABLE IF NOT EXISTS connected_accounts(id uuid PRIMARY KEY,provider varchar(30) NOT NULL,google_subject varchar(255) NOT NULL,account_email varchar(254) NOT NULL,encrypted_refresh_token text,encrypted_access_token text,encryption_key_id varchar(64),granted_scopes json NOT NULL,status varchar(30) NOT NULL,token_generation integer NOT NULL DEFAULT 1,token_expires_at timestamptz,connected_at timestamptz NOT NULL,last_verified_at timestamptz,last_refresh_at timestamptz,disconnected_at timestamptz,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),updated_at timestamptz NOT NULL DEFAULT clock_timestamp());DELETE FROM connected_accounts").execute(&mut c).await.unwrap();
    sqlx::query("INSERT INTO connected_accounts(id,provider,google_subject,account_email,granted_scopes,status,connected_at,last_verified_at,encrypted_refresh_token,encrypted_access_token) VALUES($1,'gmail','fictional-primary','fixture@example.com',$2,'connected',clock_timestamp(),clock_timestamp(),'PRIVATE_PRIMARY_REFRESH_CANARY','PRIVATE_PRIMARY_ACCESS_CANARY')").bind(Uuid::from_u128(301)).bind(json!(scopes(GrantMode::Metadata))).execute(&mut c).await.unwrap();
    c
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_legacy_saved_status_is_read_only_without_owner_lock_credentials_or_live_claim() {
    let mut c = legacy_gmail_fixture().await;
    let before = browser_snapshot(&mut c).await;
    let mut other = connection().await;
    let mut lock = other.begin().await.unwrap();
    sqlx::query(
        "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
    )
    .execute(&mut *lock)
    .await
    .unwrap();
    sqlx::query("SET lock_timeout='100ms'")
        .execute(&mut c)
        .await
        .unwrap();
    let result = automated_apply_agents::gmail_legacy::status(&mut c, &gmail_read_settings(), true)
        .await
        .unwrap();
    assert_eq!(result["status"], "connected");
    assert_eq!(result["live_verified"], false);
    assert_eq!(result["verification_recorded"], true);
    assert_eq!(result["sending_enabled"], false);
    assert_eq!(result["permissions"]["send"], false);
    assert!(
        !result
            .to_string()
            .contains("PRIVATE_PRIMARY_REFRESH_CANARY")
    );
    assert!(!result.to_string().contains("PRIVATE_PRIMARY_ACCESS_CANARY"));
    assert_eq!(browser_snapshot(&mut c).await, before);
    lock.rollback().await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_legacy_status_fails_closed_for_ambiguous_primary_accounts_and_restricts_disallowed_mailbox()
 {
    let mut c = legacy_gmail_fixture().await;
    sqlx::query("UPDATE connected_accounts SET account_email='unapproved@example.com'")
        .execute(&mut c)
        .await
        .unwrap();
    let result =
        automated_apply_agents::gmail_legacy::status(&mut c, &gmail_read_settings(), false)
            .await
            .unwrap();
    assert_eq!(result["authorization_state"], "account_not_authorized");
    assert_eq!(result["permissions"]["read_metadata"], false);
    sqlx::query("INSERT INTO connected_accounts(id,provider,google_subject,account_email,encrypted_refresh_token,encrypted_access_token,encryption_key_id,granted_scopes,status,token_generation,token_expires_at,connected_at,last_verified_at,last_refresh_at,disconnected_at,created_at,updated_at) SELECT $1,provider,google_subject,'other@example.com',encrypted_refresh_token,encrypted_access_token,encryption_key_id,granted_scopes,status,token_generation,token_expires_at,connected_at,last_verified_at,last_refresh_at,disconnected_at,created_at,updated_at FROM connected_accounts LIMIT 1").bind(Uuid::from_u128(302)).execute(&mut c).await.unwrap();
    assert_eq!(
        automated_apply_agents::gmail_legacy::status(&mut c, &gmail_read_settings(), false)
            .await
            .unwrap_err(),
        Failure("gmail_legacy_identity_requires_review")
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_legacy_missing_schema_or_empty_account_returns_honest_setup_and_not_connected_status()
 {
    let mut c = legacy_gmail_fixture().await;
    sqlx::query("DELETE FROM connected_accounts")
        .execute(&mut c)
        .await
        .unwrap();
    let result =
        automated_apply_agents::gmail_legacy::status(&mut c, &gmail_read_settings(), false)
            .await
            .unwrap();
    assert_eq!(result["status"], "not_connected");
    assert_eq!(result["schema_ready"], true);
    sqlx::query("DROP TABLE connected_accounts")
        .execute(&mut c)
        .await
        .unwrap();
    let result =
        automated_apply_agents::gmail_legacy::status(&mut c, &gmail_read_settings(), false)
            .await
            .unwrap();
    assert_eq!(result["schema_ready"], false);
    assert_eq!(result["error_code"], "gmail_legacy_schema_update_required");
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_legacy_owner_http_status_and_historical_send_refusals_ignore_old_send_flag_without_data_work()
 {
    let mut c = legacy_gmail_fixture().await;
    let before = browser_snapshot(&mut c).await;
    let accounts: Value =
        sqlx::query_scalar("SELECT jsonb_agg(to_jsonb(a)) FROM connected_accounts a")
            .fetch_one(&mut c)
            .await
            .unwrap();
    let mut values = host_values();
    values.extend(mailbox_values());
    values.insert("GMAIL_SENDING_ENABLED".into(), "true".into());
    let (url, stop, task) = http_fixture_values(values).await;
    let http = client();
    let status = format!("{url}{}", automated_apply_agents::gmail_legacy::STATUS);
    assert_eq!(http.get(&status).send().await.unwrap().status(), 401);
    assert_eq!(
        http.get(&status)
            .bearer_auth(HOST_TOKEN)
            .header("x-agent-client", "extension")
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    let result: Value = http
        .get(&status)
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(result["sending_enabled"], false);
    assert_eq!(result["live_verified"], false);
    assert_eq!(
        http.get(format!("{status}?probe=true"))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    let mut lock = c.begin().await.unwrap();
    sqlx::query("LOCK TABLE connected_accounts IN ACCESS EXCLUSIVE MODE")
        .execute(&mut *lock)
        .await
        .unwrap();
    sqlx::query(
        "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
    )
    .execute(&mut *lock)
    .await
    .unwrap();
    for action in ["send", "send-preview"] {
        let endpoint =
            format!("{url}/api/v1/outreach/drafts/11111111-1111-4111-8111-111111111111/{action}");
        assert_eq!(http.post(&endpoint).send().await.unwrap().status(), 401);
        let response=tokio::time::timeout(Duration::from_secs(1),http.post(&endpoint).bearer_auth(HOST_TOKEN).json(&json!({"confirmation_token":"FICTIONAL_PRIVATE_CONFIRMATION_CANARY","sender_account_id":Uuid::from_u128(301)})).send()).await.unwrap().unwrap();
        assert_eq!(response.status(), 409);
        assert_eq!(
            response.json::<Value>().await.unwrap()["detail"],
            json!({"code":"send_blocked","blockers":["gmail_sending_disabled_by_owner_policy"]})
        );
        assert_eq!(
            http.get(endpoint)
                .bearer_auth(HOST_TOKEN)
                .send()
                .await
                .unwrap()
                .status(),
            405
        );
    }
    lock.rollback().await.unwrap();
    assert_eq!(browser_snapshot(&mut c).await, before);
    assert_eq!(
        sqlx::query_scalar::<_, Value>("SELECT jsonb_agg(to_jsonb(a)) FROM connected_accounts a")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        accounts
    );
    stop.cancel();
    task.await.unwrap();
}
