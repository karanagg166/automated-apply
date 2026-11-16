//! Durable read-account refresh intents and generation fences; no lock spans provider IO.
use super::{
    oauth::{self, Provider, Service},
    *,
};
use chrono::Duration;
/// Contains a credential: deliberately no Debug/Serialize/Clone.
pub struct Access {
    token: String,
    pub(crate) account: Value,
}
impl Access {
    pub fn token(&self) -> &str {
        &self.token
    }
    pub fn generation(&self) -> Result<i64> {
        oauth::generation(&self.account)
    }
}
async fn credentials(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Value> {
    let account:Option<Value>=sqlx::query_scalar("SELECT jsonb_build_object('id',id,'google_subject',google_subject,'account_email',account_email,'granted_scopes',granted_scopes,'status',status,'token_generation',token_generation,'token_expires_at',token_expires_at,'encrypted_access_token',encrypted_access_token,'encrypted_refresh_token',encrypted_refresh_token) FROM gmail_read_accounts WHERE id=$1 AND provider='gmail' FOR UPDATE").bind(id).fetch_optional(&mut **tx).await.map_err(db)?;
    account.ok_or(Failure("gmail_read_account_not_found"))
}
async fn record(tx: &mut Transaction<'_, Postgres>, key: &str) -> Result<Option<Value>> {
    sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(key)
        .fetch_optional(&mut **tx)
        .await
        .map_err(db)
}
fn valid(account: &Value, settings: &Settings) -> Result<BTreeSet<String>> {
    if account["status"] != "connected" {
        return Err(Failure("gmail_not_connected"));
    }
    if !settings.allows(oauth::text(account, "account_email")?) {
        return Err(Failure("gmail_account_not_authorized"));
    }
    let current = scopes(account)?;
    if current != crate::google_oauth::scopes(crate::google_oauth::GrantMode::Metadata)
        && current != crate::google_oauth::scopes(crate::google_oauth::GrantMode::Read)
    {
        return Err(Failure("unexpected_or_insufficient_scopes"));
    }
    Ok(current)
}
fn decrypt(store: &TokenStore, account: &Value, id: Uuid, key: &str) -> Result<String> {
    store
        .decrypt(
            oauth::text(account, &format!("encrypted_{key}_token"))?,
            &format!("{id}:{key}"),
        )?
        .as_str()
        .filter(|s| !s.is_empty() && s.len() <= 16384)
        .map(str::to_owned)
        .ok_or(Failure("token_decryption_failed"))
}
impl<P: Provider> Service<'_, P> {
    pub async fn access(&self, c: &mut PgConnection, id: Uuid) -> Result<Access> {
        let store = self
            .settings
            .store
            .as_ref()
            .ok_or(Failure("oauth_encryption_not_configured"))?;
        let mut tx = oauth::begin(c).await?;
        let account = credentials(&mut tx, id).await?;
        let granted = valid(&account, self.settings)?;
        let generation = oauth::generation(&account)?;
        let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
            .fetch_one(&mut *tx)
            .await
            .map_err(db)?;
        if crate::gmail_history::contract::timestamp(&account["token_expires_at"])
            .is_some_and(|at| at > now + Duration::seconds(60))
        {
            let token = decrypt(store, &account, id, "access")?;
            let mut public = account;
            public
                .as_object_mut()
                .unwrap()
                .remove("encrypted_access_token");
            public
                .as_object_mut()
                .unwrap()
                .remove("encrypted_refresh_token");
            oauth::commit(tx).await?;
            return Ok(Access {
                token,
                account: public,
            });
        }
        let pointer = format!("gm_rfr_active:{}", id.simple());
        if let Some(active) = record(&mut tx, &pointer).await? {
            let key = oauth::text(&active, "key")?;
            let intent = record(&mut tx, key).await?.ok_or_else(invalid)?;
            if intent["account_generation"] == json!(generation)
                && matches!(
                    intent["state"].as_str(),
                    Some("refreshing" | "outcome_unknown")
                )
            {
                if intent["state"] == "refreshing" && oauth::at(&intent["lease_until"])? > now {
                    return Err(Failure("gmail_refresh_in_progress"));
                }
                let mut unknown = intent;
                unknown["state"] = json!("outcome_unknown");
                unknown["reason"] = json!("abandoned_refresh_requires_reauthorization");
                put(&mut tx, key, &unknown).await?;
                let ack:Option<i64>=sqlx::query_scalar("UPDATE gmail_read_accounts SET status='reauthorization_required',encrypted_access_token=NULL,updated_at=clock_timestamp() WHERE id=$1 AND token_generation=$2 RETURNING token_generation").bind(id).bind(generation).fetch_optional(&mut *tx).await.map_err(db)?;
                if ack != Some(generation) {
                    return Err(Failure("gmail_read_write_ack_failed"));
                }
                oauth::commit(tx).await?;
                return Err(Failure("gmail_refresh_outcome_unknown"));
            }
        }
        let refresh = decrypt(store, &account, id, "refresh")?;
        let intent_id = Uuid::new_v4();
        let key = format!("gm_rfr:{}", intent_id.simple());
        let intent = json!({"id":intent_id,"account_id":id,"account_generation":generation,"google_subject":account["google_subject"],"account_email":account["account_email"],"state":"refreshing","lease_until":now+Duration::seconds(70),"started_at":now});
        put(&mut tx, &key, &intent).await?;
        put(
            &mut tx,
            &pointer,
            &json!({"key":key,"account_generation":generation}),
        )
        .await?;
        oauth::commit(tx).await?;
        let refreshed = async {
            let tokens = self.provider.refresh(&refresh).await?;
            if tokens.granted_scopes()?.unwrap_or_else(|| granted.clone()) != granted {
                return Err(Failure("unexpected_or_insufficient_scopes"));
            }
            let identity = self.provider.identity(tokens.access()).await?;
            if identity
                != (
                    oauth::text(&account, "google_subject")?.to_owned(),
                    oauth::text(&account, "account_email")?.to_owned(),
                )
            {
                return Err(Failure("wrong_google_account"));
            }
            Ok(tokens)
        }
        .await;
        let mut tx = oauth::begin(c).await?;
        let current = credentials(&mut tx, id).await?;
        let active = record(&mut tx, &pointer)
            .await?
            .ok_or(Failure("gmail_refresh_superseded"))?;
        let mut retained = record(&mut tx, &key)
            .await?
            .ok_or(Failure("gmail_refresh_superseded"))?;
        if current["token_generation"] != account["token_generation"]
            || current["status"] != "connected"
            || active["key"] != key
            || retained["state"] != "refreshing"
            || current["google_subject"] != account["google_subject"]
            || current["account_email"] != account["account_email"]
            || scopes(&current)? != granted
        {
            return Err(Failure("gmail_refresh_superseded"));
        }
        valid(&current, self.settings)?;
        let at: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
            .fetch_one(&mut *tx)
            .await
            .map_err(db)?;
        let refreshed = if oauth::at(&retained["lease_until"])? <= at {
            Err(Failure("gmail_refresh_permit_expired"))
        } else {
            refreshed
        };
        let tokens = match refreshed {
            Ok(tokens) => tokens,
            Err(error) => {
                retained["state"] = json!("outcome_unknown");
                retained["reason"] = json!(error.0);
                put(&mut tx, &key, &retained).await?;
                let ack:Option<i64>=sqlx::query_scalar("UPDATE gmail_read_accounts SET status='reauthorization_required',encrypted_access_token=NULL,updated_at=clock_timestamp() WHERE id=$1 AND token_generation=$2 RETURNING token_generation").bind(id).bind(generation).fetch_optional(&mut *tx).await.map_err(db)?;
                if ack != Some(generation) {
                    return Err(Failure("gmail_read_write_ack_failed"));
                }
                oauth::commit(tx).await?;
                return Err(Failure("gmail_reauthorization_required"));
            }
        };
        let next = generation.checked_add(1).ok_or_else(invalid)?;
        let saved:Option<i64>=sqlx::query_scalar("UPDATE gmail_read_accounts SET encrypted_access_token=$3,encrypted_refresh_token=$4,encryption_key_id=$5,token_generation=$6,token_expires_at=clock_timestamp()+($7::double precision*interval '1 second'),last_refresh_at=clock_timestamp(),last_verified_at=clock_timestamp(),updated_at=clock_timestamp() WHERE id=$1 AND token_generation=$2 AND status='connected' RETURNING token_generation").bind(id).bind(generation).bind(store.encrypt(&json!(tokens.access()),&format!("{id}:access"))?).bind(store.encrypt(&json!(tokens.refresh().unwrap_or(&refresh)),&format!("{id}:refresh"))?).bind(store.active_id()).bind(next).bind(tokens.expires_in() as f64).fetch_optional(&mut *tx).await.map_err(db)?;
        if saved != Some(next) {
            return Err(Failure("gmail_read_write_ack_failed"));
        }
        retained["state"] = json!("completed");
        retained["published_generation"] = json!(next);
        retained["finished_at"] = json!(Utc::now());
        put(&mut tx, &key, &retained).await?;
        let public = account_in(&mut tx, id, false).await?;
        oauth::commit(tx).await?;
        Ok(Access {
            token: tokens.access().to_owned(),
            account: public,
        })
    }
    pub async fn verify(&self, c: &mut PgConnection, id: Uuid) -> Result<Value> {
        let access = self.access(c, id).await?;
        let expected = access.generation()?;
        let identity = self.provider.identity(access.token()).await?;
        let mut tx = oauth::begin(c).await?;
        let current = account_in(&mut tx, id, true).await?;
        valid(&current, self.settings)?;
        if oauth::generation(&current)? != expected
            || identity
                != (
                    oauth::text(&current, "google_subject")?.to_owned(),
                    oauth::text(&current, "account_email")?.to_owned(),
                )
        {
            return Err(Failure("gmail_read_account_context_changed"));
        }
        let ack:Option<i64>=sqlx::query_scalar("UPDATE gmail_read_accounts SET last_verified_at=clock_timestamp(),updated_at=clock_timestamp() WHERE id=$1 AND token_generation=$2 AND status='connected' RETURNING token_generation").bind(id).bind(expected).fetch_optional(&mut *tx).await.map_err(db)?;
        if ack != Some(expected) {
            return Err(Failure("gmail_read_write_ack_failed"));
        }
        let result = status_in(&mut tx, id, self.settings).await?;
        oauth::commit(tx).await?;
        Ok(result)
    }
    pub async fn disconnect(&self, c: &mut PgConnection, id: Uuid) -> Result<Value> {
        let mut tx = oauth::begin(c).await?;
        let account = credentials(&mut tx, id).await?;
        let generation = oauth::generation(&account)?;
        let next = generation.checked_add(1).ok_or_else(invalid)?;
        let revoke = self
            .settings
            .store
            .as_ref()
            .and_then(|store| decrypt(store, &account, id, "refresh").ok());
        let ack:Option<i64>=sqlx::query_scalar("UPDATE gmail_read_accounts SET encrypted_refresh_token=NULL,encrypted_access_token=NULL,encryption_key_id=NULL,status='disconnected',disconnected_at=clock_timestamp(),token_generation=$3,updated_at=clock_timestamp() WHERE id=$1 AND token_generation=$2 RETURNING token_generation").bind(id).bind(generation).bind(next).fetch_optional(&mut *tx).await.map_err(db)?;
        if ack != Some(next) {
            return Err(Failure("gmail_read_write_ack_failed"));
        }
        let policy = policy_in(&mut tx, id).await?;
        if policy["version"] != 0 {
            let version = policy["version"]
                .as_i64()
                .and_then(|v| v.checked_add(1))
                .ok_or_else(invalid)?;
            put(
                &mut tx,
                &format!("gmail_sync:{}", id.simple()),
                &json!({"version":version,"status":"disabled","policy":{"enabled":false}}),
            )
            .await?;
        }
        let count:i64=sqlx::query_scalar("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'gmail_msg:') AND value->>'account_id'=$1").bind(id.to_string()).fetch_one(&mut *tx).await.map_err(db)?;
        let purged:Vec<String>=sqlx::query_scalar("UPDATE owner_preferences SET value='{\"status\":\"purged\"}',updated_at=clock_timestamp() WHERE starts_with(key,'gmail_msg:') AND value->>'account_id'=$1 RETURNING key").bind(id.to_string()).fetch_all(&mut *tx).await.map_err(db)?;
        if purged.len() as i64 != count {
            return Err(Failure("gmail_read_write_ack_failed"));
        }
        let expected = oauth::text(&account, "account_email")?;
        let states:i64=sqlx::query_scalar("SELECT count(*) FROM gmail_read_oauth_states WHERE expected_email=$1 AND consumed_at IS NULL").bind(expected).fetch_one(&mut *tx).await.map_err(db)?;
        let consumed:Vec<String>=sqlx::query_scalar("UPDATE gmail_read_oauth_states SET consumed_at=clock_timestamp(),encrypted_verifier=NULL WHERE expected_email=$1 AND consumed_at IS NULL RETURNING state_hash").bind(expected).fetch_all(&mut *tx).await.map_err(db)?;
        if consumed.len() as i64 != states {
            return Err(Failure("gmail_read_write_ack_failed"));
        }
        oauth::commit(tx).await?;
        let revocation = if let Some(token) = revoke {
            if self.provider.revoke(&token).await.is_ok() {
                "requested"
            } else {
                "unconfirmed_revoke_in_google_account_settings"
            }
        } else {
            "not_needed"
        };
        Ok(json!({"status":"disconnected","revocation":revocation}))
    }
}
