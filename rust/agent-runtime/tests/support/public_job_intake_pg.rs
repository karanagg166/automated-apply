//! Deferred actual-schema local intake fixtures. Selected findings below are fictional, not provider acceptance.
use automated_apply_agents::job_sources::intake as public_intake;
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_intake_original_loopback_acquisition_can_finish_local_sql_without_a_second_provider_get()
 {
    let mut c = public_intake_fixture().await;
    let (values, remote, stop, task) = public_job_http(PublicJobSource::Greenhouse, "ok").await;
    let settings = automated_apply_agents::source_registry::Settings::from_values(&values).unwrap();
    let client = PublicJobClient::from_values(&values, true).unwrap();
    let id = Uuid::from_u128(65020);
    public_owner_runs::Service {
        settings: &settings,
        client: &client,
        timeout_seconds: 90.0,
    }
    .acquire(&mut c, public_intake_input(), id)
    .await
    .unwrap();
    let first = public_intake::ingest_retained(&mut c, &settings, id)
        .await
        .unwrap();
    assert_eq!(first["counts"]["inserted"], 1);
    assert_eq!(remote.calls.load(Ordering::SeqCst), 1);
    let before = public_intake_snapshot(&mut c).await;
    assert_eq!(
        public_intake::ingest_retained(&mut c, &settings, id)
            .await
            .unwrap(),
        first
    );
    assert_eq!(remote.calls.load(Ordering::SeqCst), 1);
    assert_eq!(public_intake_snapshot(&mut c).await, before);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_intake_ambiguous_company_names_create_one_unresolved_company_and_reuse_it_without_promoting_domains()
 {
    let mut c = public_intake_fixture().await;
    for domain in ["first.example", "second.example"] {
        sqlx::query("INSERT INTO companies(name,domain,metadata) VALUES('Fictional Public Employer',$1,'{\"retained_fact\":true}')").bind(domain).execute(&mut c).await.unwrap();
    }
    let id = public_intake_seed(&mut c, 65021).await;
    let company: Value = sqlx::query_scalar(
        "SELECT to_jsonb(c) FROM companies c JOIN jobs j ON j.company_id=c.id WHERE j.id=$1",
    )
    .bind(id)
    .fetch_one(&mut c)
    .await
    .unwrap();
    assert!(company["domain"].is_null());
    assert_eq!(company["metadata"]["identity_review_required"], true);
    let at = public_intake_time(&mut c).await;
    let mut job = public_intake_job(at);
    job["source_job_id"] = json!("12346");
    job["original_url"] = json!("https://boards.greenhouse.io/fictional/jobs/12346");
    job["canonical_url"] = Value::Null;
    job["application_url"] = job["original_url"].clone();
    public_intake_observation(&mut c, 65022, public_intake_input(), vec![job], at).await;
    public_intake::ingest_retained(&mut c, &public_job_settings(), Uuid::from_u128(65022))
        .await
        .unwrap();
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM companies")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        3
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_intake_now_timestamp_trigger_is_accepted_but_changed_non_timestamp_fields_roll_back()
 {
    let mut c = public_intake_fixture().await;
    sqlx::raw_sql("CREATE FUNCTION fixture_public_intake_now() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.updated_at=now();RETURN NEW;END $$;CREATE TRIGGER fixture_public_intake_now BEFORE INSERT OR UPDATE ON jobs FOR EACH ROW EXECUTE FUNCTION fixture_public_intake_now()").execute(&mut c).await.unwrap();
    let id = public_intake_seed(&mut c, 65023).await;
    let at = public_intake_time(&mut c).await;
    public_intake_observation(
        &mut c,
        65024,
        public_intake_input(),
        vec![public_intake_job(at)],
        at,
    )
    .await;
    public_intake::ingest_retained(&mut c, &public_job_settings(), Uuid::from_u128(65024))
        .await
        .unwrap();
    sqlx::raw_sql("CREATE FUNCTION fixture_public_intake_rewrite() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.title='Changed by trigger';RETURN NEW;END $$;CREATE TRIGGER fixture_public_intake_rewrite BEFORE UPDATE ON jobs FOR EACH ROW EXECUTE FUNCTION fixture_public_intake_rewrite()").execute(&mut c).await.unwrap();
    let at = public_intake_time(&mut c).await;
    public_intake_observation(
        &mut c,
        65025,
        public_intake_input(),
        vec![public_intake_job(at)],
        at,
    )
    .await;
    let before = public_intake_snapshot(&mut c).await;
    assert_eq!(
        public_intake::ingest_retained(&mut c, &public_job_settings(), Uuid::from_u128(65025))
            .await
            .unwrap_err(),
        Failure("public_job_intake_write_ack_failed")
    );
    assert_eq!(public_intake_snapshot(&mut c).await, before);
    assert_eq!(
        sqlx::query_scalar::<_, String>("SELECT title FROM jobs WHERE id=$1")
            .bind(id)
            .fetch_one(&mut c)
            .await
            .unwrap(),
        "Fictional Engineer"
    );
    sqlx::raw_sql("DROP TRIGGER fixture_public_intake_rewrite ON jobs;DROP FUNCTION fixture_public_intake_rewrite();DROP TRIGGER fixture_public_intake_now ON jobs;DROP FUNCTION fixture_public_intake_now()").execute(&mut c).await.unwrap();
}
async fn public_intake_fixture() -> PgConnection {
    let mut c = public_owner_run_fixture().await;
    sqlx::raw_sql("DROP TABLE IF EXISTS job_source_observations CASCADE;DROP TABLE IF EXISTS jobs CASCADE;DROP TABLE IF EXISTS companies CASCADE;DELETE FROM owner_preferences WHERE starts_with(key,'public_ingest:')").execute(&mut c).await.unwrap();
    let schema = include_str!("../../../../supabase/fresh_public/001_phase1_public.sql");
    for (start, end) in [
        (
            "CREATE TABLE IF NOT EXISTS public.companies (",
            "CREATE INDEX IF NOT EXISTS idx_companies_domain",
        ),
        (
            "CREATE TABLE IF NOT EXISTS public.jobs (",
            "CREATE INDEX IF NOT EXISTS idx_jobs_company_id",
        ),
        (
            "ALTER TABLE public.jobs\n    ADD COLUMN IF NOT EXISTS canonical_key",
            "CREATE TABLE IF NOT EXISTS public.discovery_runs (",
        ),
        (
            "CREATE TABLE IF NOT EXISTS public.job_source_observations (",
            "CREATE INDEX IF NOT EXISTS idx_observation_job",
        ),
    ] {
        let segment = schema
            .split_once(start)
            .unwrap()
            .1
            .split_once(end)
            .unwrap()
            .0;
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("{start}{segment}")))
            .execute(&mut c)
            .await
            .unwrap();
    }
    c
}
async fn public_intake_snapshot(c: &mut PgConnection) -> Value {
    let public = public_owner_run_snapshot(c).await;
    let facts:Value=sqlx::query_scalar("SELECT jsonb_build_object('companies',(SELECT jsonb_agg(to_jsonb(c) ORDER BY id) FROM companies c),'jobs',(SELECT jsonb_agg(to_jsonb(j) ORDER BY id) FROM jobs j),'observations',(SELECT jsonb_agg(to_jsonb(o) ORDER BY id) FROM job_source_observations o),'receipts',(SELECT jsonb_agg(jsonb_build_object('key',key,'value',value) ORDER BY key) FROM owner_preferences WHERE starts_with(key,'public_ingest:')))").fetch_one(c).await.unwrap();
    json!({"original":public,"facts":facts})
}
async fn public_intake_time(c: &mut PgConnection) -> chrono::DateTime<chrono::Utc> {
    sqlx::query_scalar("SELECT clock_timestamp()")
        .fetch_one(c)
        .await
        .unwrap()
}
fn public_intake_job(now: chrono::DateTime<chrono::Utc>) -> Value {
    automated_apply_agents::job_sources::records::greenhouse(&json!({"id":12345,"absolute_url":"https://boards.greenhouse.io/fictional/jobs/12345","title":"Fictional Engineer","content":"Public fictional role","location":{"name":"Remote"}}),"fictional","Fictional Public Employer",now).unwrap()
}
async fn public_intake_observation(
    c: &mut PgConnection,
    n: u128,
    input: Value,
    mut jobs: Vec<Value>,
    at: chrono::DateTime<chrono::Utc>,
) {
    // Each fixture new run independently admits its original child. Only fixture source pacing is cleared.
    sqlx::query("DELETE FROM provider_access_windows WHERE provider='greenhouse'")
        .execute(&mut *c)
        .await
        .unwrap();
    public_owner_runs::admit(c, &public_job_settings(), input, Uuid::from_u128(n), 90.0)
        .await
        .unwrap();
    for job in &mut jobs {
        *job = automated_apply_agents::job_sources::contract::normalize(job.clone(), at).unwrap();
    }
    let finding = json!({"source":"greenhouse","status":if jobs.is_empty(){"no_results"}else{"success"},"transport_state":"completed","batch_complete":true,"jobs":jobs,"errors":[],"cooldown_requires_review":false,"rejected_count":0,"duplicate_count":0,"next_cursor":null,"provider_http_attempts":1,"provider_responses_observed":1,"decoded_bytes":100,"observed_at":at.to_rfc3339(),"application_dispatch":false,"live_verified":false});
    let mut journal: Value = sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(public_job_batch_key(n))
        .fetch_one(&mut *c)
        .await
        .unwrap();
    journal["state"] = json!("finding_retained");
    journal["finding_hash"] = json!(automated_apply_agents::python_json::digest(&finding));
    journal["finding"] = finding;
    sqlx::query("UPDATE owner_preferences SET value=$2 WHERE key=$1")
        .bind(public_job_batch_key(n))
        .bind(journal)
        .execute(c)
        .await
        .unwrap();
}
fn public_intake_input() -> Value {
    json!({"source":"greenhouse","use_profile":false,"query":{"max_age_days":null}})
}
async fn public_intake_seed(c: &mut PgConnection, n: u128) -> Uuid {
    let now = public_intake_time(c).await;
    public_intake_observation(
        c,
        n,
        public_intake_input(),
        vec![public_intake_job(now)],
        now,
    )
    .await;
    let result = public_intake::ingest_retained(c, &public_job_settings(), Uuid::from_u128(n))
        .await
        .unwrap();
    result["job_ids"][0].as_str().unwrap().parse().unwrap()
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_intake_actual_schema_receipt_and_replay_preserve_original_freshness_after_configuration_changes()
 {
    let mut c = public_intake_fixture().await;
    let id = public_intake_seed(&mut c, 65001).await;
    let first = public_intake::read(&mut c, Uuid::from_u128(65001))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(first["counts"]["inserted"], 1);
    assert_eq!(first["local_intake_complete"], true);
    assert_eq!(first["rankings_complete"], false);
    assert_eq!(first["provider_calls"], 0);
    assert_eq!(first["application_dispatch"], false);
    let job: Value = sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1")
        .bind(id)
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(job["status"], "discovered");
    assert_eq!(job["remote_type"], "remote");
    assert!(job["match_score"].is_null());
    sqlx::query("UPDATE candidate_profiles SET version=version+1")
        .execute(&mut c)
        .await
        .unwrap();
    let before = public_intake_snapshot(&mut c).await;
    let settings =
        automated_apply_agents::source_registry::Settings::from_values(&BTreeMap::new()).unwrap();
    assert_eq!(
        public_intake::ingest_retained(&mut c, &settings, Uuid::from_u128(65001))
            .await
            .unwrap(),
        first
    );
    assert_eq!(public_intake_snapshot(&mut c).await, before);
    assert_eq!(
        public_owner_runs::read(&mut c, Uuid::from_u128(65001))
            .await
            .unwrap()["local_intake_complete"],
        true,
        "parent displays its saved local receipt while rankings remain pending"
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_intake_reobservation_preserves_applied_decision_notes_scores_links_and_secondary_primary_evidence()
 {
    let mut c = public_intake_fixture().await;
    let id = public_intake_seed(&mut c, 65002).await;
    sqlx::raw_sql("ALTER TABLE jobs ADD COLUMN owner_notes text")
        .execute(&mut c)
        .await
        .unwrap();
    sqlx::query("UPDATE jobs SET title='Owner title',status='applied',match_score=89.25,match_explanation='Owner decision',owner_notes='Retain private review',source_platform='manual',application_url='https://example.com/original',salary_min=10,salary_max=NULL,salary_currency='USD',salary_period='month',discovery_metadata=discovery_metadata||'{\"experience_min_years\":4,\"experience_max_years\":8,\"private_owner_marker\":true}'::jsonb WHERE id=$1").bind(id).execute(&mut c).await.unwrap();
    let before: Value = sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1")
        .bind(id)
        .fetch_one(&mut c)
        .await
        .unwrap();
    let at = public_intake_time(&mut c).await;
    let mut job = public_intake_job(at);
    job["title"] = json!("New provider title");
    job["experience_min_years"] = json!(0);
    job["experience_max_years"] = json!(1);
    job["salary_min"] = json!(50000);
    job["salary_currency"] = json!("EUR");
    job["salary_period"] = json!("year");
    public_intake_observation(&mut c, 65003, public_intake_input(), vec![job], at).await;
    let result =
        public_intake::ingest_retained(&mut c, &public_job_settings(), Uuid::from_u128(65003))
            .await
            .unwrap();
    assert_eq!(result["counts"]["duplicate"], 1);
    assert_eq!(result["job_ids"], json!([id]));
    let after: Value = sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j WHERE id=$1")
        .bind(id)
        .fetch_one(&mut c)
        .await
        .unwrap();
    for key in [
        "title",
        "status",
        "match_score",
        "match_explanation",
        "owner_notes",
        "source_platform",
        "job_url",
        "application_url",
        "salary_min",
        "salary_max",
        "salary_currency",
        "salary_period",
        "discovery_metadata",
        "company_id",
        "created_at",
    ] {
        assert_eq!(after[key], before[key], "{key}");
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_intake_complete_legacy_url_inventory_detects_tracking_alias_ambiguity_before_creating_employers()
 {
    let mut c = public_intake_fixture().await;
    let at = public_intake_time(&mut c).await;
    for suffix in ["first", "second"] {
        sqlx::query("INSERT INTO jobs(title,job_url,source_platform) VALUES('Retained legacy title',$1,'manual')").bind(format!("https://boards.greenhouse.io/fictional/jobs/12345?utm_source={suffix}")).execute(&mut c).await.unwrap();
    }
    public_intake_observation(
        &mut c,
        65004,
        public_intake_input(),
        vec![public_intake_job(at)],
        at,
    )
    .await;
    let before = public_intake_snapshot(&mut c).await;
    assert_eq!(
        public_intake::ingest_retained(&mut c, &public_job_settings(), Uuid::from_u128(65004))
            .await
            .unwrap_err(),
        Failure("public_job_url_identity_ambiguous")
    );
    assert_eq!(public_intake_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_intake_changed_employer_is_held_without_altering_retained_application_or_finding() {
    let mut c = public_intake_fixture().await;
    public_intake_seed(&mut c, 65005).await;
    let at = public_intake_time(&mut c).await;
    let mut job = public_intake_job(at);
    job["company_name"] = json!("Conflicting Fictional Employer");
    public_intake_observation(&mut c, 65006, public_intake_input(), vec![job], at).await;
    let before = public_intake_snapshot(&mut c).await;
    assert_eq!(
        public_intake::ingest_retained(&mut c, &public_job_settings(), Uuid::from_u128(65006))
            .await
            .unwrap_err(),
        Failure("public_job_company_identity_conflict")
    );
    assert_eq!(public_intake_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_intake_numeric_expectations_use_actual_column_scale_and_same_primary_range_can_be_removed()
 {
    let mut c = public_intake_fixture().await;
    let at = public_intake_time(&mut c).await;
    let mut job = public_intake_job(at);
    job["salary_min"] = json!(1.005);
    job["salary_currency"] = json!("USD");
    job["salary_period"] = json!("hour");
    job["experience_min_years"] = json!(0);
    job["experience_max_years"] = json!(2);
    public_intake_observation(&mut c, 65007, public_intake_input(), vec![job], at).await;
    let first =
        public_intake::ingest_retained(&mut c, &public_job_settings(), Uuid::from_u128(65007))
            .await
            .unwrap();
    let id = first["job_ids"][0]
        .as_str()
        .unwrap()
        .parse::<Uuid>()
        .unwrap();
    assert_eq!(
        sqlx::query_scalar::<_, String>("SELECT salary_min::text FROM jobs WHERE id=$1")
            .bind(id)
            .fetch_one(&mut c)
            .await
            .unwrap(),
        "1.01"
    );
    let at = public_intake_time(&mut c).await;
    public_intake_observation(
        &mut c,
        65008,
        public_intake_input(),
        vec![public_intake_job(at)],
        at,
    )
    .await;
    public_intake::ingest_retained(&mut c, &public_job_settings(), Uuid::from_u128(65008))
        .await
        .unwrap();
    let metadata: Value = sqlx::query_scalar("SELECT discovery_metadata FROM jobs WHERE id=$1")
        .bind(id)
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert!(metadata["experience_min_years"].is_null());
    assert!(metadata["experience_max_years"].is_null());
    assert_eq!(metadata["salary_min"], 1.005);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_intake_failed_observation_ack_rolls_back_new_job_company_and_receipt_then_local_retry_uses_same_finding()
 {
    let mut c = public_intake_fixture().await;
    let at = public_intake_time(&mut c).await;
    public_intake_observation(
        &mut c,
        65009,
        public_intake_input(),
        vec![public_intake_job(at)],
        at,
    )
    .await;
    sqlx::raw_sql("CREATE FUNCTION fixture_public_intake_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NULL; END $$;CREATE TRIGGER fixture_public_intake_drop BEFORE INSERT ON job_source_observations FOR EACH ROW EXECUTE FUNCTION fixture_public_intake_drop()").execute(&mut c).await.unwrap();
    let before = public_intake_snapshot(&mut c).await;
    assert_eq!(
        public_intake::ingest_retained(&mut c, &public_job_settings(), Uuid::from_u128(65009))
            .await
            .unwrap_err(),
        Failure("public_job_intake_write_ack_failed")
    );
    assert_eq!(public_intake_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP TRIGGER fixture_public_intake_drop ON job_source_observations;DROP FUNCTION fixture_public_intake_drop()").execute(&mut c).await.unwrap();
    assert_eq!(
        public_intake::ingest_retained(&mut c, &public_job_settings(), Uuid::from_u128(65009))
            .await
            .unwrap()["counts"]["inserted"],
        1
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_intake_late_receipt_trigger_cannot_rewrite_a_previously_acknowledged_job() {
    let mut c = public_intake_fixture().await;
    let at = public_intake_time(&mut c).await;
    public_intake_observation(
        &mut c,
        65010,
        public_intake_input(),
        vec![public_intake_job(at)],
        at,
    )
    .await;
    sqlx::raw_sql("CREATE FUNCTION fixture_public_intake_late() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'public_ingest:') THEN UPDATE jobs SET status='applied'; END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_public_intake_late AFTER INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_public_intake_late()").execute(&mut c).await.unwrap();
    let before = public_intake_snapshot(&mut c).await;
    assert_eq!(
        public_intake::ingest_retained(&mut c, &public_job_settings(), Uuid::from_u128(65010))
            .await
            .unwrap_err(),
        Failure("public_job_intake_write_ack_failed")
    );
    assert_eq!(public_intake_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP TRIGGER fixture_public_intake_late ON owner_preferences;DROP FUNCTION fixture_public_intake_late()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_intake_changed_profile_and_source_context_hold_local_work_before_facts_are_written()
{
    let mut c = public_intake_fixture().await;
    let at = public_intake_time(&mut c).await;
    let mut input = public_intake_input();
    input["use_profile"] = json!(true);
    public_intake_observation(&mut c, 65011, input, vec![public_intake_job(at)], at).await;
    sqlx::query("UPDATE candidate_profiles SET version=version+1")
        .execute(&mut c)
        .await
        .unwrap();
    let before = public_intake_snapshot(&mut c).await;
    assert_eq!(
        public_intake::ingest_retained(&mut c, &public_job_settings(), Uuid::from_u128(65011))
            .await
            .unwrap_err(),
        Failure("public_job_intake_profile_changed")
    );
    assert_eq!(public_intake_snapshot(&mut c).await, before);
    let changed =
        automated_apply_agents::source_registry::Settings::from_values(&BTreeMap::from([(
            "GREENHOUSE_BOARDS".into(),
            json!({"fictional":"Changed Employer"}).to_string(),
        )]))
        .unwrap();
    assert_eq!(
        public_intake::ingest_retained(&mut c, &changed, Uuid::from_u128(65011))
            .await
            .unwrap_err(),
        Failure("public_job_intake_configuration_changed")
    );
    assert_eq!(public_intake_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_intake_expired_or_future_finding_does_not_write_facts_or_refresh_source_admission()
{
    for (n, offset) in [(65012, -25 * 3600), (65013, 60)] {
        let mut c = public_intake_fixture().await;
        let at = public_intake_time(&mut c).await + chrono::Duration::seconds(offset);
        public_intake_observation(
            &mut c,
            n,
            public_intake_input(),
            vec![public_intake_job(at)],
            at,
        )
        .await;
        let before = public_intake_snapshot(&mut c).await;
        assert_eq!(
            public_intake::ingest_retained(&mut c, &public_job_settings(), Uuid::from_u128(n))
                .await
                .unwrap_err(),
            Failure("public_job_intake_finding_expired")
        );
        assert_eq!(public_intake_snapshot(&mut c).await, before);
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_intake_older_observation_preserves_newer_source_provenance_and_primary_experience()
{
    let mut c = public_intake_fixture().await;
    let id = public_intake_seed(&mut c, 65014).await;
    sqlx::query("UPDATE jobs SET last_observed_at=clock_timestamp()+interval '1 hour',discovery_metadata=discovery_metadata||'{\"experience_min_years\":5,\"experience_max_years\":7}'::jsonb WHERE id=$1").bind(id).execute(&mut c).await.unwrap();
    sqlx::query("UPDATE job_source_observations SET last_observed_at=clock_timestamp()+interval '1 hour',provenance='{\"retained_newer\":true}' WHERE job_id=$1").bind(id).execute(&mut c).await.unwrap();
    let prior: Value =
        sqlx::query_scalar("SELECT to_jsonb(o) FROM job_source_observations o WHERE job_id=$1")
            .bind(id)
            .fetch_one(&mut c)
            .await
            .unwrap();
    let at = public_intake_time(&mut c).await;
    public_intake_observation(
        &mut c,
        65015,
        public_intake_input(),
        vec![public_intake_job(at)],
        at,
    )
    .await;
    public_intake::ingest_retained(&mut c, &public_job_settings(), Uuid::from_u128(65015))
        .await
        .unwrap();
    assert_eq!(
        sqlx::query_scalar::<_, Value>(
            "SELECT to_jsonb(o) FROM job_source_observations o WHERE job_id=$1"
        )
        .bind(id)
        .fetch_one(&mut c)
        .await
        .unwrap(),
        prior
    );
    assert_eq!(
        sqlx::query_scalar::<_, Value>("SELECT discovery_metadata FROM jobs WHERE id=$1")
            .bind(id)
            .fetch_one(&mut c)
            .await
            .unwrap()["experience_min_years"],
        5
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_intake_explicit_filter_excludes_before_identity_work_but_profile_expansion_is_not_an_explicit_filter()
 {
    let mut c = public_intake_fixture().await;
    let at = public_intake_time(&mut c).await;
    let mut input = public_intake_input();
    input["query"]["keywords"] = json!(["Nonmatching Unrelated Keyword"]);
    public_intake_observation(&mut c, 65016, input, vec![public_intake_job(at)], at).await;
    let result =
        public_intake::ingest_retained(&mut c, &public_job_settings(), Uuid::from_u128(65016))
            .await
            .unwrap();
    assert_eq!(result["counts"]["skipped"], 1);
    assert_eq!(result["job_ids"], json!([]));
    assert_eq!(result["exclusions"][0]["code"], "explicit_keyword_mismatch");
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM companies")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    sqlx::query("UPDATE candidate_profiles SET preferences=jsonb_set(preferences::jsonb,'{target_titles}','[\"Nonmatching Unrelated Keyword\"]')").execute(&mut c).await.unwrap();
    let mut input = public_intake_input();
    input["use_profile"] = json!(true);
    let at = public_intake_time(&mut c).await;
    public_intake_observation(&mut c, 65017, input, vec![public_intake_job(at)], at).await;
    assert_eq!(
        public_intake::ingest_retained(&mut c, &public_job_settings(), Uuid::from_u128(65017))
            .await
            .unwrap()["counts"]["inserted"],
        1
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_intake_bounded_complete_inventory_refuses_truncation_and_saved_receipt_projection_drops_extra_fields()
 {
    let mut c = public_intake_fixture().await;
    public_intake_seed(&mut c, 65018).await;
    let key = format!("public_ingest:{}", Uuid::from_u128(65018).simple());
    let mut saved: Value = sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(&key)
        .fetch_one(&mut c)
        .await
        .unwrap();
    saved["receipt"]["private_extra"] = json!("PRIVATE_LOCAL_RECEIPT_CANARY");
    saved["receipt_hash"] = json!(automated_apply_agents::python_json::digest(
        &saved["receipt"]
    ));
    sqlx::query("UPDATE owner_preferences SET value=$2 WHERE key=$1")
        .bind(&key)
        .bind(saved)
        .execute(&mut c)
        .await
        .unwrap();
    assert!(
        !public_intake::read(&mut c, Uuid::from_u128(65018))
            .await
            .unwrap()
            .unwrap()
            .to_string()
            .contains("CANARY")
    );
    sqlx::query("INSERT INTO jobs(id,title,job_url,source_platform) SELECT gen_random_uuid(),'Unrelated legacy role','https://example.com/job/'||n,'manual' FROM generate_series(1,10000) n").execute(&mut c).await.unwrap();
    let at = public_intake_time(&mut c).await;
    let mut job = public_intake_job(at);
    job["source_job_id"] = json!("12346");
    job["original_url"] = json!("https://boards.greenhouse.io/fictional/jobs/12346");
    job["canonical_url"] = Value::Null;
    job["application_url"] = job["original_url"].clone();
    public_intake_observation(&mut c, 65019, public_intake_input(), vec![job], at).await;
    let before = public_intake_snapshot(&mut c).await;
    assert_eq!(
        public_intake::ingest_retained(&mut c, &public_job_settings(), Uuid::from_u128(65019))
            .await
            .unwrap_err(),
        Failure("public_job_legacy_identity_inventory_limit")
    );
    assert_eq!(public_intake_snapshot(&mut c).await, before);
}
