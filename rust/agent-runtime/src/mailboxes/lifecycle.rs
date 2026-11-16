use super::*;
use crate::google_oauth::scopes;
impl<P: Provider> Service<'_, P> {
    pub async fn start(
        &self,
        c: &mut PgConnection,
        slot: Slot,
        consent: Consent,
        browser: &str,
    ) -> Result<Value> {
        self.settings.enabled()?;
        if !consent.account_consent || !consent.read_and_draft_consent {
            return Err(Failure("gmail_read_draft_consent_required"));
        }
        if !(32..=128).contains(&browser.len())
            || !browser
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
        {
            return Err(Failure("invalid_oauth_browser_binding"));
        }
        let store = self.settings.store()?;
        let mut tx = c.begin().await.map_err(db)?;
        lock(&mut tx).await?;
        let mut old = read(&mut tx, &slot.key(), true).await?.unwrap_or(json!({}));
        if old["status"] == "connected" {
            return Err(Failure("disconnect_before_reconnecting"));
        }
        let next = next_generation(&old)?;
        let expected = if old["status"] == "reauthorization_required" {
            json!([text(&old, "google_subject")?, text(&old, "account_email")?])
        } else {
            Value::Null
        };
        old["status"] = json!("authorizing");
        old["generation"] = json!(next);
        let state = format!("mailbox.{}.{}", slot.name(), browser_nonce());
        let verifier = browser_nonce();
        let hash = digest(&state);
        let hint = if self.settings.allowed.len() == 1 {
            self.settings.allowed.first().map(String::as_str)
        } else {
            None
        };
        let url = self.provider.authorization_url(&state, &verifier, hint)?;
        put(&mut tx, &slot.key(), &old).await?;
        put(&mut tx,&format!("gm54_oauth:{}",&hash[..32]),&json!({"state_hash":hash,"browser_hash":digest(browser),"slot":slot.name(),"generation":next,"consumed":false,"expected_identity":expected,"verifier":store.encrypt(&json!(verifier),&hash)?,"expires_at":expires(self.settings.ttl)})).await?;
        commit(tx).await?;
        Ok(json!({"authorization_url":url,"expires_in":self.settings.ttl}))
    }
    pub async fn callback(
        &self,
        c: &mut PgConnection,
        state: &str,
        browser: &str,
        callback_uri: &str,
        code: Option<&str>,
        error: Option<&str>,
    ) -> Result<Value> {
        self.settings.enabled()?;
        if browser.is_empty() || callback_uri != self.provider.redirect_uri() {
            return Err(Failure("invalid_oauth_state_or_redirect"));
        }
        let hash = digest(state);
        let key = format!("gm54_oauth:{}", &hash[..32]);
        let store = self.settings.store()?;
        let mut tx = c.begin().await.map_err(db)?;
        lock(&mut tx).await?;
        let mut intent = read(&mut tx, &key, true)
            .await?
            .ok_or(Failure("invalid_expired_or_replayed_state"))?;
        if intent["state_hash"] != hash
            || intent["consumed"] != false
            || intent["browser_hash"] != digest(browser)
            || !instant(&intent["expires_at"]).is_some_and(|t| t > Utc::now())
        {
            return Err(Failure("invalid_expired_or_replayed_state"));
        }
        let slot = Slot::parse(text(&intent, "slot")?)?;
        let expected = generation(&intent)?;
        if read(&mut tx, &slot.key(), true)
            .await?
            .as_ref()
            .map(generation)
            .transpose()?
            != Some(expected)
        {
            return Err(Failure("connection_intent_superseded"));
        }
        let verifier = store
            .decrypt(text(&intent, "verifier")?, &hash)?
            .as_str()
            .map(str::to_owned)
            .ok_or(Failure("token_decryption_failed"))?;
        intent
            .as_object_mut()
            .ok_or(Failure("invalid_gmail_account_record"))?
            .remove("verifier");
        intent["consumed"] = json!(true);
        put(&mut tx, &key, &intent).await?;
        commit(tx).await?;
        if error.is_some() || code.is_none_or(str::is_empty) {
            return Err(Failure("consent_denied"));
        }
        let tokens = self.provider.exchange(code.unwrap(), &verifier).await?;
        if !tokens.has_refresh_token()
            || tokens.granted_scopes()?.as_ref() != Some(&scopes(GrantMode::ReadDraft))
        {
            return Err(Failure("unexpected_or_insufficient_scopes"));
        }
        let (subject, email) = self.provider.identity(tokens.access()).await?;
        if !self.settings.allowed(&email) {
            return Err(Failure("gmail_account_not_authorized"));
        }
        if !intent["expected_identity"].is_null()
            && intent["expected_identity"] != json!([subject, email])
        {
            return Err(Failure("gmail_identity_mismatch"));
        }
        let mut tx = c.begin().await.map_err(db)?;
        lock(&mut tx).await?;
        if read(&mut tx, &slot.key(), true)
            .await?
            .as_ref()
            .map(generation)
            .transpose()?
            != Some(expected)
        {
            return Err(Failure("connection_intent_superseded"));
        }
        if let Some(other) = read(&mut tx, &slot.other().key(), true).await?
            && other["status"] != "disconnected"
            && (other["google_subject"] == subject || other["account_email"] == email)
        {
            return Err(Failure("gmail_account_already_connected"));
        }
        let outreach:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM owner_preferences WHERE key='gmail_drafts:account' AND (value->>'google_subject'=$1 OR lower(value->>'account_email')=lower($2)))").bind(&subject).bind(&email).fetch_one(&mut *tx).await.map_err(db)?;
        if outreach {
            return Err(Failure("gmail_separate_outreach_account_required"));
        }
        let key = slot.key();
        put(&mut tx,&key,&json!({"status":"connected","generation":expected,"google_subject":subject,"account_email":email,"scopes":scopes(GrantMode::ReadDraft),"access":store.encrypt(&json!(tokens.access()),&format!("{key}:access"))?,"refresh":store.encrypt(&json!(tokens.refresh().ok_or(Failure("invalid_token_response"))?),&format!("{key}:refresh"))?,"expires_at":expires(tokens.expires_in()),"last_verified_at":timestamp()})).await?;
        commit(tx).await?;
        self.status(c, slot).await
    }
    pub async fn access(&self, c: &mut PgConnection, slot: Slot) -> Result<Access> {
        self.settings.enabled()?;
        let store = self.settings.store()?;
        let key = slot.key();
        let mut tx = c.begin().await.map_err(db)?;
        lock(&mut tx).await?;
        let value = read(&mut tx, &key, true)
            .await?
            .ok_or(Failure("gmail_read_draft_account_not_connected"))?;
        let granted: BTreeSet<String> = serde_json::from_value(value["scopes"].clone())
            .map_err(|_| Failure("gmail_read_draft_account_not_connected"))?;
        if value["status"] != "connected" || granted != scopes(GrantMode::ReadDraft) {
            return Err(Failure("gmail_read_draft_account_not_connected"));
        }
        if !self.settings.allowed(text(&value, "account_email")?) {
            return Err(Failure("gmail_account_not_authorized"));
        }
        let expected = generation(&value)?;
        let decrypt = |field: &str| -> Result<String> {
            store
                .decrypt(text(&value, field)?, &format!("{key}:{field}"))?
                .as_str()
                .filter(|s| !s.is_empty())
                .map(str::to_owned)
                .ok_or(Failure("token_decryption_failed"))
        };
        let expiry =
            instant(&value["expires_at"]).ok_or(Failure("invalid_gmail_account_record"))?;
        if expiry > Utc::now() + Duration::seconds(60) {
            let token = decrypt("access")?;
            commit(tx).await?;
            return Ok(Access {
                token,
                account: value,
            });
        }
        if instant(&value["refresh_lease_until"]).is_some_and(|t| t > Utc::now()) {
            return Err(Failure("gmail_refresh_in_progress"));
        }
        if value["refresh_lease"].is_string() {
            let mut unknown = value.clone();
            unknown["status"] = json!("reauthorization_required");
            unknown["access"] = Value::Null;
            unknown["refresh_outcome"] = json!("outcome_unknown");
            let history = format!("gm54_rfr:{}", &digest(text(&value, "refresh_lease")?)[..32]);
            let retained = read(&mut tx, &history, true).await?;
            let mut retained=retained.unwrap_or(json!({"slot":slot.name(),"generation":expected,"lease":value["refresh_lease"],"source":"legacy_abandoned_refresh"}));
            retained["state"] = json!("outcome_unknown");
            retained["reason"] = json!("abandoned_refresh_requires_reauthorization");
            put(&mut tx, &history, &retained).await?;
            put(&mut tx, &key, &unknown).await?;
            commit(tx).await?;
            return Err(Failure("gmail_refresh_unavailable"));
        }
        let lease = Uuid::new_v4().simple().to_string();
        let mut claimed = value.clone();
        claimed["refresh_lease"] = json!(lease);
        claimed["refresh_lease_until"] = json!(expires(70));
        let refresh = decrypt("refresh")?;
        let history = format!("gm54_rfr:{}", &digest(&lease)[..32]);
        put(&mut tx,&history,&json!({"slot":slot.name(),"generation":expected,"lease":lease,"state":"refreshing","lease_until":claimed["refresh_lease_until"],"started_at":timestamp()})).await?;
        put(&mut tx, &key, &claimed).await?;
        commit(tx).await?;
        let refreshed = async {
            let tokens = self.provider.refresh(&refresh).await?;
            if tokens.granted_scopes()?.unwrap_or(granted) != scopes(GrantMode::ReadDraft) {
                return Err(Failure("gmail_scope_changed"));
            }
            if self.provider.identity(tokens.access()).await?
                != (
                    text(&value, "google_subject")?.into(),
                    text(&value, "account_email")?.into(),
                )
            {
                return Err(Failure("gmail_identity_mismatch"));
            }
            Ok(tokens)
        }
        .await;
        let mut tx = c.begin().await.map_err(db)?;
        let current = self.fence(&mut tx, slot, expected).await?;
        if current["refresh_lease"] != lease {
            return Err(Failure("gmail_refresh_superseded"));
        }
        let mut intent = read(&mut tx, &history, true)
            .await?
            .ok_or(Failure("invalid_gmail_account_record"))?;
        let refreshed =
            if instant(&current["refresh_lease_until"]).is_none_or(|at| at <= Utc::now()) {
                Err(Failure("gmail_refresh_lease_expired"))
            } else {
                refreshed
            };
        let mut next = value.clone();
        next.as_object_mut()
            .ok_or(Failure("invalid_gmail_account_record"))?
            .remove("refresh_lease");
        next.as_object_mut()
            .ok_or(Failure("invalid_gmail_account_record"))?
            .remove("refresh_lease_until");
        let tokens = match refreshed {
            Ok(tokens) => tokens,
            Err(error) => {
                let invalid = matches!(
                    error.0,
                    "invalid_token_response"
                        | "credential_revoked_or_code_invalid"
                        | "gmail_scope_changed"
                        | "gmail_identity_mismatch"
                        | "identity_verification_failed"
                );
                next["status"] = json!("reauthorization_required");
                next["access"] = Value::Null;
                next["refresh_outcome"] = json!(if invalid {
                    "failed_reauthorization_required"
                } else {
                    "outcome_unknown"
                });
                intent["state"] = next["refresh_outcome"].clone();
                intent["reason"] = json!(error.0);
                intent["finished_at"] = json!(timestamp());
                put(&mut tx, &history, &intent).await?;
                put(&mut tx, &key, &next).await?;
                commit(tx).await?;
                return Err(Failure(if invalid {
                    "gmail_reauthorization_required"
                } else {
                    "gmail_refresh_unavailable"
                }));
            }
        };
        next["access"] = json!(store.encrypt(&json!(tokens.access()), &format!("{key}:access"))?);
        next["refresh"] = json!(store.encrypt(
            &json!(tokens.refresh().unwrap_or(&refresh)),
            &format!("{key}:refresh")
        )?);
        next["last_refresh_at"] = json!(timestamp());
        next["last_verified_at"] = json!(timestamp());
        next["expires_at"] = json!(expires(tokens.expires_in()));
        intent["state"] = json!("completed");
        intent["finished_at"] = json!(timestamp());
        put(&mut tx, &history, &intent).await?;
        put(&mut tx, &key, &next).await?;
        commit(tx).await?;
        Ok(Access {
            token: tokens.access_token,
            account: next,
        })
    }
    pub async fn verify(&self, c: &mut PgConnection, slot: Slot) -> Result<Value> {
        let access = self.access(c, slot).await?;
        let identity = self.provider.identity(access.token()).await?;
        let mut tx = c.begin().await.map_err(db)?;
        let mut current = self.fence(&mut tx, slot, access.generation()?).await?;
        let mismatch = identity
            != (
                text(&access.account, "google_subject")?.into(),
                text(&access.account, "account_email")?.into(),
            );
        if mismatch {
            current["status"] = json!("reauthorization_required");
            current["access"] = Value::Null;
        } else {
            current["last_verified_at"] = json!(timestamp());
        }
        put(&mut tx, &slot.key(), &current).await?;
        commit(tx).await?;
        if mismatch {
            return Err(Failure("gmail_identity_mismatch"));
        }
        self.status(c, slot).await
    }
    pub async fn disconnect(&self, c: &mut PgConnection, slot: Slot) -> Result<Value> {
        // Local disconnect remains possible when provider access/allowlist is disabled.
        let mut tx = c.begin().await.map_err(db)?;
        lock(&mut tx).await?;
        let key = slot.key();
        let old = read(&mut tx, &key, true).await?.unwrap_or(json!({}));
        put(
            &mut tx,
            &key,
            &json!({"status":"disconnected","generation":next_generation(&old)?}),
        )
        .await?;
        commit(tx).await?;
        let revocation = if let Some(envelope) = old["refresh"].as_str() {
            let revoke = async {
                let raw = self
                    .settings
                    .store()?
                    .decrypt(envelope, &format!("{key}:refresh"))?;
                self.provider
                    .revoke(raw.as_str().ok_or(Failure("token_decryption_failed"))?)
                    .await
            }
            .await;
            if revoke.is_ok() {
                "confirmed"
            } else {
                "manual_revocation_required"
            }
        } else {
            "not_needed"
        };
        Ok(json!({"status":"disconnected","revocation":revocation,"sending_enabled":false}))
    }
}
