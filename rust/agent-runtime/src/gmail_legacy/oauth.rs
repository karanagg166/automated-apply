//! Original unprefixed primary OAuth/table/purposes. No send grant or unconsumed exchange replay.
use super::*;
use crate::{account_tokens::TokenStore, gmail_accounts::oauth::Provider};
use chrono::{DateTime, Duration, Utc};
use sha2::{Digest, Sha256};
use sqlx::{Postgres, Transaction};
pub struct Service<'a, P> {
    pub settings: &'a Settings,
    pub provider: &'a P,
}
pub(super) fn digest(value: &str) -> String {
    format!("{:x}", Sha256::digest(value.as_bytes()))
}
pub(super) fn text<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    value[key]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or_else(invalid)
}
pub(super) fn number(value: &Value) -> Result<i64> {
    value.as_i64().filter(|n| *n > 0).ok_or_else(invalid)
}
pub(super) fn at(value: &Value) -> Result<DateTime<Utc>> {
    crate::gmail_history::contract::timestamp(value)
        .map(|v| v.with_timezone(&Utc))
        .ok_or_else(invalid)
}
pub(super) fn now() -> DateTime<Utc> {
    DateTime::from_timestamp_micros(Utc::now().timestamp_micros())
        .expect("current UTC microseconds")
}
fn nonce(value: &str) -> bool {
    (32..=128).contains(&value.len())
        && value
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, b'_' | b'-'))
}
pub(super) async fn begin(c: &mut PgConnection) -> Result<Transaction<'_, Postgres>> {
    begin_mode(c, true).await
}
pub(super) async fn begin_local(c: &mut PgConnection) -> Result<Transaction<'_, Postgres>> {
    begin_mode(c, false).await
}
async fn begin_mode(
    c: &mut PgConnection,
    require_oauth: bool,
) -> Result<Transaction<'_, Postgres>> {
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
    let ready:bool=sqlx::query_scalar("SELECT to_regclass('connected_accounts') IS NOT NULL AND (NOT $1::boolean OR to_regclass('oauth_states') IS NOT NULL)").bind(require_oauth).fetch_one(&mut *tx).await.map_err(db)?;
    if !ready {
        return Err(Failure("gmail_legacy_schema_update_required"));
    }
    Ok(tx)
}
pub(super) async fn commit(tx: Transaction<'_, Postgres>) -> Result<()> {
    tx.commit()
        .await
        .map_err(|_| Failure("gmail_legacy_commit_outcome_unknown"))
}
pub(super) async fn get(tx: &mut Transaction<'_, Postgres>, key: &str) -> Result<Option<Value>> {
    sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(key)
        .fetch_optional(&mut **tx)
        .await
        .map_err(db)
}
pub(super) async fn put(
    tx: &mut Transaction<'_, Postgres>,
    key: &str,
    value: &Value,
) -> Result<()> {
    let ack:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES($1,$2,clock_timestamp(),clock_timestamp()) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=clock_timestamp() RETURNING value").bind(key).bind(value).fetch_optional(&mut **tx).await.map_err(db)?;
    if ack.as_ref() != Some(value) {
        return Err(Failure("gmail_legacy_write_ack_failed"));
    }
    Ok(())
}
pub(super) async fn account(tx: &mut Transaction<'_, Postgres>) -> Result<Option<Value>> {
    let rows:Vec<Value>=sqlx::query_scalar("SELECT to_jsonb(a) FROM connected_accounts a WHERE provider='gmail' ORDER BY id LIMIT 2 FOR UPDATE").fetch_all(&mut **tx).await.map_err(db)?;
    if rows.len() > 1 {
        return Err(Failure("gmail_legacy_identity_requires_review"));
    }
    Ok(rows.into_iter().next())
}
pub(super) fn id(value: &Value) -> Result<Uuid> {
    text(value, "id")?.parse().map_err(|_| invalid())
}
pub(super) fn granted(value: &Value) -> Result<BTreeSet<String>> {
    value["granted_scopes"]
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .map(|s| s.as_str().map(str::to_owned).ok_or_else(invalid))
        .collect()
}
pub(super) fn valid(value: &Value, settings: &Settings) -> Result<BTreeSet<String>> {
    if value["status"] != "connected" {
        return Err(Failure("gmail_not_connected"));
    }
    if !settings.allows(text(value, "account_email")?) {
        return Err(Failure("gmail_account_not_authorized"));
    }
    let granted = granted(value)?;
    if ![GrantMode::Metadata, GrantMode::Read, GrantMode::Compose]
        .into_iter()
        .any(|mode| granted == google_oauth::scopes(mode))
    {
        return Err(Failure("unexpected_or_insufficient_scopes"));
    }
    text(value, "google_subject")?;
    number(&value["token_generation"])?;
    Ok(granted)
}
pub(super) fn store(settings: &Settings) -> Result<&TokenStore> {
    settings
        .store
        .as_ref()
        .ok_or(Failure("oauth_encryption_not_configured"))
}
pub(super) async fn save(
    tx: &mut Transaction<'_, Postgres>,
    old_generation: i64,
    value: &Value,
) -> Result<Value> {
    let ack:Option<Value>=sqlx::query_scalar("UPDATE connected_accounts SET google_subject=$1::jsonb->>'google_subject',account_email=$1::jsonb->>'account_email',encrypted_refresh_token=$1::jsonb->>'encrypted_refresh_token',encrypted_access_token=$1::jsonb->>'encrypted_access_token',encryption_key_id=$1::jsonb->>'encryption_key_id',granted_scopes=$1::jsonb->'granted_scopes',status=$1::jsonb->>'status',token_generation=($1::jsonb->>'token_generation')::integer,token_expires_at=($1::jsonb->>'token_expires_at')::timestamptz,connected_at=($1::jsonb->>'connected_at')::timestamptz,last_verified_at=($1::jsonb->>'last_verified_at')::timestamptz,last_refresh_at=($1::jsonb->>'last_refresh_at')::timestamptz,disconnected_at=($1::jsonb->>'disconnected_at')::timestamptz,updated_at=clock_timestamp() WHERE id=$2 AND provider='gmail' AND token_generation=$3 RETURNING to_jsonb(connected_accounts)").bind(value).bind(id(value)?).bind(old_generation).fetch_optional(&mut **tx).await.map_err(db)?;
    let ack = ack.ok_or(Failure("gmail_legacy_write_ack_failed"))?;
    for key in [
        "id",
        "provider",
        "google_subject",
        "account_email",
        "encrypted_refresh_token",
        "encrypted_access_token",
        "encryption_key_id",
        "granted_scopes",
        "status",
        "token_generation",
        "token_expires_at",
        "connected_at",
        "last_verified_at",
        "last_refresh_at",
        "disconnected_at",
    ] {
        let equal = if key.ends_with("_at") && !value[key].is_null() {
            at(&ack[key])? == at(&value[key])?
        } else {
            ack[key] == value[key]
        };
        if !equal {
            return Err(Failure("gmail_legacy_write_ack_failed"));
        }
    }
    Ok(ack)
}
impl<P: Provider> Service<'_, P> {
    pub async fn start(&self, c: &mut PgConnection, input: Value, browser: &str) -> Result<Value> {
        let input = connect(input)?;
        if input["authorization_mode"] == "send" {
            return Err(Failure(SEND_BLOCKER));
        }
        if !nonce(browser) {
            return Err(Failure("invalid_oauth_browser_binding"));
        }
        let expected = self
            .settings
            .legacy_expected_email
            .as_deref()
            .or_else(|| input["expected_email"].as_str())
            .ok_or(Failure("expected_secondary_email_required"))?;
        let expected = automated_apply_domain::text::folded(expected);
        if input["expected_email"]
            .as_str()
            .is_some_and(|email| automated_apply_domain::text::folded(email) != expected)
        {
            return Err(Failure("expected_account_mismatch"));
        }
        if !self.settings.allows(&expected) {
            return Err(Failure("gmail_account_not_authorized"));
        }
        let store = store(self.settings)?;
        let mode = if input["authorization_mode"] == "compose" {
            GrantMode::Compose
        } else {
            GrantMode::Metadata
        };
        let mut tx = begin(c).await?;
        let current = account(&mut tx).await?;
        if matches!(mode, GrantMode::Compose) {
            let old = current
                .as_ref()
                .ok_or(Failure("metadata_connection_required_before_upgrade"))?;
            if !matches!(
                old["status"].as_str(),
                Some("connected" | "reauthorization_required")
            ) || old["google_subject"].as_str().is_none_or(str::is_empty)
            {
                return Err(Failure("metadata_connection_required_before_upgrade"));
            }
            if old["account_email"] != expected {
                return Err(Failure("wrong_google_account"));
            }
        } else if current
            .as_ref()
            .is_some_and(|value| value["status"] != "disconnected")
        {
            return Err(Failure("disconnect_before_reconnecting"));
        }
        let current = if let Some(value) = current {
            value
        } else {
            let id = Uuid::new_v4();
            let value:Option<Value>=sqlx::query_scalar("INSERT INTO connected_accounts(id,provider,google_subject,account_email,status,token_generation,granted_scopes,connected_at,created_at,updated_at) VALUES($1,'gmail','',$2,'disconnected',1,'[]',clock_timestamp(),clock_timestamp(),clock_timestamp()) RETURNING to_jsonb(connected_accounts)").bind(id).bind(&expected).fetch_optional(&mut *tx).await.map_err(db)?;
            let value = value.ok_or(Failure("gmail_legacy_write_ack_failed"))?;
            if value["id"] != id.to_string()
                || value["account_email"] != expected
                || value["status"] != "disconnected"
                || value["token_generation"] != 1
            {
                return Err(Failure("gmail_legacy_write_ack_failed"));
            }
            value
        };
        let mut next = current.clone();
        next["token_generation"] = json!(
            number(&current["token_generation"])?
                .checked_add(1)
                .ok_or_else(invalid)?
        );
        save(&mut tx, number(&current["token_generation"])?, &next).await?;
        let state = crate::mailboxes::browser_nonce();
        let verifier = crate::mailboxes::browser_nonce();
        let hash = digest(&state);
        let url = self
            .provider
            .authorization_url(&state, &verifier, Some(&expected), mode)?;
        let authorization = if matches!(mode, GrantMode::Compose) {
            "compose"
        } else {
            "metadata"
        };
        let encrypted = store.encrypt(&json!(verifier), &hash)?;
        let expected_subject = if matches!(mode, GrantMode::Compose) {
            current["google_subject"].as_str()
        } else {
            None
        };
        let ack=sqlx::query_scalar::<_,Value>("INSERT INTO oauth_states(state_hash,provider,actor_id,browser_hash,expected_email,connection_generation,encrypted_verifier,encryption_key_id,redirect_uri,expires_at,created_at,authorization_mode,expected_subject) VALUES($1,'gmail','owner',$2,$3,$4,$5,$6,$7,clock_timestamp()+($8::double precision*interval '1 second'),clock_timestamp(),$9,$10) RETURNING to_jsonb(oauth_states)").bind(&hash).bind(digest(browser)).bind(&expected).bind(number(&next["token_generation"])?).bind(&encrypted).bind(store.active_id()).bind(self.provider.redirect_uri()).bind(self.settings.ttl as f64).bind(authorization).bind(expected_subject).fetch_optional(&mut *tx).await.map_err(|e|if matches!(mode,GrantMode::Compose)&&e.as_database_error().is_some_and(|e|e.code().as_deref()==Some("23514")&&e.constraint()==Some("oauth_states_authorization_mode_check")){Failure("gmail_compose_schema_update_required")}else{db(e)})?;
        let ack = ack.ok_or(Failure("gmail_legacy_write_ack_failed"))?;
        let expected_fields = json!({"state_hash":hash,"provider":"gmail","actor_id":"owner","browser_hash":digest(browser),"expected_email":expected,"connection_generation":next["token_generation"],"encrypted_verifier":encrypted,"encryption_key_id":store.active_id(),"redirect_uri":self.provider.redirect_uri(),"authorization_mode":authorization,"expected_subject":expected_subject});
        if expected_fields
            .as_object()
            .ok_or_else(invalid)?
            .iter()
            .any(|(key, value)| &ack[key] != value)
            || !ack["consumed_at"].is_null()
            || at(&ack["expires_at"])? <= now()
        {
            return Err(Failure("gmail_legacy_write_ack_failed"));
        }
        commit(tx).await?;
        Ok(json!({"authorization_url":url,"expires_in":self.settings.ttl}))
    }
    pub async fn callback(
        &self,
        c: &mut PgConnection,
        state: &str,
        browser: &str,
        uri: &str,
        code: Option<&str>,
        error: Option<&str>,
    ) -> Result<Value> {
        if !nonce(state) || !nonce(browser) || uri != self.provider.redirect_uri() {
            return Err(Failure("invalid_oauth_state_or_redirect"));
        }
        let store = store(self.settings)?;
        let hash = digest(state);
        let mut tx = begin(c).await?;
        let intent:Option<Value>=sqlx::query_scalar("UPDATE oauth_states SET consumed_at=clock_timestamp() WHERE state_hash=$1 AND browser_hash=$2 AND actor_id='owner' AND provider='gmail' AND consumed_at IS NULL AND expires_at>clock_timestamp() AND redirect_uri=$3 RETURNING to_jsonb(oauth_states)").bind(&hash).bind(digest(browser)).bind(uri).fetch_optional(&mut *tx).await.map_err(db)?;
        let intent = intent.ok_or(Failure("invalid_expired_or_replayed_state"))?;
        let verifier = store
            .decrypt(text(&intent, "encrypted_verifier")?, &hash)?
            .as_str()
            .ok_or_else(invalid)?
            .to_owned();
        let cleared:Option<Value>=sqlx::query_scalar("UPDATE oauth_states SET encrypted_verifier=NULL WHERE state_hash=$1 AND consumed_at IS NOT NULL RETURNING to_jsonb(oauth_states)").bind(&hash).fetch_optional(&mut *tx).await.map_err(db)?;
        let cleared = cleared.ok_or(Failure("gmail_legacy_write_ack_failed"))?;
        if cleared["state_hash"] != hash
            || !cleared["encrypted_verifier"].is_null()
            || cleared["consumed_at"].is_null()
            || [
                "browser_hash",
                "expected_email",
                "connection_generation",
                "authorization_mode",
                "expected_subject",
                "redirect_uri",
                "provider",
                "actor_id",
            ]
            .iter()
            .any(|key| cleared[*key] != intent[*key])
        {
            return Err(Failure("gmail_legacy_write_ack_failed"));
        }
        let current = account(&mut tx).await?;
        let active = current.as_ref().is_some_and(|value| {
            value["token_generation"] == intent["connection_generation"]
                && if intent["authorization_mode"] == "metadata" {
                    value["status"] != "connected"
                } else {
                    value["status"] != "disconnected"
                        && value["google_subject"] == intent["expected_subject"]
                        && value["account_email"] == intent["expected_email"]
                }
        });
        commit(tx).await?;
        if !active {
            return Err(Failure("connection_intent_superseded"));
        }
        if error.is_some() {
            return Err(Failure("consent_denied"));
        }
        let code = code
            .filter(|s| !s.is_empty())
            .ok_or(Failure("authorization_code_required"))?;
        let mode = match intent["authorization_mode"].as_str() {
            Some("metadata") => GrantMode::Metadata,
            Some("compose") => GrantMode::Compose,
            Some("send") => return Err(Failure(SEND_BLOCKER)),
            _ => return Err(Failure("unexpected_or_insufficient_scopes")),
        };
        let tokens = self.provider.exchange(code, &verifier).await?;
        let refresh = tokens.refresh().ok_or(Failure("refresh_token_required"))?;
        if tokens.granted_scopes()?.as_ref() != Some(&google_oauth::scopes(mode)) {
            return Err(Failure("unexpected_or_insufficient_scopes"));
        }
        let (subject, email) = self.provider.identity(tokens.access()).await?;
        if subject.is_empty() || !self.settings.allows(&email) {
            return Err(Failure("gmail_account_not_authorized"));
        }
        if email != text(&intent, "expected_email")?
            || intent["expected_subject"]
                .as_str()
                .is_some_and(|expected| expected != subject)
        {
            return Err(Failure("wrong_google_account"));
        }
        let mut tx = begin(c).await?;
        let mut value = account(&mut tx)
            .await?
            .ok_or(Failure("connection_intent_superseded"))?;
        let generation = number(&value["token_generation"])?;
        if value["token_generation"] != intent["connection_generation"]
            || matches!(mode, GrantMode::Metadata) && value["status"] == "connected"
            || matches!(mode, GrantMode::Compose)
                && (value["status"] == "disconnected"
                    || value["google_subject"] != subject
                    || value["account_email"] != email)
        {
            return Err(Failure("connection_intent_superseded"));
        }
        let id = id(&value)?;
        let now = now();
        value["google_subject"] = json!(subject);
        value["account_email"] = json!(email);
        value["granted_scopes"] = json!(google_oauth::scopes(mode));
        value["status"] = json!("connected");
        value["token_generation"] = json!(generation.checked_add(1).ok_or_else(invalid)?);
        value["encrypted_refresh_token"] =
            json!(store.encrypt(&json!(refresh), &format!("{id}:refresh"))?);
        value["encrypted_access_token"] =
            json!(store.encrypt(&json!(tokens.access()), &format!("{id}:access"))?);
        value["encryption_key_id"] = json!(store.active_id());
        value["token_expires_at"] = json!(now + Duration::seconds(tokens.expires_in()));
        value["connected_at"] = json!(now);
        value["last_verified_at"] = json!(now);
        value["disconnected_at"] = Value::Null;
        let value = save(&mut tx, generation, &value).await?;
        let result = projection(Some(&value), true, true)?;
        commit(tx).await?;
        Ok(result)
    }
}
