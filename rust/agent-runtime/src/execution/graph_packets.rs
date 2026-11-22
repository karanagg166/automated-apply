//! Owner-selected draft assembly in the existing application packet store.
use super::storage::lock;
use crate::{
    Failure, Result, answer_service,
    contracts::{Authority, Effect, Observation, Run, State, ToolCall, ToolName},
    knowledge::{self, ProfilePin},
    packet_contract, packet_service,
};
use chrono::Utc;
use serde_json::{Value, json};
use sqlx::{Connection, PgConnection, Postgres, Transaction};
use uuid::Uuid;

pub struct PacketTools<'a> {
    pub packets: &'a packet_service::Settings,
    pub answers: &'a answer_service::Settings,
    pub target_job_id: Option<Uuid>,
}

pub(crate) fn authority(call: &ToolCall) -> Result<Authority> {
    match call.name {
        ToolName::PrepareApplication => Ok(Authority {
            prepare: true,
            ..Authority::default()
        }),
        ToolName::InspectApplication => Ok(Authority {
            inspect_saved_packet: true,
            ..Authority::default()
        }),
        _ => Err(Failure("tool_adapter_not_migrated")),
    }
}

async fn scoped_run(
    tx: &mut Transaction<'_, Postgres>,
    run_id: Uuid,
    profile: &ProfilePin,
    effect: &Effect,
    prepare: bool,
) -> Result<Run> {
    let source: Value = sqlx::query_scalar(if prepare {
        "SELECT run FROM rust_agent_runs WHERE id=$1 AND owner='primary'
         AND lease_token IS NOT NULL AND lease_until>clock_timestamp() FOR SHARE"
    } else {
        "SELECT run FROM rust_agent_runs WHERE id=$1 AND owner='primary'
         AND lease_token IS NOT NULL AND lease_until>clock_timestamp()"
    })
    .bind(run_id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(packet_service::db)?
    .ok_or(Failure("agent_lease_or_revision_lost"))?;
    let run: Run = serde_json::from_value(source).map_err(|_| Failure("invalid_agent_record"))?;
    let allowed = run.prepare_packet
        && run.profile.as_ref() == Some(profile)
        && run.state == State::ToolRunning
        && run.pending.as_ref().is_some_and(|pending| {
            pending.id == effect.id
                && pending.call.name == effect.call.name
                && pending.call.job_id == effect.call.job_id
        })
        && effect.call.job_id.is_some_and(|job| {
            run.known_jobs.contains(&job) && run.target_job_id.is_none_or(|target| job == target)
        });
    if !allowed || crate::lifecycle::control(tx).await?.mode != crate::lifecycle::Mode::Running {
        return Err(Failure("owner_preparation_authority_required"));
    }
    Ok(run)
}

impl PacketTools<'_> {
    pub(crate) async fn run(
        &self,
        connection: &mut PgConnection,
        run_id: Uuid,
        profile: &ProfilePin,
        effect: &Effect,
    ) -> Result<Observation> {
        let prepare = match effect.call.name {
            ToolName::PrepareApplication => true,
            ToolName::InspectApplication => false,
            _ => return Err(Failure("tool_adapter_not_migrated")),
        };
        let job = effect.call.job_id.ok_or(Failure("saved_job_required"))?;
        let mut tx = connection.begin().await.map_err(packet_service::db)?;
        let data = async {
            sqlx::query(if prepare {
                "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"
            } else {
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            }).execute(&mut *tx).await.map_err(packet_service::db)?;
            if prepare {
                lock(&mut tx).await?;
            }
            let run = scoped_run(&mut tx, run_id, profile, effect, prepare).await?;
            let current = knowledge::reviewed_profile(&mut tx).await?
                .ok_or(Failure("profile_review_required"))?;
            if current.pin != *profile {
                return Err(Failure("verified_profile_context_changed"));
            }
            let now = Utc::now();
            let (packet, created) = if prepare {
                if !knowledge::job_still_rankable(&mut tx, profile, job).await? {
                    return Ok(json!({"job_id":job,"state":"not_prepared","reason":"saved_job_no_longer_eligible"}));
                }
                let existing: Option<Uuid> = sqlx::query_scalar(
                    "SELECT id FROM application_packets WHERE job_id=$1 AND candidate_profile_id=$2",
                ).bind(job).bind(profile.id).fetch_optional(&mut *tx).await.map_err(packet_service::db)?;
                if let Some(id) = existing {
                    (packet_service::read_locked_in(&mut tx, id, self.packets, now).await?, false)
                } else {
                    let request = packet_contract::normalize(json!({"idempotency_key":format!("graph_{}",effect.id.simple())}), true)?;
                    (packet_service::create_locked_in(&mut tx, job, &request, self.packets, self.answers, now).await?, true)
                }
            } else {
                let id = run.context.iter().rev()
                    .find(|item| item.tool == ToolName::PrepareApplication && item.untrusted_data["job_id"] == json!(job))
                    .and_then(|item| packet_service::id(&item.untrusted_data["packet_id"]).ok())
                    .ok_or(Failure("prepared_packet_required"))?;
                (packet_service::read_snapshot_in(&mut tx, id, self.packets, now).await?, false)
            };
            if packet["candidate_profile_id"] != json!(profile.id)
                || packet["job_id"] != json!(job)
                || (created && packet["candidate_profile_version"] != json!(profile.version))
            {
                return Err(Failure("verified_profile_context_changed"));
            }
            if created {
                // Reuse the packet service's material lock order before pinning confirmation.
                sqlx::query("SELECT key FROM owner_preferences WHERE key='phase1_profile_confirmation' FOR SHARE")
                    .fetch_one(&mut *tx).await.map_err(packet_service::db)?;
            }
            Ok(json!({"job_id":job,"packet_id":packet_service::id(&packet["id"])? ,
                "created":created,"revision":packet["revision"],"platform":packet["platform"],
                "readiness":packet["readiness"]["state"],"lifecycle_state":packet["lifecycle_state"],
                "stale":packet["readiness"]["stale"],"scope":"saved_packet_review"}))
        }.await;
        let data = match data {
            Ok(data) => {
                tx.commit()
                    .await
                    .map_err(|_| Failure("packet_commit_outcome_unknown"))?;
                data
            }
            Err(error) => {
                tx.rollback().await.map_err(packet_service::db)?;
                return Err(error);
            }
        };
        let mut evidence = vec![job, profile.id];
        evidence.extend(packet_service::id(&data["packet_id"]).ok());
        Ok(Observation {
            jobs: vec![],
            evidence,
            data,
        })
    }
}
