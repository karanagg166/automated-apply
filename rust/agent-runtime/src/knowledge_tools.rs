//! Actual read-only agent tools. External actions require their separately migrated adapters.
use crate::{
    Failure, Result,
    contracts::*,
    knowledge::{self, ProfilePin},
    postgres::Store,
    runner::Tools,
};
use serde_json::json;

pub struct KnowledgeTools {
    pub profile: ProfilePin,
}
impl Tools for KnowledgeTools {
    async fn authority(&mut self, call: &ToolCall, store: &mut Store<'_>) -> Result<Authority> {
        if !matches!(
            call.name,
            ToolName::SearchJobs
                | ToolName::RankJobs
                | ToolName::VerifiedContext
                | ToolName::ApplicationHistory
        ) {
            return Err(Failure("tool_adapter_not_migrated"));
        }
        let current = knowledge::reviewed_profile(store.connection)
            .await?
            .ok_or(Failure("profile_review_required"))?;
        if current.pin != self.profile {
            return Err(Failure("verified_profile_context_changed"));
        }
        Ok(Authority::default())
    }
    async fn execute(&mut self, effect: &Effect, store: &mut Store<'_>) -> Result<Observation> {
        match effect.call.name {
            ToolName::SearchJobs | ToolName::RankJobs => {
                let saved =
                    knowledge::rank_saved_naukri(store.connection, &self.profile, 10).await?;
                let jobs = saved.jobs.iter().map(|j| j.job_id).collect::<Vec<_>>();
                let mut evidence = jobs.clone();
                evidence.push(self.profile.id);
                let data =
                    serde_json::to_value(saved).map_err(|_| Failure("invalid_saved_results"))?;
                Ok(Observation {
                    evidence,
                    data,
                    jobs,
                })
            }
            ToolName::VerifiedContext => {
                let profile = knowledge::reviewed_profile(store.connection)
                    .await?
                    .ok_or(Failure("profile_review_required"))?;
                if profile.pin != self.profile {
                    return Err(Failure("verified_profile_context_changed"));
                }
                Ok(Observation {
                    evidence: vec![profile.pin.id],
                    jobs: vec![],
                    data: json!({"profile":profile.pin,"facts":profile.facts,"scope":"verified_profile_matching_only"}),
                })
            }
            ToolName::ApplicationHistory => Ok(Observation {
                evidence: vec![self.profile.id],
                jobs: vec![],
                data: knowledge::application_history(store.connection, &self.profile).await?,
            }),
            _ => Err(Failure("tool_adapter_not_migrated")),
        }
    }
}
