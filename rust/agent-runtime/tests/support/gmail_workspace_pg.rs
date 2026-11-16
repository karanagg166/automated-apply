//! Deferred local workspace fixtures. No real account/profile/mail/draft is used.
use automated_apply_agents::gmail_workspace;
async fn workspace_fixture() -> (PgConnection, Uuid, Uuid) {
    let (c, one, two) = gmail_read_fixture().await;
    drop(c);
    let (mut c, _) = listing_fixture().await;
    for (slot, id) in [("read_1", one), ("read_2", two)] {
        browser_save(
            &mut c,
            &format!("gmail_workspace_slot:{slot}"),
            json!({"account_id":id}),
        )
        .await;
    }
    (c, one, two)
}
fn workspace_input(version: i64) -> Value {
    json!({"expected_version":version,"recipient":"target@example.com","company":"Fictional Employer","role":"Rust developer","context":"I reviewed the public role.","subject":"Fictional private subject canary 工作","body":"Fictional private workspace body canary.\nReviewed text."})
}
async fn workspace_call(
    c: &mut PgConnection,
    suffix: &str,
    method: &str,
    input: Option<Value>,
) -> Result<Value> {
    let path = format!("{}{suffix}", gmail_workspace::PATH);
    let body = input
        .map(|v| v.to_string().into_bytes())
        .unwrap_or_default();
    gmail_workspace::dispatch(
        c,
        gmail_workspace::route(&path).unwrap(),
        method,
        None,
        &body,
        &gmail_read_settings(),
    )
    .await
}
async fn workspace_create(c: &mut PgConnection) -> Value {
    workspace_call(c, "/drafts", "POST", Some(workspace_input(0)))
        .await
        .unwrap()
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_status_has_three_fixed_roles_saved_not_live_permissions_and_no_token_envelopes_or_owner_lock()
 {
    let (mut c, one, two) = workspace_fixture().await;
    browser_save(&mut c,"gmail_drafts:account",json!({"status":"connected","generation":5,"account_email":"outreach@example.com","google_subject":"fictional-outreach","scopes":scopes(GrantMode::Compose),"access":"PRIVATE_OUTREACH_ACCESS_CANARY","refresh":"PRIVATE_OUTREACH_REFRESH_CANARY"})).await;
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
    let value = workspace_call(&mut c, "/accounts", "GET", None)
        .await
        .unwrap();
    assert_eq!(value["schema_ready"], true);
    assert_eq!(value["accounts"].as_array().unwrap().len(), 3);
    assert_eq!(value["accounts"][0]["id"], one.to_string());
    assert_eq!(value["accounts"][1]["id"], two.to_string());
    assert_eq!(value["accounts"][2]["slot"], "outreach");
    assert_eq!(value["accounts"][2]["permissions"]["send"], false);
    assert_eq!(value["accounts"][2]["permissions"]["read_mail"], false);
    assert_eq!(value["accounts"][2]["live_verified"], false);
    for text in [
        "PRIVATE_OUTREACH_ACCESS_CANARY",
        "PRIVATE_OUTREACH_REFRESH_CANARY",
        "PRIVATE_ACCESS_ENVELOPE_CANARY",
        "PRIVATE_REFRESH_ENVELOPE_CANARY",
    ] {
        assert!(!value.to_string().contains(text));
    }
    assert_eq!(browser_snapshot(&mut c).await, before);
    lock.rollback().await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_unready_schema_reports_setup_and_duplicate_or_missing_role_identity_fails_closed()
 {
    let (mut c, one, _) = workspace_fixture().await;
    browser_save(
        &mut c,
        "gmail_workspace_slot:read_2",
        json!({"account_id":one}),
    )
    .await;
    assert_eq!(
        workspace_call(&mut c, "/accounts", "GET", None)
            .await
            .unwrap_err(),
        Failure("gmail_workspace_role_identity_conflict")
    );
    browser_save(
        &mut c,
        "gmail_workspace_slot:read_2",
        json!({"account_id":Uuid::new_v4()}),
    )
    .await;
    assert_eq!(
        workspace_call(&mut c, "/accounts", "GET", None)
            .await
            .unwrap_err(),
        Failure("gmail_read_account_not_found")
    );
    sqlx::raw_sql("DROP TABLE gmail_read_oauth_states,gmail_read_accounts")
        .execute(&mut c)
        .await
        .unwrap();
    let value = workspace_call(&mut c, "/accounts", "GET", None)
        .await
        .unwrap();
    assert_eq!(value["schema_ready"], false);
    assert_eq!(value["accounts"].as_array().unwrap().len(), 3);
    assert_eq!(value["accounts"][2]["status"], "setup_required");
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_local_draft_encrypts_original_string_purpose_and_hash_then_edits_by_version()
 {
    let (mut c, _, _) = workspace_fixture().await;
    let draft = workspace_create(&mut c).await;
    assert_eq!(draft["version"], 1);
    assert_eq!(draft["status"], "local_draft");
    assert!(draft.get("gmail_draft_id").is_none());
    let id = draft["id"].as_str().unwrap();
    let key = format!("gmail_draft:{id}");
    let saved = browser_pref(&mut c, &key).await;
    assert!(saved["content"].as_str().unwrap().starts_with("fixture:"));
    for raw in [
        "Fictional private workspace body canary",
        "Fictional private subject canary",
        "target@example.com",
    ] {
        assert!(!saved.to_string().contains(raw));
    }
    let decrypted = mailbox_store()
        .decrypt(saved["content"].as_str().unwrap(), &key)
        .unwrap();
    let content: Value = serde_json::from_str(decrypted.as_str().unwrap()).unwrap();
    assert_eq!(content, draft["content"]);
    assert_eq!(
        draft["content_hash"],
        gmail_workspace::contract::digest(&content)
    );
    assert!(
        mailbox_store()
            .decrypt(saved["content"].as_str().unwrap(), "gmail_draft:other")
            .is_err()
    );
    let mut edit = workspace_input(1);
    edit["body"] = json!("Changed fictional reviewed body.");
    let updated = workspace_call(&mut c, &format!("/drafts/{id}"), "PUT", Some(edit))
        .await
        .unwrap();
    assert_eq!(updated["version"], 2);
    assert_ne!(updated["content_hash"], draft["content_hash"]);
    assert_eq!(
        workspace_call(
            &mut c,
            &format!("/drafts/{id}"),
            "PUT",
            Some(workspace_input(1))
        )
        .await
        .unwrap_err(),
        Failure("gmail_draft_version_or_state_conflict")
    );
    let listed = workspace_call(&mut c, "/drafts", "GET", None)
        .await
        .unwrap();
    assert_eq!(listed["drafts"], json!([updated]));
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_stale_profile_header_injection_and_dispatched_states_cannot_be_saved_or_overwritten()
 {
    let (mut c, _, _) = workspace_fixture().await;
    let mut input = workspace_input(0);
    input["subject"] = json!("Bad\r\nBcc: injected@example.com");
    assert_eq!(
        workspace_call(&mut c, "/drafts", "POST", Some(input))
            .await
            .unwrap_err(),
        Failure("gmail_draft_header_invalid")
    );
    assert_eq!(alert_count(&mut c, "gmail_draft:").await, 0);
    let draft = workspace_create(&mut c).await;
    let id = draft["id"].as_str().unwrap();
    let key = format!("gmail_draft:{id}");
    let original = browser_pref(&mut c, &key).await;
    for state in ["dispatching", "unknown", "saved_in_gmail"] {
        let mut saved = original.clone();
        saved["status"] = json!(state);
        browser_save(&mut c, &key, saved.clone()).await;
        assert_eq!(
            workspace_call(
                &mut c,
                &format!("/drafts/{id}"),
                "PUT",
                Some(workspace_input(1))
            )
            .await
            .unwrap_err(),
            Failure("gmail_draft_version_or_state_conflict")
        );
        assert_eq!(browser_pref(&mut c, &key).await, saved);
    }
    browser_save(&mut c, &key, original.clone()).await;
    sqlx::query("DELETE FROM owner_preferences WHERE key='phase1_profile_confirmation'")
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        workspace_call(
            &mut c,
            &format!("/drafts/{id}"),
            "PUT",
            Some(workspace_input(1))
        )
        .await
        .unwrap_err(),
        Failure("current_approved_profile_required")
    );
    assert_eq!(browser_pref(&mut c, &key).await, original);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_concurrent_edit_acknowledges_one_version_and_preserves_loser_content() {
    let (mut one, _, _) = workspace_fixture().await;
    let mut two = connection().await;
    let draft = workspace_create(&mut one).await;
    let suffix = format!("/drafts/{}", draft["id"].as_str().unwrap());
    let mut first = workspace_input(1);
    first["body"] = json!("Fictional first contender");
    let mut second = workspace_input(1);
    second["body"] = json!("Fictional second contender");
    let (a, b) = tokio::join!(
        workspace_call(&mut one, &suffix, "PUT", Some(first)),
        workspace_call(&mut two, &suffix, "PUT", Some(second))
    );
    assert_ne!(a.is_ok(), b.is_ok());
    let winner = a.ok().or_else(|| b.ok()).unwrap();
    assert_eq!(winner["version"], 2);
    let listed = workspace_call(&mut one, "/drafts", "GET", None)
        .await
        .unwrap();
    assert_eq!(listed["drafts"], json!([winner]));
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_suppressed_insert_or_update_ack_rolls_back_draft_and_preserves_other_owner_state()
 {
    let (mut c, _, _) = workspace_fixture().await;
    let before = browser_snapshot(&mut c).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_workspace_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'gmail_draft:') THEN RETURN NULL; END IF; RETURN NEW; END $$;CREATE TRIGGER fixture_workspace_drop BEFORE INSERT OR UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_workspace_drop()").execute(&mut c).await.unwrap();
    assert_eq!(
        workspace_call(&mut c, "/drafts", "POST", Some(workspace_input(0)))
            .await
            .unwrap_err(),
        Failure("gmail_workspace_write_ack_failed")
    );
    assert_eq!(browser_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP TRIGGER fixture_workspace_drop ON owner_preferences;DROP FUNCTION fixture_workspace_drop()").execute(&mut c).await.unwrap();
    let draft = workspace_create(&mut c).await;
    let before = browser_snapshot(&mut c).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_workspace_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'gmail_draft:') THEN RETURN NULL; END IF; RETURN NEW; END $$;CREATE TRIGGER fixture_workspace_drop BEFORE UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_workspace_drop()").execute(&mut c).await.unwrap();
    assert_eq!(
        workspace_call(
            &mut c,
            &format!("/drafts/{}", draft["id"].as_str().unwrap()),
            "PUT",
            Some(workspace_input(1))
        )
        .await
        .unwrap_err(),
        Failure("gmail_workspace_write_ack_failed")
    );
    assert_eq!(browser_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP TRIGGER fixture_workspace_drop ON owner_preferences;DROP FUNCTION fixture_workspace_drop()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_list_rejects_content_hash_or_encryption_purpose_tampering_without_mutation()
 {
    let (mut c, _, _) = workspace_fixture().await;
    let draft = workspace_create(&mut c).await;
    let key = format!("gmail_draft:{}", draft["id"].as_str().unwrap());
    let original = browser_pref(&mut c, &key).await;
    let mut tampered = original.clone();
    tampered["content_hash"] = json!("0".repeat(64));
    browser_save(&mut c, &key, tampered).await;
    let before = browser_snapshot(&mut c).await;
    assert_eq!(
        workspace_call(&mut c, "/drafts", "GET", None)
            .await
            .unwrap_err(),
        Failure("invalid_gmail_workspace_saved_record")
    );
    assert_eq!(browser_snapshot(&mut c).await, before);
    let other = Uuid::new_v4().simple().to_string();
    let mut moved = original.clone();
    moved["id"] = json!(other);
    browser_save(&mut c, &key, original).await;
    browser_save(&mut c, &format!("gmail_draft:{other}"), moved).await;
    assert!(
        workspace_call(&mut c, "/drafts", "GET", None)
            .await
            .is_err()
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_draft_list_is_bounded_stably_sorted_and_needs_no_owner_lock() {
    let (mut c, _, _) = workspace_fixture().await;
    for index in 1..=103 {
        let id = format!("{index:032x}");
        let key = format!("gmail_draft:{id}");
        let content = json!({"recipient":"target@example.com","subject":"Fictional","body":"Reviewed fictional body"});
        browser_save(&mut c,&key,json!({"id":id,"version":1,"status":"local_draft","profile_version":4,"company":"Fictional","role":"Rust","content_hash":gmail_workspace::contract::digest(&content),"content":mailbox_store().encrypt(&json!(automated_apply_agents::python_json::serialize(&content,false,true)),&key).unwrap()})).await;
        sqlx::query("UPDATE owner_preferences SET created_at='2026-01-01T00:00:00Z' WHERE key=$1")
            .bind(&key)
            .execute(&mut c)
            .await
            .unwrap();
    }
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
    let before = browser_snapshot(&mut c).await;
    let list = workspace_call(&mut c, "/drafts", "GET", None)
        .await
        .unwrap();
    assert_eq!(list["drafts"].as_array().unwrap().len(), 100);
    assert_eq!(list["drafts"][0]["id"], format!("{:032x}", 1));
    assert_eq!(list["drafts"][99]["id"], format!("{:032x}", 100));
    assert_eq!(browser_snapshot(&mut c).await, before);
    lock.rollback().await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_http_keeps_auth_strict_draft_validation_and_known_methods() {
    let (mut c, _, _) = workspace_fixture().await;
    let mut values = host_values();
    values.extend(mailbox_values());
    let (url, stop, task) = http_fixture_values(values).await;
    let http = client();
    let root = format!("{url}{}", gmail_workspace::PATH);
    assert_eq!(
        http.get(format!("{root}/accounts"))
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    assert_eq!(
        http.get(format!("{root}/accounts"))
            .bearer_auth(HOST_TOKEN)
            .header("x-agent-client", "extension")
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    let response = http
        .delete(format!("{root}/drafts"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 405);
    assert_eq!(response.headers()["allow"], "GET, POST");
    let mut invalid = workspace_input(0);
    invalid["send"] = json!(true);
    assert_eq!(
        http.post(format!("{root}/drafts"))
            .bearer_auth(HOST_TOKEN)
            .json(&invalid)
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    let response = http
        .post(format!("{root}/drafts"))
        .bearer_auth(HOST_TOKEN)
        .json(&workspace_input(0))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let draft: Value = response.json().await.unwrap();
    assert_eq!(draft["status"], "local_draft");
    assert_eq!(alert_count(&mut c, "gmail_draft:").await, 1);
    assert_eq!(
        http.get(format!("{root}/accounts?refresh=true"))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    stop.cancel();
    task.await.unwrap();
}
