use crate::{Failure, Result, contracts::*};

pub fn begin_model(run: &mut Run) -> Result<u32> {
    if run.state != State::Ready {
        return Err(Failure("invalid_agent_transition"));
    }
    let reserve = run
        .limits
        .max_input_tokens
        .saturating_add(run.limits.max_output_tokens);
    if run.usage.model_calls >= run.limits.model_calls
        || run.usage.reserved_tokens.saturating_add(reserve) > run.limits.tokens
    {
        run.state = State::Failed;
        run.diagnostic = Some("agent_budget_exhausted".into());
        return Err(Failure("agent_budget_exhausted"));
    }
    run.usage.model_calls += 1;
    run.usage.reserved_tokens += reserve;
    run.state = State::ModelRunning;
    Ok(reserve)
}

pub fn accept(run: &mut Run, proposal: Proposal) -> Result<()> {
    if run.state != State::ModelRunning {
        return Err(Failure("invalid_agent_transition"));
    }
    let result = (|| {
        match proposal {
            Proposal::Tool { call } => {
                call.validate(run.role)?;
                add_evidence(run, call.evidence.clone())?;
                if run.usage.tool_calls >= run.limits.tool_calls {
                    return Err(Failure("agent_budget_exhausted"));
                }
                run.pending = Some(Effect {
                    id: Uuid::new_v4(),
                    call,
                });
                run.state = State::ToolPending;
            }
            Proposal::Handoff { next, evidence } => {
                if run.role.next() != Some(next) {
                    return Err(Failure("invalid_agent_handoff"));
                }
                add_evidence(run, evidence)?;
                run.role = next;
                run.state = State::Ready;
            }
            Proposal::NeedsInput { question_key } => {
                if question_key.is_empty()
                    || question_key.len() > 64
                    || !question_key
                        .bytes()
                        .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_')
                {
                    return Err(Failure("invalid_question_key"));
                }
                run.diagnostic = Some(question_key);
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

pub fn begin_tool(run: &mut Run, authority: &Authority) -> Result<Effect> {
    if run.state != State::ToolPending {
        return Err(Failure("invalid_agent_transition"));
    }
    let effect = run
        .pending
        .clone()
        .ok_or(Failure("pending_tool_required"))?;
    effect.call.validate(run.role)?;
    if let Err(e) = authority.check(&effect.call) {
        run.state = State::WaitingOwner;
        run.diagnostic = Some(e.0.into());
        return Err(e);
    }
    if run.usage.tool_calls >= run.limits.tool_calls {
        run.state = State::Failed;
        run.diagnostic = Some("agent_budget_exhausted".into());
        return Err(Failure("agent_budget_exhausted"));
    }
    run.usage.tool_calls += 1;
    run.state = State::ToolRunning;
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
            run.context.push(context);
            for id in observation.evidence {
                if !run.evidence.contains(&id) {
                    run.evidence.push(id);
                }
            }
            run.pending = None;
            run.state = State::Ready;
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
            run.diagnostic = Some("model_interrupted_budget_retained".into());
        }
        State::ToolRunning => {
            if run
                .pending
                .as_ref()
                .is_some_and(|e| e.call.name.repeatable())
            {
                run.state = State::ToolPending;
                run.diagnostic = Some("read_tool_interrupted".into());
            } else {
                run.state = State::OutcomeUnknown;
                run.diagnostic = Some("external_effect_reconciliation_required".into());
            }
        }
        _ => {}
    }
}
