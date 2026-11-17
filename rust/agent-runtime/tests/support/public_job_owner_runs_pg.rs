// Deferred actual discovery_runs + original child coupling; private fixture profiles, no real owner data.
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_owner_run_shorter_configured_deadline_caps_the_original_child_lease() {
    let mut c = public_owner_run_fixture().await;
    let id = Uuid::from_u128(64015);
    public_owner_runs::admit(
        &mut c,
        &public_job_settings(),
        public_owner_input(),
        id,
        5.0,
    )
    .await
    .unwrap();
    let journal: Value = sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(public_job_batch_key(64015))
        .fetch_one(&mut c)
        .await
        .unwrap();
    let parse =
        |key: &str| chrono::DateTime::parse_from_rfc3339(journal[key].as_str().unwrap()).unwrap();
    let lease = (parse("expires_at") - parse("started_at"))
        .num_microseconds()
        .unwrap();
    assert!(lease > 0 && lease <= 5_000_000);
    let before = public_owner_run_snapshot(&mut c).await;
    assert!(matches!(
        public_owner_runs::admit(
            &mut c,
            &public_job_settings(),
            public_owner_input(),
            id,
            180.0
        )
        .await
        .unwrap(),
        public_owner_runs::Admission::Retained(_)
    ));
    assert_eq!(public_owner_run_snapshot(&mut c).await, before);
}
use automated_apply_agents::job_sources::runs as public_owner_runs;
async fn public_owner_run_fixture() -> PgConnection {
    let mut c = public_job_access_fixture().await;
    discovery_run_table(&mut c).await;
    c
}
async fn discovery_run_table(c: &mut PgConnection) {
    sqlx::raw_sql("DROP TABLE IF EXISTS discovery_runs CASCADE;DELETE FROM owner_preferences WHERE starts_with(key,'job_run:') OR starts_with(key,'apify_owner:')").execute(&mut *c).await.unwrap();
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
    .execute(&mut *c)
    .await
    .unwrap();
}
fn public_owner_input() -> Value {
    json!({"source":"greenhouse","use_profile":false})
}
fn public_owner_key(n: u128) -> String {
    format!("job_run:{}", Uuid::from_u128(n).simple())
}
async fn public_owner_run_snapshot(c: &mut PgConnection) -> Value {
    let base = public_job_access_snapshot(c).await;
    let rows:Value=sqlx::query_scalar("SELECT jsonb_build_object('runs',(SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM discovery_runs r),'journals',(SELECT jsonb_agg(to_jsonb(p) ORDER BY key) FROM owner_preferences p WHERE starts_with(key,'job_run:')))").fetch_one(c).await.unwrap();
    json!({"source":base,"owner_runs":rows})
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_owner_run_original_admission_couples_real_row_scope_and_child_without_replay() {
    let mut c = public_owner_run_fixture().await;
    let id = Uuid::from_u128(64001);
    let input = public_owner_input();
    let before = public_job_access_snapshot(&mut c).await["owner"].clone();
    let admitted =
        public_owner_runs::admit(&mut c, &public_job_settings(), input.clone(), id, 90.0)
            .await
            .unwrap();
    match admitted {
        public_owner_runs::Admission::Original(c) => assert_eq!(c.request_id(), id),
        _ => panic!("original owner claim required"),
    };
    let saved = public_owner_run_snapshot(&mut c).await;
    assert_eq!(saved["source"]["owner"], before);
    assert_eq!(saved["owner_runs"]["runs"].as_array().unwrap().len(), 1);
    assert_eq!(saved["source"]["journals"].as_array().unwrap().len(), 1);
    let result = public_owner_runs::read(&mut c, id).await.unwrap();
    assert_eq!(result["id"], json!(id));
    assert_eq!(result["status"], "running");
    assert_eq!(result["local_intake_complete"], false);
    assert_eq!(result["job_ids"], json!([]));
    assert!(result.get("profile_pin").is_none());
    let replay = public_owner_runs::admit(&mut c, &public_job_settings(), input, id, 180.0)
        .await
        .unwrap();
    match replay {
        public_owner_runs::Admission::Retained(v) => assert_eq!(v, result),
        _ => panic!("replay cannot obtain original child"),
    };
    assert_eq!(public_owner_run_snapshot(&mut c).await, saved);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_owner_run_changed_body_conflicts_and_missing_board_does_not_leave_parent_or_child()
{
    let mut c = public_owner_run_fixture().await;
    let id = Uuid::from_u128(64002);
    public_owner_runs::admit(
        &mut c,
        &public_job_settings(),
        public_owner_input(),
        id,
        90.0,
    )
    .await
    .unwrap();
    let before = public_owner_run_snapshot(&mut c).await;
    let mut changed = public_owner_input();
    changed["query"] = json!({"keywords":["changed"]});
    assert_eq!(
        public_owner_runs::admit(&mut c, &public_job_settings(), changed, id, 90.0)
            .await
            .err()
            .unwrap(),
        Failure("discovery_run_request_conflict")
    );
    assert_eq!(public_owner_run_snapshot(&mut c).await, before);
    let empty =
        automated_apply_agents::source_registry::Settings::from_values(&BTreeMap::new()).unwrap();
    assert_eq!(
        public_owner_runs::admit(
            &mut c,
            &empty,
            public_owner_input(),
            Uuid::from_u128(64003),
            90.0
        )
        .await
        .err()
        .unwrap(),
        Failure("public_job_boards_not_configured")
    );
    assert_eq!(public_owner_run_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_owner_run_compatibility_collision_preserves_original_legacy_row_and_consumes_no_source_window()
 {
    let mut c = public_owner_run_fixture().await;
    sqlx::query("INSERT INTO discovery_runs(id,source,request_hash,idempotency_key,query_summary) VALUES($1,'manual','fictional_legacy_hash','fictional_reused_key','{\"private\":\"PRIVATE_LEGACY_CANARY\"}')").bind(Uuid::from_u128(64004)).execute(&mut c).await.unwrap();
    let before = public_owner_run_snapshot(&mut c).await;
    let mut input = public_owner_input();
    input["idempotency_key"] = json!("fictional_reused_key");
    assert_eq!(
        public_owner_runs::admit(
            &mut c,
            &public_job_settings(),
            input,
            Uuid::from_u128(64005),
            90.0
        )
        .await
        .err()
        .unwrap(),
        Failure("discovery_run_compatibility_key_conflict")
    );
    assert_eq!(public_owner_run_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_owner_run_cannot_attach_an_unscoped_preexisting_public_child() {
    let mut c = public_owner_run_fixture().await;
    let id = Uuid::from_u128(64006);
    public_job_access::admit(
        &mut c,
        &public_job_settings(),
        PublicJobSource::Greenhouse,
        json!({}),
        id,
    )
    .await
    .unwrap();
    let before = public_owner_run_snapshot(&mut c).await;
    assert_eq!(
        public_owner_runs::admit(
            &mut c,
            &public_job_settings(),
            public_owner_input(),
            id,
            90.0
        )
        .await
        .err()
        .unwrap(),
        Failure("discovery_run_source_id_already_claimed")
    );
    assert_eq!(public_owner_run_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_owner_run_profile_expansion_and_private_pin_remain_original_after_profile_change_and_replay()
 {
    let mut c = public_owner_run_fixture().await;
    sqlx::query("UPDATE candidate_profiles SET preferences=preferences::jsonb||'{\"target_titles\":[\"Rust Engineer\"],\"preferred_locations\":[\"Remote\"],\"remote_preference\":\"remote\",\"employment_types\":[\"full_time\"]}'::jsonb").execute(&mut c).await.unwrap();
    let id = Uuid::from_u128(64007);
    let input = json!({"source":"greenhouse","use_profile":true});
    public_owner_runs::admit(&mut c, &public_job_settings(), input.clone(), id, 90.0)
        .await
        .unwrap();
    let journal: Value = sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(public_owner_key(64007))
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(
        journal["scope"]["effective_query"]["keywords"],
        json!(["Rust Engineer"])
    );
    assert_eq!(journal["scope"]["explicit_query"]["keywords"], json!([]));
    assert!(journal["scope"]["profile_pin"]["content_hash"].is_string());
    assert!(journal["scope"].get("full_name").is_none());
    sqlx::query("UPDATE candidate_profiles SET version=version+1,preferences=jsonb_set(preferences::jsonb,'{target_titles}','[\"Golang Engineer\"]')").execute(&mut c).await.unwrap();
    let before = public_owner_run_snapshot(&mut c).await;
    assert!(matches!(
        public_owner_runs::admit(&mut c, &public_job_settings(), input, id, 90.0)
            .await
            .unwrap(),
        public_owner_runs::Admission::Retained(_)
    ));
    assert_eq!(public_owner_run_snapshot(&mut c).await, before);
    let same: Value = sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(public_owner_key(64007))
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(same, journal);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_owner_run_disabled_profile_never_queries_missing_profile_table() {
    let mut c = public_owner_run_fixture().await;
    sqlx::raw_sql("DROP TABLE candidate_profiles CASCADE")
        .execute(&mut c)
        .await
        .unwrap();
    let id = Uuid::from_u128(64008);
    public_owner_runs::admit(
        &mut c,
        &public_job_settings(),
        public_owner_input(),
        id,
        90.0,
    )
    .await
    .unwrap();
    assert!(public_owner_runs::read(&mut c, id).await.unwrap()["profile_version"].is_null());
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_owner_run_parent_journal_trigger_cannot_change_child_window_after_its_initial_ack()
{
    let mut c = public_owner_run_fixture().await;
    sqlx::raw_sql("CREATE FUNCTION fixture_owner_run_pace() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'job_run:') THEN UPDATE provider_access_windows SET next_allowed_at=next_allowed_at+interval '1 second';END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_owner_run_pace AFTER INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_owner_run_pace()").execute(&mut c).await.unwrap();
    let before = public_owner_run_snapshot(&mut c).await;
    assert_eq!(
        public_owner_runs::admit(
            &mut c,
            &public_job_settings(),
            public_owner_input(),
            Uuid::from_u128(64009),
            90.0
        )
        .await
        .err()
        .unwrap(),
        Failure("public_job_write_ack_failed")
    );
    assert_eq!(public_owner_run_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP FUNCTION fixture_owner_run_pace() CASCADE")
        .execute(&mut c)
        .await
        .unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_owner_run_failed_real_row_ack_rolls_back_child_journal_and_original_source_window()
{
    let mut c = public_owner_run_fixture().await;
    sqlx::raw_sql("CREATE FUNCTION fixture_owner_run_row() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NULL;END $$;CREATE TRIGGER fixture_owner_run_row BEFORE INSERT ON discovery_runs FOR EACH ROW EXECUTE FUNCTION fixture_owner_run_row()").execute(&mut c).await.unwrap();
    let before = public_owner_run_snapshot(&mut c).await;
    assert_eq!(
        public_owner_runs::admit(
            &mut c,
            &public_job_settings(),
            public_owner_input(),
            Uuid::from_u128(64010),
            90.0
        )
        .await
        .err()
        .unwrap(),
        Failure("discovery_run_write_ack_failed")
    );
    assert_eq!(public_owner_run_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP FUNCTION fixture_owner_run_row() CASCADE")
        .execute(&mut c)
        .await
        .unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_owner_run_saved_scope_tampering_is_read_only_failure_and_legacy_rows_are_not_adopted()
 {
    let mut c = public_owner_run_fixture().await;
    let id = Uuid::from_u128(64011);
    public_owner_runs::admit(
        &mut c,
        &public_job_settings(),
        public_owner_input(),
        id,
        90.0,
    )
    .await
    .unwrap();
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{scope_hash}','\"tampered\"') WHERE key=$1").bind(public_owner_key(64011)).execute(&mut c).await.unwrap();
    let before = public_owner_run_snapshot(&mut c).await;
    assert_eq!(
        public_owner_runs::read(&mut c, id).await,
        Err(Failure("invalid_discovery_owner_run"))
    );
    assert_eq!(public_owner_run_snapshot(&mut c).await, before);
    let mut changed = before["owner_runs"]["journals"][0]["value"].clone();
    changed["scope"]["provider_calls"] = json!(99);
    changed["scope_hash"] = json!(automated_apply_agents::python_json::digest(
        &changed["scope"]
    ));
    sqlx::query("UPDATE owner_preferences SET value=$2 WHERE key=$1")
        .bind(public_owner_key(64011))
        .bind(changed)
        .execute(&mut c)
        .await
        .unwrap();
    let guarded = public_owner_run_snapshot(&mut c).await;
    assert_eq!(
        public_owner_runs::read(&mut c, id).await,
        Err(Failure("invalid_discovery_profile_scope"))
    );
    assert_eq!(public_owner_run_snapshot(&mut c).await, guarded);
    sqlx::query("INSERT INTO discovery_runs(id,source,request_hash) VALUES($1,'greenhouse','fictional_legacy_hash')").bind(Uuid::from_u128(64012)).execute(&mut c).await.unwrap();
    assert_eq!(
        public_owner_runs::read(&mut c, Uuid::from_u128(64012)).await,
        Err(Failure("discovery_run_original_scope_missing"))
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_owner_run_profile_trigger_change_rolls_back_parent_child_and_profile_together() {
    let mut c = public_owner_run_fixture().await;
    let profile_before: Value = sqlx::query_scalar(
        "SELECT to_jsonb(p) FROM candidate_profiles p WHERE singleton_key='primary'",
    )
    .fetch_one(&mut c)
    .await
    .unwrap();
    sqlx::raw_sql("CREATE FUNCTION fixture_owner_run_profile() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'job_run:') THEN UPDATE candidate_profiles SET version=version+1 WHERE singleton_key='primary';END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_owner_run_profile AFTER INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_owner_run_profile()").execute(&mut c).await.unwrap();
    let before = public_owner_run_snapshot(&mut c).await;
    assert_eq!(
        public_owner_runs::admit(
            &mut c,
            &public_job_settings(),
            json!({"source":"greenhouse","use_profile":true}),
            Uuid::from_u128(64014),
            90.0
        )
        .await
        .err()
        .unwrap(),
        Failure("discovery_run_write_ack_failed")
    );
    assert_eq!(public_owner_run_snapshot(&mut c).await, before);
    let profile_after: Value = sqlx::query_scalar(
        "SELECT to_jsonb(p) FROM candidate_profiles p WHERE singleton_key='primary'",
    )
    .fetch_one(&mut c)
    .await
    .unwrap();
    assert_eq!(profile_after, profile_before);
    sqlx::raw_sql("DROP FUNCTION fixture_owner_run_profile() CASCADE")
        .execute(&mut c)
        .await
        .unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_owner_run_actual_acquisition_retains_child_but_qualifies_pending_local_intake_and_never_replays()
 {
    let mut c = public_owner_run_fixture().await;
    let (v, f, stop, task) = public_job_http(PublicJobSource::Greenhouse, "ok").await;
    let settings = automated_apply_agents::source_registry::Settings::from_values(&v).unwrap();
    let client = PublicJobClient::from_values(&v, true).unwrap();
    let service = public_owner_runs::Service {
        settings: &settings,
        client: &client,
        timeout_seconds: 90.0,
    };
    let id = Uuid::from_u128(64013);
    let jobs_before: Value =
        sqlx::query_scalar("SELECT jsonb_agg(to_jsonb(j) ORDER BY id) FROM jobs j")
            .fetch_one(&mut c)
            .await
            .unwrap();
    let result = service
        .acquire(&mut c, public_owner_input(), id)
        .await
        .unwrap();
    assert_eq!(result["status"], "running");
    assert_eq!(result["usage"]["stage"], "local_intake_pending");
    assert_eq!(result["counts"]["discovered"], 1);
    assert_eq!(result["counts"]["inserted"], 0);
    assert_eq!(result["job_ids"], json!([]));
    assert_eq!(result["local_intake_complete"], false);
    assert_eq!(result["application_dispatch"], false);
    assert!(!result.to_string().contains("CANARY"));
    assert_eq!(f.calls.load(Ordering::SeqCst), 1);
    let before = public_owner_run_snapshot(&mut c).await;
    let replay = service
        .acquire(&mut c, public_owner_input(), id)
        .await
        .unwrap();
    assert_eq!(replay, result);
    assert_eq!(public_owner_run_snapshot(&mut c).await, before);
    assert_eq!(f.calls.load(Ordering::SeqCst), 1);
    let jobs_after: Value =
        sqlx::query_scalar("SELECT jsonb_agg(to_jsonb(j) ORDER BY id) FROM jobs j")
            .fetch_one(&mut c)
            .await
            .unwrap();
    assert_eq!(jobs_after, jobs_before);
    stop.cancel();
    task.await.unwrap();
}
