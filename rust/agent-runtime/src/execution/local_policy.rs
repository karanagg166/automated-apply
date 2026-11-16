//! Saved local preference is an additional restriction, never submission/paid-call authority.
use super::storage::*;
use crate::Result;
use serde_json::Value;
use sqlx::{Postgres, Transaction};
pub(super) async fn preference_in(
    tx: &mut Transaction<'_, Postgres>,
    platform: &str,
) -> Result<&'static str> {
    let saved: Option<Value> =
        sqlx::query_scalar("SELECT preferences FROM agent_policies WHERE key='primary'")
            .fetch_optional(&mut **tx)
            .await
            .map_err(db)?;
    let preference = match &saved {
        Some(saved) => saved["platforms"]
            .as_object()
            .ok_or_else(invalid)?
            .get(platform)
            .unwrap_or(&saved["default"])
            .as_str()
            .ok_or_else(invalid)?,
        None => match platform {
            "naukri" => "automatic_preferred",
            "gmail" => "draft_only",
            "linkedin" => "manual_only",
            _ => "approve",
        },
    };
    Ok(match preference {
        "approve" => "approve",
        "automatic_preferred" => "automatic_preferred",
        "draft_only" => "draft_only",
        "manual_only" => "manual_only",
        "disabled" => "disabled",
        _ => return Err(invalid()),
    })
}
