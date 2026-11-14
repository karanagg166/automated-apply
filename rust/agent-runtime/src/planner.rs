//! Deterministic specialists for factual saved-job review. No model process or API call.
use crate::{Failure, Result, contracts::*, postgres::Store, runner::Model};
pub struct SavedReviewPlanner;
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
            return Ok(Proposal::Handoff {
                next: role.next().ok_or(Failure("invalid_agent_handoff"))?,
                evidence: vec![],
            });
        }
        Ok(Proposal::Complete { evidence: vec![] })
    }
}
