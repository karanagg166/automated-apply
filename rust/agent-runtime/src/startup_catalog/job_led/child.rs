//! Provider-specific original child authority, with one shared startup parent/result lifecycle.
use crate::{
    Failure, Result, apify_jobs,
    job_sources::{self, runs as jobs},
    source_registry::Settings,
};
use chrono::{DateTime, Utc};
use serde_json::Value;
use sqlx::{PgConnection, Postgres, Transaction};
use uuid::Uuid;
pub(super) fn paid(source: &Value) -> bool {
    matches!(source.as_str(), Some("wellfound" | "work_at_a_startup"))
}
fn settings(
    value: Option<&apify_jobs::settings::Settings>,
) -> Result<&apify_jobs::settings::Settings> {
    value.ok_or(Failure("apify_reviewed_execution_route_required"))
}
pub(super) enum Original {
    Public(Box<jobs::Claim>),
    Paid(Box<apify_jobs::runs::Claim>),
}
pub(super) async fn admit(
    tx: &mut Transaction<'_, Postgres>,
    public: &Settings,
    paid_settings: Option<&apify_jobs::settings::Settings>,
    input: Value,
    id: Uuid,
    timeout: f64,
) -> Result<Original> {
    if paid(&input["source"]) {
        return match apify_jobs::runs::admit_in(tx, settings(paid_settings)?, input, id).await? {
            apify_jobs::runs::Admission::Original(claim) => Ok(Original::Paid(claim)),
            _ => Err(Failure("startup_job_led_child_already_claimed")),
        };
    }
    match jobs::admit_in(tx, public, input, id, timeout).await? {
        jobs::Admission::Original(claim) => Ok(Original::Public(claim)),
        _ => Err(Failure("startup_job_led_child_already_claimed")),
    }
}
pub(super) async fn assert_original(
    tx: &mut Transaction<'_, Postgres>,
    paid_settings: Option<&apify_jobs::settings::Settings>,
    child: &Original,
) -> Result<()> {
    match child {
        Original::Public(claim) => jobs::assert_original_in(tx, claim).await,
        Original::Paid(claim) => {
            apify_jobs::runs::assert_original_in(tx, settings(paid_settings)?, claim).await
        }
    }
}
pub(super) async fn scope(
    tx: &mut Transaction<'_, Postgres>,
    source: &Value,
    id: Uuid,
) -> Result<Value> {
    if paid(source) {
        apify_jobs::runs::scope_in(tx, id).await
    } else {
        jobs::scope_in(tx, id).await
    }
}
pub(super) async fn read_in(
    tx: &mut Transaction<'_, Postgres>,
    source: &Value,
    id: Uuid,
    at: DateTime<Utc>,
) -> Result<Value> {
    if paid(source) {
        apify_jobs::runs::read_in(tx, id, at).await
    } else {
        jobs::read_in(tx, id, at).await
    }
}
pub(super) async fn read(c: &mut PgConnection, source: &Value, id: Uuid) -> Result<Value> {
    if paid(source) {
        apify_jobs::runs::read(c, id).await
    } else {
        jobs::read(c, id).await
    }
}
pub(super) async fn receipt(
    tx: &mut Transaction<'_, Postgres>,
    source: &Value,
    id: Uuid,
) -> Result<Option<Value>> {
    if paid(source) {
        apify_jobs::runs::local_receipt_in(tx, id).await
    } else {
        jobs::local_receipt_in(tx, id).await
    }
}
pub(super) async fn finish(
    c: &mut PgConnection,
    public: &Settings,
    paid_settings: Option<&apify_jobs::settings::Settings>,
    source: &Value,
    id: Uuid,
) -> Result<Value> {
    if paid(source) {
        apify_jobs::runs::finish(c, settings(paid_settings)?, id).await
    } else {
        jobs::finish(c, public, id).await
    }
}
pub(super) async fn acquire(
    c: &mut PgConnection,
    paid_settings: Option<&apify_jobs::settings::Settings>,
    paid_client: Option<&apify_jobs::transport::Client>,
    public_client: &job_sources::transport::Client,
    child: Original,
) -> Result<()> {
    match child {
        Original::Public(claim) => {
            jobs::acquire_original(c, public_client, *claim).await?;
        }
        Original::Paid(claim) => {
            apify_jobs::runs::Service {
                settings: settings(paid_settings)?,
                client: paid_client.ok_or(Failure("apify_local_token_not_configured"))?,
            }
            .acquire_original(c, *claim)
            .await?;
        }
    }
    Ok(())
}
