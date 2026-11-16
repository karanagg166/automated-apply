//! Current-account strict worker proof. Operator receipts and damaged keys never enable AUTO.
use super::{receipts, storage::*};
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;

pub(super) async fn account(tx: &mut Transaction<'_, Postgres>) -> Result<Value> {
    let account = get(tx, "naukri_account_binding")
        .await?
        .ok_or(Failure("approved_naukri_account_binding_required"))?;
    if account["approved"] != true {
        return Err(Failure("approved_naukri_account_binding_required"));
    }
    revision(&account)?;
    for key in ["candidate_profile_id", "profile_binding_id"] {
        account[key]
            .as_str()
            .and_then(|s| s.parse::<Uuid>().ok())
            .ok_or_else(invalid)?;
    }
    let selected = get(tx, "chr_selection")
        .await?
        .unwrap_or(json!({"version":0,"profile_binding_id":null}));
    if account["profile_binding_id"] != selected["profile_binding_id"] {
        return Err(Failure("naukri_account_binding_context_changed"));
    }
    Ok(account)
}
pub(super) async fn require_policy(
    tx: &mut Transaction<'_, Postgres>,
    policy: &Value,
    now: DateTime<Utc>,
) -> Result<()> {
    let setting = &policy["platforms"]["naukri"];
    if setting["enabled"] != true
        || setting["mode"] != "AUTOMATIC"
        || setting["owner_submission_authorized"] != true
    {
        return Ok(());
    }
    let account = account(tx).await?;
    // Bounded keyset batches: retained history must not become a capped inventory or one huge payload.
    let mut cursor: Option<(DateTime<Utc>, String)> = None;
    loop {
        let rows:Vec<(String,Value,Value,DateTime<Utc>)>=sqlx::query_as("SELECT r.key,r.value,w.value,r.created_at FROM owner_preferences r JOIN owner_preferences w ON w.key='apply_work:'||(r.value->>'queue_id') WHERE starts_with(r.key,'naukri_worker_receipt:') AND r.value->'account_sha256'=$1 AND r.value->'worker_dispatched'='true'::jsonb AND w.value->>'stage'='SUBMITTED_CONFIRMED' AND ($2::timestamptz IS NULL OR r.created_at<$2 OR (r.created_at=$2 AND r.key>$3)) ORDER BY r.created_at DESC,r.key LIMIT 10").bind(&account["account_sha256"]).bind(cursor.as_ref().map(|c|c.0)).bind(cursor.as_ref().map(|c|c.1.as_str())).fetch_all(&mut **tx).await.map_err(db)?;
        if rows.is_empty() {
            return Err(Failure("automatic_first_verified_worker_receipt_required"));
        }
        for (key, receipt, work, created) in rows {
            if receipts::first_worker_bound(&key, &receipt, &work, &account, now) {
                return Ok(());
            }
            cursor = Some((created, key));
        }
    }
}
