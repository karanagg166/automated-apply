//! Exact dashboard intent signatures and durable nonce claims. Delegated bearer is insufficient.
use crate::{Failure, Result};
use hmac::{Hmac, KeyInit, Mac};
use sha2::{Digest, Sha256};
use sha2_hmac::Sha256 as HmacSha256;
use sqlx::{Postgres, Transaction};
use std::collections::BTreeMap;
use subtle::ConstantTimeEq;

pub struct SigningKey {
    key: String,
}
/// Constructed only after a valid path/body/time signature. Caller owns the transaction.
pub struct Proof {
    nonce: String,
    operation: String,
}
impl SigningKey {
    pub fn from_values(values: &BTreeMap<String, String>) -> Result<Option<Self>> {
        let Some(key) = values
            .get("BROWSER_OWNER_APPROVAL_KEY")
            .filter(|s| !crate::grounding::trim(s).is_empty())
        else {
            return Ok(None);
        };
        if key.chars().count() < 32
            || values
                .get("JOB_AGENT_API_TOKEN")
                .is_some_and(|token| bool::from(key.as_bytes().ct_eq(token.as_bytes())))
        {
            return Err(Failure("separate_owner_approval_key_required"));
        }
        Ok(Some(Self { key: key.clone() }))
    }
    fn header(&self, path: &str, body: &[u8], nonce: &str, timestamp: u64) -> Result<String> {
        let message = format!(
            "POST\n{path}\n{timestamp}\n{nonce}\n{:x}",
            Sha256::digest(body)
        );
        let mut mac = Hmac::<HmacSha256>::new_from_slice(self.key.as_bytes())
            .map_err(|_| Failure("invalid_owner_approval_key"))?;
        mac.update(message.as_bytes());
        let signature = mac.finalize().into_bytes();
        let mut encoded = String::with_capacity(64);
        for byte in signature.iter() {
            use std::fmt::Write;
            write!(&mut encoded, "{byte:02x}").expect("write to String");
        }
        Ok(format!("v1:{timestamp}:{nonce}:{encoded}"))
    }
    pub fn verify_at(&self, path: &str, body: &[u8], header: &str, now: f64) -> Result<Proof> {
        if header.len() != 111 || body.len() > 65536 {
            return Err(Failure("owner_approval_required"));
        }
        let parts: Vec<_> = header.split(':').collect();
        let hex = |s: &str, len| {
            s.len() == len
                && s.bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        };
        if parts.len() != 4
            || parts[0] != "v1"
            || parts[1].len() != 10
            || !parts[1].bytes().all(|b| b.is_ascii_digit())
            || !hex(parts[2], 32)
            || !hex(parts[3], 64)
        {
            return Err(Failure("owner_approval_required"));
        }
        let timestamp = parts[1]
            .parse::<u64>()
            .map_err(|_| Failure("owner_approval_required"))?;
        if !now.is_finite() || (now - timestamp as f64).abs() > 30.0 {
            return Err(Failure("owner_approval_required"));
        }
        let expected = self.header(path, body, parts[2], timestamp)?;
        if !bool::from(expected.as_bytes().ct_eq(header.as_bytes())) {
            return Err(Failure("owner_approval_operation_mismatch"));
        }
        Ok(Proof {
            nonce: parts[2].into(),
            operation: path.into(),
        })
    }
}
impl Proof {
    /// A failed effect rolls back this claim with the caller's transaction. Committed claims
    /// survive restarts and reject replay of the same exact dashboard proof.
    pub async fn claim(self, transaction: &mut Transaction<'_, Postgres>) -> Result<()> {
        let key = format!("owner-proof:{}", self.nonce);
        let row:Option<String>=sqlx::query_scalar("WITH stamp AS (SELECT clock_timestamp() AS at) INSERT INTO owner_preferences(key,value,created_at,updated_at) SELECT $1,jsonb_build_object('operation',$2::text),at,at FROM stamp ON CONFLICT (key) DO NOTHING RETURNING key")
            .bind(key).bind(self.operation).fetch_optional(&mut **transaction).await.map_err(|_|Failure("profile_database_error"))?;
        if row.is_none() {
            return Err(Failure("owner_approval_already_used"));
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;
    #[test]
    fn dashboard_proof_binds_exact_path_body_nonce_and_time_with_python_hmac_parity() {
        let cases: Vec<Value> =
            serde_json::from_str(include_str!("../tests/fixtures/owner-proof-corpus.json"))
                .unwrap();
        for (i, case) in cases.iter().enumerate() {
            let key = SigningKey::from_values(&BTreeMap::from([(
                "BROWSER_OWNER_APPROVAL_KEY".into(),
                case["key"].as_str().unwrap().into(),
            )]))
            .unwrap()
            .unwrap();
            let path = case["path"].as_str().unwrap();
            let body = case["body"].as_str().unwrap().as_bytes();
            let nonce = case["nonce"].as_str().unwrap();
            let timestamp = case["timestamp"].as_u64().unwrap();
            let header = case["header"].as_str().unwrap();
            assert_eq!(
                key.header(path, body, nonce, timestamp).unwrap(),
                header,
                "case{i}"
            );
            assert!(key.verify_at(path, body, header, timestamp as f64).is_ok());
            assert_eq!(
                key.verify_at("/api/v1/other-operation", body, header, timestamp as f64)
                    .err()
                    .map(|e| e.0),
                Some("owner_approval_operation_mismatch")
            );
            assert_eq!(
                key.verify_at(path, b"changed", header, timestamp as f64)
                    .err()
                    .map(|e| e.0),
                Some("owner_approval_operation_mismatch")
            );
            assert!(
                key.verify_at(path, body, header, timestamp as f64 + 30.0)
                    .is_ok()
            );
            assert!(
                key.verify_at(path, body, header, timestamp as f64 + 30.01)
                    .is_err()
            );
            assert!(
                key.verify_at(path, body, header, timestamp as f64 - 30.01)
                    .is_err()
            );
        }
    }
    #[test]
    fn absent_weak_and_delegated_keys_cannot_be_used_as_owner_signing_keys() {
        assert!(SigningKey::from_values(&BTreeMap::new()).unwrap().is_none());
        assert!(
            SigningKey::from_values(&BTreeMap::from([(
                "BROWSER_OWNER_APPROVAL_KEY".into(),
                " ".into()
            )]))
            .unwrap()
            .is_none()
        );
        for key in [
            "short".to_owned(),
            "fictional-shared-api-token-0123456789".into(),
        ] {
            let values = BTreeMap::from([
                ("BROWSER_OWNER_APPROVAL_KEY".into(), key.clone()),
                ("JOB_AGENT_API_TOKEN".into(), key),
            ]);
            assert!(SigningKey::from_values(&values).is_err());
        }
    }
    #[test]
    fn malformed_and_forged_headers_never_produce_a_nonce_claim() {
        let key = SigningKey::from_values(&BTreeMap::from([(
            "BROWSER_OWNER_APPROVAL_KEY".into(),
            "fictional-owner-signing-key-0123456789".into(),
        )]))
        .unwrap()
        .unwrap();
        let valid = key
            .header(
                "/api/v1/approve",
                b"{}",
                "0123456789abcdef0123456789abcdef",
                1794700000,
            )
            .unwrap();
        for supplied in [
            String::new(),
            valid.replace("v1:", "v2:"),
            valid.replace(
                "0123456789abcdef0123456789abcdef",
                "0123456789ABCDEF0123456789ABCDEF",
            ),
            format!("{valid}:extra"),
            valid[..valid.len() - 1].to_owned(),
            "v1:1794700000:0123456789abcdef0123456789abcdef:".to_owned() + &"0".repeat(64),
        ] {
            assert!(
                key.verify_at("/api/v1/approve", b"{}", &supplied, 1794700000.0)
                    .is_err()
            );
        }
        assert!(
            key.verify_at("/api/v1/approve", b"{}", &valid, f64::NAN)
                .is_err()
        );
        assert!(
            key.verify_at("/api/v1/approve", &vec![0; 65537], &valid, 1794700000.0)
                .is_err()
        );
    }
}
