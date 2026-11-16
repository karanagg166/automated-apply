//! Advance the existing lock row's MVCC version without changing private conversation JSON.
//! A waiter with an older repeatable snapshot must fail even when a control row was newly
//! inserted and was therefore invisible in that snapshot. Caller already holds the row lock.
use sqlx::{Postgres, Transaction};
pub(crate) async fn advance_in(
    tx: &mut Transaction<'_, Postgres>,
) -> std::result::Result<bool, sqlx::Error> {
    let ack:Option<String>=sqlx::query_scalar("UPDATE owner_preferences SET updated_at=clock_timestamp() WHERE key='agent_conversation:primary' RETURNING key").fetch_optional(&mut **tx).await?;
    Ok(ack.as_deref() == Some("agent_conversation:primary"))
}
