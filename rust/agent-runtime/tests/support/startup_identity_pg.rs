//! Deferred canonical company import, replay and atomic rollback fixtures; fictional data only.
use automated_apply_agents::startup_catalog::identity as startup_identity;
async fn startup_identity_fixture() -> PgConnection {
    let (mut c, _, _) = companies_fixture().await;
    sqlx::raw_sql("ALTER TABLE companies ADD COLUMN IF NOT EXISTS linkedin_url text,ADD COLUMN IF NOT EXISTS email_pattern varchar(100),ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT clock_timestamp(),ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT clock_timestamp();CREATE UNIQUE INDEX IF NOT EXISTS fixture_startup_observation_identity ON company_source_observations(source,identity_key,content_hash)").execute(&mut c).await.unwrap();
    c
}
fn startup_observation(domain: Option<&str>, source_id: Option<&str>) -> Value {
    json!({"name":"Fictional Identity Employer","domain":domain,"source":"manual","source_company_id":source_id,"source_url":"https://identity-fixture.example/about","permission_evidence_url":"https://identity-fixture.example/terms","observed_at":"2026-11-15T12:00:00Z","employee_count":12})
}
async fn startup_ingest(c: &mut PgConnection, v: Value) -> Result<Value> {
    startup_identity::ingest(c, v, None).await
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_identity_import_creates_exact_company_and_immutable_observation_then_replays_without_refresh()
 {
    let mut c = startup_identity_fixture().await;
    let input = startup_observation(Some("identity-fixture.example"), Some("fictional-source-1"));
    let first = startup_ingest(&mut c, input.clone()).await.unwrap();
    assert_eq!(first["company_created"], true);
    assert_eq!(first["created"], true);
    let before = companies_snapshot(&mut c).await;
    let second = startup_ingest(&mut c, input).await.unwrap();
    assert_eq!(second["company_id"], first["company_id"]);
    assert_eq!(second["observation_id"], first["observation_id"]);
    assert_eq!(second["created"], false);
    assert_eq!(companies_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_identity_domain_reuses_the_saved_company_but_equal_display_names_never_merge() {
    let mut c = startup_identity_fixture().await;
    let first = startup_ingest(
        &mut c,
        startup_observation(Some("identity-one.example"), None),
    )
    .await
    .unwrap();
    let mut renamed = startup_observation(Some("identity-one.example"), None);
    renamed["name"] = json!("Different observed display name");
    renamed["observed_at"] = json!("2026-11-16T12:00:00Z");
    let same = startup_ingest(&mut c, renamed).await.unwrap();
    assert_eq!(same["company_id"], first["company_id"]);
    let other = startup_ingest(
        &mut c,
        startup_observation(Some("identity-two.example"), None),
    )
    .await
    .unwrap();
    assert_ne!(other["company_id"], first["company_id"]);
    let id = first["company_id"]
        .as_str()
        .unwrap()
        .parse::<Uuid>()
        .unwrap();
    assert_eq!(
        sqlx::query_scalar::<_, String>("SELECT name FROM companies WHERE id=$1")
            .bind(id)
            .fetch_one(&mut c)
            .await
            .unwrap(),
        "Fictional Identity Employer"
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_identity_source_domain_conflicts_roll_back_new_company_or_observation_work() {
    let mut c = startup_identity_fixture().await;
    startup_ingest(
        &mut c,
        startup_observation(Some("identity-one.example"), Some("stable-source")),
    )
    .await
    .unwrap();
    startup_ingest(
        &mut c,
        startup_observation(Some("identity-two.example"), Some("other-source")),
    )
    .await
    .unwrap();
    let before = companies_snapshot(&mut c).await;
    let mut conflict = startup_observation(Some("identity-two.example"), Some("stable-source"));
    conflict["observed_at"] = json!("2026-11-16T12:00:00Z");
    assert_eq!(
        startup_ingest(&mut c, conflict).await.unwrap_err(),
        Failure("startup_source_company_domain_conflict")
    );
    assert_eq!(companies_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_identity_url_only_identity_requires_same_normalized_name_and_no_inferred_domain() {
    let mut c = startup_identity_fixture().await;
    let first = startup_ingest(&mut c, startup_observation(None, None))
        .await
        .unwrap();
    let mut changed = startup_observation(None, None);
    changed["name"] = json!("Unrelated employer");
    assert_eq!(
        startup_ingest(&mut c, changed).await.unwrap_err(),
        Failure("startup_unqualified_company_url_conflict")
    );
    let mut same = startup_observation(None, None);
    same["name"] = json!("fictional   identity employer");
    let second = startup_ingest(&mut c, same).await.unwrap();
    assert_eq!(second["company_id"], first["company_id"]);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_identity_can_fill_only_a_missing_domain_and_refuses_review_flagged_associations() {
    let mut c = startup_identity_fixture().await;
    let first = startup_ingest(
        &mut c,
        startup_observation(None, Some("domain-fill-source")),
    )
    .await
    .unwrap();
    let id = first["company_id"]
        .as_str()
        .unwrap()
        .parse::<Uuid>()
        .unwrap();
    sqlx::query("UPDATE companies SET metadata='{\"identity_review_required\":true,\"private\":\"PRIVATE_COMPANY_FACT_CANARY\"}' WHERE id=$1").bind(id).execute(&mut c).await.unwrap();
    let input = startup_observation(Some("new-identity.example"), Some("domain-fill-source"));
    assert_eq!(
        startup_ingest(&mut c, input.clone()).await.unwrap_err(),
        Failure("startup_company_identity_review_required")
    );
    sqlx::query("UPDATE companies SET metadata=metadata-'identity_review_required' WHERE id=$1")
        .bind(id)
        .execute(&mut c)
        .await
        .unwrap();
    let result = startup_ingest(&mut c, input).await.unwrap();
    assert_eq!(result["company_id"], first["company_id"]);
    assert!(!result.to_string().contains("PRIVATE_COMPANY_FACT_CANARY"));
    let row: Value = sqlx::query_scalar("SELECT to_jsonb(c) FROM companies c WHERE id=$1")
        .bind(id)
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(row["metadata"]["private"], "PRIVATE_COMPANY_FACT_CANARY");
    assert_eq!(row["domain"], "new-identity.example");
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_identity_ambiguous_source_mapping_fails_closed_without_choosing_the_first_employer()
 {
    let mut c = startup_identity_fixture().await;
    let first = startup_ingest(
        &mut c,
        startup_observation(Some("identity-one.example"), Some("ambiguous-source")),
    )
    .await
    .unwrap();
    let second = startup_ingest(
        &mut c,
        startup_observation(Some("identity-two.example"), Some("second-source")),
    )
    .await
    .unwrap();
    let id = second["company_id"]
        .as_str()
        .unwrap()
        .parse::<Uuid>()
        .unwrap();
    sqlx::query("INSERT INTO company_source_observations(id,company_id,source,identity_key,content_hash,source_url,observed_at,attributes,verification_status) SELECT $1,$2,source,identity_key,'different_hash',source_url,observed_at,attributes,verification_status FROM company_source_observations WHERE id=$3").bind(Uuid::from_u128(995001)).bind(id).bind(first["observation_id"].as_str().unwrap().parse::<Uuid>().unwrap()).execute(&mut c).await.unwrap();
    let before = companies_snapshot(&mut c).await;
    assert_eq!(
        startup_ingest(
            &mut c,
            startup_observation(Some("identity-one.example"), Some("ambiguous-source"))
        )
        .await
        .unwrap_err(),
        Failure("startup_source_identity_ambiguous")
    );
    assert_eq!(companies_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_identity_company_and_observation_ack_corruption_roll_back_the_entire_import() {
    let mut c = startup_identity_fixture().await;
    let before = companies_snapshot(&mut c).await;
    for (table, body) in [
        ("companies", "RETURN NULL;"),
        ("companies", "NEW.email_pattern='unrequested';RETURN NEW;"),
        ("company_source_observations", "RETURN NULL;"),
        (
            "company_source_observations",
            "NEW.observed_at=NEW.observed_at+interval '1 day';RETURN NEW;",
        ),
    ] {
        let sql = format!(
            "CREATE FUNCTION fixture_company_identity_corrupt() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {body} END $$;CREATE TRIGGER fixture_company_identity_corrupt BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION fixture_company_identity_corrupt()"
        );
        sqlx::raw_sql(sqlx::AssertSqlSafe(sql))
            .execute(&mut c)
            .await
            .unwrap();
        assert_eq!(
            startup_ingest(
                &mut c,
                startup_observation(Some("identity-corrupt.example"), Some("corrupt-source"))
            )
            .await
            .unwrap_err(),
            Failure("startup_identity_write_ack_failed")
        );
        assert_eq!(companies_snapshot(&mut c).await, before);
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("DROP TRIGGER fixture_company_identity_corrupt ON {table};DROP FUNCTION fixture_company_identity_corrupt()"))).execute(&mut c).await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_identity_after_trigger_changes_and_corrupt_replay_timestamps_are_detected() {
    let mut c = startup_identity_fixture().await;
    let before = companies_snapshot(&mut c).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_company_observation_after() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF pg_trigger_depth()=1 THEN UPDATE company_source_observations SET observed_at=observed_at+interval '1 day' WHERE id=NEW.id;END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_company_observation_after AFTER INSERT ON company_source_observations FOR EACH ROW EXECUTE FUNCTION fixture_company_observation_after()").execute(&mut c).await.unwrap();
    let input = startup_observation(Some("identity-after.example"), Some("after-source"));
    assert_eq!(
        startup_ingest(&mut c, input.clone()).await.unwrap_err(),
        Failure("startup_identity_write_ack_failed")
    );
    assert_eq!(companies_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP TRIGGER fixture_company_observation_after ON company_source_observations;DROP FUNCTION fixture_company_observation_after()").execute(&mut c).await.unwrap();
    let first = startup_ingest(&mut c, input.clone()).await.unwrap();
    sqlx::query("UPDATE company_source_observations SET observed_at=observed_at+interval '1 day' WHERE id=$1").bind(first["observation_id"].as_str().unwrap().parse::<Uuid>().unwrap()).execute(&mut c).await.unwrap();
    assert_eq!(
        startup_ingest(&mut c, input).await.unwrap_err(),
        Failure("startup_company_observation_replay_conflict")
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_identity_concurrent_duplicate_imports_preserve_one_company_and_one_snapshot_without_refresh()
 {
    let mut c = startup_identity_fixture().await;
    let mut other = connection().await;
    let input = startup_observation(
        Some("identity-concurrent.example"),
        Some("concurrent-source"),
    );
    let (a, b) = tokio::join!(
        startup_ingest(&mut c, input.clone()),
        startup_ingest(&mut other, input)
    );
    assert!(a.is_ok() || b.is_ok());
    if let (Ok(a), Ok(b)) = (a, b) {
        assert_eq!(a["company_id"], b["company_id"]);
        assert_eq!(a["observation_id"], b["observation_id"]);
    }
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM companies WHERE domain='identity-concurrent.example'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        1
    );
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM company_source_observations WHERE source_url='https://identity-fixture.example/about'").fetch_one(&mut c).await.unwrap(),1);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_identity_invalid_time_or_reference_run_rolls_back_all_candidate_company_work() {
    let mut c = startup_identity_fixture().await;
    let before = companies_snapshot(&mut c).await;
    let mut input = startup_observation(Some("identity-invalid.example"), Some("invalid-source"));
    input["observed_at"] = json!("2026-11-15T12:00:00");
    assert_eq!(
        startup_ingest(&mut c, input).await.unwrap_err(),
        Failure("invalid_research_contract")
    );
    assert_eq!(companies_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP TABLE IF EXISTS discovery_runs CASCADE;CREATE TABLE discovery_runs(id uuid PRIMARY KEY,source text)").execute(&mut c).await.unwrap();
    assert_eq!(
        startup_identity::ingest(
            &mut c,
            startup_observation(Some("identity-invalid.example"), Some("invalid-source")),
            Some(Uuid::nil())
        )
        .await
        .unwrap_err(),
        Failure("startup_catalog_run_not_found")
    );
    assert_eq!(companies_snapshot(&mut c).await, before);
}
