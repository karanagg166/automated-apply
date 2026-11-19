// Deferred local ledger, CAS/grounding and complete-row rollback fixtures.
use automated_apply_agents::outreach::drafts as outreach_drafts;
async fn outreach_draft_guard(c: &mut PgConnection) {
    // Run the actual final additive guard; timestamp/revision semantics must not be mocked.
    let source = include_str!("../../../../supabase/fresh_public/001_phase1_public.sql");
    let body = source
        .rsplit("CREATE OR REPLACE FUNCTION public.phase4a_draft_guard()")
        .next()
        .unwrap()
        .split("\n$$;")
        .next()
        .unwrap();
    sqlx::raw_sql(sqlx::AssertSqlSafe(format!("CREATE OR REPLACE FUNCTION public.phase4a_draft_guard(){body}\n$$;CREATE TRIGGER phase4a_draft_guard BEFORE INSERT OR UPDATE ON outreach_logs FOR EACH ROW EXECUTE FUNCTION public.phase4a_draft_guard()"))).execute(&mut *c).await.unwrap();
}
async fn outreach_drafts_fixture() -> (PgConnection, Uuid) {
    let (mut c, job) = outreach_context_fixture().await;
    outreach_history_schema(&mut c).await;
    outreach_draft_guard(&mut c).await;
    (c, job)
}
async fn outreach_create(c: &mut PgConnection, job: Uuid, key: &str) -> Result<Value> {
    let mut input = outreach_input(Some(job));
    input["idempotency_key"] = json!(key);
    outreach_drafts::create_local(c, input, "rest", &contact_settings()).await
}
async fn outreach_draft_call(
    c: &mut PgConnection,
    id: Uuid,
    action: &str,
    input: Option<Value>,
) -> Result<Value> {
    let path = format!("/api/v1/outreach/drafts/{id}{action}");
    let body = input
        .as_ref()
        .map(|v| serde_json::to_vec(v).unwrap())
        .unwrap_or_default();
    let method = if input.is_none() {
        "GET"
    } else if action.is_empty() {
        "PATCH"
    } else {
        "POST"
    };
    outreach_drafts::dispatch(
        c,
        outreach_drafts::route(&path).unwrap(),
        method,
        None,
        &body,
        &contact_settings(),
    )
    .await
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_drafts_create_replay_approve_edit_and_reject_preserve_original_history_without_sending()
 {
    let (mut c, job) = outreach_drafts_fixture().await;
    let created = outreach_create(&mut c, job, "fictional_local_draft")
        .await
        .unwrap();
    let id = created["id"].as_str().unwrap().parse::<Uuid>().unwrap();
    assert_eq!(created["draft_revision"], 1);
    assert_eq!(created["approval_status"], "pending_approval");
    assert_eq!(created["eligibility"]["eligible_for_approval"], true);
    assert_eq!(created["sending_enabled"], false);
    let before = outreach_snapshot(&mut c).await;
    let replay = outreach_create(&mut c, job, "fictional_local_draft")
        .await
        .unwrap();
    assert_eq!(replay, created);
    assert_eq!(outreach_snapshot(&mut c).await, before);
    let approved =
        outreach_draft_call(&mut c, id, "/approve", Some(json!({"expected_revision":1})))
            .await
            .unwrap();
    assert_eq!(approved["draft_revision"], 2);
    assert_eq!(approved["approved_revision"], 2);
    assert_eq!(approved["eligibility"]["approval_current"], true);
    assert_eq!(approved["eligibility"]["email_send_ready"], false);
    let edited = outreach_draft_call(
        &mut c,
        id,
        "",
        Some(json!({"expected_revision":2,"body":created["body"]})),
    )
    .await
    .unwrap();
    assert_eq!(edited["draft_revision"], 3);
    assert_eq!(edited["approval_status"], "pending_approval");
    assert!(edited["approved_revision"].is_null());
    assert_eq!(edited["eligibility"]["approval_current"], false);
    let rejected = outreach_draft_call(&mut c, id, "/reject", Some(json!({"expected_revision":3})))
        .await
        .unwrap();
    assert_eq!(rejected["draft_revision"], 4);
    assert_eq!(rejected["approval_status"], "rejected");
    assert_eq!(rejected["eligibility"]["eligible_for_approval"], false);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM outreach_send_attempts")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_drafts_changed_request_conflicts_but_changed_evidence_replay_returns_the_original_draft_stale()
 {
    let (mut c, job) = outreach_drafts_fixture().await;
    let created = outreach_create(&mut c, job, "fictional_idempotent_draft")
        .await
        .unwrap();
    let mut input = outreach_input(Some(job));
    input["idempotency_key"] = json!("fictional_idempotent_draft");
    input["writing_style"] = json!("friendly");
    assert_eq!(
        outreach_drafts::create_local(&mut c, input, "rest", &contact_settings())
            .await
            .unwrap_err(),
        Failure("outreach_idempotency_key_conflict")
    );
    sqlx::query("UPDATE candidate_profiles SET summary='Changed source after original creation'")
        .execute(&mut c)
        .await
        .unwrap();
    let replay = outreach_create(&mut c, job, "fictional_idempotent_draft")
        .await
        .unwrap();
    assert_eq!(replay["id"], created["id"]);
    assert_eq!(replay["body"], created["body"]);
    assert_eq!(replay["eligibility"]["eligible_for_approval"], false);
    assert!(
        replay["eligibility"]["blockers"]
            .as_array()
            .unwrap()
            .contains(&json!("material_evidence_changed_regenerate_draft"))
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM outreach_logs")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        1
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_drafts_stale_revisions_and_unsupported_edits_cannot_be_approved() {
    let (mut c, job) = outreach_drafts_fixture().await;
    let created = outreach_create(&mut c, job, "fictional_edit_draft")
        .await
        .unwrap();
    let id = created["id"].as_str().unwrap().parse::<Uuid>().unwrap();
    let before = outreach_snapshot(&mut c).await;
    for action in ["", "/approve", "/reject"] {
        let mut input = json!({"expected_revision":99});
        if action.is_empty() {
            input["body"] = created["body"].clone();
        }
        assert_eq!(
            outreach_draft_call(&mut c, id, action, Some(input))
                .await
                .unwrap_err(),
            Failure("outreach_draft_revision_conflict")
        );
    }
    assert_eq!(outreach_snapshot(&mut c).await, before);
    let edited = outreach_draft_call(
        &mut c,
        id,
        "",
        Some(json!({"expected_revision":1,"body":"I hold a fictional unsupported credential."})),
    )
    .await
    .unwrap();
    assert!(
        edited["eligibility"]["blockers"]
            .as_array()
            .unwrap()
            .contains(&json!("unsupported_edited_claim_requires_grounding"))
    );
    assert_eq!(
        outreach_draft_call(&mut c, id, "/approve", Some(json!({"expected_revision":2})))
            .await
            .unwrap_err(),
        Failure("outreach_draft_not_eligible")
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_drafts_recipient_changes_clear_approval_and_require_current_canonical_business_evidence()
 {
    let (mut c, job) = outreach_drafts_fixture().await;
    let created = outreach_create(&mut c, job, "fictional_recipient_draft")
        .await
        .unwrap();
    let id = created["id"].as_str().unwrap().parse::<Uuid>().unwrap();
    let edited = outreach_draft_call(
        &mut c,
        id,
        "",
        Some(json!({"expected_revision":1,"recipient_email":"other@contact-fixture.example"})),
    )
    .await
    .unwrap();
    assert_eq!(edited["recipient_email"], "other@contact-fixture.example");
    assert_eq!(edited["eligibility"]["approval_current"], false);
    assert!(
        edited["eligibility"]["blockers"]
            .as_array()
            .unwrap()
            .contains(&json!("recipient_changed_or_unverified"))
    );
    assert_eq!(
        outreach_draft_call(&mut c, id, "/approve", Some(json!({"expected_revision":2})))
            .await
            .unwrap_err(),
        Failure("outreach_draft_not_eligible")
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_drafts_every_historical_attempt_or_sent_timestamp_locks_edits_and_decisions_without_refund()
 {
    let (mut c, job) = outreach_drafts_fixture().await;
    let created = outreach_create(&mut c, job, "fictional_reserved_draft")
        .await
        .unwrap();
    let id = created["id"].as_str().unwrap().parse::<Uuid>().unwrap();
    for status in [
        "prepared",
        "attempting",
        "outcome_unknown",
        "failed_before_send",
        "accepted_by_gmail",
    ] {
        sqlx::query("INSERT INTO outreach_send_attempts(id,draft_id,draft_revision,subject,body,status) VALUES($1,$2,1,'Fictional original subject','Fictional original body',$3) ON CONFLICT(draft_id) DO UPDATE SET status=excluded.status").bind(Uuid::from_u128(980001)).bind(id).bind(status).execute(&mut c).await.unwrap();
        let before = outreach_snapshot(&mut c).await;
        for action in ["", "/approve", "/reject"] {
            let mut input = json!({"expected_revision":1});
            if action.is_empty() {
                input["subject"] = json!("Reviewed subject");
            }
            assert_eq!(
                outreach_draft_call(&mut c, id, action, Some(input))
                    .await
                    .unwrap_err(),
                Failure("outreach_send_reserved_draft_immutable")
            );
        }
        assert_eq!(outreach_snapshot(&mut c).await, before);
    }
    sqlx::query("DELETE FROM outreach_send_attempts")
        .execute(&mut c)
        .await
        .unwrap();
    sqlx::query("ALTER TABLE outreach_logs DISABLE TRIGGER phase4a_draft_guard")
        .execute(&mut c)
        .await
        .unwrap();
    sqlx::query("UPDATE outreach_logs SET sent_at=clock_timestamp() WHERE id=$1")
        .bind(id)
        .execute(&mut c)
        .await
        .unwrap();
    sqlx::query("ALTER TABLE outreach_logs ENABLE TRIGGER phase4a_draft_guard")
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        outreach_draft_call(&mut c, id, "/reject", Some(json!({"expected_revision":1})))
            .await
            .unwrap_err(),
        Failure("outreach_send_reserved_draft_immutable")
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_drafts_complete_update_ack_detects_before_and_after_trigger_corruption_and_rolls_back()
 {
    let (mut c, job) = outreach_drafts_fixture().await;
    let created = outreach_create(&mut c, job, "fictional_ack_draft")
        .await
        .unwrap();
    let id = created["id"].as_str().unwrap().parse::<Uuid>().unwrap();
    let before = outreach_snapshot(&mut c).await;
    for timing in ["BEFORE", "AFTER"] {
        let trigger = if timing == "BEFORE" {
            "NEW.resume_version='fictional-corruption'; RETURN NEW;"
        } else {
            "IF pg_trigger_depth()=1 THEN UPDATE outreach_logs SET resume_version='fictional-corruption', approval_status='pending_approval', approved_at=NULL, approval_hash=NULL, approved_revision=NULL WHERE id=NEW.id; END IF; RETURN NEW;"
        };
        let sql = format!(
            "CREATE FUNCTION fixture_outreach_corrupt() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {trigger} END $$;CREATE TRIGGER fixture_outreach_corrupt {timing} UPDATE ON outreach_logs FOR EACH ROW EXECUTE FUNCTION fixture_outreach_corrupt()"
        );
        sqlx::raw_sql(sqlx::AssertSqlSafe(sql))
            .execute(&mut c)
            .await
            .unwrap();
        assert_eq!(
            outreach_draft_call(&mut c, id, "/approve", Some(json!({"expected_revision":1})))
                .await
                .unwrap_err(),
            Failure("outreach_write_ack_failed"),
            "{timing} trigger"
        );
        assert_eq!(outreach_snapshot(&mut c).await, before);
        sqlx::raw_sql("DROP TRIGGER fixture_outreach_corrupt ON outreach_logs;DROP FUNCTION fixture_outreach_corrupt()").execute(&mut c).await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_drafts_complete_insert_ack_rejects_suppressed_or_changed_records_atomically() {
    let (mut c, job) = outreach_drafts_fixture().await;
    let before = outreach_snapshot(&mut c).await;
    for body in ["RETURN NULL;", "NEW.approval_status='rejected';RETURN NEW;"] {
        let sql = format!(
            "CREATE FUNCTION fixture_outreach_insert() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {body} END $$;CREATE TRIGGER fixture_outreach_insert BEFORE INSERT ON outreach_logs FOR EACH ROW EXECUTE FUNCTION fixture_outreach_insert()"
        );
        sqlx::raw_sql(sqlx::AssertSqlSafe(sql))
            .execute(&mut c)
            .await
            .unwrap();
        assert_eq!(
            outreach_create(&mut c, job, "fictional_insert_ack")
                .await
                .unwrap_err(),
            Failure("outreach_write_ack_failed")
        );
        assert_eq!(outreach_snapshot(&mut c).await, before);
        sqlx::raw_sql("DROP TRIGGER fixture_outreach_insert ON outreach_logs;DROP FUNCTION fixture_outreach_insert()").execute(&mut c).await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_drafts_read_only_list_eligibility_and_detail_preserve_private_snapshots_and_approval()
 {
    let (mut c, job) = outreach_drafts_fixture().await;
    let created = outreach_create(&mut c, job, "fictional_read_draft")
        .await
        .unwrap();
    let id = created["id"].as_str().unwrap().parse::<Uuid>().unwrap();
    let before = outreach_snapshot(&mut c).await;
    let mut other = connection().await;
    let mut tx = other.begin().await.unwrap();
    sqlx::query(
        "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
    )
    .execute(&mut *tx)
    .await
    .unwrap();
    sqlx::query("SET lock_timeout='100ms'")
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        outreach_draft_call(&mut c, id, "", None).await.unwrap(),
        created
    );
    assert_eq!(
        outreach_draft_call(&mut c, id, "/eligibility", None)
            .await
            .unwrap()["eligible_for_approval"],
        true
    );
    let list = outreach_drafts::dispatch(
        &mut c,
        outreach_drafts::Route::List,
        "GET",
        Some("limit=1"),
        &[],
        &contact_settings(),
    )
    .await
    .unwrap();
    assert_eq!(list["total"], 1);
    assert_eq!(list["drafts"][0], created);
    assert!(
        !list
            .to_string()
            .contains("PRIVATE_CONTEXT_PROVENANCE_CANARY")
    );
    assert!(list["drafts"][0].get("evidence_snapshot").is_none());
    assert!(list["drafts"][0].get("approval_hash").is_none());
    assert_eq!(outreach_snapshot(&mut c).await, before);
    tx.rollback().await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_drafts_suppressed_context_is_needs_input_and_local_function_refuses_narrative_execution()
 {
    let (mut c, job) = outreach_drafts_fixture().await;
    let before = outreach_snapshot(&mut c).await;
    let mut input = outreach_input(Some(job));
    input["use_llm"] = json!(true);
    assert_eq!(
        outreach_drafts::create_local(&mut c, input.clone(), "rest", &contact_settings())
            .await
            .unwrap_err(),
        Failure("outreach_writer_intent_required")
    );
    assert_eq!(outreach_snapshot(&mut c).await, before);
    sqlx::query("UPDATE contacts SET do_not_contact=true")
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        outreach_create(&mut c, job, "fictional_blocked_draft")
            .await
            .unwrap()["status"],
        "needs_input"
    );
    assert_eq!(outreach_snapshot(&mut c).await, before);
    sqlx::query("UPDATE contacts SET do_not_contact=false")
        .execute(&mut c)
        .await
        .unwrap();
    let result = outreach_drafts::create_local(&mut c, input, "mcp", &contact_settings())
        .await
        .unwrap();
    assert_eq!(result["provider_metadata"]["used_llm"], false);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_drafts_owner_http_validates_auth_revision_contract_and_current_approval_without_send_permission()
 {
    let (mut c, job) = outreach_drafts_fixture().await;
    let created = outreach_create(&mut c, job, "fictional_http_draft")
        .await
        .unwrap();
    let (url, stop, task) = http_fixture_values(host_values()).await;
    let http = client();
    let path = format!(
        "{url}/api/v1/outreach/drafts/{}",
        created["id"].as_str().unwrap()
    );
    let page = http
        .get(format!("{url}/api/v1/outreach/drafts?limit=1"))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(page.status(), 200);
    let page: Value = page.json().await.unwrap();
    assert_eq!(page["limit"], 1);
    assert_eq!(page["drafts"][0]["id"], created["id"]);
    assert_eq!(http.get(&path).send().await.unwrap().status(), 401);
    assert_eq!(
        http.get(&path)
            .bearer_auth(HOST_TOKEN)
            .header("x-agent-client", "extension")
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    assert_eq!(
        http.get(&path)
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    assert_eq!(
        http.patch(&path)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"expected_revision":1,"body":null}))
            .send()
            .await
            .unwrap()
            .status(),
        422
    );
    assert_eq!(
        http.post(format!("{path}/approve"))
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"expected_revision":2}))
            .send()
            .await
            .unwrap()
            .status(),
        409
    );
    let approved: Value = http
        .post(format!("{path}/approve"))
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"expected_revision":1}))
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(approved["eligibility"]["approval_current"], true);
    assert_eq!(approved["eligibility"]["email_send_ready"], false);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_drafts_concurrent_same_key_cannot_create_two_records_or_silently_adopt_a_stale_snapshot()
 {
    let (mut c, job) = outreach_drafts_fixture().await;
    sqlx::raw_sql("CREATE FUNCTION fixture_outreach_pause() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_sleep(0.05);RETURN NEW; END $$;CREATE TRIGGER fixture_outreach_pause BEFORE INSERT ON outreach_logs FOR EACH ROW EXECUTE FUNCTION fixture_outreach_pause()").execute(&mut c).await.unwrap();
    let mut second = connection().await;
    let (a, b) = tokio::join!(
        outreach_create(&mut c, job, "fictional_concurrent_draft"),
        outreach_create(&mut second, job, "fictional_concurrent_draft")
    );
    assert!(a.is_ok() || b.is_ok());
    if let (Ok(a), Ok(b)) = (a, b) {
        assert_eq!(a["id"], b["id"]);
    }
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM outreach_logs")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        1
    );
    sqlx::raw_sql("DROP TRIGGER fixture_outreach_pause ON outreach_logs;DROP FUNCTION fixture_outreach_pause()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn outreach_drafts_material_lock_timeout_rolls_back_the_owner_fence_and_creates_no_partial_draft()
 {
    let (mut c, job) = outreach_drafts_fixture().await;
    let before = outreach_snapshot(&mut c).await;
    let owner_before = browser_snapshot(&mut c).await;
    let mut other = connection().await;
    let mut tx = other.begin().await.unwrap();
    sqlx::query("SELECT id FROM candidate_profiles WHERE singleton_key='primary' FOR UPDATE")
        .execute(&mut *tx)
        .await
        .unwrap();
    sqlx::query("SET lock_timeout='100ms'")
        .execute(&mut c)
        .await
        .unwrap();
    assert!(
        outreach_create(&mut c, job, "fictional_locked_draft")
            .await
            .is_err()
    );
    assert_eq!(outreach_snapshot(&mut c).await, before);
    assert_eq!(browser_snapshot(&mut c).await, owner_before);
    tx.rollback().await.unwrap();
}
