//! Grounded local outreach draft review. No sending or provider delivery authority.
pub mod context;
pub mod contract;
pub mod drafts;
pub mod history;
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection};
use uuid::Uuid;
pub struct Settings {
    pub interrupted_after_millis: i64,
}
impl Settings {
    pub fn from_values(values: &std::collections::BTreeMap<String, String>) -> Result<Self> {
        let timeout = values
            .get("GMAIL_SEND_TIMEOUT_SECONDS")
            .map(String::as_str)
            .unwrap_or("20")
            .parse::<f64>()
            .ok()
            .filter(|s| s.is_finite() && (1.0..=60.0).contains(s))
            .ok_or(Failure("invalid_outreach_settings"))?;
        Ok(Self {
            interrupted_after_millis: ((2.0 * timeout + 60.0) * 1000.0).ceil() as i64,
        })
    }
}
fn db(_: sqlx::Error) -> Failure {
    Failure("outreach_database_error")
}
fn invalid() -> Failure {
    Failure("invalid_outreach_saved_record")
}
pub fn fingerprint(value: &Value) -> String {
    use sha2::{Digest, Sha256};
    format!(
        "{:x}",
        Sha256::digest(crate::python_json::serialize(value, false, false).as_bytes())
    )
}
pub fn line(value: &str) -> String {
    value
        .split(crate::context_contract::python_space)
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}
