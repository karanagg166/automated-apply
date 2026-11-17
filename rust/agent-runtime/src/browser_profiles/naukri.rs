//! Selected authenticated native browser queue bridge. Never performs browser or provider IO.
use super::*;
use crate::execution::broker;
pub(super) fn supports(name: &str) -> bool {
    broker::COMMANDS.contains(&name)
}
pub(super) fn domain_denial(error: Failure) -> bool {
    let code = error.0;
    if code.contains("database_error")
        || code.contains("write_ack_failed")
        || code.contains("rollback")
        || code.contains("snapshot_required")
        || code.starts_with("invalid_")
    {
        return false;
    }
    crate::execution::denial(error)
        || [
            "queue_",
            "profile_sync_",
            "questionnaire_",
            "naukri_",
            "profile_setup_",
            "original_form_",
            "form_loss_",
            "pending_original_",
            "bounded_reconciliation_",
            "prior_",
            "fresh_provider_",
            "canonical_",
            "platform_",
            "background_",
            "supervised_",
            "hourly_",
            "daily_",
            "posting_",
            "applicant_",
            "required_experience_",
            "verified_experience_",
            "advertised_",
            "minimum_match_",
            "uncertain_job_",
        ]
        .iter()
        .any(|p| code.starts_with(p))
        || matches!(
            code,
            "execution_mode_off"
                | "standing_submission_scope_required"
                | "admission_history_requires_reconciliation"
                | "prepared_application_required"
                | "confirmed_primary_resume_required"
                | "resume_revision_changed"
                | "resume_decryption_key_unavailable"
                | "pdf_exceeds_conservative_naukri_limit"
                | "verified_profile_context_changed"
                | "current_profile_preferences_or_required_skills_exclude_job"
                | "packet_context_stale"
                | "existing_worker_receipt_requires_review"
                | "apply_action_observation_required"
                | "provider_job_or_company_changed"
                | "persistent_provider_application_status_required"
                | "independent_history_reload_required"
        )
}
/// Status is a coherent read snapshot and never waits on or advances the owner fence.
pub(super) async fn read_status(c: &mut PgConnection, command: &native::Command) -> Result<Value> {
    let mut tx = c.begin().await.map_err(db)?;
    let result = async {
        sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            .execute(&mut *tx)
            .await
            .map_err(db)?;
        let at = now(&mut tx).await?;
        commands::read_profile(&mut tx, command, at).await?;
        broker::status_in(&mut tx).await
    }
    .await;
    match result {
        Ok(value) => {
            tx.commit().await.map_err(db)?;
            Ok(value)
        }
        Err(e) => {
            tx.rollback()
                .await
                .map_err(|_| Failure("browser_profile_rollback_unconfirmed"))?;
            Err(e)
        }
    }
}
pub(super) async fn dispatch(
    tx: &mut Transaction<'_, Postgres>,
    command: &native::Command,
    settings: &Settings,
    packets: &crate::packet_service::Settings,
    forms: Option<form_service::Services<'_>>,
    now: DateTime<Utc>,
) -> Result<Value> {
    let name = command.name();
    let profile = if name == "naukri_queue_status" {
        commands::read_profile(tx, command, now).await?
    } else {
        commands::require_profile(tx, command, now).await?
    };
    if name == "naukri_queue_status" {
        return broker::status_in(tx).await;
    }
    if name == "naukri_queue_control" {
        if command.value["queue_action"] == "start"
            && (!settings.commands_enabled || profile["commands_enabled"] != true)
        {
            return Err(Failure("PROFILE_COMMANDS_DISABLED"));
        }
    } else if !settings.commands_enabled || profile["commands_enabled"] != true {
        return Err(Failure("PROFILE_COMMANDS_DISABLED"));
    }
    let mut savepoint = sqlx::Acquire::begin(&mut *tx).await.map_err(db)?;
    let result=async{
        if name=="naukri_queue_control"{return broker::control_in(&mut savepoint,&command.value,now).await;}
        if command.value["window_id"].as_i64().is_none_or(|n|n<=0)||command.value["window_id"]!=profile["window_id"]{return Err(Failure("queue_window_binding_changed"));}
        let selected=selection(&mut savepoint).await?;let binding=json!({"profile_binding_id":profile["id"],"profile_version":profile["version"],"selection_version":selected["version"],"browser_session_id":command.value["browser_session_id"],"window_id":command.value["window_id"],"tab_id":command.value["tab_id"]});
        let services=forms.ok_or(Failure("browser_form_inspection_unavailable"))?;let services=broker::Services{packets,resumes:services.resumes,telegram:settings.telegram_notices};
        if name=="poll_naukri_work"{broker::poll_in(&mut savepoint,&command.value,&binding,&services,now).await}else{broker::step_in(&mut savepoint,&command.value,&binding,&services,now).await}
    }.await;
    match result {
        Ok(value) => {
            savepoint.commit().await.map_err(db)?;
            Ok(value)
        }
        Err(e) => {
            savepoint
                .rollback()
                .await
                .map_err(|_| Failure("browser_profile_rollback_unconfirmed"))?;
            Err(e)
        }
    }
}
