// Deferred compose-account and role OAuth fixtures; all identity and transport are fictional.
#[derive(Default)]
struct DraftGoogle {
    inner: ReadGoogle,
    wrong_scope: Cell<bool>,
}
fn draft_tokens(wrong: bool) -> TokenResponse {
    TokenResponse::parse(json!({"access_token":"fictional-compose-access","refresh_token":"fictional-compose-refresh","token_type":"Bearer","expires_in":3600,"scope":scopes(if wrong{GrantMode::Read}else{GrantMode::Compose}).into_iter().collect::<Vec<_>>().join(" ")})).unwrap()
}
impl automated_apply_agents::gmail_accounts::oauth::Provider for DraftGoogle {
    fn redirect_uri(&self) -> &str {
        "https://workspace.example/api/v1/integrations/gmail/oauth/callback"
    }
    fn authorization_url(
        &self,
        state: &str,
        verifier: &str,
        email: Option<&str>,
        mode: GrantMode,
    ) -> Result<String> {
        assert!(matches!(mode, GrantMode::Compose));
        automated_apply_agents::gmail_accounts::oauth::Provider::authorization_url(
            &self.inner,
            state,
            verifier,
            email,
            mode,
        )
    }
    async fn exchange(&self, _code: &str, _verifier: &str) -> Result<TokenResponse> {
        self.inner.exchanges.set(self.inner.exchanges.get() + 1);
        if self.inner.held_exchange {
            self.inner.entered.notify_one();
            self.inner.release.notified().await;
        }
        Ok(draft_tokens(self.wrong_scope.get()))
    }
    async fn refresh(&self, _refresh: &str) -> Result<TokenResponse> {
        self.inner.refreshes.set(self.inner.refreshes.get() + 1);
        if self.inner.held_refresh {
            self.inner.entered.notify_one();
            self.inner.release.notified().await;
        }
        if self.inner.fail_refresh.get() {
            return Err(Failure("google_transport_or_response_error"));
        }
        Ok(draft_tokens(self.wrong_scope.get()))
    }
    async fn identity(&self, _token: &str) -> Result<(String, String)> {
        Ok(self.inner.identity.borrow().clone())
    }
    async fn revoke(&self, _token: &str) -> Result<()> {
        panic!("outreach disconnect is local and must not revoke")
    }
}
fn draft_account_values() -> BTreeMap<String, String> {
    let mut values = mailbox_values();
    values.insert(
        "GMAIL_LOCAL_ALLOWED_EMAILS".into(),
        "[\"fixture@example.com\",\"other@example.com\",\"outreach@example.com\"]".into(),
    );
    values.insert("GMAIL_DRAFTS_ENABLED".into(), "true".into());
    values
}
fn draft_account_settings() -> automated_apply_agents::gmail_accounts::Settings {
    automated_apply_agents::gmail_accounts::Settings::from_values(&draft_account_values()).unwrap()
}
fn draft_google() -> DraftGoogle {
    let google = DraftGoogle::default();
    *google.inner.identity.borrow_mut() = (
        "fictional-outreach-subject".into(),
        "outreach@example.com".into(),
    );
    google
}
async fn draft_account_row(c: &mut PgConnection) -> Value {
    browser_pref(c, "gmail_drafts:account").await
}
async fn draft_account_authorize(
    c: &mut PgConnection,
    settings: &automated_apply_agents::gmail_accounts::Settings,
    google: &DraftGoogle,
) -> Value {
    let svc = gmail_workspace::account::Service {
        settings,
        provider: google,
    };
    let browser = "b".repeat(64);
    let start = svc
        .start(c, json!({"account_consent":true}), &browser)
        .await
        .unwrap();
    svc.callback(
        c,
        &read_state(&start),
        &browser,
        "https://workspace.example/api/v1/integrations/gmail/oauth/callback",
        Some("fictional-code"),
        None,
    )
    .await
    .unwrap()
}
async fn draft_expire(c: &mut PgConnection) {
    let mut row = draft_account_row(c).await;
    row["expires_at"] = json!("2000-01-01T00:00:00Z");
    browser_save(c, "gmail_drafts:account", row).await;
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_outreach_oauth_pins_compose_consent_original_encryption_and_consumed_replay()
 {
    let (mut c, _, _) = workspace_fixture().await;
    let settings = draft_account_settings();
    let google = draft_google();
    let svc = gmail_workspace::account::Service {
        settings: &settings,
        provider: &google,
    };
    let browser = "b".repeat(64);
    for input in [
        json!({"account_consent":false}),
        json!({"account_consent":true,"read_body":true}),
    ] {
        assert!(svc.start(&mut c, input, &browser).await.is_err());
    }
    assert_eq!(alert_count(&mut c, "gmail_draft_oauth:").await, 0);
    let start = svc
        .start(&mut c, json!({"account_consent":true}), &browser)
        .await
        .unwrap();
    let state = read_state(&start);
    assert!(state.starts_with("draft."));
    let hash = format!("{:x}", sha2::Sha256::digest(state.as_bytes()));
    let key = format!("gmail_draft_oauth:{}", &hash[..32]);
    let intent = browser_pref(&mut c, &key).await;
    assert!(!intent.to_string().contains(&browser));
    assert!(!intent.to_string().contains(&state));
    assert!(
        mailbox_store()
            .decrypt(intent["verifier"].as_str().unwrap(), &hash)
            .unwrap()
            .is_string()
    );
    assert!(
        svc.callback(
            &mut c,
            &state,
            &"c".repeat(64),
            "https://workspace.example/api/v1/integrations/gmail/oauth/callback",
            Some("code"),
            None
        )
        .await
        .is_err()
    );
    assert_eq!(google.inner.exchanges.get(), 0);
    let result = svc
        .callback(
            &mut c,
            &state,
            &browser,
            "https://workspace.example/api/v1/integrations/gmail/oauth/callback",
            Some("code"),
            None,
        )
        .await
        .unwrap();
    assert_eq!(result["generation"], 2);
    assert_eq!(result["permissions"]["send"], false);
    assert_eq!(result["permissions"]["read_mail"], false);
    assert!(!result.to_string().contains("fictional-compose-access"));
    let intent = browser_pref(&mut c, &key).await;
    assert_eq!(intent["consumed"], true);
    assert!(intent.get("verifier").is_none());
    let row = draft_account_row(&mut c).await;
    assert_eq!(
        mailbox_store()
            .decrypt(
                row["access"].as_str().unwrap(),
                "gmail_drafts:account:access"
            )
            .unwrap(),
        "fictional-compose-access"
    );
    assert!(
        svc.callback(
            &mut c,
            &state,
            &browser,
            "https://workspace.example/api/v1/integrations/gmail/oauth/callback",
            Some("code"),
            None
        )
        .await
        .is_err()
    );
    assert_eq!(google.inner.exchanges.get(), 1);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_outreach_denied_scope_or_read_identity_keeps_intent_consumed_without_credentials()
 {
    for case in ["denied", "scope", "identity", "local_identity"] {
        let (mut c, _, _) = workspace_fixture().await;
        let settings = draft_account_settings();
        let google = draft_google();
        if case == "scope" {
            google.wrong_scope.set(true);
        }
        if case == "identity" {
            *google.inner.identity.borrow_mut() =
                ("fictional-overlap".into(), "fixture@example.com".into());
        }
        if case == "local_identity" {
            browser_save(&mut c,"gm54_account:1",json!({"google_subject":"fictional-outreach-subject","account_email":"outreach@example.com","status":"connected"})).await;
        }
        let svc = gmail_workspace::account::Service {
            settings: &settings,
            provider: &google,
        };
        let browser = "b".repeat(64);
        let start = svc
            .start(&mut c, json!({"account_consent":true}), &browser)
            .await
            .unwrap();
        let state = read_state(&start);
        assert!(
            svc.callback(
                &mut c,
                &state,
                &browser,
                "https://workspace.example/api/v1/integrations/gmail/oauth/callback",
                Some("code"),
                if case == "denied" {
                    Some("access_denied")
                } else {
                    None
                }
            )
            .await
            .is_err()
        );
        assert_eq!(draft_account_row(&mut c).await["status"], "disconnected");
        assert!(draft_account_row(&mut c).await["access"].is_null());
        assert!(
            svc.callback(
                &mut c,
                &state,
                &browser,
                "https://workspace.example/api/v1/integrations/gmail/oauth/callback",
                Some("code"),
                None
            )
            .await
            .is_err()
        );
        assert_eq!(
            google.inner.exchanges.get(),
            if case == "denied" { 0 } else { 1 }
        );
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_oauth_exchange_releases_owner_lock_and_disconnect_supersedes_late_credentials()
 {
    let (mut c, _, _) = workspace_fixture().await;
    let mut other = connection().await;
    let settings = draft_account_settings();
    let mut google = draft_google();
    google.inner.held_exchange = true;
    let svc = gmail_workspace::account::Service {
        settings: &settings,
        provider: &google,
    };
    let browser = "b".repeat(64);
    let start = svc
        .start(&mut c, json!({"account_consent":true}), &browser)
        .await
        .unwrap();
    let state = read_state(&start);
    let operation = svc.callback(
        &mut c,
        &state,
        &browser,
        "https://workspace.example/api/v1/integrations/gmail/oauth/callback",
        Some("code"),
        None,
    );
    let competing = async {
        google.inner.entered.notified().await;
        let mut lock = other.begin().await.unwrap();
        sqlx::query("SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE NOWAIT").execute(&mut *lock).await.unwrap();
        lock.commit().await.unwrap();
        gmail_workspace::account::disconnect(&mut other)
            .await
            .unwrap();
        google.inner.release.notify_one();
    };
    let (result, ()) = tokio::join!(operation, competing);
    assert_eq!(result.unwrap_err(), Failure("connection_intent_superseded"));
    assert_eq!(
        draft_account_row(&mut c).await,
        json!({"status":"disconnected","generation":2})
    );
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_cached_and_refreshed_compose_access_preserve_original_purpose_and_separate_identity()
 {
    let (mut c, _, _) = workspace_fixture().await;
    let settings = draft_account_settings();
    let google = draft_google();
    draft_account_authorize(&mut c, &settings, &google).await;
    let svc = gmail_workspace::account::Service {
        settings: &settings,
        provider: &google,
    };
    let access = svc.access(&mut c).await.unwrap();
    assert_eq!(access.generation().unwrap(), 2);
    assert_eq!(access.token(), "fictional-compose-access");
    assert_eq!(google.inner.refreshes.get(), 0);
    draft_expire(&mut c).await;
    let access = svc.access(&mut c).await.unwrap();
    assert_eq!(access.token(), "fictional-compose-access");
    assert_eq!(google.inner.refreshes.get(), 1);
    assert!(draft_account_row(&mut c).await["refresh_intent"].is_null());
    let intents: Vec<Value> =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE starts_with(key,'gmd_rfr:')")
            .fetch_all(&mut c)
            .await
            .unwrap();
    assert_eq!(intents.len(), 1);
    assert_eq!(intents[0]["state"], "completed");
    assert!(!intents[0].to_string().contains("fictional-compose-refresh"));
    let result = gmail_workspace::account::disconnect(&mut c).await.unwrap();
    assert_eq!(result["revoke_in_google_settings"], true);
    assert!(svc.access(&mut c).await.is_err());
    assert_eq!(google.inner.revokes.get(), 0);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_uncertain_refresh_scope_or_identity_failure_requires_reauthorization_without_replay()
 {
    for cause in ["transport", "scope", "identity"] {
        let (mut c, _, _) = workspace_fixture().await;
        let settings = draft_account_settings();
        let google = draft_google();
        draft_account_authorize(&mut c, &settings, &google).await;
        draft_expire(&mut c).await;
        match cause {
            "transport" => google.inner.fail_refresh.set(true),
            "scope" => google.wrong_scope.set(true),
            _ => {
                *google.inner.identity.borrow_mut() =
                    ("wrong-subject".into(), "outreach@example.com".into())
            }
        };
        let svc = gmail_workspace::account::Service {
            settings: &settings,
            provider: &google,
        };
        assert!(matches!(
            svc.access(&mut c).await,
            Err(Failure("gmail_drafts_reauthorization_required"))
        ));
        let row = draft_account_row(&mut c).await;
        assert_eq!(row["status"], "reauthorization_required");
        assert!(row["access"].is_null());
        assert!(row["refresh"].is_string());
        assert!(svc.access(&mut c).await.is_err());
        assert_eq!(google.inner.refreshes.get(), 1);
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_abandoned_refresh_lease_expires_into_unknown_without_a_second_provider_call()
 {
    let (mut c, _, _) = workspace_fixture().await;
    let settings = draft_account_settings();
    let mut google = draft_google();
    draft_account_authorize(&mut c, &settings, &google).await;
    draft_expire(&mut c).await;
    google.inner.held_refresh = true;
    let svc = gmail_workspace::account::Service {
        settings: &settings,
        provider: &google,
    };
    {
        let operation = svc.access(&mut c);
        tokio::pin!(operation);
        tokio::select! {result=&mut operation=>match result {Ok(_)=>panic!("unexpected completed refresh"),Err(error)=>panic!("unexpected {}",error.0)},_=google.inner.entered.notified()=>{}}
    }
    assert!(matches!(
        svc.access(&mut c).await,
        Err(Failure("gmail_refresh_in_progress"))
    ));
    let row = draft_account_row(&mut c).await;
    let key = row["refresh_intent"].as_str().unwrap();
    let mut intent = browser_pref(&mut c, key).await;
    intent["lease_until"] = json!("2000-01-01T00:00:00Z");
    browser_save(&mut c, key, intent).await;
    assert!(matches!(
        svc.access(&mut c).await,
        Err(Failure("gmail_refresh_outcome_unknown"))
    ));
    assert_eq!(google.inner.refreshes.get(), 1);
    assert_eq!(
        draft_account_row(&mut c).await["status"],
        "reauthorization_required"
    );
    assert_eq!(browser_pref(&mut c, key).await["state"], "outcome_unknown");
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_late_refresh_after_disconnect_or_expiry_never_publishes_credentials() {
    for cause in ["disconnect", "expiry", "retained_finding"] {
        let (mut c, _, _) = workspace_fixture().await;
        let mut other = connection().await;
        let settings = draft_account_settings();
        let mut google = draft_google();
        draft_account_authorize(&mut c, &settings, &google).await;
        draft_expire(&mut c).await;
        google.inner.held_refresh = true;
        let svc = gmail_workspace::account::Service {
            settings: &settings,
            provider: &google,
        };
        let operation = svc.access(&mut c);
        let competing = async {
            google.inner.entered.notified().await;
            if cause == "disconnect" {
                gmail_workspace::account::disconnect(&mut other)
                    .await
                    .unwrap();
            } else {
                let row = draft_account_row(&mut other).await;
                let key = row["refresh_intent"].as_str().unwrap();
                let mut intent = browser_pref(&mut other, key).await;
                if cause == "retained_finding" {
                    intent["state"] = json!("outcome_unknown");
                    intent["reason"] = json!("retained_owner_finding");
                    let mut account = row.clone();
                    account["status"] = json!("reauthorization_required");
                    account["access"] = Value::Null;
                    browser_save(&mut other, "gmail_drafts:account", account).await;
                } else {
                    intent["lease_until"] = json!("2000-01-01T00:00:00Z");
                }
                browser_save(&mut other, key, intent).await;
            }
            google.inner.release.notify_one();
        };
        let (result, ()) = tokio::join!(operation, competing);
        assert!(result.is_err());
        let account = draft_account_row(&mut c).await;
        assert_ne!(account["status"], "connected");
        assert!(account["access"].is_null());
        assert_eq!(google.inner.refreshes.get(), 1);
        if cause == "retained_finding" {
            let key = account["refresh_intent"].as_str().unwrap();
            assert_eq!(
                browser_pref(&mut c, key).await["reason"],
                "retained_owner_finding"
            );
        }
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_read_slot_start_preserves_reserved_identity_and_original_read_authorization()
 {
    let (mut c, one, _) = workspace_fixture().await;
    let settings = draft_account_settings();
    let google = ReadGoogle::default();
    sqlx::query("UPDATE gmail_read_accounts SET status='disconnected' WHERE id=$1")
        .bind(one)
        .execute(&mut c)
        .await
        .unwrap();
    let start = gmail_workspace::start_read(
        &mut c,
        gmail_workspace::Slot::ReadOne,
        json!({"account_consent":true}),
        &"b".repeat(64),
        &settings,
        &google,
    )
    .await
    .unwrap();
    assert!(read_state(&start).starts_with("read."));
    assert_eq!(
        browser_pref(&mut c, "gmail_workspace_slot:read_1").await["account_id"],
        one.to_string()
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM gmail_read_accounts")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        2
    );
    sqlx::query("DELETE FROM owner_preferences WHERE key='gmail_workspace_slot:read_2'")
        .execute(&mut c)
        .await
        .unwrap();
    let start = gmail_workspace::start_read(
        &mut c,
        gmail_workspace::Slot::ReadTwo,
        json!({"account_consent":true}),
        &"b".repeat(64),
        &settings,
        &google,
    )
    .await
    .unwrap();
    assert!(read_state(&start).starts_with("read."));
    let id = browser_pref(&mut c, "gmail_workspace_slot:read_2").await["account_id"]
        .as_str()
        .unwrap()
        .parse::<Uuid>()
        .unwrap();
    assert_ne!(id, one);
    let account: Value =
        sqlx::query_scalar("SELECT to_jsonb(a) FROM gmail_read_accounts a WHERE id=$1")
            .bind(id)
            .fetch_one(&mut c)
            .await
            .unwrap();
    assert_eq!(account["status"], "disconnected");
    assert_eq!(account["google_subject"], "");
    assert!(account["encrypted_access_token"].is_null());
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_oauth_suppressed_consume_ack_prevents_exchange_and_refresh_ack_prevents_dispatch()
 {
    let (mut c, _, _) = workspace_fixture().await;
    let settings = draft_account_settings();
    let google = draft_google();
    let svc = gmail_workspace::account::Service {
        settings: &settings,
        provider: &google,
    };
    let browser = "b".repeat(64);
    let start = svc
        .start(&mut c, json!({"account_consent":true}), &browser)
        .await
        .unwrap();
    sqlx::raw_sql("CREATE FUNCTION fixture_draft_account_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'gmail_draft_oauth:') THEN RETURN NULL; END IF; RETURN NEW; END $$;CREATE TRIGGER fixture_draft_account_drop BEFORE UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_draft_account_drop()").execute(&mut c).await.unwrap();
    assert!(
        svc.callback(
            &mut c,
            &read_state(&start),
            &browser,
            "https://workspace.example/api/v1/integrations/gmail/oauth/callback",
            Some("code"),
            None
        )
        .await
        .is_err()
    );
    assert_eq!(google.inner.exchanges.get(), 0);
    sqlx::raw_sql("DROP TRIGGER fixture_draft_account_drop ON owner_preferences;DROP FUNCTION fixture_draft_account_drop()").execute(&mut c).await.unwrap();
    svc.callback(
        &mut c,
        &read_state(&start),
        &browser,
        "https://workspace.example/api/v1/integrations/gmail/oauth/callback",
        Some("code"),
        None,
    )
    .await
    .unwrap();
    draft_expire(&mut c).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_draft_account_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'gmd_rfr:') THEN RETURN NULL; END IF; RETURN NEW; END $$;CREATE TRIGGER fixture_draft_account_drop BEFORE INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_draft_account_drop()").execute(&mut c).await.unwrap();
    assert!(svc.access(&mut c).await.is_err());
    assert_eq!(google.inner.refreshes.get(), 0);
    assert!(draft_account_row(&mut c).await["refresh_intent"].is_null());
    sqlx::raw_sql("DROP TRIGGER fixture_draft_account_drop ON owner_preferences;DROP FUNCTION fixture_draft_account_drop()").execute(&mut c).await.unwrap();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_workspace_actual_http_role_consent_draft_callback_cookie_and_local_disconnect_are_separate()
 {
    let (mut c, _, _) = workspace_fixture().await;
    let (google, calls, google_stop, google_task) =
        read_google_http_grant(GrantMode::Compose, "outreach@example.com").await;
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    let callback = format!("{url}{}", mailboxes::routes::CALLBACK);
    let mut values = host_values();
    values.extend(draft_account_values());
    values.extend(BTreeMap::from([
        ("GMAIL_CLIENT_ID".into(), "fictional-client".into()),
        (
            "GMAIL_CLIENT_SECRET".into(),
            "fictional-client-secret".into(),
        ),
        ("GMAIL_REDIRECT_URI".into(), callback.clone()),
        ("RUST_GOOGLE_FIXTURE_ENDPOINT".into(), google),
    ]));
    let config = Arc::new(Configuration::from_values(&values).unwrap());
    let api = Api::new(
        config.clone(),
        config.connect(false).await.unwrap(),
        Wake::default(),
    );
    let stop = CancellationToken::new();
    let shutdown = stop.clone();
    let task = tokio::spawn(async move {
        axum::serve(
            listener,
            server::router(api).into_make_service_with_connect_info::<std::net::SocketAddr>(),
        )
        .with_graceful_shutdown(shutdown.cancelled_owned())
        .await
        .unwrap();
    });
    let http = client();
    let root = format!("{url}{}", gmail_workspace::PATH);
    let endpoint = format!("{root}/accounts/outreach/connect");
    assert_eq!(
        http.post(&endpoint)
            .json(&json!({"account_consent":true}))
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    assert_eq!(
        http.post(&endpoint)
            .bearer_auth(HOST_TOKEN)
            .header("x-agent-client", "extension")
            .json(&json!({"account_consent":true}))
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    assert_eq!(
        http.post(&endpoint)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"account_consent":true,"read_body":true}))
            .send()
            .await
            .unwrap()
            .status(),
        409
    );
    let response = http
        .post(&endpoint)
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"account_consent":true}))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let cookie = response.headers()["set-cookie"]
        .to_str()
        .unwrap()
        .split(';')
        .next()
        .unwrap()
        .to_owned();
    let start: Value = response.json().await.unwrap();
    let state = read_state(&start);
    assert!(state.starts_with("draft."));
    let target = reqwest::Url::parse_with_params(
        &callback,
        [("state", state.as_str()), ("code", "fictional-code")],
    )
    .unwrap();
    assert_eq!(http.get(target.clone()).send().await.unwrap().status(), 400);
    assert!(calls.lock().unwrap().is_empty());
    let response = http
        .get(target.clone())
        .header("cookie", &cookie)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    assert!(
        response.headers()["set-cookie"]
            .to_str()
            .unwrap()
            .contains("Max-Age=0")
    );
    let result: Value = response.json().await.unwrap();
    assert_eq!(result["connection"]["permissions"]["send"], false);
    assert_eq!(result["connection"]["permissions"]["read_mail"], false);
    assert_eq!(
        http.get(target)
            .header("cookie", &cookie)
            .send()
            .await
            .unwrap()
            .status(),
        400
    );
    let account = draft_account_row(&mut c).await;
    assert_eq!(account["account_email"], "outreach@example.com");
    let original_calls = calls.lock().unwrap().clone();
    let response = http
        .post(format!("{root}/outreach/disconnect"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    assert_eq!(*calls.lock().unwrap(), original_calls);
    assert_eq!(draft_account_row(&mut c).await["status"], "disconnected");
    stop.cancel();
    task.await.unwrap();
    google_stop.cancel();
    google_task.await.unwrap();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_mailbox_first_owner_fence_supplies_nondefault_timestamps_and_preserves_existing_conversation()
 {
    let mut c = mailbox_fixture().await;
    sqlx::query("DELETE FROM owner_preferences WHERE key='agent_conversation:primary'")
        .execute(&mut c)
        .await
        .unwrap();
    let settings = mailbox_settings();
    let google = MailboxGoogle::default();
    let service = Service {
        settings: &settings,
        provider: &google,
    };
    service
        .start(&mut c, Slot::One, mailbox_consent(), &"b".repeat(64))
        .await
        .unwrap();
    assert_eq!(
        browser_pref(&mut c, "agent_conversation:primary").await,
        json!({})
    );
    let timestamps:bool=sqlx::query_scalar("SELECT created_at IS NOT NULL AND updated_at IS NOT NULL FROM owner_preferences WHERE key='agent_conversation:primary'").fetch_one(&mut c).await.unwrap();
    assert!(timestamps);
    let retained = json!({"messages":[{"role":"user","content":"Fictional retained owner conversation"}],"expires_at":"2099-01-01T00:00:00Z","selection":{"role":"keep"}});
    sqlx::query("UPDATE owner_preferences SET value=$1 WHERE key='agent_conversation:primary'")
        .bind(&retained)
        .execute(&mut c)
        .await
        .unwrap();
    service
        .start(&mut c, Slot::Two, mailbox_consent(), &"c".repeat(64))
        .await
        .unwrap();
    assert_eq!(
        browser_pref(&mut c, "agent_conversation:primary").await,
        retained
    );
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_local_mailbox_callback_rechecks_outreach_identity_after_exchange_without_connecting_both()
 {
    let (mut c, _, _) = workspace_fixture().await;
    let mut other = connection().await;
    let settings = mailbox_settings();
    let mut google = MailboxGoogle::default();
    google.held_exchange = true;
    let service = Service {
        settings: &settings,
        provider: &google,
    };
    let browser = "b".repeat(64);
    let start = service
        .start(&mut c, Slot::One, mailbox_consent(), &browser)
        .await
        .unwrap();
    let state = mailbox_state(&start);
    let operation = service.callback(
        &mut c,
        &state,
        &browser,
        "https://workspace.example/api/v1/integrations/gmail/oauth/callback",
        Some("code"),
        None,
    );
    let competing = async {
        google.entered.notified().await;
        browser_save(&mut other,"gmail_drafts:account",json!({"status":"connected","generation":2,"google_subject":"fictional-subject","account_email":"fixture@example.com"})).await;
        google.release.notify_one();
    };
    let (result, ()) = tokio::join!(operation, competing);
    assert_eq!(
        result.unwrap_err(),
        Failure("gmail_separate_outreach_account_required")
    );
    assert_eq!(mailbox_row(&mut c, "1").await["status"], "authorizing");
    assert_eq!(draft_account_row(&mut c).await["status"], "connected");
    assert_eq!(google.exchanges.get(), 1);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_local_writer_advances_owner_fence_so_older_serializable_context_cannot_commit() {
    let (mut c, _, _) = workspace_fixture().await;
    let mut other = connection().await;
    let before = browser_pref(&mut c, "agent_conversation:primary").await;
    let mut stale = other.begin().await.unwrap();
    sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        .execute(&mut *stale)
        .await
        .unwrap();
    let _: Value = sqlx::query_scalar(
        "SELECT value FROM owner_preferences WHERE key='agent_conversation:primary'",
    )
    .fetch_one(&mut *stale)
    .await
    .unwrap();
    let settings = mailbox_settings();
    let google = MailboxGoogle::default();
    Service {
        settings: &settings,
        provider: &google,
    }
    .start(&mut c, Slot::One, mailbox_consent(), &"b".repeat(64))
    .await
    .unwrap();
    let failed = sqlx::query(
        "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
    )
    .fetch_one(&mut *stale)
    .await
    .unwrap_err();
    assert_eq!(
        failed.as_database_error().unwrap().code().as_deref(),
        Some("40001")
    );
    stale.rollback().await.unwrap();
    assert_eq!(
        browser_pref(&mut c, "agent_conversation:primary").await,
        before
    );
}
