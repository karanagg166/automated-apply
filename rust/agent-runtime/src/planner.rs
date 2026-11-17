//! Deterministic specialists for factual saved-job review. No model process or API call.
use crate::{Failure, Result, contracts::*, postgres::Store, runner::Model};
use serde_json::{Value, json};
pub struct SavedReviewPlanner {
    pub notify: bool,
}
pub struct HybridPlanner {
    saved: SavedReviewPlanner,
    reviewer: Option<crate::provider::CohereModel>,
    pub(crate) roles: Vec<Role>,
}
impl HybridPlanner {
    pub fn for_run(
        policy: Option<&crate::model_policy::Policy>,
        configured: Option<&crate::model_policy::Models>,
        notify: bool,
    ) -> Result<Self> {
        use crate::model_policy::Policy;
        if let Some(policy) = policy {
            policy.validate()?;
        }
        let roles = match policy {
            Some(Policy::Deterministic {}) => vec![],
            Some(policy @ Policy::Cohere { roles, .. }) => {
                if configured.is_none_or(|models| !models.matches(policy)) {
                    return Err(Failure("pinned_model_policy_unavailable"));
                }
                roles.clone()
            }
            // Legacy runtime records only supported model review; a new planner setting
            // must never add a new inference role to them after restart.
            None if configured.is_some() => vec![Role::Review],
            None => vec![],
        };
        Ok(Self {
            saved: SavedReviewPlanner { notify },
            reviewer: configured.map(|models| models.client.clone()),
            roles,
        })
    }
    fn inference_ready(&self, role: Role, context: &[Context]) -> bool {
        if self.reviewer.is_none() || !self.roles.contains(&role) {
            return false;
        }
        let required: &[ToolName] = match role {
            Role::Discovery => &[ToolName::SearchJobs],
            Role::Review => &[
                ToolName::SearchJobs,
                ToolName::RankJobs,
                ToolName::VerifiedContext,
                ToolName::ApplicationHistory,
            ],
            _ => return false,
        };
        required
            .iter()
            .all(|tool| context.iter().any(|c| c.tool == *tool))
    }
}
impl Model for HybridPlanner {
    async fn ready_at(
        &mut self,
        role: Role,
        context: &[Context],
        store: &mut Store<'_>,
    ) -> Result<Option<i64>> {
        if self.inference_ready(role, context) {
            return self
                .reviewer
                .as_mut()
                .ok_or(Failure("agent_model_unavailable"))?
                .ready_at(role, context, store)
                .await;
        }
        Ok(None)
    }
    fn inference_required(&self, role: Role, context: &[Context]) -> bool {
        self.inference_ready(role, context)
    }

    fn prepare(
        &self,
        role: Role,
        context: &[Context],
        budget: ModelBudget,
    ) -> Result<Option<crate::provider::DecisionRequest>> {
        if !self.inference_ready(role, context) {
            return Ok(None);
        }
        let compact = decision_context(context)?;
        self.reviewer
            .as_ref()
            .ok_or(Failure("agent_model_unavailable"))?
            .prepare_decision(role, &compact, budget)
            .map(Some)
    }
    async fn propose(
        &mut self,
        role: Role,
        context: &[Context],
        budget: ModelBudget,
        store: &mut Store<'_>,
    ) -> Result<Proposal> {
        if self.inference_ready(role, context) {
            let compact = decision_context(context)?;
            let proposal = self
                .reviewer
                .as_mut()
                .ok_or(Failure("agent_model_unavailable"))?
                .propose(role, &compact, budget, store)
                .await?;
            return model_decision(role, proposal);
        }
        self.saved.propose(role, context, budget, store).await
    }
}
pub(crate) fn model_decision(role: Role, proposal: Proposal) -> Result<Proposal> {
    let allowed = matches!(
        (role, &proposal),
        (
            Role::Discovery,
            Proposal::Handoff {
                next: Role::Matching,
                ..
            }
        ) | (
            Role::Review,
            Proposal::Handoff {
                next: Role::Execution,
                ..
            }
        ) | (Role::Discovery | Role::Review, Proposal::NeedsInput { .. })
            | (Role::Review, Proposal::Replan { .. })
    );
    if allowed {
        Ok(proposal)
    } else {
        Err(Failure("agent_model_action_denied"))
    }
}
/// Mechanical, explicit projection. Full observations remain available to the owner;
/// cloud context includes only bounded source references and never contact/resume data.
fn decision_context(context: &[Context]) -> Result<Vec<Context>> {
    let mut result = Vec::new();
    for source in context {
        let data = &source.untrusted_data;
        let projected = match source.tool {
            ToolName::SearchJobs => {
                json!({"scope":"saved_results_references_only","profile":data.get("profile"),"scanned":data.get("scanned")})
            }
            ToolName::RankJobs => {
                json!({"scope":"top_three_saved_results_only","excluded_prior_or_unknown":data.get("excluded_prior_or_unknown"),"jobs":data.get("jobs").and_then(Value::as_array).map(|jobs|jobs.iter().take(3).map(|job|json!({"job_id":job.get("job_id"),"score":job.pointer("/ranking/match_score"),"unknown_fields":job.pointer("/ranking/unknown_fields"),"exclusion_reasons":job.pointer("/ranking/exclusion_reasons")})).collect::<Vec<_>>())})
            }
            ToolName::VerifiedContext => {
                json!({"scope":"profile_reference_only","profile":data.get("profile"),"verified_experience_years":data.pointer("/facts/verified_experience_years"),"verified_skill_count":data.pointer("/facts/verified_skills").and_then(Value::as_array).map(Vec::len)})
            }
            ToolName::ApplicationHistory => {
                json!({"scope":"history_reference_only","record_count":data.get("applications").and_then(Value::as_array).map(Vec::len)})
            }
            _ => continue,
        };
        result.push(Context {
            effect_id: source.effect_id,
            tool: source.tool,
            evidence: source.evidence.iter().take(4).copied().collect(),
            untrusted_data: projected,
        });
    }
    if serde_json::to_vec(&result)
        .map_err(|_| Failure("invalid_agent_context"))?
        .len()
        > 3200
    {
        return Err(Failure("review_context_limit"));
    }
    Ok(result)
}
impl Model for SavedReviewPlanner {
    fn inference_required(&self, _: Role, _: &[Context]) -> bool {
        false
    }
    async fn propose(
        &mut self,
        role: Role,
        context: &[Context],
        _: ModelBudget,
        _: &mut Store<'_>,
    ) -> Result<Proposal> {
        let tool = match role {
            Role::Discovery => Some(ToolName::SearchJobs),
            Role::Matching => Some(ToolName::RankJobs),
            Role::Answers => Some(ToolName::VerifiedContext),
            Role::Review => Some(ToolName::ApplicationHistory),
            Role::Execution if self.notify => Some(ToolName::NotifyTelegram),
            Role::Execution => None,
        };
        if let Some(name) = tool {
            if !context.iter().any(|c| c.tool == name) {
                return Ok(Proposal::Tool {
                    call: ToolCall {
                        name,
                        job_id: None,
                        evidence: vec![],
                    },
                });
            }
            if role == Role::Execution {
                return Ok(Proposal::Complete { evidence: vec![] });
            }
            return Ok(Proposal::Handoff {
                next: role.next().ok_or(Failure("invalid_agent_handoff"))?,
                evidence: vec![],
            });
        }
        Ok(Proposal::Complete { evidence: vec![] })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use uuid::Uuid;
    #[test]
    fn cloud_review_projection_excludes_contacts_resumes_free_text_and_extra_results() {
        let sources = vec![
            Context {
                effect_id: Uuid::new_v4(),
                tool: ToolName::RankJobs,
                evidence: vec![],
                untrusted_data: json!({"jobs":(0..8).map(|i|json!({"job_id":Uuid::from_u128(i),"description":"private-free-text-canary","ranking":{"match_score":80,"unknown_fields":[],"exclusion_reasons":[]}})).collect::<Vec<_>>()}),
            },
            Context {
                effect_id: Uuid::new_v4(),
                tool: ToolName::VerifiedContext,
                evidence: vec![],
                untrusted_data: json!({"email":"private-email-canary","resume_text":"private-resume-canary","facts":{"verified_skills":["Rust"],"verified_experience_years":0}}),
            },
        ];
        let compact = decision_context(&sources).unwrap();
        assert_eq!(
            compact[0].untrusted_data["jobs"].as_array().unwrap().len(),
            3
        );
        assert_eq!(compact[1].untrusted_data["verified_skill_count"], 1);
        let encoded = serde_json::to_string(&compact).unwrap();
        assert!(!encoded.contains("canary"));
        assert!(!encoded.contains("Rust"));
    }
    #[test]
    fn model_decisions_cannot_dispatch_tools_or_skip_the_required_handoffs() {
        assert!(
            model_decision(
                Role::Discovery,
                Proposal::Tool {
                    call: ToolCall {
                        name: ToolName::SearchJobs,
                        job_id: None,
                        evidence: vec![]
                    }
                }
            )
            .is_err()
        );
        assert!(model_decision(Role::Review, Proposal::Complete { evidence: vec![] }).is_err());
        assert!(
            model_decision(
                Role::Discovery,
                Proposal::Handoff {
                    next: Role::Review,
                    evidence: vec![]
                }
            )
            .is_err()
        );
        assert!(
            model_decision(
                Role::Discovery,
                Proposal::Handoff {
                    next: Role::Matching,
                    evidence: vec![]
                }
            )
            .is_ok()
        );
        assert!(
            model_decision(
                Role::Review,
                Proposal::Replan {
                    target: Role::Matching,
                    reason: crate::graph::ReplanReason::RecheckEligibility,
                    evidence: vec![]
                }
            )
            .is_ok()
        );
    }
}
