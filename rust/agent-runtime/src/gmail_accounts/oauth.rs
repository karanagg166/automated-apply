//! Original read.* OAuth intents: commit consume before exchange; no owner lock spans HTTP.
use super::*;
use crate::google_oauth::{GoogleOAuth, GrantMode, TokenResponse};
#[allow(async_fn_in_trait)]
pub trait Provider {
    fn redirect_uri(&self) -> &str;
    fn authorization_url(
        &self,
        state: &str,
        verifier: &str,
        email: Option<&str>,
        mode: GrantMode,
    ) -> Result<String>;
    async fn exchange(&self, code: &str, verifier: &str) -> Result<TokenResponse>;
    async fn refresh(&self, refresh: &str) -> Result<TokenResponse>;
    async fn identity(&self, token: &str) -> Result<(String, String)>;
    async fn revoke(&self, token: &str) -> Result<()>;
}
impl Provider for GoogleOAuth {
    fn redirect_uri(&self) -> &str {
        self.redirect_uri()
    }
    fn authorization_url(
        &self,
        state: &str,
        verifier: &str,
        email: Option<&str>,
        mode: GrantMode,
    ) -> Result<String> {
        self.authorization_url(state, verifier, email, mode)
    }
    async fn exchange(&self, code: &str, verifier: &str) -> Result<TokenResponse> {
        self.exchange(code, verifier).await
    }
    async fn refresh(&self, refresh: &str) -> Result<TokenResponse> {
        self.refresh(refresh).await
    }
    async fn identity(&self, token: &str) -> Result<(String, String)> {
        self.identity(token).await
    }
    async fn revoke(&self, token: &str) -> Result<()> {
        self.revoke(token).await
    }
}
pub struct Service<'a, P> {
    pub settings: &'a Settings,
    pub provider: &'a P,
}
pub(super) fn digest(raw: &str) -> String {
    format!("{:x}", Sha256::digest(raw.as_bytes()))
}
pub(super) fn text<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    value[key]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or_else(invalid)
}
pub(super) fn generation(value: &Value) -> Result<i64> {
    value["token_generation"]
        .as_i64()
        .filter(|n| *n > 0)
        .ok_or_else(invalid)
}
pub(super) fn at(value: &Value) -> Result<DateTime<Utc>> {
    crate::gmail_history::contract::timestamp(value)
        .map(|at| at.with_timezone(&Utc))
        .ok_or_else(invalid)
}
pub(super) async fn begin(c: &mut PgConnection) -> Result<Transaction<'_, Postgres>> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    crate::execution::lock_owner_in(&mut tx).await?;
    sqlx::query("SELECT pg_advisory_xact_lock(407006,1)")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    if !schema(&mut tx).await? {
        return Err(Failure("gmail_readonly_schema_update_required"));
    }
    Ok(tx)
}
pub(super) async fn commit(tx: Transaction<'_, Postgres>) -> Result<()> {
    tx.commit()
        .await
        .map_err(|_| Failure("gmail_read_commit_outcome_unknown"))
}
fn browser(raw: &str) -> bool {
    (32..=128).contains(&raw.len())
        && raw
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'-'))
}
pub struct Callback {
    pub state: String,
    pub code: Option<String>,
    pub error: Option<String>,
}
pub fn callback(query: Option<&str>) -> Result<Callback> {
    let invalid = || Failure("invalid_oauth_callback");
    let raw = query.filter(|s| s.len() <= 16000).ok_or_else(invalid)?;
    let url = reqwest::Url::parse(&format!("http://127.0.0.1/?{raw}")).map_err(|_| invalid())?;
    let mut values = BTreeMap::new();
    for (k, v) in url.query_pairs() {
        if ![
            "state",
            "code",
            "error",
            "scope",
            "authuser",
            "prompt",
            "error_description",
            "error_uri",
        ]
        .contains(&k.as_ref())
            || values.insert(k.to_string(), v.to_string()).is_some()
        {
            return Err(Failure("ambiguous_oauth_callback"));
        }
    }
    let state = values
        .remove("state")
        .filter(|s| s.strip_prefix("read.").is_some_and(browser))
        .ok_or_else(invalid)?;
    let code = values.remove("code");
    let error = values.remove("error");
    if code
        .as_ref()
        .is_some_and(|s| s.len() > 4096 || s.chars().any(char::is_control))
        || error
            .as_ref()
            .is_some_and(|s| s.len() > 100 || s.chars().any(char::is_control))
    {
        return Err(invalid());
    }
    Ok(Callback { state, code, error })
}
pub fn browser_cookie(headers: &axum::http::HeaderMap) -> Result<String> {
    let mut result = None;
    for raw in headers.get_all("cookie") {
        let raw = raw
            .to_str()
            .map_err(|_| Failure("invalid_oauth_browser_binding"))?;
        for pair in raw.split(';') {
            if let Some(("gmail_oauth_browser", value)) = pair.trim().split_once('=') {
                if result.is_some() || !browser(value) {
                    return Err(Failure("invalid_oauth_browser_binding"));
                }
                result = Some(value.to_owned());
            }
        }
    }
    result.ok_or(Failure("invalid_oauth_browser_binding"))
}
impl<P: Provider> Service<'_, P> {
    pub fn ttl(&self) -> i64 {
        self.settings.ttl
    }
    fn store(&self) -> Result<&TokenStore> {
        self.settings
            .store
            .as_ref()
            .ok_or(Failure("oauth_encryption_not_configured"))
    }
    pub async fn start(
        &self,
        c: &mut PgConnection,
        input: Value,
        existing: Option<Uuid>,
        browser_secret: &str,
    ) -> Result<Value> {
        let input = contract::normalize(contract::Kind::Connect, input)?;
        if !browser(browser_secret) {
            return Err(Failure("invalid_oauth_browser_binding"));
        }
        let body = input["read_body"] == true;
        if body && !self.settings.body {
            return Err(Failure("gmail_body_access_review_required"));
        }
        let store = self.store()?;
        let mut tx = begin(c).await?;
        let mut account = if let Some(id) = existing {
            Some(account_in(&mut tx, id, true).await?)
        } else if let Some(email) = input["expected_email"].as_str() {
            sqlx::query_scalar(&format!(
                "{PUBLIC_ACCOUNT} WHERE provider='gmail' AND account_email=$1 FOR UPDATE"
            ))
            .bind(automated_apply_domain::text::folded(email))
            .fetch_optional(&mut *tx)
            .await
            .map_err(db)?
        } else {
            None
        };
        let id = account
            .as_ref()
            .and_then(|v| v["id"].as_str())
            .and_then(|s| s.parse::<Uuid>().ok())
            .unwrap_or_else(Uuid::new_v4);
        let expected = if let Some(account) = &account {
            text(account, "account_email")?.to_owned()
        } else if let Some(email) = input["expected_email"].as_str() {
            automated_apply_domain::text::folded(email)
        } else {
            format!("pending:{}", id.simple())
        };
        if let Some(input) = input["expected_email"].as_str() {
            if automated_apply_domain::text::folded(input) != expected {
                return Err(Failure("expected_account_mismatch"));
            }
        }
        if !expected.starts_with("pending:") && !self.settings.allows(&expected) {
            return Err(Failure("gmail_account_not_authorized"));
        }
        if let Some(current) = &account {
            if current["status"] != "disconnected"
                && current["status"] != "reauthorization_required"
                && !(body
                    && current["status"] == "connected"
                    && scopes(current)? == crate::google_oauth::scopes(GrantMode::Metadata))
            {
                return Err(Failure("disconnect_before_reconnecting"));
            }
        }
        if account.is_none() {
            let saved:Option<Value>=sqlx::query_scalar("INSERT INTO gmail_read_accounts(id,provider,google_subject,account_email,status,token_generation,granted_scopes,connected_at) VALUES($1,'gmail','',$2,'disconnected',1,'[]',clock_timestamp()) RETURNING jsonb_build_object('id',id,'google_subject',google_subject,'account_email',account_email,'status',status,'token_generation',token_generation)").bind(id).bind(&expected).fetch_optional(&mut *tx).await.map_err(db)?;
            account = Some(saved.ok_or(Failure("gmail_read_write_ack_failed"))?);
        }
        let current = account.as_ref().unwrap();
        let next = generation(current)?.checked_add(1).ok_or_else(invalid)?;
        let changed:Option<i64>=sqlx::query_scalar("UPDATE gmail_read_accounts SET token_generation=$2,updated_at=clock_timestamp() WHERE id=$1 AND token_generation=$3 RETURNING token_generation").bind(id).bind(next).bind(generation(current)?).fetch_optional(&mut *tx).await.map_err(db)?;
        if changed != Some(next) {
            return Err(Failure("gmail_read_write_ack_failed"));
        }
        let state = format!("read.{}", crate::mailboxes::browser_nonce());
        let verifier = crate::mailboxes::browser_nonce();
        let hash = digest(&state);
        let mode = if body { "read_body" } else { "read_metadata" };
        let url = self.provider.authorization_url(
            &state,
            &verifier,
            if expected.starts_with("pending:") {
                None
            } else {
                Some(&expected)
            },
            if body {
                GrantMode::Read
            } else {
                GrantMode::Metadata
            },
        )?;
        let ack:Option<String>=sqlx::query_scalar("INSERT INTO gmail_read_oauth_states(state_hash,provider,actor_id,browser_hash,expected_email,connection_generation,encrypted_verifier,encryption_key_id,redirect_uri,expires_at,created_at,authorization_mode,expected_subject) VALUES($1,'gmail','owner',$2,$3,$4,$5,$6,$7,clock_timestamp()+($8::double precision*interval '1 second'),clock_timestamp(),$9,$10) RETURNING state_hash").bind(&hash).bind(digest(browser_secret)).bind(&expected).bind(next).bind(store.encrypt(&json!(verifier),&hash)?).bind(store.active_id()).bind(self.provider.redirect_uri()).bind(self.settings.ttl as f64).bind(mode).bind(current["google_subject"].as_str().filter(|s|!s.is_empty())).fetch_optional(&mut *tx).await.map_err(db)?;
        if ack.as_deref() != Some(hash.as_str()) {
            return Err(Failure("gmail_read_write_ack_failed"));
        }
        commit(tx).await?;
        Ok(json!({"authorization_url":url,"expires_in":self.settings.ttl}))
    }
    pub async fn callback(
        &self,
        c: &mut PgConnection,
        state: &str,
        browser_secret: &str,
        uri: &str,
        code: Option<&str>,
        error: Option<&str>,
    ) -> Result<Value> {
        if !state.strip_prefix("read.").is_some_and(browser)
            || !browser(browser_secret)
            || uri != self.provider.redirect_uri()
        {
            return Err(Failure("invalid_oauth_state_or_redirect"));
        }
        let store = self.store()?;
        let hash = digest(state);
        let mut tx = begin(c).await?;
        let intent:Option<Value>=sqlx::query_scalar("UPDATE gmail_read_oauth_states SET consumed_at=clock_timestamp() WHERE state_hash=$1 AND browser_hash=$2 AND provider='gmail' AND actor_id='owner' AND consumed_at IS NULL AND expires_at>clock_timestamp() AND redirect_uri=$3 RETURNING to_jsonb(gmail_read_oauth_states)").bind(&hash).bind(digest(browser_secret)).bind(uri).fetch_optional(&mut *tx).await.map_err(db)?;
        let intent = intent.ok_or(Failure("invalid_expired_or_replayed_state"))?;
        let verifier = store
            .decrypt(text(&intent, "encrypted_verifier")?, &hash)?
            .as_str()
            .ok_or_else(invalid)?
            .to_owned();
        let cleared:Option<String>=sqlx::query_scalar("UPDATE gmail_read_oauth_states SET encrypted_verifier=NULL WHERE state_hash=$1 AND consumed_at IS NOT NULL RETURNING state_hash").bind(&hash).fetch_optional(&mut *tx).await.map_err(db)?;
        if cleared.as_deref() != Some(hash.as_str()) {
            return Err(Failure("gmail_read_write_ack_failed"));
        }
        commit(tx).await?;
        if error.is_some() {
            return Err(Failure("consent_denied"));
        }
        let code = code
            .filter(|s| !s.is_empty() && s.len() <= 4096 && !s.chars().any(char::is_control))
            .ok_or(Failure("authorization_code_required"))?;
        let body = match intent["authorization_mode"].as_str() {
            Some("read_body") => true,
            Some("read_metadata") => false,
            _ => return Err(invalid()),
        };
        if body && !self.settings.body {
            return Err(Failure("gmail_body_access_review_required"));
        }
        let tokens = self.provider.exchange(code, &verifier).await?;
        let refresh = tokens.refresh().ok_or(Failure("refresh_token_required"))?;
        let expected_scopes = crate::google_oauth::scopes(if body {
            GrantMode::Read
        } else {
            GrantMode::Metadata
        });
        let granted = tokens
            .granted_scopes()?
            .ok_or(Failure("missing_granted_scopes"))?;
        if granted != expected_scopes {
            return Err(Failure("unexpected_or_insufficient_scopes"));
        }
        let (subject, email) = self.provider.identity(tokens.access()).await?;
        if subject.is_empty() || !self.settings.allows(&email) {
            return Err(Failure("gmail_account_not_authorized"));
        }
        let expected = text(&intent, "expected_email")?;
        if !expected.starts_with("pending:") && email != expected
            || intent["expected_subject"]
                .as_str()
                .is_some_and(|s| s != subject)
        {
            return Err(Failure("wrong_google_account"));
        }
        let mut tx = begin(c).await?;
        let account: Option<Value> = sqlx::query_scalar(&format!(
            "{PUBLIC_ACCOUNT} WHERE provider='gmail' AND account_email=$1 FOR UPDATE"
        ))
        .bind(expected)
        .fetch_optional(&mut *tx)
        .await
        .map_err(db)?;
        let account = account.ok_or(Failure("connection_intent_superseded"))?;
        if account["token_generation"] != intent["connection_generation"]
            || account["status"] == "connected" && !body
        {
            return Err(Failure("connection_intent_superseded"));
        }
        let id = text(&account, "id")?
            .parse::<Uuid>()
            .map_err(|_| invalid())?;
        let outreach:Option<Value>=sqlx::query_scalar("SELECT jsonb_build_object('google_subject',value->'google_subject','account_email',value->'account_email') FROM owner_preferences WHERE key='gmail_drafts:account' FOR SHARE").fetch_optional(&mut *tx).await.map_err(db)?;
        if outreach.is_some_and(|v| v["google_subject"] == subject || v["account_email"] == email) {
            return Err(Failure("gmail_separate_outreach_account_required"));
        }
        let duplicate:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM gmail_read_accounts WHERE provider='gmail' AND id!=$1 AND (google_subject=$2 OR account_email=$3))").bind(id).bind(&subject).bind(&email).fetch_one(&mut *tx).await.map_err(db)?;
        if duplicate {
            return Err(Failure("gmail_account_already_connected"));
        }
        let next = generation(&account)?.checked_add(1).ok_or_else(invalid)?;
        let saved:Option<i64>=sqlx::query_scalar("UPDATE gmail_read_accounts SET google_subject=$2,account_email=$3,encrypted_refresh_token=$4,encrypted_access_token=$5,encryption_key_id=$6,granted_scopes=$7,status='connected',connected_at=clock_timestamp(),last_verified_at=clock_timestamp(),token_expires_at=clock_timestamp()+($8::double precision*interval '1 second'),disconnected_at=NULL,token_generation=$9,updated_at=clock_timestamp() WHERE id=$1 AND token_generation=$10 RETURNING token_generation").bind(id).bind(&subject).bind(&email).bind(store.encrypt(&json!(refresh),&format!("{id}:refresh"))?).bind(store.encrypt(&json!(tokens.access()),&format!("{id}:access"))?).bind(store.active_id()).bind(json!(granted)).bind(tokens.expires_in() as f64).bind(next).bind(generation(&account)?).fetch_optional(&mut *tx).await.map_err(db)?;
        if saved != Some(next) {
            return Err(Failure("gmail_read_write_ack_failed"));
        }
        let status = status_in(&mut tx, id, self.settings).await?;
        commit(tx).await?;
        Ok(status)
    }
}
