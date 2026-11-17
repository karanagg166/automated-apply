//! Deferred terminal parent/local receipt/ranking fixtures. No production account or provider evidence.
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_result_original_loopback_run_is_locally_complete_and_terminal_replay_never_reads_new_profile_or_gets_again()
 {
    let mut c = public_intake_fixture().await;
    let (values, remote, stop, task) = public_job_http(PublicJobSource::Greenhouse, "ok").await;
    let settings = automated_apply_agents::source_registry::Settings::from_values(&values).unwrap();
    let client = PublicJobClient::from_values(&values, true).unwrap();
    let id = Uuid::from_u128(66001);
    let service = public_owner_runs::Service {
        settings: &settings,
        client: &client,
        timeout_seconds: 90.0,
    };
    let first = service
        .run(&mut c, public_intake_input(), id)
        .await
        .unwrap();
    assert_eq!(first["status"], "success");
    assert_eq!(first["counts"]["inserted"], 1);
    assert_eq!(first["rankings"], json!([]));
    assert_eq!(first["local_intake_complete"], true);
    assert_eq!(first["rankings_complete"], true);
    assert_eq!(first["live_verified"], false);
    assert_eq!(first["application_dispatch"], false);
    assert_eq!(remote.calls.load(Ordering::SeqCst), 1);
    sqlx::raw_sql("DROP TABLE candidate_profiles CASCADE")
        .execute(&mut c)
        .await
        .unwrap();
    let before = public_intake_snapshot(&mut c).await;
    let empty =
        automated_apply_agents::source_registry::Settings::from_values(&BTreeMap::new()).unwrap();
    let replay = public_owner_runs::Service {
        settings: &empty,
        client: &client,
        timeout_seconds: 180.0,
    }
    .run(&mut c, public_intake_input(), id)
    .await
    .unwrap();
    assert_eq!(replay, first);
    assert_eq!(public_owner_runs::read(&mut c, id).await.unwrap(), first);
    assert_eq!(public_intake_snapshot(&mut c).await, before);
    assert_eq!(remote.calls.load(Ordering::SeqCst), 1);
    assert!(!first.to_string().contains("CANARY"));
    stop.cancel();
    task.await.unwrap();
}
fn public_result_input() -> Value {
    let mut v = public_intake_input();
    v["use_profile"] = json!(true);
    v
}
async fn public_result_history(c: &mut PgConnection, key: &str, url: &str) {
    let value = json!({"id":key,"version":1,"deleted":false,"confirmed_application":true,"company":"Fictional Public Employer","role":"Fictional Engineer","job_url":url,"applied_at":"2026-11-01T00:00:00Z","expires_at":(public_intake_time(c).await+chrono::Duration::days(90)).to_rfc3339(),"private_fixture":"PRIVATE_REVIEWED_HISTORY_CANARY"});
    sqlx::query("INSERT INTO owner_preferences(key,value) VALUES($1,$2)")
        .bind(format!("gmail_application:{key}"))
        .bind(value)
        .execute(c)
        .await
        .unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_result_rankings_use_saved_profile_and_suppress_confirmed_history_without_rewriting_job_decisions()
 {
    let mut c = public_intake_fixture().await;
    let at = public_intake_time(&mut c).await;
    let first = public_intake_job(at);
    let mut second = first.clone();
    second["source_job_id"] = json!("12346");
    second["original_url"] = json!("https://boards.greenhouse.io/fictional/jobs/12346");
    second["canonical_url"] = Value::Null;
    second["application_url"] = second["original_url"].clone();
    public_result_history(
        &mut c,
        "fictional_prior",
        "https://job-boards.greenhouse.io/fictional/jobs/12345",
    )
    .await;
    public_intake_observation(
        &mut c,
        66002,
        public_result_input(),
        vec![first, second],
        at,
    )
    .await;
    let result = public_owner_runs::finish(&mut c, &public_job_settings(), Uuid::from_u128(66002))
        .await
        .unwrap();
    assert_eq!(result["counts"]["inserted"], 2);
    assert_eq!(result["usage"]["suppressed_prior_history"], 1);
    assert_eq!(result["rankings"].as_array().unwrap().len(), 1);
    assert_eq!(
        result["rankings"][0]["profile_version"],
        result["profile_version"]
    );
    assert!(
        result["rankings"][0]["explanation"]
            .as_str()
            .unwrap()
            .contains("eligibility review")
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM jobs WHERE status='discovered'")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        2
    );
    assert!(!result.to_string().contains("CANARY"));
    let before = public_intake_snapshot(&mut c).await;
    sqlx::query("UPDATE candidate_profiles SET version=version+1")
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        public_owner_runs::finish(&mut c, &public_job_settings(), Uuid::from_u128(66002))
            .await
            .unwrap(),
        result
    );
    assert_eq!(public_intake_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_result_equal_scores_sort_by_saved_uuid_and_filter_only_result_is_honest_no_results()
{
    let mut c = public_intake_fixture().await;
    let at = public_intake_time(&mut c).await;
    let first = public_intake_job(at);
    let mut second = first.clone();
    second["source_job_id"] = json!("12346");
    second["original_url"] = json!("https://boards.greenhouse.io/fictional/jobs/12346");
    second["canonical_url"] = Value::Null;
    second["application_url"] = second["original_url"].clone();
    public_intake_observation(
        &mut c,
        66003,
        public_result_input(),
        vec![first, second],
        at,
    )
    .await;
    let result = public_owner_runs::finish(&mut c, &public_job_settings(), Uuid::from_u128(66003))
        .await
        .unwrap();
    let ranked = result["rankings"].as_array().unwrap();
    assert_eq!(ranked.len(), 2);
    assert_eq!(ranked[0]["match_score"], ranked[1]["match_score"]);
    assert!(ranked[0]["job_id"].as_str().unwrap() < ranked[1]["job_id"].as_str().unwrap());
    let at = public_intake_time(&mut c).await;
    let mut input = public_intake_input();
    input["query"]["keywords"] = json!(["Unrelated explicit keyword"]);
    public_intake_observation(&mut c, 66004, input, vec![public_intake_job(at)], at).await;
    let filtered =
        public_owner_runs::finish(&mut c, &public_job_settings(), Uuid::from_u128(66004))
            .await
            .unwrap();
    assert_eq!(filtered["status"], "no_results");
    assert_eq!(filtered["counts"]["skipped"], 1);
    assert_eq!(filtered["job_ids"], json!([]));
    assert_eq!(filtered["rankings_complete"], true);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_result_missing_parent_update_ack_rolls_back_fresh_employers_jobs_observations_and_local_receipt()
 {
    let mut c = public_intake_fixture().await;
    let at = public_intake_time(&mut c).await;
    public_intake_observation(
        &mut c,
        66005,
        public_intake_input(),
        vec![public_intake_job(at)],
        at,
    )
    .await;
    sqlx::raw_sql("CREATE FUNCTION fixture_public_result_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NULL;END $$;CREATE TRIGGER fixture_public_result_drop BEFORE UPDATE ON discovery_runs FOR EACH ROW EXECUTE FUNCTION fixture_public_result_drop()").execute(&mut c).await.unwrap();
    let before = public_intake_snapshot(&mut c).await;
    assert_eq!(
        public_owner_runs::finish(&mut c, &public_job_settings(), Uuid::from_u128(66005))
            .await
            .unwrap_err(),
        Failure("discovery_run_write_ack_failed")
    );
    assert_eq!(public_intake_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP TRIGGER fixture_public_result_drop ON discovery_runs;DROP FUNCTION fixture_public_result_drop()").execute(&mut c).await.unwrap();
    assert_eq!(
        public_owner_runs::finish(&mut c, &public_job_settings(), Uuid::from_u128(66005))
            .await
            .unwrap()["counts"]["inserted"],
        1
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_result_late_terminal_journal_trigger_cannot_change_local_jobs_after_initial_intake_ack()
 {
    let mut c = public_intake_fixture().await;
    let at = public_intake_time(&mut c).await;
    public_intake_observation(
        &mut c,
        66006,
        public_intake_input(),
        vec![public_intake_job(at)],
        at,
    )
    .await;
    sqlx::raw_sql("CREATE FUNCTION fixture_public_result_late() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'job_run:') AND NEW.value->>'state'='completed' THEN UPDATE jobs SET status='applied';END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_public_result_late AFTER UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_public_result_late()").execute(&mut c).await.unwrap();
    let before = public_intake_snapshot(&mut c).await;
    assert_eq!(
        public_owner_runs::finish(&mut c, &public_job_settings(), Uuid::from_u128(66006))
            .await
            .unwrap_err(),
        Failure("public_job_intake_write_ack_failed")
    );
    assert_eq!(public_intake_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP TRIGGER fixture_public_result_late ON owner_preferences;DROP FUNCTION fixture_public_result_late()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_result_parent_trigger_profile_change_rolls_back_profile_and_fresh_local_intake() {
    let mut c = public_intake_fixture().await;
    let at = public_intake_time(&mut c).await;
    public_intake_observation(
        &mut c,
        66007,
        public_result_input(),
        vec![public_intake_job(at)],
        at,
    )
    .await;
    sqlx::raw_sql("CREATE FUNCTION fixture_public_result_profile() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN UPDATE candidate_profiles SET version=version+1;RETURN NEW;END $$;CREATE TRIGGER fixture_public_result_profile AFTER UPDATE ON discovery_runs FOR EACH ROW EXECUTE FUNCTION fixture_public_result_profile()").execute(&mut c).await.unwrap();
    let before = public_intake_snapshot(&mut c).await;
    let version: i32 = sqlx::query_scalar("SELECT version FROM candidate_profiles")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(
        public_owner_runs::finish(&mut c, &public_job_settings(), Uuid::from_u128(66007))
            .await
            .unwrap_err(),
        Failure("public_job_intake_profile_changed")
    );
    assert_eq!(public_intake_snapshot(&mut c).await, before);
    assert_eq!(
        sqlx::query_scalar::<_, i32>("SELECT version FROM candidate_profiles")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        version
    );
    sqlx::raw_sql("DROP TRIGGER fixture_public_result_profile ON discovery_runs;DROP FUNCTION fixture_public_result_profile()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_result_history_change_after_ranking_rolls_back_terminal_and_all_fresh_local_writes()
{
    let mut c = public_intake_fixture().await;
    let at = public_intake_time(&mut c).await;
    public_intake_observation(
        &mut c,
        66008,
        public_result_input(),
        vec![public_intake_job(at)],
        at,
    )
    .await;
    sqlx::raw_sql("CREATE FUNCTION fixture_public_result_history() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'job_run:') AND NEW.value->>'state'='completed' THEN INSERT INTO owner_preferences(key,value) VALUES('gmail_application:late_fixture',jsonb_build_object('confirmed_application',true,'company','Fictional Public Employer','role','Fictional Engineer','job_url','https://job-boards.greenhouse.io/fictional/jobs/12345','expires_at',clock_timestamp()+interval '90 days'));END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_public_result_history AFTER UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_public_result_history()").execute(&mut c).await.unwrap();
    let before = public_intake_snapshot(&mut c).await;
    assert_eq!(
        public_owner_runs::finish(&mut c, &public_job_settings(), Uuid::from_u128(66008))
            .await
            .unwrap_err(),
        Failure("discovery_run_write_ack_failed")
    );
    assert_eq!(public_intake_snapshot(&mut c).await, before);
    assert!(!sqlx::query_scalar::<_,bool>("SELECT EXISTS(SELECT 1 FROM owner_preferences WHERE key='gmail_application:late_fixture')").fetch_one(&mut c).await.unwrap());
    sqlx::raw_sql("DROP TRIGGER fixture_public_result_history ON owner_preferences;DROP FUNCTION fixture_public_result_history()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_result_reuses_existing_local_receipt_without_refreshing_job_or_observation_times() {
    let mut c = public_intake_fixture().await;
    public_intake_seed(&mut c, 66009).await;
    let before = public_intake_snapshot(&mut c).await["facts"].clone();
    let pending = public_owner_runs::read(&mut c, Uuid::from_u128(66009))
        .await
        .unwrap();
    assert_eq!(pending["local_intake_complete"], true);
    assert_eq!(pending["rankings_complete"], false);
    assert_eq!(pending["usage"]["stage"], "rankings_pending");
    let result = public_owner_runs::finish(&mut c, &public_job_settings(), Uuid::from_u128(66009))
        .await
        .unwrap();
    assert_eq!(result["status"], "success");
    assert_eq!(result["counts"]["inserted"], 1);
    assert_eq!(public_intake_snapshot(&mut c).await["facts"], before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_result_pending_unknown_child_never_becomes_a_successful_empty_search_or_a_new_remote_admission()
 {
    let mut c = public_intake_fixture().await;
    public_owner_runs::admit(
        &mut c,
        &public_job_settings(),
        public_intake_input(),
        Uuid::from_u128(66010),
        90.0,
    )
    .await
    .unwrap();
    let before = public_intake_snapshot(&mut c).await;
    assert_eq!(
        public_owner_runs::finish(&mut c, &public_job_settings(), Uuid::from_u128(66010))
            .await
            .unwrap_err(),
        Failure("public_job_intake_finding_missing")
    );
    assert_eq!(public_intake_snapshot(&mut c).await, before);
    assert_eq!(
        public_owner_runs::read(&mut c, Uuid::from_u128(66010))
            .await
            .unwrap()["local_intake_complete"],
        false
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_result_reviewed_history_individual_and_total_size_limits_hold_before_returning_partial_rankings()
 {
    for (n, rows, size) in [(66011, 1, 262145), (66012, 35, 245000)] {
        let mut c = public_intake_fixture().await;
        let at = public_intake_time(&mut c).await;
        public_intake_observation(
            &mut c,
            n,
            public_result_input(),
            vec![public_intake_job(at)],
            at,
        )
        .await;
        sqlx::query("INSERT INTO owner_preferences(key,value) SELECT 'gmail_application:oversized_'||n,jsonb_build_object('confirmed_application',true,'company','Unrelated Employer','role','Unrelated Role','job_url',NULL,'expires_at',clock_timestamp()+interval '90 days','private_padding',repeat('x',$2)) FROM generate_series(1,$1) n").bind(rows).bind(size).execute(&mut c).await.unwrap();
        let before = public_intake_snapshot(&mut c).await;
        assert_eq!(
            public_owner_runs::finish(&mut c, &public_job_settings(), Uuid::from_u128(n))
                .await
                .unwrap_err(),
            Failure("gmail_history_limit_reached")
        );
        assert_eq!(public_intake_snapshot(&mut c).await, before);
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_result_missing_saved_intake_receipt_is_read_only_failure_without_manufacturing_a_terminal_result()
 {
    let mut c = public_intake_fixture().await;
    let at = public_intake_time(&mut c).await;
    public_intake_observation(
        &mut c,
        66013,
        public_intake_input(),
        vec![public_intake_job(at)],
        at,
    )
    .await;
    public_owner_runs::finish(&mut c, &public_job_settings(), Uuid::from_u128(66013))
        .await
        .unwrap();
    sqlx::query("DELETE FROM owner_preferences WHERE key=$1")
        .bind(format!("public_ingest:{}", Uuid::from_u128(66013).simple()))
        .execute(&mut c)
        .await
        .unwrap();
    let before = public_intake_snapshot(&mut c).await;
    assert_eq!(
        public_owner_runs::read(&mut c, Uuid::from_u128(66013))
            .await
            .unwrap_err(),
        Failure("discovery_run_intake_receipt_missing")
    );
    assert_eq!(public_intake_snapshot(&mut c).await, before);
}
