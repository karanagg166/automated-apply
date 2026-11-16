//! Deferred unprefixed primary OAuth/refresh/verify fixtures, isolated fictional data only.
#[derive(Default)]
struct PrimaryGoogle {
    base: ReadGoogle,
    hold_identity: Cell<bool>,
    fail_identity: Cell<bool>,
    entered: tokio::sync::Notify,
    release: tokio::sync::Notify,
}
impl automated_apply_agents::gmail_accounts::oauth::Provider for PrimaryGoogle {
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
        automated_apply_agents::gmail_accounts::oauth::Provider::authorization_url(
            &self.base, state, verifier, email, mode,
        )
    }
    async fn exchange(&self, code: &str, verifier: &str) -> Result<TokenResponse> {
        automated_apply_agents::gmail_accounts::oauth::Provider::exchange(
            &self.base, code, verifier,
        )
        .await
    }
    async fn refresh(&self, refresh: &str) -> Result<TokenResponse> {
        automated_apply_agents::gmail_accounts::oauth::Provider::refresh(&self.base, refresh).await
    }
    async fn identity(&self, token: &str) -> Result<(String, String)> {
        if self.hold_identity.get() {
            self.entered.notify_one();
            self.release.notified().await;
        }
        if self.fail_identity.get() {
            return Err(Failure("google_transport_or_response_error"));
        }
        automated_apply_agents::gmail_accounts::oauth::Provider::identity(&self.base, token).await
    }
    async fn revoke(&self, token: &str) -> Result<()> {
        automated_apply_agents::gmail_accounts::oauth::Provider::revoke(&self.base, token).await
    }
}
async fn primary_fixture() -> (
    PgConnection,
    automated_apply_agents::gmail_accounts::Settings,
) {
    let mut c = legacy_gmail_fixture().await;
    sqlx::raw_sql("CREATE TABLE IF NOT EXISTS oauth_states(state_hash varchar(64) PRIMARY KEY,provider varchar(30) NOT NULL,actor_id varchar(64) NOT NULL,browser_hash varchar(64) NOT NULL,expected_email varchar(254) NOT NULL,connection_generation integer NOT NULL,encrypted_verifier text,encryption_key_id varchar(64) NOT NULL,redirect_uri varchar(2048) NOT NULL,expires_at timestamptz NOT NULL,created_at timestamptz NOT NULL,consumed_at timestamptz,authorization_mode varchar(20) NOT NULL,expected_subject varchar(255));DELETE FROM oauth_states;UPDATE connected_accounts SET status='disconnected',encrypted_refresh_token=NULL,encrypted_access_token=NULL,encryption_key_id=NULL").execute(&mut c).await.unwrap();
    (c, gmail_read_settings())
}
async fn primary_row(c: &mut PgConnection) -> Value {
    sqlx::query_scalar("SELECT to_jsonb(a) FROM connected_accounts a WHERE provider='gmail'")
        .fetch_one(c)
        .await
        .unwrap()
}
async fn primary_authorize<P: automated_apply_agents::gmail_accounts::oauth::Provider>(
    c: &mut PgConnection,
    settings: &automated_apply_agents::gmail_accounts::Settings,
    google: &P,
) -> Value {
    let service = automated_apply_agents::gmail_legacy::oauth::Service {
        settings,
        provider: google,
    };
    let browser = "b".repeat(64);
    let start = service
        .start(c, json!({"expected_email":"fixture@example.com"}), &browser)
        .await
        .unwrap();
    service
        .callback(
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
async fn primary_expire(c: &mut PgConnection) {
    sqlx::query("UPDATE connected_accounts SET token_expires_at='2000-01-01T00:00:00Z'")
        .execute(c)
        .await
        .unwrap();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_primary_unprefixed_oauth_preserves_account_id_token_purpose_and_consumed_state() {
    let (mut c, settings) = primary_fixture().await;
    let google = PrimaryGoogle::default();
    let service = automated_apply_agents::gmail_legacy::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    let browser = "b".repeat(64);
    let start = service
        .start(
            &mut c,
            json!({"expected_email":"fixture@example.com"}),
            &browser,
        )
        .await
        .unwrap();
    let state = read_state(&start);
    assert!(!state.contains('.'));
    let hash = format!("{:x}", sha2::Sha256::digest(state.as_bytes()));
    let intent: Value =
        sqlx::query_scalar("SELECT to_jsonb(s) FROM oauth_states s WHERE state_hash=$1")
            .bind(&hash)
            .fetch_one(&mut c)
            .await
            .unwrap();
    assert!(!intent.to_string().contains(&browser));
    assert!(!intent.to_string().contains(&state));
    assert!(
        mailbox_store()
            .decrypt(intent["encrypted_verifier"].as_str().unwrap(), &hash)
            .unwrap()
            .is_string()
    );
    assert!(
        service
            .callback(
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
    assert_eq!(google.base.exchanges.get(), 0);
    let result = service
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
    assert_eq!(result["id"], Uuid::from_u128(301).to_string());
    assert_eq!(result["permissions"]["send"], false);
    assert_eq!(result["live_verified"], false);
    let row = primary_row(&mut c).await;
    assert_eq!(row["token_generation"], 3);
    assert_eq!(
        mailbox_store()
            .decrypt(
                row["encrypted_access_token"].as_str().unwrap(),
                &format!("{}:access", Uuid::from_u128(301))
            )
            .unwrap(),
        "fictional-read-access"
    );
    let saved: Value =
        sqlx::query_scalar("SELECT to_jsonb(s) FROM oauth_states s WHERE state_hash=$1")
            .bind(hash)
            .fetch_one(&mut c)
            .await
            .unwrap();
    assert!(!saved["consumed_at"].is_null());
    assert!(saved["encrypted_verifier"].is_null());
    assert!(
        service
            .callback(
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
    assert_eq!(google.base.exchanges.get(), 1);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_primary_send_request_and_compose_without_metadata_are_denied_before_intent_or_exchange()
 {
    let (mut c, settings) = primary_fixture().await;
    let google = PrimaryGoogle::default();
    let service = automated_apply_agents::gmail_legacy::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    let before = primary_row(&mut c).await;
    for (mode, want) in [
        ("send", "gmail_sending_disabled_by_owner_policy"),
        ("compose", "metadata_connection_required_before_upgrade"),
    ] {
        assert_eq!(
            service
                .start(
                    &mut c,
                    json!({"expected_email":"fixture@example.com","authorization_mode":mode}),
                    &"b".repeat(64)
                )
                .await
                .unwrap_err(),
            Failure(want)
        );
        assert_eq!(primary_row(&mut c).await, before);
    }
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM oauth_states")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    assert_eq!(google.base.exchanges.get(), 0);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_primary_compose_upgrade_pins_existing_subject_email_and_preserves_primary_uuid() {
    let (mut c, settings) = primary_fixture().await;
    let google = PrimaryGoogle::default();
    primary_authorize(&mut c, &settings, &google).await;
    let compose = draft_google();
    *compose.inner.identity.borrow_mut() = google.base.identity.borrow().clone();
    let service = automated_apply_agents::gmail_legacy::oauth::Service {
        settings: &settings,
        provider: &compose,
    };
    let browser = "b".repeat(64);
    let start = service
        .start(
            &mut c,
            json!({"expected_email":"fixture@example.com","authorization_mode":"compose"}),
            &browser,
        )
        .await
        .unwrap();
    let result = service
        .callback(
            &mut c,
            &read_state(&start),
            &browser,
            "https://workspace.example/api/v1/integrations/gmail/oauth/callback",
            Some("code"),
            None,
        )
        .await
        .unwrap();
    assert_eq!(result["id"], Uuid::from_u128(301).to_string());
    assert_eq!(result["authorization_state"], "compose_authorized");
    assert_eq!(result["permissions"]["send"], false);
    assert_eq!(primary_row(&mut c).await["token_generation"], 5);
    assert_eq!(
        primary_row(&mut c).await["granted_scopes"],
        json!(scopes(GrantMode::Compose))
    );
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_primary_denied_or_wrong_account_callbacks_stay_consumed_and_never_replay_exchange() {
    for cause in ["denied", "wrong_account", "wrong_scope", "retained_send"] {
        let (mut c, settings) = primary_fixture().await;
        let google = PrimaryGoogle::default();
        let service = automated_apply_agents::gmail_legacy::oauth::Service {
            settings: &settings,
            provider: &google,
        };
        let browser = "b".repeat(64);
        let start = service
            .start(
                &mut c,
                json!({"expected_email":"fixture@example.com"}),
                &browser,
            )
            .await
            .unwrap();
        if cause == "wrong_account" {
            *google.base.identity.borrow_mut() =
                ("fictional-other".into(), "other@example.com".into());
        }
        if cause == "wrong_scope" {
            google.base.mode.set(true);
        }
        let state = read_state(&start);
        if cause == "retained_send" {
            sqlx::query("UPDATE oauth_states SET authorization_mode='send'")
                .execute(&mut c)
                .await
                .unwrap();
        }
        assert!(
            service
                .callback(
                    &mut c,
                    &state,
                    &browser,
                    "https://workspace.example/api/v1/integrations/gmail/oauth/callback",
                    Some("code"),
                    if cause == "denied" {
                        Some("access_denied")
                    } else {
                        None
                    }
                )
                .await
                .is_err()
        );
        assert!(primary_row(&mut c).await["encrypted_access_token"].is_null());
        assert!(
            service
                .callback(
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
            google.base.exchanges.get(),
            if matches!(cause, "denied" | "retained_send") {
                0
            } else {
                1
            }
        );
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_primary_callback_releases_owner_lock_and_disconnect_fences_late_exchange() {
    let (mut c, settings) = primary_fixture().await;
    let mut other = connection().await;
    let mut google = PrimaryGoogle::default();
    google.base.held_exchange = true;
    let service = automated_apply_agents::gmail_legacy::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    let browser = "b".repeat(64);
    let start = service
        .start(
            &mut c,
            json!({"expected_email":"fixture@example.com"}),
            &browser,
        )
        .await
        .unwrap();
    let state = read_state(&start);
    let operation = service.callback(
        &mut c,
        &state,
        &browser,
        "https://workspace.example/api/v1/integrations/gmail/oauth/callback",
        Some("code"),
        None,
    );
    let competing = async {
        google.base.entered.notified().await;
        let mut lock = other.begin().await.unwrap();
        sqlx::query("SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE NOWAIT").execute(&mut *lock).await.unwrap();
        lock.commit().await.unwrap();
        automated_apply_agents::gmail_legacy::refresh::disconnect_without_provider(
            &mut other, &settings,
        )
        .await
        .unwrap();
        google.base.release.notify_one();
    };
    let (result, ()) = tokio::join!(operation, competing);
    assert_eq!(result.unwrap_err(), Failure("connection_intent_superseded"));
    assert_eq!(primary_row(&mut c).await["status"], "disconnected");
    assert!(primary_row(&mut c).await["encrypted_access_token"].is_null());
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_primary_cached_refresh_and_current_verify_have_distinct_generation_and_probe_evidence()
 {
    let (mut c, settings) = primary_fixture().await;
    let google = PrimaryGoogle::default();
    primary_authorize(&mut c, &settings, &google).await;
    let service = automated_apply_agents::gmail_legacy::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    assert_eq!(
        service.access(&mut c).await.unwrap().generation().unwrap(),
        3
    );
    assert_eq!(google.base.refreshes.get(), 0);
    primary_expire(&mut c).await;
    assert_eq!(
        service.access(&mut c).await.unwrap().generation().unwrap(),
        4
    );
    assert_eq!(google.base.refreshes.get(), 1);
    let row = primary_row(&mut c).await;
    assert_eq!(
        mailbox_store()
            .decrypt(
                row["encrypted_access_token"].as_str().unwrap(),
                &format!("{}:access", Uuid::from_u128(301))
            )
            .unwrap(),
        "fictional-read-access"
    );
    let verified = service.verify(&mut c).await.unwrap();
    assert_eq!(verified["live_verified"], true);
    assert_eq!(verified["verification_basis"], "current_identity_probe");
    let status = automated_apply_agents::gmail_legacy::status(&mut c, &settings, true)
        .await
        .unwrap();
    assert_eq!(status["live_verified"], false);
    assert_eq!(status["verification_recorded"], true);
    let intents: Vec<Value> =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE starts_with(key,'gm_lrf:')")
            .fetch_all(&mut c)
            .await
            .unwrap();
    assert_eq!(intents.len(), 1);
    assert_eq!(intents[0]["state"], "completed");
    assert!(!intents[0].to_string().contains("fictional-read-refresh"));
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_primary_transport_identity_or_scope_refresh_failure_requires_reauthorization_without_second_refresh()
 {
    for cause in ["transport", "identity", "scope"] {
        let (mut c, settings) = primary_fixture().await;
        let google = PrimaryGoogle::default();
        primary_authorize(&mut c, &settings, &google).await;
        primary_expire(&mut c).await;
        match cause {
            "transport" => google.base.fail_refresh.set(true),
            "identity" => {
                *google.base.identity.borrow_mut() =
                    ("wrong-subject".into(), "fixture@example.com".into())
            }
            _ => google.base.mode.set(true),
        }
        let service = automated_apply_agents::gmail_legacy::oauth::Service {
            settings: &settings,
            provider: &google,
        };
        assert!(matches!(
            service.access(&mut c).await,
            Err(Failure("gmail_reauthorization_required"))
        ));
        assert_eq!(
            primary_row(&mut c).await["status"],
            "reauthorization_required"
        );
        assert!(primary_row(&mut c).await["encrypted_access_token"].is_null());
        assert!(service.access(&mut c).await.is_err());
        assert_eq!(google.base.refreshes.get(), 1);
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_primary_lost_refresh_is_not_reissued_after_lease_expiry() {
    let (mut c, settings) = primary_fixture().await;
    let mut google = PrimaryGoogle::default();
    primary_authorize(&mut c, &settings, &google).await;
    primary_expire(&mut c).await;
    google.base.held_refresh = true;
    let service = automated_apply_agents::gmail_legacy::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    {
        let operation = service.access(&mut c);
        tokio::pin!(operation);
        tokio::select! {result=&mut operation=>match result{Ok(_)=>panic!("unexpected access"),Err(e)=>panic!("unexpected {}",e.0)},_=google.base.entered.notified()=>{}}
    }
    assert!(matches!(
        service.access(&mut c).await,
        Err(Failure("gmail_refresh_in_progress"))
    ));
    let pointer = browser_pref(
        &mut c,
        &format!("gm_leg_rfr:{}", Uuid::from_u128(301).simple()),
    )
    .await;
    let key = pointer["key"].as_str().unwrap();
    let mut intent = browser_pref(&mut c, key).await;
    intent["lease_until"] = json!("2000-01-01T00:00:00Z");
    browser_save(&mut c, key, intent).await;
    assert!(matches!(
        service.access(&mut c).await,
        Err(Failure("gmail_refresh_outcome_unknown"))
    ));
    assert_eq!(google.base.refreshes.get(), 1);
    assert_eq!(browser_pref(&mut c, key).await["state"], "outcome_unknown");
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_primary_late_refresh_and_verify_cannot_restore_disconnected_credentials() {
    for stage in ["refresh", "verify"] {
        let (mut c, settings) = primary_fixture().await;
        let mut other = connection().await;
        let mut google = PrimaryGoogle::default();
        primary_authorize(&mut c, &settings, &google).await;
        if stage == "refresh" {
            primary_expire(&mut c).await;
            google.base.held_refresh = true;
        } else {
            google.hold_identity.set(true);
        }
        let service = automated_apply_agents::gmail_legacy::oauth::Service {
            settings: &settings,
            provider: &google,
        };
        let operation = async {
            if stage == "refresh" {
                service.access(&mut c).await.map(|_| ())
            } else {
                service.verify(&mut c).await.map(|_| ())
            }
        };
        let competing = async {
            if stage == "refresh" {
                google.base.entered.notified().await;
            } else {
                google.entered.notified().await;
            }
            automated_apply_agents::gmail_legacy::refresh::disconnect_without_provider(
                &mut other, &settings,
            )
            .await
            .unwrap();
            if stage == "refresh" {
                google.base.release.notify_one();
            } else {
                google.release.notify_one();
            }
        };
        let (result, ()) = tokio::join!(operation, competing);
        assert!(result.is_err());
        let row = primary_row(&mut c).await;
        assert_eq!(row["status"], "disconnected");
        assert!(row["encrypted_access_token"].is_null());
        assert!(row["encrypted_refresh_token"].is_null());
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_primary_disconnect_is_local_first_without_provider_or_oauth_schema_and_revoke_is_only_requested()
 {
    let (mut c, settings) = primary_fixture().await;
    let google = PrimaryGoogle::default();
    primary_authorize(&mut c, &settings, &google).await;
    google.base.fail_revoke.set(true);
    let service = automated_apply_agents::gmail_legacy::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    let result = service.disconnect(&mut c).await.unwrap();
    assert_eq!(
        result["revocation"],
        "unconfirmed_revoke_in_google_account_settings"
    );
    assert_eq!(primary_row(&mut c).await["status"], "disconnected");
    assert_eq!(google.base.revokes.get(), 1);
    primary_authorize(&mut c, &settings, &google).await;
    sqlx::query("DROP TABLE oauth_states")
        .execute(&mut c)
        .await
        .unwrap();
    let result = automated_apply_agents::gmail_legacy::refresh::disconnect_without_provider(
        &mut c, &settings,
    )
    .await
    .unwrap();
    assert_eq!(result["status"], "disconnected");
    let row = primary_row(&mut c).await;
    assert!(row["encrypted_access_token"].is_null());
    assert!(row["encrypted_refresh_token"].is_null());
    assert_eq!(google.base.revokes.get(), 1);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_primary_suppressed_or_mutated_oauth_ack_prevents_exchange_and_refresh_admission_ack_prevents_io()
 {
    for stage in ["intent", "consume"] {
        let (mut c, settings) = primary_fixture().await;
        let google = PrimaryGoogle::default();
        let service = automated_apply_agents::gmail_legacy::oauth::Service {
            settings: &settings,
            provider: &google,
        };
        let browser = "b".repeat(64);
        if stage == "intent" {
            sqlx::raw_sql("CREATE FUNCTION fixture_primary_oauth_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.expected_email='changed@example.com';RETURN NEW; END $$;CREATE TRIGGER fixture_primary_oauth_drop BEFORE INSERT ON oauth_states FOR EACH ROW EXECUTE FUNCTION fixture_primary_oauth_drop()").execute(&mut c).await.unwrap();
            assert_eq!(
                service
                    .start(
                        &mut c,
                        json!({"expected_email":"fixture@example.com"}),
                        &browser
                    )
                    .await
                    .unwrap_err(),
                Failure("gmail_legacy_write_ack_failed")
            );
            assert_eq!(primary_row(&mut c).await["token_generation"], 1);
        } else {
            let start = service
                .start(
                    &mut c,
                    json!({"expected_email":"fixture@example.com"}),
                    &browser,
                )
                .await
                .unwrap();
            sqlx::raw_sql("CREATE FUNCTION fixture_primary_oauth_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.encrypted_verifier IS NULL THEN NEW.encrypted_verifier=OLD.encrypted_verifier; END IF;RETURN NEW; END $$;CREATE TRIGGER fixture_primary_oauth_drop BEFORE UPDATE ON oauth_states FOR EACH ROW EXECUTE FUNCTION fixture_primary_oauth_drop()").execute(&mut c).await.unwrap();
            assert!(
                service
                    .callback(
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
            assert_eq!(google.base.exchanges.get(), 0);
        }
        sqlx::raw_sql("DROP TRIGGER fixture_primary_oauth_drop ON oauth_states;DROP FUNCTION fixture_primary_oauth_drop()").execute(&mut c).await.unwrap();
    }
    let (mut c, settings) = primary_fixture().await;
    let google = PrimaryGoogle::default();
    primary_authorize(&mut c, &settings, &google).await;
    primary_expire(&mut c).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_primary_refresh_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'gm_lrf:') THEN RETURN NULL; END IF;RETURN NEW; END $$;CREATE TRIGGER fixture_primary_refresh_drop BEFORE INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_primary_refresh_drop()").execute(&mut c).await.unwrap();
    assert!(
        automated_apply_agents::gmail_legacy::oauth::Service {
            settings: &settings,
            provider: &google
        }
        .access(&mut c)
        .await
        .is_err()
    );
    assert_eq!(google.base.refreshes.get(), 0);
    sqlx::raw_sql("DROP TRIGGER fixture_primary_refresh_drop ON owner_preferences;DROP FUNCTION fixture_primary_refresh_drop()").execute(&mut c).await.unwrap();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_primary_actual_owner_http_cookie_unprefixed_callback_verify_and_disconnect_use_fixed_transport()
 {
    let (mut c, _settings) = primary_fixture().await;
    let (google, calls, google_stop, google_task) = read_google_http().await;
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    let callback = format!("{url}{}", mailboxes::routes::CALLBACK);
    let mut values = host_values();
    values.extend(mailbox_values());
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
    let root = format!("{url}/api/v1/integrations/gmail");
    assert_eq!(
        http.post(format!("{root}/connect/start"))
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"expected_email":"fixture@example.com","authorization_mode":"send"}))
            .send()
            .await
            .unwrap()
            .status(),
        409
    );
    assert!(calls.lock().unwrap().is_empty());
    let response = http
        .post(format!("{root}/connect/start"))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"expected_email":"fixture@example.com"}))
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
    assert!(!state.contains('.'));
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
    assert_eq!(
        http.get(target)
            .header("cookie", cookie)
            .send()
            .await
            .unwrap()
            .status(),
        400
    );
    let response = http
        .post(format!("{root}/verify"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    assert_eq!(
        response.json::<Value>().await.unwrap()["live_verified"],
        true
    );
    let status: Value = http
        .get(format!("{root}/status"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(status["live_verified"], false);
    assert_eq!(
        http.post(format!("{root}/disconnect"))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    assert_eq!(primary_row(&mut c).await["status"], "disconnected");
    assert!(
        calls
            .lock()
            .unwrap()
            .iter()
            .all(|entry| !entry.contains("messages") && !entry.contains("drafts"))
    );
    stop.cancel();
    task.await.unwrap();
    google_stop.cancel();
    google_task.await.unwrap();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_primary_late_positive_refresh_after_expiry_is_unknown_and_identity_failure_requires_reauthorization()
 {
    let (mut c, settings) = primary_fixture().await;
    let mut other = connection().await;
    let mut google = PrimaryGoogle::default();
    primary_authorize(&mut c, &settings, &google).await;
    primary_expire(&mut c).await;
    google.base.held_refresh = true;
    let service = automated_apply_agents::gmail_legacy::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    let operation = service.access(&mut c);
    let competing = async {
        google.base.entered.notified().await;
        let pointer = browser_pref(
            &mut other,
            &format!("gm_leg_rfr:{}", Uuid::from_u128(301).simple()),
        )
        .await;
        let key = pointer["key"].as_str().unwrap();
        let mut intent = browser_pref(&mut other, key).await;
        intent["lease_until"] = json!("2000-01-01T00:00:00Z");
        browser_save(&mut other, key, intent).await;
        google.base.release.notify_one();
    };
    let (result, ()) = tokio::join!(operation, competing);
    assert!(matches!(
        result,
        Err(Failure("gmail_reauthorization_required"))
    ));
    let row = primary_row(&mut c).await;
    assert_eq!(row["status"], "reauthorization_required");
    assert!(row["encrypted_access_token"].is_null());
    assert!(row["encrypted_refresh_token"].is_string());
    assert_eq!(google.base.refreshes.get(), 1);
    let (mut c, settings) = primary_fixture().await;
    let google = PrimaryGoogle::default();
    primary_authorize(&mut c, &settings, &google).await;
    google.fail_identity.set(true);
    let result = automated_apply_agents::gmail_legacy::oauth::Service {
        settings: &settings,
        provider: &google,
    }
    .verify(&mut c)
    .await;
    assert_eq!(
        result.unwrap_err(),
        Failure("gmail_reauthorization_required")
    );
    assert_eq!(
        primary_row(&mut c).await["status"],
        "reauthorization_required"
    );
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_primary_expected_mailbox_is_config_pinned_and_missing_identity_never_creates_an_intent()
 {
    let (mut c, settings) = primary_fixture().await;
    let google = PrimaryGoogle::default();
    let before = primary_row(&mut c).await;
    let service = automated_apply_agents::gmail_legacy::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    assert_eq!(
        service
            .start(&mut c, json!({}), &"b".repeat(64))
            .await
            .unwrap_err(),
        Failure("expected_secondary_email_required")
    );
    assert_eq!(primary_row(&mut c).await, before);
    let mut values = mailbox_values();
    values.insert(
        "GMAIL_EXPECTED_EMAIL".into(),
        " fixture@EXAMPLE.COM ".into(),
    );
    let settings = automated_apply_agents::gmail_accounts::Settings::from_values(&values).unwrap();
    let service = automated_apply_agents::gmail_legacy::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    assert_eq!(
        service
            .start(
                &mut c,
                json!({"expected_email":"other@example.com"}),
                &"b".repeat(64)
            )
            .await
            .unwrap_err(),
        Failure("expected_account_mismatch")
    );
    assert_eq!(primary_row(&mut c).await, before);
    let start = service
        .start(&mut c, json!({}), &"b".repeat(64))
        .await
        .unwrap();
    let url = reqwest::Url::parse(start["authorization_url"].as_str().unwrap()).unwrap();
    assert!(
        url.query_pairs()
            .any(|(key, value)| key == "login_hint" && value == "fixture@example.com")
    );
    assert_eq!(
        sqlx::query_scalar::<_, String>("SELECT expected_email FROM oauth_states LIMIT 1")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        "fixture@example.com"
    );
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_primary_known_superseded_callback_is_consumed_before_refusing_exchange() {
    let (mut c, settings) = primary_fixture().await;
    let google = PrimaryGoogle::default();
    let service = automated_apply_agents::gmail_legacy::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    let browser = "b".repeat(64);
    let start = service
        .start(
            &mut c,
            json!({"expected_email":"fixture@example.com"}),
            &browser,
        )
        .await
        .unwrap();
    sqlx::query(
        "UPDATE connected_accounts SET token_generation=token_generation+1,status='disconnected'",
    )
    .execute(&mut c)
    .await
    .unwrap();
    assert_eq!(
        service
            .callback(
                &mut c,
                &read_state(&start),
                &browser,
                "https://workspace.example/api/v1/integrations/gmail/oauth/callback",
                Some("code"),
                None
            )
            .await
            .unwrap_err(),
        Failure("connection_intent_superseded")
    );
    assert_eq!(google.base.exchanges.get(), 0);
    let intent: Value = sqlx::query_scalar("SELECT to_jsonb(s) FROM oauth_states s LIMIT 1")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert!(!intent["consumed_at"].is_null());
    assert!(intent["encrypted_verifier"].is_null());
}
