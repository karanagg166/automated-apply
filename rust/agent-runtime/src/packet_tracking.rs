//! Audited manual submission and outcome transitions. No employer request or job mutation.
use crate::{
    Failure, Result, packet_archive, packet_context, packet_mutation,
    packet_record::{self, Kind},
    packet_review,
    packet_service::{self, Settings},
    packet_tracking_contract::{Submission, Tracking},
};
use chrono::Utc;
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;

async fn parent(tx: &mut Transaction<'_, Postgres>, packet: Uuid) -> Result<Value> {
    sqlx::query_scalar("SELECT to_jsonb(p) FROM application_packets p WHERE id=$1 FOR UPDATE")
        .bind(packet)
        .fetch_optional(&mut **tx)
        .await
        .map_err(packet_service::db)?
        .ok_or(Failure("packet_not_found"))
}
async fn evidence(tx: &mut Transaction<'_, Postgres>, packet: Uuid) -> Result<Option<Value>> {
    sqlx::query_scalar(
        "SELECT to_jsonb(e) FROM application_submission_evidence e WHERE packet_id=$1",
    )
    .bind(packet)
    .fetch_optional(&mut **tx)
    .await
    .map_err(packet_service::db)
}
fn submission_read(raw: &Value) -> Result<Value> {
    let mut result = json!({});
    for key in [
        "id",
        "packet_id",
        "packet_revision",
        "confirmation_source",
        "receipt_reference",
        "evidence_confidence",
        "human_confirmed",
    ] {
        result[key] = raw[key].clone();
    }
    result["created_at"] = packet_record::timestamp(&raw["created_at"], true)?;
    static VALIDATOR: std::sync::LazyLock<jsonschema::Validator> = std::sync::LazyLock::new(|| {
        let schema: Value = serde_json::from_str(include_str!("../schemas/packet-submission.json"))
            .expect("frozen submission schema");
        jsonschema::draft202012::options()
            .should_validate_formats(false)
            .build(&schema)
            .expect("local submission validator")
    });
    if !VALIDATOR.is_valid(&result) {
        return Err(Failure("invalid_packet_saved_record"));
    }
    Ok(result)
}
async fn event(
    tx: &mut Transaction<'_, Postgres>,
    packet: Uuid,
    kind: &str,
    old: &Value,
    new: &Value,
    evidence: Option<Uuid>,
    note: Option<&str>,
) -> Result<()> {
    let id = Uuid::new_v4();
    let wanted = json!({"id":id,"packet_id":packet,"event_type":kind,"previous_state":old["lifecycle_state"],"next_state":new["lifecycle_state"],"packet_revision":new["revision"],"origin":"owner_rest","evidence_id":evidence,"note":note});
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO application_events(id,packet_id,event_type,previous_state,next_state,packet_revision,origin,evidence_id,note) VALUES($1,$2,$3,$4,$5,$6,'owner_rest',$7,$8) RETURNING to_jsonb(application_events)-'created_at'")
        .bind(id).bind(packet).bind(kind).bind(old["lifecycle_state"].as_str()).bind(new["lifecycle_state"].as_str()).bind(new["revision"].as_i64().ok_or(Failure("invalid_packet_saved_record"))? as i32).bind(evidence).bind(note).fetch_optional(&mut **tx).await.map_err(packet_service::db)?;
    if saved != Some(wanted) {
        return Err(Failure("packet_write_ack_failed"));
    }
    Ok(())
}
pub(crate) async fn report_in(
    tx: &mut Transaction<'_, Postgres>,
    packet: Uuid,
    input: &Submission,
) -> Result<Value> {
    let raw = parent(tx, packet).await?;
    let mut request =
        serde_json::to_value(input).map_err(|_| Failure("invalid_packet_tracking_request"))?;
    request["packet_id"] = json!(packet);
    let hash = crate::python_json::digest(&request);
    // Exact replay precedes revision/lifecycle checks and never advances the packet again.
    if let Some(existing) = evidence(tx, packet).await? {
        if existing["idempotency_key"] != input.idempotency_key || existing["request_hash"] != hash
        {
            return Err(Failure("packet_submission_already_reported"));
        }
        return submission_read(&existing);
    }
    if raw["revision"] != input.expected_revision {
        return Err(Failure("packet_revision_conflict"));
    }
    if matches!(
        raw["lifecycle_state"].as_str(),
        Some(
            "withdrawn"
                | "abandoned"
                | "provider_confirmed_submitted"
                | "submitting"
                | "submission_unknown"
        )
    ) {
        return Err(Failure("packet_closed"));
    }
    let used: bool = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM application_submission_evidence WHERE idempotency_key=$1)",
    )
    .bind(&input.idempotency_key)
    .fetch_one(&mut **tx)
    .await
    .map_err(packet_service::db)?;
    if used {
        return Err(Failure("packet_submission_key_conflict"));
    }
    let fields = packet_mutation::fields_in(tx, packet).await?;
    packet_archive::advance_in(tx, &raw, &fields, input.expected_revision, Utc::now()).await?;
    let id = Uuid::new_v4();
    let revision = input.expected_revision + 1;
    let saved:Option<Value>=sqlx::query_scalar("INSERT INTO application_submission_evidence(id,packet_id,packet_revision,confirmation_source,receipt_reference,evidence_confidence,human_confirmed,idempotency_key,request_hash) VALUES($1,$2,$3,'user_reported',$4,'self_reported_unverified',true,$5,$6) ON CONFLICT DO NOTHING RETURNING to_jsonb(application_submission_evidence)")
        .bind(id).bind(packet).bind(revision).bind(&input.receipt_reference).bind(&input.idempotency_key).bind(hash).fetch_optional(&mut **tx).await.map_err(packet_service::db)?;
    let saved = saved.ok_or(Failure("packet_submission_key_conflict"))?;
    if saved["id"] != json!(id)
        || saved["packet_id"] != json!(packet)
        || saved["packet_revision"] != revision
        || saved["confirmation_source"] != "user_reported"
        || saved["evidence_confidence"] != "self_reported_unverified"
        || saved["human_confirmed"] != true
        || saved["receipt_reference"] != json!(input.receipt_reference)
        || saved["idempotency_key"] != input.idempotency_key
        || saved["request_hash"] != request_hash(&request)
    {
        return Err(Failure("packet_write_ack_failed"));
    }
    let updated:Option<Value>=sqlx::query_scalar("UPDATE application_packets p SET lifecycle_state='user_reported_submitted',tracking_state='applied_manually',readiness_state='completed_by_user' WHERE id=$1 RETURNING to_jsonb(p)")
        .bind(packet).fetch_optional(&mut **tx).await.map_err(packet_service::db)?;
    let updated = updated.ok_or(Failure("packet_write_ack_failed"))?;
    if updated["revision"] != revision
        || updated["lifecycle_state"] != "user_reported_submitted"
        || updated["tracking_state"] != "applied_manually"
        || updated["readiness_state"] != "completed_by_user"
        || !updated["approved_revision"].is_null()
    {
        return Err(Failure("packet_write_ack_failed"));
    }
    event(
        tx,
        packet,
        "user_reported_submission",
        &raw,
        &updated,
        Some(id),
        input.note.as_deref(),
    )
    .await?;
    submission_read(&saved)
}
fn request_hash(request: &Value) -> String {
    crate::python_json::digest(request)
}
pub(crate) async fn track_in(
    tx: &mut Transaction<'_, Postgres>,
    packet: Uuid,
    input: &Tracking,
    settings: &Settings,
) -> Result<Value> {
    let raw = parent(tx, packet).await?;
    if raw["revision"] != input.expected_revision {
        return Err(Failure("packet_revision_conflict"));
    }
    if matches!(
        raw["lifecycle_state"].as_str(),
        Some("submitting" | "submission_unknown")
    ) {
        return Err(Failure("packet_tracking_reconcile_required"));
    }
    if input.tracking_state.as_deref() == Some("applied_verified")
        && raw["lifecycle_state"] != "provider_confirmed_submitted"
    {
        return Err(Failure("packet_tracking_receipt_required"));
    }
    let submitted = evidence(tx, packet).await?.is_some();
    if !submitted
        && matches!(
            input.tracking_state.as_deref(),
            Some(
                "applied_manually"
                    | "applied_verified"
                    | "application_rejected"
                    | "interview_scheduled"
                    | "offer_received"
            )
        )
    {
        return Err(Failure("packet_tracking_submission_required"));
    }
    if submitted
        && matches!(
            input.tracking_state.as_deref(),
            Some("not_applied" | "application_incomplete")
        )
    {
        return Err(Failure("packet_tracking_history_immutable"));
    }
    if input.lifecycle_state.as_deref() == Some("external_application_opened") {
        packet_review::handoff_in(tx, packet, settings).await?;
    }
    if matches!(
        raw["lifecycle_state"].as_str(),
        Some("withdrawn" | "abandoned")
    ) && input.lifecycle_state.is_some()
    {
        return Err(Failure("packet_closed"));
    }
    if input.lifecycle_state.as_deref() == Some("withdrawn") && !submitted {
        return Err(Failure("packet_tracking_submission_required"));
    }
    let mut stale = false;
    if !raw["approved_revision"].is_null() {
        let selected = raw["resume_resource_id"]
            .as_str()
            .map(|s| {
                s.parse::<Uuid>()
                    .map_err(|_| Failure("invalid_packet_saved_record"))
            })
            .transpose()?;
        let current = packet_context::load_locked_in(
            tx,
            packet_service::id(&raw["job_id"])?,
            selected,
            &settings.policy,
        )
        .await?;
        stale = current.snapshot["context_digest"]
            != packet_record::normalize(Kind::Snapshot, raw["snapshot"].clone())?["context_digest"]
            || current
                .profile
                .as_ref()
                .is_none_or(|p| p["id"] != raw["candidate_profile_id"]);
    }
    let fields = packet_mutation::fields_in(tx, packet).await?;
    let advanced = packet_archive::advance_mode_in(
        tx,
        &raw,
        &fields,
        input.expected_revision,
        Utc::now(),
        !stale,
    )
    .await?;
    let lifecycle = input.lifecycle_state.as_deref().unwrap_or(if stale {
        "needs_input"
    } else {
        advanced["lifecycle_state"]
            .as_str()
            .ok_or(Failure("invalid_packet_saved_record"))?
    });
    let tracking = input.tracking_state.as_deref().unwrap_or(
        advanced["tracking_state"]
            .as_str()
            .ok_or(Failure("invalid_packet_saved_record"))?,
    );
    let readiness = if stale {
        "needs_review"
    } else {
        advanced["readiness_state"]
            .as_str()
            .ok_or(Failure("invalid_packet_saved_record"))?
    };
    let approved = if matches!(lifecycle, "withdrawn" | "abandoned") {
        None
    } else {
        advanced["approved_revision"].as_i64().map(|n| n as i32)
    };
    let updated:Option<Value>=sqlx::query_scalar("UPDATE application_packets p SET lifecycle_state=$2,tracking_state=$3,readiness_state=$4,approved_revision=$5 WHERE id=$1 RETURNING to_jsonb(p)")
        .bind(packet).bind(lifecycle).bind(tracking).bind(readiness).bind(approved).fetch_optional(&mut **tx).await.map_err(packet_service::db)?;
    let updated = updated.ok_or(Failure("packet_write_ack_failed"))?;
    if updated["revision"] != input.expected_revision + 1
        || updated["lifecycle_state"] != lifecycle
        || updated["tracking_state"] != tracking
        || updated["readiness_state"] != readiness
        || updated["approved_revision"] != json!(approved)
    {
        return Err(Failure("packet_write_ack_failed"));
    }
    event(
        tx,
        packet,
        "tracking_updated",
        &raw,
        &updated,
        None,
        input.note.as_deref(),
    )
    .await?;
    packet_service::read_locked_in(tx, packet, settings, Utc::now()).await
}
