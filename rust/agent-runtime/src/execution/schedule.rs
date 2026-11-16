//! Existing execution connection drives local intake/filter/preparation; never network or model IO.
use super::{preparation, reconsideration, storage::*};
use crate::{Failure, Result, configuration::Configuration};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection};
pub(crate) async fn record(
    c: &mut PgConnection,
    key: &str,
    error: Option<Failure>,
    data: Option<Value>,
) -> Result<()> {
    if !matches!(key, "apply_schedule:naukri" | "apply_generation:naukri") {
        return Err(invalid());
    }
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
        lock(&mut tx).await?;
        let now = now(&mut tx).await?;
        let value = json!({"at":stamp(now),"last_error":error.map(|e|e.0),"data":data});
        put(&mut tx, key, &value).await
    }
    .await;
    match result {
        Ok(()) => tx
            .commit()
            .await
            .map_err(|_| Failure("execution_commit_outcome_unknown")),
        Err(e) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            Err(e)
        }
    }
}
pub(crate) async fn tick(c: &mut PgConnection, config: &Configuration) -> Result<bool> {
    let retained = crate::gmail_history::maintenance(c).await?;
    let indexed = super::retained_index::tick(c).await?;
    let legacy = super::legacy_worker::tick(c, config).await?;
    let metadata:Value=sqlx::query_scalar("SELECT jsonb_build_object('running',EXISTS(SELECT 1 FROM owner_preferences WHERE key='application_queue_policy' AND value->>'state'='RUNNING' AND value#>>'{policy,platforms,naukri,enabled}'='true'),'last',(SELECT value FROM owner_preferences WHERE key='apply_schedule:naukri'),'at',clock_timestamp())").fetch_one(&mut *c).await.map_err(db)?;
    if metadata["running"] != true {
        return Ok(legacy || indexed > 0 || retained > 0);
    }
    let seeded = preparation::seed_saved_sources(c).await?;
    let rechecked = reconsideration::tick(c).await?;
    let prepared = preparation::prepare_one(
        c,
        preparation::Services {
            packets: &config.packets,
            answers: &config.answers,
            resumes: &config.resumes,
        },
    )
    .await?;
    let now = timestamp(&metadata["at"])?;
    let due = timestamp(&metadata["last"]["at"])
        .ok()
        .is_none_or(|at| at > now || now - at >= chrono::Duration::seconds(30));
    if seeded > 0 || rechecked || prepared || due {
        record(c,"apply_schedule:naukri",None,Some(json!({"saved_sources_added":seeded,"filter_recheck_changed":rechecked,"prepared":prepared,"provider_calls":0,"application_dispatch":false}))).await?;
    }
    Ok(legacy || indexed > 0 || retained > 0 || seeded > 0 || rechecked || prepared)
}
pub(crate) async fn pause(c: &mut PgConnection) -> Result<()> {
    let running:bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM owner_preferences WHERE key IN ('application_queue_policy','naukri_automation') AND value->>'state'='RUNNING')").fetch_one(&mut *c).await.map_err(db)?;
    if !running {
        return Ok(());
    }
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
        sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            .execute(&mut *tx)
            .await
            .map_err(db)?;
        lock(&mut tx).await?;
        let config = super::queue_control::configuration(&mut tx).await?;
        if config["state"] == "RUNNING" {
            let now = now(&mut tx).await?;
            super::queue_control::control(
                &mut tx,
                json!({"action":"pause","expected_revision":config["revision"]}),
                now,
            )
            .await?;
        }
        let legacy = super::legacy_policy::record(&mut tx).await?;
        if legacy["state"] == "RUNNING" {
            let now = now(&mut tx).await?;
            super::legacy_policy::control_in(
                &mut tx,
                json!({"action":"pause","expected_revision":legacy["revision"]}),
                now,
            )
            .await?;
        }
        Ok(())
    }
    .await;
    match result {
        Ok(()) => tx
            .commit()
            .await
            .map_err(|_| Failure("execution_commit_outcome_unknown")),
        Err(e) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            Err(e)
        }
    }
}
