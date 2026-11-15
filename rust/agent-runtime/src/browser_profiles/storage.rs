use super::*;
pub(super) fn db(_: sqlx::Error) -> Failure {
    Failure("browser_profile_database_error")
}
pub(super) async fn lock(tx: &mut Transaction<'_, Postgres>) -> Result<()> {
    // Lock first when present, matching the legacy order; insert only for first bootstrap.
    let key: Option<String> = sqlx::query_scalar(
        "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
    )
    .fetch_optional(&mut **tx)
    .await
    .map_err(db)?;
    if key.is_none() {
        sqlx::query("INSERT INTO owner_preferences(key,value) VALUES('agent_conversation:primary','{}') ON CONFLICT(key) DO NOTHING").execute(&mut **tx).await.map_err(db)?;
        let _: String = sqlx::query_scalar(
            "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
        )
        .fetch_one(&mut **tx)
        .await
        .map_err(db)?;
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
