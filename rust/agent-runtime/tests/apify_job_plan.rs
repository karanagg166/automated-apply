//! Deferred pure original actor/build/run targets and selected evidence. No transport or budget mutation.
use automated_apply_agents::apify_jobs::read_context::ReadContext;
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
fn checkpoint(status: &str) -> Value {
    let plan = plan();
    let identity = identity(&plan);
    let run = Run::parse(&plan, &identity, &run_payload(status), None, now(), now()).unwrap();
    json!({"schema":1,"request_id":"10000000-0000-0000-0000-000000000001","state":"failed","start_intent":true,"start_attempted":true,
        "configuration_hash":plan.context(),"source":"naukri","effective_query":automated_apply_agents::job_sources::contract::query(json!({"limit":100})).unwrap(),
        "started_at":now().to_rfc3339(),"expires_at":(now()+chrono::Duration::seconds(75)).to_rfc3339(),
        "selected_actor":identity.selected(),"selected_run":run.selected(),"selected_run_hash":automated_apply_agents::python_json::digest(&run.selected()),
        "reservation":{"provider":"apify","state":"run_attached","provider_run_id":"originalRun"}})
}
fn read_now() -> chrono::DateTime<chrono::Utc> {
    now() + chrono::Duration::seconds(80)
}
#[test]
fn selected_original_options_round_trip_into_pure_get_context_without_new_start_or_private_metadata()
 {
    let saved = checkpoint("RUNNING");
    let context = ReadContext::from_retained(plan(), &saved, read_now()).unwrap();
    assert_eq!(context.run_id(), "originalRun");
    assert_eq!(context.selected_run(), saved["selected_run"]);
    assert_eq!(
        context.selected_run()["acknowledged_options"],
        run_payload("RUNNING")["data"]["options"]
    );
    assert!(!context.selected_run().to_string().contains("CANARY"));
    let target = context.status_target().unwrap();
    assert_eq!(target.method(), "GET");
    assert_eq!(target.path(), "actor-runs/originalRun");
    assert!(
        target
            .query()
            .contains(&("waitForFinish".into(), "10".into()))
    );
    assert!(context.build_target().is_err());
}
#[test]
fn pure_read_context_requires_expired_original_intent_and_refuses_stale_or_missing_acknowledged_run()
 {
    let saved = checkpoint("RUNNING");
    assert_eq!(
        ReadContext::from_retained(plan(), &saved, now() + chrono::Duration::seconds(74))
            .err()
            .unwrap(),
        Failure("apify_read_original_still_active")
    );
    assert!(
        ReadContext::from_retained(plan(), &saved, now() + chrono::Duration::seconds(75)).is_ok()
    );
    assert_eq!(
        ReadContext::from_retained(plan(), &saved, now() + chrono::Duration::hours(25))
            .err()
            .unwrap(),
        Failure("apify_read_original_expired")
    );
    for field in ["selected_run", "selected_actor", "selected_run_hash"] {
        let mut missing = saved.clone();
        missing.as_object_mut().unwrap().remove(field);
        assert!(
            ReadContext::from_retained(plan(), &missing, read_now()).is_err(),
            "{field}"
        );
    }
}
#[test]
fn pure_read_context_refuses_changed_original_source_query_scope_run_attachment_or_start_evidence()
{
    for (pointer, value) in [
        ("/source", json!("instahyre")),
        ("/configuration_hash", json!("a".repeat(64))),
        ("/effective_query/limit", json!(10)),
        ("/reservation/provider_run_id", json!("foreignRun")),
        ("/reservation/state", json!("reserved")),
        ("/start_attempted", Value::Null),
        ("/start_intent", json!(false)),
        ("/state", json!("finding_retained")),
        ("/request_id", json!("00000000-0000-0000-0000-000000000000")),
    ] {
        let mut saved = checkpoint("RUNNING");
        *saved.pointer_mut(pointer).unwrap() = value;
        assert!(
            ReadContext::from_retained(plan(), &saved, read_now()).is_err(),
            "{pointer}"
        );
    }
}
#[test]
fn pure_read_context_refuses_hash_consistent_but_promoted_or_invalid_selected_options_and_identity()
{
    for (pointer, value) in [
        ("/selected_run/billing_final", json!(true)),
        (
            "/selected_run/independent_termination_verified",
            json!(true),
        ),
        (
            "/selected_run/acknowledged_options/restartOnError",
            json!(true),
        ),
        ("/selected_run/acknowledged_options/timeoutSecs", json!(61)),
        ("/selected_run/acknowledged_options/maxItems", json!(101)),
        (
            "/selected_actor/identity_basis",
            json!("guessed_latest_run"),
        ),
        ("/selected_actor/id", json!("foreignActor")),
    ] {
        let mut saved = checkpoint("RUNNING");
        *saved.pointer_mut(pointer).unwrap() = value;
        saved["selected_run_hash"] = json!(automated_apply_agents::python_json::digest(
            &saved["selected_run"]
        ));
        assert!(
            ReadContext::from_retained(plan(), &saved, read_now()).is_err(),
            "{pointer}"
        );
    }
}
#[test]
fn read_status_preserves_original_run_actor_build_start_cap_dataset_and_acknowledged_options() {
    for (field, value) in [
        ("id", json!("foreignRun")),
        ("actId", json!("foreignActor")),
        ("buildId", json!("foreignBuild")),
        (
            "startedAt",
            json!((now() + chrono::Duration::seconds(1)).to_rfc3339()),
        ),
        ("defaultDatasetId", json!("foreignDataset")),
    ] {
        let mut context =
            ReadContext::from_retained(plan(), &checkpoint("RUNNING"), read_now()).unwrap();
        let before = context.selected_run();
        let mut body = run_payload("SUCCEEDED");
        body["data"][field] = value;
        assert!(context.accept_status(&body, read_now()).is_err(), "{field}");
        assert_eq!(context.selected_run(), before);
    }
    for (field, value) in [
        ("maxTotalChargeUsd", json!(0.5)),
        ("timeoutSecs", json!(30)),
        ("maxItems", json!(50)),
    ] {
        let mut context =
            ReadContext::from_retained(plan(), &checkpoint("RUNNING"), read_now()).unwrap();
        let before = context.selected_run();
        let mut body = run_payload("SUCCEEDED");
        body["data"]["options"][field] = value;
        assert!(context.accept_status(&body, read_now()).is_err(), "{field}");
        assert_eq!(context.selected_run(), before);
    }
}
#[test]
fn read_build_and_dataset_targets_require_fresh_success_original_build_and_bounded_offsets() {
    let mut context =
        ReadContext::from_retained(plan(), &checkpoint("SUCCEEDED"), read_now()).unwrap();
    assert!(context.build_target().is_err());
    context
        .accept_status(&run_payload("SUCCEEDED"), read_now())
        .unwrap();
    assert_eq!(context.build_target().unwrap().method(), "GET");
    assert_eq!(
        context.build_target().unwrap().path(),
        "actor-builds/originalBuild"
    );
    let mut foreign = build_payload(&schema());
    foreign["data"]["actId"] = json!("foreignActor");
    assert!(context.accept_build(&foreign).is_err());
    let build = context.accept_build(&build_payload(&schema())).unwrap();
    for offset in [0, 50] {
        let target = context.dataset_target(&build, offset).unwrap();
        assert_eq!(target.method(), "GET");
        assert_eq!(target.path(), "datasets/originalDataset/items");
    }
    for offset in [1, 100, 5000] {
        assert!(context.dataset_target(&build, offset).is_err());
    }
    assert!(
        context
            .accept_status(&run_payload("RUNNING"), read_now())
            .is_err()
    );
}
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
