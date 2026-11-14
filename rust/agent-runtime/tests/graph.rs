use automated_apply_agents::{
    Failure,
    contracts::*,
    engine,
    graph::{self, Actor, ApprovalScope, ApprovalStatus, Decision, Node, ReplanReason},
};
use serde_json::json;
use uuid::Uuid;
fn run() -> Run {
    Run::new(Uuid::new_v4(), Limits::default()).unwrap()
}
fn review() -> Run {
    let mut r = run();
    r.limits.human_review = true;
    r.role = Role::Execution;
    r.context = [
        ToolName::SearchJobs,
        ToolName::RankJobs,
        ToolName::VerifiedContext,
        ToolName::ApplicationHistory,
    ]
    .into_iter()
    .map(|tool| Context {
        effect_id: Uuid::new_v4(),
        tool,
        evidence: vec![],
        untrusted_data: json!({"fixture":"observed"}),
    })
    .collect();
    r
}
#[test]
fn reviewer_loops_are_bounded_and_never_reset_spent_budgets() {
    let mut r = run();
    r.usage.model_calls = 2;
    r.usage.decision_calls = 2;
    r.usage.reserved_tokens = 768;
    for _ in 0..2 {
        r.role = Role::Review;
        engine::begin_model(&mut r).unwrap();
        engine::accept(
            &mut r,
            Proposal::Replan {
                target: Role::Matching,
                reason: ReplanReason::RecheckEligibility,
                evidence: vec![],
            },
        )
        .unwrap();
    }
    assert_eq!(r.graph.iterations, 2);
    assert_eq!(r.graph.revision, 3);
    assert_eq!(r.usage.model_calls, 4);
    assert_eq!(r.usage.reserved_tokens, 1536);
    r.role = Role::Review;
    engine::begin_model(&mut r).unwrap();
    assert_eq!(
        engine::accept(
            &mut r,
            Proposal::Replan {
                target: Role::Discovery,
                reason: ReplanReason::RefreshSourceFacts,
                evidence: vec![]
            }
        ),
        Err(Failure("agent_replan_limit"))
    );
}
#[test]
fn replan_cannot_replay_prior_external_effect_or_keep_old_job_bindings() {
    let mut r = run();
    r.known_jobs = vec![Uuid::new_v4()];
    r.context.push(Context {
        effect_id: Uuid::new_v4(),
        tool: ToolName::NotifyTelegram,
        evidence: vec![],
        untrusted_data: json!({"pending":true}),
    });
    assert_eq!(
        graph::replan(
            &mut r,
            Role::Discovery,
            ReplanReason::RefreshSourceFacts,
            false
        ),
        Err(Failure("agent_reconciliation_required"))
    );
    r.context.clear();
    graph::replan(&mut r, Role::Matching, ReplanReason::MissingEvidence, false).unwrap();
    assert!(r.known_jobs.is_empty());
}
#[test]
fn approval_is_for_exact_review_and_changed_results_or_expiry_are_rejected() {
    let mut r = review();
    graph::request(&mut r, ApprovalScope::Review, 100).unwrap();
    let id = r.graph.approvals[0].id;
    r.context[0].untrusted_data = json!({"different":true});
    assert_eq!(
        graph::decide(&mut r, id, Decision::Approve, Actor::OwnerApi, 101),
        Err(Failure("agent_approval_context_changed"))
    );
    let mut r = review();
    graph::request(&mut r, ApprovalScope::Review, 100).unwrap();
    let id = r.graph.approvals[0].id;
    assert_eq!(
        graph::decide(&mut r, id, Decision::Approve, Actor::OwnerApi, 3701),
        Err(Failure("agent_approval_expired"))
    );
    graph::decide(&mut r, id, Decision::Reject, Actor::OwnerApi, 3701).unwrap();
    assert_eq!(r.state, State::Stopped);
    assert_eq!(r.graph.approvals[0].status, ApprovalStatus::Rejected);
}
#[test]
fn approval_request_requires_concrete_review_and_core_cannot_skip_it() {
    let mut missing = run();
    missing.limits.human_review = true;
    missing.role = Role::Execution;
    assert_eq!(
        graph::request(&mut missing, ApprovalScope::Review, 1),
        Err(Failure("review_evidence_incomplete"))
    );
    let mut r = review();
    engine::begin_model(&mut r).unwrap();
    assert_eq!(
        engine::accept(&mut r, Proposal::Complete { evidence: vec![] }),
        Err(Failure("human_approval_required"))
    );
}
#[test]
fn changes_keep_usage_and_create_a_new_bounded_plan_revision() {
    let mut r = review();
    r.usage.decision_calls = 8;
    r.usage.tool_calls = 4;
    graph::request(&mut r, ApprovalScope::Review, 100).unwrap();
    let id = r.graph.approvals[0].id;
    graph::decide(&mut r, id, Decision::RequestChanges, Actor::OwnerApi, 101).unwrap();
    assert_eq!(r.role, Role::Discovery);
    assert_eq!(r.graph.iterations, 1);
    assert_eq!(r.graph.revision, 2);
    assert_eq!(r.usage.decision_calls, 8);
    assert_eq!(r.usage.tool_calls, 4);
    assert!(r.context.is_empty());
}
#[test]
fn human_tool_gate_preserves_the_same_unexecuted_effect_without_granting_submission() {
    let mut r = run();
    r.role = Role::Execution;
    r.known_jobs = vec![Uuid::from_u128(1)];
    engine::begin_model(&mut r).unwrap();
    engine::accept(
        &mut r,
        Proposal::Tool {
            call: ToolCall {
                name: ToolName::OpenBrowser,
                job_id: Some(Uuid::from_u128(1)),
                evidence: vec![],
            },
        },
    )
    .unwrap();
    let effect = r.pending.as_ref().unwrap().id;
    let authority = Authority {
        requires_human_approval: true,
        inactive_owned_browser: true,
        ..Authority::default()
    };
    assert_eq!(
        engine::begin_tool(&mut r, &authority).err(),
        Some(Failure("human_approval_required"))
    );
    assert_eq!(r.usage.tool_calls, 0);
    graph::request(&mut r, ApprovalScope::Tool { effect_id: effect }, 100).unwrap();
    let id = r.graph.approvals[0].id;
    graph::decide(&mut r, id, Decision::Approve, Actor::OwnerApi, 101).unwrap();
    assert_eq!(r.pending.as_ref().unwrap().id, effect);
    assert_eq!(r.state, State::ToolPending);
    assert_eq!(
        Authority {
            requires_human_approval: true,
            ..Authority::default()
        }
        .check(&ToolCall {
            name: ToolName::SubmitApplication,
            job_id: Some(Uuid::from_u128(1)),
            evidence: vec![]
        }),
        Err(Failure("submission_adapter_not_migrated"))
    );
}
#[test]
fn graph_checkpoint_survives_serialization_and_terminal_nodes_are_honest() {
    let mut r = review();
    graph::request(&mut r, ApprovalScope::Review, 100).unwrap();
    let encoded = serde_json::to_value(&r).unwrap();
    let restored: Run = serde_json::from_value(encoded).unwrap();
    assert_eq!(graph::node(&restored), Node::HumanApproval);
    assert_eq!(restored.graph.approvals[0].id, r.graph.approvals[0].id);
    r.state = State::OutcomeUnknown;
    assert_eq!(graph::node(&r), Node::Reconciliation);
    r.state = State::Failed;
    assert_eq!(graph::node(&r), Node::Finished);
}

#[test]
fn approval_cannot_authorize_a_different_pinned_agent_model_policy() {
    use automated_apply_agents::model_policy::Policy;
    let mut r = review();
    r.model_policy = Some(Policy::Cohere {
        model: "command-a-plus-05-2026".into(),
        roles: vec![Role::Review],
    });
    graph::request(&mut r, ApprovalScope::Review, 100).unwrap();
    let id = r.graph.approvals[0].id;
    graph::decide(&mut r, id, Decision::Approve, Actor::OwnerApi, 101).unwrap();
    assert!(graph::approved(&r, ApprovalScope::Review, 102));
    r.model_policy = Some(Policy::Cohere {
        model: "command-a-plus-05-2026".into(),
        roles: vec![Role::Discovery, Role::Review],
    });
    assert!(!graph::approved(&r, ApprovalScope::Review, 102));
}
