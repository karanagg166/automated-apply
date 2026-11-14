//! Deterministic specialists for factual saved-job review. No model process or API call.
use crate::{Failure, Result, contracts::*, postgres::Store, runner::Model};
use serde_json::{Value, json};
pub struct SavedReviewPlanner {
    pub notify: bool,
}
pub struct HybridPlanner {
    pub saved: SavedReviewPlanner,
    pub reviewer: Option<crate::provider::CohereModel>,
}
impl HybridPlanner {
    fn review(&self, role: Role, context: &[Context]) -> bool {
        self.reviewer.is_some()
            && role == Role::Review
            && [
                ToolName::SearchJobs,
                ToolName::RankJobs,
                ToolName::VerifiedContext,
                ToolName::ApplicationHistory,
            ]
            .into_iter()
            .all(|tool| context.iter().any(|c| c.tool == tool))
    }
}
impl Model for HybridPlanner {
    async fn ready_at(
        &mut self,
        role: Role,
        context: &[Context],
        store: &mut Store<'_>,
    ) -> Result<Option<i64>> {
        if self.review(role, context) {
            return self
                .reviewer
                .as_mut()
                .ok_or(Failure("review_model_unavailable"))?
                .ready_at(role, context, store)
                .await;
        }
        Ok(None)
    }
    fn inference_required(&self, role: Role, context: &[Context]) -> bool {
        self.review(role, context)
    }
    async fn propose(
        &mut self,
        role: Role,
        context: &[Context],
        budget: ModelBudget,
        store: &mut Store<'_>,
    ) -> Result<Proposal> {
        if self.review(role, context) {
            let compact = review_context(context)?;
            return self
                .reviewer
                .as_mut()
                .ok_or(Failure("review_model_unavailable"))?
                .propose(role, &compact, budget, store)
                .await;
        }
        self.saved.propose(role, context, budget, store).await
    }
}
/// Mechanical, explicit projection. Full observations remain available to the owner;
/// cloud context includes only bounded source references and never contact/resume data.
fn review_context(context: &[Context]) -> Result<Vec<Context>> {
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
        let compact = review_context(&sources).unwrap();
        assert_eq!(
            compact[0].untrusted_data["jobs"].as_array().unwrap().len(),
            3
        );
        assert_eq!(compact[1].untrusted_data["verified_skill_count"], 1);
        let encoded = serde_json::to_string(&compact).unwrap();
        assert!(!encoded.contains("canary"));
        assert!(!encoded.contains("Rust"));
    }
}
