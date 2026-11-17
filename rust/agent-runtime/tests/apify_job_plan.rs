//! Deferred pure original actor/build/run targets and selected evidence. No transport or budget mutation.
use automated_apply_agents::{
    Failure,
    apify_jobs::{
        evidence::{ActorIdentity, Run, VerifiedBuild},
        money::Usd,
        plan::{BuildReview, Plan, Policy},
    },
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
fn now() -> chrono::DateTime<chrono::Utc> {
    chrono::DateTime::parse_from_rfc3339("2026-11-17T00:00:00Z")
        .unwrap()
        .to_utc()
}
fn schema() -> Value {
    json!({"type":"object","additionalProperties":false,"required":["maxItems"],"properties":{"maxItems":{"type":"integer","minimum":1,"maximum":100}}})
}
fn digest(v: &Value) -> String {
    format!(
        "{:x}",
        Sha256::digest(automated_apply_agents::python_json::serialize(v, false, true).as_bytes())
    )
}
fn actor() -> Value {
    json!({"actor_id":"fictional/public-jobs","build":"1.2.3","enabled":true,"reviewed":true,"review_expires_at":"2026-11-17T12:00:00Z","platform_usage_included":true,"account_spending_limit_verified":true,"schema_evidence_url":"https://actor-fixture.example/schema","pricing_evidence_url":"https://actor-fixture.example/pricing","permission_evidence_url":"https://actor-fixture.example/permission","pricing_model":"PAY_PER_EVENT","estimated_per_item_usd":0.001,"field_map":{"limit":"maxItems"}})
}
fn policy(schema: &Value) -> Policy {
    Policy {
        monthly: Usd::parse("5").unwrap(),
        cap: Usd::parse("1").unwrap(),
        allow_paid: true,
        credential_present: true,
        reviewed_build: BuildReview::parse(
            &json!({"build_id":"originalBuild","schema_digest":digest(schema)}),
        )
        .unwrap(),
    }
}
fn plan() -> Plan {
    Plan::build(
        "naukri",
        actor(),
        json!({"limit":100}),
        policy(&schema()),
        now(),
    )
    .unwrap()
}
fn identity(plan: &Plan) -> ActorIdentity {
    ActorIdentity::parse(plan,&json!({"data":{"id":"originalActor","username":"fictional","name":"public-jobs","private":"PRIVATE_ACTOR_CANARY"}})).unwrap()
}
fn build_payload(schema: &Value) -> Value {
    json!({"data":{"id":"originalBuild","actId":"originalActor","buildNumber":"1.2.3","status":"SUCCEEDED","inputSchema":schema.to_string(),"imageDigest":"a".repeat(64),"actorDefinition":{"environmentVariables":{"private":"PRIVATE_ENV_CANARY"}}}})
}
fn run_payload(status: &str) -> Value {
    json!({"data":{"id":"originalRun","actId":"originalActor","buildId":"originalBuild","buildNumber":"1.2.3","status":status,"defaultDatasetId":"originalDataset","startedAt":now().to_rfc3339(),"finishedAt":if status=="SUCCEEDED"{json!(now().to_rfc3339())}else{Value::Null},"usageTotalUsd":0.05,"options":{"build":"1.2.3","timeoutSecs":60,"restartOnError":false,"maxTotalChargeUsd":1,"maxItems":100},"meta":{"private":"PRIVATE_RUN_META_CANARY"},"containerUrl":"https://private-fixture.example/never-read"}})
}
#[test]
fn original_start_requires_matching_actor_and_reviewed_pinned_build_with_bounded_input() {
    let plan = plan();
    let identity = identity(&plan);
    let build = VerifiedBuild::review(&plan, &identity, &build_payload(&schema())).unwrap();
    let target = plan.start(&identity, &build).unwrap();
    assert_eq!(target.method(), "POST");
    assert_eq!(target.path(), "actors/originalActor/runs");
    assert_eq!(target.body(), Some(&json!({"maxItems":100})));
    let query = target
        .query()
        .iter()
        .cloned()
        .collect::<std::collections::BTreeMap<_, _>>();
    assert_eq!(query["maxTotalChargeUsd"], "1.000000");
    assert_eq!(query["timeout"], "60");
    assert_eq!(query["restartOnError"], "false");
    assert!(!build.selected().to_string().contains("CANARY"));
    assert!(!target.path().contains("?"));
    assert_eq!(
        plan.reviewed_build(&identity).unwrap().path(),
        "actor-builds/originalBuild"
    );
}
#[test]
fn paid_opt_in_current_review_and_exact_cap_are_required_before_a_plan_is_constructed() {
    let mut p = policy(&schema());
    p.allow_paid = false;
    assert_eq!(
        Plan::build("naukri", actor(), json!({}), p, now())
            .err()
            .unwrap(),
        Failure("apify_paid_opt_in_required")
    );
    let mut cfg = actor();
    cfg["review_expires_at"] = json!("2026-11-16T12:00:00Z");
    assert!(Plan::build("naukri", cfg, json!({}), policy(&schema()), now()).is_err());
    let mut cfg = actor();
    cfg["estimated_per_item_usd"] = json!(1);
    assert_eq!(
        Plan::build(
            "naukri",
            cfg,
            json!({"limit":100}),
            policy(&schema()),
            now()
        )
        .err()
        .unwrap(),
        Failure("apify_estimate_exceeds_reserved_cap")
    );
    assert_eq!(
        Plan::build(
            "naukri",
            actor(),
            json!({"page":2}),
            policy(&schema()),
            now()
        )
        .err()
        .unwrap(),
        Failure("apify_first_page_only")
    );
    assert!(BuildReview::parse(&json!({"build_id":"https://private-fixture.example/build","schema_digest":"a".repeat(64)})).is_err());
}
#[test]
fn build_schema_changes_remote_references_and_actor_identity_swaps_cannot_authorize_a_start() {
    let plan = plan();
    let original = identity(&plan);
    let build = VerifiedBuild::review(&plan, &original, &build_payload(&schema())).unwrap();
    let other = ActorIdentity::parse(
        &plan,
        &json!({"data":{"id":"otherActor","username":"fictional","name":"public-jobs"}}),
    )
    .unwrap();
    assert_eq!(
        plan.start(&other, &build).err().unwrap(),
        Failure("apify_build_original_binding_changed")
    );
    let mut changed = build_payload(&schema());
    changed["data"]["inputSchema"] = json!(json!({"type":"string"}).to_string());
    assert_eq!(
        VerifiedBuild::review(&plan, &original, &changed)
            .err()
            .unwrap(),
        Failure("apify_reviewed_schema_changed")
    );
    for key in ["$ref", "$dynamicRef", "$recursiveRef", "$vocabulary"] {
        let mut schema = schema();
        schema[key] = json!("https://private-fixture.example/never-read");
        let plan = Plan::build(
            "naukri",
            actor(),
            json!({"limit":100}),
            policy(&schema),
            now(),
        )
        .unwrap();
        let identity = identity(&plan);
        assert_eq!(
            VerifiedBuild::review(&plan, &identity, &build_payload(&schema))
                .err()
                .unwrap(),
            Failure("apify_schema_reference_not_supported")
        );
    }
}
#[test]
fn selected_run_and_dataset_targets_keep_original_ids_and_do_not_claim_final_billing_or_independent_termination()
 {
    let plan = plan();
    let identity = identity(&plan);
    let build = VerifiedBuild::review(&plan, &identity, &build_payload(&schema())).unwrap();
    let run = Run::parse(
        &plan,
        &identity,
        &run_payload("SUCCEEDED"),
        None,
        now(),
        now(),
    )
    .unwrap();
    assert!(run.succeeded());
    let selected = run.selected();
    assert_eq!(selected["billing_final"], false);
    assert_eq!(selected["independent_termination_verified"], false);
    assert!(!selected.to_string().contains("CANARY"));
    assert!(!selected.to_string().contains("containerUrl"));
    assert_eq!(plan.status(&run).unwrap().path(), "actor-runs/originalRun");
    assert_eq!(
        plan.abort(&run).unwrap().path(),
        "actor-runs/originalRun/abort"
    );
    for offset in [0, 50] {
        let target = plan.dataset(&run, &build, offset).unwrap();
        assert_eq!(target.path(), "datasets/originalDataset/items");
        assert!(target.query().contains(&("limit".into(), "50".into())));
    }
    for offset in [1, 100, 10001] {
        assert!(plan.dataset(&run, &build, offset).is_err());
    }
    let running = Run::parse(
        &plan,
        &identity,
        &run_payload("RUNNING"),
        None,
        now(),
        now(),
    )
    .unwrap();
    assert!(!running.terminal());
    assert!(plan.dataset(&running, &build, 0).is_err());
}
#[test]
fn run_actor_build_cap_and_original_dataset_changes_are_rejected_without_following_provider_urls() {
    let plan = plan();
    let identity = identity(&plan);
    let first = Run::parse(
        &plan,
        &identity,
        &run_payload("RUNNING"),
        None,
        now(),
        now(),
    )
    .unwrap();
    for (pointer, value) in [
        ("/data/actId", json!("otherActor")),
        ("/data/buildId", json!("otherBuild")),
        ("/data/options/maxTotalChargeUsd", json!(2)),
        ("/data/id", json!("../../otherRun")),
        (
            "/data/defaultDatasetId",
            json!("https://private-fixture.example/dataset"),
        ),
        ("/data/options/restartOnError", json!(true)),
        ("/data/usageTotalUsd", json!(true)),
    ] {
        let mut payload = run_payload("RUNNING");
        *payload.pointer_mut(pointer).unwrap() = value;
        assert!(
            Run::parse(&plan, &identity, &payload, Some(&first), now(), now()).is_err(),
            "{pointer}"
        );
    }
    let mut changed = run_payload("SUCCEEDED");
    changed["data"]["defaultDatasetId"] = json!("otherDataset");
    assert_eq!(
        Run::parse(&plan, &identity, &changed, Some(&first), now(), now())
            .err()
            .unwrap(),
        Failure("apify_run_original_binding_changed")
    );
}
