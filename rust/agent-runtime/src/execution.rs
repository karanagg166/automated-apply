//! Legacy application execution parity. Pure policy/observations confer no browser authority.
pub mod admission;
mod automatic;
mod budgets;
pub mod contracts;
pub mod eligibility;
mod events;
pub mod fences;
pub mod filters;
mod history;
mod notices;
mod preflight;
pub mod preparation;
pub mod profile_sync;
mod questionnaire_context;
pub mod queue;
mod queue_control;
pub mod queue_page;
mod queue_status;
pub mod receipts;
mod storage;
pub mod submission;

use crate::{Failure, Result};
use serde_json::Value;
use sqlx::{Connection, PgConnection};
pub fn denial(error: Failure) -> bool {
    matches!(
        error.0,
        "queue_policy_revision_conflict"
            | "enabled_platform_required"
            | "automatic_first_verified_worker_receipt_required"
            | "approved_naukri_account_binding_required"
            | "naukri_account_binding_context_changed"
    )
}
#[derive(Clone, Copy)]
pub enum Route {
    Queue,
    Account,
    Policy,
    Control,
}
impl Route {
    pub fn method(self) -> &'static str {
        match self {
            Self::Policy => "PUT",
            Self::Control => "POST",
            _ => "GET",
        }
    }
}
pub fn route(path: &str) -> Option<Route> {
    match path {
        "/api/v1/execution/queue" => Some(Route::Queue),
        "/api/v1/execution/naukri/account-binding" => Some(Route::Account),
        "/api/v1/execution/queue/policy" => Some(Route::Policy),
        "/api/v1/execution/queue/control" => Some(Route::Control),
        _ => None,
    }
}
pub async fn dispatch(
    c: &mut PgConnection,
    route: Route,
    method: &str,
    query: Option<&str>,
) -> Result<Value> {
    dispatch_body(c, route, method, query, &[]).await
}
pub async fn dispatch_body(
    c: &mut PgConnection,
    route: Route,
    method: &str,
    query: Option<&str>,
    body: &[u8],
) -> Result<Value> {
    if method != route.method() {
        return Err(Failure("execution_method_not_allowed"));
    }
    let page = if matches!(route, Route::Queue) {
        Some(queue_page::Page::parse(query)?)
    } else {
        if query.is_some() {
            return Err(Failure("invalid_execution_page"));
        }
        None
    };
    let input = match route {
        Route::Policy | Route::Control => Some(contracts::normalize(
            if matches!(route, Route::Policy) {
                contracts::Kind::PolicyUpdate
            } else {
                contracts::Kind::Control
            },
            serde_json::from_slice(body).map_err(|_| Failure("invalid_execution_contract"))?,
        )?),
        _ => None,
    };
    let mut tx = c.begin().await.map_err(storage::db)?;
    let result = async {
        if input.is_some() {
            storage::lock(&mut tx).await?;
        } else {
            sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                .execute(&mut *tx)
                .await
                .map_err(storage::db)?;
        }
        match route {
            Route::Queue => queue_status::listing(&mut tx, page.unwrap()).await,
            Route::Account => queue_status::account(&mut tx).await,
            Route::Policy => {
                let now = storage::now(&mut tx).await?;
                queue_control::configure(&mut tx, input.unwrap(), now).await
            }
            Route::Control => {
                let now = storage::now(&mut tx).await?;
                queue_control::control(&mut tx, input.unwrap(), now).await
            }
        }
    }
    .await;
    match result {
        Ok(value) => {
            tx.commit().await.map_err(|_| {
                Failure(if matches!(route, Route::Policy | Route::Control) {
                    "execution_commit_outcome_unknown"
                } else {
                    "execution_read_commit_failed"
                })
            })?;
            Ok(value)
        }
        Err(error) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("execution_rollback_unconfirmed"))?;
            Err(error)
        }
    }
}
