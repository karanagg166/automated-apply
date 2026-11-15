//! Existing private notification inbox and delivery history; never schedules or sends.
use crate::{Failure, Result};
use serde_json::{Value, json};
use sqlx::PgConnection;
use uuid::Uuid;

pub(crate) const INBOX: &str = "/api/v1/dashboard/notifications";
const HISTORY: &str = "/api/v1/dashboard/notification-delivery-history";
pub(crate) enum Route<'a> {
    Inbox,
    History,
    Read(&'a str),
}
pub(crate) fn route(path: &str) -> Option<Route<'_>> {
    match path {
        INBOX => Some(Route::Inbox),
        HISTORY => Some(Route::History),
        _ => path
            .strip_prefix(INBOX)?
            .strip_prefix('/')?
            .strip_suffix("/read")
            .filter(|id| !id.is_empty() && !id.contains('/'))
            .map(Route::Read),
    }
}
fn db(_: sqlx::Error) -> Failure {
    Failure("profile_database_error")
}
pub(crate) async fn dispatch(
    connection: &mut PgConnection,
    method: &str,
    path: &str,
    offset: i64,
) -> Result<Value> {
    match route(path) {
        Some(Route::Inbox) if method == "GET" => inbox(connection, offset).await,
        Some(Route::History) if method == "GET" => history(connection).await,
        Some(Route::Read(id)) if method == "POST" => {
            let id = id
                .parse::<Uuid>()
                .map_err(|_| Failure("invalid_notification_id"))?;
            let changed=sqlx::query("UPDATE owner_notifications SET read_at=statement_timestamp(),updated_at=statement_timestamp() WHERE id=$1").bind(id).execute(connection).await.map_err(db)?.rows_affected();
            if changed == 0 {
                return Err(Failure("notification_not_found"));
            }
            // One autocommitted statement finishes before ACK; no delivery/history write.
            Ok(json!({"read":true}))
        }
        Some(Route::Read(_)) => Err(Failure("match_method_not_allowed")),
        Some(_) => Err(Failure("resource_read_method_not_allowed")),
        None => Err(Failure("owner_route_not_found")),
    }
}
async fn inbox(connection: &mut PgConnection, offset: i64) -> Result<Value> {
    if !(0..=100000).contains(&offset) {
        return Err(Failure("invalid_resource_page"));
    }
    // Guard corrupt oversized TEXT before the driver materializes it. Normal legacy
    // messages are unchanged; no truncation or deletion is performed.
    let rows:Vec<Value>=sqlx::query_scalar("SELECT jsonb_build_object('id',id,'kind',kind,'title',title,'body',CASE WHEN octet_length(body)<=65536 THEN body ELSE NULL END,'href',href,'read_at',read_at,'created_at',created_at) FROM owner_notifications ORDER BY created_at DESC,id OFFSET $1 LIMIT 50").bind(offset).fetch_all(connection).await.map_err(db)?;
    if rows.iter().any(|v| !v["body"].is_string()) {
        return Err(Failure("invalid_notification_record"));
    }
    let value = json!(rows);
    if value.to_string().len() > 524288 {
        return Err(Failure("invalid_notification_record"));
    }
    Ok(value)
}
async fn history(connection: &mut PgConnection) -> Result<Value> {
    let rows:Vec<Value>=sqlx::query_scalar("SELECT jsonb_build_object('id',id,'channel',channel,'status',status,'attempt_count',attempt_count,'last_error',last_error,'next_attempt_at',next_attempt_at,'created_at',created_at) FROM notification_deliveries ORDER BY created_at DESC,id LIMIT 100").fetch_all(connection).await.map_err(db)?;
    Ok(json!({"attempts":rows,"external_delivery_enabled":false}))
}
