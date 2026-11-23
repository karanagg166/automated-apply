//! Revisioned refresh, local checklist additions and human answers. No review or provider action.
use crate::{
    Failure, Result, answer_service, packet_archive, packet_context,
    packet_contract::{self, Prepare, Question},
    packet_fields,
    packet_mutation_contract::Input,
    packet_readiness::{Flags, State},
    packet_record::{self, Kind},
    packet_service::{self, Settings},
};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;

pub(crate) fn question(field: &Value) -> Result<Question> {
    let mut body = field
        .as_object()
        .ok_or(Failure("invalid_packet_saved_record"))?
        .clone();
    body.retain(|k, _| {
        [
            "question",
            "category",
            "field_type",
            "required",
            "max_characters",
            "max_words",
            "constraints",
            "options",
            "writing_style",
        ]
        .contains(&k.as_str())
    });
    packet_contract::question(Value::Object(body))
        .map_err(|_| Failure("invalid_packet_saved_record"))
}
pub(crate) async fn multiple(
    tx: &mut Transaction<'_, Postgres>,
    questions: Vec<Question>,
    settings: &Settings,
) -> Result<()> {
    packet_service::multi_select(
        tx,
        &Prepare {
            resume_resource_id: None,
            questions,
            idempotency_key: None,
        },
        settings,
    )
    .await
}
pub(crate) async fn fields_in(
    tx: &mut Transaction<'_, Postgres>,
    packet: Uuid,
) -> Result<Vec<Value>> {
    sqlx::query_scalar(
        "SELECT to_jsonb(f) FROM application_packet_fields f WHERE packet_id=$1 ORDER BY position",
    )
    .bind(packet)
    .fetch_all(&mut **tx)
    .await
    .map_err(packet_service::db)
}
pub(crate) async fn add_field_in(
    tx: &mut Transaction<'_, Postgres>,
    packet: Uuid,
    position: usize,
    field: &Value,
) -> Result<()> {
    add_fields_in(tx, packet, position, std::slice::from_ref(field)).await
}
pub(crate) async fn add_fields_in(
    tx: &mut Transaction<'_, Postgres>,
    packet: Uuid,
    position: usize,
    fields: &[Value],
) -> Result<()> {
    let mut expected = fields
        .iter()
        .map(|field| packet_service::id(&field["id"]))
        .collect::<Result<Vec<_>>>()?;
    let mut inserted: Vec<Uuid> = sqlx::query_scalar("INSERT INTO application_packet_fields(id,packet_id,position,question,category,field_type,required,max_characters,max_words,constraints,options,writing_style,proposed_answer,human_answer,provenance,validation_status,review_status,requires_review,missing_information,answer_revision)
        SELECT f.id,$1,$2+(entry.ordinality-1)::int,f.question,f.category,f.field_type,f.required,f.max_characters,f.max_words,f.constraints,f.options,f.writing_style,f.proposed_answer,f.human_answer,f.provenance,f.validation_status,f.review_status,f.requires_review,f.missing_information,f.answer_revision
        FROM jsonb_array_elements($3) WITH ORDINALITY AS entry(value,ordinality)
        CROSS JOIN LATERAL jsonb_populate_record(NULL::application_packet_fields,entry.value) f
        ORDER BY entry.ordinality RETURNING id")
        .bind(packet).bind(position as i32).bind(json!(fields)).fetch_all(&mut **tx).await.map_err(packet_service::db)?;
    expected.sort_unstable();
    inserted.sort_unstable();
    if inserted != expected {
        return Err(Failure("packet_write_ack_failed"));
    }
    Ok(())
}
pub(crate) async fn replace_answer_in(
    tx: &mut Transaction<'_, Postgres>,
    field: Uuid,
    replacement: &Value,
) -> Result<()> {
    let changed=sqlx::query("UPDATE application_packet_fields SET proposed_answer=$2,human_answer=$3,provenance=$4,validation_status=$5,missing_information=$6,requires_review=$7,review_status='pending',answer_revision=answer_revision+1 WHERE id=$1")
        .bind(field).bind(replacement["proposed_answer"].as_str()).bind(replacement["human_answer"].as_str()).bind(&replacement["provenance"]).bind(replacement["validation_status"].as_str().ok_or(Failure("invalid_packet_field_record"))?).bind(&replacement["missing_information"]).bind(replacement["requires_review"].as_bool().ok_or(Failure("invalid_packet_field_record"))?).execute(&mut **tx).await.map_err(packet_service::db)?.rows_affected();
    if changed != 1 {
        return Err(Failure("packet_write_ack_failed"));
    }
    Ok(())
}
pub(crate) struct Claim {
    pub raw: Value,
    pub material: packet_context::Built,
    pub prior_fields: Vec<Value>,
    pub normalized: Vec<Value>,
}
pub(crate) struct RunOptions<'a> {
    pub settings: &'a Settings,
    pub answers: &'a answer_service::Settings,
    pub now: DateTime<Utc>,
    pub metadata: Option<&'a Value>,
}
pub(crate) async fn locked_in(
    tx: &mut Transaction<'_, Postgres>,
    packet: Uuid,
    revision: i32,
    fresh: bool,
    settings: &Settings,
) -> Result<Claim> {
    let raw: Option<Value> =
        sqlx::query_scalar("SELECT to_jsonb(p) FROM application_packets p WHERE id=$1 FOR UPDATE")
            .bind(packet)
            .fetch_optional(&mut **tx)
            .await
            .map_err(packet_service::db)?;
    let raw = raw.ok_or(Failure("packet_not_found"))?;
    if raw["revision"] != revision {
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
    let job = packet_service::id(&raw["job_id"])?;
    let selected = raw["resume_resource_id"]
        .as_str()
        .map(|s| {
            s.parse()
                .map_err(|_| Failure("invalid_packet_saved_record"))
        })
        .transpose()?;
    let material = packet_context::load_locked_in(tx, job, selected, &settings.policy).await?;
    let _profile = material
        .profile
        .as_ref()
        .filter(|p| p["id"] == raw["candidate_profile_id"])
        .ok_or(Failure("packet_profile_changed"))?;
    if fresh
        && material.snapshot["context_digest"]
            != packet_record::normalize(Kind::Snapshot, raw["snapshot"].clone())?["context_digest"]
    {
        return Err(Failure("packet_context_changed"));
    }
    let prior_fields = fields_in(tx, packet).await?;
    let normalized = prior_fields
        .iter()
        .map(|f| packet_record::normalize(Kind::Field, f.clone()))
        .collect::<Result<Vec<_>>>()?;
    Ok(Claim {
        raw,
        material,
        prior_fields,
        normalized,
    })
}
pub(crate) async fn run_in(
    tx: &mut Transaction<'_, Postgres>,
    packet: Uuid,
    input: &Input,
    field: Option<Uuid>,
    settings: &Settings,
    answers: &answer_service::Settings,
    now: DateTime<Utc>,
) -> Result<Value> {
    run_with_answer_metadata_in(
        tx,
        packet,
        input,
        field,
        RunOptions {
            settings,
            answers,
            now,
            metadata: None,
        },
    )
    .await
}
/// Owner-question provenance is included in the same guarded field update as
/// the answer, so the database advances answer_revision exactly once.
pub(crate) async fn run_with_answer_metadata_in(
    tx: &mut Transaction<'_, Postgres>,
    packet: Uuid,
    input: &Input,
    field: Option<Uuid>,
    options: RunOptions<'_>,
) -> Result<Value> {
    let RunOptions {
        settings,
        answers,
        now,
        metadata,
    } = options;
    if let Some(metadata) = metadata
        && (!matches!(input, Input::Answer { .. })
            || metadata.as_object().is_none_or(|o| {
                o.keys().any(|k| {
                    !matches!(
                        k.as_str(),
                        "telegram_question"
                            | "answer_expires_at"
                            | "interview_availability"
                            | "telegram_owner_update"
                    )
                })
            }))
    {
        return Err(Failure("invalid_packet_edit_request"));
    }
    if matches!(
        input,
        Input::Refresh {
            refresh_saved_data: false,
            explicit_resume: false,
            ..
        }
    ) {
        return Err(Failure("packet_refresh_required"));
    }
    if let Input::Questions { questions, .. } = input {
        multiple(tx, questions.clone(), settings).await?;
    }
    let Claim {
        raw,
        material,
        prior_fields,
        normalized,
    } = locked_in(
        tx,
        packet,
        input.revision(),
        !matches!(input, Input::Refresh { .. }),
        settings,
    )
    .await?;
    let job = packet_service::id(&raw["job_id"])?;
    let selected = raw["resume_resource_id"]
        .as_str()
        .map(|s| {
            s.parse()
                .map_err(|_| Failure("invalid_packet_saved_record"))
        })
        .transpose()?;
    let profile = material
        .profile
        .as_ref()
        .ok_or(Failure("packet_profile_changed"))?;
    match input {
        Input::Refresh {
            resume_resource_id,
            explicit_resume,
            ..
        } => {
            multiple(
                tx,
                normalized
                    .iter()
                    .map(question)
                    .collect::<Result<Vec<_>>>()?,
                settings,
            )
            .await?;
            let selected = if *explicit_resume {
                *resume_resource_id
            } else {
                selected
            };
            let fresh = packet_context::load_in(tx, job, selected, &settings.policy, now).await?;
            packet_archive::advance_in(tx, &raw, &prior_fields, input.revision(), now).await?;
            let resume = crate::resources::select_resume(&fresh.resources, selected)?;
            let selected_id = resume.selected.as_ref().map(|s| s.resource_id);
            let updated:Option<Value>=sqlx::query_scalar("UPDATE application_packets SET snapshot=$2,platform=$3,resume_resource_id=$4,application_url=$5,candidate_profile_version=$6 WHERE id=$1 RETURNING jsonb_build_object('snapshot',snapshot,'platform',platform,'resume',resume_resource_id,'url',application_url,'version',candidate_profile_version)").bind(packet).bind(&fresh.snapshot).bind(fresh.snapshot["platform"].as_str().unwrap_or("unsupported")).bind(selected_id).bind(fresh.snapshot["destination"]["application_url"].as_str()).bind(profile["version"].as_i64().ok_or(Failure("invalid_packet_context_record"))? as i32).fetch_optional(&mut **tx).await.map_err(packet_service::db)?;
            let expected = json!({"snapshot":fresh.snapshot,"platform":fresh.snapshot["platform"].as_str().unwrap_or("unsupported"),"resume":selected_id,"url":fresh.snapshot["destination"]["application_url"],"version":profile["version"]});
            if updated != Some(expected) {
                return Err(Failure("packet_write_ack_failed"));
            }
            for old in normalized {
                let rebuilt = packet_fields::build_factual_in(
                    tx,
                    question(&old)?,
                    job,
                    Some(profile),
                    Some(&resume),
                    old["provenance"]["origin"]
                        .as_str()
                        .ok_or(Failure("invalid_packet_field_record"))?,
                    answers,
                )
                .await?;
                replace_answer_in(tx, packet_service::id(&old["id"])?, &rebuilt).await?;
            }
            finish_in(
                tx,
                packet,
                &fresh.snapshot,
                &raw,
                "packet_refreshed",
                settings,
                now,
            )
            .await
        }
        Input::Questions { questions, .. } => {
            if prior_fields.len() + questions.len() > 100 {
                return Err(Failure("packet_field_limit"));
            }
            let snapshot = packet_record::normalize(Kind::Snapshot, raw["snapshot"].clone())?;
            let resume = crate::resources::select_resume(&material.resources, selected)?;
            packet_archive::advance_in(tx, &raw, &prior_fields, input.revision(), now).await?;
            for (position, question) in questions.iter().cloned().enumerate() {
                let field = packet_fields::build_factual_in(
                    tx,
                    question,
                    job,
                    Some(profile),
                    Some(&resume),
                    "user_provided",
                    answers,
                )
                .await?;
                add_field_in(tx, packet, prior_fields.len() + position, &field).await?;
            }
            finish_in(
                tx,
                packet,
                &snapshot,
                &raw,
                "questions_added",
                settings,
                now,
            )
            .await
        }
        Input::Answer { answer, .. } => {
            let field = field.ok_or(Failure("invalid_packet_id"))?;
            let mut old = normalized
                .into_iter()
                .find(|f| f["id"] == json!(field))
                .ok_or(Failure("packet_field_not_found"))?;
            multiple(tx, vec![question(&old)?], settings).await?;
            if old["field_type"] == "file" || old["validation_status"] == "file_upload_required" {
                return Err(Failure("packet_upload_attestation_denied"));
            }
            if packet_fields::value_error(&question(&old)?, Some(answer))?.is_some() {
                return Err(Failure("packet_answer_invalid"));
            }
            packet_archive::advance_in(tx, &raw, &prior_fields, input.revision(), now).await?;
            old["human_answer"] = json!(answer);
            old["validation_status"] = json!("draft_ready");
            old["requires_review"] = json!(true);
            old["missing_information"] = json!([]);
            // Preserve raw proposed-answer bytes exactly; a human edit changes only the human answer.
            let original = prior_fields
                .iter()
                .find(|f| f["id"] == json!(field))
                .ok_or(Failure("packet_field_not_found"))?;
            old["proposed_answer"] = original["proposed_answer"].clone();
            old["provenance"] = original["provenance"].clone();
            old["provenance"]["source"] = json!("human");
            old["provenance"]["resolver"] = json!("human");
            if let Some(metadata) = metadata {
                for (k, v) in metadata.as_object().unwrap() {
                    old["provenance"][k] = v.clone();
                }
            }
            replace_answer_in(tx, field, &old).await?;
            let snapshot = packet_record::normalize(Kind::Snapshot, raw["snapshot"].clone())?;
            finish_in(tx, packet, &snapshot, &raw, "answer_edited", settings, now).await
        }
    }
}
pub(crate) async fn finish_in(
    tx: &mut Transaction<'_, Postgres>,
    packet: Uuid,
    snapshot: &Value,
    previous: &Value,
    event: &str,
    settings: &Settings,
    now: DateTime<Utc>,
) -> Result<Value> {
    let fields = fields_in(tx, packet)
        .await?
        .into_iter()
        .map(|f| packet_record::normalize(Kind::Field, f))
        .collect::<Result<Vec<_>>>()?;
    let eligible =
        packet_service::readiness(snapshot, &fields, Flags::default(), "preparing", now)?;
    let lifecycle = if matches!(
        eligible.state,
        State::NeedsInput | State::NeedsResume | State::Unsupported
    ) {
        "needs_input"
    } else {
        "ready_for_review"
    };
    let ready = json!(eligible.state);
    let revision:Option<i32>=sqlx::query_scalar("UPDATE application_packets SET lifecycle_state=$2,readiness_state=$3 WHERE id=$1 RETURNING revision").bind(packet).bind(lifecycle).bind(ready.as_str().ok_or(Failure("invalid_packet_saved_record"))?).fetch_optional(&mut **tx).await.map_err(packet_service::db)?;
    let revision = revision.ok_or(Failure("packet_write_ack_failed"))?;
    if revision as i64
        != previous["revision"]
            .as_i64()
            .ok_or(Failure("invalid_packet_saved_record"))?
            + 1
    {
        return Err(Failure("packet_write_ack_failed"));
    }
    event_in(
        tx,
        packet,
        event,
        previous["lifecycle_state"].as_str(),
        lifecycle,
        revision,
    )
    .await?;
    packet_service::read_in(tx, packet, settings, now).await
}
/// The explicit native inspection may preserve an observed unanswered narrative.
/// No model call or generated rewrite is allowed while the owner transaction is held.
pub(crate) async fn observed_question_in(
    tx: &mut Transaction<'_, Postgres>,
    packet: Uuid,
    revision: i32,
    question: Question,
    settings: &Settings,
    answers: &answer_service::Settings,
    now: DateTime<Utc>,
) -> Result<Value> {
    multiple(tx, vec![question.clone()], settings).await?;
    let claim = locked_in(tx, packet, revision, true, settings).await?;
    if claim.prior_fields.len() >= 100 {
        return Err(Failure("packet_field_limit"));
    }
    let profile = claim
        .material
        .profile
        .as_ref()
        .ok_or(Failure("packet_profile_changed"))?;
    let selected = claim.raw["resume_resource_id"]
        .as_str()
        .map(|s| {
            s.parse()
                .map_err(|_| Failure("invalid_packet_saved_record"))
        })
        .transpose()?;
    let resume = crate::resources::select_resume(&claim.material.resources, selected)?;
    let prepared = packet_fields::prepare_generation(
        question,
        packet_service::id(&claim.raw["job_id"])?,
        Some(profile),
        Some(&resume),
        "user_provided",
        false,
    )?;
    let field = if let Some(request) = prepared.resolution.as_ref() {
        let result = answer_service::form_in(tx, request.clone(), answers, packet).await?;
        packet_fields::resolved(prepared, &result, profile)?
    } else {
        prepared.field
    };
    let snapshot = packet_record::normalize(Kind::Snapshot, claim.raw["snapshot"].clone())?;
    packet_archive::advance_in(tx, &claim.raw, &claim.prior_fields, revision, now).await?;
    add_field_in(tx, packet, claim.prior_fields.len(), &field).await?;
    finish_in(
        tx,
        packet,
        &snapshot,
        &claim.raw,
        "questions_added",
        settings,
        now,
    )
    .await
}
pub(crate) async fn event_in(
    tx: &mut Transaction<'_, Postgres>,
    packet: Uuid,
    event: &str,
    previous: Option<&str>,
    next: &str,
    revision: i32,
) -> Result<()> {
    let event_id = Uuid::new_v4();
    let inserted:Option<Uuid>=sqlx::query_scalar("INSERT INTO application_events(id,packet_id,event_type,previous_state,next_state,packet_revision,origin) VALUES($1,$2,$3,$4,$5,$6,'owner_rest') RETURNING id").bind(event_id).bind(packet).bind(event).bind(previous).bind(next).bind(revision).fetch_optional(&mut **tx).await.map_err(packet_service::db)?;
    if inserted != Some(event_id) {
        return Err(Failure("packet_write_ack_failed"));
    }
    Ok(())
}
