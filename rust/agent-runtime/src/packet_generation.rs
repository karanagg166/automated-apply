//! Explicit packet drafting on the bounded generation connection. No approval or submission.
use crate::{
    Failure, Result, answer_service, packet_archive, packet_context, packet_fields,
    packet_mutation,
    packet_record::{self, Kind},
    packet_service::{self, Settings},
};
use chrono::Utc;
use serde::Serialize;
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;

#[derive(Serialize)]
pub struct Input {
    pub expected_revision: i32,
    pub rewrite: bool,
}
pub fn request(value: Value) -> Result<Input> {
    let invalid = Failure("invalid_packet_generation_request");
    let body = value
        .as_object()
        .filter(|b| {
            b.keys()
                .all(|k| matches!(k.as_str(), "expected_revision" | "rewrite"))
        })
        .ok_or(invalid)?;
    let revision = crate::profile_contract::pagination_integer(
        body.get("expected_revision").cloned().ok_or(invalid)?,
        1,
        2147483646,
    )
    .map_err(|_| invalid)? as i32;
    let rewrite = body
        .get("rewrite")
        .map(crate::resource_contract::boolean)
        .transpose()
        .map_err(|_| invalid)?
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    Ok(Input {
        expected_revision: revision,
        rewrite,
    })
}
pub(crate) fn route(path: &str) -> Option<(&str, &str)> {
    let (packet, tail) = path
        .strip_prefix("/api/v1/application-packets/")?
        .split_once("/questions/")?;
    let field = tail.strip_suffix("/generate")?;
    (!packet.is_empty() && !packet.contains('/') && !field.is_empty() && !field.contains('/'))
        .then_some((packet, field))
}
struct Initial {
    prepared: packet_fields::Prepared,
    profile: Value,
    original: Value,
    digest: Value,
}
async fn prepare_in(
    tx: &mut Transaction<'_, Postgres>,
    packet: Uuid,
    field: Uuid,
    input: &Input,
    settings: &Settings,
) -> Result<Initial> {
    // A repeatable-read preflight finishes before the answer service can reserve/call a model.
    let raw: Option<Value> =
        sqlx::query_scalar("SELECT to_jsonb(p) FROM application_packets p WHERE id=$1")
            .bind(packet)
            .fetch_optional(&mut **tx)
            .await
            .map_err(packet_service::db)?;
    let raw = raw.ok_or(Failure("packet_not_found"))?;
    if raw["revision"] != input.expected_revision {
        return Err(Failure("packet_revision_conflict"));
    }
    if matches!(
        raw["lifecycle_state"].as_str(),
        Some(
            "user_reported_submitted"
                | "provider_confirmed_submitted"
                | "submitting"
                | "submission_unknown"
                | "withdrawn"
                | "abandoned"
        )
    ) {
        return Err(Failure("packet_closed"));
    }
    let original: Option<Value> = sqlx::query_scalar(
        "SELECT to_jsonb(f) FROM application_packet_fields f WHERE packet_id=$1 AND id=$2",
    )
    .bind(packet)
    .bind(field)
    .fetch_optional(&mut **tx)
    .await
    .map_err(packet_service::db)?;
    let original = packet_record::normalize(
        Kind::Field,
        original.ok_or(Failure("packet_field_not_found"))?,
    )?;
    let selected = raw["resume_resource_id"]
        .as_str()
        .map(|s| {
            s.parse()
                .map_err(|_| Failure("invalid_packet_saved_record"))
        })
        .transpose()?;
    let material = packet_context::load_in(
        tx,
        packet_service::id(&raw["job_id"])?,
        selected,
        &settings.policy,
        Utc::now(),
    )
    .await?;
    let snapshot = packet_record::normalize(Kind::Snapshot, raw["snapshot"].clone())?;
    if snapshot["context_digest"] != material.snapshot["context_digest"] {
        return Err(Failure("packet_context_changed"));
    }
    let profile = material
        .profile
        .as_ref()
        .filter(|p| p["id"] == raw["candidate_profile_id"])
        .ok_or(Failure("packet_profile_changed"))?;
    let question = packet_mutation::question(&original)?;
    packet_mutation::multiple(tx, vec![question.clone()], settings).await?;
    let resume = crate::resources::select_resume(&material.resources, selected)?;
    let prepared = packet_fields::prepare_generation(
        question,
        packet_service::id(&raw["job_id"])?,
        Some(profile),
        Some(&resume),
        original["provenance"]["origin"]
            .as_str()
            .ok_or(Failure("invalid_packet_saved_record"))?,
        input.rewrite,
    )?;
    Ok(Initial {
        prepared,
        profile: profile.clone(),
        original,
        digest: snapshot["context_digest"].clone(),
    })
}
async fn apply_in(
    tx: &mut Transaction<'_, Postgres>,
    packet: Uuid,
    field: Uuid,
    input: &Input,
    initial: &Initial,
    result: &Value,
    settings: &Settings,
) -> Result<Value> {
    let now = Utc::now();
    let claim =
        packet_mutation::locked_in(tx, packet, input.expected_revision, true, settings).await?;
    if claim.material.snapshot["context_digest"] != initial.digest {
        return Err(Failure("packet_context_changed"));
    }
    let current = claim
        .normalized
        .iter()
        .find(|v| v["id"] == json!(field))
        .ok_or(Failure("packet_field_not_found"))?;
    if current != &initial.original {
        return Err(Failure("packet_revision_conflict"));
    }
    packet_archive::advance_in(
        tx,
        &claim.raw,
        &claim.prior_fields,
        input.expected_revision,
        now,
    )
    .await?;
    packet_mutation::replace_answer_in(tx, field, result).await?;
    let snapshot = packet_record::normalize(Kind::Snapshot, claim.raw["snapshot"].clone())?;
    packet_mutation::finish_in(
        tx,
        packet,
        &snapshot,
        &claim.raw,
        "answer_generated",
        settings,
        now,
    )
    .await
}
pub async fn generate(
    connection: &mut PgConnection,
    packet: Uuid,
    field: Uuid,
    input: Input,
    settings: &Settings,
    answers: &answer_service::Settings,
) -> Result<Value> {
    let mut tx = connection.begin().await.map_err(packet_service::db)?;
    sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        .execute(&mut *tx)
        .await
        .map_err(packet_service::db)?;
    let initial = match prepare_in(&mut tx, packet, field, &input, settings).await {
        Ok(initial) => {
            tx.commit()
                .await
                .map_err(|_| Failure("packet_database_error"))?;
            initial
        }
        Err(error) => {
            tx.rollback().await.map_err(packet_service::db)?;
            return Err(error);
        }
    };
    // A saved draft may outlive a rejected packet CAS, matching the existing answer lifecycle.
    let result = if let Some(request) = &initial.prepared.resolution {
        let result = answer_service::generate(connection, json!(request), answers).await?;
        packet_fields::resolved(
            packet_fields::Prepared {
                field: initial.prepared.field.clone(),
                resolution: Some(request.clone()),
            },
            &result,
            &initial.profile,
        )?
    } else {
        initial.prepared.field.clone()
    };
    for attempt in 0..2 {
        let mut tx = connection.begin().await.map_err(packet_service::db)?;
        sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            .execute(&mut *tx)
            .await
            .map_err(packet_service::db)?;
        match apply_in(&mut tx, packet, field, &input, &initial, &result, settings).await {
            Ok(value) => {
                tx.commit()
                    .await
                    .map_err(|_| Failure("packet_commit_outcome_unknown"))?;
                return Ok(value);
            }
            Err(error) => {
                tx.rollback().await.map_err(packet_service::db)?;
                if error == Failure("packet_serialization_rollback") && attempt == 0 {
                    continue;
                }
                return Err(error);
            }
        }
    }
    Err(Failure("packet_revision_conflict"))
}
