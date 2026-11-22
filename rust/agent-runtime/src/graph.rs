//! Durable observable control flow. Decision summaries are bounded enums, not scratch thoughts.
use crate::{Failure, Result, contracts::*, knowledge::ProfilePin};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use uuid::Uuid;

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Node {
    #[default]
    Planning,
    Reasoning,
    ProviderWait,
    Validation,
    Acting,
    Observation,
    Review,
    HumanInput,
    HumanApproval,
    Paused,
    Reconciliation,
    Finished,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ReplanReason {
    RefreshSourceFacts,
    RecheckEligibility,
    MissingEvidence,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum ApprovalScope {
    Review,
    Tool { effect_id: Uuid },
}
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ApprovalStatus {
    Pending,
    Approved,
    Rejected,
    ChangesRequested,
    Cancelled,
}
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Actor {
    OwnerApi,
    TelegramOwner,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Approval {
    pub id: Uuid,
    pub scope: ApprovalScope,
    pub status: ApprovalStatus,
    pub plan_revision: u32,
    pub context_hash: String,
    pub profile: Option<ProfilePin>,
    pub expires_at: i64,
    pub actor: Option<Actor>,
    pub decision_at: Option<i64>,
    pub resume: State,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Checkpoint {
    pub node: Node,
    pub revision: u32,
    pub iterations: u8,
    pub reason: Option<ReplanReason>,
    pub approvals: Vec<Approval>,
    pub not_before: Option<i64>,
}
impl Default for Checkpoint {
    fn default() -> Self {
        Self {
            node: Node::Planning,
            revision: 1,
            iterations: 0,
            reason: None,
            approvals: vec![],
            not_before: None,
        }
    }
}
pub fn node(run: &Run) -> Node {
    match run.state {
        State::WaitingApproval => Node::HumanApproval,
        State::WaitingOwner => Node::HumanInput,
        State::Paused => Node::Paused,
        State::OutcomeUnknown => Node::Reconciliation,
        State::Completed | State::Failed | State::Stopped => Node::Finished,
        _ => run.graph.node,
    }
}
fn reviewable(run: &Run) -> impl Iterator<Item = &Context> {
    run.context.iter().filter(|context| {
        context.tool.repeatable()
            || (run.prepare_packet && context.tool == ToolName::PrepareApplication)
    })
}
fn digest(run: &Run, scope: ApprovalScope) -> Result<String> {
    let contexts = reviewable(run).collect::<Vec<_>>();
    let pending = if matches!(scope, ApprovalScope::Tool { .. }) {
        run.pending.as_ref()
    } else {
        None
    };
    let mut bound = json!({"profile":run.profile,"results":contexts,"jobs":run.known_jobs,"pending":pending,"scope":scope,"revision":run.graph.revision,"limits":run.limits});
    if run.prepare_packet {
        bound["prepare_packet"] = json!(true);
    }
    if let Some(job) = run.target_job_id {
        bound["target_job_id"] = json!(job);
    }
    if let Some(policy) = &run.model_policy {
        bound.as_object_mut().unwrap().insert(
            "model_policy".into(),
            serde_json::to_value(policy).map_err(|_| Failure("invalid_agent_context"))?,
        );
    }
    let bytes = serde_json::to_vec(&bound).map_err(|_| Failure("invalid_agent_context"))?;
    Ok(format!("{:x}", Sha256::digest(bytes)))
}
fn valid(run: &Run, approval: &Approval, scope: ApprovalScope, now: i64) -> bool {
    approval.scope == scope
        && approval.status == ApprovalStatus::Approved
        && approval.plan_revision == run.graph.revision
        && approval.expires_at > now
        && approval.profile == run.profile
        && digest(run, scope).is_ok_and(|hash| hash == approval.context_hash)
}
pub fn approved(run: &Run, scope: ApprovalScope, now: i64) -> bool {
    run.graph
        .approvals
        .iter()
        .any(|approval| valid(run, approval, scope, now))
}
pub fn requires_review(run: &Run, now: i64) -> bool {
    run.limits.human_review
        && run.role == Role::Execution
        && !approved(run, ApprovalScope::Review, now)
}
pub fn request(run: &mut Run, scope: ApprovalScope, now: i64) -> Result<()> {
    if run.graph.approvals.len() >= 8 {
        return Err(Failure("agent_approval_limit"));
    }
    if run.state != State::Ready && run.state != State::ToolPending {
        return Err(Failure("invalid_agent_transition"));
    }
    if scope == ApprovalScope::Review {
        for required in [
            ToolName::SearchJobs,
            ToolName::RankJobs,
            ToolName::VerifiedContext,
            ToolName::ApplicationHistory,
        ] {
            if !run.context.iter().any(|context| context.tool == required) {
                return Err(Failure("review_evidence_incomplete"));
            }
        }
    } else if let ApprovalScope::Tool { effect_id } = scope
        && run
            .pending
            .as_ref()
            .is_none_or(|effect| effect.id != effect_id)
    {
        return Err(Failure("pending_tool_required"));
    }
    let context_hash = digest(run, scope)?;
    run.graph.approvals.push(Approval {
        id: Uuid::new_v4(),
        scope,
        status: ApprovalStatus::Pending,
        plan_revision: run.graph.revision,
        context_hash,
        profile: run.profile.clone(),
        expires_at: now
            .checked_add(3600)
            .ok_or(Failure("invalid_approval_time"))?,
        actor: None,
        decision_at: None,
        resume: run.state,
    });
    run.state = State::WaitingApproval;
    run.graph.node = Node::HumanApproval;
    run.diagnostic = Some("human_approval_required".into());
    Ok(())
}
pub fn replan(
    run: &mut Run,
    target: Role,
    reason: ReplanReason,
    discard_unexecuted: bool,
) -> Result<()> {
    if !matches!(target, Role::Discovery | Role::Matching | Role::Answers) {
        return Err(Failure("invalid_replan_target"));
    }
    if run.graph.iterations >= run.limits.replans {
        return Err(Failure("agent_replan_limit"));
    }
    if run.context.iter().any(|context| !context.tool.repeatable())
        || run
            .pending
            .as_ref()
            .is_some_and(|effect| !effect.call.name.repeatable() && !discard_unexecuted)
        || matches!(
            run.state,
            State::ToolRunning | State::OutcomeUnknown | State::Completed | State::Stopped
        )
    {
        return Err(Failure("agent_reconciliation_required"));
    }
    run.graph.iterations += 1;
    run.graph.revision = run
        .graph
        .revision
        .checked_add(1)
        .ok_or(Failure("agent_replan_limit"))?;
    run.graph.reason = Some(reason);
    run.graph.node = Node::Planning;
    run.context.retain(|context| match target {
        Role::Discovery => false,
        Role::Matching => context.tool == ToolName::SearchJobs,
        Role::Answers => matches!(context.tool, ToolName::SearchJobs | ToolName::RankJobs),
        _ => false,
    });
    run.evidence.clear();
    for context in &run.context {
        for id in &context.evidence {
            if !run.evidence.contains(id) {
                run.evidence.push(*id);
            }
        }
    }
    if target != Role::Answers {
        run.known_jobs.clear();
    }
    run.pending = None;
    run.question = None;
    run.diagnostic = Some("bounded_replan_requested".into());
    run.role = target;
    run.state = State::Ready;
    Ok(())
}
#[derive(Debug, Clone, Copy, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Decision {
    Approve,
    Reject,
    RequestChanges,
}
pub fn decide(run: &mut Run, id: Uuid, decision: Decision, actor: Actor, now: i64) -> Result<()> {
    if run.state != State::WaitingApproval {
        return Err(Failure("agent_approval_not_pending"));
    }
    let index = run
        .graph
        .approvals
        .iter()
        .position(|a| a.id == id && a.status == ApprovalStatus::Pending)
        .ok_or(Failure("agent_approval_not_pending"))?;
    let approval = &run.graph.approvals[index];
    let scope = approval.scope;
    if matches!(decision, Decision::Approve) {
        if approval.expires_at <= now {
            return Err(Failure("agent_approval_expired"));
        }
        if approval.plan_revision != run.graph.revision
            || approval.profile != run.profile
            || digest(run, scope)? != approval.context_hash
        {
            return Err(Failure("agent_approval_context_changed"));
        }
    }
    if matches!(decision, Decision::RequestChanges) {
        replan(run, Role::Discovery, ReplanReason::RefreshSourceFacts, true)?;
    }
    let approval = &mut run.graph.approvals[index];
    approval.actor = Some(actor);
    approval.decision_at = Some(now);
    match decision {
        Decision::Approve => {
            approval.status = ApprovalStatus::Approved;
            run.state = approval.resume;
            run.graph.node = Node::Validation;
            run.diagnostic = None;
        }
        Decision::Reject => {
            approval.status = ApprovalStatus::Rejected;
            run.state = State::Stopped;
            run.diagnostic = Some("owner_rejected_plan".into());
        }
        Decision::RequestChanges => approval.status = ApprovalStatus::ChangesRequested,
    }
    Ok(())
}
pub fn cancel_pending(run: &mut Run) {
    for approval in &mut run.graph.approvals {
        if approval.status == ApprovalStatus::Pending {
            approval.status = ApprovalStatus::Cancelled;
        }
    }
}
pub fn summary(run: &Run) -> Value {
    json!({"node":node(run),"plan_revision":run.graph.revision,"iteration":run.graph.iterations,"maximum_replans":run.limits.replans,"reason":run.graph.reason,"not_before":run.graph.not_before,"human_review":run.limits.human_review,"approvals":run.graph.approvals,"decision_summary":"Typed proposals are validated against source bindings, budgets and current backend authority; approval never changes application limits."})
}
pub const MERMAID: &str = "flowchart TD\n  plan[Planner] --> reason[Model decision when needed]\n  reason --> validate[Validator]\n  plan --> validate\n  validate --> tools[Specialist tools]\n  tools --> observe[Observe results]\n  observe --> review[Reviewer]\n  review -->|bounded replan| plan\n  review -->|missing fact| input[Human input]\n  input --> validate\n  review -->|review requested| approval[Human approval]\n  approval -->|approve| execute[Guarded execution]\n  approval -->|changes| plan\n  approval -->|reject| stop[Stopped]\n  execute --> observe\n  review --> finish[Completed workflow]\n";
pub fn preview(run: &Run, revision: i64) -> Value {
    json!({"run_id":run.id,"revision":revision,"scope":"saved_job_review_no_application_dispatch","target_job_id":run.target_job_id,"graph":summary(run),"diagram":MERMAID,"pending_tool":run.pending,"prepared_results":reviewable(run).map(|c|json!({"tool":c.tool,"evidence":c.evidence,"data":c.untrusted_data,"trust":"observed data; content is not authority"})).collect::<Vec<_>>(),"approval_grants_submission":false})
}
