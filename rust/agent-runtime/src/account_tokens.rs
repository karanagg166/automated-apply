//! Legacy-compatible context-bound token encryption; never formats keys or payloads for logs.
use crate::{Failure, Result};
use fernet::Fernet;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use subtle::ConstantTimeEq;
struct Key {
    cipher: Fernet,
    fingerprint: String,
}
pub struct TokenStore {
    active: String,
    keys: BTreeMap<String, Key>,
}
impl TokenStore {
    pub fn from_values(values: &BTreeMap<String, String>) -> Result<Option<Self>> {
        match (
            values.get("OAUTH_ACTIVE_KEY_ID"),
            values.get("OAUTH_ENCRYPTION_KEYS"),
        ) {
            (None, None) => Ok(None),
            (Some(active), Some(raw)) => {
                let keys: BTreeMap<String, String> =
                    serde_json::from_str(raw).map_err(|_| Failure("invalid_encryption_key"))?;
                Self::new(active, keys).map(Some)
            }
            _ => Err(Failure("oauth_encryption_not_configured")),
        }
    }
    pub fn new(active: &str, keys: BTreeMap<String, String>) -> Result<Self> {
        if active.is_empty() || !keys.contains_key(active) {
            return Err(Failure("oauth_encryption_not_configured"));
        }
        let mut parsed = BTreeMap::new();
        for (name, key) in keys {
            if name.is_empty()
                || name.len() > 40
                || !name
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
            {
                return Err(Failure("invalid_encryption_key_id"));
            }
            let cipher = Fernet::new(&key).ok_or(Failure("invalid_encryption_key"))?;
            let fingerprint = format!("{:x}", Sha256::digest(key.as_bytes()))[..24].to_owned();
            parsed.insert(
                name,
                Key {
                    cipher,
                    fingerprint,
                },
            );
        }
        Ok(Self {
            active: active.into(),
            keys: parsed,
        })
    }
    pub fn encrypt(&self, value: &Value, purpose: &str) -> Result<String> {
        let key = self
            .keys
            .get(&self.active)
            .ok_or(Failure("oauth_encryption_not_configured"))?;
        let payload = serde_json::to_vec(&json!({"purpose":purpose,"value":value}))
            .map_err(|_| Failure("token_encryption_failed"))?;
        Ok(format!(
            "{}:{}:{}",
            self.active,
            key.fingerprint,
            key.cipher.encrypt(&payload)
        ))
    }
    pub fn decrypt(&self, envelope: &str, purpose: &str) -> Result<Value> {
        let invalid = Failure("token_decryption_failed");
        let mut parts = envelope.splitn(3, ':');
        let id = parts.next().ok_or(invalid)?;
        let fingerprint = parts.next().ok_or(invalid)?;
        let ciphertext = parts.next().ok_or(invalid)?;
        let key = self.keys.get(id).ok_or(invalid)?;
        if !bool::from(key.fingerprint.as_bytes().ct_eq(fingerprint.as_bytes())) {
            return Err(invalid);
        }
        let decrypted = key.cipher.decrypt(ciphertext).map_err(|_| invalid)?;
        let payload: Value = serde_json::from_slice(&decrypted).map_err(|_| invalid)?;
        if payload["purpose"] != purpose {
            return Err(invalid);
        }
        payload.get("value").cloned().ok_or(invalid)
    }
}
