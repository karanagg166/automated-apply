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
pub mod legacy_policy;
pub mod legacy_prepare;
mod legacy_questions;
mod legacy_schedule;
pub mod legacy_work;
pub mod legacy_worker;
pub mod listing_ingestion;
mod local_policy;
mod notices;
pub mod owner_import;
pub mod owner_questions;
pub mod owner_routes;
pub mod owner_status;
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
pub mod retained_index;
pub mod review;
pub mod reviewed_history;
pub(crate) mod schedule;
pub mod search;
mod storage;
pub mod submission;
pub mod telegram_commands;
pub(crate) mod telegram_questions;
pub mod telegram_reconciliation;

use crate::{Failure, Result};
use serde_json::Value;
use sqlx::{Connection, PgConnection};
pub(crate) async fn lock_owner_in(tx: &mut sqlx::Transaction<'_, sqlx::Postgres>) -> Result<()> {
    storage::lock(tx).await
}
pub(crate) async fn preparation_authority_in(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
) -> Result<Value> {
    let record = legacy_policy::record(tx).await?;
    let configuration = legacy_policy::configuration(tx).await?;
    Ok(
        serde_json::json!({"state":record["state"],"revision":record["revision"],"mode":configuration["mode"]}),
    )
}

pub(crate) async fn reviewed_profile_in(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
) -> crate::Result<serde_json::Value> {
    preflight::profile_in(tx, &serde_json::json!({})).await
}
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
            | "naukri_submission_capability_not_verified"
            | "automation_revision_conflict"
            | "confirmed_profile_version_required"
            | "approved_primary_resume_changed_or_missing"
            | "verified_experience_outside_policy"
            | "gmail_intake_deferred_to_phase54"
            | "approved_telegram_channel_required"
            | "bounded_preparation_policy_required"
            | "saved_naukri_job_required"
            | "execution_not_found"
            | "execution_revision_conflict"
            | "execution_terminal_check_history"
            | "execution_not_resumable"
            | "role_outside_policy"
            | "excluded_company"
            | "location_outside_policy"
            | "required_experience_band_unknown"
            | "job_experience_band_outside_policy"
            | "posting_date_required"
            | "posting_outside_freshness_policy"
            | "strict_skill_or_preference_match_required"
            | "uncertain_match_requires_review"
            | "invalid_requisition_identity"
            | "vacancy_closed_expired_or_invalid"
            | "previous_application_or_owner_exclusion"
            | "required_experience_outside_verified_band"
            | "required_experience_unknown"
            | "fit_requires_owner_review"
            | "experience_suitability_unknown"
            | "confirmed_profile_required"
            | "current_vacancy_requires_owner_review"
            | "closed"
            | "expired"
            | "invalid_evidence"
            | "already_applied"
            | "question_not_found"
            | "question_already_answered"
            | "question_revision_conflict"
            | "question_expired_or_application_cancelled"
            | "questionnaire_question_context_changed"
            | "execution_not_waiting_for_question"
            | "answerable_packet_field_required"
            | "missing_or_expired_answer_required"
            | "supported_ats_application_required"
            | "current_answer_required"
            | "answer_context_stale"
            | "answer_changed_review_again"
            | "unexpired_reuse_approval_required"
            | "source_answer_changed_review_again"
            | "answer_reuse_context_mismatch"
            | "sensitive_answer_not_retained"
            | "answer_length_invalid"
            | "numeric_answer_required"
            | "iso_date_answer_required"
            | "email_answer_required"
            | "public_https_answer_required"
            | "answer_must_match_option"
            | "yes_or_no_required"
            | "availability_requires_future_datetime_and_iana_timezone"
            | "packet_context_stale_or_destination_invalid"
            | "extension_answer_context_mismatch"
            | "telegram_question_too_long_manual_required"
            | "telegram_delivery_attempt_conflict"
            | "telegram_delivery_binding_required"
            | "telegram_delivery_lease_active"
            | "telegram_delivery_already_resolved"
            | "telegram_delivery_message_conflict"
            | "invalid_execution_transition"
    )
}
#[derive(Clone, Copy)]
pub enum Route<'a> {
    Queue,
    Account,
    AccountApproval,
    SyncStatus,
    SyncPolicy,
    Policy,
    Control,
    Owner(owner_routes::Route<'a>),
}
impl Route<'_> {
    pub fn method(self) -> &'static str {
        match self {
            Self::Policy | Self::AccountApproval | Self::SyncPolicy => "PUT",
            Self::Control => "POST",
            Self::Owner(route) => route.method(),
            _ => "GET",
        }
    }
    pub fn for_method(self, method: &str) -> Self {
        if matches!(self, Self::Account) && method == "PUT" {
            Self::AccountApproval
        } else if matches!(self, Self::Owner(owner_routes::Route::Summary)) && method == "PUT" {
            Self::Owner(owner_routes::Route::Configuration)
        } else {
            self
        }
    }
    pub fn allow(self) -> &'static str {
        if matches!(
            self,
            Self::Account
                | Self::AccountApproval
                | Self::Owner(owner_routes::Route::Summary | owner_routes::Route::Configuration)
        ) {
            "GET, PUT"
        } else {
            self.method()
        }
    }
    pub fn status(self) -> u16 {
        if let Self::Owner(route) = self {
            route.status()
        } else {
            200
        }
    }
}
pub fn route(path: &str) -> Option<Route<'_>> {
    match path {
        "/api/v1/execution/queue" => Some(Route::Queue),
        "/api/v1/execution/naukri/account-binding" => Some(Route::Account),
        "/api/v1/execution/naukri/profile-sync" => Some(Route::SyncStatus),
        "/api/v1/execution/naukri/profile-sync/policy" => Some(Route::SyncPolicy),
        "/api/v1/execution/queue/policy" => Some(Route::Policy),
        "/api/v1/execution/queue/control" => Some(Route::Control),
        _ => owner_routes::route(path).map(Route::Owner),
    }
}
pub async fn dispatch(
    c: &mut PgConnection,
    route: Route<'_>,
    method: &str,
    query: Option<&str>,
) -> Result<Value> {
    dispatch_body(c, route, method, query, &[]).await
}
pub async fn dispatch_body(
    c: &mut PgConnection,
    route: Route<'_>,
    method: &str,
    query: Option<&str>,
    body: &[u8],
) -> Result<Value> {
    dispatch_body_configured(c, route, method, query, body, None).await
}
pub async fn dispatch_body_configured(
    c: &mut PgConnection,
    route: Route<'_>,
    method: &str,
    query: Option<&str>,
    body: &[u8],
    config: Option<&crate::configuration::Configuration>,
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
        Route::Owner(owner) => owner.input(body)?,
        _ => None,
    };
    let mut tx = c.begin().await.map_err(storage::db)?;
    let result = async {
        let isolation = match route {
            // The owner fence serializes queue control changes. Read the
            // revision committed by a preceding owner transaction after waiting.
            Route::Control => "SET TRANSACTION ISOLATION LEVEL READ COMMITTED",
            _ if route.method() == "GET" => {
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            }
            _ => "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE",
        };
        sqlx::query(isolation)
            .execute(&mut *tx)
            .await
            .map_err(storage::db)?;
        if route.method() != "GET" {
            storage::lock(&mut tx).await?;
        }
        match route {
            Route::Owner(owner) => {
                let now = storage::now(&mut tx).await?;
                owner_routes::dispatch_in(
                    &mut tx,
                    owner,
                    input,
                    config.is_some_and(|c| c.telegram_enabled()),
                    config.map(|c| legacy_questions::Services {
                        packets: &c.packets,
                        answers: &c.answers,
                        resumes: &c.resumes,
                    }),
                    config,
                    now,
                )
                .await
            }
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
