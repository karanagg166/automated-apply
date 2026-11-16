//! Existing execution connection services explicit legacy preparation. No browser/provider IO.
use super::{legacy_prepare, legacy_schedule, legacy_work, storage::*};
use crate::{Failure, Result, configuration::Configuration};
use serde_json::Value;
use sqlx::PgConnection;
pub async fn tick(c: &mut PgConnection, config: &Configuration) -> Result<bool> {
    // Health is an observation, not authority: no owner lock or permission mutation.
    let heartbeat:Value=sqlx::query_scalar("SELECT jsonb_build_object('at',clock_timestamp(),'last',(SELECT value FROM owner_preferences WHERE key='naukri_worker_health'))").fetch_one(&mut *c).await.map_err(db)?;
    let at = timestamp(&heartbeat["at"])?;
    let due = timestamp(&heartbeat["last"]["heartbeat_at"])
        .ok()
        .is_none_or(|last| last > at || at - last >= chrono::Duration::seconds(10));
    if due {
        let saved:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value) VALUES('naukri_worker_health',jsonb_build_object('heartbeat_at',$1::text)) ON CONFLICT(key) DO UPDATE SET value=excluded.value RETURNING value").bind(stamp(at)).fetch_optional(&mut *c).await.map_err(db)?;
        if saved
            .as_ref()
            .is_none_or(|v| v["heartbeat_at"] != stamp(at))
        {
            return Err(Failure("execution_write_ack_failed"));
        }
    }
    let scheduled = legacy_schedule::tick(c, config).await?;
    let Some(claim) = legacy_work::claim(c).await? else {
        return Ok(scheduled);
    };
    match legacy_prepare::prepare(c, claim, config).await {
        Ok(()) => Ok(true),
        Err(Failure("execution_lease_lost" | "automation_authority_lost")) => Ok(scheduled),
        Err(error)
            if crate::recovery::database_failure(error)
                || matches!(
                    error.0,
                    "execution_commit_outcome_unknown"
                        | "execution_write_ack_failed"
                        | "packet_write_ack_failed"
                        | "execution_rollback_unconfirmed"
                ) =>
        {
            Err(error)
        }
        Err(error) => {
            legacy_work::failed(c, claim).await?;
            Err(error)
        }
    }
}
