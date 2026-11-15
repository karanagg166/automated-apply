//! Exact owner review/approval and manual handoff. Never dispatches an application.
use crate::{
    Failure, Result, packet_archive, packet_execution, packet_mutation, packet_notice,
    packet_readiness::{Flags, State},
    packet_record::{self, Kind},
    packet_service::{self, Settings},
};
use chrono::Utc;
use serde::Serialize;
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use std::collections::HashSet;
use uuid::Uuid;

#[derive(Serialize)]
pub struct Input {
    pub expected_revision: i32,
    pub action: String,
    pub reviewed_field_ids: Vec<Uuid>,
    pub confirm_resume: bool,
    pub confirm_destination: bool,
}
fn invalid() -> Failure {
    Failure("invalid_packet_review_request")
}
pub fn request(input: Value) -> Result<Input> {
    let body = input
        .as_object()
        .filter(|b| {
            b.keys().all(|k| {
                [
                    "expected_revision",
                    "action",
                    "reviewed_field_ids",
                    "confirm_resume",
                    "confirm_destination",
                ]
                .contains(&k.as_str())
            })
        })
        .ok_or_else(invalid)?;
    let expected_revision = crate::profile_contract::pagination_integer(
        body.get("expected_revision").cloned().ok_or_else(invalid)?,
        1,
        2147483646,
    )
    .map_err(|_| invalid())? as i32;
    let action = body
        .get("action")
        .map(|v| v.as_str().ok_or_else(invalid))
        .transpose()?
        .unwrap_or("review");
    if !matches!(action, "review" | "approve") {
        return Err(invalid());
    }
    let reviewed_field_ids = match body.get("reviewed_field_ids") {
        None => vec![],
        Some(Value::Array(ids)) if ids.len() <= 100 => ids
            .iter()
            .map(packet_service::id)
            .collect::<Result<Vec<_>>>()
            .map_err(|_| invalid())?,
        _ => return Err(invalid()),
    };
    let boolean = |key| {
        body.get(key)
            .map(crate::resource_contract::boolean)
            .transpose()
            .map_err(|_| invalid())
            .map(|v| v.and_then(|v| v.as_bool()).unwrap_or(false))
    };
    Ok(Input {
        expected_revision,
        action: action.into(),
        reviewed_field_ids,
        confirm_resume: boolean("confirm_resume")?,
        confirm_destination: boolean("confirm_destination")?,
    })
}
pub async fn review_in(
    tx: &mut Transaction<'_, Postgres>,
    packet: Uuid,
    input: &Input,
    settings: &Settings,
) -> Result<Value> {
    // Legacy execution workers take this singleton fence before packet/material claims.
    let mut execution = packet_execution::lock_in(tx, packet).await?;
    let claim =
        packet_mutation::locked_in(tx, packet, input.expected_revision, true, settings).await?;
    let now = Utc::now();
    let ids = input
        .reviewed_field_ids
        .iter()
        .copied()
        .collect::<HashSet<_>>();
    if ids.len() != input.reviewed_field_ids.len()
        || ids
            .iter()
            .any(|id| !claim.normalized.iter().any(|f| f["id"] == json!(id)))
    {
        return Err(Failure("packet_review_fields_invalid"));
    }
    let questions = claim
        .normalized
        .iter()
        .filter(|f| {
            f["id"]
                .as_str()
                .and_then(|s| s.parse::<Uuid>().ok())
                .is_some_and(|id| ids.contains(&id))
        })
        .map(packet_mutation::question)
        .collect::<Result<Vec<_>>>()?;
    packet_mutation::multiple(tx, questions, settings).await?;
    let mut fields = claim.normalized.clone();
    for field in &mut fields {
        if ids.contains(&packet_service::id(&field["id"])?) {
            if !field["effective_answer"]
                .as_str()
                .is_some_and(|s| !s.is_empty())
                || field["validation_status"] != "draft_ready"
            {
                return Err(Failure("packet_review_answer_invalid"));
            }
            field["review_status"] = json!("reviewed");
        }
    }
    let snapshot = packet_record::normalize(Kind::Snapshot, claim.raw["snapshot"].clone())?;
    let eligible = packet_service::readiness(
        &snapshot,
        &fields,
        Flags {
            approved: true,
            ..Default::default()
        },
        "created",
        Utc::now(),
    )?;
    let approve = input.action == "approve";
    if approve {
        if !input.confirm_resume || !input.confirm_destination {
            return Err(Failure("packet_review_confirmation_required"));
        }
        if eligible.state != State::ReadyForManualHandoff {
            return Err(Failure("packet_approval_blocked"));
        }
    }
    packet_archive::advance_in(
        tx,
        &claim.raw,
        &claim.prior_fields,
        input.expected_revision,
        now,
    )
    .await?;
    for field in &fields {
        let id = packet_service::id(&field["id"])?;
        if !ids.contains(&id) {
            continue;
        }
        let updated:Option<Value>=sqlx::query_scalar("UPDATE application_packet_fields SET review_status='reviewed' WHERE packet_id=$1 AND id=$2 RETURNING jsonb_build_object('id',id,'packet_id',packet_id,'answer_revision',answer_revision,'review_status',review_status)").bind(packet).bind(id).fetch_optional(&mut **tx).await.map_err(packet_service::db)?;
        if updated
            != Some(
                json!({"id":id,"packet_id":packet,"answer_revision":field["answer_revision"],"review_status":"reviewed"}),
            )
        {
            return Err(Failure("packet_write_ack_failed"));
        }
    }
    let revision = input.expected_revision + 1;
    let state = if approve {
        "approved_for_manual_handoff"
    } else {
        "reviewed"
    };
    let readiness = if approve {
        "ready_for_manual_handoff"
    } else {
        "needs_review"
    };
    let approved = approve.then_some(revision);
    let updated:Option<Value>=sqlx::query_scalar("UPDATE application_packets SET lifecycle_state=$2,approved_revision=$3,readiness_state=$4 WHERE id=$1 RETURNING jsonb_build_object('id',id,'revision',revision,'lifecycle_state',lifecycle_state,'approved_revision',approved_revision,'readiness_state',readiness_state)").bind(packet).bind(state).bind(approved).bind(readiness).fetch_optional(&mut **tx).await.map_err(packet_service::db)?;
    if updated
        != Some(
            json!({"id":packet,"revision":revision,"lifecycle_state":state,"approved_revision":approved,"readiness_state":readiness}),
        )
    {
        return Err(Failure("packet_write_ack_failed"));
    }
    packet_mutation::event_in(
        tx,
        packet,
        if approve {
            "packet_approved"
        } else {
            "packet_reviewed"
        },
        claim.raw["lifecycle_state"].as_str(),
        state,
        revision,
    )
    .await?;
    if let Some(execution) = execution.as_mut() {
        packet_execution::reviewed_in(tx, execution, &fields).await?;
    }
    let result = packet_service::read_locked_in(tx, packet, settings, Utc::now()).await?;
    packet_notice::notify_in(tx, execution.as_ref(), &result, settings.telegram_notices).await?;
    Ok(result)
}
pub async fn handoff_in(
    tx: &mut Transaction<'_, Postgres>,
    packet: Uuid,
    settings: &Settings,
) -> Result<Value> {
    let data = packet_service::read_locked_in(tx, packet, settings, Utc::now()).await?;
    if matches!(
        data["lifecycle_state"].as_str(),
        Some(
            "user_reported_submitted"
                | "provider_confirmed_submitted"
                | "submitting"
                | "submission_unknown"
                | "withdrawn"
                | "abandoned"
        )
    ) || data["approved_revision"].is_null()
        || data["approved_revision"] != data["revision"]
    {
        return Err(Failure("packet_handoff_approval_required"));
    }
    if data["readiness"]["state"] != "ready_for_manual_handoff"
        || data["readiness"]["stale"] == true
    {
        return Err(Failure("packet_handoff_incomplete"));
    }
    let result = json!({"packet_id":data["id"],"revision":data["revision"],"approved_revision":data["approved_revision"],"company":data["snapshot"]["company_name"],"job_title":data["snapshot"]["job_title"],"application_url":data["snapshot"]["destination"]["application_url"],"destination_kind":data["snapshot"]["destination"]["kind"],"resume":data["snapshot"]["resume"],"professional_links":data["snapshot"]["professional_links"],"fields":data["fields"],"manual_steps":data["readiness"]["manual_steps"],"warnings":data["readiness"]["warnings"],"submission_mode":"manual_handoff","submitted":false});
    static HANDOFF: std::sync::LazyLock<jsonschema::Validator> = std::sync::LazyLock::new(|| {
        let schema: Value = serde_json::from_str(include_str!("../schemas/packet-handoff.json"))
            .expect("frozen handoff schema");
        jsonschema::draft202012::options()
            .should_validate_formats(false)
            .build(&schema)
            .expect("local handoff validator")
    });
    if !HANDOFF.is_valid(&result) {
        return Err(Failure("invalid_packet_saved_record"));
    }
    Ok(result)
}
