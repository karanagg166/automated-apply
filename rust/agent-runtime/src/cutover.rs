//! A read-only database observation for the operator's STOP-only installation.
use automated_apply_agents::{Failure, Result, configuration::Configuration, lifecycle, server};
use serde_json::{Value, json};
use sqlx::Connection;
use std::{path::Path, time::Duration};

pub async fn report(path: &Path) -> Result<()> {
    let config = Configuration::load(path)?;
    let checks = tokio::time::timeout(Duration::from_secs(25), observe(&config))
        .await
        .map_err(|_| Failure("cutover_preflight_timeout"))??;
    println!("{checks}");
    Ok(())
}

async fn observe(config: &Configuration) -> Result<Value> {
    let mut connection = config.connect(false).await?;
    let mut tx = connection.begin().await.map_err(database_error)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(database_error)?;
    server::readiness(&mut tx, config).await?;
    let control = lifecycle::control(&mut tx).await?;
    if control.mode != lifecycle::Mode::Stopped {
        return Err(Failure("cutover_stopped_rust_coordinator_required"));
    }

    let controls: Value = sqlx::query_scalar(
        "SELECT coalesce(jsonb_object_agg(key,jsonb_build_object(
            'state', value->'state', 'revision', value->'revision')), '{}'::jsonb)
         FROM owner_preferences WHERE key IN ('application_queue_policy','naukri_automation')",
    )
    .fetch_one(&mut *tx)
    .await
    .map_err(database_error)?;
    let queue_revision = stopped_revision(
        &controls["application_queue_policy"],
        "cutover_stopped_application_queue_required",
    )?;
    let preparation_revision = controls
        .get("naukri_automation")
        .map(|saved| stopped_revision(saved, "cutover_stopped_legacy_preparation_required"))
        .transpose()?;

    let role: (i32, i64) = sqlx::query_as(
        "SELECT rolconnlimit,
            (SELECT count(*) FROM pg_stat_activity
             WHERE usename=current_user AND pid<>pg_backend_pid())
         FROM pg_roles WHERE rolname=current_user",
    )
    .fetch_one(&mut *tx)
    .await
    .map_err(database_error)?;
    tx.rollback().await.map_err(database_error)?;
    connection.close().await.map_err(database_error)?;

    Ok(json!({
        "event": "rust_cutover_preflight",
        "scope": "read_only_database_observation",
        "fixture": config.is_fixture(),
        "rust_control": control,
        "queue_revision": queue_revision,
        "legacy_preparation_revision": preparation_revision,
        "runtime_role_connection_limit": role.0,
        "other_visible_role_sessions": role.1,
        "planned_rust_session_peak": if config.telegram_enabled() { 4 } else { 3 },
    }))
}

fn stopped_revision(saved: &Value, error: &'static str) -> Result<i64> {
    if saved["state"] != "STOPPED" {
        return Err(Failure(error));
    }
    saved["revision"]
        .as_i64()
        .filter(|revision| *revision >= 0)
        .ok_or(Failure(error))
}

fn database_error(_: sqlx::Error) -> Failure {
    Failure("cutover_preflight_database_unavailable")
}
