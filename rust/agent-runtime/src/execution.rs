//! Legacy application execution parity. Pure policy/observations confer no browser authority.
mod account;
pub mod admission;
mod applicant_notices;
mod automatic;
pub(crate) mod broker;
mod budgets;
pub mod contracts;
pub mod discovery_observation;
pub mod eligibility;
mod events;
pub mod fences;
pub mod filters;
mod form_loss;
mod history;
pub mod intake;
pub mod listing_ingestion;
mod local_policy;
mod notices;
pub mod owner_questions;
mod preflight;
pub mod preparation;
pub mod profile_sync;
mod profile_sync_notices;
mod profile_sync_policy;
pub mod profile_sync_work;
pub mod question_answers;
mod questionnaire_answer_context;
mod questionnaire_context;
pub mod questionnaire_preparation;
pub mod questionnaire_steps;
pub mod questionnaires;
pub mod queue;
mod queue_control;
pub mod queue_page;
mod queue_status;
pub mod read_bounds;
pub mod receipts;
pub mod reconsideration;
pub(crate) mod schedule;
pub mod search;
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
            | "account_binding_revision_conflict"
            | "owner_account_confirmation_required"
            | "account_binding_context_changed"
            | "profile_sync_revision_conflict"
            | "current_confirmed_profile_version_required"
            | "profile_sync_in_progress_reconcile_before_change"
    )
}
#[derive(Clone, Copy)]
pub enum Route {
    Queue,
    Account,
    AccountApproval,
    SyncStatus,
    SyncPolicy,
    Policy,
    Control,
}
impl Route {
    pub fn method(self) -> &'static str {
        match self {
            Self::Policy | Self::AccountApproval | Self::SyncPolicy => "PUT",
            Self::Control => "POST",
            _ => "GET",
        }
    }
    pub fn for_method(self, method: &str) -> Self {
        if matches!(self, Self::Account) && method == "PUT" {
            Self::AccountApproval
        } else {
            self
        }
    }
    pub fn allow(self) -> &'static str {
        if matches!(self, Self::Account | Self::AccountApproval) {
            "GET, PUT"
        } else {
            self.method()
        }
    }
}
pub fn route(path: &str) -> Option<Route> {
    match path {
        "/api/v1/execution/queue" => Some(Route::Queue),
        "/api/v1/execution/naukri/account-binding" => Some(Route::Account),
        "/api/v1/execution/naukri/profile-sync" => Some(Route::SyncStatus),
        "/api/v1/execution/naukri/profile-sync/policy" => Some(Route::SyncPolicy),
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
    let route = route.for_method(method);
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
        Route::Policy | Route::Control | Route::AccountApproval | Route::SyncPolicy => {
            Some(contracts::normalize(
                match route {
                    Route::Policy => contracts::Kind::PolicyUpdate,
                    Route::Control => contracts::Kind::Control,
                    Route::AccountApproval => contracts::Kind::AccountApproval,
                    Route::SyncPolicy => contracts::Kind::SyncPolicyUpdate,
                    _ => unreachable!(),
                },
                serde_json::from_slice(body).map_err(|_| Failure("invalid_execution_contract"))?,
            )?)
        }
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
            Route::SyncStatus => profile_sync_policy::status_in(&mut tx).await,
            Route::AccountApproval => {
                let now = storage::now(&mut tx).await?;
                account::approve_in(&mut tx, input.unwrap(), now).await
            }
            Route::SyncPolicy => profile_sync_policy::configure_in(&mut tx, input.unwrap()).await,
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
                Failure(if route.method() != "GET" {
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
