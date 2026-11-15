use super::*;
pub(super) fn db(_: sqlx::Error) -> Failure {
    Failure("gmail_account_database_error")
}
pub(super) async fn lock(c: &mut PgConnection) -> Result<()> {
    sqlx::query("SELECT pg_advisory_xact_lock(407054,1)")
        .execute(c)
        .await
        .map_err(db)?;
    Ok(())
}
pub(super) async fn read(c: &mut PgConnection, key: &str, locked: bool) -> Result<Option<Value>> {
    let query = if locked {
        "SELECT value FROM owner_preferences WHERE key=$1 FOR UPDATE"
    } else {
        "SELECT value FROM owner_preferences WHERE key=$1"
    };
    let value: Option<Value> = sqlx::query_scalar(query)
        .bind(key)
        .fetch_optional(c)
        .await
        .map_err(db)?;
    if value.as_ref().is_some_and(|v| !v.is_object()) {
        return Err(Failure("invalid_gmail_account_record"));
    }
    Ok(value)
}
pub(super) async fn put(c: &mut PgConnection, key: &str, value: &Value) -> Result<()> {
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value,created_at,updated_at) VALUES($1,$2,clock_timestamp(),clock_timestamp()) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=clock_timestamp() RETURNING value").bind(key).bind(value).fetch_optional(c).await.map_err(db)?;
    if saved.as_ref() != Some(value) {
        return Err(Failure("gmail_account_write_ack_failed"));
    }
    Ok(())
}
pub(super) async fn commit(tx: sqlx::Transaction<'_, sqlx::Postgres>) -> Result<()> {
    tx.commit()
        .await
        .map_err(|_| Failure("gmail_account_commit_outcome_unknown"))
}
