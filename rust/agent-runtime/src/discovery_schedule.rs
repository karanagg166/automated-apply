//! Optional public discovery on the existing execution connection; never submits applications.
use crate::{
    Failure, Result, feed_ingestion,
    lifecycle::{self, Mode},
    public_discovery::{self, Batch, Platform, Reservation},
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection};
use uuid::Uuid;
const KEY: &str = "public_feed_schedule";
#[derive(Clone, Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Policy {
    pub revision: i32,
    pub enabled: Vec<Platform>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Update {
    pub expected_revision: i32,
    pub enabled: Vec<Platform>,
}
fn invalid() -> Failure {
    Failure("invalid_discovery_schedule")
}
fn db(_: sqlx::Error) -> Failure {
    Failure("public_feed_database_error")
}
pub async fn record_status(c: &mut PgConnection, error: Option<Failure>) -> Result<()> {
    let value =
        json!({"error_code":error.map(|e|e.0),"recorded_at":chrono::Utc::now().timestamp()});
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value) VALUES('public_feed_schedule_status',$1) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=clock_timestamp() RETURNING value").bind(&value).fetch_optional(c).await.map_err(db)?;
    if saved != Some(value) {
        return Err(Failure("discovery_schedule_write_ack_failed"));
    }
    Ok(())
}
fn validate(revision: i32, enabled: &[Platform]) -> Result<()> {
    if !(0..i32::MAX).contains(&revision)
        || enabled.len() > 2
        || enabled.len() == 2 && enabled[0].name() == enabled[1].name()
    {
        return Err(invalid());
    }
    Ok(())
}
pub fn request(body: &[u8]) -> Result<Update> {
    let update: Update = serde_json::from_slice(body).map_err(|_| invalid())?;
    validate(update.expected_revision, &update.enabled)?;
    Ok(update)
}
pub async fn policy(c: &mut PgConnection) -> Result<Policy> {
    // Minimal saved-review fixtures have no legacy owner preferences. No schedule
    // can be enabled there; production readiness separately requires its catalog.
    let exists: bool = sqlx::query_scalar("SELECT to_regclass('owner_preferences') IS NOT NULL")
        .fetch_one(&mut *c)
        .await
        .map_err(db)?;
    if !exists {
        return Ok(Policy::default());
    }
    let raw: Option<Value> = sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(KEY)
        .fetch_optional(c)
        .await
        .map_err(db)?;
    let p: Policy = raw
        .map(serde_json::from_value)
        .transpose()
        .map_err(|_| invalid())?
        .unwrap_or_default();
    validate(p.revision, &p.enabled)?;
    Ok(p)
}
pub async fn status(c: &mut PgConnection) -> Result<Value> {
    let p = policy(c).await?;
    let raw: Option<Value> = sqlx::query_scalar(
        "SELECT value FROM owner_preferences WHERE key='public_feed_schedule_status'",
    )
    .fetch_optional(c)
    .await
    .map_err(db)?;
    Ok(
        json!({"policy":p,"last_status":raw,"scope":"public_discovery_only","application_dispatch":false,"tick_interval_seconds":30}),
    )
}
pub async fn update(c: &mut PgConnection, update: Update) -> Result<Policy> {
    validate(update.expected_revision, &update.enabled)?;
    let mut tx = c.begin().await.map_err(db)?;
    sqlx::query("SELECT pg_advisory_xact_lock(166001,51)")
        .execute(&mut *tx)
        .await
        .map_err(db)?;
    let current = policy(&mut tx).await?;
    if current.revision != update.expected_revision {
        return Err(Failure("discovery_schedule_revision_conflict"));
    }
    let next = Policy {
        revision: current
            .revision
            .checked_add(1)
            .filter(|n| *n < i32::MAX)
            .ok_or_else(invalid)?,
        enabled: update.enabled,
    };
    let value = json!(next);
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value) VALUES($1,$2) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=clock_timestamp() RETURNING value").bind(KEY).bind(&value).fetch_optional(&mut *tx).await.map_err(db)?;
    if saved != Some(value) {
        return Err(Failure("discovery_schedule_write_ack_failed"));
    }
    tx.commit()
        .await
        .map_err(|_| Failure("public_feed_commit_outcome_unknown"))?;
    Ok(next)
}
#[allow(async_fn_in_trait)]
pub trait Provider {
    async fn fetch(&mut self, platform: Platform) -> Result<Batch>;
}
async fn authorized(
    c: &mut PgConnection,
    revision: i32,
    control_revision: i64,
    p: Platform,
) -> Result<bool> {
    let current = policy(c).await?;
    let control = lifecycle::control(c).await?;
    Ok(control.mode == Mode::Running
        && control.revision == control_revision
        && current.revision == revision
        && current
            .enabled
            .iter()
            .any(|enabled| enabled.name() == p.name()))
}
pub struct ScheduledFetch {
    pub(crate) platform: Platform,
    token: Uuid,
    record: Value,
    revision: i32,
    control_revision: i64,
}

/// Reserve one fetch before any network work. A cached batch can be ingested here.
pub async fn begin(c: &mut PgConnection) -> Result<Option<ScheduledFetch>> {
    let control = lifecycle::control(c).await?;
    if control.mode != Mode::Running {
        return Ok(None);
    }
    let config = policy(c).await?;
    if config.enabled.is_empty() {
        return Ok(None);
    }
    let last: Option<Value> = sqlx::query_scalar(
        "SELECT value FROM owner_preferences WHERE key='public_feed_schedule_cursor'",
    )
    .fetch_optional(&mut *c)
    .await
    .map_err(db)?;
    let mut enabled = config.enabled.clone();
    if let Some(i) = enabled
        .iter()
        .position(|p| last.as_ref().and_then(|v| v["platform"].as_str()) == Some(p.name()))
    {
        let n = enabled.len();
        enabled.rotate_left((i + 1) % n);
    }
    for platform in enabled {
        let cache: Option<Value> =
            sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
                .bind(format!("public_feed:{}", platform.name()))
                .fetch_optional(&mut *c)
                .await
                .map_err(db)?;
        if let Some(cache) = cache {
            let at = cache["next_allowed_at"]
                .as_i64()
                .ok_or(Failure("public_feed_saved_state_invalid"))?;
            if at > chrono::Utc::now().timestamp() {
                if cache["state"] != "completed" {
                    continue;
                }
                let token: Uuid =
                    serde_json::from_value(cache["token"].clone()).map_err(|_| invalid())?;
                let consumed: bool = sqlx::query_scalar(
                    "SELECT EXISTS(SELECT 1 FROM owner_preferences WHERE key=$1)",
                )
                .bind(feed_ingestion::ledger_key(platform, token))
                .fetch_one(&mut *c)
                .await
                .map_err(db)?;
                if consumed {
                    continue;
                }
            }
        }
        if !authorized(c, config.revision, control.revision, platform).await? {
            return Ok(None);
        }
        // Rotate before dispatch, so one invalid/failed source cannot starve the other.
        let cursor = json!({"platform":platform,"checked_at":chrono::Utc::now().timestamp()});
        let saved:Option<Value>=sqlx::query_scalar("INSERT INTO owner_preferences(key,value) VALUES('public_feed_schedule_cursor',$1) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=clock_timestamp() RETURNING value").bind(&cursor).fetch_optional(&mut *c).await.map_err(db)?;
        if saved != Some(cursor) {
            return Err(Failure("discovery_schedule_write_ack_failed"));
        }
        match public_discovery::reserve(c, platform, 20).await {
            Ok(Reservation::Cached(value)) => {
                let token =
                    serde_json::from_value(value["batch_token"].clone()).map_err(|_| invalid())?;
                ingest(c, platform, token, config.revision, control.revision).await?;
                return Ok(None);
            }
            Ok(Reservation::Fetch { token, record }) => {
                if !authorized(c, config.revision, control.revision, platform).await? {
                    return Ok(None);
                }
                return Ok(Some(ScheduledFetch {
                    platform,
                    token,
                    record,
                    revision: config.revision,
                    control_revision: control.revision,
                }));
            }
            Err(Failure("public_feed_cooldown")) => continue,
            Err(e) => return Err(e),
        }
    }
    Ok(None)
}

async fn ingest(
    c: &mut PgConnection,
    platform: Platform,
    token: Uuid,
    revision: i32,
    control_revision: i64,
) -> Result<()> {
    // The intake transaction holds both revisions through commit.
    match feed_ingestion::ingest_scheduled(
        c,
        platform,
        feed_ingestion::Input { batch_token: token },
        revision,
        control_revision,
    )
    .await
    {
        Ok(_) => record_status(c, None).await,
        Err(Failure("discovery_schedule_changed")) => Ok(()),
        Err(error) => Err(error),
    }
}

pub async fn complete(
    c: &mut PgConnection,
    fetch: ScheduledFetch,
    result: Result<Batch>,
) -> Result<()> {
    let ScheduledFetch {
        platform,
        token,
        record,
        revision,
        control_revision,
    } = fetch;
    match public_discovery::finish(c, platform, token, record, result, 20).await {
        Ok(_) => ingest(c, platform, token, revision, control_revision).await,
        Err(error) if crate::recovery::database_failure(error) => Err(error),
        Err(error) => record_status(c, Some(error)).await,
    }
}

/// The same three phases with an injected provider for a single schedule cycle.
pub async fn tick(c: &mut PgConnection, provider: &mut impl Provider) -> Result<()> {
    let Some(fetch) = begin(c).await? else {
        return Ok(());
    };
    let result = provider.fetch(fetch.platform).await;
    complete(c, fetch, result).await
}
