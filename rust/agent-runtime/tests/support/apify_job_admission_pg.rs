// Deferred exact USD/admission fixtures. No token files, HTTP, Actors or real money.
use automated_apply_agents::apify_jobs::{
    admission as apify_admission, settings::Settings as ApifyJobSettings,
};
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_final_original_ack_detects_new_global_cooldown_added_by_journal_trigger() {
    let mut c = apify_job_admission_fixture().await;
    sqlx::raw_sql("CREATE FUNCTION fixture_apify_other_cooldown() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'apify_job:') THEN INSERT INTO discovery_monthly_budgets(provider,month,reserved,cooldown_until) VALUES('apify','1999-01',0,clock_timestamp()+interval '1 hour');END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_apify_other_cooldown AFTER INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_apify_other_cooldown()").execute(&mut c).await.unwrap();
    let before = apify_job_intent_snapshot(&mut c).await;
    assert_eq!(
        apify_job_admit(&mut c, 69013).await.err().unwrap(),
        Failure("apify_execution_write_ack_failed")
    );
    assert_eq!(apify_job_intent_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP TRIGGER fixture_apify_other_cooldown ON owner_preferences;DROP FUNCTION fixture_apify_other_cooldown()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_expired_lost_original_intent_keeps_full_cap_without_constructing_a_second_grant() {
    let mut c = apify_job_admission_fixture().await;
    apify_job_admit(&mut c, 69014).await.unwrap();
    let key = format!("apify_job:{}", Uuid::from_u128(69014).simple());
    sqlx::query("UPDATE owner_preferences SET value=jsonb_set(jsonb_set(value,'{started_at}',to_jsonb(clock_timestamp()-interval '80 seconds')),'{expires_at}',to_jsonb(clock_timestamp()-interval '5 seconds')) WHERE key=$1").bind(&key).execute(&mut c).await.unwrap();
    // Bind both timestamps to one fixed saved instant, preserving the exact original lease duration.
    let mut journal: Value = sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(&key)
        .fetch_one(&mut c)
        .await
        .unwrap();
    let started =
        chrono::DateTime::parse_from_rfc3339(journal["started_at"].as_str().unwrap()).unwrap();
    journal["expires_at"] = json!((started + chrono::Duration::seconds(75)).to_rfc3339());
    sqlx::query("UPDATE owner_preferences SET value=$2 WHERE key=$1")
        .bind(&key)
        .bind(journal)
        .execute(&mut c)
        .await
        .unwrap();
    let before = apify_job_intent_snapshot(&mut c).await;
    match apify_job_admit(&mut c, 69014).await.unwrap() {
        apify_admission::Admission::Retained(value) => {
            assert_eq!(value["status"], "outcome_unknown");
            assert_eq!(value["reservation"]["reserved_usd"], "0.100001");
            assert_eq!(value["start_admissions"], 1)
        }
        _ => panic!("lost invocation must not be renewed"),
    }
    assert_eq!(apify_job_intent_snapshot(&mut c).await, before);
}
fn apify_job_values() -> BTreeMap<String, String> {
    let actor = json!({"actor_id":"fictional/public-jobs","build":"1.2.3","enabled":true,"reviewed":true,"review_expires_at":(chrono::Utc::now()+chrono::Duration::hours(12)).to_rfc3339(),"platform_usage_included":true,"account_spending_limit_verified":true,"schema_evidence_url":"https://actor-fixture.example/schema","pricing_evidence_url":"https://actor-fixture.example/pricing","permission_evidence_url":"https://actor-fixture.example/permission","pricing_model":"PAY_PER_EVENT","estimated_per_item_usd":0.001,"field_map":{"limit":"maxItems"}});
    BTreeMap::from([("APIFY_API_TOKEN".into(),"PRIVATE_APIFY_INTENT_TOKEN_CANARY".into()),("APIFY_MONTHLY_LIMIT_USD".into(),"2.000001".into()),("APIFY_PER_RUN_CAP_USD".into(),"0.100001".into()),("APIFY_SOURCES".into(),json!({"naukri":actor,"instahyre":actor}).to_string()),("APIFY_BUILD_REVIEWS".into(),json!({"naukri":{"build_id":"originalBuild","schema_digest":"a".repeat(64)},"instahyre":{"build_id":"originalBuild","schema_digest":"a".repeat(64)}}).to_string())])
}
async fn apify_job_admission_fixture() -> PgConnection {
    let mut c = apify_metadata_fixture().await;
    sqlx::query("DELETE FROM owner_preferences WHERE starts_with(key,'apify_job:')")
        .execute(&mut c)
        .await
        .unwrap();
    c
}
fn apify_job_input() -> Value {
    json!({"source":"naukri","allow_paid":true,"use_profile":false,"query":{"max_age_days":null}})
}
async fn apify_job_admit(c: &mut PgConnection, n: u128) -> Result<apify_admission::Admission> {
    apify_admission::admit(
        c,
        &ApifyJobSettings::from_values(&apify_job_values()).unwrap(),
        apify_job_input(),
        Uuid::from_u128(n),
    )
    .await
}
async fn apify_job_intent_snapshot(c: &mut PgConnection) -> Value {
    sqlx::query_scalar("SELECT jsonb_build_object('journal',(SELECT jsonb_agg(jsonb_build_object('key',key,'value',value) ORDER BY key) FROM owner_preferences WHERE starts_with(key,'apify_job:')),'reservations',(SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM discovery_budget_reservations r),'monthly',(SELECT jsonb_agg(to_jsonb(b) ORDER BY provider,month) FROM discovery_monthly_budgets b),'owner',(SELECT value FROM owner_preferences WHERE key='agent_conversation:primary'))").fetch_one(c).await.unwrap()
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_original_usd_admission_is_visible_before_dispatch_and_replay_does_not_reserve_or_renew()
 {
    let mut c = apify_job_admission_fixture().await;
    let owner = apify_job_intent_snapshot(&mut c).await["owner"].clone();
    let id = Uuid::from_u128(69001);
    match apify_job_admit(&mut c, 69001).await.unwrap() {
        apify_admission::Admission::Original(claim) => assert_eq!(claim.request_id(), id),
        _ => panic!("original required"),
    }
    let first = apify_admission::read(&mut c, id).await.unwrap();
    assert_eq!(first["status"], "pending");
    assert_eq!(first["reservation"]["reserved_usd"], "0.100001");
    assert_eq!(first["reservation"]["billing_final"], false);
    assert_eq!(first["replay_authorized"], false);
    assert!(first["provider_start_attempted"].is_null());
    assert!(!first.to_string().contains("CANARY"));
    let mut other = connection().await;
    assert_eq!(
        sqlx::query_scalar::<_, String>(
            "SELECT reserved::text FROM discovery_monthly_budgets WHERE provider='apify'"
        )
        .fetch_one(&mut other)
        .await
        .unwrap(),
        "0.100001"
    );
    let before = apify_job_intent_snapshot(&mut c).await;
    assert_eq!(before["owner"], owner);
    let empty = ApifyJobSettings::from_values(&BTreeMap::new()).unwrap();
    match apify_admission::admit(&mut c, &empty, apify_job_input(), id)
        .await
        .unwrap()
    {
        apify_admission::Admission::Retained(value) => assert_eq!(value, first),
        _ => panic!("no replay grant"),
    }
    assert_eq!(apify_job_intent_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_usd_monthly_cap_is_exact_at_one_micro_and_changed_uuid_body_cannot_reuse_original_intent()
 {
    let mut c = apify_job_admission_fixture().await;
    let mut v = apify_job_values();
    v.insert("APIFY_MONTHLY_LIMIT_USD".into(), "0.200002".into());
    let settings = ApifyJobSettings::from_values(&v).unwrap();
    for n in [69002, 69003] {
        apify_admission::admit(&mut c, &settings, apify_job_input(), Uuid::from_u128(n))
            .await
            .unwrap();
    }
    assert_eq!(
        sqlx::query_scalar::<_, String>(
            "SELECT reserved::text FROM discovery_monthly_budgets WHERE provider='apify'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        "0.200002"
    );
    let before = apify_job_intent_snapshot(&mut c).await;
    assert_eq!(
        apify_admission::admit(&mut c, &settings, apify_job_input(), Uuid::from_u128(69004))
            .await
            .err()
            .unwrap(),
        Failure("apify_execution_budget_exhausted")
    );
    let mut changed = apify_job_input();
    changed["query"]["limit"] = json!(10);
    assert_eq!(
        apify_admission::admit(&mut c, &settings, changed, Uuid::from_u128(69002))
            .await
            .err()
            .unwrap(),
        Failure("apify_original_intent_request_conflict")
    );
    assert_eq!(apify_job_intent_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_cooldown_in_an_older_month_blocks_new_reservation_without_touching_unknown_previous_admission()
 {
    let mut c = apify_job_admission_fixture().await;
    apify_job_admit(&mut c, 69005).await.unwrap();
    sqlx::query("INSERT INTO discovery_monthly_budgets(provider,month,reserved,cooldown_until) VALUES('apify','2000-01',0,clock_timestamp()+interval '1 hour')").execute(&mut c).await.unwrap();
    let before = apify_job_intent_snapshot(&mut c).await;
    assert_eq!(
        apify_job_admit(&mut c, 69006).await.err().unwrap(),
        Failure("apify_execution_cooling_down")
    );
    assert_eq!(apify_job_intent_snapshot(&mut c).await, before);
    assert_eq!(
        apify_admission::read(&mut c, Uuid::from_u128(69005))
            .await
            .unwrap()["reservation"]["reserved_usd"],
        "0.100001"
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_dropped_original_journal_ack_rolls_back_the_full_numeric_reservation_and_monthly_increment()
 {
    let mut c = apify_job_admission_fixture().await;
    sqlx::raw_sql("CREATE FUNCTION fixture_apify_intent_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'apify_job:') THEN RETURN NULL;END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_apify_intent_drop BEFORE INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_apify_intent_drop()").execute(&mut c).await.unwrap();
    let before = apify_job_intent_snapshot(&mut c).await;
    assert_eq!(
        apify_job_admit(&mut c, 69007).await.err().unwrap(),
        Failure("apify_execution_write_ack_failed")
    );
    assert_eq!(apify_job_intent_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP TRIGGER fixture_apify_intent_drop ON owner_preferences;DROP FUNCTION fixture_apify_intent_drop()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_late_journal_trigger_cannot_change_the_numeric_monthly_total_after_its_initial_ack()
{
    let mut c = apify_job_admission_fixture().await;
    sqlx::raw_sql("CREATE FUNCTION fixture_apify_intent_late() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'apify_job:') THEN UPDATE discovery_monthly_budgets SET reserved=reserved+0.000001 WHERE provider='apify';END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_apify_intent_late AFTER INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_apify_intent_late()").execute(&mut c).await.unwrap();
    let before = apify_job_intent_snapshot(&mut c).await;
    assert_eq!(
        apify_job_admit(&mut c, 69008).await.err().unwrap(),
        Failure("apify_execution_write_ack_failed")
    );
    assert_eq!(apify_job_intent_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP TRIGGER fixture_apify_intent_late ON owner_preferences;DROP FUNCTION fixture_apify_intent_late()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_profile_pin_change_during_original_admission_rolls_back_profile_budget_and_intent() {
    let mut c = apify_job_admission_fixture().await;
    let mut input = apify_job_input();
    input["use_profile"] = json!(true);
    let profile = automated_apply_agents::profile_store::get(&mut c)
        .await
        .unwrap()
        .value;
    sqlx::raw_sql("CREATE FUNCTION fixture_apify_intent_profile() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'apify_job:') THEN UPDATE candidate_profiles SET version=version+1;END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_apify_intent_profile AFTER INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_apify_intent_profile()").execute(&mut c).await.unwrap();
    let before = apify_job_intent_snapshot(&mut c).await;
    assert_eq!(
        apify_admission::admit(
            &mut c,
            &ApifyJobSettings::from_values(&apify_job_values()).unwrap(),
            input,
            Uuid::from_u128(69009)
        )
        .await
        .err()
        .unwrap(),
        Failure("apify_execution_write_ack_failed")
    );
    assert_eq!(apify_job_intent_snapshot(&mut c).await, before);
    assert_eq!(
        automated_apply_agents::profile_store::get(&mut c)
            .await
            .unwrap()
            .value,
        profile
    );
    sqlx::raw_sql("DROP TRIGGER fixture_apify_intent_profile ON owner_preferences;DROP FUNCTION fixture_apify_intent_profile()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_missing_build_review_paid_consent_or_credentials_consumes_no_allowance() {
    let mut c = apify_job_admission_fixture().await;
    let before = apify_job_intent_snapshot(&mut c).await;
    for kind in ["review", "consent", "token"] {
        let mut v = apify_job_values();
        let mut input = apify_job_input();
        match kind {
            "review" => {
                v.remove("APIFY_BUILD_REVIEWS");
            }
            "token" => {
                v.remove("APIFY_API_TOKEN");
            }
            _ => input["allow_paid"] = json!(false),
        };
        assert!(
            apify_admission::admit(
                &mut c,
                &ApifyJobSettings::from_values(&v).unwrap(),
                input,
                Uuid::from_u128(69010)
            )
            .await
            .is_err()
        );
        assert_eq!(apify_job_intent_snapshot(&mut c).await, before);
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_changed_or_missing_original_numeric_reservation_fails_saved_read_without_repair_or_refund()
 {
    let mut c = apify_job_admission_fixture().await;
    apify_job_admit(&mut c, 69011).await.unwrap();
    sqlx::query("UPDATE discovery_budget_reservations SET provider_run_id='unboundRun' WHERE provider='apify'").execute(&mut c).await.unwrap();
    let before = apify_job_intent_snapshot(&mut c).await;
    assert_eq!(
        apify_admission::read(&mut c, Uuid::from_u128(69011))
            .await
            .unwrap_err(),
        Failure("apify_original_reservation_changed")
    );
    assert_eq!(apify_job_intent_snapshot(&mut c).await, before);
    sqlx::query("DELETE FROM discovery_budget_reservations WHERE provider='apify'")
        .execute(&mut c)
        .await
        .unwrap();
    let before = apify_job_intent_snapshot(&mut c).await;
    assert_eq!(
        apify_admission::read(&mut c, Uuid::from_u128(69011))
            .await
            .unwrap_err(),
        Failure("apify_original_reservation_missing")
    );
    assert_eq!(apify_job_intent_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_exact_monthly_total_near_numeric_maximum_detects_late_one_micro_trigger_change() {
    let mut c = apify_job_admission_fixture().await;
    let mut v = apify_job_values();
    v.insert("APIFY_MONTHLY_LIMIT_USD".into(), "9999999999.999999".into());
    sqlx::query("INSERT INTO discovery_monthly_budgets(provider,month,reserved) VALUES('apify',to_char(clock_timestamp(),'YYYY-MM'),9999999999.800000)").execute(&mut c).await.unwrap();
    sqlx::raw_sql("CREATE FUNCTION fixture_apify_large_total() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'apify_job:') THEN UPDATE discovery_monthly_budgets SET reserved=reserved+0.000001 WHERE provider='apify';END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_apify_large_total AFTER INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_apify_large_total()").execute(&mut c).await.unwrap();
    let before = apify_job_intent_snapshot(&mut c).await;
    assert_eq!(
        apify_admission::admit(
            &mut c,
            &ApifyJobSettings::from_values(&v).unwrap(),
            apify_job_input(),
            Uuid::from_u128(69012)
        )
        .await
        .err()
        .unwrap(),
        Failure("apify_execution_write_ack_failed")
    );
    assert_eq!(apify_job_intent_snapshot(&mut c).await, before);
    assert_eq!(
        sqlx::query_scalar::<_, String>(
            "SELECT reserved::text FROM discovery_monthly_budgets WHERE provider='apify'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        "9999999999.800000"
    );
    sqlx::raw_sql("DROP TRIGGER fixture_apify_large_total ON owner_preferences;DROP FUNCTION fixture_apify_large_total()").execute(&mut c).await.unwrap();
}
