//! Primary credential generation and unknown-safe refresh/verify/local-first disconnect.
use super::{oauth::*, *};
use crate::{gmail_accounts::oauth::Provider, google_oauth::TokenResponse};
use chrono::Duration;
/// Contains a credential; no Debug, Clone or Serialize.
pub struct Access {
    token: String,
    account: Value,
}
impl Access {
    pub fn token(&self) -> &str {
        &self.token
    }
    pub fn generation(&self) -> Result<i64> {
        number(&self.account["token_generation"])
    }
}
fn decrypt(settings: &Settings, value: &Value, kind: &str) -> Result<String> {
    let id = id(value)?;
    store(settings)?
        .decrypt(
            text(value, &format!("encrypted_{kind}_token"))?,
            &format!("{id}:{kind}"),
        )?
        .as_str()
        .filter(|s| !s.is_empty() && s.len() <= 16384)
        .map(str::to_owned)
        .ok_or(Failure("token_decryption_failed"))
}
fn public(mut value: Value) -> Value {
    if let Some(value) = value.as_object_mut() {
        for key in [
            "encrypted_access_token",
            "encrypted_refresh_token",
            "encryption_key_id",
        ] {
            value.remove(key);
        }
    }
    value
}
fn same(current: &Value, original: &Value) -> bool {
    [
        "id",
        "token_generation",
        "google_subject",
        "account_email",
        "granted_scopes",
    ]
    .iter()
    .all(|key| current[*key] == original[*key])
        && current["status"] == "connected"
}
impl<P: Provider> Service<'_, P> {
    pub async fn access(&self, c: &mut PgConnection) -> Result<Access> {
        let store = store(self.settings)?;
        let mut tx = begin(c).await?;
        let mut value = account(&mut tx)
            .await?
            .ok_or(Failure("gmail_not_connected"))?;
        let granted = valid(&value, self.settings)?;
        let id = id(&value)?;
        let generation = number(&value["token_generation"])?;
        let pointer = format!("gm_leg_rfr:{}", id.simple());
        if let Some(active) = get(&mut tx, &pointer).await? {
            let key = text(&active, "key")?;
            let mut intent = get(&mut tx, key).await?.ok_or_else(invalid)?;
            if intent["account_generation"] == json!(generation)
                && matches!(
                    intent["state"].as_str(),
                    Some("refreshing" | "outcome_unknown")
                )
            {
                if intent["state"] == "refreshing" && at(&intent["lease_until"])? > now() {
                    return Err(Failure("gmail_refresh_in_progress"));
                }
                if intent["state"] == "refreshing" {
                    intent["state"] = json!("outcome_unknown");
                    intent["reason"] = json!("abandoned_refresh_requires_reauthorization");
                    put(&mut tx, key, &intent).await?;
                }
                value["status"] = json!("reauthorization_required");
                value["encrypted_access_token"] = Value::Null;
                save(&mut tx, generation, &value).await?;
                commit(tx).await?;
                return Err(Failure("gmail_refresh_outcome_unknown"));
            }
        }
        if !value["token_expires_at"].is_null()
            && at(&value["token_expires_at"])? > now() + Duration::seconds(60)
        {
            let token = decrypt(self.settings, &value, "access")?;
            commit(tx).await?;
            return Ok(Access {
                token,
                account: public(value),
            });
        }
        let refresh = decrypt(self.settings, &value, "refresh")?;
        let key = format!("gm_lrf:{}", Uuid::new_v4().simple());
        let intent = json!({"account_id":id,"account_generation":generation,"google_subject":value["google_subject"],"account_email":value["account_email"],"state":"refreshing","started_at":now(),"lease_until":now()+Duration::seconds(70)});
        put(&mut tx, &key, &intent).await?;
        put(
            &mut tx,
            &pointer,
            &json!({"key":key,"account_generation":generation}),
        )
        .await?;
        commit(tx).await?;
        let result: Result<TokenResponse> = async {
            let tokens = self.provider.refresh(&refresh).await?;
            if tokens.granted_scopes()?.unwrap_or_else(|| granted.clone()) != granted {
                return Err(Failure("unexpected_or_insufficient_scopes"));
            }
            if self.provider.identity(tokens.access()).await?
                != (
                    text(&value, "google_subject")?.to_owned(),
                    text(&value, "account_email")?.to_owned(),
                )
            {
                return Err(Failure("wrong_google_account"));
            }
            Ok(tokens)
        }
        .await;
        let mut tx = begin(c).await?;
        let mut current = account(&mut tx)
            .await?
            .ok_or(Failure("gmail_connection_changed_retry_verification"))?;
        let active = get(&mut tx, &pointer).await?.ok_or_else(invalid)?;
        let mut intent = get(&mut tx, &key).await?.ok_or_else(invalid)?;
        if !same(&current, &value) || active["key"] != key || intent["state"] != "refreshing" {
            if intent["state"] == "refreshing" {
                intent["state"] = json!("outcome_unknown");
                intent["reason"] = json!("account_context_changed");
                put(&mut tx, &key, &intent).await?;
            }
            commit(tx).await?;
            return Err(Failure("gmail_connection_changed_retry_verification"));
        }
        let result = if at(&intent["lease_until"])? <= now() {
            Err(Failure("gmail_refresh_permit_expired"))
        } else {
            result
        };
        match result {
            Err(error) => {
                intent["state"] = json!("outcome_unknown");
                intent["reason"] = json!(error.0);
                put(&mut tx, &key, &intent).await?;
                current["status"] = json!("reauthorization_required");
                current["encrypted_access_token"] = Value::Null;
                save(&mut tx, generation, &current).await?;
                commit(tx).await?;
                Err(Failure("gmail_reauthorization_required"))
            }
            Ok(tokens) => {
                valid(&current, self.settings)?;
                let next = generation.checked_add(1).ok_or_else(invalid)?;
                current["encrypted_access_token"] =
                    json!(store.encrypt(&json!(tokens.access()), &format!("{id}:access"))?);
                current["encrypted_refresh_token"] = json!(store.encrypt(
                    &json!(tokens.refresh().unwrap_or(&refresh)),
                    &format!("{id}:refresh")
                )?);
                current["encryption_key_id"] = json!(store.active_id());
                current["token_generation"] = json!(next);
                current["token_expires_at"] = json!(now() + Duration::seconds(tokens.expires_in()));
                current["last_refresh_at"] = json!(now());
                current["last_verified_at"] = json!(now());
                let saved = save(&mut tx, generation, &current).await?;
                intent["state"] = json!("completed");
                intent["published_generation"] = json!(next);
                intent["finished_at"] = json!(now());
                put(&mut tx, &key, &intent).await?;
                commit(tx).await?;
                Ok(Access {
                    token: tokens.access().to_owned(),
                    account: public(saved),
                })
            }
        }
    }
    pub async fn verify(&self, c: &mut PgConnection) -> Result<Value> {
        let access = self.access(c).await?;
        let mut tx = begin(c).await?;
        let current = account(&mut tx)
            .await?
            .ok_or(Failure("gmail_not_connected"))?;
        valid(&current, self.settings)?;
        if !same(&current, &access.account)
            || decrypt(self.settings, &current, "access")? != access.token
        {
            return Err(Failure("gmail_connection_changed_retry_verification"));
        }
        commit(tx).await?;
        let identity = self.provider.identity(access.token()).await;
        let mut tx = begin(c).await?;
        let mut current = account(&mut tx)
            .await?
            .ok_or(Failure("gmail_not_connected"))?;
        if !same(&current, &access.account)
            || decrypt(self.settings, &current, "access")? != access.token
        {
            return Err(Failure("gmail_connection_changed_retry_verification"));
        }
        valid(&current, self.settings)?;
        let generation = access.generation()?;
        if identity.as_ref().ok()
            != Some(&(
                text(&current, "google_subject")?.to_owned(),
                text(&current, "account_email")?.to_owned(),
            ))
        {
            current["status"] = json!("reauthorization_required");
            current["encrypted_access_token"] = Value::Null;
            save(&mut tx, generation, &current).await?;
            commit(tx).await?;
            return Err(Failure("gmail_reauthorization_required"));
        }
        current["last_verified_at"] = json!(now());
        let saved = save(&mut tx, generation, &current).await?;
        let mut result = projection(Some(&saved), true, true)?;
        result["live_verified"] = json!(true);
        result["verification_basis"] = json!("current_identity_probe");
        commit(tx).await?;
        Ok(result)
    }
    pub async fn disconnect(&self, c: &mut PgConnection) -> Result<Value> {
        let (result, revoke) = disconnect_local(c, self.settings).await?;
        let Some((token, revoke_key)) = revoke else {
            return Ok(result);
        };
        let requested = self.provider.revoke(&token).await.is_ok();
        let mut tx = begin_local(c).await?;
        let mut record = get(&mut tx, &revoke_key).await?.ok_or_else(invalid)?;
        record["state"] = json!(if requested {
            "request_accepted"
        } else {
            "outcome_unknown"
        });
        record["response_recorded_at"] = json!(now());
        put(&mut tx, &revoke_key, &record).await?;
        commit(tx).await?;
        Ok(
            json!({"status":"disconnected","revocation":if requested{"requested"}else{"unconfirmed_revoke_in_google_account_settings"}}),
        )
    }
}
pub async fn disconnect_without_provider(
    c: &mut PgConnection,
    settings: &Settings,
) -> Result<Value> {
    disconnect_local(c, settings).await.map(|(value, _)| value)
}
async fn disconnect_local(
    c: &mut PgConnection,
    settings: &Settings,
) -> Result<(Value, Option<(String, String)>)> {
    let mut tx = begin_local(c).await?;
    let Some(mut value) = account(&mut tx).await? else {
        commit(tx).await?;
        return Ok((
            json!({"status":"disconnected","revocation":"not_needed"}),
            None,
        ));
    };
    let generation = number(&value["token_generation"])?;
    let had_refresh = !value["encrypted_refresh_token"].is_null();
    let revoke = decrypt(settings, &value, "refresh").ok();
    let revoke_key = format!("gm_lrv:{}", Uuid::new_v4().simple());
    let expected = text(&value, "account_email")?.to_owned();
    value["encrypted_access_token"] = Value::Null;
    value["encrypted_refresh_token"] = Value::Null;
    value["encryption_key_id"] = Value::Null;
    value["status"] = json!("disconnected");
    value["disconnected_at"] = json!(now());
    value["token_generation"] = json!(generation.checked_add(1).ok_or_else(invalid)?);
    save(&mut tx, generation, &value).await?;
    let states: bool = sqlx::query_scalar("SELECT to_regclass('oauth_states') IS NOT NULL")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    if states {
        let keys:Vec<String>=sqlx::query_scalar("SELECT state_hash FROM oauth_states WHERE provider='gmail' AND expected_email=$1 AND consumed_at IS NULL ORDER BY state_hash LIMIT 10001 FOR UPDATE").bind(&expected).fetch_all(&mut *tx).await.map_err(db)?;
        if keys.len() > 10000 {
            return Err(Failure("gmail_legacy_oauth_inventory_limit"));
        }
        let consumed:Vec<Value>=sqlx::query_scalar("UPDATE oauth_states SET consumed_at=clock_timestamp(),encrypted_verifier=NULL WHERE state_hash=ANY($1::text[]) AND consumed_at IS NULL RETURNING jsonb_build_object('state_hash',state_hash,'consumed_at',consumed_at,'encrypted_verifier',encrypted_verifier)").bind(&keys).fetch_all(&mut *tx).await.map_err(db)?;
        let returned = consumed
            .iter()
            .map(|value| text(value, "state_hash"))
            .collect::<Result<BTreeSet<_>>>()?;
        if keys.iter().map(String::as_str).collect::<BTreeSet<_>>() != returned
            || consumed.iter().any(|value| {
                value["consumed_at"].is_null() || !value["encrypted_verifier"].is_null()
            })
        {
            return Err(Failure("gmail_legacy_write_ack_failed"));
        }
    }
    if revoke.is_some() {
        put(&mut tx,&revoke_key,&json!({"account_id":value["id"],"account_generation":generation,"state":"outcome_unknown","action":"revoke","requested_at":now(),"automatic_replay":false})).await?;
    }
    commit(tx).await?;
    Ok((
        json!({"status":"disconnected","revocation":if had_refresh{"unconfirmed_revoke_in_google_account_settings"}else{"not_needed"}}),
        revoke.map(|token| (token, revoke_key)),
    ))
}
