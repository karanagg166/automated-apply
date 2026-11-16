//! Deferred draft dispatch/reconciliation fixtures. Every message/recipient/provider is fictional.
#[derive(Default)]
struct DraftWriteClient {
    posts: Cell<usize>,
    gets: Cell<usize>,
    lists: Cell<usize>,
    saved: RefCell<Option<Value>>,
    fail_post: Cell<bool>,
    fail_get: Cell<bool>,
    empty: Cell<bool>,
    ambiguous: Cell<bool>,
    edited: Cell<bool>,
    sent: Cell<bool>,
    wrong_marker: Cell<bool>,
    hold_post: bool,
    hold_get: bool,
    entered: tokio::sync::Notify,
    release: tokio::sync::Notify,
}
impl gmail_workspace::dispatch::Client for DraftWriteClient {
    async fn create(&self, raw: &[u8]) -> Result<Value> {
        self.posts.set(self.posts.get() + 1);
        let message = mail_parser::MessageParser::default().parse(raw).unwrap();
        assert!(message.cc().is_none());
        assert!(message.bcc().is_none());
        let headers = message
            .headers_raw()
            .map(|(name, value)| json!({"name":name,"value":value.trim()}))
            .collect::<Vec<_>>();
        let observed = json!({"id":"fictional-workspace-draft","message":{"id":"fictional-workspace-message","labelIds":["DRAFT"],"payload":{"mimeType":"text/plain","headers":headers,"body":{"data":automated_apply_agents::mail_evidence::encoded(message.body_text(0).unwrap().as_bytes())}}}});
        *self.saved.borrow_mut() = Some(observed);
        if self.hold_post {
            self.entered.notify_one();
            self.release.notified().await;
        }
        if self.fail_post.get() {
            return Err(Failure("gmail_draft_request_unconfirmed"));
        }
        Ok(json!({"id":"fictional-workspace-draft"}))
    }
    async fn get(&self, id: &str) -> Result<Value> {
        self.gets.set(self.gets.get() + 1);
        assert_eq!(id, "fictional-workspace-draft");
        if self.hold_get {
            self.entered.notify_one();
            self.release.notified().await;
        }
        if self.fail_get.get() {
            return Err(Failure("gmail_draft_read_failed"));
        }
        let mut value = self.saved.borrow().clone().unwrap();
        if self.edited.get() {
            value["message"]["payload"]["body"]["data"] = json!(
                automated_apply_agents::mail_evidence::encoded(b"Fictional changed body.")
            );
        }
        if self.sent.get() {
            value["message"]["labelIds"] = json!(["SENT"]);
        }
        if self.wrong_marker.get() {
            for header in value["message"]["payload"]["headers"]
                .as_array_mut()
                .unwrap()
            {
                if header["name"]
                    .as_str()
                    .unwrap()
                    .eq_ignore_ascii_case("message-id")
                {
                    header["value"] = json!("<different-marker@example.com>");
                }
            }
        }
        Ok(value)
    }
    async fn list(&self, query: &str) -> Result<Value> {
        self.lists.set(self.lists.get() + 1);
        assert!(query.starts_with("rfc822msgid:aa.workspace."));
        if self.empty.get() {
            return Ok(json!({"drafts":[]}));
        }
        if self.ambiguous.get() {
            return Ok(json!({"drafts":[{"id":"fictional-workspace-draft"},{"id":"other-draft"}]}));
        }
        Ok(json!({"drafts":[{"id":"fictional-workspace-draft"}]}))
    }
}
async fn workspace_dispatch_fixture() -> (
    PgConnection,
    automated_apply_agents::gmail_accounts::Settings,
    DraftGoogle,
    Value,
) {
    let (mut c, _, _) = workspace_fixture().await;
    let settings = draft_account_settings();
    let google = draft_google();
    draft_account_authorize(&mut c, &settings, &google).await;
    let draft = workspace_create(&mut c).await;
    (c, settings, google, draft)
}
fn workspace_approval(draft: &Value) -> Value {
    json!({"expected_version":draft["version"],"content_hash":draft["content_hash"],"expected_account_generation":2,"owner_reviewed":true})
}
fn workspace_uuid(draft: &Value) -> Uuid {
    draft["id"].as_str().unwrap().parse().unwrap()
}
async fn workspace_send_fixture(
    c: &mut PgConnection,
    settings: &automated_apply_agents::gmail_accounts::Settings,
    google: &DraftGoogle,
    draft: &Value,
    client: &DraftWriteClient,
) -> Result<Value> {
    gmail_workspace::account::Service {
        settings,
        provider: google,
    }
    .create_draft_with_client(c, workspace_uuid(draft), workspace_approval(draft), client)
    .await
}
async fn workspace_saved_draft(c: &mut PgConnection, draft: &Value) -> Value {
    browser_pref(c, &format!("gmail_draft:{}", draft["id"].as_str().unwrap())).await
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_draft_one_post_independent_content_readback_and_exact_retry_use_no_send() {
    let (mut c, settings, google, draft) = workspace_dispatch_fixture().await;
    let client = DraftWriteClient::default();
    let before = browser_snapshot(&mut c).await;
    let result = workspace_send_fixture(&mut c, &settings, &google, &draft, &client)
        .await
        .unwrap();
    assert_eq!(result["status"], "saved_in_gmail");
    assert_eq!(result["content_verified"], true);
    assert_eq!(result["sent"], false);
    assert_eq!(client.posts.get(), 1);
    assert_eq!(client.gets.get(), 1);
    assert_eq!(client.lists.get(), 0);
    assert_eq!(
        workspace_send_fixture(&mut c, &settings, &google, &draft, &client)
            .await
            .unwrap(),
        result
    );
    assert_eq!(client.posts.get(), 1);
    assert_eq!(client.gets.get(), 1);
    let saved = workspace_saved_draft(&mut c, &draft).await;
    let intent = browser_pref(&mut c, saved["dispatch_intent"].as_str().unwrap()).await;
    assert_eq!(intent["post_admissions"], 1);
    assert_eq!(intent["read_admissions"], 1);
    assert_eq!(intent["state"], "verified");
    assert!(
        !intent
            .to_string()
            .contains("Fictional private workspace body canary")
    );
    let after = browser_snapshot(&mut c).await;
    for (key, value) in before.as_object().unwrap() {
        if key.starts_with("apply_work:") || key == "application_queue_policy" {
            assert_eq!(&after[key], value);
        }
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_draft_exact_review_hash_version_generation_and_optin_gate_before_dispatch()
{
    let (mut c, settings, google, draft) = workspace_dispatch_fixture().await;
    let client = DraftWriteClient::default();
    let svc = gmail_workspace::account::Service {
        settings: &settings,
        provider: &google,
    };
    for case in ["review", "hash", "version", "account"] {
        let mut approval = workspace_approval(&draft);
        match case {
            "review" => approval["owner_reviewed"] = json!(false),
            "hash" => approval["content_hash"] = json!("0".repeat(64)),
            "version" => approval["expected_version"] = json!(2),
            _ => approval["expected_account_generation"] = json!(3),
        }
        assert!(
            svc.create_draft_with_client(&mut c, workspace_uuid(&draft), approval, &client)
                .await
                .is_err()
        );
    }
    let mut values = draft_account_values();
    values.insert("GMAIL_DRAFTS_ENABLED".into(), "false".into());
    let disabled = automated_apply_agents::gmail_accounts::Settings::from_values(&values).unwrap();
    assert_eq!(
        workspace_send_fixture(&mut c, &disabled, &google, &draft, &client)
            .await
            .unwrap_err(),
        Failure("gmail_draft_creation_disabled")
    );
    assert_eq!(client.posts.get(), 0);
    assert_eq!(alert_count(&mut c, "gmd_write:").await, 0);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_lost_post_response_reconciles_original_marker_without_a_second_post() {
    let (mut c, settings, google, draft) = workspace_dispatch_fixture().await;
    let client = DraftWriteClient::default();
    client.fail_post.set(true);
    assert_eq!(
        workspace_send_fixture(&mut c, &settings, &google, &draft, &client)
            .await
            .unwrap_err(),
        Failure("gmail_draft_creation_unconfirmed")
    );
    let unknown = workspace_saved_draft(&mut c, &draft).await;
    assert_eq!(unknown["status"], "unknown");
    assert!(unknown["gmail_draft_id"].is_null());
    client.fail_post.set(false);
    let result = workspace_send_fixture(&mut c, &settings, &google, &draft, &client)
        .await
        .unwrap();
    assert_eq!(result["content_verified"], true);
    assert_eq!(client.posts.get(), 1);
    assert_eq!(client.lists.get(), 1);
    assert_eq!(client.gets.get(), 1);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_failed_read_retains_positive_id_and_explicit_retry_only_rechecks_that_id()
{
    let (mut c, settings, google, draft) = workspace_dispatch_fixture().await;
    let client = DraftWriteClient::default();
    client.fail_get.set(true);
    assert!(
        workspace_send_fixture(&mut c, &settings, &google, &draft, &client)
            .await
            .is_err()
    );
    let row = workspace_saved_draft(&mut c, &draft).await;
    assert_eq!(row["status"], "unknown");
    assert_eq!(
        row["unconfirmed_gmail_draft_id"],
        "fictional-workspace-draft"
    );
    client.fail_get.set(false);
    assert_eq!(
        workspace_send_fixture(&mut c, &settings, &google, &draft, &client)
            .await
            .unwrap()["content_verified"],
        true
    );
    assert_eq!(client.posts.get(), 1);
    assert_eq!(client.lists.get(), 0);
    assert_eq!(client.gets.get(), 2);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_edited_sent_wrong_marker_and_ambiguous_readback_do_not_confirm_or_repost()
{
    for case in ["edited", "sent", "marker", "ambiguous"] {
        let (mut c, settings, google, draft) = workspace_dispatch_fixture().await;
        let client = DraftWriteClient::default();
        match case {
            "edited" => client.edited.set(true),
            "sent" => client.sent.set(true),
            "marker" => client.wrong_marker.set(true),
            _ => {
                client.fail_post.set(true);
                client.ambiguous.set(true)
            }
        }
        assert!(
            workspace_send_fixture(&mut c, &settings, &google, &draft, &client)
                .await
                .is_err()
        );
        if case == "ambiguous" {
            assert!(
                workspace_send_fixture(&mut c, &settings, &google, &draft, &client)
                    .await
                    .is_err()
            );
        }
        assert_eq!(
            workspace_saved_draft(&mut c, &draft).await["status"],
            "unknown"
        );
        assert_eq!(client.posts.get(), 1);
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_reconciliation_has_three_nonrefundable_read_admissions_and_never_renews_post()
 {
    let (mut c, settings, google, draft) = workspace_dispatch_fixture().await;
    let client = DraftWriteClient::default();
    client.fail_post.set(true);
    client.empty.set(true);
    assert!(
        workspace_send_fixture(&mut c, &settings, &google, &draft, &client)
            .await
            .is_err()
    );
    for _ in 0..3 {
        assert!(
            workspace_send_fixture(&mut c, &settings, &google, &draft, &client)
                .await
                .is_err()
        );
    }
    assert!(
        workspace_send_fixture(&mut c, &settings, &google, &draft, &client)
            .await
            .is_err()
    );
    assert_eq!(client.posts.get(), 1);
    assert_eq!(client.lists.get(), 3);
    let row = workspace_saved_draft(&mut c, &draft).await;
    let intent = browser_pref(&mut c, row["dispatch_intent"].as_str().unwrap()).await;
    assert_eq!(intent["read_admissions"], 3);
    assert_eq!(intent["post_admissions"], 1);
    assert_eq!(intent["state"], "outcome_unknown");
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_cancelled_post_preserves_original_lease_and_reconciles_only_after_expiry()
{
    let (mut c, settings, google, draft) = workspace_dispatch_fixture().await;
    let mut client = DraftWriteClient::default();
    client.hold_post = true;
    {
        let operation = workspace_send_fixture(&mut c, &settings, &google, &draft, &client);
        tokio::pin!(operation);
        tokio::select! {value=&mut operation=>panic!("unexpected {value:?}"),_=client.entered.notified()=>{}}
    }
    assert_eq!(
        workspace_send_fixture(&mut c, &settings, &google, &draft, &client)
            .await
            .unwrap_err(),
        Failure("gmail_draft_dispatch_in_progress")
    );
    assert_eq!(client.posts.get(), 1);
    let row = workspace_saved_draft(&mut c, &draft).await;
    let key = row["dispatch_intent"].as_str().unwrap();
    let mut intent = browser_pref(&mut c, key).await;
    intent["post_until"] = json!("2000-01-01T00:00:00Z");
    browser_save(&mut c, key, intent).await;
    assert_eq!(
        workspace_send_fixture(&mut c, &settings, &google, &draft, &client)
            .await
            .unwrap()["content_verified"],
        true
    );
    assert_eq!(client.posts.get(), 1);
    assert_eq!(client.lists.get(), 1);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_readback_releases_owner_lock_and_rejects_account_or_profile_change() {
    for cause in ["account", "profile"] {
        let (mut c, settings, google, draft) = workspace_dispatch_fixture().await;
        let mut other = connection().await;
        let mut client = DraftWriteClient::default();
        client.hold_get = true;
        let operation = workspace_send_fixture(&mut c, &settings, &google, &draft, &client);
        let competing = async {
            client.entered.notified().await;
            let mut lock = other.begin().await.unwrap();
            sqlx::query("SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE NOWAIT").execute(&mut *lock).await.unwrap();
            lock.commit().await.unwrap();
            if cause == "account" {
                gmail_workspace::account::disconnect(&mut other)
                    .await
                    .unwrap();
            } else {
                sqlx::query(
                    "DELETE FROM owner_preferences WHERE key='phase1_profile_confirmation'",
                )
                .execute(&mut other)
                .await
                .unwrap();
            }
            client.release.notify_one();
        };
        let (result, ()) = tokio::join!(operation, competing);
        assert!(result.is_err());
        let row = workspace_saved_draft(&mut c, &draft).await;
        assert_eq!(row["status"], "unknown");
        assert_eq!(
            row["unconfirmed_gmail_draft_id"],
            "fictional-workspace-draft"
        );
        assert_eq!(client.posts.get(), 1);
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_late_failed_post_does_not_erase_newer_verified_reconciliation() {
    let (mut c, settings, google, draft) = workspace_dispatch_fixture().await;
    let mut other = connection().await;
    let mut client = DraftWriteClient::default();
    client.hold_post = true;
    client.fail_post.set(true);
    let operation = workspace_send_fixture(&mut c, &settings, &google, &draft, &client);
    let competing = async {
        client.entered.notified().await;
        let row = workspace_saved_draft(&mut other, &draft).await;
        let key = row["dispatch_intent"].as_str().unwrap();
        let mut intent = browser_pref(&mut other, key).await;
        intent["post_until"] = json!("2000-01-01T00:00:00Z");
        browser_save(&mut other, key, intent).await;
        assert_eq!(
            workspace_send_fixture(&mut other, &settings, &google, &draft, &client)
                .await
                .unwrap()["content_verified"],
            true
        );
        client.release.notify_one();
    };
    let (result, ()) = tokio::join!(operation, competing);
    assert!(result.is_err());
    let row = workspace_saved_draft(&mut c, &draft).await;
    assert_eq!(row["status"], "saved_in_gmail");
    assert_eq!(
        browser_pref(&mut c, row["dispatch_intent"].as_str().unwrap()).await["state"],
        "verified"
    );
    assert_eq!(client.posts.get(), 1);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_suppressed_admission_ack_prevents_post_and_suppressed_final_ack_keeps_unknown()
 {
    for stage in ["admission", "final"] {
        let (mut c, settings, google, draft) = workspace_dispatch_fixture().await;
        let client = DraftWriteClient::default();
        let sql = if stage == "admission" {
            "CREATE FUNCTION fixture_workspace_write_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'gmd_write:') THEN RETURN NULL; END IF; RETURN NEW; END $$;CREATE TRIGGER fixture_workspace_write_drop BEFORE INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_workspace_write_drop()"
        } else {
            "CREATE FUNCTION fixture_workspace_write_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'gmd_write:') AND NEW.value->>'state'='verified' THEN RETURN NULL; END IF; RETURN NEW; END $$;CREATE TRIGGER fixture_workspace_write_drop BEFORE UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_workspace_write_drop()"
        };
        sqlx::raw_sql(sql).execute(&mut c).await.unwrap();
        assert!(
            workspace_send_fixture(&mut c, &settings, &google, &draft, &client)
                .await
                .is_err()
        );
        assert_eq!(client.posts.get(), if stage == "admission" { 0 } else { 1 });
        assert_eq!(
            workspace_saved_draft(&mut c, &draft).await["status"],
            if stage == "admission" {
                "local_draft"
            } else {
                "unknown"
            }
        );
        sqlx::raw_sql("DROP TRIGGER fixture_workspace_write_drop ON owner_preferences;DROP FUNCTION fixture_workspace_write_drop()").execute(&mut c).await.unwrap();
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_legacy_unknown_intent_is_never_adopted_as_permission_for_another_post() {
    let (mut c, settings, google, draft) = workspace_dispatch_fixture().await;
    let key = format!("gmail_draft:{}", draft["id"].as_str().unwrap());
    let mut row = browser_pref(&mut c, &key).await;
    row["status"] = json!("unknown");
    row["account_subject"] = json!("fictional-outreach-subject");
    browser_save(&mut c, &key, row.clone()).await;
    let client = DraftWriteClient::default();
    assert_eq!(
        workspace_send_fixture(&mut c, &settings, &google, &draft, &client)
            .await
            .unwrap_err(),
        Failure("gmail_draft_dispatch_requires_manual_reconciliation")
    );
    assert_eq!(browser_pref(&mut c, &key).await, row);
    assert_eq!(client.posts.get(), 0);
    assert_eq!(client.gets.get(), 0);
    assert_eq!(google.inner.refreshes.get(), 0);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_actual_owner_http_creates_and_independently_reads_only_a_gmail_draft() {
    let (mut c, _settings, _google, draft) = workspace_dispatch_fixture().await;
    let (endpoint, state, transport_stop, transport_task) = mailbox_data_http().await;
    let mut account = draft_account_row(&mut c).await;
    account["access"] = json!(
        mailbox_store()
            .encrypt(
                &json!("fictional-saved-access"),
                "gmail_drafts:account:access"
            )
            .unwrap()
    );
    browser_save(&mut c, "gmail_drafts:account", account).await;
    let mut values = host_values();
    values.extend(draft_account_values());
    values.insert("RUST_GMAIL_FIXTURE_ENDPOINT".into(), endpoint);
    values.insert("GMAIL_CLIENT_ID".into(), "fictional-client".into());
    values.insert(
        "GMAIL_CLIENT_SECRET".into(),
        "fictional-client-secret".into(),
    );
    values.insert(
        "GMAIL_REDIRECT_URI".into(),
        "https://workspace.example/api/v1/integrations/gmail/oauth/callback".into(),
    );
    let (url, stop, task) = http_fixture_values(values).await;
    let endpoint = format!(
        "{url}{}/drafts/{}/create-in-gmail",
        gmail_workspace::PATH,
        draft["id"].as_str().unwrap()
    );
    let http = client();
    assert_eq!(
        http.post(&endpoint)
            .json(&workspace_approval(&draft))
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    let response = http
        .post(&endpoint)
        .bearer_auth(HOST_TOKEN)
        .json(&workspace_approval(&draft))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let result: Value = response.json().await.unwrap();
    assert_eq!(result["content_verified"], true);
    assert_eq!(result["sent"], false);
    assert_eq!(state.posts.load(std::sync::atomic::Ordering::SeqCst), 1);
    assert_eq!(
        *state.requests.lock().unwrap(),
        vec!["POST /drafts", "GET /drafts/fictional-draft-1"]
    );
    stop.cancel();
    task.await.unwrap();
    transport_stop.cancel();
    transport_task.await.unwrap();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_local_label_with_retained_spent_intent_or_provider_id_cannot_gain_a_new_post()
 {
    for retained in [
        "dispatch_intent",
        "gmail_draft_id",
        "unconfirmed_gmail_draft_id",
    ] {
        let (mut c, settings, google, draft) = workspace_dispatch_fixture().await;
        let key = format!("gmail_draft:{}", draft["id"].as_str().unwrap());
        let mut row = browser_pref(&mut c, &key).await;
        row[retained] = json!("fictional-retained-intent-or-reference");
        browser_save(&mut c, &key, row.clone()).await;
        let client = DraftWriteClient::default();
        assert_eq!(
            workspace_send_fixture(&mut c, &settings, &google, &draft, &client)
                .await
                .unwrap_err(),
            Failure("gmail_draft_dispatch_requires_manual_reconciliation")
        );
        assert_eq!(client.posts.get(), 0);
        assert_eq!(browser_pref(&mut c, &key).await, row);
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_cancelled_read_keeps_lease_and_spent_read_count_then_uses_a_new_bounded_get()
 {
    let (mut c, settings, google, draft) = workspace_dispatch_fixture().await;
    let mut client = DraftWriteClient::default();
    client.hold_get = true;
    {
        let operation = workspace_send_fixture(&mut c, &settings, &google, &draft, &client);
        tokio::pin!(operation);
        tokio::select! {value=&mut operation=>panic!("unexpected {value:?}"),_=client.entered.notified()=>{}}
    }
    assert_eq!(
        workspace_send_fixture(&mut c, &settings, &google, &draft, &client)
            .await
            .unwrap_err(),
        Failure("gmail_draft_reconciliation_in_progress")
    );
    let row = workspace_saved_draft(&mut c, &draft).await;
    let key = row["dispatch_intent"].as_str().unwrap();
    let mut intent = browser_pref(&mut c, key).await;
    assert_eq!(intent["read_admissions"], 1);
    assert_eq!(intent["state"], "reading");
    intent["read_until"] = json!("2000-01-01T00:00:00Z");
    browser_save(&mut c, key, intent).await;
    client.hold_get = false;
    assert_eq!(
        workspace_send_fixture(&mut c, &settings, &google, &draft, &client)
            .await
            .unwrap()["content_verified"],
        true
    );
    let intent = browser_pref(&mut c, key).await;
    assert_eq!(intent["post_admissions"], 1);
    assert_eq!(intent["read_admissions"], 2);
    assert_eq!(client.posts.get(), 1);
    assert_eq!(client.gets.get(), 2);
}
