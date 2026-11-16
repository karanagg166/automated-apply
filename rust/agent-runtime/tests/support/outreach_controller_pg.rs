//! Deferred unified owner HTTP and loopback-only governed-writer fixtures.
use automated_apply_agents::outreach::controller::{
    self as outreach_controller, Action as OutreachAction,
};
struct OutreachModelFixture {
    calls: AtomicUsize,
    mode: &'static str,
    reference: Value,
    entered: tokio::sync::Notify,
    release: tokio::sync::Notify,
}
async fn outreach_model_response(
    axum::extract::State(state): axum::extract::State<Arc<OutreachModelFixture>>,
    axum::Json(body): axum::Json<Value>,
) -> (axum::http::StatusCode, axum::Json<Value>) {
    state.calls.fetch_add(1, Ordering::SeqCst);
    assert!(body.get("tools").is_none());
    assert!(
        !body
            .to_string()
            .contains("PRIVATE_CONTEXT_PROVENANCE_CANARY")
    );
    assert!(!body.to_string().contains("private-fictional@example.com"));
    if state.mode == "changed" {
        let mut c = connection().await;
        sqlx::query(
            "UPDATE candidate_profiles SET version=version+1 WHERE singleton_key='primary'",
        )
        .execute(&mut c)
        .await
        .unwrap();
    }
    if state.mode == "hold" {
        state.entered.notify_one();
        state.release.notified().await;
    }
    let text = "I implemented Rust workers and REST APIs.";
    let content = json!({"answer":text,"evidence_references":[state.reference],"claims":[{"text":text,"quote":text,"source":state.reference}],"opportunity_claims":[]});
    (
        if state.mode == "rate" {
            axum::http::StatusCode::TOO_MANY_REQUESTS
        } else {
            axum::http::StatusCode::OK
        },
        axum::Json(
            json!({"finish_reason":"COMPLETE","message":{"role":"assistant","content":[{"type":"text","text":content.to_string()}]},"usage":{"tokens":{"input_tokens":100,"output_tokens":10}}}),
        ),
    )
}
async fn outreach_model(
    c: &mut PgConnection,
    mode: &'static str,
) -> (
    automated_apply_agents::answer_service::Settings,
    Arc<OutreachModelFixture>,
    CancellationToken,
    tokio::task::JoinHandle<()>,
) {
    let profile: Uuid =
        sqlx::query_scalar("SELECT id FROM candidate_profiles WHERE singleton_key='primary'")
            .fetch_one(c)
            .await
            .unwrap();
    let state = Arc::new(OutreachModelFixture {
        calls: AtomicUsize::new(0),
        mode,
        reference: json!({"source_type":"verified_project","source_id":format!("{profile}:project:0")}),
        entered: tokio::sync::Notify::new(),
        release: tokio::sync::Notify::new(),
    });
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let stop = CancellationToken::new();
    let shutdown = stop.clone();
    let router = axum::Router::new()
        .route("/v2/chat", axum::routing::post(outreach_model_response))
        .with_state(state.clone());
    let task = tokio::spawn(async move {
        axum::serve(listener, router)
            .with_graceful_shutdown(shutdown.cancelled_owned())
            .await
            .unwrap();
    });
    let settings = automated_apply_agents::answer_service::Settings::from_values(
        &answer_cloud_values(format!("http://{addr}/v2/chat")),
        true,
        BTreeMap::new(),
    )
    .unwrap();
    (settings, state, stop, task)
}
fn outreach_writer_input(job: Uuid, key: &str) -> Value {
    let mut v = outreach_input(Some(job));
    v["use_llm"] = json!(true);
    v["idempotency_key"] = json!(key);
    v
}
async fn outreach_journals(c: &mut PgConnection) -> Value {
    sqlx::query_scalar("SELECT coalesce(jsonb_object_agg(key,value),'{}') FROM owner_preferences WHERE starts_with(key,'outreach_gen:')").fetch_one(c).await.unwrap()
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_controller_local_preview_and_create_share_grounding_without_writer_intents_or_usage()
 {
    let (mut c, job) = outreach_drafts_fixture().await;
    let answers = answer_settings();
    let contacts = contact_settings();
    let service = outreach_controller::Service {
        contacts: &contacts,
        answers: &answers,
    };
    let before = browser_snapshot(&mut c).await;
    let preview = service
        .run(
            &mut c,
            outreach_input(Some(job)),
            OutreachAction::Preview,
            "rest",
        )
        .await
        .unwrap();
    assert_eq!(preview["status"], "draft_ready");
    assert_eq!(browser_snapshot(&mut c).await, before);
    let mut input = outreach_input(Some(job));
    input["idempotency_key"] = json!("fictional_controller_local");
    let result = service
        .run(&mut c, input.clone(), OutreachAction::Create, "rest")
        .await
        .unwrap();
    let replay = service
        .run(&mut c, input, OutreachAction::Create, "rest")
        .await
        .unwrap();
    assert_eq!(result["id"], replay["id"]);
    assert_eq!(outreach_journals(&mut c).await, json!({}));
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM llm_monthly_usage")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_controller_mcp_is_local_even_with_writer_requested_and_configured() {
    let (mut c, job) = outreach_drafts_fixture().await;
    let (answers, state, stop, task) = outreach_model(&mut c, "normal").await;
    let contacts = contact_settings();
    let service = outreach_controller::Service {
        contacts: &contacts,
        answers: &answers,
    };
    let input = outreach_writer_input(job, "fictional_mcp_local");
    let result = service
        .run(&mut c, input, OutreachAction::Create, "mcp")
        .await
        .unwrap();
    assert_eq!(result["created_via"], "mcp");
    assert_eq!(result["provider_metadata"]["used_llm"], false);
    assert_eq!(state.calls.load(Ordering::SeqCst), 0);
    assert_eq!(outreach_journals(&mut c).await, json!({}));
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_controller_writer_requires_stable_key_before_admission_or_provider_work() {
    let (mut c, job) = outreach_drafts_fixture().await;
    let (answers, state, stop, task) = outreach_model(&mut c, "normal").await;
    let contacts = contact_settings();
    let service = outreach_controller::Service {
        contacts: &contacts,
        answers: &answers,
    };
    let mut input = outreach_input(Some(job));
    input["use_llm"] = json!(true);
    assert_eq!(
        service
            .run(&mut c, input, OutreachAction::Create, "rest")
            .await
            .unwrap_err(),
        Failure("outreach_writer_idempotency_key_required")
    );
    assert_eq!(outreach_journals(&mut c).await, json!({}));
    assert_eq!(state.calls.load(Ordering::SeqCst), 0);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_controller_one_grounded_writer_call_creates_original_local_draft_and_replay_is_retained_only()
 {
    let (mut c, job) = outreach_drafts_fixture().await;
    let (answers, state, stop, task) = outreach_model(&mut c, "normal").await;
    let contacts = contact_settings();
    let service = outreach_controller::Service {
        contacts: &contacts,
        answers: &answers,
    };
    let input = outreach_writer_input(job, "fictional_writer_create");
    let result = service
        .run(&mut c, input.clone(), OutreachAction::Create, "rest")
        .await
        .unwrap();
    assert!(result["id"].is_string(), "{result}");
    assert_eq!(result["provider_metadata"]["used_llm"], true);
    assert_eq!(result["eligibility"]["eligible_for_approval"], true);
    assert_eq!(result["approval_status"], "pending_approval");
    let replay = service
        .run(&mut c, input, OutreachAction::Create, "rest")
        .await
        .unwrap();
    assert_eq!(replay["id"], result["id"]);
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        sqlx::query_scalar::<_, i32>(
            "SELECT requests FROM llm_monthly_usage WHERE provider='cohere'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        1
    );
    assert_eq!(
        outreach_journals(&mut c)
            .await
            .as_object()
            .unwrap()
            .values()
            .next()
            .unwrap()["state"],
        "completed"
    );
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_controller_preview_is_retained_without_draft_and_changed_context_never_becomes_fresh_copy()
 {
    let (mut c, job) = outreach_drafts_fixture().await;
    let (answers, state, stop, task) = outreach_model(&mut c, "normal").await;
    let contacts = contact_settings();
    let service = outreach_controller::Service {
        contacts: &contacts,
        answers: &answers,
    };
    let input = outreach_writer_input(job, "fictional_writer_preview");
    let first = service
        .run(&mut c, input.clone(), OutreachAction::Preview, "rest")
        .await
        .unwrap();
    assert_eq!(first["status"], "draft_ready");
    assert_eq!(
        service
            .run(&mut c, input.clone(), OutreachAction::Preview, "rest")
            .await
            .unwrap()["retained_result"],
        true
    );
    sqlx::query("UPDATE companies SET name='Changed fictional employer'")
        .execute(&mut c)
        .await
        .unwrap();
    let changed = service
        .run(&mut c, input, OutreachAction::Preview, "rest")
        .await
        .unwrap();
    assert_eq!(changed["status"], "needs_input");
    assert!(changed["body"].is_null());
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM outreach_logs")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_controller_profile_change_during_model_wait_holds_finding_and_preserves_the_consumed_request()
 {
    let (mut c, job) = outreach_drafts_fixture().await;
    let (answers, state, stop, task) = outreach_model(&mut c, "changed").await;
    let contacts = contact_settings();
    let service = outreach_controller::Service {
        contacts: &contacts,
        answers: &answers,
    };
    let input = outreach_writer_input(job, "fictional_changed_writer");
    let result = service
        .run(&mut c, input.clone(), OutreachAction::Create, "rest")
        .await
        .unwrap();
    assert_eq!(result["status"], "needs_input");
    assert!(result["body"].is_null());
    assert_eq!(
        service
            .run(&mut c, input, OutreachAction::Create, "rest")
            .await
            .unwrap()["status"],
        "needs_input"
    );
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        sqlx::query_scalar::<_, i32>(
            "SELECT requests FROM llm_monthly_usage WHERE provider='cohere'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        1
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM outreach_logs")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_controller_rate_limit_result_is_retained_without_retry_refund_or_draft() {
    let (mut c, job) = outreach_drafts_fixture().await;
    let (answers, state, stop, task) = outreach_model(&mut c, "rate").await;
    let contacts = contact_settings();
    let service = outreach_controller::Service {
        contacts: &contacts,
        answers: &answers,
    };
    let input = outreach_writer_input(job, "fictional_rate_writer");
    let result = service
        .run(&mut c, input.clone(), OutreachAction::Create, "rest")
        .await
        .unwrap();
    assert_eq!(result["error_code"], "rate_limited");
    assert_eq!(
        service
            .run(&mut c, input, OutreachAction::Create, "rest")
            .await
            .unwrap()["retained_result"],
        true
    );
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        sqlx::query_scalar::<_, i32>(
            "SELECT requests FROM llm_monthly_usage WHERE provider='cohere'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        1
    );
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_controller_unconfigured_writer_finishes_once_as_needs_input_and_cannot_enable_sending()
 {
    let (mut c, job) = outreach_drafts_fixture().await;
    let answers = answer_settings();
    let contacts = contact_settings();
    let service = outreach_controller::Service {
        contacts: &contacts,
        answers: &answers,
    };
    let input = outreach_writer_input(job, "fictional_unconfigured_writer");
    let result = service
        .run(&mut c, input.clone(), OutreachAction::Create, "rest")
        .await
        .unwrap();
    assert_eq!(result["status"], "needs_input");
    assert_eq!(result["sending_enabled"], false);
    assert_eq!(result["provider_metadata"]["used_llm"], false);
    assert_eq!(
        service
            .run(&mut c, input, OutreachAction::Create, "rest")
            .await
            .unwrap()["retained_result"],
        true
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM llm_monthly_usage")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_controller_failed_draft_insert_retains_the_model_finding_and_never_reconstructs_dispatch_authority()
 {
    let (mut c, job) = outreach_drafts_fixture().await;
    sqlx::raw_sql("CREATE FUNCTION fixture_outreach_no_draft() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NULL; END $$;CREATE TRIGGER fixture_outreach_no_draft BEFORE INSERT ON outreach_logs FOR EACH ROW EXECUTE FUNCTION fixture_outreach_no_draft()").execute(&mut c).await.unwrap();
    let (answers, state, stop, task) = outreach_model(&mut c, "normal").await;
    let contacts = contact_settings();
    let service = outreach_controller::Service {
        contacts: &contacts,
        answers: &answers,
    };
    let input = outreach_writer_input(job, "fictional_failed_draft_writer");
    assert_eq!(
        service
            .run(&mut c, input.clone(), OutreachAction::Create, "rest")
            .await
            .unwrap_err(),
        Failure("outreach_write_ack_failed")
    );
    let journals = outreach_journals(&mut c).await;
    assert_eq!(
        journals.as_object().unwrap().values().next().unwrap()["state"],
        "finding_retained"
    );
    let retained = service
        .run(&mut c, input, OutreachAction::Create, "rest")
        .await
        .unwrap();
    assert_eq!(
        retained["error_code"],
        "outreach_generation_result_requires_review"
    );
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
    sqlx::raw_sql("DROP TRIGGER fixture_outreach_no_draft ON outreach_logs;DROP FUNCTION fixture_outreach_no_draft()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_controller_failed_admission_ack_calls_no_provider_and_rolls_back_journal() {
    let (mut c, job) = outreach_drafts_fixture().await;
    sqlx::raw_sql("CREATE FUNCTION fixture_outreach_no_intent() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'outreach_gen:') THEN RETURN NULL; END IF;RETURN NEW; END $$;CREATE TRIGGER fixture_outreach_no_intent BEFORE INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_outreach_no_intent()").execute(&mut c).await.unwrap();
    let (answers, state, stop, task) = outreach_model(&mut c, "normal").await;
    let contacts = contact_settings();
    let service = outreach_controller::Service {
        contacts: &contacts,
        answers: &answers,
    };
    assert_eq!(
        service
            .run(
                &mut c,
                outreach_writer_input(job, "fictional_failed_admission"),
                OutreachAction::Create,
                "rest"
            )
            .await
            .unwrap_err(),
        Failure("outreach_write_ack_failed")
    );
    assert_eq!(outreach_journals(&mut c).await, json!({}));
    assert_eq!(state.calls.load(Ordering::SeqCst), 0);
    stop.cancel();
    task.await.unwrap();
    sqlx::raw_sql("DROP TRIGGER fixture_outreach_no_intent ON owner_preferences;DROP FUNCTION fixture_outreach_no_intent()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_controller_interrupted_writer_holds_no_owner_or_profile_lock_and_expired_intent_never_replays()
 {
    let (mut c, job) = outreach_drafts_fixture().await;
    let (answers, state, stop, task) = outreach_model(&mut c, "hold").await;
    let contacts = contact_settings();
    let service = outreach_controller::Service {
        contacts: &contacts,
        answers: &answers,
    };
    let input = outreach_writer_input(job, "fictional_interrupted_writer");
    {
        let future = service.run(&mut c, input.clone(), OutreachAction::Create, "rest");
        tokio::pin!(future);
        tokio::select! {result=&mut future=>panic!("writer returned before hold: {result:?}"),_=state.entered.notified()=>{}}
        let mut other = connection().await;
        sqlx::query("SET lock_timeout='100ms'")
            .execute(&mut other)
            .await
            .unwrap();
        let mut tx = other.begin().await.unwrap();
        sqlx::query(
            "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
        )
        .execute(&mut *tx)
        .await
        .unwrap();
        sqlx::query("SELECT id FROM candidate_profiles WHERE singleton_key='primary' FOR UPDATE")
            .execute(&mut *tx)
            .await
            .unwrap();
        tx.rollback().await.unwrap();
    }
    state.release.notify_one();
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{expires_at}','\"2020-01-01T00:00:00Z\"') WHERE starts_with(key,'outreach_gen:')").execute(&mut c).await.unwrap();
    let before = outreach_journals(&mut c).await;
    assert_eq!(
        service
            .run(&mut c, input, OutreachAction::Create, "rest")
            .await
            .unwrap_err(),
        Failure("outreach_generation_reconciliation_required")
    );
    assert_eq!(outreach_journals(&mut c).await, before);
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_controller_owner_http_preview_create_and_recovery_share_auth_and_budget_boundaries()
 {
    let (mut c, job) = outreach_drafts_fixture().await;
    let (url, stop, task) = http_fixture_values(host_values()).await;
    let http = client();
    let root = format!("{url}/api/v1/outreach/drafts");
    let input = outreach_input(Some(job));
    assert_eq!(
        http.post(&root).json(&input).send().await.unwrap().status(),
        401
    );
    assert_eq!(
        http.post(&root)
            .bearer_auth(HOST_TOKEN)
            .header("x-agent-client", "extension")
            .json(&input)
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    let preview: Value = http
        .post(format!("{root}/preview"))
        .bearer_auth(HOST_TOKEN)
        .json(&input)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(preview["status"], "draft_ready");
    assert_eq!(
        http.get(format!("{root}/preview"))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        405
    );
    assert_eq!(
        http.post(format!("{root}?probe=true"))
            .bearer_auth(HOST_TOKEN)
            .json(&input)
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    let mut writer = input.clone();
    writer["use_llm"] = json!(true);
    assert_eq!(
        http.post(&root)
            .bearer_auth(HOST_TOKEN)
            .json(&writer)
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    let mut create = input;
    create["idempotency_key"] = json!("fictional_http_create_recovery");
    let first: Value = http
        .post(&root)
        .bearer_auth(HOST_TOKEN)
        .json(&create)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    let replay: Value = http
        .post(&root)
        .bearer_auth(HOST_TOKEN)
        .json(&create)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert!(first["id"].is_string(), "{first}");
    assert_eq!(first["id"], replay["id"]);
    assert_eq!(outreach_journals(&mut c).await, json!({}));
    stop.cancel();
    task.await.unwrap().unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_controller_completed_journal_ack_failure_rolls_back_draft_but_keeps_the_separate_finding()
 {
    let (mut c, job) = outreach_drafts_fixture().await;
    sqlx::raw_sql("CREATE FUNCTION fixture_outreach_no_finish() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'outreach_gen:') AND NEW.value->>'state'='completed' THEN RETURN NULL; END IF;RETURN NEW; END $$;CREATE TRIGGER fixture_outreach_no_finish BEFORE UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_outreach_no_finish()").execute(&mut c).await.unwrap();
    let (answers, state, stop, task) = outreach_model(&mut c, "normal").await;
    let contacts = contact_settings();
    let service = outreach_controller::Service {
        contacts: &contacts,
        answers: &answers,
    };
    let input = outreach_writer_input(job, "fictional_failed_finish_writer");
    assert_eq!(
        service
            .run(&mut c, input.clone(), OutreachAction::Create, "rest")
            .await
            .unwrap_err(),
        Failure("outreach_write_ack_failed")
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM outreach_logs")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    assert_eq!(
        outreach_journals(&mut c)
            .await
            .as_object()
            .unwrap()
            .values()
            .next()
            .unwrap()["state"],
        "finding_retained"
    );
    assert_eq!(
        service
            .run(&mut c, input, OutreachAction::Create, "rest")
            .await
            .unwrap()["error_code"],
        "outreach_generation_result_requires_review"
    );
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
    sqlx::raw_sql("DROP TRIGGER fixture_outreach_no_finish ON owner_preferences;DROP FUNCTION fixture_outreach_no_finish()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_controller_retained_preview_refuses_changed_request_or_unknown_stored_response_fields()
 {
    let (mut c, job) = outreach_drafts_fixture().await;
    let (answers, state, stop, task) = outreach_model(&mut c, "normal").await;
    let contacts = contact_settings();
    let service = outreach_controller::Service {
        contacts: &contacts,
        answers: &answers,
    };
    let input = outreach_writer_input(job, "fictional_malformed_retained");
    assert_eq!(
        service
            .run(&mut c, input.clone(), OutreachAction::Preview, "rest")
            .await
            .unwrap()["status"],
        "draft_ready"
    );
    let mut changed = input.clone();
    changed["writing_style"] = json!("friendly");
    assert_eq!(
        service
            .run(&mut c, changed, OutreachAction::Preview, "rest")
            .await
            .unwrap_err(),
        Failure("outreach_generation_intent_conflict")
    );
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{result,private_token}','\"PRIVATE_JOURNAL_TOKEN_CANARY\"') WHERE starts_with(key,'outreach_gen:')").execute(&mut c).await.unwrap();
    assert_eq!(
        service
            .run(&mut c, input, OutreachAction::Preview, "rest")
            .await
            .unwrap_err(),
        Failure("invalid_outreach_saved_record")
    );
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_controller_local_mode_cannot_reuse_an_unknown_writer_create_identity() {
    let (mut c, job) = outreach_drafts_fixture().await;
    let (answers, state, stop, task) = outreach_model(&mut c, "hold").await;
    let contacts = contact_settings();
    let service = outreach_controller::Service {
        contacts: &contacts,
        answers: &answers,
    };
    let mut input = outreach_writer_input(job, "fictional_changed_mode_writer");
    {
        let future = service.run(&mut c, input.clone(), OutreachAction::Create, "rest");
        tokio::pin!(future);
        tokio::select! {result=&mut future=>panic!("writer returned before hold: {result:?}"),_=state.entered.notified()=>{}}
    }
    state.release.notify_one();
    input["use_llm"] = json!(false);
    assert_eq!(
        service
            .run(&mut c, input, OutreachAction::Create, "rest")
            .await
            .unwrap_err(),
        Failure("outreach_idempotency_key_conflict")
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM outreach_logs")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
