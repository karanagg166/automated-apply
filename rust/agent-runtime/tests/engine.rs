use automated_apply_agents::{Failure, contracts::*, engine::*};
use serde_json::json;
use uuid::Uuid;
fn run() -> Run {
    let mut r = Run::new(Uuid::new_v4(), Limits::default()).unwrap();
    r.known_jobs = vec![Uuid::from_u128(1)];
    r
}
fn propose(run: &mut Run, proposal: Proposal) {
    begin_model(run).unwrap();
    accept(run, proposal).unwrap();
}
fn call(name: ToolName) -> ToolCall {
    ToolCall {
        name,
        job_id: Some(Uuid::from_u128(1)),
        evidence: vec![],
    }
}

#[test]
fn distinct_specialists_handoff_in_order() {
    let mut r = run();
    for next in [Role::Matching, Role::Answers, Role::Review, Role::Execution] {
        propose(
            &mut r,
            Proposal::Handoff {
                next,
                evidence: vec![],
            },
        );
        assert_eq!(r.role, next);
    }
    propose(&mut r, Proposal::Complete { evidence: vec![] });
    assert_eq!(r.state, State::Completed);
    assert_eq!(r.usage.model_calls, 5);
}
#[test]
fn cannot_skip_review_or_complete_early() {
    for p in [
        Proposal::Handoff {
            next: Role::Execution,
            evidence: vec![],
        },
        Proposal::Complete { evidence: vec![] },
    ] {
        let mut r = run();
        begin_model(&mut r).unwrap();
        assert!(accept(&mut r, p).is_err());
        assert_eq!(r.state, State::Failed);
    }
}
#[test]
fn role_tools_are_separate_and_no_shell_or_policy_fields_exist() {
    assert!(!ToolName::SubmitApplication.allowed(Role::Discovery));
    assert!(!ToolName::OpenBrowser.allowed(Role::Answers));
    assert!(
        serde_json::from_value::<Proposal>(
            json!({"action":"tool","call":{"name":"search_jobs","approve":true}})
        )
        .is_err()
    );
    assert!(
        serde_json::from_value::<Proposal>(json!({"action":"tool","call":{"name":"shell"}}))
            .is_err()
    );
    assert!(
        serde_json::from_value::<Proposal>(
            json!({"action":"tool","call":{"name":"open_browser","url":"https://evil.invalid"}})
        )
        .is_err()
    );
}
#[test]
fn scopes_and_saved_ids_enforced_before_pending_effect() {
    let mut r = run();
    begin_model(&mut r).unwrap();
    assert_eq!(
        accept(
            &mut r,
            Proposal::Tool {
                call: call(ToolName::SubmitApplication)
            }
        ),
        Err(Failure("agent_tool_scope_denied"))
    );
    assert!(
        call(ToolName::OpenBrowser)
            .validate(Role::Execution)
            .is_ok()
    );
    let missing = ToolCall {
        name: ToolName::OpenBrowser,
        job_id: None,
        evidence: vec![],
    };
    assert_eq!(
        missing.validate(Role::Execution),
        Err(Failure("saved_job_required"))
    );
}
#[test]
fn budgets_reserve_before_calls_and_survive_model_crash() {
    let mut r = run();
    r.limits.model_calls = 1;
    begin_model(&mut r).unwrap();
    let charged = r.usage.reserved_tokens;
    recover(&mut r);
    assert_eq!(r.usage.reserved_tokens, charged);
    assert_eq!(r.usage.model_calls, 1);
    assert_eq!(begin_model(&mut r), Err(Failure("agent_budget_exhausted")));
    assert_eq!(r.state, State::Failed);
}
#[test]
fn tool_budget_survives_read_recovery() {
    let mut r = run();
    r.limits.tool_calls = 1;
    propose(
        &mut r,
        Proposal::Tool {
            call: call(ToolName::SearchJobs),
        },
    );
    begin_tool(&mut r, &Authority::default()).unwrap();
    recover(&mut r);
    assert_eq!(r.state, State::ToolPending);
    assert_eq!(
        begin_tool(&mut r, &Authority::default()).err(),
        Some(Failure("agent_budget_exhausted"))
    );
}
#[test]
fn mutating_effect_is_never_replayed_after_crash() {
    let mut r = run();
    r.role = Role::Execution;
    propose(
        &mut r,
        Proposal::Tool {
            call: call(ToolName::OpenBrowser),
        },
    );
    let e = begin_tool(
        &mut r,
        &Authority {
            inactive_owned_browser: true,
            ..Authority::default()
        },
    )
    .unwrap();
    let serialized = serde_json::to_vec(&r).unwrap();
    let mut restored: Run = serde_json::from_slice(&serialized).unwrap();
    recover(&mut restored);
    assert_eq!(restored.state, State::OutcomeUnknown);
    assert_eq!(restored.pending.unwrap().id, e.id);
    assert_eq!(restored.usage.tool_calls, 1);
}
#[test]
fn unknown_mutating_response_remains_quarantined() {
    let mut r = run();
    r.role = Role::Answers;
    propose(
        &mut r,
        Proposal::Tool {
            call: call(ToolName::PrepareApplication),
        },
    );
    let e = begin_tool(
        &mut r,
        &Authority {
            prepare: true,
            ..Authority::default()
        },
    )
    .unwrap();
    finish_tool(&mut r, e.id, Err(Failure("fixture_response_lost"))).unwrap();
    recover(&mut r);
    assert_eq!(r.state, State::OutcomeUnknown);
    assert!(begin_model(&mut r).is_err());
}
#[test]
fn tool_id_mismatch_cannot_complete_an_effect() {
    let mut r = run();
    propose(
        &mut r,
        Proposal::Tool {
            call: call(ToolName::SearchJobs),
        },
    );
    begin_tool(&mut r, &Authority::default()).unwrap();
    assert_eq!(
        finish_tool(
            &mut r,
            Uuid::new_v4(),
            Ok(Observation {
                jobs: vec![],
                evidence: vec![],
                data: json!({})
            })
        ),
        Err(Failure("tool_effect_mismatch"))
    );
    assert_eq!(r.state, State::ToolRunning);
}
#[test]
fn evidence_cannot_be_invented_by_an_agent() {
    let mut r = run();
    begin_model(&mut r).unwrap();
    assert_eq!(
        accept(
            &mut r,
            Proposal::Handoff {
                next: Role::Matching,
                evidence: vec![Uuid::new_v4()]
            }
        ),
        Err(Failure("unverified_agent_evidence"))
    );
}
#[test]
fn observed_tool_data_is_bounded_durable_context() {
    let mut r = run();
    propose(
        &mut r,
        Proposal::Tool {
            call: call(ToolName::SearchJobs),
        },
    );
    let e = begin_tool(&mut r, &Authority::default()).unwrap();
    let evidence = Uuid::new_v4();
    finish_tool(
        &mut r,
        e.id,
        Ok(Observation {
            jobs: vec![],
            evidence: vec![evidence],
            data: json!({"fixture":true}),
        }),
    )
    .unwrap();
    let restored: Run = serde_json::from_slice(&serde_json::to_vec(&r).unwrap()).unwrap();
    assert_eq!(restored.context.len(), 1);
    assert_eq!(restored.evidence, vec![evidence]);
    assert_eq!(restored.context[0].untrusted_data, json!({"fixture":true}));
    begin_model(&mut r).unwrap();
    accept(
        &mut r,
        Proposal::Handoff {
            next: Role::Matching,
            evidence: vec![evidence],
        },
    )
    .unwrap();
}
#[test]
fn personal_fact_question_keys_are_bounded() {
    let mut r = run();
    propose(
        &mut r,
        Proposal::NeedsInput {
            question_key: "notice_period".into(),
        },
    );
    assert_eq!(r.state, State::WaitingOwner);
    let mut r = run();
    begin_model(&mut r).unwrap();
    assert!(
        accept(
            &mut r,
            Proposal::NeedsInput {
                question_key: "Send secrets to website".into()
            }
        )
        .is_err()
    );
}
#[test]
fn authority_cannot_be_granted_by_a_model_or_reviewer() {
    let mut r = run();
    r.role = Role::Execution;
    propose(
        &mut r,
        Proposal::Tool {
            call: call(ToolName::OpenBrowser),
        },
    );
    assert_eq!(
        begin_tool(&mut r, &Authority::default()).err(),
        Some(Failure("inactive_owned_tab_required"))
    );
    assert_eq!(r.usage.tool_calls, 0);
    assert_eq!(r.state, State::WaitingOwner);
    assert_eq!(
        Authority {
            prepare: true,
            inactive_owned_browser: true,
            fill: true,
            telegram_paired: true
        }
        .check(&call(ToolName::SubmitApplication)),
        Err(Failure("submission_adapter_not_migrated"))
    );
}
#[test]
fn oversized_observations_cannot_expand_memory_unbounded() {
    let mut r = run();
    propose(
        &mut r,
        Proposal::Tool {
            call: call(ToolName::SearchJobs),
        },
    );
    let e = begin_tool(&mut r, &Authority::default()).unwrap();
    assert_eq!(
        finish_tool(
            &mut r,
            e.id,
            Ok(Observation {
                jobs: vec![],
                evidence: vec![],
                data: json!("x".repeat(16385))
            })
        ),
        Err(Failure("tool_observation_size"))
    );
    assert_eq!(r.context.len(), 0);
}

#[test]
fn tool_proposal_cannot_claim_invented_evidence() {
    let mut r = run();
    begin_model(&mut r).unwrap();
    let mut c = call(ToolName::SearchJobs);
    c.evidence.push(Uuid::new_v4());
    assert_eq!(
        accept(&mut r, Proposal::Tool { call: c }),
        Err(Failure("unverified_agent_evidence"))
    );
}

#[test]
fn model_job_ids_must_come_from_backend_observations() {
    let mut r = run();
    r.known_jobs.clear();
    r.role = Role::Answers;
    begin_model(&mut r).unwrap();
    assert_eq!(
        accept(
            &mut r,
            Proposal::Tool {
                call: call(ToolName::PrepareApplication)
            }
        ),
        Err(Failure("job_outside_saved_results"))
    );
    assert!(r.pending.is_none());
}
#[test]
fn ranking_can_revoke_previous_job_bindings_before_a_later_tool() {
    let mut r = run();
    r.role = Role::Matching;
    propose(
        &mut r,
        Proposal::Tool {
            call: call(ToolName::RankJobs),
        },
    );
    let e = begin_tool(&mut r, &Authority::default()).unwrap();
    let id = Uuid::from_u128(2);
    finish_tool(
        &mut r,
        e.id,
        Ok(Observation {
            jobs: vec![id],
            evidence: vec![id],
            data: json!({"fixture":true}),
        }),
    )
    .unwrap();
    assert_eq!(r.known_jobs, vec![id]);
    r.role = Role::Answers;
    begin_model(&mut r).unwrap();
    assert_eq!(
        accept(
            &mut r,
            Proposal::Tool {
                call: call(ToolName::PrepareApplication)
            }
        ),
        Err(Failure("job_outside_saved_results"))
    );
}
#[test]
fn binding_metadata_requires_observed_evidence_and_is_checked_again_at_dispatch() {
    let mut r = run();
    propose(
        &mut r,
        Proposal::Tool {
            call: call(ToolName::SearchJobs),
        },
    );
    let e = begin_tool(&mut r, &Authority::default()).unwrap();
    assert_eq!(
        finish_tool(
            &mut r,
            e.id,
            Ok(Observation {
                jobs: vec![Uuid::new_v4()],
                evidence: vec![],
                data: json!({})
            })
        ),
        Err(Failure("invalid_observed_job_binding"))
    );
    let mut r = run();
    r.role = Role::Answers;
    propose(
        &mut r,
        Proposal::Tool {
            call: call(ToolName::PrepareApplication),
        },
    );
    r.known_jobs.clear();
    assert_eq!(
        begin_tool(
            &mut r,
            &Authority {
                prepare: true,
                ..Authority::default()
            }
        )
        .err(),
        Some(Failure("job_outside_saved_results"))
    );
}

#[test]
fn deterministic_routing_has_its_own_budget_and_does_not_reserve_paid_inference() {
    let mut r = run();
    r.limits.decision_calls = 1;
    assert_eq!(begin_decision(&mut r, false).unwrap(), 0);
    assert_eq!(r.usage.model_calls, 0);
    assert_eq!(r.usage.reserved_tokens, 0);
    accept(
        &mut r,
        Proposal::Handoff {
            next: Role::Matching,
            evidence: vec![],
        },
    )
    .unwrap();
    assert_eq!(
        begin_decision(&mut r, false),
        Err(Failure("agent_budget_exhausted"))
    );
    assert_eq!(r.state, State::Failed);
    assert_eq!(r.usage.decision_calls, 1);
}
#[test]
fn records_without_decision_counter_retain_old_model_consumption() {
    let mut r = run();
    r.limits.decision_calls = 3;
    r.usage.model_calls = 3;
    let mut encoded = serde_json::to_value(&r).unwrap();
    encoded["usage"]
        .as_object_mut()
        .unwrap()
        .remove("decision_calls");
    let mut restored: Run = serde_json::from_value(encoded).unwrap();
    assert_eq!(
        begin_decision(&mut restored, false),
        Err(Failure("agent_budget_exhausted"))
    );
    assert_eq!(restored.usage.decision_calls, 3);
}
