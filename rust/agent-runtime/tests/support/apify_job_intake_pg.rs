// Deferred actual-schema intake over selected loopback findings; no real account or paid operation.
use automated_apply_agents::apify_jobs::intake as apify_intake;
async fn apify_intake_fixture() -> PgConnection {
    let mut c = apify_job_admission_fixture().await;
    job_intake_tables(&mut c).await;
    c
}
async fn apify_intake_snapshot(c: &mut PgConnection) -> Value {
    let original = apify_job_intent_snapshot(c).await;
    let facts: Value = sqlx::query_scalar("SELECT jsonb_build_object('jobs',(SELECT jsonb_agg(to_jsonb(j) ORDER BY id) FROM jobs j),'companies',(SELECT jsonb_agg(to_jsonb(c) ORDER BY id) FROM companies c),'observations',(SELECT jsonb_agg(to_jsonb(o) ORDER BY id) FROM job_source_observations o),'receipts',(SELECT jsonb_agg(jsonb_build_object('key',key,'value',value) ORDER BY key) FROM owner_preferences WHERE starts_with(key,'apify_intake:')))")
        .fetch_one(&mut *c).await.unwrap();
    json!({"original":original,"facts":facts})
}
async fn apify_intake_journal(c: &mut PgConnection, id: Uuid) -> Value {
    sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(format!("apify_job:{}", id.simple()))
        .fetch_one(c)
        .await
        .unwrap()
}
async fn apify_intake_save_fixture_journal(c: &mut PgConnection, id: Uuid, mut journal: Value) {
    // Fixture corruption/aging only; production does not rewrite original findings.
    journal["finding_hash"] = json!(automated_apply_agents::python_json::digest(
        &journal["finding"]
    ));
    sqlx::query("UPDATE owner_preferences SET value=$2 WHERE key=$1")
        .bind(format!("apify_job:{}", id.simple()))
        .bind(journal)
        .execute(c)
        .await
        .unwrap();
}
async fn apify_intake_finish(
    c: &mut PgConnection,
    values: &BTreeMap<String, String>,
    id: Uuid,
) -> Result<Value> {
    apify_intake::ingest_retained(c, &ApifyJobSettings::from_values(values)?, id).await
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_selected_loopback_finding_ingests_atomically_and_saved_replay_ignores_configuration_and_job_edits()
 {
    let mut c = apify_intake_fixture().await;
    let (v, f, stop, task) = apify_job_http("ok").await;
    let id = Uuid::from_u128(71001);
    apify_transport_acquire(&mut c, &v, 71001).await.unwrap();
    assert!(apify_intake::read(&mut c, id).await.unwrap().is_none());
    let remote = apify_admission::read(&mut c, id).await.unwrap();
    let receipt = apify_intake_finish(&mut c, &v, id).await.unwrap();
    assert_eq!(receipt["counts"]["inserted"], 1);
    assert_eq!(receipt["local_intake_complete"], true);
    assert_eq!(receipt["provider_calls"], 0);
    assert_eq!(receipt["billing_final"], false);
    assert_eq!(receipt["budget_accounting"], "full_cap_retained");
    assert_eq!(receipt["rankings_complete"], false);
    assert_eq!(apify_admission::read(&mut c, id).await.unwrap(), remote);
    assert_eq!(f.calls.lock().await.len(), 5);
    assert!(!receipt.to_string().contains("CANARY"));
    sqlx::query("UPDATE jobs SET status='applied',match_score=99,match_explanation='owner review'")
        .execute(&mut c)
        .await
        .unwrap();
    let before = apify_intake_snapshot(&mut c).await;
    assert_eq!(
        apify_intake_finish(&mut c, &BTreeMap::new(), id)
            .await
            .unwrap(),
        receipt
    );
    assert_eq!(apify_intake::read(&mut c, id).await.unwrap(), Some(receipt));
    assert_eq!(apify_intake_snapshot(&mut c).await, before);
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    assert_eq!(f.calls.lock().await.len(), 5);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_duplicate_canonical_job_preserves_complete_owner_application_row_and_company_facts()
{
    let mut c = apify_intake_fixture().await;
    let (v, f, stop, task) = apify_job_http("ok").await;
    let id = Uuid::from_u128(71002);
    apify_transport_acquire(&mut c, &v, 71002).await.unwrap();
    sqlx::query("INSERT INTO companies(id,name,domain,metadata) VALUES($1,'Fictional Public Employer','known-fixture.example','{\"owner_fact\":true}')").bind(Uuid::from_u128(71901)).execute(&mut c).await.unwrap();
    sqlx::raw_sql("ALTER TABLE jobs ADD COLUMN fixture_owner_notes text;INSERT INTO jobs(company_id,title,job_url,source_platform,status,match_score,match_explanation,fixture_owner_notes,discovery_metadata) SELECT id,'Owner title','https://job-fixture.example/12345','owner','applied',98,'reviewed','PRIVATE_LOCAL_NOTE','{\"original_owner_decision\":true}' FROM companies").execute(&mut c).await.unwrap();
    let before: Value = sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j")
        .fetch_one(&mut c)
        .await
        .unwrap();
    let company: Value = sqlx::query_scalar("SELECT to_jsonb(c) FROM companies c")
        .fetch_one(&mut c)
        .await
        .unwrap();
    let receipt = apify_intake_finish(&mut c, &v, id).await.unwrap();
    assert_eq!(receipt["counts"]["updated"], 1);
    assert_eq!(receipt["counts"]["inserted"], 0);
    let after: Value = sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j")
        .fetch_one(&mut c)
        .await
        .unwrap();
    for field in [
        "title",
        "job_url",
        "source_platform",
        "status",
        "match_score",
        "match_explanation",
        "fixture_owner_notes",
        "discovery_metadata",
        "company_id",
        "created_at",
    ] {
        assert_eq!(after[field], before[field], "{field}");
    }
    assert_eq!(
        sqlx::query_scalar::<_, Value>("SELECT to_jsonb(c) FROM companies c")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        company
    );
    assert_eq!(f.calls.lock().await.len(), 5);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_intake_applies_original_explicit_keyword_filter_before_job_writes() {
    let mut c = apify_intake_fixture().await;
    let (v, f, stop, task) = apify_job_http("ok").await;
    let settings = ApifyJobSettings::from_values(&v).unwrap();
    let client = ApifyJobClient::from_values(&v, true).unwrap();
    let mut input = apify_job_input();
    input["query"]["keywords"] = json!(["entirely absent keyword"]);
    let id = Uuid::from_u128(71003);
    ApifyJobService {
        settings: &settings,
        client: &client,
    }
    .acquire(&mut c, input, id)
    .await
    .unwrap();
    let receipt = apify_intake_finish(&mut c, &v, id).await.unwrap();
    assert_eq!(receipt["counts"]["skipped"], 1);
    assert_eq!(
        receipt["exclusions"][0]["code"],
        "explicit_keyword_mismatch"
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM jobs")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        0
    );
    assert_eq!(f.calls.lock().await.len(), 5);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_intake_changed_credential_or_reviewed_configuration_holds_local_writes_and_keeps_paid_finding()
 {
    let mut c = apify_intake_fixture().await;
    let (v, f, stop, task) = apify_job_http("ok").await;
    let id = Uuid::from_u128(71004);
    apify_transport_acquire(&mut c, &v, 71004).await.unwrap();
    let before = apify_intake_snapshot(&mut c).await;
    for field in ["APIFY_API_TOKEN", "APIFY_PER_RUN_CAP_USD"] {
        let mut changed = v.clone();
        changed.insert(
            field.into(),
            if field == "APIFY_API_TOKEN" {
                "CHANGED_PRIVATE_TOKEN"
            } else {
                "0.100002"
            }
            .into(),
        );
        assert_eq!(
            apify_intake_finish(&mut c, &changed, id).await.unwrap_err(),
            Failure("apify_intake_configuration_changed")
        );
        assert_eq!(apify_intake_snapshot(&mut c).await, before);
    }
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_intake_aged_original_finding_holds_without_clearing_original_reservation_or_restarting()
 {
    let mut c = apify_intake_fixture().await;
    let (v, f, stop, task) = apify_job_http("ok").await;
    let id = Uuid::from_u128(71005);
    apify_transport_acquire(&mut c, &v, 71005).await.unwrap();
    let mut journal = apify_intake_journal(&mut c, id).await;
    let old = (chrono::Utc::now() - chrono::Duration::hours(25)).to_rfc3339();
    journal["finding"]["observed_at"] = json!(old);
    for job in journal["finding"]["jobs"].as_array_mut().unwrap() {
        for field in ["first_observed_date", "last_observed_date", "retrieved_at"] {
            job[field] = json!(old);
        }
    }
    apify_intake_save_fixture_journal(&mut c, id, journal).await;
    let before = apify_intake_snapshot(&mut c).await;
    assert_eq!(
        apify_intake_finish(&mut c, &v, id).await.unwrap_err(),
        Failure("apify_intake_finding_expired")
    );
    assert_eq!(apify_intake_snapshot(&mut c).await, before);
    assert!(apify_intake::read(&mut c, id).await.unwrap().is_none());
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_intake_lost_start_cannot_be_promoted_to_local_receipt_or_refund() {
    let mut c = apify_intake_fixture().await;
    let (v, f, stop, task) = apify_job_http("lost_start").await;
    let id = Uuid::from_u128(71006);
    assert!(apify_transport_acquire(&mut c, &v, 71006).await.is_err());
    let before = apify_intake_snapshot(&mut c).await;
    assert_eq!(
        apify_intake_finish(&mut c, &v, id).await.unwrap_err(),
        Failure("apify_intake_finding_missing")
    );
    assert_eq!(apify_intake_snapshot(&mut c).await, before);
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_intake_dropped_receipt_rolls_back_all_local_rows_and_recovers_without_another_provider_call()
 {
    let mut c = apify_intake_fixture().await;
    let (v, f, stop, task) = apify_job_http("ok").await;
    let id = Uuid::from_u128(71007);
    apify_transport_acquire(&mut c, &v, 71007).await.unwrap();
    sqlx::raw_sql("CREATE FUNCTION fixture_apify_intake_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'apify_intake:') THEN RETURN NULL;END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_apify_intake_drop BEFORE INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_apify_intake_drop()").execute(&mut c).await.unwrap();
    let before = apify_intake_snapshot(&mut c).await;
    assert_eq!(
        apify_intake_finish(&mut c, &v, id).await.unwrap_err(),
        Failure("apify_intake_write_ack_failed")
    );
    assert_eq!(apify_intake_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP TRIGGER fixture_apify_intake_drop ON owner_preferences;DROP FUNCTION fixture_apify_intake_drop()").execute(&mut c).await.unwrap();
    assert_eq!(
        apify_intake_finish(&mut c, &v, id).await.unwrap()["counts"]["inserted"],
        1
    );
    assert_eq!(f.calls.lock().await.len(), 5);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_intake_final_ack_rejects_late_job_rewrite_after_receipt_trigger_and_preserves_remote_evidence()
 {
    let mut c = apify_intake_fixture().await;
    let (v, _, stop, task) = apify_job_http("ok").await;
    let id = Uuid::from_u128(71008);
    apify_transport_acquire(&mut c, &v, 71008).await.unwrap();
    sqlx::raw_sql("CREATE FUNCTION fixture_apify_intake_job() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'apify_intake:') THEN UPDATE jobs SET status='applied';END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_apify_intake_job AFTER INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_apify_intake_job()").execute(&mut c).await.unwrap();
    let before = apify_intake_snapshot(&mut c).await;
    assert_eq!(
        apify_intake_finish(&mut c, &v, id).await.unwrap_err(),
        Failure("public_job_intake_write_ack_failed")
    );
    assert_eq!(apify_intake_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP TRIGGER fixture_apify_intake_job ON owner_preferences;DROP FUNCTION fixture_apify_intake_job()").execute(&mut c).await.unwrap();
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_intake_detects_exact_one_micro_monthly_mutation_after_receipt_even_near_numeric_maximum()
 {
    let mut c = apify_intake_fixture().await;
    let (v, _, stop, task) = apify_job_http("ok").await;
    let id = Uuid::from_u128(71009);
    apify_transport_acquire(&mut c, &v, 71009).await.unwrap();
    sqlx::query(
        "UPDATE discovery_monthly_budgets SET reserved=9999999999.900000 WHERE provider='apify'",
    )
    .execute(&mut c)
    .await
    .unwrap();
    sqlx::raw_sql("CREATE FUNCTION fixture_apify_intake_budget() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'apify_intake:') THEN UPDATE discovery_monthly_budgets SET reserved=reserved+0.000001 WHERE provider='apify';END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_apify_intake_budget AFTER INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_apify_intake_budget()").execute(&mut c).await.unwrap();
    let before = apify_intake_snapshot(&mut c).await;
    assert_eq!(
        apify_intake_finish(&mut c, &v, id).await.unwrap_err(),
        Failure("apify_intake_write_ack_failed")
    );
    assert_eq!(apify_intake_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP TRIGGER fixture_apify_intake_budget ON owner_preferences;DROP FUNCTION fixture_apify_intake_budget()").execute(&mut c).await.unwrap();
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_intake_final_ack_rejects_original_journal_mutation_after_receipt() {
    let mut c = apify_intake_fixture().await;
    let (v, _, stop, task) = apify_job_http("ok").await;
    let id = Uuid::from_u128(71010);
    apify_transport_acquire(&mut c, &v, 71010).await.unwrap();
    sqlx::raw_sql("CREATE FUNCTION fixture_apify_intake_journal() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'apify_intake:') THEN UPDATE owner_preferences SET value=value || '{\"unexpected\":true}'::jsonb WHERE starts_with(key,'apify_job:');END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_apify_intake_journal AFTER INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_apify_intake_journal()").execute(&mut c).await.unwrap();
    let before = apify_intake_snapshot(&mut c).await;
    assert_eq!(
        apify_intake_finish(&mut c, &v, id).await.unwrap_err(),
        Failure("apify_intake_write_ack_failed")
    );
    assert_eq!(apify_intake_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP TRIGGER fixture_apify_intake_journal ON owner_preferences;DROP FUNCTION fixture_apify_intake_journal()").execute(&mut c).await.unwrap();
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_intake_rechecks_pinned_profile_after_receipt_and_retained_read_does_not_require_current_profile()
 {
    let mut c = apify_intake_fixture().await;
    let (v, f, stop, task) = apify_job_http("ok").await;
    let settings = ApifyJobSettings::from_values(&v).unwrap();
    let client = ApifyJobClient::from_values(&v, true).unwrap();
    let mut input = apify_job_input();
    input["use_profile"] = json!(true);
    let id = Uuid::from_u128(71011);
    ApifyJobService {
        settings: &settings,
        client: &client,
    }
    .acquire(&mut c, input, id)
    .await
    .unwrap();
    sqlx::raw_sql("CREATE FUNCTION fixture_apify_intake_profile() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'apify_intake:') THEN UPDATE candidate_profiles SET version=version+1;END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_apify_intake_profile AFTER INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_apify_intake_profile()").execute(&mut c).await.unwrap();
    let before = apify_intake_snapshot(&mut c).await;
    let profile = automated_apply_agents::profile_store::get(&mut c)
        .await
        .unwrap()
        .value;
    assert_eq!(
        apify_intake_finish(&mut c, &v, id).await.unwrap_err(),
        Failure("apify_intake_profile_changed")
    );
    assert_eq!(apify_intake_snapshot(&mut c).await, before);
    assert_eq!(
        automated_apply_agents::profile_store::get(&mut c)
            .await
            .unwrap()
            .value,
        profile
    );
    sqlx::raw_sql("DROP TRIGGER fixture_apify_intake_profile ON owner_preferences;DROP FUNCTION fixture_apify_intake_profile()").execute(&mut c).await.unwrap();
    let receipt = apify_intake_finish(&mut c, &v, id).await.unwrap();
    sqlx::query("UPDATE candidate_profiles SET version=version+1")
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        apify_intake_finish(&mut c, &BTreeMap::new(), id)
            .await
            .unwrap(),
        receipt
    );
    assert_eq!(apify_intake::read(&mut c, id).await.unwrap(), Some(receipt));
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_intake_keeps_selected_company_claims_in_source_evidence_without_promoting_curated_facts()
 {
    let mut c = apify_intake_fixture().await;
    let (v, _, stop, task) = apify_job_http("ok").await;
    let id = Uuid::from_u128(71012);
    apify_transport_acquire(&mut c, &v, 71012).await.unwrap();
    let mut journal = apify_intake_journal(&mut c, id).await;
    journal["finding"]["jobs"][0]["company_intelligence"] = json!({"stage":"seed","batch":"fictional-batch","technologies":["Rust"],"source":"naukri","verification_status":"source_reported"});
    apify_intake_save_fixture_journal(&mut c, id, journal).await;
    apify_intake_finish(&mut c, &v, id).await.unwrap();
    let observation: Value = sqlx::query_scalar("SELECT provenance FROM job_source_observations")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(
        observation["company_intelligence"]["verification_status"],
        "source_reported"
    );
    assert_eq!(observation["company_intelligence"]["stage"], "seed");
    let company: Value = sqlx::query_scalar("SELECT metadata FROM companies")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert!(company["startup_discovery"].is_null());
    assert!(company["stage"].is_null());
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_intake_corrupted_saved_receipt_hash_is_rejected_without_reingestion() {
    let mut c = apify_intake_fixture().await;
    let (v, f, stop, task) = apify_job_http("ok").await;
    let id = Uuid::from_u128(71013);
    apify_transport_acquire(&mut c, &v, 71013).await.unwrap();
    apify_intake_finish(&mut c, &v, id).await.unwrap();
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(value,'{receipt,counts,inserted}','100'::jsonb) WHERE key=$1").bind(format!("apify_intake:{}",id.simple())).execute(&mut c).await.unwrap();
    let before = apify_intake_snapshot(&mut c).await;
    assert_eq!(
        apify_intake::read(&mut c, id).await.unwrap_err(),
        Failure("apify_intake_receipt_conflict")
    );
    assert_eq!(
        apify_intake_finish(&mut c, &v, id).await.unwrap_err(),
        Failure("apify_intake_receipt_conflict")
    );
    assert_eq!(apify_intake_snapshot(&mut c).await, before);
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_intake_reservation_rebinding_refuses_saved_receipt_without_new_remote_authority() {
    let mut c = apify_intake_fixture().await;
    let (v, _, stop, task) = apify_job_http("ok").await;
    let id = Uuid::from_u128(71014);
    apify_transport_acquire(&mut c, &v, 71014).await.unwrap();
    apify_intake_finish(&mut c, &v, id).await.unwrap();
    sqlx::query("UPDATE discovery_budget_reservations SET provider_run_id='differentRun' WHERE provider='apify'").execute(&mut c).await.unwrap();
    let before = apify_intake_snapshot(&mut c).await;
    assert_eq!(
        apify_intake::read(&mut c, id).await.unwrap_err(),
        Failure("apify_original_reservation_changed")
    );
    assert_eq!(
        apify_intake_finish(&mut c, &v, id).await.unwrap_err(),
        Failure("apify_original_reservation_changed")
    );
    assert_eq!(apify_intake_snapshot(&mut c).await, before);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_intake_empty_selected_finding_saves_truthful_zero_result_receipt() {
    let mut c = apify_intake_fixture().await;
    let (v, f, stop, task) = apify_job_http("conflict").await;
    let id = Uuid::from_u128(71015);
    apify_transport_acquire(&mut c, &v, 71015).await.unwrap();
    let receipt = apify_intake_finish(&mut c, &v, id).await.unwrap();
    assert_eq!(receipt["provider_status"], "partial");
    assert_eq!(receipt["counts"]["discovered"], 0);
    assert_eq!(receipt["counts"]["rejected"], 2);
    assert_eq!(receipt["counts"]["inserted"], 0);
    assert_eq!(receipt["job_ids"], json!([]));
    assert_eq!(receipt["company_ids_by_job"], json!({}));
    assert_eq!(f.calls.lock().await.len(), 5);
    stop.cancel();
    task.await.unwrap();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_intake_unknown_location_stays_unknown_and_is_not_a_false_explicit_mismatch() {
    let mut c = apify_intake_fixture().await;
    let (v, _, stop, task) = apify_job_http("ok").await;
    let settings = ApifyJobSettings::from_values(&v).unwrap();
    let client = ApifyJobClient::from_values(&v, true).unwrap();
    let id = Uuid::from_u128(71016);
    let mut input = apify_job_input();
    input["query"]["locations"] = json!(["Fictional Delhi"]);
    ApifyJobService {
        settings: &settings,
        client: &client,
    }
    .acquire(&mut c, input, id)
    .await
    .unwrap();
    let mut journal = apify_intake_journal(&mut c, id).await;
    let job = &mut journal["finding"]["jobs"][0];
    job["location"] = Value::Null;
    job["remote_type"] = json!("unknown");
    job["is_remote"] = Value::Null;
    apify_intake_save_fixture_journal(&mut c, id, journal).await;
    let receipt = apify_intake_finish(&mut c, &v, id).await.unwrap();
    assert_eq!(receipt["counts"]["inserted"], 1);
    assert_eq!(receipt["counts"]["skipped"], 0);
    let job: Value = sqlx::query_scalar("SELECT to_jsonb(j) FROM jobs j")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert!(job["location"].is_null());
    assert_eq!(job["remote_type"], "unknown");
    assert_eq!(job["source_verification_status"], "source_reported");
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_intake_unknown_start_cannot_be_promoted_to_job_intake_or_release_paid_cap() {
    let mut c = apify_intake_fixture().await;
    let (v, f, stop, task) = apify_job_http("lost_start").await;
    let id = Uuid::from_u128(71017);
    assert!(apify_transport_acquire(&mut c, &v, 71017).await.is_err());
    let before = apify_intake_snapshot(&mut c).await;
    assert_eq!(
        apify_intake_finish(&mut c, &v, id).await.unwrap_err(),
        Failure("apify_intake_finding_missing")
    );
    assert_eq!(apify_intake_snapshot(&mut c).await, before);
    assert!(apify_intake::read(&mut c, id).await.unwrap().is_none());
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    assert_eq!(
        apify_admission::read(&mut c, id).await.unwrap()["reservation"]["reserved_usd"],
        "0.100001"
    );
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_intake_rejects_promoted_or_unbounded_company_intelligence_before_local_writes() {
    let mut c = apify_intake_fixture().await;
    let (v, _, stop, task) = apify_job_http("ok").await;
    let id = Uuid::from_u128(71018);
    apify_transport_acquire(&mut c, &v, 71018).await.unwrap();
    let original = apify_intake_journal(&mut c, id).await;
    for intelligence in [
        json!({"stage":"seed","source":"naukri","verification_status":"verified"}),
        json!({"stage":"seed","source":"instahyre","verification_status":"source_reported"}),
        json!({"technologies": ["x".repeat(201)],"source":"naukri","verification_status":"source_reported"}),
    ] {
        let mut journal = original.clone();
        journal["finding"]["jobs"][0]["company_intelligence"] = intelligence;
        apify_intake_save_fixture_journal(&mut c, id, journal).await;
        let before = apify_intake_snapshot(&mut c).await;
        assert_eq!(
            apify_intake_finish(&mut c, &v, id).await.unwrap_err(),
            Failure("invalid_apify_job_finding")
        );
        assert_eq!(apify_intake_snapshot(&mut c).await, before);
    }
    stop.cancel();
    task.await.unwrap();
}
