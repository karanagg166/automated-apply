// Deferred complete paid-to-local flow and context/ACK/recovery, loopback fixtures only.
use automated_apply_agents::people_research::completion as people_search_completion;
async fn people_search_complete(
    c: &mut PgConnection,
    input: Value,
    id: u128,
    values: &BTreeMap<String, String>,
) -> Result<Value> {
    let settings = PeopleSearchSettings::from_values(values).unwrap();
    let client = PeopleSearchClient::from_values(values, true).unwrap();
    let contacts = contact_settings();
    PeopleSearchService {
        settings: &settings,
        client: client.as_ref(),
        contacts: &contacts,
    }
    .run(c, input, Uuid::from_u128(id))
    .await
}
async fn people_search_apply(
    c: &mut PgConnection,
    id: u128,
    values: &BTreeMap<String, String>,
) -> Result<Value> {
    people_search_completion::apply(
        c,
        Uuid::from_u128(id),
        &PeopleSearchSettings::from_values(values).unwrap(),
        &contact_settings(),
    )
    .await
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_complete_official_flow_persists_public_search_provenance_and_unconfirmed_identity_once()
 {
    let mut c = people_search_fixture().await;
    let (values, state, stop, task) = people_search_http("official").await;
    let result = people_search_complete(&mut c, people_search_input(), 40001, &values)
        .await
        .unwrap();
    assert_eq!(result["status"], "success");
    assert_eq!(result["persistence_status"], "imported");
    assert_eq!(result["recorded_state"], "completed");
    assert_eq!(
        result["people"][0]["identity_independently_confirmed"],
        false
    );
    assert_eq!(
        result["people"][0]["verification_status"],
        "requires_review"
    );
    people_search_no_private(&result);
    let id: Uuid = result["people"][0]["contact_id"]
        .as_str()
        .unwrap()
        .parse()
        .unwrap();
    let row = contact_identity_row(&mut c, id).await;
    assert_eq!(row["enrichment_source"], "public_search");
    assert_eq!(row["metadata"]["identity_review_required"], true);
    assert_eq!(row["metadata"]["identity_human_confirmed"], false);
    assert!(row["email"].is_null());
    assert!(row["last_verified_at"].is_null());
    let before = people_ingest_snapshot(&mut c).await;
    assert_eq!(
        people_search_complete(&mut c, people_search_input(), 40001, &values)
            .await
            .unwrap(),
        result
    );
    assert_eq!(
        people_search_runs::retained(&mut c, Uuid::from_u128(40001))
            .await
            .unwrap(),
        result
    );
    assert_eq!(people_ingest_snapshot(&mut c).await, before);
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_complete_public_profile_keeps_original_finding_observation_and_review_requirement()
 {
    let mut c = people_search_fixture().await;
    let (mut values, state, stop, task) = people_search_http("public").await;
    values.insert("LINKEDIN_SEARCH_RETENTION_AUTHORIZED".into(), "true".into());
    let mut input = people_search_input();
    input["research_mode"] = json!("public_profiles");
    people_search_with(&mut c, input.clone(), 40002, &values)
        .await
        .unwrap();
    let at: Value =
        sqlx::query_scalar("SELECT value->'finding_at' FROM owner_preferences WHERE key=$1")
            .bind(format!("people_search:{}", Uuid::from_u128(40002).simple()))
            .fetch_one(&mut c)
            .await
            .unwrap();
    let result = people_search_complete(&mut c, input, 40002, &values)
        .await
        .unwrap();
    assert_eq!(result["people"][0]["source"], "public_search");
    assert_eq!(
        result["people"][0]["verification_status"],
        "source_reported"
    );
    let row:Value=sqlx::query_scalar("SELECT to_jsonb(p) FROM discovered_company_people p WHERE linkedin_url='https://www.linkedin.com/in/fictional-search-professional/'").fetch_one(&mut c).await.unwrap();
    let observed =
        chrono::DateTime::parse_from_rfc3339(row["observed_at"].as_str().unwrap()).unwrap();
    assert_eq!(
        observed,
        chrono::DateTime::parse_from_rfc3339(at.as_str().unwrap()).unwrap()
    );
    let review:bool=sqlx::query_scalar("SELECT (metadata->>'identity_review_required')::boolean FROM contacts WHERE full_name='Fictional Search Professional'").fetch_one(&mut c).await.unwrap();
    assert!(review);
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_current_company_change_holds_saved_finding_without_import_or_new_request() {
    let mut c = people_search_fixture().await;
    let (values, state, stop, task) = people_search_http("official").await;
    people_search_with(&mut c, people_search_input(), 40003, &values)
        .await
        .unwrap();
    sqlx::query("UPDATE companies SET name='Changed Fictional Employer' WHERE domain='contact-fixture.example'").execute(&mut c).await.unwrap();
    let before = people_ingest_snapshot(&mut c).await;
    let held = people_search_apply(&mut c, 40003, &values).await.unwrap();
    assert_eq!(held["status"], "needs_review");
    assert_eq!(held["failure_code"], "public_research_company_changed");
    assert_eq!(held["persistence_status"], "held");
    assert_eq!(people_ingest_snapshot(&mut c).await, before);
    assert_eq!(
        people_search_complete(&mut c, people_search_input(), 40003, &values)
            .await
            .unwrap(),
        held
    );
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_current_configuration_change_holds_original_findings_even_when_client_is_unavailable()
 {
    let mut c = people_search_fixture().await;
    let (mut values, state, stop, task) = people_search_http("official").await;
    people_search_with(&mut c, people_search_input(), 40004, &values)
        .await
        .unwrap();
    values.insert("PEOPLE_SEARCH_ENABLED".into(), "false".into());
    let before = people_ingest_snapshot(&mut c).await;
    let held = people_search_apply(&mut c, 40004, &values).await.unwrap();
    assert_eq!(
        held["failure_code"],
        "public_research_configuration_changed"
    );
    assert_eq!(
        people_search_complete(&mut c, people_search_input(), 40004, &values)
            .await
            .unwrap(),
        held
    );
    assert_eq!(people_ingest_snapshot(&mut c).await, before);
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_stale_retained_finding_is_held_without_refreshing_its_observation_or_charge()
{
    let mut c = people_search_fixture().await;
    let (values, state, stop, task) = people_search_http("official").await;
    people_search_with(&mut c, people_search_input(), 40005, &values)
        .await
        .unwrap();
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{finding_at}',to_jsonb(clock_timestamp()-interval '25 hours')) WHERE key=$1").bind(format!("people_search:{}",Uuid::from_u128(40005).simple())).execute(&mut c).await.unwrap();
    let before = people_ingest_snapshot(&mut c).await;
    let held = people_search_apply(&mut c, 40005, &values).await.unwrap();
    assert_eq!(held["failure_code"], "public_research_finding_expired");
    assert_eq!(people_ingest_snapshot(&mut c).await, before);
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_local_completion_ack_failure_preserves_finding_and_retry_can_finish_without_a_client()
 {
    let mut c = people_search_fixture().await;
    let (values, state, stop, task) = people_search_http("official").await;
    people_search_with(&mut c, people_search_input(), 40006, &values)
        .await
        .unwrap();
    let before = people_ingest_snapshot(&mut c).await;
    let journal_before = people_search_snapshot(&mut c).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_search_complete_fail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'people_search:') AND NEW.value->>'state'='completed' THEN RETURN NULL;END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_search_complete_fail BEFORE UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_search_complete_fail()").execute(&mut c).await.unwrap();
    assert_eq!(
        people_search_apply(&mut c, 40006, &values)
            .await
            .unwrap_err(),
        Failure("public_research_write_ack_failed")
    );
    assert_eq!(people_ingest_snapshot(&mut c).await, before);
    assert_eq!(people_search_snapshot(&mut c).await, journal_before);
    sqlx::raw_sql("DROP TRIGGER fixture_search_complete_fail ON owner_preferences;DROP FUNCTION fixture_search_complete_fail()").execute(&mut c).await.unwrap();
    let settings = PeopleSearchSettings::from_values(&values).unwrap();
    let contacts = contact_settings();
    let result = PeopleSearchService {
        settings: &settings,
        client: None,
        contacts: &contacts,
    }
    .run(&mut c, people_search_input(), Uuid::from_u128(40006))
    .await
    .unwrap();
    assert_eq!(result["recorded_state"], "completed");
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_paid_journal_trigger_cannot_corrupt_the_coupled_local_receipt_after_its_first_ack()
 {
    let mut c = people_search_fixture().await;
    let (values, state, stop, task) = people_search_http("official").await;
    people_search_with(&mut c, people_search_input(), 40007, &values)
        .await
        .unwrap();
    let before = people_ingest_snapshot(&mut c).await;
    let journal_before = people_search_snapshot(&mut c).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_search_receipt_corrupt() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF pg_trigger_depth()=1 AND starts_with(NEW.key,'people_search:') AND NEW.value->>'state'='completed' THEN UPDATE owner_preferences SET value=value||'{\"private_corrupt\":true}'::jsonb WHERE key=replace(NEW.key,'people_search:','people_import:');END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_search_receipt_corrupt AFTER UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_search_receipt_corrupt()").execute(&mut c).await.unwrap();
    assert_eq!(
        people_search_apply(&mut c, 40007, &values)
            .await
            .unwrap_err(),
        Failure("public_research_write_ack_failed")
    );
    assert_eq!(people_ingest_snapshot(&mut c).await, before);
    assert_eq!(people_search_snapshot(&mut c).await, journal_before);
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    sqlx::raw_sql("DROP TRIGGER fixture_search_receipt_corrupt ON owner_preferences;DROP FUNCTION fixture_search_receipt_corrupt()").execute(&mut c).await.unwrap();
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_concurrent_local_completion_keeps_one_saved_result_and_never_reissues_transport()
 {
    let mut c = people_search_fixture().await;
    let (values, state, stop, task) = people_search_http("official").await;
    people_search_with(&mut c, people_search_input(), 40008, &values)
        .await
        .unwrap();
    let mut other = connection().await;
    let (a, b) = tokio::join!(
        people_search_apply(&mut c, 40008, &values),
        people_search_apply(&mut other, 40008, &values)
    );
    let result = a.or(b).unwrap();
    assert_eq!(result["recorded_state"], "completed");
    assert_eq!(
        people_search_runs::retained(&mut c, Uuid::from_u128(40008))
            .await
            .unwrap(),
        result
    );
    let n: i64 = sqlx::query_scalar(
        "SELECT count(*)::bigint FROM contacts WHERE full_name='Fictional Search Professional'",
    )
    .fetch_one(&mut c)
    .await
    .unwrap();
    assert_eq!(n, 1);
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_completed_history_is_selected_read_only_and_excludes_private_nested_result_fields()
 {
    let mut c = people_search_fixture().await;
    let (values, _, stop, task) = people_search_http("official").await;
    people_search_complete(&mut c, people_search_input(), 40009, &values)
        .await
        .unwrap();
    let key = format!("people_search:{}", Uuid::from_u128(40009).simple());
    let mut journal: Value = sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(&key)
        .fetch_one(&mut c)
        .await
        .unwrap();
    journal["result"]["people"][0]["private_vendor"] = json!("PRIVATE_COMPLETED_RESULT_CANARY");
    journal["result_hash"] =
        json!(automated_apply_agents::startup_catalog::identity::content_hash(&journal["result"]));
    sqlx::query("UPDATE owner_preferences SET value=$1 WHERE key=$2")
        .bind(journal)
        .bind(&key)
        .execute(&mut c)
        .await
        .unwrap();
    let before = people_search_snapshot(&mut c).await;
    let result = people_search_runs::retained(&mut c, Uuid::from_u128(40009))
        .await
        .unwrap();
    assert_eq!(result["persistence_status"], "imported");
    assert!(
        !result
            .to_string()
            .contains("PRIVATE_COMPLETED_RESULT_CANARY")
    );
    people_search_no_private(&result);
    assert_eq!(people_search_snapshot(&mut c).await, before);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_valid_empty_result_completes_without_creating_company_people_or_contacts() {
    let mut c = people_search_fixture().await;
    let (values, state, stop, task) = people_search_http("public").await;
    let before = people_ingest_snapshot(&mut c).await;
    let result = people_search_complete(&mut c, people_search_input(), 40010, &values)
        .await
        .unwrap();
    assert_eq!(result["status"], "no_results");
    assert_eq!(result["recorded_state"], "completed");
    assert_eq!(result["people"], json!([]));
    let after = people_ingest_snapshot(&mut c).await;
    for key in ["companies", "people", "contacts", "evidence", "identities"] {
        assert_eq!(before[key], after[key]);
    }
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_missing_company_domain_holds_public_candidates_without_inventing_employer_identity()
 {
    let mut c = people_search_fixture().await;
    let (mut values, state, stop, task) = people_search_http("public").await;
    values.insert("LINKEDIN_SEARCH_RETENTION_AUTHORIZED".into(), "true".into());
    let mut input = people_search_input();
    input["company_domain"] = Value::Null;
    input["research_mode"] = json!("public_profiles");
    let before = people_ingest_snapshot(&mut c).await;
    let held = people_search_complete(&mut c, input, 40011, &values)
        .await
        .unwrap();
    assert_eq!(
        held["failure_code"],
        "public_research_company_domain_required"
    );
    assert_eq!(held["persistence_status"], "held");
    assert_eq!(people_ingest_snapshot(&mut c).await, before);
    assert_eq!(state.calls.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn people_search_owner_controller_manual_import_works_with_disabled_paid_settings_and_no_remote_client()
 {
    let mut c = people_search_fixture().await;
    let settings = PeopleSearchSettings::from_values(&BTreeMap::new()).unwrap();
    let contacts = contact_settings();
    let service = PeopleSearchService {
        settings: &settings,
        client: None,
        contacts: &contacts,
    };
    let result = service
        .run(&mut c, people_manual(), Uuid::from_u128(40012))
        .await
        .unwrap();
    assert_eq!(result["provider_calls"], 0);
    assert_eq!(
        service.read(&mut c, Uuid::from_u128(40012)).await.unwrap(),
        result
    );
    let n: i64 = sqlx::query_scalar("SELECT count(*)::bigint FROM discovery_budget_reservations")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(n, 0);
}
