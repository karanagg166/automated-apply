//! Deferred original read-account OAuth/refresh guards. Fixed fake provider, no real mail.
use sha2::Digest as _;
struct ReadGoogle {
    mode: Cell<bool>,
    identity: RefCell<(String, String)>,
    exchanges: Cell<usize>,
    refreshes: Cell<usize>,
    revokes: Cell<usize>,
    fail_refresh: Cell<bool>,
    fail_revoke: Cell<bool>,
    held_refresh: bool,
    held_exchange: bool,
    entered: tokio::sync::Notify,
    release: tokio::sync::Notify,
}
impl Default for ReadGoogle {
    fn default() -> Self {
        Self {
            mode: Cell::new(false),
            identity: RefCell::new((
                "fictional-read-subject".into(),
                "fixture@example.com".into(),
            )),
            exchanges: Cell::new(0),
            refreshes: Cell::new(0),
            revokes: Cell::new(0),
            fail_refresh: Cell::new(false),
            fail_revoke: Cell::new(false),
            held_refresh: false,
            held_exchange: false,
            entered: tokio::sync::Notify::new(),
            release: tokio::sync::Notify::new(),
        }
    }
}
fn read_tokens(body: bool) -> TokenResponse {
    TokenResponse::parse(json!({"access_token":"fictional-read-access","refresh_token":"fictional-read-refresh","token_type":"Bearer","expires_in":3600,"scope":scopes(if body{GrantMode::Read}else{GrantMode::Metadata}).into_iter().collect::<Vec<_>>().join(" ")})).unwrap()
}
impl automated_apply_agents::gmail_accounts::oauth::Provider for ReadGoogle {
    fn redirect_uri(&self) -> &str {
        "https://workspace.example/api/v1/integrations/gmail/oauth/callback"
    }
    fn authorization_url(
        &self,
        state: &str,
        _verifier: &str,
        email: Option<&str>,
        mode: GrantMode,
    ) -> Result<String> {
        self.mode.set(matches!(mode, GrantMode::Read));
        let mut url = reqwest::Url::parse("https://accounts.google.com/o/oauth2/v2/auth").unwrap();
        url.query_pairs_mut()
            .append_pair("state", state)
            .append_pair(
                "scope",
                &scopes(mode).into_iter().collect::<Vec<_>>().join(" "),
            );
        if let Some(email) = email {
            url.query_pairs_mut().append_pair("login_hint", email);
        }
        Ok(url.into())
    }
    async fn exchange(&self, _code: &str, _verifier: &str) -> Result<TokenResponse> {
        self.exchanges.set(self.exchanges.get() + 1);
        if self.held_exchange {
            self.entered.notify_one();
            self.release.notified().await;
        }
        Ok(read_tokens(self.mode.get()))
    }
    async fn refresh(&self, _refresh: &str) -> Result<TokenResponse> {
        self.refreshes.set(self.refreshes.get() + 1);
        if self.held_refresh {
            self.entered.notify_one();
            self.release.notified().await;
        }
        if self.fail_refresh.get() {
            return Err(Failure("google_transport_or_response_error"));
        }
        Ok(read_tokens(self.mode.get()))
    }
    async fn identity(&self, _token: &str) -> Result<(String, String)> {
        Ok(self.identity.borrow().clone())
    }
    async fn revoke(&self, _token: &str) -> Result<()> {
        self.revokes.set(self.revokes.get() + 1);
        if self.fail_revoke.get() {
            Err(Failure("google_transport_or_response_error"))
        } else {
            Ok(())
        }
    }
}
async fn gmail_read_oauth_fixture() -> (
    PgConnection,
    Uuid,
    automated_apply_agents::gmail_accounts::Settings,
) {
    let (mut c, one, _two) = gmail_read_fixture().await;
    sqlx::query("UPDATE gmail_read_accounts SET status='disconnected',google_subject='',granted_scopes='[]',encrypted_access_token=NULL,encrypted_refresh_token=NULL WHERE id=$1").bind(one).execute(&mut c).await.unwrap();
    (c, one, gmail_read_settings())
}
fn read_state(start: &Value) -> String {
    reqwest::Url::parse(start["authorization_url"].as_str().unwrap())
        .unwrap()
        .query_pairs()
        .find(|(k, _)| k == "state")
        .unwrap()
        .1
        .into_owned()
}
async fn read_oauth_authorize(
    c: &mut PgConnection,
    id: Uuid,
    settings: &automated_apply_agents::gmail_accounts::Settings,
    google: &ReadGoogle,
) -> Value {
    let service = automated_apply_agents::gmail_accounts::oauth::Service {
        settings,
        provider: google,
    };
    let browser = "b".repeat(64);
    let start = service
        .start(c, json!({"account_consent":true}), Some(id), &browser)
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
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_read_oauth_consumes_once_and_uses_original_context_bound_tokens_without_send_scope()
{
    let (mut c, id, settings) = gmail_read_oauth_fixture().await;
    let google = ReadGoogle::default();
    let service = automated_apply_agents::gmail_accounts::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    let browser = "b".repeat(64);
    let start = service
        .start(&mut c, json!({"account_consent":true}), Some(id), &browser)
        .await
        .unwrap();
    let state = read_state(&start);
    assert!(state.starts_with("read."));
    assert!(!start.to_string().contains("gmail.compose"));
    let result = service
        .callback(
            &mut c,
            &state,
            &browser,
            "https://workspace.example/api/v1/integrations/gmail/oauth/callback",
            Some("fictional-code"),
            None,
        )
        .await
        .unwrap();
    assert_eq!(result["permissions"]["send"], false);
    assert_eq!(result["permissions"]["read_metadata"], true);
    assert_eq!(result["live_verified"], false);
    assert_eq!(google.exchanges.get(), 1);
    assert_eq!(
        service
            .callback(
                &mut c,
                &state,
                &browser,
                "https://workspace.example/api/v1/integrations/gmail/oauth/callback",
                Some("fictional-code"),
                None
            )
            .await
            .unwrap_err(),
        Failure("invalid_expired_or_replayed_state")
    );
    assert_eq!(google.exchanges.get(), 1);
    let envelope:(String,String)=sqlx::query_as("SELECT encrypted_access_token,encrypted_refresh_token FROM gmail_read_accounts WHERE id=$1").bind(id).fetch_one(&mut c).await.unwrap();
    let store = TokenStore::from_values(&mailbox_values()).unwrap().unwrap();
    assert_eq!(
        store.decrypt(&envelope.0, &format!("{id}:access")).unwrap(),
        "fictional-read-access"
    );
    assert_eq!(
        store
            .decrypt(&envelope.1, &format!("{id}:refresh"))
            .unwrap(),
        "fictional-read-refresh"
    );
    let verifier: Option<String> = sqlx::query_scalar(
        "SELECT encrypted_verifier FROM gmail_read_oauth_states WHERE state_hash=$1",
    )
    .bind(format!("{:x}", sha2::Sha256::digest(state.as_bytes())))
    .fetch_one(&mut c)
    .await
    .unwrap();
    assert!(verifier.is_none());
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_read_oauth_wrong_cookie_or_uri_does_not_consume_but_denied_consent_consumes_without_exchange()
 {
    let (mut c, id, settings) = gmail_read_oauth_fixture().await;
    let google = ReadGoogle::default();
    let service = automated_apply_agents::gmail_accounts::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    let browser = "b".repeat(64);
    let state = read_state(
        &service
            .start(&mut c, json!({"account_consent":true}), Some(id), &browser)
            .await
            .unwrap(),
    );
    assert_eq!(
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
            .unwrap_err(),
        Failure("invalid_expired_or_replayed_state")
    );
    assert_eq!(
        service
            .callback(
                &mut c,
                &state,
                &browser,
                "https://wrong.example/api/v1/integrations/gmail/oauth/callback",
                Some("code"),
                None
            )
            .await
            .unwrap_err(),
        Failure("invalid_oauth_state_or_redirect")
    );
    assert_eq!(
        service
            .callback(
                &mut c,
                &state,
                &browser,
                "https://workspace.example/api/v1/integrations/gmail/oauth/callback",
                None,
                Some("access_denied")
            )
            .await
            .unwrap_err(),
        Failure("consent_denied")
    );
    assert_eq!(google.exchanges.get(), 0);
    assert_eq!(
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
            .unwrap_err(),
        Failure("invalid_expired_or_replayed_state")
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_read_oauth_exchange_releases_owner_lock_and_disconnect_fences_late_identity_publication()
 {
    let (mut c, id, settings) = gmail_read_oauth_fixture().await;
    let google = ReadGoogle {
        held_exchange: true,
        ..ReadGoogle::default()
    };
    let service = automated_apply_agents::gmail_accounts::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    let browser = "b".repeat(64);
    let state = read_state(
        &service
            .start(&mut c, json!({"account_consent":true}), Some(id), &browser)
            .await
            .unwrap(),
    );
    let mut other = connection().await;
    let complete = service.callback(
        &mut c,
        &state,
        &browser,
        "https://workspace.example/api/v1/integrations/gmail/oauth/callback",
        Some("code"),
        None,
    );
    let supersede = async {
        google.entered.notified().await;
        let mut owner = other.begin().await.unwrap();
        sqlx::query("SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE NOWAIT").execute(&mut *owner).await.unwrap();
        owner.commit().await.unwrap();
        service.disconnect(&mut other, id).await.unwrap();
        google.release.notify_one();
    };
    let (result, ()) = tokio::join!(complete, supersede);
    assert_eq!(result.unwrap_err(), Failure("connection_intent_superseded"));
    assert_eq!(
        sqlx::query_scalar::<_, String>("SELECT status FROM gmail_read_accounts WHERE id=$1")
            .bind(id)
            .fetch_one(&mut c)
            .await
            .unwrap(),
        "disconnected"
    );
    assert_eq!(google.exchanges.get(), 1);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_read_oauth_anonymous_account_chooser_binds_original_pending_row_and_keeps_outreach_account_separate()
 {
    let (mut c, _id, settings) = gmail_read_oauth_fixture().await;
    let google = ReadGoogle::default();
    let service = automated_apply_agents::gmail_accounts::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    let browser = "b".repeat(64);
    let start = service
        .start(&mut c, json!({"account_consent":true}), None, &browser)
        .await
        .unwrap();
    let url = reqwest::Url::parse(start["authorization_url"].as_str().unwrap()).unwrap();
    assert!(!url.query_pairs().any(|(k, _)| k == "login_hint"));
    let pending: Uuid = sqlx::query_scalar(
        "SELECT id FROM gmail_read_accounts WHERE starts_with(account_email,'pending:')",
    )
    .fetch_one(&mut c)
    .await
    .unwrap();
    browser_save(
        &mut c,
        "gmail_drafts:account",
        json!({"google_subject":"fictional-read-subject","account_email":"fixture@example.com"}),
    )
    .await;
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
        Failure("gmail_separate_outreach_account_required")
    );
    assert_eq!(
        sqlx::query_scalar::<_, String>("SELECT status FROM gmail_read_accounts WHERE id=$1")
            .bind(pending)
            .fetch_one(&mut c)
            .await
            .unwrap(),
        "disconnected"
    );
    assert_eq!(google.exchanges.get(), 1);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_read_cached_access_and_refresh_preserve_original_token_purposes_and_record_one_attempt()
 {
    let (mut c, id, settings) = gmail_read_oauth_fixture().await;
    let google = ReadGoogle::default();
    read_oauth_authorize(&mut c, id, &settings, &google).await;
    let service = automated_apply_agents::gmail_accounts::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    let cached = service.access(&mut c, id).await.unwrap();
    assert_eq!(cached.token(), "fictional-read-access");
    assert_eq!(google.refreshes.get(), 0);
    sqlx::query(
        "UPDATE gmail_read_accounts SET token_expires_at='2000-01-01T00:00:00Z' WHERE id=$1",
    )
    .bind(id)
    .execute(&mut c)
    .await
    .unwrap();
    let refreshed = service.access(&mut c, id).await.unwrap();
    assert!(refreshed.generation().unwrap() > cached.generation().unwrap());
    assert_eq!(google.refreshes.get(), 1);
    let records: Vec<Value> =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE starts_with(key,'gm_rfr:')")
            .fetch_all(&mut c)
            .await
            .unwrap();
    assert_eq!(records.len(), 1);
    assert_eq!(records[0]["state"], "completed");
    assert_eq!(
        records[0]["published_generation"],
        refreshed.generation().unwrap()
    );
    assert!(!records[0].to_string().contains("fictional-read-access"));
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_read_lost_refresh_response_is_not_replayed_after_restart_and_requires_reauthorization()
 {
    let (mut c, id, settings) = gmail_read_oauth_fixture().await;
    let google = ReadGoogle {
        held_refresh: true,
        ..ReadGoogle::default()
    };
    read_oauth_authorize(&mut c, id, &settings, &google).await;
    sqlx::query(
        "UPDATE gmail_read_accounts SET token_expires_at='2000-01-01T00:00:00Z' WHERE id=$1",
    )
    .bind(id)
    .execute(&mut c)
    .await
    .unwrap();
    let service = automated_apply_agents::gmail_accounts::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    {
        let request = service.access(&mut c, id);
        tokio::pin!(request);
        tokio::select! {_ = google.entered.notified()=>{},result=&mut request=>panic!("refresh unexpectedly completed: {}",result.is_ok())};
    }
    // Dropping the future simulates process loss; use an independent connection for restart.
    let mut other = connection().await;
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{lease_until}','\"2000-01-01T00:00:00Z\"') WHERE starts_with(key,'gm_rfr:')").execute(&mut other).await.unwrap();
    let restarted = ReadGoogle::default();
    let service = automated_apply_agents::gmail_accounts::oauth::Service {
        settings: &settings,
        provider: &restarted,
    };
    let result = service.access(&mut other, id).await;
    assert!(matches!(
        result,
        Err(Failure("gmail_refresh_outcome_unknown"))
    ));
    assert_eq!(restarted.refreshes.get(), 0);
    assert_eq!(
        sqlx::query_scalar::<_, String>("SELECT status FROM gmail_read_accounts WHERE id=$1")
            .bind(id)
            .fetch_one(&mut other)
            .await
            .unwrap(),
        "reauthorization_required"
    );
    let intent: Value =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE starts_with(key,'gm_rfr:')")
            .fetch_one(&mut other)
            .await
            .unwrap();
    assert_eq!(intent["state"], "outcome_unknown");
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_read_refresh_releases_owner_lock_and_cannot_undo_concurrent_disconnect() {
    let (mut c, id, settings) = gmail_read_oauth_fixture().await;
    let google = ReadGoogle {
        held_refresh: true,
        ..ReadGoogle::default()
    };
    read_oauth_authorize(&mut c, id, &settings, &google).await;
    sqlx::query(
        "UPDATE gmail_read_accounts SET token_expires_at='2000-01-01T00:00:00Z' WHERE id=$1",
    )
    .bind(id)
    .execute(&mut c)
    .await
    .unwrap();
    let service = automated_apply_agents::gmail_accounts::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    let mut other = connection().await;
    let refresh = service.access(&mut c, id);
    let disconnect = async {
        google.entered.notified().await;
        let mut owner = other.begin().await.unwrap();
        sqlx::query("SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE NOWAIT").execute(&mut *owner).await.unwrap();
        owner.commit().await.unwrap();
        service.disconnect(&mut other, id).await.unwrap();
        google.release.notify_one();
    };
    let (result, ()) = tokio::join!(refresh, disconnect);
    assert!(matches!(result, Err(Failure("gmail_refresh_superseded"))));
    assert_eq!(
        sqlx::query_scalar::<_, String>("SELECT status FROM gmail_read_accounts WHERE id=$1")
            .bind(id)
            .fetch_one(&mut c)
            .await
            .unwrap(),
        "disconnected"
    );
    assert_eq!(google.refreshes.get(), 1);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_read_disconnect_fences_credentials_selection_evidence_and_oauth_before_unconfirmed_revocation()
 {
    let (mut c, id, settings) = gmail_read_oauth_fixture().await;
    let google = ReadGoogle::default();
    read_oauth_authorize(&mut c, id, &settings, &google).await;
    gmail_read_seed_evidence(
        &mut c,
        &"a".repeat(32),
        id,
        "2099-01-01T00:00:00Z",
        "2020-01-01T00:00:00Z",
    )
    .await;
    browser_save(
        &mut c,
        &format!("gmail_sync:{}", id.simple()),
        json!({"version":3,"policy":{"enabled":true},"lease_id":"old-sync"}),
    )
    .await;
    let service = automated_apply_agents::gmail_accounts::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    google.fail_revoke.set(true);
    let result = service.disconnect(&mut c, id).await.unwrap();
    assert_eq!(result["status"], "disconnected");
    assert_eq!(
        result["revocation"],
        "unconfirmed_revoke_in_google_account_settings"
    );
    assert_eq!(google.revokes.get(), 1);
    let account: Value =
        sqlx::query_scalar("SELECT to_jsonb(a) FROM gmail_read_accounts a WHERE id=$1")
            .bind(id)
            .fetch_one(&mut c)
            .await
            .unwrap();
    assert_eq!(account["encrypted_access_token"], Value::Null);
    assert_eq!(account["encrypted_refresh_token"], Value::Null);
    assert_eq!(
        browser_pref(&mut c, &format!("gmail_msg:{}", "a".repeat(32))).await,
        json!({"status":"purged"})
    );
    assert_eq!(
        browser_pref(&mut c, &format!("gmail_sync:{}", id.simple())).await,
        json!({"version":4,"status":"disabled","policy":{"enabled":false}})
    );
    service.disconnect(&mut c, id).await.unwrap();
    assert_eq!(google.revokes.get(), 1);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_read_refresh_provider_failure_records_unknown_and_never_retries_the_same_intent() {
    let (mut c, id, settings) = gmail_read_oauth_fixture().await;
    let google = ReadGoogle::default();
    read_oauth_authorize(&mut c, id, &settings, &google).await;
    sqlx::query(
        "UPDATE gmail_read_accounts SET token_expires_at='2000-01-01T00:00:00Z' WHERE id=$1",
    )
    .bind(id)
    .execute(&mut c)
    .await
    .unwrap();
    google.fail_refresh.set(true);
    let service = automated_apply_agents::gmail_accounts::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    assert!(matches!(
        service.access(&mut c, id).await,
        Err(Failure("gmail_reauthorization_required"))
    ));
    assert!(matches!(
        service.access(&mut c, id).await,
        Err(Failure("gmail_not_connected"))
    ));
    assert_eq!(google.refreshes.get(), 1);
    let intent: Value =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE starts_with(key,'gm_rfr:')")
            .fetch_one(&mut c)
            .await
            .unwrap();
    assert_eq!(intent["state"], "outcome_unknown");
    assert_eq!(intent["reason"], "google_transport_or_response_error");
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_read_suppressed_callback_verifier_clear_cannot_consume_or_exchange_authorization_code()
 {
    let (mut c, id, settings) = gmail_read_oauth_fixture().await;
    let google = ReadGoogle::default();
    let service = automated_apply_agents::gmail_accounts::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    let browser = "b".repeat(64);
    let state = read_state(
        &service
            .start(&mut c, json!({"account_consent":true}), Some(id), &browser)
            .await
            .unwrap(),
    );
    sqlx::raw_sql("CREATE FUNCTION fixture_read_verifier_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.encrypted_verifier IS NULL AND OLD.encrypted_verifier IS NOT NULL THEN RETURN NULL; END IF; RETURN NEW; END $$; CREATE TRIGGER fixture_read_verifier_drop BEFORE UPDATE ON gmail_read_oauth_states FOR EACH ROW EXECUTE FUNCTION fixture_read_verifier_drop()").execute(&mut c).await.unwrap();
    let result = service
        .callback(
            &mut c,
            &state,
            &browser,
            "https://workspace.example/api/v1/integrations/gmail/oauth/callback",
            Some("code"),
            None,
        )
        .await;
    sqlx::raw_sql("DROP TRIGGER fixture_read_verifier_drop ON gmail_read_oauth_states; DROP FUNCTION fixture_read_verifier_drop()").execute(&mut c).await.unwrap();
    assert_eq!(result.unwrap_err(), Failure("gmail_read_write_ack_failed"));
    assert_eq!(google.exchanges.get(), 0);
    let consumed: bool = sqlx::query_scalar(
        "SELECT consumed_at IS NOT NULL FROM gmail_read_oauth_states WHERE state_hash=$1",
    )
    .bind(format!("{:x}", sha2::Sha256::digest(state.as_bytes())))
    .fetch_one(&mut c)
    .await
    .unwrap();
    assert!(!consumed);
    service
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
    assert_eq!(google.exchanges.get(), 1);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_read_refresh_expiring_while_provider_waits_cannot_publish_positive_late_result() {
    let (mut c, id, settings) = gmail_read_oauth_fixture().await;
    let google = ReadGoogle {
        held_refresh: true,
        ..ReadGoogle::default()
    };
    read_oauth_authorize(&mut c, id, &settings, &google).await;
    sqlx::query(
        "UPDATE gmail_read_accounts SET token_expires_at='2000-01-01T00:00:00Z' WHERE id=$1",
    )
    .bind(id)
    .execute(&mut c)
    .await
    .unwrap();
    let before: i32 =
        sqlx::query_scalar("SELECT token_generation FROM gmail_read_accounts WHERE id=$1")
            .bind(id)
            .fetch_one(&mut c)
            .await
            .unwrap();
    let service = automated_apply_agents::gmail_accounts::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    let mut other = connection().await;
    let refresh = service.access(&mut c, id);
    let expire = async {
        google.entered.notified().await;
        sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{lease_until}','\"2000-01-01T00:00:00Z\"') WHERE starts_with(key,'gm_rfr:')").execute(&mut other).await.unwrap();
        google.release.notify_one();
    };
    let (result, ()) = tokio::join!(refresh, expire);
    assert!(matches!(
        result,
        Err(Failure("gmail_reauthorization_required"))
    ));
    assert_eq!(
        sqlx::query_scalar::<_, i32>(
            "SELECT token_generation FROM gmail_read_accounts WHERE id=$1"
        )
        .bind(id)
        .fetch_one(&mut c)
        .await
        .unwrap(),
        before
    );
    let intent: Value =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE starts_with(key,'gm_rfr:')")
            .fetch_one(&mut c)
            .await
            .unwrap();
    assert_eq!(intent["state"], "outcome_unknown");
    assert_eq!(intent["reason"], "gmail_refresh_permit_expired");
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_read_wrong_account_and_scope_response_consume_intent_without_storing_credentials() {
    let (mut c, id, settings) = gmail_read_oauth_fixture().await;
    let google = ReadGoogle::default();
    let service = automated_apply_agents::gmail_accounts::oauth::Service {
        settings: &settings,
        provider: &google,
    };
    let browser = "b".repeat(64);
    let start = service
        .start(&mut c, json!({"account_consent":true}), Some(id), &browser)
        .await
        .unwrap();
    *google.identity.borrow_mut() = ("other-subject".into(), "other@example.com".into());
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
        Failure("wrong_google_account")
    );
    let start = service
        .start(&mut c, json!({"account_consent":true}), Some(id), &browser)
        .await
        .unwrap();
    google.mode.set(true);
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
        Failure("unexpected_or_insufficient_scopes")
    );
    let token: Option<String> =
        sqlx::query_scalar("SELECT encrypted_access_token FROM gmail_read_accounts WHERE id=$1")
            .bind(id)
            .fetch_one(&mut c)
            .await
            .unwrap();
    assert!(token.is_none());
    assert_eq!(google.exchanges.get(), 2);
}
async fn read_google_http() -> (
    String,
    Arc<std::sync::Mutex<Vec<String>>>,
    CancellationToken,
    tokio::task::JoinHandle<()>,
) {
    use axum::{
        extract::{Request, State},
        response::IntoResponse,
    };
    let calls = Arc::new(std::sync::Mutex::new(Vec::<String>::new()));
    async fn handle(
        State(calls): State<Arc<std::sync::Mutex<Vec<String>>>>,
        request: Request,
    ) -> axum::response::Response {
        let method = request.method().to_string();
        let path = request.uri().path().to_string();
        calls.lock().unwrap().push(format!("{method} {path}"));
        let value = match (method.as_str(), path.as_str()) {
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
                json!({"access_token":"fictional-read-http-access","refresh_token":"fictional-read-http-refresh","expires_in":3600,"token_type":"Bearer","scope":scopes(GrantMode::Metadata).into_iter().collect::<Vec<_>>().join(" ")})
            }
            ("GET", "/userinfo") => {
                assert_eq!(
                    request.headers()["authorization"],
                    "Bearer fictional-read-http-access"
                );
                json!({"sub":"fictional-read-http-subject","email":"fixture@example.com","email_verified":true})
            }
            ("GET", "/profile") => json!({"emailAddress":"fixture@example.com"}),
            ("POST", "/revoke") => json!({}),
            _ => return axum::http::StatusCode::NOT_FOUND.into_response(),
        };
        axum::Json(value).into_response()
    }
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    let stop = CancellationToken::new();
    let shutdown = stop.clone();
    let router = axum::Router::new()
        .fallback(handle)
        .with_state(calls.clone());
    let server = tokio::spawn(async move {
        axum::serve(listener, router)
            .with_graceful_shutdown(shutdown.cancelled_owned())
            .await
            .unwrap();
    });
    (url, calls, stop, server)
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn gmail_read_actual_http_owner_consent_cookie_callback_verify_disconnect_use_fixed_transport()
 {
    let (mut c, id, _settings) = gmail_read_oauth_fixture().await;
    let (google, calls, google_stop, google_server) = read_google_http().await;
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
    let server = tokio::spawn(async move {
        axum::serve(
            listener,
            server::router(api).into_make_service_with_connect_info::<std::net::SocketAddr>(),
        )
        .with_graceful_shutdown(shutdown.cancelled_owned())
        .await
        .unwrap();
    });
    let http = client();
    let endpoint = format!(
        "{url}{}/connect/start",
        automated_apply_agents::gmail_accounts::PATH
    );
    assert_eq!(
        http.post(&endpoint)
            .json(&json!({"account_consent":true}))
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
    let start = http
        .post(&endpoint)
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"account_consent":true,"expected_email":"fixture@example.com"}))
        .send()
        .await
        .unwrap();
    let code = start.status();
    let cookie = start.headers()["set-cookie"]
        .to_str()
        .unwrap()
        .split(';')
        .next()
        .unwrap()
        .to_owned();
    let start: Value = start.json().await.unwrap();
    assert_eq!(code, 200, "{start}");
    assert!(cookie.starts_with("gmail_oauth_browser="));
    let state = read_state(&start);
    let result = http
        .get(format!("{callback}?state={state}&code=fictional-code"))
        .header("cookie", &cookie)
        .send()
        .await
        .unwrap();
    let code = result.status();
    let result: Value = result.json().await.unwrap();
    assert_eq!(code, 200, "{result}");
    assert_eq!(result["connection"]["id"], id.to_string());
    assert_eq!(result["connection"]["permissions"]["send"], false);
    assert_eq!(
        http.get(format!("{callback}?state={state}&code=fictional-code"))
            .header("cookie", &cookie)
            .send()
            .await
            .unwrap()
            .status(),
        400
    );
    assert_eq!(
        http.post(format!("{url}{}", gmail_read_path(id, "/verify")))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    assert_eq!(
        http.post(format!("{url}{}", gmail_read_path(id, "/disconnect")))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    let calls = calls.lock().unwrap().clone();
    assert_eq!(calls.iter().filter(|s| *s == "POST /token").count(), 1);
    assert_eq!(calls.iter().filter(|s| *s == "POST /revoke").count(), 1);
    assert!(calls.iter().all(|s| matches!(
        s.as_str(),
        "POST /token" | "POST /revoke" | "GET /userinfo" | "GET /profile"
    )));
    assert_eq!(
        sqlx::query_scalar::<_, String>("SELECT status FROM gmail_read_accounts WHERE id=$1")
            .bind(id)
            .fetch_one(&mut c)
            .await
            .unwrap(),
        "disconnected"
    );
    stop.cancel();
    server.await.unwrap();
    google_stop.cancel();
    google_server.await.unwrap();
}
