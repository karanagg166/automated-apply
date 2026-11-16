//! Independent compose-only account; durable consumed OAuth and non-replayed refresh intents.
use super::*;
use crate::{
    gmail_accounts::oauth::Provider,
    google_oauth::{GrantMode, TokenResponse},
};
use chrono::{DateTime, Duration, Utc};
use sha2::{Digest, Sha256};
pub struct Service<'a, P> {
    pub settings: &'a Settings,
    pub provider: &'a P,
}
fn digest(value: &str) -> String {
    format!("{:x}", Sha256::digest(value.as_bytes()))
}
fn nonce(value: &str) -> bool {
    (32..=128).contains(&value.len())
        && value
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, b'_' | b'-'))
}
fn number(value: &Value) -> Result<i64> {
    value.as_i64().filter(|n| *n > 0).ok_or_else(invalid)
}
fn text<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    value[key]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or_else(invalid)
}
fn at(value: &Value) -> Result<DateTime<Utc>> {
    crate::gmail_history::contract::timestamp(value)
        .map(|v| v.with_timezone(&Utc))
        .ok_or_else(invalid)
}
fn public(value: &Value, settings: &Settings) -> Value {
    let mut result = json!({"workflow":"drafts_only","drafts_enabled":settings.drafts,"sending_enabled":false,"permissions":{"drafts":false,"send":false,"read_mail":false},"live_verified":false,"verification_basis":"saved_record_not_current_probe"});
    for key in ["status", "account_email", "google_subject", "generation"] {
        if let Some(value) = value.get(key) {
            result[key] = value.clone();
        }
    }
    result["permissions"]["drafts"] = json!(settings.drafts && valid(value, settings).is_ok());
    result
}
fn valid(value: &Value, settings: &Settings) -> Result<()> {
    if value["status"] != "connected" {
        return Err(Failure("gmail_drafts_account_not_connected"));
    }
    number(&value["generation"])?;
    if !settings.allows(text(value, "account_email")?) {
        return Err(Failure("gmail_account_not_authorized"));
    }
    text(value, "google_subject")?;
    let scopes = value["scopes"]
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .map(|v| v.as_str().map(str::to_owned).ok_or_else(invalid))
        .collect::<Result<std::collections::BTreeSet<_>>>()?;
    if scopes != crate::google_oauth::scopes(GrantMode::Compose) {
        return Err(Failure("unexpected_or_insufficient_scopes"));
    }
    Ok(())
}
async fn separate(tx: &mut Transaction<'_, Postgres>, subject: &str, email: &str) -> Result<()> {
    if !gmail_accounts::schema(tx).await? {
        return Err(Failure("gmail_readonly_schema_update_required"));
    }
    let collision:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM gmail_read_accounts WHERE google_subject=$1 OR lower(account_email)=lower($2)) OR EXISTS(SELECT 1 FROM owner_preferences WHERE key IN ('gm54_account:1','gm54_account:2') AND (value->>'google_subject'=$1 OR lower(value->>'account_email')=lower($2)))").bind(subject).bind(email).fetch_one(&mut **tx).await.map_err(db)?;
    if collision {
        return Err(Failure("gmail_separate_outreach_account_required"));
    }
    Ok(())
}
fn secret(settings: &Settings, value: &Value, key: &str) -> Result<String> {
    store(settings)?
        .decrypt(text(value, key)?, &format!("{ACCOUNT}:{key}"))?
        .as_str()
        .filter(|s| !s.is_empty() && s.len() <= 16384)
        .map(str::to_owned)
        .ok_or(Failure("token_decryption_failed"))
}
impl<P: Provider> Service<'_, P> {
    pub async fn start(&self, c: &mut PgConnection, input: Value, browser: &str) -> Result<Value> {
        let input = contract::normalize(contract::Kind::Consent, input)?;
        if input["account_consent"] != true {
            return Err(Failure("gmail_account_consent_required"));
        }
        if input["read_body"] == true {
            return Err(Failure("outreach_drafts_only"));
        }
        if !nonce(browser) {
            return Err(Failure("invalid_oauth_browser_binding"));
        }
        let store = store(self.settings)?;
        let mut tx = begin(c).await?;
        if !gmail_accounts::schema(&mut tx).await? {
            return Err(Failure("gmail_readonly_schema_update_required"));
        }
        let old = get(&mut tx, ACCOUNT)
            .await?
            .unwrap_or(json!({"generation":0}));
        if old["status"] == "connected" {
            return Err(Failure("disconnect_before_reconnecting"));
        }
        let generation = old["generation"]
            .as_i64()
            .and_then(|n| n.checked_add(1))
            .filter(|n| *n > 0)
            .ok_or_else(invalid)?;
        let state = format!("draft.{}", crate::mailboxes::browser_nonce());
        let verifier = crate::mailboxes::browser_nonce();
        let hash = digest(&state);
        let url = self
            .provider
            .authorization_url(&state, &verifier, None, GrantMode::Compose)?;
        let intent = json!({"state_hash":hash,"browser_hash":digest(browser),"generation":generation,"consumed":false,"verifier":store.encrypt(&json!(verifier),&hash)?,"expires_at":Utc::now()+Duration::seconds(self.settings.ttl)});
        put(
            &mut tx,
            ACCOUNT,
            &json!({"status":"disconnected","generation":generation}),
        )
        .await?;
        put(
            &mut tx,
            &format!("gmail_draft_oauth:{}", &hash[..32]),
            &intent,
        )
        .await?;
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
        if !state.strip_prefix("draft.").is_some_and(nonce)
            || !nonce(browser)
            || uri != self.provider.redirect_uri()
        {
            return Err(Failure("invalid_oauth_state_or_redirect"));
        }
        let store = store(self.settings)?;
        let hash = digest(state);
        let key = format!("gmail_draft_oauth:{}", &hash[..32]);
        let mut tx = begin(c).await?;
        let mut intent = get(&mut tx, &key)
            .await?
            .ok_or(Failure("invalid_expired_or_replayed_state"))?;
        let account = get(&mut tx, ACCOUNT)
            .await?
            .ok_or(Failure("invalid_expired_or_replayed_state"))?;
        if intent["state_hash"] != hash
            || intent["browser_hash"] != digest(browser)
            || intent["consumed"] != false
            || at(&intent["expires_at"])? <= Utc::now()
            || account["generation"] != intent["generation"]
            || account["status"] != "disconnected"
        {
            return Err(Failure("invalid_expired_or_replayed_state"));
        }
        let generation = number(&intent["generation"])?;
        let verifier = store
            .decrypt(text(&intent, "verifier")?, &hash)?
            .as_str()
            .ok_or_else(invalid)?
            .to_owned();
        intent
            .as_object_mut()
            .ok_or_else(invalid)?
            .remove("verifier");
        intent["consumed"] = json!(true);
        intent["consumed_at"] = json!(Utc::now());
        put(&mut tx, &key, &intent).await?;
        commit(tx).await?;
        if error.is_some() || code.is_none_or(str::is_empty) {
            return Err(Failure("consent_denied"));
        }
        let tokens = self.provider.exchange(code.unwrap(), &verifier).await?;
        if tokens.refresh().is_none()
            || tokens.granted_scopes()?.as_ref()
                != Some(&crate::google_oauth::scopes(GrantMode::Compose))
        {
            return Err(Failure("unexpected_or_insufficient_scopes"));
        }
        let (subject, email) = self.provider.identity(tokens.access()).await?;
        if subject.is_empty() || !self.settings.allows(&email) {
            return Err(Failure("gmail_account_not_authorized"));
        }
        let email =
            crate::profile_contract::email(&email).map_err(|_| Failure("wrong_google_account"))?;
        let mut tx = begin(c).await?;
        let current = get(&mut tx, ACCOUNT)
            .await?
            .ok_or(Failure("connection_intent_superseded"))?;
        if current["generation"] != json!(generation) || current["status"] != "disconnected" {
            return Err(Failure("connection_intent_superseded"));
        }
        separate(&mut tx, &subject, &email).await?;
        let next = generation.checked_add(1).ok_or_else(invalid)?;
        let account = json!({"status":"connected","generation":next,"account_email":email,"google_subject":subject,"scopes":crate::google_oauth::scopes(GrantMode::Compose),"access":store.encrypt(&json!(tokens.access()),&format!("{ACCOUNT}:access"))?,"refresh":store.encrypt(&json!(tokens.refresh().unwrap()),&format!("{ACCOUNT}:refresh"))?,"expires_at":Utc::now()+Duration::seconds(tokens.expires_in())});
        put(&mut tx, ACCOUNT, &account).await?;
        let result = public(&account, self.settings);
        commit(tx).await?;
        Ok(result)
    }
    pub async fn disconnect(&self, c: &mut PgConnection) -> Result<Value> {
        disconnect(c).await
    }
}
pub async fn disconnect(c: &mut PgConnection) -> Result<Value> {
    let mut tx = begin(c).await?;
    if let Some(old) = get(&mut tx, ACCOUNT).await? {
        let next = number(&old["generation"])?
            .checked_add(1)
            .ok_or_else(invalid)?;
        put(
            &mut tx,
            ACCOUNT,
            &json!({"status":"disconnected","generation":next}),
        )
        .await?;
    }
    commit(tx).await?;
    Ok(json!({"status":"disconnected","revoke_in_google_settings":true,"sending_enabled":false}))
}
/// Contains a credential; deliberately not Debug/Clone/Serialize.
pub struct Access {
    token: String,
    pub(crate) account: Value,
}
impl Access {
    pub fn token(&self) -> &str {
        &self.token
    }
    pub fn generation(&self) -> Result<i64> {
        number(&self.account["generation"])
    }
}
impl<P: Provider> Service<'_, P> {
    pub async fn access(&self, c: &mut PgConnection) -> Result<Access> {
        let mut tx = begin(c).await?;
        let mut account = get(&mut tx, ACCOUNT)
            .await?
            .ok_or(Failure("gmail_drafts_account_not_connected"))?;
        valid(&account, self.settings)?;
        separate(
            &mut tx,
            text(&account, "google_subject")?,
            text(&account, "account_email")?,
        )
        .await?;
        let generation = number(&account["generation"])?;
        let now = Utc::now();
        if let Some(key) = account["refresh_intent"].as_str() {
            let mut intent = get(&mut tx, key).await?.ok_or_else(invalid)?;
            if intent["generation"] != json!(generation) {
                return Err(invalid());
            }
            if matches!(
                intent["state"].as_str(),
                Some("refreshing" | "outcome_unknown")
            ) {
                if intent["state"] == "refreshing" && at(&intent["lease_until"])? > now {
                    return Err(Failure("gmail_refresh_in_progress"));
                }
                intent["state"] = json!("outcome_unknown");
                intent["reason"] = json!("abandoned_refresh_requires_reauthorization");
                put(&mut tx, key, &intent).await?;
                account["status"] = json!("reauthorization_required");
                account["access"] = Value::Null;
                put(&mut tx, ACCOUNT, &account).await?;
                commit(tx).await?;
                return Err(Failure("gmail_refresh_outcome_unknown"));
            }
        }
        if at(&account["expires_at"])? > now + Duration::seconds(60) {
            let token = secret(self.settings, &account, "access")?;
            account
                .as_object_mut()
                .ok_or_else(invalid)?
                .remove("access");
            account
                .as_object_mut()
                .ok_or_else(invalid)?
                .remove("refresh");
            commit(tx).await?;
            return Ok(Access { token, account });
        }
        let refresh = secret(self.settings, &account, "refresh")?;
        let key = format!("gmd_rfr:{}", Uuid::new_v4().simple());
        let intent = json!({"state":"refreshing","generation":generation,"google_subject":account["google_subject"],"account_email":account["account_email"],"started_at":now,"lease_until":now+Duration::seconds(70)});
        account["refresh_intent"] = json!(key);
        put(&mut tx, &key, &intent).await?;
        put(&mut tx, ACCOUNT, &account).await?;
        commit(tx).await?;
        let result: Result<TokenResponse> = async {
            let tokens = self.provider.refresh(&refresh).await?;
            if tokens
                .granted_scopes()?
                .unwrap_or_else(|| crate::google_oauth::scopes(GrantMode::Compose))
                != crate::google_oauth::scopes(GrantMode::Compose)
            {
                return Err(Failure("unexpected_or_insufficient_scopes"));
            }
            if self.provider.identity(tokens.access()).await?
                != (
                    text(&account, "google_subject")?.to_owned(),
                    text(&account, "account_email")?.to_owned(),
                )
            {
                return Err(Failure("wrong_google_account"));
            }
            Ok(tokens)
        }
        .await;
        let mut tx = begin(c).await?;
        let current = get(&mut tx, ACCOUNT)
            .await?
            .ok_or(Failure("gmail_drafts_account_changed"))?;
        let mut retained = get(&mut tx, &key).await?.ok_or_else(invalid)?;
        if current["generation"] != json!(generation)
            || current["status"] != "connected"
            || current["refresh_intent"] != key
            || current["google_subject"] != account["google_subject"]
            || current["account_email"] != account["account_email"]
            || retained["state"] != "refreshing"
        {
            if retained["state"] == "refreshing" {
                retained["state"] = json!("outcome_unknown");
                retained["reason"] = json!("account_context_changed");
                put(&mut tx, &key, &retained).await?;
            }
            commit(tx).await?;
            return Err(Failure("gmail_drafts_account_changed"));
        }
        let result = if at(&retained["lease_until"])? <= Utc::now() {
            Err(Failure("gmail_refresh_permit_expired"))
        } else {
            result
        };
        let mut current = current;
        match result {
            Err(error) => {
                retained["state"] = json!("outcome_unknown");
                retained["failure_code"] = json!(error.0);
                put(&mut tx, &key, &retained).await?;
                current["status"] = json!("reauthorization_required");
                current["access"] = Value::Null;
                put(&mut tx, ACCOUNT, &current).await?;
                commit(tx).await?;
                Err(Failure("gmail_drafts_reauthorization_required"))
            }
            Ok(tokens) => {
                valid(&current, self.settings)?;
                separate(
                    &mut tx,
                    text(&current, "google_subject")?,
                    text(&current, "account_email")?,
                )
                .await?;
                let store = store(self.settings)?;
                current["access"] =
                    json!(store.encrypt(&json!(tokens.access()), &format!("{ACCOUNT}:access"))?);
                current["refresh"] = json!(store.encrypt(
                    &json!(tokens.refresh().unwrap_or(&refresh)),
                    &format!("{ACCOUNT}:refresh")
                )?);
                current["expires_at"] = json!(Utc::now() + Duration::seconds(tokens.expires_in()));
                current["last_refresh_at"] = json!(Utc::now());
                current["refresh_intent"] = Value::Null;
                retained["state"] = json!("completed");
                retained["completed_at"] = json!(Utc::now());
                put(&mut tx, &key, &retained).await?;
                put(&mut tx, ACCOUNT, &current).await?;
                let token = tokens.access().to_owned();
                current
                    .as_object_mut()
                    .ok_or_else(invalid)?
                    .remove("access");
                current
                    .as_object_mut()
                    .ok_or_else(invalid)?
                    .remove("refresh");
                commit(tx).await?;
                Ok(Access {
                    token,
                    account: current,
                })
            }
        }
    }
}
