// Deferred original manual startup run lifecycle fixtures. No provider or platform requests.
use automated_apply_agents::startup_catalog::runs as startup_runs;
async fn startup_run_fixture() -> PgConnection {
    let (mut c, _, _) = startup_detail_fixture().await;
    sqlx::raw_sql("ALTER TABLE companies ADD COLUMN IF NOT EXISTS linkedin_url text,ADD COLUMN IF NOT EXISTS email_pattern varchar(100),ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT clock_timestamp(),ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT clock_timestamp();CREATE UNIQUE INDEX IF NOT EXISTS fixture_manual_company_observation_unique ON company_source_observations(source,identity_key,content_hash);DROP TABLE IF EXISTS discovery_runs CASCADE").execute(&mut c).await.unwrap();
    let source = include_str!("../../../../supabase/fresh_public/001_phase1_public.sql");
    let table = source
        .split("CREATE TABLE IF NOT EXISTS public.discovery_runs (")
        .nth(1)
        .unwrap()
        .split("CREATE TABLE IF NOT EXISTS public.job_source_observations (")
        .next()
        .unwrap();
    sqlx::raw_sql(sqlx::AssertSqlSafe(format!(
        "CREATE TABLE IF NOT EXISTS public.discovery_runs ({table}"
    )))
    .execute(&mut c)
    .await
    .unwrap();
    c
}
fn startup_run_input(key: &str) -> Value {
    json!({"idempotency_key":key,"source":"manual","mode":"company_first","permission_confirmed":true,"filters":{"use_profile":false,"max_employees":null},"companies":[startup_observation(Some("manual-run-fixture.example"),Some("manual-run-source"))]})
}
async fn startup_run(c: &mut PgConnection, input: Value) -> Result<Value> {
    startup_runs::run_manual(c, input, &contact_settings(), 90.0).await
}
async fn startup_run_snapshot(c: &mut PgConnection) -> Value {
    sqlx::query_scalar("SELECT jsonb_build_object('runs',(SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM discovery_runs r),'journals',(SELECT jsonb_object_agg(key,value) FROM owner_preferences WHERE starts_with(key,'startup_run:')))").fetch_one(c).await.unwrap()
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_run_manual_import_ranks_only_its_companies_and_replay_preserves_original_evidence()
{
    let mut c = startup_run_fixture().await;
    let input = startup_run_input("fictional_manual_startup");
    let first = startup_run(&mut c, input.clone()).await.unwrap();
    assert_eq!(first["status"], "success");
    assert_eq!(first["counts"]["companies_observed"], 1);
    assert_eq!(first["counts"]["companies_matching"], 1);
    assert_eq!(first["rankings"].as_array().unwrap().len(), 1);
    assert_eq!(
        first["rankings"][0]["company_domain"],
        "manual-run-fixture.example"
    );
    assert_eq!(first["provider_calls_performed_by_read"], 0);
    let run_before = startup_run_snapshot(&mut c).await;
    let data_before = companies_snapshot(&mut c).await;
    let second = startup_run(&mut c, input).await.unwrap();
    assert_eq!(second, first);
    assert_eq!(startup_run_snapshot(&mut c).await, run_before);
    assert_eq!(companies_snapshot(&mut c).await, data_before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_run_manual_empty_input_retains_an_honest_manual_input_required_result() {
    let mut c = startup_run_fixture().await;
    let result = startup_run(&mut c, json!({"idempotency_key":"fictional_empty_manual"}))
        .await
        .unwrap();
    assert_eq!(result["status"], "manual_input_required");
    assert_eq!(result["counts"]["companies_observed"], 0);
    assert_eq!(result["rankings"], json!([]));
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_run_idempotency_conflicts_do_not_create_a_second_run_or_rewrite_the_first() {
    let mut c = startup_run_fixture().await;
    let input = startup_run_input("fictional_conflicting_manual");
    startup_run(&mut c, input.clone()).await.unwrap();
    let before = startup_run_snapshot(&mut c).await;
    let mut changed = input;
    changed["filters"]["early_stage"] = json!(true);
    assert_eq!(
        startup_run(&mut c, changed).await.unwrap_err(),
        Failure("startup_run_idempotency_conflict")
    );
    assert_eq!(startup_run_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_run_lost_original_invocation_is_retained_only_and_never_renews_or_imports_on_replay()
 {
    let mut c = startup_run_fixture().await;
    let input = startup_run_input("fictional_interrupted_manual");
    let admitted = startup_runs::admit_manual(&mut c, input.clone(), 90.0)
        .await
        .unwrap();
    assert!(matches!(admitted, startup_runs::Admission::Original(_)));
    let before = startup_run_snapshot(&mut c).await;
    let data_before = companies_snapshot(&mut c).await;
    let replay = startup_run(&mut c, input).await.unwrap();
    assert_eq!(replay["status"], "running");
    assert_eq!(startup_run_snapshot(&mut c).await, before);
    assert_eq!(companies_snapshot(&mut c).await, data_before);
    assert!(replay.get("token").is_none());
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_run_expired_retained_history_qualifies_recovery_without_get_writes_or_provider_retry()
 {
    let mut c = startup_run_fixture().await;
    let input = startup_run_input("fictional_old_manual");
    let result = startup_runs::admit_manual(&mut c, input, 90.0)
        .await
        .unwrap();
    let startup_runs::Admission::Original(_) = result else {
        panic!("original invocation required")
    };
    sqlx::query("UPDATE discovery_runs SET started_at=clock_timestamp()-interval '1 hour'")
        .execute(&mut c)
        .await
        .unwrap();
    let id: Uuid = sqlx::query_scalar("SELECT id FROM discovery_runs")
        .fetch_one(&mut c)
        .await
        .unwrap();
    let before = startup_run_snapshot(&mut c).await;
    let result = startup_runs::read(&mut c, id, 90.0).await.unwrap();
    assert_eq!(result["status"], "recovery_required");
    assert_eq!(result["recorded_status"], "running");
    assert_eq!(startup_run_snapshot(&mut c).await, before);
    assert!(result.to_string().find("token").is_none());
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_run_failed_observation_save_rolls_back_company_batch_but_preserves_the_admitted_run()
 {
    let mut c = startup_run_fixture().await;
    sqlx::raw_sql("CREATE FUNCTION fixture_manual_observation_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NULL;END $$;CREATE TRIGGER fixture_manual_observation_drop BEFORE INSERT ON company_source_observations FOR EACH ROW EXECUTE FUNCTION fixture_manual_observation_drop()").execute(&mut c).await.unwrap();
    let input = startup_run_input("fictional_failed_manual");
    let data_before = companies_snapshot(&mut c).await;
    assert_eq!(
        startup_run(&mut c, input.clone()).await.unwrap_err(),
        Failure("startup_identity_write_ack_failed")
    );
    assert_eq!(companies_snapshot(&mut c).await, data_before);
    let row: Value = sqlx::query_scalar("SELECT to_jsonb(r) FROM discovery_runs r")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(row["status"], "running");
    assert_eq!(
        startup_run(&mut c, input).await.unwrap()["status"],
        "running"
    );
    sqlx::raw_sql("DROP TRIGGER fixture_manual_observation_drop ON company_source_observations;DROP FUNCTION fixture_manual_observation_drop()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_run_admission_and_finish_ack_failures_are_atomic_and_never_return_false_success() {
    let mut c = startup_run_fixture().await;
    let before = startup_run_snapshot(&mut c).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_manual_run_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NULL;END $$;CREATE TRIGGER fixture_manual_run_drop BEFORE INSERT ON discovery_runs FOR EACH ROW EXECUTE FUNCTION fixture_manual_run_drop()").execute(&mut c).await.unwrap();
    assert_eq!(
        startup_run(&mut c, startup_run_input("fictional_admission_ack"))
            .await
            .unwrap_err(),
        Failure("startup_run_write_ack_failed")
    );
    assert_eq!(startup_run_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP TRIGGER fixture_manual_run_drop ON discovery_runs;DROP FUNCTION fixture_manual_run_drop();CREATE FUNCTION fixture_manual_finish_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'startup_run:') AND NEW.value->>'state'='completed' THEN RETURN NULL;END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_manual_finish_drop BEFORE UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_manual_finish_drop()").execute(&mut c).await.unwrap();
    let data_before = companies_snapshot(&mut c).await;
    assert_eq!(
        startup_run(&mut c, startup_run_input("fictional_finish_ack"))
            .await
            .unwrap_err(),
        Failure("startup_run_write_ack_failed")
    );
    assert_eq!(companies_snapshot(&mut c).await, data_before);
    let row: Value = sqlx::query_scalar("SELECT to_jsonb(r) FROM discovery_runs r")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(row["status"], "running");
    sqlx::raw_sql("DROP TRIGGER fixture_manual_finish_drop ON owner_preferences;DROP FUNCTION fixture_manual_finish_drop()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_run_complete_row_drift_blocks_the_original_invocation_and_preserves_its_admission()
{
    let mut c = startup_run_fixture().await;
    let admitted =
        startup_runs::admit_manual(&mut c, startup_run_input("fictional_changed_run"), 90.0)
            .await
            .unwrap();
    let startup_runs::Admission::Original(invocation) = admitted else {
        panic!("original invocation required")
    };
    sqlx::query("UPDATE discovery_runs SET errors='[\"owner_review_marker\"]'")
        .execute(&mut c)
        .await
        .unwrap();
    let before = startup_run_snapshot(&mut c).await;
    assert_eq!(
        startup_runs::complete_manual(&mut c, *invocation, &contact_settings(), 90.0)
            .await
            .unwrap_err(),
        Failure("startup_run_invocation_conflict")
    );
    assert_eq!(startup_run_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_run_missing_permissions_or_nonmanual_request_does_not_claim_any_run() {
    let mut c = startup_run_fixture().await;
    let mut input = startup_run_input("fictional_permission_required");
    input["permission_confirmed"] = json!(false);
    assert_eq!(
        startup_run(&mut c, input).await.unwrap_err(),
        Failure("invalid_research_contract")
    );
    assert_eq!(startup_run(&mut c,json!({"idempotency_key":"fictional_other_source","source":"greenhouse","mode":"job_led"})).await.unwrap_err(),Failure("startup_manual_run_required"));
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM discovery_runs")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_run_saved_history_excludes_private_query_vendor_usage_and_journal_data() {
    let mut c = startup_run_fixture().await;
    let saved = startup_run(&mut c, startup_run_input("fictional_private_run"))
        .await
        .unwrap();
    let id = saved["id"].as_str().unwrap().parse::<Uuid>().unwrap();
    sqlx::query("UPDATE discovery_runs SET query_summary=query_summary||'{\"private_input\":\"PRIVATE_RUN_INPUT_CANARY\"}',usage='{\"private_token\":\"PRIVATE_RUN_USAGE_CANARY\"}',provider_run_id='PRIVATE_PROVIDER_REFERENCE_CANARY',errors='[\"PRIVATE_ERROR_CANARY\"]' WHERE id=$1").bind(id).execute(&mut c).await.unwrap();
    let before = startup_run_snapshot(&mut c).await;
    let result = startup_runs::read(&mut c, id, 90.0).await.unwrap();
    for private in [
        "PRIVATE_RUN_INPUT_CANARY",
        "PRIVATE_RUN_USAGE_CANARY",
        "PRIVATE_PROVIDER_REFERENCE_CANARY",
        "PRIVATE_ERROR_CANARY",
    ] {
        assert!(!result.to_string().contains(private));
    }
    assert_eq!(
        result["errors"],
        json!(["startup_saved_error_requires_review"])
    );
    assert_eq!(startup_run_snapshot(&mut c).await, before);
}
