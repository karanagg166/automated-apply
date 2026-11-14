use crate::{
    Failure, Result,
    contracts::*,
    engine,
    postgres::{Lease, Store},
};
use std::time::Duration;

// Model calls receive role-specific context; no credentials or policy grants.
#[allow(async_fn_in_trait)]
pub trait Model {
    fn inference_required(&self, _: Role, _: &[Context]) -> bool {
        true
    }
    async fn propose(
        &mut self,
        role: Role,
        context: &[Context],
        budget: ModelBudget,
        store: &mut Store<'_>,
    ) -> Result<Proposal>;
}
#[allow(async_fn_in_trait)]
pub trait Tools {
    /// Must read current backend policy/account/tab state rather than trusting model data.
    async fn authority(&mut self, call: &ToolCall, store: &mut Store<'_>) -> Result<Authority>;
    /// All external writes use this stable effect ID and existing backend admission checks.
    async fn execute(&mut self, effect: &Effect, store: &mut Store<'_>) -> Result<Observation>;
}

/// A bounded single tick; persistence precedes every model/tool call.
/// Fresh lease duration is90s and each external wait is20s, including authority checks.
pub async fn tick(
    store: &mut Store<'_>,
    lease: &mut Lease,
    model: &mut impl Model,
    tools: &mut impl Tools,
) -> Result<()> {
    engine::recover(&mut lease.run);
    store.save(lease).await?;
    match lease.run.state {
        State::Ready => {
            let inference = model.inference_required(lease.run.role, &lease.run.context);
            if engine::begin_decision(&mut lease.run, inference).is_ok() {
                store.save(lease).await?;
                let proposal = tokio::time::timeout(
                    Duration::from_secs(20),
                    model.propose(
                        lease.run.role,
                        &lease.run.context,
                        ModelBudget {
                            maximum_input_tokens: lease.run.limits.max_input_tokens,
                            maximum_output_tokens: lease.run.limits.max_output_tokens,
                        },
                        store,
                    ),
                )
                .await
                .map_err(|_| Failure("agent_model_timeout"))
                .and_then(|x| x);
                match proposal {
                    Ok(proposal) => {
                        let _ = engine::accept(&mut lease.run, proposal);
                    }
                    Err(error) => {
                        lease.run.state = State::Failed;
                        lease.run.diagnostic = Some(error.0.into());
                    }
                }
            }
        }
        State::ToolPending => {
            let call = lease
                .run
                .pending
                .as_ref()
                .ok_or(Failure("pending_tool_required"))?
                .call
                .clone();
            let authority =
                tokio::time::timeout(Duration::from_secs(20), tools.authority(&call, store))
                    .await
                    .map_err(|_| Failure("agent_authority_timeout"))
                    .and_then(|x| x);
            match authority {
                Ok(authority) => {
                    if let Ok(effect) = engine::begin_tool(&mut lease.run, &authority) {
                        store.save(lease).await?; // Fence checked immediately before external dispatch.
                        let result = tokio::time::timeout(
                            Duration::from_secs(20),
                            tools.execute(&effect, store),
                        )
                        .await
                        .map_err(|_| Failure("agent_tool_timeout"))
                        .and_then(|x| x);
                        let _ = engine::finish_tool(&mut lease.run, effect.id, result);
                    }
                }
                Err(error) => {
                    let profile_question = matches!(
                        error.0,
                        "profile_review_required" | "verified_profile_context_changed"
                    );
                    lease.run.state = if profile_question {
                        State::WaitingOwner
                    } else {
                        State::Failed
                    };
                    lease.run.diagnostic = Some(error.0.into());
                    if profile_question {
                        lease.run.question =
                            Some(crate::questions::Question::new("profile_review_required")?);
                    }
                }
            }
        }
        _ => {}
    }
    store.save(lease).await?;
    store.release(lease).await
}
