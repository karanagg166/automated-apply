use crate::{Failure, Result, contracts::*};

pub fn begin_model(run: &mut Run) -> Result<u32> {
    begin_decision(run, true)
}
pub fn begin_decision(run: &mut Run, inference: bool) -> Result<u32> {
    if run.state != State::Ready {
        return Err(Failure("invalid_agent_transition"));
    }
    // Old records counted every decision as a model call. Never reset that allowance.
    run.usage.decision_calls = run.usage.decision_calls.max(run.usage.model_calls);
    let reserve = if inference {
        run.limits
            .max_input_tokens
            .saturating_add(run.limits.max_output_tokens)
    } else {
        0
    };
    if run.usage.decision_calls >= run.limits.decision_calls
        || (inference && run.usage.model_calls >= run.limits.model_calls)
        || run.usage.reserved_tokens.saturating_add(reserve) > run.limits.tokens
    {
        run.state = State::Failed;
        run.diagnostic = Some("agent_budget_exhausted".into());
        return Err(Failure("agent_budget_exhausted"));
    }
    run.usage.decision_calls += 1;
    if inference {
        run.usage.model_calls += 1;
    }
    run.usage.reserved_tokens += reserve;
    run.state = State::ModelRunning;
    run.graph.node = if inference {
        crate::graph::Node::Reasoning
    } else if run.role == Role::Review {
        crate::graph::Node::Review
    } else {
        crate::graph::Node::Planning
    };
    Ok(reserve)
}

pub fn accept(run: &mut Run, proposal: Proposal) -> Result<()> {
    accept_checked(run, proposal, false)
}
pub(crate) fn accept_checked(
    run: &mut Run,
    proposal: Proposal,
    review_verified: bool,
) -> Result<()> {
    if run.state != State::ModelRunning {
        return Err(Failure("invalid_agent_transition"));
    }
    if run.limits.human_review && run.role == Role::Execution && !review_verified {
        return Err(Failure("human_approval_required"));
    }
    let result = (|| {
        match proposal {
            Proposal::Replan {
                target,
                reason,
                evidence,
            } => {
                if run.role != Role::Review {
                    return Err(Failure("reviewer_replan_required"));
                }
                add_evidence(run, evidence)?;
                crate::graph::replan(run, target, reason, false)?;
            }
            Proposal::Tool { call } => {
                call.validate(run.role)?;
                add_evidence(run, call.evidence.clone())?;
                check_source_binding(run, &call)?;
                if run.usage.tool_calls >= run.limits.tool_calls {
                    return Err(Failure("agent_budget_exhausted"));
                }
                run.pending = Some(Effect {
                    id: Uuid::new_v4(),
                    call,
                });
                run.state = State::ToolPending;
                run.graph.node = crate::graph::Node::Validation;
            }
            Proposal::Handoff { next, evidence } => {
                if run.role.next() != Some(next) {
                    return Err(Failure("invalid_agent_handoff"));
                }
                add_evidence(run, evidence)?;
                run.role = next;
                run.state = State::Ready;
                run.graph.node = if next == Role::Review {
                    crate::graph::Node::Review
                } else {
                    crate::graph::Node::Planning
                };
            }
            Proposal::NeedsInput { question_key } => {
                let question = crate::questions::Question::new(&question_key)?;
                run.diagnostic = Some(question_key);
                run.question = Some(question);
                run.state = State::WaitingOwner;
            }
            Proposal::Complete { evidence } => {
                if run.role != Role::Execution {
                    return Err(Failure("review_and_execution_handoffs_required"));
                }
                add_evidence(run, evidence)?;
                run.state = State::Completed;
            }
        }
        Ok(())
    })();
    if let Err(error) = result {
        run.state = State::Failed;
        run.diagnostic = Some(error.0.into());
    }
    result
}
use uuid::Uuid;
fn add_evidence(run: &mut Run, evidence: Vec<Uuid>) -> Result<()> {
    // Only evidence already observed through tools can be handed between agents.
    if evidence.len() > 12 || evidence.iter().any(|id| !run.evidence.contains(id)) {
        return Err(Failure("unverified_agent_evidence"));
    }
    Ok(())
}

fn check_source_binding(run: &Run, call: &ToolCall) -> Result<()> {
    if matches!(
        call.name,
        ToolName::PrepareApplication
            | ToolName::InspectApplication
            | ToolName::OpenBrowser
            | ToolName::FillApplication
            | ToolName::SubmitApplication
    ) && call.job_id.is_some_and(|id| !run.known_jobs.contains(&id))
    {
        return Err(Failure("job_outside_saved_results"));
    }
    Ok(())
}
fn invalid_observation(run: &mut Run, code: &'static str) -> Failure {
    run.state = if run.pending.as_ref().unwrap().call.name.repeatable() {
        State::Failed
    } else {
        State::OutcomeUnknown
    };
    run.diagnostic = Some(code.into());
    Failure(code)
}

pub fn begin_tool(run: &mut Run, authority: &Authority) -> Result<Effect> {
    begin_tool_approved(run, authority, false)
}
pub(crate) fn begin_tool_approved(
    run: &mut Run,
    authority: &Authority,
    human_verified: bool,
) -> Result<Effect> {
    if run.state != State::ToolPending {
        return Err(Failure("invalid_agent_transition"));
    }
    let effect = run
        .pending
        .clone()
        .ok_or(Failure("pending_tool_required"))?;
    effect.call.validate(run.role)?;
    check_source_binding(run, &effect.call)?;
    if let Err(e) = authority.check(&effect.call) {
        run.state = if e.0.ends_with("not_migrated") {
            State::Failed
        } else {
            State::WaitingOwner
        };
        run.diagnostic = Some(e.0.into());
        return Err(e);
    }
    if authority.requires_human_approval && !human_verified {
        return Err(Failure("human_approval_required"));
    }
    if run.usage.tool_calls >= run.limits.tool_calls {
        run.state = State::Failed;
        run.diagnostic = Some("agent_budget_exhausted".into());
        return Err(Failure("agent_budget_exhausted"));
    }
    run.usage.tool_calls += 1;
    run.state = State::ToolRunning;
    run.graph.node = crate::graph::Node::Acting;
    Ok(effect)
}

pub fn finish_tool(run: &mut Run, id: Uuid, result: Result<Observation>) -> Result<()> {
    if run.state != State::ToolRunning || run.pending.as_ref().is_none_or(|e| e.id != id) {
        return Err(Failure("tool_effect_mismatch"));
    }
    match result {
        Ok(observation) => {
            if observation.evidence.len() > 12
                || run.evidence.len() + observation.evidence.len() > 128
            {
                run.state = if run.pending.as_ref().unwrap().call.name.repeatable() {
                    State::Failed
                } else {
                    State::OutcomeUnknown
                };
                run.diagnostic = Some("agent_evidence_limit".into());
                return Err(Failure("agent_evidence_limit"));
            }
            if observation.jobs.len() > 10
                || observation
                    .jobs
                    .iter()
                    .any(|id| !observation.evidence.contains(id))
            {
                return Err(invalid_observation(run, "invalid_observed_job_binding"));
            }
            let update_jobs = matches!(
                run.pending.as_ref().unwrap().call.name,
                ToolName::SearchJobs | ToolName::RankJobs
            );
            if !update_jobs && !observation.jobs.is_empty() {
                return Err(invalid_observation(run, "unexpected_observed_job_binding"));
            }
            let observed_jobs = observation.jobs;
            let context = Context {
                effect_id: id,
                tool: run.pending.as_ref().unwrap().call.name,
                evidence: observation.evidence.clone(),
                untrusted_data: observation.data,
            };
            let size = serde_json::to_vec(&context)
                .map_err(|_| Failure("invalid_tool_observation"))?
                .len();
            let previous = serde_json::to_vec(&run.context)
                .map_err(|_| Failure("invalid_tool_observation"))?
                .len();
            if size > 16384 || previous + size > 65536 {
                run.state = if context.tool.repeatable() {
                    State::Failed
                } else {
                    State::OutcomeUnknown
                };
                run.diagnostic = Some("tool_observation_size".into());
                return Err(Failure("tool_observation_size"));
            }
            if update_jobs {
                run.known_jobs = observed_jobs;
            }
            run.context.push(context);
            for id in observation.evidence {
                if !run.evidence.contains(&id) {
                    run.evidence.push(id);
                }
            }
            run.pending = None;
            run.state = State::Ready;
            run.graph.node = crate::graph::Node::Observation;
        }
        Err(error) => {
            run.state = if run.pending.as_ref().unwrap().call.name.repeatable() {
                State::Failed
            } else {
                State::OutcomeUnknown
            };
            run.diagnostic = Some(error.0.into());
        }
    }
    Ok(())
}

/// Called only after obtaining a fresh fenced lease. No authority or budget is refunded.
pub fn recover(run: &mut Run) {
    match run.state {
        State::ModelRunning => {
            run.state = State::Ready;
            run.graph.node = if run.role == Role::Review {
                crate::graph::Node::Review
            } else {
                crate::graph::Node::Planning
            };
            run.diagnostic = Some("model_interrupted_budget_retained".into());
        }
        State::ToolRunning => {
            if run
                .pending
                .as_ref()
                .is_some_and(|e| e.call.name.repeatable())
            {
                run.state = State::ToolPending;
                run.graph.node = crate::graph::Node::Validation;
                run.diagnostic = Some("read_tool_interrupted".into());
            } else {
                run.state = State::OutcomeUnknown;
                run.diagnostic = Some("external_effect_reconciliation_required".into());
            }
        }
        _ => {}
    }
}
