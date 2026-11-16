//! Owner-confirmed ordinary-profile identity. Contact email never becomes a login identity.
use super::{queue_status, storage::*};
use crate::{Failure, Result};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;
pub(super) async fn approve_in(
    tx: &mut Transaction<'_, Postgres>,
    input: Value,
    now: DateTime<Utc>,
) -> Result<Value> {
    let current = queue_status::account(tx).await?;
    if current["revision"] != input["expected_revision"] {
        return Err(Failure("account_binding_revision_conflict"));
    }
    if input["owner_confirmed"] != true {
        return Err(Failure("owner_account_confirmation_required"));
    }
    let candidate = input["candidate_profile_id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    let binding = input["profile_binding_id"]
        .as_str()
        .and_then(|s| s.parse::<Uuid>().ok())
        .ok_or_else(invalid)?;
    let primary: bool = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM candidate_profiles WHERE id=$1 AND singleton_key='primary')",
    )
    .bind(candidate)
    .fetch_one(&mut **tx)
    .await
    .map_err(db)?;
    let selected = get(tx, "chr_selection")
        .await?
        .unwrap_or(json!({"version":0,"profile_binding_id":null}));
    let chrome = get(tx, &format!("chr_prof:{binding}")).await?;
    if !primary
        || selected["profile_binding_id"] != input["profile_binding_id"]
        || chrome
            .as_ref()
            .is_none_or(|p| p["id"] != input["profile_binding_id"])
    {
        return Err(Failure("account_binding_context_changed"));
    }
    let value = json!({"revision":next(&current)?,"approved":true,"candidate_profile_id":candidate,"profile_binding_id":binding,"account_sha256":input["account_sha256"],"evidence_sha256":input["evidence_sha256"],"source":"owner_confirmed_profile_ui","approved_at":stamp(now)});
    put(tx, "naukri_account_binding", &value).await?;
    Ok(value)
}
