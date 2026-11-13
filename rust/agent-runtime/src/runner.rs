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
    async fn propose(
        &mut self,
        role: Role,
        context: &[Context],
        budget: ModelBudget,
    ) -> Result<Proposal>;
}
#[allow(async_fn_in_trait)]
pub trait Tools {
    /// Must read current backend policy/account/tab state rather than trusting model data.
    async fn authority(&mut self, call: &ToolCall) -> Result<Authority>;
    /// All external writes use this stable effect ID and existing backend admission checks.
    async fn execute(&mut self, effect: &Effect) -> Result<Observation>;
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
            if engine::begin_model(&mut lease.run).is_ok() {
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
            let authority = tokio::time::timeout(Duration::from_secs(20), tools.authority(&call))
                .await
                .map_err(|_| Failure("agent_authority_timeout"))
                .and_then(|x| x);
            match authority {
                Ok(authority) => {
                    if let Ok(effect) = engine::begin_tool(&mut lease.run, &authority) {
                        store.save(lease).await?; // Fence checked immediately before external dispatch.
                        let result =
                            tokio::time::timeout(Duration::from_secs(20), tools.execute(&effect))
                                .await
                                .map_err(|_| Failure("agent_tool_timeout"))
                                .and_then(|x| x);
                        let _ = engine::finish_tool(&mut lease.run, effect.id, result);
                    }
                }
                Err(error) => {
                    lease.run.state = State::WaitingOwner;
                    lease.run.diagnostic = Some(error.0.into());
                }
            }
        }
        _ => {}
    }
    store.save(lease).await?;
    store.release(lease).await
}
