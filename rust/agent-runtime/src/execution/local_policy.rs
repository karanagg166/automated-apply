//! Saved local preference is an additional restriction, never submission/paid-call authority.
use super::storage::invalid;
use crate::{Failure, Result};
use sqlx::{Postgres, Transaction};
pub(super) async fn preference_in(
    tx: &mut Transaction<'_, Postgres>,
    platform: &str,
) -> Result<&'static str> {
    crate::platform_policy::preference_in(tx, platform)
        .await
        .map_err(|error| match error.0 {
            "platform_policy_database_error" => Failure("execution_database_error"),
            _ => invalid(),
        })
}
