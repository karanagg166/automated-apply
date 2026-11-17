// Deferred original paid owner rows and atomic local result/ranking fixtures. Loopback only.
use automated_apply_agents::apify_jobs::runs as apify_runs;
async fn apify_owner_fixture() -> PgConnection {
    let mut c = apify_intake_fixture().await;
    discovery_run_table(&mut c).await;
    c
}
async fn apify_owner_snapshot(c: &mut PgConnection) -> Value {
    let intake = apify_intake_snapshot(c).await;
    let owner:Value=sqlx::query_scalar("SELECT jsonb_build_object('runs',(SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM discovery_runs r),'journals',(SELECT jsonb_agg(to_jsonb(p) ORDER BY key) FROM owner_preferences p WHERE starts_with(key,'apify_owner:')))").fetch_one(&mut *c).await.unwrap();
    json!({"intake":intake,"owner":owner})
}
async fn apify_owner_acquire(
    c: &mut PgConnection,
    values: &BTreeMap<String, String>,
    n: u128,
    profile: bool,
) -> Result<Value> {
    let settings = ApifyJobSettings::from_values(values)?;
    let client = ApifyJobClient::from_values(values, true)?;
    let mut input = apify_job_input();
    input["use_profile"] = json!(profile);
    apify_runs::Service {
        settings: &settings,
        client: &client,
    }
    .acquire(c, input, Uuid::from_u128(n))
    .await
}
async fn apify_owner_finish(
    c: &mut PgConnection,
    values: &BTreeMap<String, String>,
    id: Uuid,
) -> Result<Value> {
    apify_runs::finish(c, &ApifyJobSettings::from_values(values)?, id).await
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_owner_admission_commits_parent_original_child_and_exact_reservation_together_without_replay_grant()
 {
    let mut c = apify_owner_fixture().await;
    let id = Uuid::from_u128(72001);
    let settings = ApifyJobSettings::from_values(&apify_job_values()).unwrap();
    match apify_runs::admit(&mut c, &settings, apify_job_input(), id)
        .await
        .unwrap()
    {
        apify_runs::Admission::Original(claim) => assert_eq!(claim.request_id(), id),
        _ => panic!("original only"),
    }
    let out = apify_runs::read(&mut c, id).await.unwrap();
    assert_eq!(out["status"], "running");
    assert_eq!(out["usage"]["stage"], "provider_pending_or_unknown");
    assert_eq!(out["local_intake_complete"], false);
    assert_eq!(out["reservation"]["reserved_usd"], "0.100001");
    assert!(out["usage"]["provider_http_attempts"].is_null());
    assert!(!out.to_string().contains("CANARY"));
    let before = apify_owner_snapshot(&mut c).await;
    let mut observer = connection().await;
    assert_eq!(apify_runs::read(&mut observer, id).await.unwrap(), out);
    let empty = ApifyJobSettings::from_values(&BTreeMap::new()).unwrap();
    match apify_runs::admit(&mut c, &empty, apify_job_input(), id)
        .await
        .unwrap()
    {
        apify_runs::Admission::Retained(v) => assert_eq!(v, out),
        _ => panic!("no replay grant"),
    }
    assert_eq!(apify_owner_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_owner_cannot_adopt_standalone_original_intent_as_new_owner_authority() {
    let mut c = apify_owner_fixture().await;
    let id = Uuid::from_u128(72002);
    apify_job_admit(&mut c, 72002).await.unwrap();
    let before = apify_owner_snapshot(&mut c).await;
    assert_eq!(
        apify_runs::admit(
            &mut c,
            &ApifyJobSettings::from_values(&apify_job_values()).unwrap(),
            apify_job_input(),
            id
        )
        .await
        .err()
        .unwrap(),
        Failure("apify_owner_child_already_claimed")
    );
    assert_eq!(apify_owner_snapshot(&mut c).await, before);
    assert_eq!(
        apify_runs::read(&mut c, id).await.unwrap_err(),
        Failure("discovery_run_not_found")
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_owner_legacy_compatibility_collision_and_changed_replay_body_preserve_original_history()
 {
    let mut c = apify_owner_fixture().await;
    let settings = ApifyJobSettings::from_values(&apify_job_values()).unwrap();
    let mut input = apify_job_input();
    input["idempotency_key"] = json!("fictional_compatibility");
    let id = Uuid::from_u128(72003);
    apify_runs::admit(&mut c, &settings, input.clone(), id)
        .await
        .unwrap();
    let before = apify_owner_snapshot(&mut c).await;
    assert_eq!(
        apify_runs::admit(&mut c, &settings, input, Uuid::from_u128(72004))
            .await
            .err()
            .unwrap(),
        Failure("discovery_run_compatibility_key_conflict")
    );
    let mut changed = apify_job_input();
    changed["query"]["limit"] = json!(21);
    assert_eq!(
        apify_runs::admit(&mut c, &settings, changed, id)
            .await
            .err()
            .unwrap(),
        Failure("discovery_run_request_conflict")
    );
    assert_eq!(apify_owner_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_owner_missing_paid_prerequisites_do_not_leave_parent_or_child_or_budget() {
    let mut c = apify_owner_fixture().await;
    let settings = ApifyJobSettings::from_values(&apify_job_values()).unwrap();
    let before = apify_owner_snapshot(&mut c).await;
    let mut input = apify_job_input();
    input["allow_paid"] = json!(false);
    assert_eq!(
        apify_runs::admit(&mut c, &settings, input, Uuid::from_u128(72005))
            .await
            .err()
            .unwrap(),
        Failure("apify_paid_opt_in_required")
    );
    assert_eq!(apify_owner_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_owner_final_original_ack_detects_parent_trigger_budget_profile_and_global_cooldown_mutations()
 {
    for (n, mutation) in [
        (
            72006,
            "UPDATE discovery_monthly_budgets SET reserved=reserved+0.000001 WHERE provider='apify';",
        ),
        (72007, "UPDATE candidate_profiles SET version=version+1;"),
        (
            72008,
            "INSERT INTO discovery_monthly_budgets(provider,month,reserved,cooldown_until) VALUES('apify','1999-01',0,clock_timestamp()+interval '1 hour');",
        ),
    ] {
        let mut c = apify_owner_fixture().await;
        let settings = ApifyJobSettings::from_values(&apify_job_values()).unwrap();
        let mut input = apify_job_input();
        input["use_profile"] = json!(true);
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("CREATE FUNCTION fixture_apify_parent_admit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {mutation} RETURN NEW;END $$;CREATE TRIGGER fixture_apify_parent_admit AFTER INSERT ON discovery_runs FOR EACH ROW EXECUTE FUNCTION fixture_apify_parent_admit()"))).execute(&mut c).await.unwrap();
        let before = apify_owner_snapshot(&mut c).await;
        let profile = automated_apply_agents::profile_store::get(&mut c)
            .await
            .unwrap()
            .value;
        assert_eq!(
            apify_runs::admit(&mut c, &settings, input, Uuid::from_u128(n))
                .await
                .err()
                .unwrap(),
            Failure("apify_execution_write_ack_failed")
        );
        assert_eq!(apify_owner_snapshot(&mut c).await, before);
        assert_eq!(
            automated_apply_agents::profile_store::get(&mut c)
                .await
                .unwrap()
                .value,
            profile
        );
        sqlx::raw_sql("DROP TRIGGER fixture_apify_parent_admit ON discovery_runs;DROP FUNCTION fixture_apify_parent_admit()").execute(&mut c).await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_owner_dropped_parent_insert_rolls_back_original_budget_and_prevents_remote_dispatch()
{
    let mut c = apify_owner_fixture().await;
    let (v, f, stop, task) = apify_job_http("ok").await;
    sqlx::raw_sql("CREATE FUNCTION fixture_apify_parent_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NULL;END $$;CREATE TRIGGER fixture_apify_parent_drop BEFORE INSERT ON discovery_runs FOR EACH ROW EXECUTE FUNCTION fixture_apify_parent_drop()").execute(&mut c).await.unwrap();
    let before = apify_owner_snapshot(&mut c).await;
    assert_eq!(
        apify_owner_acquire(&mut c, &v, 72009, false)
            .await
            .unwrap_err(),
        Failure("apify_owner_write_ack_failed")
    );
    assert_eq!(apify_owner_snapshot(&mut c).await, before);
    assert_eq!(f.calls.lock().await.len(), 0);
    sqlx::raw_sql("DROP TRIGGER fixture_apify_parent_drop ON discovery_runs;DROP FUNCTION fixture_apify_parent_drop()").execute(&mut c).await.unwrap();
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_owner_service_completes_original_loopback_run_and_terminal_replay_needs_no_current_token_or_profile()
 {
    let mut c = apify_owner_fixture().await;
    let (v, f, stop, task) = apify_job_http("ok").await;
    let settings = ApifyJobSettings::from_values(&v).unwrap();
    let client = ApifyJobClient::from_values(&v, true).unwrap();
    let id = Uuid::from_u128(72010);
    let result = apify_runs::Service {
        settings: &settings,
        client: &client,
    }
    .run(&mut c, apify_job_input(), id)
    .await
    .unwrap();
    assert_eq!(result["status"], "success");
    assert_eq!(result["counts"]["inserted"], 1);
    assert_eq!(result["local_intake_complete"], true);
    assert_eq!(result["rankings_complete"], true);
    assert_eq!(result["rankings"], json!([]));
    assert_eq!(result["provider_run_id"], "originalRun");
    assert_eq!(result["billing_final"], false);
    assert_eq!(result["reservation"]["reserved_usd"], "0.100001");
    assert_eq!(result["usage"]["provider_http_attempts"], 5);
    assert_eq!(result["application_dispatch"], false);
    assert!(!result.to_string().contains("CANARY"));
    sqlx::raw_sql("DROP TABLE candidate_profiles CASCADE")
        .execute(&mut c)
        .await
        .unwrap();
    let before = apify_owner_snapshot(&mut c).await;
    let empty = ApifyJobSettings::from_values(&BTreeMap::new()).unwrap();
    assert_eq!(
        apify_runs::Service {
            settings: &empty,
            client: &client
        }
        .run(&mut c, apify_job_input(), id)
        .await
        .unwrap(),
        result
    );
    assert_eq!(apify_runs::read(&mut c, id).await.unwrap(), result);
    assert_eq!(apify_owner_snapshot(&mut c).await, before);
    assert_eq!(f.calls.lock().await.len(), 5);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_owner_unknown_start_stays_recovery_required_and_finish_cannot_dispatch_or_manufacture_no_results()
 {
    let mut c = apify_owner_fixture().await;
    let (v, f, stop, task) = apify_job_http("lost_start").await;
    let id = Uuid::from_u128(72011);
    assert!(apify_owner_acquire(&mut c, &v, 72011, false).await.is_err());
    let saved = apify_runs::read(&mut c, id).await.unwrap();
    assert_eq!(saved["status"], "recovery_required");
    assert_eq!(saved["local_intake_complete"], false);
    assert_eq!(saved["provider_run_id"], Value::Null);
    let before = apify_owner_snapshot(&mut c).await;
    assert_eq!(
        apify_owner_finish(&mut c, &v, id).await.unwrap_err(),
        Failure("apify_intake_finding_missing")
    );
    assert_eq!(
        apify_owner_acquire(&mut c, &v, 72011, false).await.unwrap(),
        saved
    );
    assert_eq!(apify_owner_snapshot(&mut c).await, before);
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_owner_local_only_completion_reuses_prior_receipt_after_failed_parent_finalization_without_refreshing_jobs()
 {
    let mut c = apify_owner_fixture().await;
    let (v, f, stop, task) = apify_job_http("ok").await;
    let id = Uuid::from_u128(72012);
    let acquired = apify_owner_acquire(&mut c, &v, 72012, false).await.unwrap();
    assert_eq!(acquired["usage"]["stage"], "local_intake_pending");
    assert_eq!(acquired["local_intake_complete"], false);
    apify_intake_finish(&mut c, &v, id).await.unwrap();
    assert_eq!(
        apify_runs::read(&mut c, id).await.unwrap()["usage"]["stage"],
        "rankings_pending"
    );
    sqlx::raw_sql("CREATE FUNCTION fixture_apify_finish_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NULL;END $$;CREATE TRIGGER fixture_apify_finish_drop BEFORE UPDATE ON discovery_runs FOR EACH ROW EXECUTE FUNCTION fixture_apify_finish_drop()").execute(&mut c).await.unwrap();
    let before = apify_owner_snapshot(&mut c).await;
    assert_eq!(
        apify_owner_finish(&mut c, &v, id).await.unwrap_err(),
        Failure("apify_owner_write_ack_failed")
    );
    assert_eq!(apify_owner_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP TRIGGER fixture_apify_finish_drop ON discovery_runs;DROP FUNCTION fixture_apify_finish_drop()").execute(&mut c).await.unwrap();
    let facts = apify_intake_snapshot(&mut c).await["facts"].clone();
    let finished = apify_owner_finish(&mut c, &v, id).await.unwrap();
    assert_eq!(finished["status"], "success");
    assert_eq!(apify_intake_snapshot(&mut c).await["facts"], facts);
    assert_eq!(f.calls.lock().await.len(), 5);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_owner_rankings_use_original_profile_and_suppress_reviewed_history_without_changing_application_decisions()
 {
    let mut c = apify_owner_fixture().await;
    let (v, f, stop, task) = apify_job_http("ok").await;
    public_result_history(
        &mut c,
        "fictional_apify_prior",
        "https://job-fixture.example/12345",
    )
    .await;
    let id = Uuid::from_u128(72013);
    apify_owner_acquire(&mut c, &v, 72013, true).await.unwrap();
    let result = apify_owner_finish(&mut c, &v, id).await.unwrap();
    assert_eq!(result["counts"]["inserted"], 1);
    assert_eq!(result["usage"]["suppressed_prior_history"], 1);
    assert_eq!(result["rankings"], json!([]));
    assert!(result["profile_version"].as_i64().is_some());
    assert_eq!(
        sqlx::query_scalar::<_, String>("SELECT status FROM jobs")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        "discovered"
    );
    assert!(!result.to_string().contains("CANARY"));
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_owner_pending_current_profile_change_holds_all_fresh_local_work_and_never_replays_provider()
 {
    let mut c = apify_owner_fixture().await;
    let (v, f, stop, task) = apify_job_http("ok").await;
    let id = Uuid::from_u128(72014);
    apify_owner_acquire(&mut c, &v, 72014, true).await.unwrap();
    sqlx::query("UPDATE candidate_profiles SET version=version+1")
        .execute(&mut c)
        .await
        .unwrap();
    let before = apify_owner_snapshot(&mut c).await;
    assert_eq!(
        apify_owner_finish(&mut c, &v, id).await.unwrap_err(),
        Failure("apify_intake_profile_changed")
    );
    assert_eq!(apify_owner_snapshot(&mut c).await, before);
    assert_eq!(f.calls.lock().await.len(), 5);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_owner_terminal_profile_trigger_rolls_back_all_fresh_local_jobs_receipt_and_parent() {
    let mut c = apify_owner_fixture().await;
    let (v, _, stop, task) = apify_job_http("ok").await;
    let id = Uuid::from_u128(72015);
    apify_owner_acquire(&mut c, &v, 72015, true).await.unwrap();
    sqlx::raw_sql("CREATE FUNCTION fixture_apify_finish_profile() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN UPDATE candidate_profiles SET version=version+1;RETURN NEW;END $$;CREATE TRIGGER fixture_apify_finish_profile AFTER UPDATE ON discovery_runs FOR EACH ROW EXECUTE FUNCTION fixture_apify_finish_profile()").execute(&mut c).await.unwrap();
    let before = apify_owner_snapshot(&mut c).await;
    let profile = automated_apply_agents::profile_store::get(&mut c)
        .await
        .unwrap()
        .value;
    assert_eq!(
        apify_owner_finish(&mut c, &v, id).await.unwrap_err(),
        Failure("apify_intake_profile_changed")
    );
    assert_eq!(apify_owner_snapshot(&mut c).await, before);
    assert_eq!(
        automated_apply_agents::profile_store::get(&mut c)
            .await
            .unwrap()
            .value,
        profile
    );
    sqlx::raw_sql("DROP TRIGGER fixture_apify_finish_profile ON discovery_runs;DROP FUNCTION fixture_apify_finish_profile()").execute(&mut c).await.unwrap();
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_owner_late_history_trigger_rolls_back_terminal_rankings_and_local_writes() {
    let mut c = apify_owner_fixture().await;
    let (v, _, stop, task) = apify_job_http("ok").await;
    let id = Uuid::from_u128(72016);
    apify_owner_acquire(&mut c, &v, 72016, true).await.unwrap();
    sqlx::raw_sql("CREATE FUNCTION fixture_apify_finish_history() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'apify_owner:') AND NEW.value->>'state'='completed' THEN INSERT INTO owner_preferences(key,value) VALUES('gmail_application:late_apify_fixture',jsonb_build_object('confirmed_application',true,'company','Fictional Public Employer','role','Fictional Engineer','job_url','https://job-fixture.example/12345','expires_at',clock_timestamp()+interval '90 days'));END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_apify_finish_history AFTER UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_apify_finish_history()").execute(&mut c).await.unwrap();
    let before = apify_owner_snapshot(&mut c).await;
    assert_eq!(
        apify_owner_finish(&mut c, &v, id).await.unwrap_err(),
        Failure("discovery_run_write_ack_failed")
    );
    assert_eq!(apify_owner_snapshot(&mut c).await, before);
    assert!(!sqlx::query_scalar::<_,bool>("SELECT EXISTS(SELECT 1 FROM owner_preferences WHERE key='gmail_application:late_apify_fixture')").fetch_one(&mut c).await.unwrap());
    sqlx::raw_sql("DROP TRIGGER fixture_apify_finish_history ON owner_preferences;DROP FUNCTION fixture_apify_finish_history()").execute(&mut c).await.unwrap();
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_owner_terminal_journal_trigger_cannot_silently_rewrite_saved_parent_results() {
    let mut c = apify_owner_fixture().await;
    let (v, _, stop, task) = apify_job_http("ok").await;
    let id = Uuid::from_u128(72017);
    apify_owner_acquire(&mut c, &v, 72017, false).await.unwrap();
    sqlx::raw_sql("CREATE FUNCTION fixture_apify_finish_parent() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'apify_owner:') AND NEW.value->>'state'='completed' THEN UPDATE discovery_runs SET provider_run_id='foreignRun';END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_apify_finish_parent AFTER UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_apify_finish_parent()").execute(&mut c).await.unwrap();
    let before = apify_owner_snapshot(&mut c).await;
    assert_eq!(
        apify_owner_finish(&mut c, &v, id).await.unwrap_err(),
        Failure("apify_owner_write_ack_failed")
    );
    assert_eq!(apify_owner_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP TRIGGER fixture_apify_finish_parent ON owner_preferences;DROP FUNCTION fixture_apify_finish_parent()").execute(&mut c).await.unwrap();
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_owner_retained_all_filtered_finding_finishes_as_no_results_with_original_exclusion_counts()
 {
    let mut c = apify_owner_fixture().await;
    let (v, f, stop, task) = apify_job_http("ok").await;
    let settings = ApifyJobSettings::from_values(&v).unwrap();
    let client = ApifyJobClient::from_values(&v, true).unwrap();
    let id = Uuid::from_u128(72018);
    let mut input = apify_job_input();
    input["query"]["keywords"] = json!(["unmatched fictional keyword"]);
    let result = apify_runs::Service {
        settings: &settings,
        client: &client,
    }
    .run(&mut c, input, id)
    .await
    .unwrap();
    assert_eq!(result["status"], "no_results");
    assert_eq!(result["counts"]["discovered"], 1);
    assert_eq!(result["counts"]["skipped"], 1);
    assert_eq!(result["counts"]["inserted"], 0);
    assert_eq!(result["job_ids"], json!([]));
    assert_eq!(result["rankings_complete"], true);
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_owner_admission_final_ack_rechecks_exact_monthly_profile_and_global_cooldown_after_parent_triggers()
 {
    for mode in ["budget", "profile", "cooldown"] {
        let mut c = apify_owner_fixture().await;
        let (v, f, stop, task) = apify_job_http("ok").await;
        let effect = match mode {
            "budget" => {
                "UPDATE discovery_monthly_budgets SET reserved=reserved+0.000001 WHERE provider='apify';"
            }
            "profile" => "UPDATE candidate_profiles SET version=version+1;",
            _ => {
                "INSERT INTO discovery_monthly_budgets(provider,month,reserved,cooldown_until) VALUES('apify','1999-01',0,clock_timestamp()+interval '1 hour');"
            }
        };
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("CREATE FUNCTION fixture_apify_parent_late() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'apify_owner:') THEN {effect} END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_apify_parent_late AFTER INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_apify_parent_late()"))).execute(&mut c).await.unwrap();
        let before = apify_owner_snapshot(&mut c).await;
        let profile = automated_apply_agents::profile_store::get(&mut c)
            .await
            .unwrap()
            .value;
        assert_eq!(
            apify_owner_acquire(&mut c, &v, 72019, true)
                .await
                .unwrap_err(),
            Failure("apify_execution_write_ack_failed")
        );
        assert_eq!(apify_owner_snapshot(&mut c).await, before);
        assert_eq!(
            automated_apply_agents::profile_store::get(&mut c)
                .await
                .unwrap()
                .value,
            profile
        );
        assert_eq!(f.calls.lock().await.len(), 0);
        sqlx::raw_sql("DROP TRIGGER fixture_apify_parent_late ON owner_preferences;DROP FUNCTION fixture_apify_parent_late()").execute(&mut c).await.unwrap();
        stop.cancel();
        task.await.unwrap();
    }
}
