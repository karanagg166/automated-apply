//! Narrow saved-platform reads and fixed, durable owner notifications for MCP clients.
use crate::{Failure, Result, configuration::Configuration, knowledge, lifecycle, telegram};
use serde::Deserialize;
use serde_json::{Value, json};
use sqlx::PgConnection;
use uuid::Uuid;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Search {
    limit: u8,
}
pub async fn route(
    config: &Configuration,
    connection: &mut PgConnection,
    method: &str,
    parts: &[&str],
    body: &[u8],
) -> Option<Result<Value>> {
    Some(match (method, parts) {
        ("GET", ["api", "v1", "rust-agent", "browser"]) => Ok(config.browser.inventory()),
        (
            "POST",
            [
                "api",
                "v1",
                "rust-agent",
                "platforms",
                platform,
                "saved-jobs",
            ],
        ) => search(connection, platform, body).await,
        ("GET", ["api", "v1", "rust-agent", "application-history"]) => history(connection).await,
        ("GET", ["api", "v1", "rust-agent", "telegram"]) => Ok(
            json!({"enabled":config.telegram_enabled(),"recipient":"configured_owner_only","arbitrary_text":false,"unknown_send_replay":false}),
        ),
        ("POST", ["api", "v1", "rust-agent", "runs", id, "notify-telegram"]) => {
            notify(connection, config, id, body).await
        }
        _ => return None,
    })
}
async fn search(connection: &mut PgConnection, platform: &str, body: &[u8]) -> Result<Value> {
    if !matches!(platform, "naukri" | "instahyre") {
        return Err(Failure("unsupported_job_platform"));
    }
    let input: Search =
        serde_json::from_slice(body).map_err(|_| Failure("invalid_tool_arguments"))?;
    if !(1..=50).contains(&input.limit) {
        return Err(Failure("invalid_tool_arguments"));
    }
    let rows:Vec<Value>=sqlx::query_scalar("SELECT jsonb_build_object('id',id,'title',left(title,255),'job_url',left(job_url,2048),'source_platform',source_platform,'status',status,'source_verification_status',source_verification_status) FROM jobs WHERE source_platform=$1 ORDER BY created_at DESC,id LIMIT $2")
        .bind(platform).bind(i64::from(input.limit)).fetch_all(connection).await.map_err(|_|Failure("saved_jobs_database_error"))?;
    Ok(
        json!({"platform":platform,"jobs":rows,"scope":"saved_only_not_live_verified","application_dispatch":false}),
    )
}
async fn history(connection: &mut PgConnection) -> Result<Value> {
    let profile = knowledge::reviewed_profile(connection)
        .await?
        .ok_or(Failure("profile_review_required"))?;
    knowledge::application_history(connection, &profile.pin).await
}
async fn notify(
    connection: &mut PgConnection,
    config: &Configuration,
    id: &str,
    body: &[u8],
) -> Result<Value> {
    let input: Value =
        serde_json::from_slice(body).map_err(|_| Failure("invalid_tool_arguments"))?;
    if input != json!({}) {
        return Err(Failure("invalid_tool_arguments"));
    }
    let id: Uuid = id.parse().map_err(|_| Failure("invalid_tool_arguments"))?;
    let settings = config
        .telegram
        .as_ref()
        .ok_or(Failure("telegram_adapter_not_enabled"))?;
    lifecycle::load(connection, id).await?;
    // Stable per-run effect ID: repeated MCP calls neither resend unknown outcomes
    // nor create another outbox row. The relay alone performs the actual send.
    let effect = Uuid::new_v5(&id, b"owner-mcp-notice-v1");
    telegram::enqueue(
        connection,
        settings,
        effect,
        telegram::Notice::AgentUpdate { id },
    )
    .await?;
    Ok(
        json!({"queued":true,"run_id":id,"effect_id":effect,"delivery":"durable_outbox_not_a_send_receipt"}),
    )
}
