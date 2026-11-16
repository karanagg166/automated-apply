//! Sanitized response mapping shared by domain route modules.
use crate::Failure;
use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
};
use serde_json::{Value, json};

pub(super) fn profile_failure(error: Failure) -> Response {
    if error.0.starts_with("gmail_legacy_") || error.0.starts_with("invalid_gmail_legacy_") {
        let status = match error.0 {
            "invalid_gmail_legacy_request" => StatusCode::UNPROCESSABLE_ENTITY,
            "gmail_legacy_method_not_allowed" => StatusCode::METHOD_NOT_ALLOWED,
            "gmail_legacy_identity_requires_review" => StatusCode::CONFLICT,
            _ => StatusCode::SERVICE_UNAVAILABLE,
        };
        return reply(status, json!({"detail":error.0}));
    }
    if error.0.starts_with("gmail_workspace_")
        || error.0.starts_with("invalid_gmail_workspace_")
        || matches!(
            error.0,
            "gmail_draft_version_or_state_conflict"
                | "gmail_draft_header_invalid"
                | "current_approved_profile_required"
        )
    {
        let status = match error.0 {
            "invalid_gmail_workspace_contract" | "gmail_draft_header_invalid" => {
                StatusCode::UNPROCESSABLE_ENTITY
            }
            "gmail_workspace_method_not_allowed" => StatusCode::METHOD_NOT_ALLOWED,
            "gmail_draft_version_or_state_conflict"
            | "current_approved_profile_required"
            | "gmail_workspace_role_identity_conflict" => StatusCode::CONFLICT,
            _ => StatusCode::SERVICE_UNAVAILABLE,
        };
        return reply(status, json!({"detail":error.0}));
    }
    if error.0.starts_with("gmail_read_")
        || error.0.starts_with("invalid_gmail_read_")
        || matches!(
            error.0,
            "gmail_readonly_schema_update_required"
                | "gmail_readonly_scope_required"
                | "gmail_body_access_review_required"
                | "gmail_sync_version_conflict"
                | "gmail_evidence_projection_limit"
                | "gmail_evidence_not_found"
                | "gmail_lead_not_in_selected_evidence"
                | "gmail_lead_identity_requires_review"
                | "gmail_lead_legacy_inventory_limit"
        )
    {
        let status = match error.0 {
            "invalid_gmail_read_contract" | "invalid_gmail_read_page" => {
                StatusCode::UNPROCESSABLE_ENTITY
            }
            "gmail_read_method_not_allowed" => StatusCode::METHOD_NOT_ALLOWED,
            "gmail_read_account_not_found"
            | "gmail_readonly_schema_update_required"
            | "gmail_readonly_scope_required"
            | "gmail_body_access_review_required"
            | "gmail_sync_version_conflict"
            | "gmail_evidence_not_found"
            | "gmail_lead_not_in_selected_evidence"
            | "gmail_lead_identity_requires_review" => StatusCode::CONFLICT,
            _ => StatusCode::SERVICE_UNAVAILABLE,
        };
        return reply(status, json!({"detail":error.0}));
    }
    if error.0.starts_with("gmail_history_") || error.0.starts_with("invalid_gmail_history_") {
        let status = match error.0 {
            "invalid_gmail_history_contract" => StatusCode::UNPROCESSABLE_ENTITY,
            "gmail_history_method_not_allowed" => StatusCode::METHOD_NOT_ALLOWED,
            "gmail_history_version_conflict"
            | "gmail_history_identity_conflict"
            | "gmail_history_evidence_unavailable"
            | "gmail_history_expired_record" => StatusCode::CONFLICT,
            _ => StatusCode::SERVICE_UNAVAILABLE,
        };
        return reply(status, json!({"detail":error.0}));
    }
    if error.0 == "execution_event_not_found" {
        return reply(StatusCode::NOT_FOUND, json!({"detail":error.0}));
    }
    if crate::execution::denial(error) {
        return reply(StatusCode::CONFLICT, json!({"detail":error.0}));
    }
    if matches!(
        error.0,
        "execution_database_error"
            | "execution_services_required"
            | "execution_commit_outcome_unknown"
            | "execution_active_inventory_limit"
            | "execution_write_ack_failed"
            | "execution_read_commit_failed"
            | "execution_rollback_unconfirmed"
            | "execution_method_not_allowed"
            | "invalid_execution_contract"
            | "invalid_naukri_import"
            | "invalid_execution_page"
            | "invalid_execution_saved_record"
    ) {
        let status = match error.0 {
            "invalid_execution_contract" | "invalid_execution_page" | "invalid_naukri_import" => {
                StatusCode::UNPROCESSABLE_ENTITY
            }
            "execution_method_not_allowed" => StatusCode::METHOD_NOT_ALLOWED,
            _ => StatusCode::SERVICE_UNAVAILABLE,
        };
        return reply(status, json!({"detail":error.0}));
    }
    if matches!(
        error.0,
        "invalid_browser_task_record" | "invalid_browser_form_record"
    ) {
        return reply(StatusCode::SERVICE_UNAVAILABLE, json!({"detail":error.0}));
    }
    if crate::browser_profiles::tasks::owner_denial(error)
        || crate::browser_profiles::form_service::domain_denial(error)
    {
        return reply(StatusCode::CONFLICT, json!({"detail":error.0}));
    }
    if matches!(
        error.0,
        "command_id_conflict"
            | "PROFILE_COMMANDS_DISABLED"
            | "profile_queue_full"
            | "extension_task_required"
            | "extension_task_not_found"
            | "extension_task_revision_conflict"
            | "extension_task_context_stale"
            | "stale_or_unreviewed_candidate_context"
            | "application_not_eligible"
            | "naukri_automation_paused"
            | "naukri_automation_stopped"
            | "execution_mode_off"
            | "unverified_application_destination"
            | "unsupported_form_adapter"
            | "platform_fill_policy_denied"
    ) {
        return reply(StatusCode::CONFLICT, json!({"detail":error.0}));
    }
    if error.0.starts_with("browser_profile_")
        || error.0.starts_with("invalid_browser_profile_")
        || matches!(
            error.0,
            "PROFILE_SELECTION_CONFLICT"
                | "PROFILE_REVISION_CONFLICT"
                | "PROFILE_OFFLINE"
                | "FIXED_PROFILE_REQUIRED"
                | "extension_identity_not_authorized"
        )
    {
        let status = match error.0 {
            "invalid_browser_profile_request" => StatusCode::UNPROCESSABLE_ENTITY,
            "extension_identity_not_authorized" => StatusCode::FORBIDDEN,
            "browser_profile_method_not_allowed" => StatusCode::METHOD_NOT_ALLOWED,
            "PROFILE_SELECTION_CONFLICT"
            | "PROFILE_REVISION_CONFLICT"
            | "PROFILE_OFFLINE"
            | "FIXED_PROFILE_REQUIRED"
            | "browser_profile_write_ack_failed" => StatusCode::CONFLICT,
            _ => StatusCode::SERVICE_UNAVAILABLE,
        };
        return reply(status, json!({"detail":error.0}));
    }
    if matches!(error.0, "invalid_job_status" | "invalid_catalog_job_record") {
        return reply(
            StatusCode::BAD_REQUEST,
            json!({"detail":"Invalid argument","error_type":"invalid_argument"}),
        );
    }
    if matches!(
        error.0,
        "invalid_resume_review_request"
            | "invalid_resume_drive_source"
            | "resume_skill_removal_confirmation_required"
    ) {
        return reply(StatusCode::UNPROCESSABLE_ENTITY, json!({"detail":error.0}));
    }
    if error.0 == "resume_review_method_not_allowed" {
        return reply(StatusCode::METHOD_NOT_ALLOWED, json!({"detail":error.0}));
    }
    if matches!(
        error.0,
        "resume_review_not_found" | "resume_source_not_found"
    ) {
        return reply(StatusCode::NOT_FOUND, json!({"detail":error.0}));
    }
    if matches!(
        error.0,
        "resume_review_database_error"
            | "resume_review_commit_outcome_unknown"
            | "resume_review_rollback_unconfirmed"
            | "invalid_resume_review_record"
            | "private_resume_review_invalid"
            | "resume_review_incomplete"
    ) {
        return reply(StatusCode::SERVICE_UNAVAILABLE, json!({"detail":error.0}));
    }
    if matches!(
        error.0,
        "drive_oauth_deferred_use_manual_pdf_upload"
            | "resume_source_generation_conflict"
            | "resume_latest_version_required"
            | "resume_source_write_ack_failed"
            | "resume_review_write_ack_failed"
            | "profile_write_ack_failed"
    ) {
        return reply(StatusCode::CONFLICT, json!({"detail":error.0}));
    }
    let status = failure(error).status();
    let detail = match error.0 {
        "invalid_notification_preferences" => {
            "Notification preferences are invalid; external channels remain disabled"
        }
        "invalid_saved_notification_preferences" => {
            "Saved notification preferences are invalid; correct them before continuing"
        }
        "notification_preferences_outcome_unknown" => {
            "Preference commit outcome is uncertain; retrieve current preferences before retrying"
        }
        "notification_preferences_write_ack_failed" => {
            "Preference write was not acknowledged; retrieve current preferences before retrying"
        }
        "notification_preferences_method_not_allowed" => "Method Not Allowed",
        "packet_not_found" => "Application packet not found",
        "invalid_packet_tracking_request" => "Submission or tracking request is invalid",
        "packet_submission_already_reported" => {
            "Submission was already reported; reload application history"
        }
        "packet_submission_key_conflict" => "Submission key belongs to another report",
        "packet_tracking_reconcile_required" => {
            "Reconcile the dispatched submission before changing tracking"
        }
        "packet_tracking_receipt_required" => {
            "Verified tracking requires a verified employer receipt"
        }
        "packet_tracking_submission_required" => {
            "Record actual submission before a post-submission outcome"
        }
        "packet_tracking_history_immutable" => "Tracking cannot erase existing submission evidence",
        "packet_field_not_found" => "Question does not belong to this application packet",
        "invalid_packet_review_request" => "Packet review request is invalid",
        "packet_review_fields_invalid" => {
            "Review IDs must be unique questions belonging to this packet"
        }
        "packet_review_answer_invalid" => "Only valid answered fields can be reviewed",
        "packet_review_confirmation_required" => {
            "Explicitly confirm the selected resume and saved application destination"
        }
        "packet_approval_blocked" => {
            "Packet cannot be approved; inspect its current readiness blockers"
        }
        "packet_handoff_approval_required" => {
            "Approve the current packet revision before manual handoff"
        }
        "packet_handoff_incomplete" => {
            "Packet is stale or incomplete; refresh, review and approve it"
        }
        "packet_execution_binding_conflict" => {
            "Packet execution binding is ambiguous or changed; reconcile before reviewing"
        }
        "invalid_packet_notice_state" => {
            "Saved execution or notice policy is invalid; correct it before reviewing"
        }
        "packet_revision_conflict" => "Packet revision changed; reload it before retrying",
        "packet_write_ack_failed" => {
            "Application write was not acknowledged; reload before retrying"
        }
        "packet_closed" => "Closed or submitted packets cannot be edited",
        "packet_context_changed" => {
            "Saved evidence changed; refresh the packet before editing or reviewing"
        }
        "packet_profile_changed" => "Saved candidate no longer matches this packet",
        "packet_refresh_required" => "Select a resume or request refresh_saved_data",
        "packet_field_limit" => "A packet supports at most 100 checklist and screening fields",
        "packet_upload_attestation_denied" => {
            "An answer cannot attest to a portal file upload; upload the file on the official website"
        }
        "packet_answer_invalid" => {
            "Supply a nonblank answer within the displayed length and exact option constraints"
        }
        "invalid_packet_edit_request" | "invalid_packet_generation_request" => {
            "Application packet edit request is invalid"
        }
        "packet_job_not_found" => "Saved job not found",
        "packet_profile_required" => {
            "Save a candidate profile before persisting an application packet"
        }
        "packet_idempotency_conflict" => {
            "Idempotency key or candidate/job already belongs to a different packet request"
        }
        "packet_storage_conflict" | "packet_serialization_rollback" => {
            "Application data conflict; reload before retrying"
        }
        "packet_multi_select_unavailable" => {
            "Multiple selections require explicit enablement and an installed, permitted database capability; use manual handoff"
        }
        "invalid_packet_preparation" | "invalid_packet_page" | "invalid_packet_id" => {
            "Application preparation request is invalid"
        }
        "packet_method_not_allowed" => "Method Not Allowed",
        "packet_commit_outcome_unknown" => {
            "Packet commit outcome is uncertain; inspect saved packets before retrying"
        }
        "packet_database_error"
        | "invalid_packet_field_record"
        | "invalid_packet_job_record"
        | "invalid_packet_saved_record"
        | "invalid_packet_context_record"
        | "packet_context_inventory_limit"
        | "packet_context_snapshot_required" => "Application storage unavailable",
        "resume_encryption_unavailable" => {
            "Configure the existing dedicated RESUME_ENCRYPTION_KEY before uploading a private resume"
        }
        "private_resume_outcome_unknown" => {
            "Resume operation outcome is uncertain; inspect saved resumes before retrying"
        }
        "private_pdf_integrity_failed" | "private_pdf_checksum_failed" => {
            "Private PDF integrity failed; restore the original PDF and encryption key"
        }
        "drive_resume_review_required" => {
            "Drive imports require the Resume Sync profile-review approval"
        }
        "canonical_resume_changed" => {
            "Canonical resume changed; review the current version before replacing it"
        }
        "private_resume_changed" => "Resume changed; review the current PDF contents",
        "private_resume_binding_invalid" => "Private resume resource binding is invalid",
        "private_resume_not_found" => "Private resume not found",
        "notification_not_found" => "Notification not found",
        "saved_record_not_found" => "Saved record or candidate profile not found",
        "job_shortlist_conflict" => "This job has already progressed beyond shortlisting",
        "job_shortlist_write_conflict" => "Job update was not saved; reload before shortlisting",
        "invalid_job_page" => "Invalid request",
        "invalid_notification_id" | "invalid_notification_record" => "Notification data is invalid",
        "invalid_notification_page" => "Supply offset 0..100000 once; page size is fixed at 50",
        "pdf_content_type_required" => "Use application/pdf",
        "invalid_answer_request" => "Answer request is invalid",
        "generation_outcome_unknown" => {
            "Generation outcome is uncertain; inspect saved drafts and requests before retrying"
        }
        "generation_context_changed" => {
            "Approved facts changed during generation; reload and review before generating again"
        }
        "answer_reuse_disabled" => "Approved answer reuse is disabled",
        "answer_reuse_current_review_required" => {
            "Review the current answer and candidate facts before approving reuse"
        }
        "answer_reuse_unsupported_intent" => {
            "This question requires individual review; no supported reuse intent is established"
        }
        "answer_reuse_job_required" => "Same-job reuse requires a saved job context",
        "answer_reuse_exact_job_required" => {
            "Company or employer evidence can only be reused for the exact saved job"
        }
        "answer_reuse_context_changed" => {
            "Evidence changed or expired; generate and review a fresh answer"
        }
        "invalid_answer_reuse_approval"
        | "invalid_answer_reuse_record"
        | "answer_draft_context_mismatch" => error.0,
        "missing_input_not_found" => "Missing-answer request not found",
        "missing_input_version_conflict"
        | "missing_input_packet_context_mismatch"
        | "missing_input_draft_context_mismatch"
        | "missing_input_identity_collision"
        | "factual_answer_and_evidence_note_required"
        | "missing_input_context_changed_edit_before_approval"
        | "sensitive_answer_not_retained" => error.0,
        "owner_approval_required" => {
            "Submission authorization requires current dashboard owner approval"
        }
        "owner_approval_unavailable" => {
            "Configure a separate dashboard owner approval key before authorizing consent or submission"
        }
        "owner_approval_operation_mismatch" => "Owner approval does not match this exact operation",
        "owner_approval_already_used" => {
            "Owner approval was already used; review again in the dashboard"
        }
        "invalid_missing_input_request" | "invalid_missing_input_record" => error.0,
        "profile_changed_review_current_version" => "profile_changed_review_current_version",
        "invalid_profile_confirmation" => {
            "Review the current profile version and explicitly confirm it"
        }
        "invalid_resource_selection" => "Select a saved resource by its UUID",
        "invalid_resource_record" => "Saved resource is invalid",
        "invalid_resource_input" => "Resource or evidence input is invalid",
        "invalid_resource_page" => "Supply offset 0..100000 and limit 1..100 once each",
        "resource_not_found" => "Resource not found",
        "evidence_not_found" => "Evidence not found",
        "answer_draft_not_found" => "Draft not found",
        "answer_draft_stale" => {
            "Draft is stale; regenerate or correct the profile before reviewing"
        }
        "invalid_answer_draft_record" | "invalid_answer_draft_review" => {
            "Saved answer draft or review is invalid"
        }
        "resource_conflict" => "Duplicate URL or conflicting primary resource",
        "resource_insert_conflict" => {
            "Duplicate URL or conflicting primary resource; update the existing resource or demote its primary first"
        }
        "standard_link_confirmation_required" => {
            "Standard links require explicit user confirmation and are stored only on the profile"
        }
        "standard_link_version_required" => {
            "Supply expected_profile_version to change a standard profile link"
        }
        "resource_inventory_limit" => "Resource inventory exceeds the inspection limit",
        "owner_client_required" => "owner_ui_required",
        "job_not_found" => "Job not found",
        "invalid_job_id" => "Invalid job ID",
        "profile_not_found" => "No candidate profile saved",
        "profile_version_required" => "Supply If-Match with the current profile version",
        "profile_version_conflict" => "Profile version changed; retrieve it before retrying",
        "invalid_profile_version" => "Invalid profile version",
        "profile_version_syntax" => "If-Match must be a quoted positive integer, e.g. \"1\"",
        "owner_authentication_required" => "Invalid or missing bearer token",
        "invalid_profile_input" | "profile_payload_limit" | "invalid_profile_record" => {
            "Resulting profile is invalid or exceeds 64 KiB"
        }
        "fictional_or_placeholder_profile_rejected" => "fictional_or_placeholder_profile_rejected",
        "profile_method_not_allowed"
        | "match_method_not_allowed"
        | "saved_match_method_not_allowed"
        | "resource_list_method_not_allowed"
        | "evidence_patch_method_not_allowed"
        | "resource_read_method_not_allowed" => "Method Not Allowed",
        "missing_item_method_not_allowed" => "Method Not Allowed",
        "profile_database_error" | "agent_database_reconnecting" | "agent_database_unavailable" => {
            "Profile database unavailable; retrieve the current profile before retrying"
        }
        _ => "Profile request rejected",
    };
    let mut response = reply(status, json!({"detail":detail}));
    if error.0 == "saved_match_method_not_allowed" {
        response
            .headers_mut()
            .insert("allow", "GET, POST".parse().unwrap());
    }
    if error.0 == "match_method_not_allowed" {
        response
            .headers_mut()
            .insert("allow", "POST".parse().unwrap());
    }
    if error.0 == "resource_read_method_not_allowed" {
        response
            .headers_mut()
            .insert("allow", "GET".parse().unwrap());
    }
    if status == StatusCode::UNAUTHORIZED {
        response
            .headers_mut()
            .insert("www-authenticate", "Bearer".parse().unwrap());
    }
    if error.0 == "resource_list_method_not_allowed" {
        response
            .headers_mut()
            .insert("allow", "GET, POST".parse().unwrap());
    }
    if error.0 == "evidence_patch_method_not_allowed" {
        response
            .headers_mut()
            .insert("allow", "PATCH".parse().unwrap());
    }
    if error.0 == "missing_item_method_not_allowed" {
        response
            .headers_mut()
            .insert("allow", "GET, PATCH".parse().unwrap());
    }
    response
}
pub(super) fn failure(error: Failure) -> Response {
    let code = match error.0 {
        "invalid_packet_tracking_request"
        | "invalid_packet_review_request"
        | "packet_review_fields_invalid"
        | "packet_review_answer_invalid"
        | "packet_review_confirmation_required" => StatusCode::UNPROCESSABLE_ENTITY,
        "packet_submission_already_reported"
        | "packet_submission_key_conflict"
        | "packet_tracking_reconcile_required"
        | "packet_tracking_receipt_required"
        | "packet_tracking_submission_required"
        | "packet_tracking_history_immutable"
        | "packet_approval_blocked"
        | "packet_handoff_approval_required"
        | "packet_handoff_incomplete"
        | "packet_execution_binding_conflict" => StatusCode::CONFLICT,
        "invalid_packet_notice_state" => StatusCode::SERVICE_UNAVAILABLE,
        "invalid_notification_preferences" => StatusCode::UNPROCESSABLE_ENTITY,
        "invalid_saved_notification_preferences" | "notification_preferences_outcome_unknown" => {
            StatusCode::SERVICE_UNAVAILABLE
        }
        "notification_preferences_write_ack_failed" => StatusCode::CONFLICT,
        "notification_preferences_method_not_allowed" => StatusCode::METHOD_NOT_ALLOWED,
        "packet_not_found" | "packet_job_not_found" | "packet_field_not_found" => {
            StatusCode::NOT_FOUND
        }
        "packet_write_ack_failed"
        | "packet_revision_conflict"
        | "packet_closed"
        | "packet_context_changed"
        | "packet_profile_changed" => StatusCode::CONFLICT,
        "invalid_packet_generation_request"
        | "invalid_packet_edit_request"
        | "packet_refresh_required"
        | "packet_field_limit"
        | "packet_upload_attestation_denied"
        | "packet_answer_invalid" => StatusCode::UNPROCESSABLE_ENTITY,
        "packet_method_not_allowed" => StatusCode::METHOD_NOT_ALLOWED,
        "packet_idempotency_conflict"
        | "packet_storage_conflict"
        | "packet_serialization_rollback" => StatusCode::CONFLICT,
        "packet_profile_required"
        | "packet_multi_select_unavailable"
        | "invalid_packet_preparation"
        | "invalid_packet_page"
        | "invalid_packet_id" => StatusCode::UNPROCESSABLE_ENTITY,
        "packet_database_error"
        | "invalid_packet_field_record"
        | "invalid_packet_job_record"
        | "packet_commit_outcome_unknown"
        | "invalid_packet_saved_record"
        | "invalid_packet_context_record"
        | "packet_context_inventory_limit"
        | "packet_context_snapshot_required" => StatusCode::SERVICE_UNAVAILABLE,
        "owner_authentication_required" => StatusCode::UNAUTHORIZED,
        "owner_peer_denied"
        | "owner_host_denied"
        | "owner_origin_denied"
        | "owner_client_required" => StatusCode::FORBIDDEN,
        "owner_approval_required"
        | "owner_approval_operation_mismatch"
        | "owner_approval_already_used" => StatusCode::FORBIDDEN,
        "owner_approval_unavailable" => StatusCode::SERVICE_UNAVAILABLE,
        "answer_reuse_disabled" | "generation_outcome_unknown" => StatusCode::SERVICE_UNAVAILABLE,
        "owner_api_tls_required" => StatusCode::UPGRADE_REQUIRED,
        "job_not_found"
        | "profile_not_found"
        | "agent_run_not_found"
        | "owner_route_not_found"
        | "resource_not_found"
        | "evidence_not_found" => StatusCode::NOT_FOUND,
        "saved_record_not_found" => StatusCode::NOT_FOUND,
        "job_shortlist_conflict" | "job_shortlist_write_conflict" => StatusCode::CONFLICT,
        "answer_draft_not_found"
        | "missing_input_not_found"
        | "private_resume_not_found"
        | "notification_not_found" => StatusCode::NOT_FOUND,
        "pdf_content_type_required" => StatusCode::UNSUPPORTED_MEDIA_TYPE,
        "resume_method_not_allowed" => StatusCode::METHOD_NOT_ALLOWED,
        "resume_encryption_unavailable"
        | "document_worker_unavailable"
        | "private_resume_outcome_unknown" => StatusCode::SERVICE_UNAVAILABLE,
        "invalid_resume_label"
        | "invalid_notification_id"
        | "invalid_notification_page"
        | "invalid_notification_record"
        | "invalid_resume_confirmation"
        | "invalid_pdf_upload"
        | "invalid_or_unsafe_pdf"
        | "invalid_pdf_extraction"
        | "pdf_validation_timeout"
        | "pdf_output_limit"
        | "pdf_memory_limit"
        | "pdf_memory_supervision_failed" => StatusCode::UNPROCESSABLE_ENTITY,
        "private_pdf_integrity_failed"
        | "private_pdf_checksum_failed"
        | "private_resume_changed"
        | "canonical_resume_changed"
        | "private_resume_binding_invalid"
        | "drive_resume_review_required"
        | "private_resume_insert_mismatch" => StatusCode::CONFLICT,
        "profile_method_not_allowed"
        | "match_method_not_allowed"
        | "saved_match_method_not_allowed"
        | "resource_read_method_not_allowed" => StatusCode::METHOD_NOT_ALLOWED,
        "missing_item_method_not_allowed" => StatusCode::METHOD_NOT_ALLOWED,
        "resource_list_method_not_allowed" | "evidence_patch_method_not_allowed" => {
            StatusCode::METHOD_NOT_ALLOWED
        }
        "profile_version_required" | "standard_link_version_required" => {
            StatusCode::PRECONDITION_REQUIRED
        }
        "standard_link_confirmation_required"
        | "resource_conflict"
        | "resource_insert_conflict" => StatusCode::CONFLICT,
        "answer_draft_stale" => StatusCode::CONFLICT,
        "generation_context_changed"
        | "answer_reuse_context_changed"
        | "answer_reuse_current_review_required" => StatusCode::CONFLICT,
        "missing_input_version_conflict"
        | "missing_input_packet_context_mismatch"
        | "missing_input_draft_context_mismatch"
        | "missing_input_identity_collision"
        | "factual_answer_and_evidence_note_required"
        | "sensitive_answer_not_retained"
        | "missing_input_context_changed_edit_before_approval" => StatusCode::CONFLICT,
        "profile_version_conflict" | "profile_changed_review_current_version" => {
            StatusCode::CONFLICT
        }
        "invalid_profile_confirmation"
        | "invalid_resource_selection"
        | "invalid_resource_record"
        | "invalid_resource_input"
        | "invalid_resource_page"
        | "invalid_answer_draft_record"
        | "invalid_answer_draft_review"
        | "invalid_missing_input_request"
        | "invalid_missing_input_record"
        | "invalid_answer_request"
        | "invalid_answer_reuse_approval"
        | "invalid_answer_reuse_record"
        | "answer_reuse_unsupported_intent"
        | "answer_reuse_job_required"
        | "answer_reuse_exact_job_required"
        | "answer_draft_context_mismatch"
        | "resource_inventory_limit"
        | "invalid_job_id"
        | "invalid_job_page"
        | "invalid_saved_job_record"
        | "invalid_match_result"
        | "profile_version_syntax"
        | "invalid_profile_input"
        | "profile_payload_limit"
        | "invalid_profile_record"
        | "invalid_profile_version"
        | "fictional_or_placeholder_profile_rejected" => StatusCode::UNPROCESSABLE_ENTITY,
        "agent_approval_not_pending"
        | "agent_approval_expired"
        | "agent_approval_context_changed"
        | "agent_replan_limit"
        | "agent_approval_limit"
        | "agent_revision_conflict"
        | "agent_control_revision_conflict"
        | "agent_request_key_conflict"
        | "agent_question_not_pending"
        | "owner_fact_not_confirmed"
        | "verified_profile_context_changed"
        | "verified_profile_identity_changed"
        | "agent_reconciliation_required"
        | "invalid_agent_control" => StatusCode::CONFLICT,
        "profile_database_error"
        | "agent_database_reconnecting"
        | "agent_database_unavailable"
        | "database_host_unavailable"
        | "verified_context_database_error"
        | "saved_jobs_database_error"
        | "application_history_database_error"
        | "owner_fact_database_error"
        | "agent_database_error"
        | "agent_schema_unavailable"
        | "invalid_worker_control"
        | "agent_database_target_mismatch" => StatusCode::SERVICE_UNAVAILABLE,
        _ => StatusCode::BAD_REQUEST,
    };
    reply(code, json!({"error":error.0}))
}
pub(super) fn reply(status: StatusCode, data: Value) -> Response {
    let mut response = (status, axum::Json(data)).into_response();
    for (key, value) in [
        ("cache-control", "private, no-store"),
        ("x-content-type-options", "nosniff"),
        ("referrer-policy", "no-referrer"),
    ] {
        response.headers_mut().insert(
            axum::http::HeaderName::from_static(key),
            axum::http::HeaderValue::from_static(value),
        );
    }
    response
}
