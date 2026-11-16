use automated_apply_agents::mailboxes::{self, Consent, Provider, Service, Slot};
use automated_apply_agents::{
    account_tokens::TokenStore,
    google_oauth::{GrantMode, TokenResponse, scopes},
};
use std::cell::{Cell, RefCell};
struct MailboxGoogle {
    exchanges: Cell<usize>,
    refreshes: Cell<usize>,
    revocations: Cell<usize>,
    identities: Cell<usize>,
    fail: Cell<Option<Failure>>,
    identity: RefCell<(String, String)>,
    held_refresh: bool,
    held_exchange: bool,
    entered: tokio::sync::Notify,
    release: tokio::sync::Notify,
}
impl Default for MailboxGoogle {
    fn default() -> Self {
        Self {
            exchanges: Cell::new(0),
            refreshes: Cell::new(0),
            revocations: Cell::new(0),
            identities: Cell::new(0),
            fail: Cell::new(None),
            identity: RefCell::new(("fictional-subject".into(), "fixture@example.com".into())),
            held_refresh: false,
            held_exchange: false,
            entered: tokio::sync::Notify::new(),
            release: tokio::sync::Notify::new(),
        }
    }
}
fn mailbox_tokens(refresh: bool) -> TokenResponse {
    let mut raw = json!({"access_token":"fictional-refreshed-access","expires_in":3600,"token_type":"Bearer","scope":scopes(GrantMode::ReadDraft).into_iter().collect::<Vec<_>>().join(" ")});
    if refresh {
        raw["refresh_token"] = json!("fictional-new-refresh");
    }
    TokenResponse::parse(raw).unwrap()
}
impl Provider for MailboxGoogle {
    fn redirect_uri(&self) -> &str {
        "https://workspace.example/api/v1/integrations/gmail/oauth/callback"
    }
    fn authorization_url(
        &self,
        state: &str,
        verifier: &str,
        _hint: Option<&str>,
    ) -> automated_apply_agents::Result<String> {
        assert!((43..=128).contains(&verifier.len()));
        Ok(format!(
            "https://accounts.google.com/o/oauth2/v2/auth?state={state}"
        ))
    }
    async fn exchange(
        &self,
        _code: &str,
        _verifier: &str,
    ) -> automated_apply_agents::Result<TokenResponse> {
        self.exchanges.set(self.exchanges.get() + 1);
        if self.held_exchange {
            self.entered.notify_one();
            self.release.notified().await;
        }
        if let Some(error) = self.fail.get() {
            return Err(error);
        }
        Ok(mailbox_tokens(true))
    }
    async fn refresh(&self, _refresh: &str) -> automated_apply_agents::Result<TokenResponse> {
        self.refreshes.set(self.refreshes.get() + 1);
        if self.held_refresh {
            self.entered.notify_one();
            self.release.notified().await;
        }
        if let Some(error) = self.fail.get() {
            return Err(error);
        }
        Ok(mailbox_tokens(false))
    }
    async fn identity(&self, _token: &str) -> automated_apply_agents::Result<(String, String)> {
        self.identities.set(self.identities.get() + 1);
        Ok(self.identity.borrow().clone())
    }
    async fn revoke(&self, _token: &str) -> automated_apply_agents::Result<()> {
        self.revocations.set(self.revocations.get() + 1);
        if let Some(error) = self.fail.get() {
            Err(error)
        } else {
            Ok(())
        }
    }
}
fn mailbox_values() -> BTreeMap<String, String> {
    BTreeMap::from([
        ("GMAIL_LOCAL_ACCOUNTS_ENABLED".into(), "true".into()),
        (
            "GMAIL_LOCAL_ALLOWED_EMAILS".into(),
            "[\"fixture@example.com\",\"other@example.com\"]".into(),
        ),
        ("OAUTH_ACTIVE_KEY_ID".into(), "fixture".into()),
        (
            "OAUTH_ENCRYPTION_KEYS".into(),
            "{\"fixture\":\"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=\"}".into(),
        ),
    ])
}
fn mailbox_settings() -> mailboxes::Settings {
    mailboxes::Settings::from_values(&mailbox_values(), true).unwrap()
}
fn mailbox_store() -> TokenStore {
    TokenStore::from_values(&mailbox_values()).unwrap().unwrap()
}
async fn mailbox_fixture() -> PgConnection {
    let mut c = knowledge_fixture().await;
    // Production ORM timestamp columns have no database defaults.
    sqlx::raw_sql("ALTER TABLE owner_preferences ADD COLUMN created_at timestamptz, ADD COLUMN updated_at timestamptz;UPDATE owner_preferences SET created_at=clock_timestamp(),updated_at=clock_timestamp();ALTER TABLE owner_preferences ALTER COLUMN created_at SET NOT NULL,ALTER COLUMN updated_at SET NOT NULL").execute(&mut c).await.unwrap();
    c
}
async fn mailbox_row(c: &mut PgConnection, slot: &str) -> Value {
    sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(format!("gm54_account:{slot}"))
        .fetch_one(c)
        .await
        .unwrap()
}
async fn mailbox_seed(c: &mut PgConnection, expired: bool) {
    let store = mailbox_store();
    let expiry = chrono::Utc::now() + chrono::Duration::seconds(if expired { -10 } else { 3600 });
    let value = json!({"status":"connected","generation":1,"account_email":"fixture@example.com","google_subject":"fictional-subject","scopes":scopes(GrantMode::ReadDraft),"access":store.encrypt(&json!("fictional-saved-access"),"gm54_account:1:access").unwrap(),"refresh":store.encrypt(&json!("fictional-saved-refresh"),"gm54_account:1:refresh").unwrap(),"expires_at":expiry.to_rfc3339()});
    sqlx::query("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES('gm54_account:1',$1,clock_timestamp(),clock_timestamp())").bind(value).execute(c).await.unwrap();
}
fn mailbox_consent() -> Consent {
    Consent {
        account_consent: true,
        read_and_draft_consent: true,
    }
}
fn mailbox_state(result: &Value) -> String {
    reqwest::Url::parse(result["authorization_url"].as_str().unwrap())
        .unwrap()
        .query_pairs()
        .find(|(k, _)| k == "state")
        .unwrap()
        .1
        .into_owned()
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn mailbox_consent_callback_encryption_identity_and_replay_fences() {
    let mut c = mailbox_fixture().await;
    let settings = mailbox_settings();
    let google = MailboxGoogle::default();
    let svc = Service {
        settings: &settings,
        provider: &google,
    };
    let browser = mailboxes::browser_nonce();
    assert_eq!(
        svc.start(
            &mut c,
            Slot::One,
            Consent {
                account_consent: false,
                read_and_draft_consent: true
            },
            &browser
        )
        .await
        .err(),
        Some(Failure("gmail_read_draft_consent_required"))
    );
    let start = svc
        .start(&mut c, Slot::One, mailbox_consent(), &browser)
        .await
        .unwrap();
    let state = mailbox_state(&start);
    let hash = mailboxes::digest(&state);
    let intent: Value = sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(format!("gm54_oauth:{}", &hash[..32]))
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert!(!intent.to_string().contains(&browser));
    assert!(!intent.to_string().contains(&state));
    assert!(intent["verifier"].as_str().unwrap().starts_with("fixture:"));
    for (cookie, uri) in [
        ("wrong", google.redirect_uri()),
        (browser.as_str(), "https://wrong.example/callback"),
    ] {
        assert!(
            svc.callback(&mut c, &state, cookie, uri, Some("code"), None)
                .await
                .is_err()
        );
    }
    assert_eq!(google.exchanges.get(), 0);
    let status = svc
        .callback(
            &mut c,
            &state,
            &browser,
            google.redirect_uri(),
            Some("code"),
            None,
        )
        .await
        .unwrap();
    assert_eq!(status["status"], "connected");
    assert_eq!(status["permissions"]["send"], false);
    assert!(!status.to_string().contains("fictional-refreshed-access"));
    let saved = mailbox_row(&mut c, "1").await;
    assert_eq!(
        mailbox_store()
            .decrypt(saved["access"].as_str().unwrap(), "gm54_account:1:access")
            .unwrap(),
        "fictional-refreshed-access"
    );
    assert_eq!(
        svc.callback(
            &mut c,
            &state,
            &browser,
            google.redirect_uri(),
            Some("code"),
            None
        )
        .await
        .err(),
        Some(Failure("invalid_expired_or_replayed_state"))
    );
    assert_eq!(google.exchanges.get(), 1);
    let consumed: Value = sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(format!("gm54_oauth:{}", &hash[..32]))
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(consumed["consumed"], true);
    assert!(consumed.get("verifier").is_none());
    assert_eq!(
        svc.start(&mut c, Slot::One, mailbox_consent(), &browser)
            .await
            .err(),
        Some(Failure("disconnect_before_reconnecting"))
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn mailbox_denied_exchange_is_consumed_and_cannot_be_replayed() {
    let mut c = mailbox_fixture().await;
    let settings = mailbox_settings();
    let google = MailboxGoogle::default();
    let svc = Service {
        settings: &settings,
        provider: &google,
    };
    let browser = mailboxes::browser_nonce();
    let state = mailbox_state(
        &svc.start(&mut c, Slot::One, mailbox_consent(), &browser)
            .await
            .unwrap(),
    );
    assert_eq!(
        svc.callback(
            &mut c,
            &state,
            &browser,
            google.redirect_uri(),
            None,
            Some("access_denied")
        )
        .await
        .err(),
        Some(Failure("consent_denied"))
    );
    assert_eq!(google.exchanges.get(), 0);
    assert_eq!(
        svc.callback(
            &mut c,
            &state,
            &browser,
            google.redirect_uri(),
            Some("code"),
            None
        )
        .await
        .err(),
        Some(Failure("invalid_expired_or_replayed_state"))
    );
    let state = mailbox_state(
        &svc.start(&mut c, Slot::One, mailbox_consent(), &browser)
            .await
            .unwrap(),
    );
    google
        .fail
        .set(Some(Failure("google_transport_or_response_error")));
    assert!(
        svc.callback(
            &mut c,
            &state,
            &browser,
            google.redirect_uri(),
            Some("code"),
            None
        )
        .await
        .is_err()
    );
    assert_eq!(google.exchanges.get(), 1);
    assert_eq!(
        svc.callback(
            &mut c,
            &state,
            &browser,
            google.redirect_uri(),
            Some("code"),
            None
        )
        .await
        .err(),
        Some(Failure("invalid_expired_or_replayed_state"))
    );
    assert_eq!(google.exchanges.get(), 1);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn mailbox_callback_does_not_reconnect_a_concurrently_disconnected_generation() {
    let mut c = mailbox_fixture().await;
    let mut other = connection().await;
    let settings = mailbox_settings();
    let google = MailboxGoogle {
        held_exchange: true,
        ..Default::default()
    };
    let svc = Service {
        settings: &settings,
        provider: &google,
    };
    let browser = mailboxes::browser_nonce();
    let state = mailbox_state(
        &svc.start(&mut c, Slot::One, mailbox_consent(), &browser)
            .await
            .unwrap(),
    );
    let callback = svc.callback(
        &mut c,
        &state,
        &browser,
        google.redirect_uri(),
        Some("code"),
        None,
    );
    let disconnect = async {
        google.entered.notified().await;
        svc.disconnect(&mut other, Slot::One).await.unwrap();
        google.release.notify_one();
    };
    let (result, ()) = tokio::join!(callback, disconnect);
    assert_eq!(result.err(), Some(Failure("connection_intent_superseded")));
    assert_eq!(mailbox_row(&mut c, "1").await["status"], "disconnected");
    assert_eq!(google.exchanges.get(), 1);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn mailbox_duplicate_identity_and_reauthorization_subject_are_pinned() {
    let mut c = mailbox_fixture().await;
    mailbox_seed(&mut c, false).await;
    let settings = mailbox_settings();
    let google = MailboxGoogle::default();
    let svc = Service {
        settings: &settings,
        provider: &google,
    };
    let browser = mailboxes::browser_nonce();
    let state = mailbox_state(
        &svc.start(&mut c, Slot::Two, mailbox_consent(), &browser)
            .await
            .unwrap(),
    );
    assert_eq!(
        svc.callback(
            &mut c,
            &state,
            &browser,
            google.redirect_uri(),
            Some("code"),
            None
        )
        .await
        .err(),
        Some(Failure("gmail_account_already_connected"))
    );
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{status}','\"reauthorization_required\"') WHERE key='gm54_account:1'").execute(&mut c).await.unwrap();
    let state = mailbox_state(
        &svc.start(&mut c, Slot::One, mailbox_consent(), &browser)
            .await
            .unwrap(),
    );
    *google.identity.borrow_mut() = ("different-subject".into(), "fixture@example.com".into());
    assert_eq!(
        svc.callback(
            &mut c,
            &state,
            &browser,
            google.redirect_uri(),
            Some("code"),
            None
        )
        .await
        .err(),
        Some(Failure("gmail_identity_mismatch"))
    );
    assert_eq!(mailbox_row(&mut c, "1").await["status"], "authorizing");
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn mailbox_cached_access_and_refresh_preserve_refresh_envelope_and_hidden_values() {
    let mut c = mailbox_fixture().await;
    mailbox_seed(&mut c, false).await;
    let settings = mailbox_settings();
    let google = MailboxGoogle::default();
    let svc = Service {
        settings: &settings,
        provider: &google,
    };
    assert_eq!(
        svc.access(&mut c, Slot::One).await.unwrap().token(),
        "fictional-saved-access"
    );
    assert_eq!(google.refreshes.get(), 0);
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{expires_at}',to_jsonb('2020-01-01T00:00:00+00:00'::text)) WHERE key='gm54_account:1'").execute(&mut c).await.unwrap();
    let token = svc.access(&mut c, Slot::One).await.unwrap();
    assert_eq!(token.token(), "fictional-refreshed-access");
    assert_eq!(google.refreshes.get(), 1);
    assert_eq!(google.identities.get(), 1);
    let saved = mailbox_row(&mut c, "1").await;
    assert_eq!(
        mailbox_store()
            .decrypt(saved["refresh"].as_str().unwrap(), "gm54_account:1:refresh")
            .unwrap(),
        "fictional-saved-refresh"
    );
    assert!(saved.get("refresh_lease").is_none());
    let status = svc.status(&mut c, Slot::One).await.unwrap().to_string();
    for hidden in [
        "fictional-saved-refresh",
        "fictional-refreshed-access",
        "fictional-subject",
        "fixture:",
    ] {
        assert!(!status.contains(hidden));
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn mailbox_refresh_lease_serializes_network_and_disconnect_wins_generation_race() {
    let mut c = mailbox_fixture().await;
    mailbox_seed(&mut c, true).await;
    let mut other = connection().await;
    let settings = mailbox_settings();
    let google = MailboxGoogle {
        held_refresh: true,
        ..Default::default()
    };
    let svc = Service {
        settings: &settings,
        provider: &google,
    };
    let access = svc.access(&mut c, Slot::One);
    let competing = async {
        google.entered.notified().await;
        assert_eq!(
            svc.access(&mut other, Slot::One).await.err().map(|e| e.0),
            Some("gmail_refresh_in_progress")
        );
        assert_eq!(google.refreshes.get(), 1);
        svc.disconnect(&mut other, Slot::One).await.unwrap();
        google.release.notify_one();
    };
    let (result, ()) = tokio::join!(access, competing);
    assert_eq!(result.err().map(|e| e.0), Some("gmail_account_changed"));
    assert_eq!(mailbox_row(&mut c, "1").await["status"], "disconnected");
    assert_eq!(google.revocations.get(), 1);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn mailbox_revoked_and_transient_refresh_errors_have_distinct_durable_states() {
    let mut c = mailbox_fixture().await;
    mailbox_seed(&mut c, true).await;
    let settings = mailbox_settings();
    let google = MailboxGoogle::default();
    let svc = Service {
        settings: &settings,
        provider: &google,
    };
    google
        .fail
        .set(Some(Failure("google_transport_or_response_error")));
    assert_eq!(
        svc.access(&mut c, Slot::One).await.err().map(|e| e.0),
        Some("gmail_refresh_unavailable")
    );
    assert_eq!(
        mailbox_row(&mut c, "1").await["status"],
        "reauthorization_required"
    );
    assert_eq!(
        mailbox_row(&mut c, "1").await["refresh_outcome"],
        "outcome_unknown"
    );
    assert_eq!(
        svc.access(&mut c, Slot::One).await.err().map(|e| e.0),
        Some("gmail_read_draft_account_not_connected")
    );
    assert_eq!(google.refreshes.get(), 1);
    sqlx::query("DELETE FROM owner_preferences WHERE key='gm54_account:1'").execute(&mut c).await.unwrap();
    mailbox_seed(&mut c, true).await;
    google
        .fail
        .set(Some(Failure("credential_revoked_or_code_invalid")));
    assert_eq!(
        svc.access(&mut c, Slot::One).await.err().map(|e| e.0),
        Some("gmail_reauthorization_required")
    );
    let row = mailbox_row(&mut c, "1").await;
    assert_eq!(row["status"], "reauthorization_required");
    assert!(row["access"].is_null());
    assert!(row["refresh"].is_string());
    let result = svc.disconnect(&mut c, Slot::One).await.unwrap();
    assert_eq!(result["revocation"], "manual_revocation_required");
    let row = mailbox_row(&mut c, "1").await;
    assert_eq!(row, json!({"status":"disconnected","generation":2}));
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn local_mailbox_abandoned_refresh_lease_never_replays_on_restart_and_retains_unknown_intent()
{
    let mut c = mailbox_fixture().await;
    mailbox_seed(&mut c, true).await;
    let settings = mailbox_settings();
    let google = MailboxGoogle {
        held_refresh: true,
        ..MailboxGoogle::default()
    };
    let service = Service {
        settings: &settings,
        provider: &google,
    };
    {
        let request = service.access(&mut c, Slot::One);
        tokio::pin!(request);
        tokio::select! {_ = google.entered.notified()=>{},result=&mut request=>panic!("refresh unexpectedly completed: {}",result.is_ok())};
    }
    let mut other = connection().await;
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{refresh_lease_until}','\"2000-01-01T00:00:00Z\"') WHERE key='gm54_account:1'").execute(&mut other).await.unwrap();
    let restarted = MailboxGoogle::default();
    let service = Service {
        settings: &settings,
        provider: &restarted,
    };
    assert_eq!(
        service
            .access(&mut other, Slot::One)
            .await
            .err()
            .map(|e| e.0),
        Some("gmail_refresh_unavailable")
    );
    assert_eq!(restarted.refreshes.get(), 0);
    let row = mailbox_row(&mut other, "1").await;
    assert_eq!(row["status"], "reauthorization_required");
    assert_eq!(row["refresh_outcome"], "outcome_unknown");
    assert!(row["access"].is_null());
    let intents: Vec<Value> = sqlx::query_scalar(
        "SELECT value FROM owner_preferences WHERE starts_with(key,'gm54_rfr:')",
    )
    .fetch_all(&mut other)
    .await
    .unwrap();
    assert_eq!(intents.len(), 1);
    assert_eq!(intents[0]["state"], "outcome_unknown");
    assert_eq!(
        intents[0]["reason"],
        "abandoned_refresh_requires_reauthorization"
    );
    assert!(!intents[0].to_string().contains("fictional-saved-refresh"));
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn local_mailbox_positive_refresh_response_after_lease_expiry_cannot_publish_new_credentials()
{
    let mut c = mailbox_fixture().await;
    mailbox_seed(&mut c, true).await;
    let settings = mailbox_settings();
    let google = MailboxGoogle {
        held_refresh: true,
        ..MailboxGoogle::default()
    };
    let service = Service {
        settings: &settings,
        provider: &google,
    };
    let mut other = connection().await;
    let request = service.access(&mut c, Slot::One);
    let expire = async {
        google.entered.notified().await;
        sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{refresh_lease_until}','\"2000-01-01T00:00:00Z\"') WHERE key='gm54_account:1'").execute(&mut other).await.unwrap();
        google.release.notify_one();
    };
    let (result, ()) = tokio::join!(request, expire);
    assert_eq!(result.err().map(|e| e.0), Some("gmail_refresh_unavailable"));
    assert_eq!(google.refreshes.get(), 1);
    let row = mailbox_row(&mut c, "1").await;
    assert_eq!(row["status"], "reauthorization_required");
    assert_eq!(row["refresh_outcome"], "outcome_unknown");
    assert!(row["access"].is_null());
    let intent: Value = sqlx::query_scalar(
        "SELECT value FROM owner_preferences WHERE starts_with(key,'gm54_rfr:')",
    )
    .fetch_one(&mut c)
    .await
    .unwrap();
    assert_eq!(intent["state"], "outcome_unknown");
    assert_eq!(intent["reason"], "gmail_refresh_lease_expired");
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn mailbox_suppressed_and_deferred_writes_never_acknowledge_or_dispatch_exchange() {
    let mut c = mailbox_fixture().await;
    let settings = mailbox_settings();
    let google = MailboxGoogle::default();
    let svc = Service {
        settings: &settings,
        provider: &google,
    };
    let browser = mailboxes::browser_nonce();
    sqlx::raw_sql("CREATE FUNCTION fixture_mailbox_suppress() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NULL; END $$;CREATE TRIGGER fixture_mailbox_suppress BEFORE INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_mailbox_suppress()").execute(&mut c).await.unwrap();
    assert_eq!(
        svc.start(&mut c, Slot::One, mailbox_consent(), &browser)
            .await
            .err(),
        Some(Failure("gmail_account_write_ack_failed"))
    );
    sqlx::raw_sql("DROP TRIGGER fixture_mailbox_suppress ON owner_preferences;CREATE FUNCTION fixture_mailbox_deferred() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'private fixture failure'; END $$;CREATE CONSTRAINT TRIGGER fixture_mailbox_deferred AFTER INSERT ON owner_preferences DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fixture_mailbox_deferred()").execute(&mut c).await.unwrap();
    assert_eq!(
        svc.start(&mut c, Slot::One, mailbox_consent(), &browser)
            .await
            .err(),
        Some(Failure("gmail_account_commit_outcome_unknown"))
    );
    assert_eq!(google.exchanges.get(), 0);
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM owner_preferences WHERE starts_with(key,'gm54_')"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        0
    );
}
async fn mailbox_google_http() -> (
    String,
    Arc<std::sync::Mutex<Vec<String>>>,
    CancellationToken,
    tokio::task::JoinHandle<()>,
) {
    use axum::{
        extract::{Request, State},
        response::IntoResponse,
    };
    let calls = Arc::new(std::sync::Mutex::new(Vec::new()));
    async fn handle(
        State(calls): State<Arc<std::sync::Mutex<Vec<String>>>>,
        request: Request,
    ) -> axum::response::Response {
        let method = request.method().to_string();
        let path = request.uri().path().to_string();
        calls.lock().unwrap().push(format!("{method} {path}"));
        let data = match (method.as_str(), path.as_str()) {
            ("POST", "/token") => {
                let body = axum::body::to_bytes(request.into_body(), 10000)
                    .await
                    .unwrap();
                let form = reqwest::Url::parse(&format!(
                    "http://127.0.0.1/?{}",
                    String::from_utf8(body.to_vec()).unwrap()
                ))
                .unwrap()
                .query_pairs()
                .into_owned()
                .collect::<BTreeMap<_, _>>();
                assert_eq!(form["grant_type"], "authorization_code");
                assert!((43..=128).contains(&form["code_verifier"].len()));
                json!({"access_token":"fictional-real-transport-access","refresh_token":"fictional-real-transport-refresh","expires_in":3600,"token_type":"Bearer","scope":scopes(GrantMode::ReadDraft).into_iter().collect::<Vec<_>>().join(" ")})
            }
            ("GET", "/userinfo") => {
                assert_eq!(
                    request.headers()["authorization"],
                    "Bearer fictional-real-transport-access"
                );
                json!({"sub":"fictional-subject","email":"fixture@example.com","email_verified":true})
            }
            ("GET", "/profile") => json!({"emailAddress":"fixture@example.com"}),
            ("POST", "/revoke") => json!({}),
            _ => return axum::http::StatusCode::NOT_FOUND.into_response(),
        };
        axum::Json(data).into_response()
    }
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    let stop = CancellationToken::new();
    let shutdown = stop.clone();
    let router = axum::Router::new()
        .fallback(handle)
        .with_state(calls.clone());
    let task = tokio::spawn(async move {
        axum::serve(listener, router)
            .with_graceful_shutdown(shutdown.cancelled_owned())
            .await
            .unwrap();
    });
    (url, calls, stop, task)
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn mailbox_actual_http_consent_cookie_callback_verify_disconnect_without_owner_credentials() {
    let mut c = mailbox_fixture().await;
    let (google, calls, google_stop, google_task) = mailbox_google_http().await;
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let url = format!("http://{address}");
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
    let account = format!("{url}{}/1", mailboxes::routes::ACCOUNTS);
    assert_eq!(
        http.get(format!("{url}{}", mailboxes::routes::ACCOUNTS))
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    assert_eq!(
        http.post(format!("{account}/connect"))
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"account_consent":true,"read_and_draft_consent":"yes"}))
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    let response = http
        .post(format!("{account}/connect"))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"account_consent":true,"read_and_draft_consent":true}))
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let cookie = response.headers()["set-cookie"]
        .to_str()
        .unwrap()
        .to_owned();
    assert!(cookie.contains("HttpOnly"));
    assert!(cookie.contains("SameSite=Lax"));
    assert!(cookie.contains("Path=/api/v1/integrations/gmail/oauth/callback"));
    let cookie = cookie.split(';').next().unwrap();
    let start: Value = response.json().await.unwrap();
    let state = mailbox_state(&start);
    assert_eq!(
        http.get(&callback)
            .query(&[("state", state.as_str()), ("code", "fictional-code")])
            .send()
            .await
            .unwrap()
            .status(),
        400
    );
    assert_eq!(calls.lock().unwrap().len(), 0);
    let response = http
        .get(&callback)
        .query(&[("state", state.as_str()), ("code", "fictional-code")])
        .header("cookie", cookie)
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
    let data: Value = response.json().await.unwrap();
    assert_eq!(data["connection"]["status"], "connected");
    assert!(!data.to_string().contains("fictional-real-transport"));
    assert_eq!(
        calls.lock().unwrap().as_slice(),
        ["POST /token", "GET /userinfo", "GET /profile"]
    );
    assert_eq!(
        http.get(&callback)
            .query(&[("state", state.as_str()), ("code", "fictional-code")])
            .header("cookie", cookie)
            .send()
            .await
            .unwrap()
            .status(),
        400
    );
    assert_eq!(calls.lock().unwrap().len(), 3);
    assert_eq!(
        http.post(format!("{account}/verify"))
            .bearer_auth(HOST_TOKEN)
            .json(&json!({}))
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    let data: Value = http
        .get(format!("{url}{}", mailboxes::routes::ACCOUNTS))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(data["accounts"][0]["status"], "connected");
    assert_eq!(data["sending_enabled"], false);
    assert_eq!(data["monitoring_enabled"], false);
    let disconnected: Value = http
        .post(format!("{account}/disconnect"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(disconnected["revocation"], "confirmed");
    assert_eq!(
        mailbox_row(&mut c, "1").await,
        json!({"status":"disconnected","generation":2})
    );
    stop.cancel();
    task.await.unwrap();
    google_stop.cancel();
    google_task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn mailbox_superseded_refresh_cannot_clear_a_newer_success_after_lease_expiry() {
    let mut c = mailbox_fixture().await;
    mailbox_seed(&mut c, true).await;
    let mut other = connection().await;
    let settings = mailbox_settings();
    let old = MailboxGoogle {
        held_refresh: true,
        ..Default::default()
    };
    old.fail
        .set(Some(Failure("credential_revoked_or_code_invalid")));
    let newer = MailboxGoogle::default();
    let old_svc = Service {
        settings: &settings,
        provider: &old,
    };
    let new_svc = Service {
        settings: &settings,
        provider: &newer,
    };
    let access = old_svc.access(&mut c, Slot::One);
    let competing = async {
        old.entered.notified().await;
        sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{refresh_lease_until}',to_jsonb('2020-01-01T00:00:00+00:00'::text)) WHERE key='gm54_account:1'").execute(&mut other).await.unwrap();
        assert_eq!(
            new_svc.access(&mut other, Slot::One).await.unwrap().token(),
            "fictional-refreshed-access"
        );
        old.release.notify_one();
    };
    let (result, ()) = tokio::join!(access, competing);
    assert_eq!(result.err().map(|e| e.0), Some("gmail_refresh_superseded"));
    let row = mailbox_row(&mut c, "1").await;
    assert_eq!(row["status"], "connected");
    assert!(row["access"].is_string());
    assert!(row.get("refresh_lease").is_none());
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn mailbox_expired_and_superseded_intents_never_exchange_and_verification_mismatch_closes_access()
 {
    let mut c = mailbox_fixture().await;
    let settings = mailbox_settings();
    let google = MailboxGoogle::default();
    let svc = Service {
        settings: &settings,
        provider: &google,
    };
    let browser = mailboxes::browser_nonce();
    let state = mailbox_state(
        &svc.start(&mut c, Slot::One, mailbox_consent(), &browser)
            .await
            .unwrap(),
    );
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{expires_at}',to_jsonb('2020-01-01T00:00:00+00:00'::text)) WHERE starts_with(key,'gm54_oauth:')").execute(&mut c).await.unwrap();
    assert_eq!(
        svc.callback(
            &mut c,
            &state,
            &browser,
            google.redirect_uri(),
            Some("code"),
            None
        )
        .await
        .err(),
        Some(Failure("invalid_expired_or_replayed_state"))
    );
    let state = mailbox_state(
        &svc.start(&mut c, Slot::One, mailbox_consent(), &browser)
            .await
            .unwrap(),
    );
    let current = svc
        .start(&mut c, Slot::One, mailbox_consent(), &browser)
        .await
        .unwrap();
    assert_eq!(
        svc.callback(
            &mut c,
            &state,
            &browser,
            google.redirect_uri(),
            Some("code"),
            None
        )
        .await
        .err(),
        Some(Failure("connection_intent_superseded"))
    );
    assert_eq!(google.exchanges.get(), 0);
    svc.callback(
        &mut c,
        &mailbox_state(&current),
        &browser,
        google.redirect_uri(),
        Some("code"),
        None,
    )
    .await
    .unwrap();
    *google.identity.borrow_mut() = ("other-subject".into(), "other@example.com".into());
    assert_eq!(
        svc.verify(&mut c, Slot::One).await.err(),
        Some(Failure("gmail_identity_mismatch"))
    );
    let row = mailbox_row(&mut c, "1").await;
    assert_eq!(row["status"], "reauthorization_required");
    assert!(row["access"].is_null());
}
