//! Durable reconciliation ceilings include lost poll/admission responses, not only reported reads.
use super::storage::*;
use crate::{Failure, Result};
use serde_json::{Value, json};
const ALL: &[&str] = &[
    "reconciliation_attempts",
    "account_recheck_attempts",
    "reconciliation_lease_attempts",
    "account_recheck_lease_attempts",
    "reconciliation_read_admissions",
    "account_recheck_read_admissions",
];
fn count(work: &Value, key: &str) -> Result<i64> {
    work.get(key)
        .map(|v| v.as_i64().filter(|n| *n >= 0).ok_or_else(invalid))
        .transpose()
        .map(|n| n.unwrap_or(0))
}
fn keys(work: &Value) -> Option<(&'static str, &'static str, &'static str)> {
    match work["operation"].as_str() {
        Some("reconcile_application") => Some((ALL[0], ALL[2], ALL[4])),
        Some("verify_account") => Some((ALL[1], ALL[3], ALL[5])),
        _ => None,
    }
}
pub fn exhausted(work: &Value) -> Result<bool> {
    for key in ALL {
        if count(work, key)? >= 3 {
            return Ok(true);
        }
    }
    Ok(false)
}
pub fn claim(work: &mut Value) -> Result<bool> {
    if let Some((_, lease, _)) = keys(work) {
        if exhausted(work)? {
            return Ok(false);
        }
        work[lease] = json!(count(work, lease)?.checked_add(1).ok_or_else(invalid)?);
    }
    Ok(true)
}
pub fn admit(work: &mut Value) -> Result<()> {
    if let Some((reported, _, admitted)) = keys(work) {
        if count(work, reported)?.max(count(work, admitted)?) >= 3 {
            return Err(Failure("bounded_reconciliation_exhausted"));
        }
        work[admitted] = json!(count(work, admitted)?.checked_add(1).ok_or_else(invalid)?);
    }
    Ok(())
}
pub(crate) fn report(work: &mut Value) -> Result<()> {
    if let Some((reported, _, _)) = keys(work) {
        work[reported] = json!(count(work, reported)?.checked_add(1).ok_or_else(invalid)?);
    }
    Ok(())
}
