// Deferred separate GET-only recovery, durable pages and local finding completion. Numeric loopback only.
use automated_apply_agents::apify_jobs::read_controller::{self, Service as ApifyReadService};
async fn apify_read_seed(
    c: &mut PgConnection,
    v: &BTreeMap<String, String>,
    f: &ApifyJobHttp,
    n: u128,
    limit: u64,
) {
    f.limit.store(limit as usize, Ordering::SeqCst);
    let settings = ApifyJobSettings::from_values(v).unwrap();
    let client = ApifyJobClient::from_values(v, true).unwrap();
    let mut input = apify_job_input();
    input["query"]["limit"] = json!(limit);
    assert_eq!(
        ApifyJobService {
            settings: &settings,
            client: &client
        }
        .acquire(c, input, Uuid::from_u128(n))
        .await
        .unwrap_err(),
        Failure("apify_execution_response_limit")
    );
    apify_read_age_original(c, Uuid::from_u128(n)).await;
    f.recovering.store(true, Ordering::SeqCst);
}
async fn apify_read_recover(
    c: &mut PgConnection,
    v: &BTreeMap<String, String>,
    parent: Uuid,
    id: Uuid,
) -> Result<Value> {
    let settings = ApifyJobSettings::from_values(v)?;
    let client = ApifyJobClient::from_values(v, true)?;
    ApifyReadService {
        settings: &settings,
        client: &client,
    }
    .recover(c, parent, id)
    .await
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_read_transport_recovers_original_dataset_without_second_start_and_saved_replay_never_gets_again()
 {
    let mut c = apify_read_fixture().await;
    job_intake_tables(&mut c).await;
    let (v, f, stop, task) = apify_job_http("read_ok").await;
    let parent = Uuid::from_u128(76001);
    let id = Uuid::from_u128(77001);
    apify_read_seed(&mut c, &v, &f, 76001, 20).await;
    let first = apify_read_recover(&mut c, &v, parent, id).await.unwrap();
    assert_eq!(first["finding_retained"], true);
    assert_eq!(first["http_attempts"], 3);
    assert_eq!(first["http_responses"], 3);
    assert_eq!(first["provider_status"], "SUCCEEDED");
    assert_eq!(first["independent_termination_verified"], false);
    assert_eq!(first["billing_final"], false);
    let original = apify_admission::read(&mut c, parent).await.unwrap();
    assert_eq!(original["finding_retained"], true);
    assert_eq!(original["jobs"].as_array().unwrap().len(), 1);
    assert_eq!(original["provider_http_attempts"], 5);
    assert_eq!(original["read_rounds_admitted"], 1);
    assert_eq!(original["last_read_request_id"], json!(id));
    let before = apify_read_snapshot(&mut c).await;
    let calls = f.calls.lock().await.len();
    assert_eq!(
        apify_read_recover(&mut c, &BTreeMap::new(), parent, id)
            .await
            .unwrap(),
        first
    );
    assert_eq!(
        read_controller::finish(
            &mut c,
            &ApifyJobSettings::from_values(&BTreeMap::new()).unwrap(),
            parent,
            id
        )
        .await
        .unwrap(),
        first
    );
    assert_eq!(apify_read_snapshot(&mut c).await, before);
    assert_eq!(f.calls.lock().await.len(), calls);
    assert_eq!(
        apify_intake_finish(&mut c, &v, parent).await.unwrap()["counts"]["inserted"],
        1
    );
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    assert_eq!(f.aborts.load(Ordering::SeqCst), 0);
    assert!(!first.to_string().contains("CANARY"));
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_read_two_pages_retain_all_fifty_one_original_jobs_under_four_get_ceiling() {
    let mut c = apify_read_fixture().await;
    let (v, f, stop, task) = apify_job_http("read_two_pages").await;
    let parent = Uuid::from_u128(76002);
    let id = Uuid::from_u128(77002);
    apify_read_seed(&mut c, &v, &f, 76002, 100).await;
    let result = apify_read_recover(&mut c, &v, parent, id).await.unwrap();
    assert_eq!(result["finding_retained"], true);
    assert_eq!(result["http_attempts"], 4);
    assert_eq!(
        apify_admission::read(&mut c, parent).await.unwrap()["jobs"]
            .as_array()
            .unwrap()
            .len(),
        51
    );
    let row: Value = sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(format!("apify_read:{}", id.simple()))
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(row["selected_pages"].as_array().unwrap().len(), 2);
    assert_eq!(
        row["selected_pages"][0]["page"]["jobs"]
            .as_array()
            .unwrap()
            .len(),
        50
    );
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    assert_eq!(f.calls.lock().await.len(), 9);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_read_pending_acknowledged_run_records_one_status_without_build_dataset_abort_or_start()
 {
    let mut c = apify_read_fixture().await;
    let (v, f, stop, task) = apify_job_http("read_pending").await;
    let parent = Uuid::from_u128(76003);
    let id = Uuid::from_u128(77003);
    apify_read_seed(&mut c, &v, &f, 76003, 20).await;
    // Fictional nonterminal original checkpoint; production never downgrades a terminal run.
    let mut journal = apify_intake_journal(&mut c, parent).await;
    journal["selected_run"]["status"] = json!("RUNNING");
    journal["selected_run"]["finishedAt"] = Value::Null;
    journal["selected_run"]["termination_observed"] = json!(false);
    journal["selected_run_hash"] = json!(automated_apply_agents::python_json::digest(
        &journal["selected_run"]
    ));
    sqlx::query("UPDATE owner_preferences SET value=$2 WHERE key=$1")
        .bind(format!("apify_job:{}", parent.simple()))
        .bind(journal)
        .execute(&mut c)
        .await
        .unwrap();
    let before = f.calls.lock().await.len();
    let result = apify_read_recover(&mut c, &v, parent, id).await.unwrap();
    assert_eq!(result["provider_status"], "RUNNING");
    assert_eq!(result["finding_retained"], false);
    assert_eq!(result["http_attempts"], 1);
    assert_eq!(f.calls.lock().await.len(), before + 1);
    assert_eq!(f.aborts.load(Ordering::SeqCst), 0);
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_read_foreign_run_and_changed_build_schema_fail_closed_without_dataset_or_another_start()
 {
    for (n, mode, expected, reads) in [
        (
            76004,
            "read_foreign",
            "apify_run_original_binding_changed",
            1,
        ),
        (76005, "read_schema", "apify_reviewed_schema_changed", 2),
    ] {
        let mut c = apify_read_fixture().await;
        let (v, f, stop, task) = apify_job_http(mode).await;
        let parent = Uuid::from_u128(n);
        let id = Uuid::from_u128(n + 1000);
        apify_read_seed(&mut c, &v, &f, n, 20).await;
        let before = f.calls.lock().await.len();
        assert_eq!(
            apify_read_recover(&mut c, &v, parent, id)
                .await
                .unwrap_err(),
            Failure(expected)
        );
        let saved = apify_read::read(&mut c, parent, id).await.unwrap();
        assert_eq!(saved["http_attempts"], reads);
        assert_eq!(saved["finding_retained"], false);
        assert_eq!(f.calls.lock().await.len(), before + reads as usize);
        assert_eq!(f.starts.load(Ordering::SeqCst), 1);
        assert_eq!(f.aborts.load(Ordering::SeqCst), 0);
        stop.cancel();
        task.await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_read_rate_reply_sets_monotonic_cooldown_and_retains_full_cap_without_new_read_or_start()
 {
    let mut c = apify_read_fixture().await;
    let (v, f, stop, task) = apify_job_http("read_rate").await;
    let parent = Uuid::from_u128(76006);
    let id = Uuid::from_u128(77006);
    apify_read_seed(&mut c, &v, &f, 76006, 20).await;
    assert_eq!(
        apify_read_recover(&mut c, &v, parent, id)
            .await
            .unwrap_err(),
        Failure("apify_execution_rate_limited")
    );
    let saved = apify_read::read(&mut c, parent, id).await.unwrap();
    assert_eq!(saved["http_attempts"], 1);
    assert_eq!(saved["reservation"]["reserved_usd"], "0.100001");
    assert!(sqlx::query_scalar::<_,bool>("SELECT cooldown_until>clock_timestamp()+interval '50 minutes' FROM discovery_monthly_budgets WHERE provider='apify'").fetch_one(&mut c).await.unwrap());
    let before = apify_read_snapshot(&mut c).await;
    let calls = f.calls.lock().await.len();
    assert_eq!(
        apify_read_recover(&mut c, &v, parent, id).await.unwrap(),
        saved
    );
    assert_eq!(apify_read_snapshot(&mut c).await, before);
    assert_eq!(f.calls.lock().await.len(), calls);
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_read_dropped_operation_admission_prevents_get_while_consumed_read_round_remains() {
    let mut c = apify_read_fixture().await;
    let (v, f, stop, task) = apify_job_http("read_ok").await;
    let parent = Uuid::from_u128(76007);
    let id = Uuid::from_u128(77007);
    apify_read_seed(&mut c, &v, &f, 76007, 20).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_apify_read_op_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'apify_read:') AND NEW.value->'operation'->>'state'='admitted' THEN RETURN NULL;END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_apify_read_op_drop BEFORE UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_apify_read_op_drop()").execute(&mut c).await.unwrap();
    let calls = f.calls.lock().await.len();
    assert_eq!(
        apify_read_recover(&mut c, &v, parent, id)
            .await
            .unwrap_err(),
        Failure("apify_read_write_ack_failed")
    );
    let saved = apify_read::read(&mut c, parent, id).await.unwrap();
    assert_eq!(saved["recorded_state"], "read_admitted");
    assert_eq!(saved["http_attempts"], 0);
    assert_eq!(
        apify_admission::read(&mut c, parent).await.unwrap()["read_rounds_admitted"],
        1
    );
    assert_eq!(f.calls.lock().await.len(), calls);
    assert_eq!(
        apify_read_recover(&mut c, &v, parent, id).await.unwrap(),
        saved
    );
    assert_eq!(f.calls.lock().await.len(), calls);
    sqlx::raw_sql("DROP TRIGGER fixture_apify_read_op_drop ON owner_preferences;DROP FUNCTION fixture_apify_read_op_drop()").execute(&mut c).await.unwrap();
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_read_dropped_response_checkpoint_keeps_unknown_minimum_counts_and_original_binding_without_repeating_get()
 {
    let mut c = apify_read_fixture().await;
    let (v, f, stop, task) = apify_job_http("read_ok").await;
    let parent = Uuid::from_u128(76008);
    let id = Uuid::from_u128(77008);
    apify_read_seed(&mut c, &v, &f, 76008, 20).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_apify_read_response_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'apify_read:') AND NEW.value->'operation'->>'state'='retained' THEN RETURN NULL;END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_apify_read_response_drop BEFORE UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_apify_read_response_drop()").execute(&mut c).await.unwrap();
    let calls = f.calls.lock().await.len();
    assert_eq!(
        apify_read_recover(&mut c, &v, parent, id)
            .await
            .unwrap_err(),
        Failure("apify_read_write_ack_failed")
    );
    let saved = apify_read::read(&mut c, parent, id).await.unwrap();
    assert_eq!(saved["recorded_state"], "operation_admitted");
    assert_eq!(saved["http_counts_are_minimum"], true);
    assert_eq!(saved["http_attempts"], 0);
    assert_eq!(f.calls.lock().await.len(), calls + 1);
    assert_eq!(
        apify_read_recover(&mut c, &v, parent, id).await.unwrap(),
        saved
    );
    assert_eq!(f.calls.lock().await.len(), calls + 1);
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    sqlx::raw_sql("DROP TRIGGER fixture_apify_read_response_drop ON owner_preferences;DROP FUNCTION fixture_apify_read_response_drop()").execute(&mut c).await.unwrap();
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_read_cancellation_during_status_is_not_an_abort_or_an_authorization_to_repeat_the_get()
 {
    let mut c = apify_read_fixture().await;
    let (v, f, stop, task) = apify_job_http("read_hold").await;
    let parent = Uuid::from_u128(76009);
    let id = Uuid::from_u128(77009);
    apify_read_seed(&mut c, &v, &f, 76009, 20).await;
    let other_values = v.clone();
    let work = tokio::spawn(async move {
        let mut c = connection().await;
        apify_read_recover(&mut c, &other_values, parent, id).await
    });
    tokio::time::timeout(Duration::from_secs(3), f.entered.notified())
        .await
        .unwrap();
    work.abort();
    assert!(work.await.unwrap_err().is_cancelled());
    let saved = apify_read::read(&mut c, parent, id).await.unwrap();
    assert_eq!(saved["http_counts_are_minimum"], true);
    assert_eq!(saved["http_attempts"], 0);
    let calls = f.calls.lock().await.len();
    assert_eq!(
        apify_read_recover(&mut c, &v, parent, id).await.unwrap(),
        saved
    );
    assert_eq!(f.calls.lock().await.len(), calls);
    assert_eq!(f.aborts.load(Ordering::SeqCst), 0);
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    f.release.notify_one();
    stop.cancel();
    task.await.unwrap();
}
async fn apify_read_hold_final(c: &mut PgConnection) {
    sqlx::raw_sql("CREATE FUNCTION fixture_apify_read_final_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'apify_job:') AND NEW.value->>'state'='finding_retained' THEN RETURN NULL;END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_apify_read_final_drop BEFORE UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_apify_read_final_drop()").execute(c).await.unwrap();
}
async fn apify_read_release_final(c: &mut PgConnection) {
    sqlx::raw_sql("DROP TRIGGER fixture_apify_read_final_drop ON owner_preferences;DROP FUNCTION fixture_apify_read_final_drop()").execute(c).await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_read_complete_saved_pages_recover_final_finding_locally_without_new_read_round_or_observation_time()
 {
    let mut c = apify_read_fixture().await;
    let (v, f, stop, task) = apify_job_http("read_two_pages").await;
    let parent = Uuid::from_u128(76010);
    let id = Uuid::from_u128(77010);
    apify_read_seed(&mut c, &v, &f, 76010, 100).await;
    apify_read_hold_final(&mut c).await;
    assert_eq!(
        apify_read_recover(&mut c, &v, parent, id)
            .await
            .unwrap_err(),
        Failure("apify_read_write_ack_failed")
    );
    let saved = apify_read::read(&mut c, parent, id).await.unwrap();
    assert_eq!(saved["local_merge_available"], true);
    assert_eq!(saved["finding_retained"], false);
    let calls = f.calls.lock().await.len();
    let before = apify_read_snapshot(&mut c).await;
    assert_eq!(
        apify_read_recover(&mut c, &v, parent, Uuid::from_u128(77999))
            .await
            .unwrap_err(),
        Failure("apify_read_local_completion_required")
    );
    assert_eq!(apify_read_snapshot(&mut c).await, before);
    let page_at:Value=sqlx::query_scalar("SELECT value->'selected_pages'->0->'page'->'observed_at' FROM owner_preferences WHERE key=$1").bind(format!("apify_read:{}",id.simple())).fetch_one(&mut c).await.unwrap();
    apify_read_release_final(&mut c).await;
    let result = read_controller::finish(
        &mut c,
        &ApifyJobSettings::from_values(&v).unwrap(),
        parent,
        id,
    )
    .await
    .unwrap();
    assert_eq!(result["finding_retained"], true);
    let original = apify_admission::read(&mut c, parent).await.unwrap();
    assert_eq!(original["observed_at"], page_at);
    assert_eq!(original["jobs"].as_array().unwrap().len(), 51);
    assert_eq!(f.calls.lock().await.len(), calls);
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_read_corrupted_saved_page_hash_cannot_be_merged_or_renew_an_original_paid_start() {
    let mut c = apify_read_fixture().await;
    let (v, f, stop, task) = apify_job_http("read_ok").await;
    let parent = Uuid::from_u128(76011);
    let id = Uuid::from_u128(77011);
    apify_read_seed(&mut c, &v, &f, 76011, 20).await;
    apify_read_hold_final(&mut c).await;
    assert!(apify_read_recover(&mut c, &v, parent, id).await.is_err());
    apify_read_release_final(&mut c).await;
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{selected_pages,0,page,jobs,0,title}','\"Altered fixture\"') WHERE key=$1").bind(format!("apify_read:{}",id.simple())).execute(&mut c).await.unwrap();
    let before = apify_read_snapshot(&mut c).await;
    let calls = f.calls.lock().await.len();
    assert_eq!(
        read_controller::finish(
            &mut c,
            &ApifyJobSettings::from_values(&v).unwrap(),
            parent,
            id
        )
        .await
        .unwrap_err(),
        Failure("apify_read_selected_pages_invalid")
    );
    assert_eq!(apify_read_snapshot(&mut c).await, before);
    assert_eq!(f.calls.lock().await.len(), calls);
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_read_local_merge_holds_changed_configuration_and_recovers_same_pages_after_restore_without_gets()
 {
    let mut c = apify_read_fixture().await;
    let (v, f, stop, task) = apify_job_http("read_ok").await;
    let parent = Uuid::from_u128(76012);
    let id = Uuid::from_u128(77012);
    apify_read_seed(&mut c, &v, &f, 76012, 20).await;
    apify_read_hold_final(&mut c).await;
    assert!(apify_read_recover(&mut c, &v, parent, id).await.is_err());
    apify_read_release_final(&mut c).await;
    let mut changed = v.clone();
    changed.insert("APIFY_PER_RUN_CAP_USD".into(), "0.100002".into());
    let before = apify_read_snapshot(&mut c).await;
    let calls = f.calls.lock().await.len();
    assert_eq!(
        read_controller::finish(
            &mut c,
            &ApifyJobSettings::from_values(&changed).unwrap(),
            parent,
            id
        )
        .await
        .unwrap_err(),
        Failure("apify_read_configuration_changed")
    );
    assert_eq!(apify_read_snapshot(&mut c).await, before);
    assert_eq!(
        read_controller::finish(
            &mut c,
            &ApifyJobSettings::from_values(&v).unwrap(),
            parent,
            id
        )
        .await
        .unwrap()["finding_retained"],
        true
    );
    assert_eq!(f.calls.lock().await.len(), calls);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_read_final_finding_ack_detects_late_one_micro_budget_change_while_preserving_complete_pages()
 {
    let mut c = apify_read_fixture().await;
    let (v, f, stop, task) = apify_job_http("read_ok").await;
    let parent = Uuid::from_u128(76013);
    let id = Uuid::from_u128(77013);
    apify_read_seed(&mut c, &v, &f, 76013, 20).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_apify_read_final_budget() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'apify_read:') AND NEW.value->>'state'='finding_retained' THEN UPDATE discovery_monthly_budgets SET reserved=reserved+0.000001 WHERE provider='apify';END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_apify_read_final_budget AFTER UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_apify_read_final_budget()").execute(&mut c).await.unwrap();
    assert_eq!(
        apify_read_recover(&mut c, &v, parent, id)
            .await
            .unwrap_err(),
        Failure("apify_read_write_ack_failed")
    );
    assert_eq!(
        apify_read::read(&mut c, parent, id).await.unwrap()["local_merge_available"],
        true
    );
    assert_eq!(
        sqlx::query_scalar::<_, String>(
            "SELECT reserved::text FROM discovery_monthly_budgets WHERE provider='apify'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        "0.100001"
    );
    let calls = f.calls.lock().await.len();
    sqlx::raw_sql("DROP TRIGGER fixture_apify_read_final_budget ON owner_preferences;DROP FUNCTION fixture_apify_read_final_budget()").execute(&mut c).await.unwrap();
    assert_eq!(
        read_controller::finish(
            &mut c,
            &ApifyJobSettings::from_values(&v).unwrap(),
            parent,
            id
        )
        .await
        .unwrap()["finding_retained"],
        true
    );
    assert_eq!(f.calls.lock().await.len(), calls);
    stop.cancel();
    task.await.unwrap();
}
