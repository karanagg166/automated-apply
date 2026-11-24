use super::*;
pub(super) fn db(_: sqlx::Error) -> Failure {
    Failure("browser_profile_database_error")
}

fn fence_error(error: sqlx::Error, rollback_code: Option<&'static str>) -> Failure {
    let code = error.as_database_error().and_then(|source| source.code());
    if let Some(rollback_code) = rollback_code
        && matches!(code.as_deref(), Some("55P03" | "40001"))
    {
        // The dispatcher propagates this marker only after rollback succeeds.
        return Failure(rollback_code);
    }
    db(error)
}

pub(super) async fn lock(
    tx: &mut Transaction<'_, Postgres>,
    rollback_code: Option<&'static str>,
) -> Result<()> {
    let fence_error = |error| fence_error(error, rollback_code);
    // Lock first when present, matching the legacy order; insert only for first bootstrap.
    let key: Option<String> = sqlx::query_scalar(
        "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
    )
    .fetch_optional(&mut **tx)
    .await
    .map_err(fence_error)?;
    if key.is_none() {
        sqlx::query("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES('agent_conversation:primary','{}',clock_timestamp(),clock_timestamp()) ON CONFLICT(key) DO NOTHING").execute(&mut **tx).await.map_err(fence_error)?;
        let _: String = sqlx::query_scalar(
            "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
        )
        .fetch_one(&mut **tx)
        .await
        .map_err(fence_error)?;
    }
    if !crate::owner_fence::advance_in(tx)
        .await
        .map_err(fence_error)?
    {
        return Err(Failure("browser_profile_write_ack_failed"));
    }
    Ok(())
}
pub(super) async fn now(tx: &mut Transaction<'_, Postgres>) -> Result<DateTime<Utc>> {
    let s: String = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp()) #>> '{}'")
        .fetch_one(&mut **tx)
        .await
        .map_err(db)?;
    timestamp(&json!(s))
}
/// SERIALIZABLE forms may establish their snapshot while waiting for the owner row.
/// Lock the actual authority versions after that wait: a legacy READ COMMITTED Stop,
/// selection/account/policy edit or heartbeat cannot be read silently from an older snapshot.
pub(super) async fn lock_snapshot_scope(
    tx: &mut Transaction<'_, Postgres>,
    rollback_code: Option<&'static str>,
) -> Result<()> {
    let keys:Vec<String>=sqlx::query_scalar("SELECT key FROM owner_preferences WHERE key IN ('application_queue_policy','exec_config:naukri','naukri_automation','naukri_account_binding','phase1_profile_confirmation','chr_selection','chr_fixed_profile','naukri_profile_sync_policy','naukri_extension_maintenance','candidate_configuration_v1') OR starts_with(key,'candidate_project-') OR starts_with(key,'document_project-') OR key='chr_prof:'||(SELECT value->>'profile_binding_id' FROM owner_preferences WHERE key='chr_selection') ORDER BY key LIMIT 10001 FOR UPDATE").fetch_all(&mut **tx).await.map_err(|error| fence_error(error, rollback_code))?;
    if keys.len() > 10000 {
        return Err(Failure("browser_profile_inventory_limit"));
    }
    Ok(())
}
pub(super) async fn get(tx: &mut Transaction<'_, Postgres>, key: &str) -> Result<Option<Value>> {
    sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(key)
        .fetch_optional(&mut **tx)
        .await
        .map_err(db)
}
pub(super) async fn put(
    tx: &mut Transaction<'_, Postgres>,
    key: &str,
    value: &Value,
) -> Result<()> {
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value) VALUES($1,$2) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=clock_timestamp() RETURNING value").bind(key).bind(value).fetch_optional(&mut **tx).await.map_err(db)?;
    if saved.as_ref() != Some(value) {
        return Err(Failure("browser_profile_write_ack_failed"));
    }
    Ok(())
}
pub(super) async fn prefix(
    tx: &mut Transaction<'_, Postgres>,
    prefix: &str,
) -> Result<Vec<(String, Value)>> {
    let rows:Vec<(String,Value)>=sqlx::query_as("SELECT key,value FROM owner_preferences WHERE starts_with(key,$1) ORDER BY created_at,key LIMIT 10001").bind(prefix).fetch_all(&mut **tx).await.map_err(db)?;
    if rows.len() > 10000 {
        return Err(Failure("browser_profile_inventory_limit"));
    }
    Ok(rows)
}
pub(super) async fn selection(tx: &mut Transaction<'_, Postgres>) -> Result<Value> {
    let value = get(tx, "chr_selection")
        .await?
        .unwrap_or_else(|| json!({"version":0,"profile_binding_id":null}));
    number(&value, "version")?;
    if !value["profile_binding_id"].is_null() {
        string(&value, "profile_binding_id")?
            .parse::<Uuid>()
            .map_err(|_| invalid())?;
    }
    Ok(value)
}
pub(super) async fn active_commands(
    tx: &mut Transaction<'_, Postgres>,
    identity: Option<&Value>,
) -> Result<Vec<(String, Value)>> {
    let rows:Vec<(String,Value)>=sqlx::query_as("SELECT key,value FROM owner_preferences WHERE starts_with(key,'chr_cmd:') AND (value->>'state' IS NULL OR value->>'state' NOT IN ('completed','failed','expired','cancelled','outcome_unknown')) AND ($1::jsonb IS NULL OR value->'profile_binding_id'=$1) ORDER BY created_at,key LIMIT 10001").bind(identity).fetch_all(&mut **tx).await.map_err(db)?;
    if rows.len() > 10000 {
        return Err(Failure("browser_profile_inventory_limit"));
    }
    Ok(rows)
}
pub(super) async fn active_tasks(
    tx: &mut Transaction<'_, Postgres>,
    identity: &Value,
) -> Result<Vec<(String, Value)>> {
    let rows:Vec<(String,Value)>=sqlx::query_as("SELECT key,value FROM owner_preferences WHERE starts_with(key,'ext_task:') AND (value->>'state' IS NULL OR value->>'state' NOT IN ('FAILED_FINAL','SUBMISSION_UNKNOWN','SUBMITTED_CONFIRMED')) AND value->'profile_binding_id'=$1 ORDER BY created_at DESC,key LIMIT 10001").bind(identity).fetch_all(&mut **tx).await.map_err(db)?;
    if rows.len() > 10000 {
        return Err(Failure("browser_profile_inventory_limit"));
    }
    Ok(rows)
}
