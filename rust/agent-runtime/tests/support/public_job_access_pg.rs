// Deferred original public batch admission fixtures. No HTTP/client/tool is involved.
use automated_apply_agents::job_sources::{
    access as public_job_access, plan::Source as PublicJobSource,
};
async fn public_job_access_fixture() -> PgConnection {
    let mut c = apify_metadata_fixture().await;
    sqlx::query("DELETE FROM owner_preferences WHERE starts_with(key,'public_jobs:')")
        .execute(&mut c)
        .await
        .unwrap();
    c
}
fn public_job_settings() -> automated_apply_agents::source_registry::Settings {
    automated_apply_agents::source_registry::Settings::from_values(&BTreeMap::from([(
        "GREENHOUSE_BOARDS".into(),
        json!({"fictional":"Fictional Public Employer"}).to_string(),
    )]))
    .unwrap()
}
fn public_job_batch_key(n: u128) -> String {
    format!("public_jobs:{}", Uuid::from_u128(n).simple())
}
async fn public_job_access_snapshot(c: &mut PgConnection) -> Value {
    sqlx::query_scalar("SELECT jsonb_build_object('journals',(SELECT jsonb_agg(to_jsonb(p) ORDER BY key) FROM owner_preferences p WHERE starts_with(key,'public_jobs:')),'windows',(SELECT jsonb_agg(to_jsonb(w) ORDER BY provider) FROM provider_access_windows w),'owner',(SELECT value FROM owner_preferences WHERE key='agent_conversation:primary'))").fetch_one(c).await.unwrap()
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_job_original_batch_binds_snapshot_and_replay_never_renews_window_or_invocation() {
    let mut c = public_job_access_fixture().await;
    let settings = public_job_settings();
    let id = Uuid::from_u128(61001);
    let before: Value = sqlx::query_scalar(
        "SELECT value FROM owner_preferences WHERE key='agent_conversation:primary'",
    )
    .fetch_one(&mut c)
    .await
    .unwrap();
    let original = public_job_access::admit(
        &mut c,
        &settings,
        PublicJobSource::Greenhouse,
        json!({"keywords":["Rust"]}),
        id,
    )
    .await
    .unwrap();
    match original {
        public_job_access::Admission::Original(c) => assert_eq!(c.request_id(), id),
        _ => panic!("original grant expected"),
    }
    let saved = public_job_access_snapshot(&mut c).await;
    assert_eq!(saved["owner"], before);
    let read = public_job_access::read(&mut c, id).await.unwrap();
    assert_eq!(read["status"], "pending");
    assert_eq!(read["batch_admissions"], 1);
    assert_eq!(read["replay_authorized"], false);
    assert_eq!(read["application_dispatch"], false);
    assert_eq!(read["writes_to_job_queue"], 0);
    assert!(read["provider_http_calls"].is_null());
    assert!(read.get("invocation_id").is_none());
    assert!(read.get("configuration_hash").is_none());
    let replay = public_job_access::admit(
        &mut c,
        &settings,
        PublicJobSource::Greenhouse,
        json!({"keywords":["Rust"]}),
        id,
    )
    .await
    .unwrap();
    match replay {
        public_job_access::Admission::Retained(v) => assert_eq!(v, read),
        _ => panic!("replay cannot obtain grant"),
    }
    assert_eq!(public_job_access_snapshot(&mut c).await, saved);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_job_same_uuid_changed_query_or_source_conflicts_without_second_admission() {
    let mut c = public_job_access_fixture().await;
    let settings = public_job_settings();
    let id = Uuid::from_u128(61002);
    public_job_access::admit(&mut c, &settings, PublicJobSource::Remotive, json!({}), id)
        .await
        .unwrap();
    let before = public_job_access_snapshot(&mut c).await;
    for (source, input) in [
        (PublicJobSource::Remotive, json!({"page":2})),
        (PublicJobSource::Arbeitnow, json!({})),
    ] {
        assert_eq!(
            public_job_access::admit(&mut c, &settings, source, input, id)
                .await
                .err()
                .unwrap(),
            Failure("public_job_request_conflict")
        );
    }
    assert_eq!(public_job_access_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_job_saved_request_remains_readable_after_board_configuration_is_removed() {
    let mut c = public_job_access_fixture().await;
    let id = Uuid::from_u128(61003);
    public_job_access::admit(
        &mut c,
        &public_job_settings(),
        PublicJobSource::Greenhouse,
        json!({}),
        id,
    )
    .await
    .unwrap();
    let empty =
        automated_apply_agents::source_registry::Settings::from_values(&BTreeMap::new()).unwrap();
    let before = public_job_access_snapshot(&mut c).await;
    let replay =
        public_job_access::admit(&mut c, &empty, PublicJobSource::Greenhouse, json!({}), id)
            .await
            .unwrap();
    assert!(matches!(replay, public_job_access::Admission::Retained(_)));
    assert_eq!(public_job_access_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_job_fresh_uuid_cannot_bypass_shared_provider_window_and_missing_configuration_does_not_consume_one()
 {
    let mut c = public_job_access_fixture().await;
    let settings = public_job_settings();
    public_job_access::admit(
        &mut c,
        &settings,
        PublicJobSource::Remotive,
        json!({}),
        Uuid::from_u128(61004),
    )
    .await
    .unwrap();
    let before = public_job_access_snapshot(&mut c).await;
    assert_eq!(
        public_job_access::admit(
            &mut c,
            &settings,
            PublicJobSource::Remotive,
            json!({}),
            Uuid::from_u128(61005)
        )
        .await
        .err()
        .unwrap(),
        Failure("public_job_source_rate_limited")
    );
    let empty =
        automated_apply_agents::source_registry::Settings::from_values(&BTreeMap::new()).unwrap();
    assert_eq!(
        public_job_access::admit(
            &mut c,
            &empty,
            PublicJobSource::Greenhouse,
            json!({}),
            Uuid::from_u128(61006)
        )
        .await
        .err()
        .unwrap(),
        Failure("public_job_boards_not_configured")
    );
    assert_eq!(public_job_access_snapshot(&mut c).await, before);
    let seconds:f64=sqlx::query_scalar("SELECT extract(epoch FROM (next_allowed_at-clock_timestamp()))::double precision FROM provider_access_windows WHERE provider='remotive'").fetch_one(&mut c).await.unwrap();
    assert!((21590.0..=21600.0).contains(&seconds));
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_job_lost_invocation_expiry_is_read_only_unknown_without_resetting_original_pace() {
    let mut c = public_job_access_fixture().await;
    let id = Uuid::from_u128(61007);
    public_job_access::admit(
        &mut c,
        &public_job_settings(),
        PublicJobSource::Remotive,
        json!({}),
        id,
    )
    .await
    .unwrap();
    let mut journal: Value = sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(public_job_batch_key(61007))
        .fetch_one(&mut c)
        .await
        .unwrap();
    let at: chrono::DateTime<chrono::Utc> =
        sqlx::query_scalar("SELECT clock_timestamp()-interval '80 seconds'")
            .fetch_one(&mut c)
            .await
            .unwrap();
    journal["started_at"] = json!(at.to_rfc3339());
    journal["expires_at"] = json!((at + chrono::Duration::seconds(75)).to_rfc3339());
    journal["access_window_until"] = json!((at + chrono::Duration::seconds(21600)).to_rfc3339());
    sqlx::query("UPDATE owner_preferences SET value=$2 WHERE key=$1")
        .bind(public_job_batch_key(61007))
        .bind(journal)
        .execute(&mut c)
        .await
        .unwrap();
    let before = public_job_access_snapshot(&mut c).await;
    assert_eq!(
        public_job_access::read(&mut c, id).await.unwrap()["status"],
        "outcome_unknown"
    );
    assert_eq!(public_job_access_snapshot(&mut c).await, before);
    assert!(matches!(
        public_job_access::admit(
            &mut c,
            &public_job_settings(),
            PublicJobSource::Remotive,
            json!({}),
            id
        )
        .await
        .unwrap(),
        public_job_access::Admission::Retained(_)
    ));
    assert_eq!(public_job_access_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_job_original_journal_trigger_cannot_mutate_window_after_the_admission_ack() {
    let mut c = public_job_access_fixture().await;
    sqlx::raw_sql("CREATE FUNCTION fixture_public_job_pace() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'public_jobs:') THEN UPDATE provider_access_windows SET next_allowed_at=next_allowed_at+interval '1 second';END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_public_job_pace AFTER INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_public_job_pace()").execute(&mut c).await.unwrap();
    assert_eq!(
        public_job_access::admit(
            &mut c,
            &public_job_settings(),
            PublicJobSource::Remotive,
            json!({}),
            Uuid::from_u128(61008)
        )
        .await
        .err()
        .unwrap(),
        Failure("public_job_write_ack_failed")
    );
    let snapshot = public_job_access_snapshot(&mut c).await;
    assert!(snapshot["journals"].is_null());
    assert!(snapshot["windows"].is_null());
    sqlx::raw_sql("DROP FUNCTION fixture_public_job_pace() CASCADE")
        .execute(&mut c)
        .await
        .unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_job_journal_ack_failure_rolls_back_the_coupled_window_and_never_returns_a_grant() {
    let mut c = public_job_access_fixture().await;
    sqlx::raw_sql("CREATE FUNCTION fixture_public_job_journal() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'public_jobs:') THEN NEW.value=jsonb_set(NEW.value,'{state}','\"tampered\"');END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_public_job_journal BEFORE INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_public_job_journal()").execute(&mut c).await.unwrap();
    assert_eq!(
        public_job_access::admit(
            &mut c,
            &public_job_settings(),
            PublicJobSource::Remotive,
            json!({}),
            Uuid::from_u128(61009)
        )
        .await
        .err()
        .unwrap(),
        Failure("public_job_write_ack_failed")
    );
    let snapshot = public_job_access_snapshot(&mut c).await;
    assert!(snapshot["journals"].is_null());
    assert!(snapshot["windows"].is_null());
    sqlx::raw_sql("DROP FUNCTION fixture_public_job_journal() CASCADE")
        .execute(&mut c)
        .await
        .unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn public_job_invalid_saved_context_and_large_rows_fail_closed_without_rewriting_history() {
    let mut c = public_job_access_fixture().await;
    let id = Uuid::from_u128(61010);
    public_job_access::admit(
        &mut c,
        &public_job_settings(),
        PublicJobSource::Arbeitnow,
        json!({}),
        id,
    )
    .await
    .unwrap();
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{input_hash}','\"changed\"') WHERE key=$1").bind(public_job_batch_key(61010)).execute(&mut c).await.unwrap();
    let before = public_job_access_snapshot(&mut c).await;
    assert_eq!(
        public_job_access::read(&mut c, id).await,
        Err(Failure("invalid_public_job_batch"))
    );
    assert_eq!(public_job_access_snapshot(&mut c).await, before);
    sqlx::query("UPDATE owner_preferences SET value=$2 WHERE key=$1")
        .bind(public_job_batch_key(61010))
        .bind(json!({"private":"x".repeat(9437185)}))
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        public_job_access::read(&mut c, id).await,
        Err(Failure("public_job_saved_batch_limit"))
    );
    assert_eq!(
        public_job_access::read(&mut c, Uuid::from_u128(61999)).await,
        Err(Failure("public_job_request_not_found"))
    );
}
