use crate::{
    Failure, Result,
    contracts::*,
    engine,
    postgres::{Lease, Store},
    provider::{DecisionDispatch, DecisionRequest, DecisionResponse},
};
use std::time::Duration;

// Model calls receive role-specific context; no credentials or policy grants.
#[allow(async_fn_in_trait)]
pub trait Model {
    async fn ready_at(&mut self, _: Role, _: &[Context], _: &mut Store<'_>) -> Result<Option<i64>> {
        Ok(None)
    }
    fn inference_required(&self, _: Role, _: &[Context]) -> bool {
        true
    }
    fn prepare(&self, _: Role, _: &[Context], _: ModelBudget) -> Result<Option<DecisionRequest>> {
        Ok(None)
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
    /// Read-only checks of current backend policy/account/tab state. Never admit or
    /// dispatch a side effect while checking authority or before human approval.
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
    if let Some(dispatch) = begin_tick(store, lease, model, tools).await? {
        finish_decision(store, lease, dispatch.send().await).await?;
    }
    Ok(())
}

pub(crate) async fn begin_tick(
    store: &mut Store<'_>,
    lease: &mut Lease,
    model: &mut impl Model,
    tools: &mut impl Tools,
) -> Result<Option<DecisionDispatch>> {
    engine::recover(&mut lease.run);
    store.save(lease).await?;
    let review_time = if lease.run.limits.human_review
        && lease.run.role == Role::Execution
        && matches!(lease.run.state, State::Ready | State::ToolPending)
    {
        Some(clock(store).await?)
    } else {
        None
    };
    if let Some(now) = review_time
        && crate::graph::requires_review(&lease.run, now)
    {
        if let Err(error) =
            crate::graph::request(&mut lease.run, crate::graph::ApprovalScope::Review, now)
        {
            lease.run.state = State::Failed;
            lease.run.diagnostic = Some(error.0.into());
        }
        store.save(lease).await?;
        store.release(lease).await?;
        return Ok(None);
    }
    match lease.run.state {
        State::Ready => {
            let inference = model.inference_required(lease.run.role, &lease.run.context);
            if inference
                && let Some(at) = model
                    .ready_at(lease.run.role, &lease.run.context, store)
                    .await?
            {
                defer(store, lease, at).await?;
                return Ok(None);
            }
            let budget = ModelBudget {
                maximum_input_tokens: lease.run.limits.max_input_tokens,
                maximum_output_tokens: lease.run.limits.max_output_tokens,
            };
            let prepared = model.prepare(lease.run.role, &lease.run.context, budget);
            if matches!(prepared, Err(Failure("provider_busy"))) {
                // Another service acquired the shared permit after the readiness check.
                let at = clock(store).await?.saturating_add(2);
                defer(store, lease, at).await?;
                return Ok(None);
            }
            lease.run.graph.not_before = None;
            if engine::begin_decision(&mut lease.run, inference).is_ok() {
                store.save(lease).await?;
                let proposal = match prepared {
                    Ok(Some(prepared)) => match prepared.admit(store).await {
                        Ok(dispatch) => return Ok(Some(dispatch)),
                        Err(error) => Err(error),
                    },
                    Ok(None) => tokio::time::timeout(
                        Duration::from_secs(20),
                        model.propose(lease.run.role, &lease.run.context, budget, store),
                    )
                    .await
                    .map_err(|_| Failure("agent_model_timeout"))
                    .and_then(|result| result),
                    Err(error) => Err(error),
                };
                apply_proposal(store, lease, proposal).await?;
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
                    let scope = crate::graph::ApprovalScope::Tool {
                        effect_id: lease
                            .run
                            .pending
                            .as_ref()
                            .ok_or(Failure("pending_tool_required"))?
                            .id,
                    };
                    let now = if authority.requires_human_approval {
                        clock(store).await?
                    } else {
                        0
                    };
                    let human_verified = authority.requires_human_approval
                        && crate::graph::approved(&lease.run, scope, now);
                    if authority.requires_human_approval
                        && authority.check(&call).is_ok()
                        && !human_verified
                    {
                        if let Err(error) = crate::graph::request(&mut lease.run, scope, now) {
                            lease.run.state = State::Failed;
                            lease.run.diagnostic = Some(error.0.into());
                        }
                        store.save(lease).await?;
                        store.release(lease).await?;
                        return Ok(None);
                    }
                    if let Ok(effect) =
                        engine::begin_tool_approved(&mut lease.run, &authority, human_verified)
                    {
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
    store.release(lease).await?;
    Ok(None)
}

pub(crate) async fn finish_decision(
    store: &mut Store<'_>,
    lease: &mut Lease,
    response: DecisionResponse,
) -> Result<()> {
    let proposal = response
        .account(store)
        .await
        .and_then(|proposal| crate::planner::model_decision(lease.run.role, proposal));
    apply_proposal(store, lease, proposal).await?;
    store.save(lease).await?;
    store.release(lease).await
}

async fn apply_proposal(
    store: &mut Store<'_>,
    lease: &mut Lease,
    proposal: Result<Proposal>,
) -> Result<()> {
    match proposal {
        Ok(proposal) => {
            let reviewed = if lease.run.limits.human_review && lease.run.role == Role::Execution {
                crate::graph::approved(
                    &lease.run,
                    crate::graph::ApprovalScope::Review,
                    clock(store).await?,
                )
            } else {
                false
            };
            let result = engine::accept_checked(&mut lease.run, proposal, reviewed);
            if matches!(result, Err(Failure("human_approval_required"))) {
                lease.run.state = State::Ready;
            }
        }
        Err(error) => {
            lease.run.state = State::Failed;
            lease.run.diagnostic = Some(error.0.into());
        }
    }
    Ok(())
}

async fn defer(store: &mut Store<'_>, lease: &mut Lease, until: i64) -> Result<()> {
    lease.run.graph.not_before = Some(until);
    lease.run.graph.node = crate::graph::Node::ProviderWait;
    store.save(lease).await?;
    store.release(lease).await
}
async fn clock(store: &mut Store<'_>) -> Result<i64> {
    sqlx::query_scalar("SELECT EXTRACT(EPOCH FROM clock_timestamp())::bigint")
        .fetch_one(&mut *store.connection)
        .await
        .map_err(|_| Failure("agent_database_error"))
}
