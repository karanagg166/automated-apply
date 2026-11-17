// Deferred saved read-account policies, current projections and selected retained evidence.
fn gmail_read_settings() -> automated_apply_agents::gmail_accounts::Settings {
    automated_apply_agents::gmail_accounts::Settings::from_values(&mailbox_values()).unwrap()
}
async fn gmail_read_fixture() -> (PgConnection, Uuid, Uuid) {
    let mut c = browser_fixture().await;
    sqlx::raw_sql("CREATE TABLE IF NOT EXISTS gmail_read_accounts(id uuid PRIMARY KEY,provider varchar(30) NOT NULL DEFAULT 'gmail',google_subject varchar(255) NOT NULL,account_email varchar(254) NOT NULL UNIQUE,encrypted_refresh_token text,encrypted_access_token text,encryption_key_id varchar(64),granted_scopes json NOT NULL DEFAULT '[]',status varchar(30) NOT NULL DEFAULT 'disconnected',token_generation integer NOT NULL DEFAULT 1,token_expires_at timestamptz,connected_at timestamptz NOT NULL DEFAULT clock_timestamp(),last_verified_at timestamptz,last_refresh_at timestamptz,disconnected_at timestamptz,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),updated_at timestamptz NOT NULL DEFAULT clock_timestamp()); CREATE TABLE IF NOT EXISTS gmail_read_oauth_states(state_hash varchar(64) PRIMARY KEY,provider varchar(30) NOT NULL DEFAULT 'gmail',actor_id varchar(64) NOT NULL,browser_hash varchar(64) NOT NULL,expected_email varchar(254) NOT NULL,connection_generation integer NOT NULL,encrypted_verifier text,encryption_key_id varchar(64) NOT NULL,redirect_uri varchar(2048) NOT NULL,expires_at timestamptz NOT NULL,created_at timestamptz NOT NULL,consumed_at timestamptz,authorization_mode varchar(20) NOT NULL,expected_subject varchar(255));DELETE FROM gmail_read_oauth_states;DELETE FROM gmail_read_accounts").execute(&mut c).await.unwrap();
    let one = Uuid::from_u128(101);
    let two = Uuid::from_u128(102);
    for (id, email, mode) in [
        (one, "fixture@example.com", GrantMode::Metadata),
        (two, "other@example.com", GrantMode::Read),
    ] {
        sqlx::query("INSERT INTO gmail_read_accounts(id,google_subject,account_email,granted_scopes,status,last_verified_at,encrypted_access_token,encrypted_refresh_token,encryption_key_id) VALUES($1,$2,$3,$4,'connected',clock_timestamp(),'PRIVATE_ACCESS_ENVELOPE_CANARY','PRIVATE_REFRESH_ENVELOPE_CANARY','fixture')").bind(id).bind(format!("subject-{id}")).bind(email).bind(json!(scopes(mode))).execute(&mut c).await.unwrap();
    }
    (c, one, two)
}
fn gmail_read_path(id: Uuid, action: &str) -> String {
    format!(
        "{}/{id}{action}",
        automated_apply_agents::gmail_accounts::PATH
    )
}
async fn gmail_read_call(
    c: &mut PgConnection,
    path: &str,
    query: Option<&str>,
    input: Value,
    settings: &automated_apply_agents::gmail_accounts::Settings,
) -> Result<Value> {
    let route = automated_apply_agents::gmail_accounts::route(path).unwrap();
    automated_apply_agents::gmail_accounts::dispatch(
        c,
        route,
        route.method(),
        query,
        input.to_string().as_bytes(),
        settings,
    )
    .await
}
fn gmail_read_policy() -> Value {
    json!({"expected_version":0,"enabled":true,"label_allowlist":["Label_fictional_jobs"]})
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_read_status_lists_saved_metadata_without_token_or_lease_exposure_and_without_owner_lock()
 {
    let (mut c, one, _two) = gmail_read_fixture().await;
    let key = format!("gmail_sync:{}", one.simple());
    browser_save(&mut c,&key,json!({"version":7,"policy":{"enabled":true},"status":"syncing","lease_id":"PRIVATE_LEASE_CANARY","page_token":"PRIVATE_PAGE_CANARY","lease_until":"2099-01-01T00:00:00Z"})).await;
    browser_save(
        &mut c,
        "agent_conversation:primary",
        json!({"retained":true}),
    )
    .await;
    let before = browser_snapshot(&mut c).await;
    let mut other = connection().await;
    let mut owner = other.begin().await.unwrap();
    sqlx::query(
        "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
    )
    .execute(&mut *owner)
    .await
    .unwrap();
    sqlx::query("SET lock_timeout='100ms'")
        .execute(&mut c)
        .await
        .unwrap();
    let list = gmail_read_call(
        &mut c,
        automated_apply_agents::gmail_accounts::PATH,
        None,
        Value::Null,
        &gmail_read_settings(),
    )
    .await
    .unwrap();
    assert_eq!(list["accounts"].as_array().unwrap().len(), 2);
    assert_eq!(list["schema_ready"], true);
    let encoded = list.to_string();
    for canary in [
        "PRIVATE_ACCESS_ENVELOPE_CANARY",
        "PRIVATE_REFRESH_ENVELOPE_CANARY",
        "PRIVATE_LEASE_CANARY",
        "PRIVATE_PAGE_CANARY",
    ] {
        assert!(!encoded.contains(canary));
    }
    let account = gmail_read_call(
        &mut c,
        &gmail_read_path(one, ""),
        None,
        Value::Null,
        &gmail_read_settings(),
    )
    .await
    .unwrap();
    assert_eq!(account["live_verified"], false);
    assert_eq!(account["verification_recorded"], true);
    assert_eq!(account["permissions"]["send"], false);
    assert_eq!(account["permissions"]["read_metadata"], true);
    assert_eq!(account["permissions"]["read_body"], false);
    assert_eq!(browser_snapshot(&mut c).await, before);
    owner.rollback().await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_read_selection_changes_only_requested_policy_generation_and_invalidates_old_sync_lease()
 {
    let (mut c, one, two) = gmail_read_fixture().await;
    let key = format!("gmail_sync:{}", one.simple());
    let mut old = contract_read_policy();
    old["version"] = json!(4);
    old["lease_id"] = json!("old-sync");
    old["page_token"] = json!("old-private-page");
    old["window_start"] = json!("2000-01-01T00:00:00Z");
    browser_save(&mut c, &key, old).await;
    let other = json!({"version":9,"status":"syncing","lease_id":"retained-other-account"});
    browser_save(
        &mut c,
        &format!("gmail_sync:{}", two.simple()),
        other.clone(),
    )
    .await;
    let account_before: Value =
        sqlx::query_scalar("SELECT to_jsonb(a) FROM gmail_read_accounts a WHERE id=$1")
            .bind(one)
            .fetch_one(&mut c)
            .await
            .unwrap();
    let mut input = gmail_read_policy();
    input["expected_version"] = json!(4);
    let result = gmail_read_call(
        &mut c,
        &gmail_read_path(one, "/selection"),
        None,
        input,
        &gmail_read_settings(),
    )
    .await
    .unwrap();
    assert_eq!(result["sync"]["version"], 5);
    assert_eq!(result["sync"]["status"], "ready");
    let saved = browser_pref(&mut c, &key).await;
    assert!(saved.get("lease_id").is_none());
    assert!(saved.get("page_token").is_none());
    assert_eq!(saved["checkpoint"], Value::Null);
    assert_eq!(
        browser_pref(&mut c, &format!("gmail_sync:{}", two.simple())).await,
        other
    );
    assert_eq!(
        sqlx::query_scalar::<_, Value>("SELECT to_jsonb(a) FROM gmail_read_accounts a WHERE id=$1")
            .bind(one)
            .fetch_one(&mut c)
            .await
            .unwrap(),
        account_before
    );
}
fn contract_read_policy() -> Value {
    json!({"version":0,"status":"ready","policy":{"enabled":true}})
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_read_selection_requires_exact_scopes_body_review_and_policy_version() {
    let (mut c, one, two) = gmail_read_fixture().await;
    let mut body = gmail_read_policy();
    body["read_body"] = json!(true);
    body["body_purpose"] = json!("Review fictional selected job evidence");
    for id in [one, two] {
        let before = browser_snapshot(&mut c).await;
        assert_eq!(
            gmail_read_call(
                &mut c,
                &gmail_read_path(id, "/selection"),
                None,
                body.clone(),
                &gmail_read_settings()
            )
            .await
            .unwrap_err(),
            Failure("gmail_body_access_review_required")
        );
        assert_eq!(browser_snapshot(&mut c).await, before);
    }
    let mut values = mailbox_values();
    values.insert("GMAIL_READ_BODY_REVIEWED".into(), "true".into());
    let settings = automated_apply_agents::gmail_accounts::Settings::from_values(&values).unwrap();
    let accepted = gmail_read_call(
        &mut c,
        &gmail_read_path(two, "/selection"),
        None,
        body.clone(),
        &settings,
    )
    .await
    .unwrap();
    assert_eq!(accepted["sync"]["version"], 1);
    assert_eq!(accepted["sync"]["policy"]["read_body"], true);
    let before = browser_snapshot(&mut c).await;
    assert_eq!(
        gmail_read_call(
            &mut c,
            &gmail_read_path(two, "/selection"),
            None,
            body,
            &settings
        )
        .await
        .unwrap_err(),
        Failure("gmail_sync_version_conflict")
    );
    assert_eq!(browser_snapshot(&mut c).await, before);
    sqlx::query("UPDATE gmail_read_accounts SET granted_scopes=$1 WHERE id=$2")
        .bind(json!(scopes(GrantMode::ReadDraft)))
        .bind(one)
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        gmail_read_call(
            &mut c,
            &gmail_read_path(one, "/selection"),
            None,
            gmail_read_policy(),
            &settings
        )
        .await
        .unwrap_err(),
        Failure("gmail_readonly_scope_required")
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_read_policy_concurrent_cas_and_suppressed_ack_cannot_publish_partial_selection() {
    let (mut c, one, _two) = gmail_read_fixture().await;
    let mut other = connection().await;
    let path = gmail_read_path(one, "/selection");
    let settings = gmail_read_settings();
    let (a, b) = tokio::join!(
        gmail_read_call(&mut c, &path, None, gmail_read_policy(), &settings),
        gmail_read_call(&mut other, &path, None, gmail_read_policy(), &settings)
    );
    assert_eq!(usize::from(a.is_ok()) + usize::from(b.is_ok()), 1);
    let before = browser_snapshot(&mut c).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_gmail_selection_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'gmail_sync:') THEN RETURN NULL; END IF; RETURN NEW; END $$; CREATE TRIGGER fixture_gmail_selection_drop BEFORE UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_gmail_selection_drop()").execute(&mut c).await.unwrap();
    let mut input = gmail_read_policy();
    input["expected_version"] = json!(1);
    input["enabled"] = json!(false);
    let result = gmail_read_call(&mut c, &path, None, input, &settings).await;
    sqlx::raw_sql("DROP TRIGGER fixture_gmail_selection_drop ON owner_preferences; DROP FUNCTION fixture_gmail_selection_drop()").execute(&mut c).await.unwrap();
    assert_eq!(result.unwrap_err(), Failure("gmail_read_write_ack_failed"));
    assert_eq!(browser_snapshot(&mut c).await, before);
}
async fn gmail_read_seed_evidence(
    c: &mut PgConnection,
    id: &str,
    account: Uuid,
    expires: &str,
    created: &str,
) {
    browser_save(c,&format!("gmail_msg:{id}"),json!({"id":id,"account_id":account,"expires_at":expires,"links":["https://example.com/jobs/one"],"verification_status":"requires_review","submission_confirmed":false,"status_confirmed":false})).await;
    sqlx::query("UPDATE owner_preferences SET created_at=$1::timestamptz WHERE key=$2")
        .bind(created)
        .bind(format!("gmail_msg:{id}"))
        .execute(c)
        .await
        .unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_read_evidence_paging_filters_account_and_expiry_before_offset_without_get_writes() {
    let (mut c, one, two) = gmail_read_fixture().await;
    for (id, account, expires, date) in [
        (
            "a".repeat(32),
            one,
            "2099-01-01T00:00:00Z",
            "2020-01-01T00:00:00Z",
        ),
        (
            "b".repeat(32),
            one,
            "2099-01-01T00:00:00Z",
            "2021-01-01T00:00:00Z",
        ),
        (
            "c".repeat(32),
            one,
            "2000-01-01T00:00:00Z",
            "2023-01-01T00:00:00Z",
        ),
        (
            "d".repeat(32),
            two,
            "2099-01-01T00:00:00Z",
            "2024-01-01T00:00:00Z",
        ),
    ] {
        gmail_read_seed_evidence(&mut c, &id, account, expires, date).await;
    }
    let before = browser_snapshot(&mut c).await;
    let result = gmail_read_call(
        &mut c,
        &gmail_read_path(one, "/evidence"),
        Some("offset=1&limit=1"),
        Value::Null,
        &gmail_read_settings(),
    )
    .await
    .unwrap();
    assert_eq!(result["evidence"].as_array().unwrap().len(), 1);
    assert_eq!(result["evidence"][0]["id"], "a".repeat(32));
    assert_eq!(result["offset"], 1);
    assert_eq!(result["limit"], 1);
    assert_eq!(browser_snapshot(&mut c).await, before);
    let leads = gmail_read_call(
        &mut c,
        &gmail_read_path(one, "/leads"),
        None,
        Value::Null,
        &gmail_read_settings(),
    )
    .await
    .unwrap();
    assert_eq!(leads["leads"].as_array().unwrap().len(), 1);
    assert_eq!(
        leads["leads"][0]["evidence_ids"],
        json!(["b".repeat(32), "a".repeat(32)])
    );
    assert_eq!(leads["leads"][0]["confirmed_vacancy"], false);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_read_selected_metadata_decrypts_only_bound_envelope_without_returning_ciphertext() {
    let (mut c, one, _two) = gmail_read_fixture().await;
    let id = "a".repeat(32);
    gmail_read_seed_evidence(
        &mut c,
        &id,
        one,
        "2099-01-01T00:00:00Z",
        "2020-01-01T00:00:00Z",
    )
    .await;
    let store = TokenStore::from_values(&mailbox_values()).unwrap().unwrap();
    let raw=json!({"subject":"Fictional application acknowledgment","from":"fictional@example.com","folder":"INBOX"}).to_string();
    let encrypted = store
        .encrypt(&json!(raw), &format!("gmail-metadata:{id}"))
        .unwrap();
    let key = format!("gmail_msg:{id}");
    let mut message = browser_pref(&mut c, &key).await;
    message["encrypted_metadata"] = json!(encrypted);
    browser_save(&mut c, &key, message.clone()).await;
    let result = gmail_read_call(
        &mut c,
        &gmail_read_path(one, "/evidence"),
        None,
        Value::Null,
        &gmail_read_settings(),
    )
    .await
    .unwrap();
    assert_eq!(
        result["evidence"][0]["metadata"]["subject"],
        "Fictional application acknowledgment"
    );
    assert!(result["evidence"][0].get("encrypted_metadata").is_none());
    message["encrypted_metadata"] = json!(
        store
            .encrypt(&json!("{}"), "gmail-metadata:wrong-id")
            .unwrap()
    );
    browser_save(&mut c, &key, message).await;
    assert_eq!(
        gmail_read_call(
            &mut c,
            &gmail_read_path(one, "/evidence"),
            None,
            Value::Null,
            &gmail_read_settings()
        )
        .await
        .unwrap_err(),
        Failure("token_decryption_failed")
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_read_unauthorized_account_saved_status_never_confers_body_or_metadata_permissions() {
    let (mut c, one, _two) = gmail_read_fixture().await;
    let mut values = mailbox_values();
    values.insert(
        "GMAIL_LOCAL_ALLOWED_EMAILS".into(),
        "[\"different@example.com\"]".into(),
    );
    let settings = automated_apply_agents::gmail_accounts::Settings::from_values(&values).unwrap();
    let status = gmail_read_call(
        &mut c,
        &gmail_read_path(one, ""),
        None,
        Value::Null,
        &settings,
    )
    .await
    .unwrap();
    assert_eq!(status["account_authorized"], false);
    assert_eq!(
        status["permissions"],
        json!({"read_metadata":false,"read_body":false,"send":false,"modify":false})
    );
    assert_eq!(status["authorization_state"], "account_not_authorized");
    assert_eq!(status["live_verified"], false);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_read_actual_http_preserves_owner_auth_exact_method_and_bounded_evidence_query() {
    let (mut c, one, _two) = gmail_read_fixture().await;
    let (url, stop, server) = http_fixture_values(browser_values()).await;
    let http = client();
    let endpoint = format!("{url}{}", gmail_read_path(one, "/selection"));
    let input = gmail_read_policy();
    assert_eq!(
        http.put(&endpoint)
            .json(&input)
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    assert_eq!(
        http.put(&endpoint)
            .bearer_auth(HOST_TOKEN)
            .header("x-agent-client", BROWSER_EXTENSION)
            .json(&input)
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    let wrong = http
        .post(&endpoint)
        .bearer_auth(HOST_TOKEN)
        .json(&input)
        .send()
        .await
        .unwrap();
    assert_eq!(wrong.status(), 405);
    assert_eq!(wrong.headers()["allow"], "PUT");
    let result = http
        .put(&endpoint)
        .bearer_auth(HOST_TOKEN)
        .json(&input)
        .send()
        .await
        .unwrap();
    let code = result.status();
    let result: Value = result.json().await.unwrap();
    assert_eq!(code, 200, "{result}");
    assert_eq!(result["sync"]["version"], 1);
    assert_eq!(
        http.get(format!(
            "{url}{}?limit=101",
            gmail_read_path(one, "/evidence")
        ))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .status(),
        422
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM owner_preferences WHERE starts_with(key,'apply_budget:')"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        0
    );
    stop.cancel();
    server.await.unwrap();
}
