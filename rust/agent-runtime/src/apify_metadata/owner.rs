//! Durable metadata pacing/cache. No actor dispatch, credit reservation or application work.
use super::transport::Client;
use crate::{Failure, Result, source_registry::Settings};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
const CACHE: &str = "rust_apify_capabilities";
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Route {
    Status,
    Account,
    Actor,
}
pub fn route(path: &str) -> Option<Route> {
    match path {
        "/api/v1/integrations/providers/apify" => Some(Route::Status),
        "/api/v1/integrations/providers/apify/inspect" => Some(Route::Account),
        "/api/v1/integrations/providers/apify/actors/inspect" => Some(Route::Actor),
        _ => None,
    }
}
impl Route {
    pub fn method(self) -> &'static str {
        if self == Self::Status { "GET" } else { "POST" }
    }
}
fn db(_: sqlx::Error) -> Failure {
    Failure("apify_metadata_database_error")
}
fn ack() -> Failure {
    Failure("apify_metadata_write_ack_failed")
}
struct Claim {
    next: DateTime<Utc>,
    context: String,
}
async fn tx(c: &mut PgConnection) -> Result<Transaction<'_, Postgres>> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    crate::execution::lock_owner_in(&mut tx).await?;
    Ok(tx)
}
async fn claim(c: &mut PgConnection, client: &Client) -> Result<Claim> {
    let mut tx = tx(c).await?;
    let next:Option<DateTime<Utc>>=sqlx::query_scalar("INSERT INTO provider_access_windows(provider,next_allowed_at) VALUES('apify_metadata',clock_timestamp()+interval '10 seconds') ON CONFLICT(provider) DO UPDATE SET next_allowed_at=EXCLUDED.next_allowed_at WHERE provider_access_windows.next_allowed_at<=clock_timestamp() RETURNING next_allowed_at").fetch_optional(&mut *tx).await.map_err(db)?;
    let next = next.ok_or(Failure("apify_metadata_access_rate_limited"))?;
    let saved: Option<DateTime<Utc>> = sqlx::query_scalar(
        "SELECT next_allowed_at FROM provider_access_windows WHERE provider='apify_metadata'",
    )
    .fetch_optional(&mut *tx)
    .await
    .map_err(db)?;
    if saved != Some(next) {
        return Err(ack());
    }
    tx.commit()
        .await
        .map_err(|_| Failure("apify_metadata_claim_outcome_unknown"))?;
    Ok(Claim {
        next,
        context: client.context(),
    })
}
fn cached(value: &Value, now: DateTime<Utc>) -> Result<Value> {
    if value["provider"] != "apify"
        || value["transport"] != "official_api"
        || value["authenticated"] != true
        || value["execution_authorized"] != false
    {
        return Err(Failure("apify_metadata_cache_invalid"));
    }
    let at = value["observed_at"]
        .as_str()
        .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
        .map(|v| v.to_utc())
        .filter(|at| *at <= now)
        .ok_or(Failure("apify_metadata_cache_invalid"))?;
    super::account(
        &json!({"data":value["limits"]}),
        &json!({"data":value["usage"]}),
        at,
    )
}
async fn cache(c: &mut PgConnection, claim: Claim, result: &Value) -> Result<()> {
    let mut tx = tx(c).await?;
    let current: Option<DateTime<Utc>> = sqlx::query_scalar(
        "SELECT next_allowed_at FROM provider_access_windows WHERE provider='apify_metadata'",
    )
    .fetch_optional(&mut *tx)
    .await
    .map_err(db)?;
    if current != Some(claim.next) {
        return Err(Failure("apify_metadata_inspection_superseded"));
    }
    let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let selected = cached(result, now)?;
    let value = json!({"schema":1,"configuration_hash":claim.context,"inspection":selected,"content_hash":crate::python_json::digest(&selected)});
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value) VALUES($1,$2) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=clock_timestamp() RETURNING value").bind(CACHE).bind(&value).fetch_optional(&mut *tx).await.map_err(db)?;
    if saved.as_ref() != Some(&value) {
        return Err(ack());
    }
    let retained: Option<Value> =
        sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
            .bind(CACHE)
            .fetch_optional(&mut *tx)
            .await
            .map_err(db)?;
    let pace: Option<DateTime<Utc>> = sqlx::query_scalar(
        "SELECT next_allowed_at FROM provider_access_windows WHERE provider='apify_metadata'",
    )
    .fetch_optional(&mut *tx)
    .await
    .map_err(db)?;
    if retained.as_ref() != Some(&value) || pace != Some(claim.next) {
        return Err(ack());
    }
    tx.commit()
        .await
        .map_err(|_| Failure("apify_metadata_cache_outcome_unknown"))?;
    Ok(())
}
pub async fn inspect(
    c: &mut PgConnection,
    settings: &Settings,
    client: &Client,
    actor: Option<&str>,
) -> Result<Value> {
    if let Some(actor) = actor {
        crate::apify_config::safe_actor(actor)?;
        if !settings.actor_metadata_allowed(actor) {
            return Err(Failure("apify_actor_metadata_not_allowlisted"));
        }
    } else if !client.token_configured() {
        return Err(Failure("apify_local_token_not_configured"));
    }
    let original = claim(c, client).await?;
    if let Some(actor) = actor {
        return client.actor(actor).await;
    }
    let result = client.account().await?;
    cache(c, original, &result).await?;
    Ok(result)
}
pub async fn status(c: &mut PgConnection, settings: &Settings, client: &Client) -> Result<Value> {
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let now: DateTime<Utc> = sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(&mut *tx)
        .await
        .map_err(db)?;
    let mut out = settings.apify_settings(now);
    let month = now.format("%Y-%m").to_string();
    let reserved: Option<String> = sqlx::query_scalar(
        "SELECT reserved::text FROM discovery_monthly_budgets WHERE provider='apify' AND month=$1",
    )
    .bind(&month)
    .fetch_optional(&mut *tx)
    .await
    .map_err(db)?;
    let reserved = reserved
        .map(|v| {
            v.parse::<f64>()
                .ok()
                .filter(|n| n.is_finite() && *n >= 0.0)
                .ok_or(Failure("apify_metadata_budget_invalid"))
        })
        .transpose()?
        .unwrap_or(0.0);
    let stored:Option<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(value::text)<=1048576 THEN value ELSE NULL END FROM owner_preferences WHERE key=$1").bind(CACHE).fetch_optional(&mut *tx).await.map_err(db)?;
    let (result, cache_state) = if let Some(Some(saved)) = stored.as_ref() {
        if saved["schema"] != 1
            || saved["content_hash"] != crate::python_json::digest(&saved["inspection"])
        {
            (None, "invalid")
        } else if saved["configuration_hash"] != client.context() {
            (None, "configuration_changed")
        } else {
            match cached(&saved["inspection"], now) {
                Ok(v) => (Some(v), "saved"),
                Err(_) => (None, "invalid"),
            }
        }
    } else if stored.is_some() {
        (None, "invalid")
    } else {
        let old:Option<Option<Value>>=sqlx::query_scalar("SELECT CASE WHEN octet_length(value::text)<=1048576 THEN value ELSE NULL END FROM owner_preferences WHERE key='apify_capabilities'").fetch_optional(&mut *tx).await.map_err(db)?;
        match old {
            Some(Some(v)) => match cached(&v, now) {
                Ok(v) => (Some(v), "legacy_context_unverified"),
                Err(_) => (None, "invalid"),
            },
            Some(None) => (None, "invalid"),
            None => (None, "not_inspected"),
        }
    };
    let age = result
        .as_ref()
        .and_then(|r| r["observed_at"].as_str())
        .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
        .map(|at| (now - at.to_utc()).num_seconds());
    out["last_account_inspection"] = result.unwrap_or(Value::Null);
    out["inspection_cache_state"] = json!(cache_state);
    out["inspection_age_seconds"] = json!(age);
    out["inspection_stale"] = json!(age.is_none_or(|age| age > 86400));
    out["live_verified"] = json!(false);
    out["provider_calls_performed_by_read"] = json!(0);
    let monthly = out["monthly_limit_usd"].as_f64().unwrap_or(0.0);
    out["local_budget"] = json!({"month":month,"reserved_usd":reserved,"remaining_local_usd":(monthly-reserved).max(0.0),"accounting":"local_reservations_not_provider_credit"});
    tx.commit().await.map_err(db)?;
    Ok(out)
}
