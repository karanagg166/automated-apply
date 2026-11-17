//! Deferred separate acknowledged-run read allowances. Original acquisition uses fictional loopback only.
use automated_apply_agents::apify_jobs::read_admission as apify_read;
async fn apify_read_fixture() -> PgConnection {
    let mut c = apify_job_admission_fixture().await;
    sqlx::query("DELETE FROM owner_preferences WHERE starts_with(key,'apify_read:')")
        .execute(&mut c)
        .await
        .unwrap();
    c
}
async fn apify_read_snapshot(c: &mut PgConnection) -> Value {
    let original = apify_job_intent_snapshot(c).await;
    let reads:Value=sqlx::query_scalar("SELECT coalesce(jsonb_agg(to_jsonb(p) ORDER BY key),'[]') FROM owner_preferences p WHERE starts_with(key,'apify_read:')").fetch_one(c).await.unwrap();
    json!({"original":original,"reads":reads})
}
async fn apify_read_age_original(c: &mut PgConnection, parent: Uuid) {
    let mut original = apify_intake_journal(c, parent).await;
    let at = public_intake_time(c).await - chrono::Duration::minutes(20);
    // Fixture aging avoids sleeping or issuing repeated real provider requests.
    original["started_at"] = json!(at.to_rfc3339());
    original["expires_at"] = json!((at + chrono::Duration::seconds(75)).to_rfc3339());
    sqlx::query("UPDATE owner_preferences SET value=$2 WHERE key=$1")
        .bind(format!("apify_job:{}", parent.simple()))
        .bind(original)
        .execute(c)
        .await
        .unwrap();
}
async fn apify_read_admit(
    c: &mut PgConnection,
    v: &BTreeMap<String, String>,
    parent: Uuid,
    id: Uuid,
) -> Result<apify_read::Admission> {
    apify_read::admit(c, &ApifyJobSettings::from_values(v)?, parent, id).await
}
async fn apify_read_age_last(c: &mut PgConnection, parent: Uuid, id: Uuid) {
    let at = public_intake_time(c).await - chrono::Duration::seconds(301);
    let key = format!("apify_read:{}", id.simple());
    let mut row: Value = sqlx::query_scalar("SELECT value FROM owner_preferences WHERE key=$1")
        .bind(&key)
        .fetch_one(&mut *c)
        .await
        .unwrap();
    row["admitted_at"] = json!(at.to_rfc3339());
    row["expires_at"] = json!((at + chrono::Duration::seconds(45)).to_rfc3339());
    sqlx::query("UPDATE owner_preferences SET value=$2 WHERE key=$1")
        .bind(&key)
        .bind(row)
        .execute(&mut *c)
        .await
        .unwrap();
    let mut original = apify_intake_journal(c, parent).await;
    original["read_recovery"]["last_admitted_at"] = json!(at.to_rfc3339());
    original["read_recovery"]["next_allowed_at"] =
        json!((at + chrono::Duration::minutes(5)).to_rfc3339());
    sqlx::query("UPDATE owner_preferences SET value=$2 WHERE key=$1")
        .bind(format!("apify_job:{}", parent.simple()))
        .bind(original)
        .execute(c)
        .await
        .unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_read_original_admission_is_separate_visible_and_saved_replay_never_renews_grant_or_changes_budget()
 {
    let mut c = apify_read_fixture().await;
    let (v, f, stop, task) = apify_job_http("oversized").await;
    let parent = Uuid::from_u128(74001);
    let id = Uuid::from_u128(75001);
    assert!(apify_transport_acquire(&mut c, &v, 74001).await.is_err());
    apify_read_age_original(&mut c, parent).await;
    match apify_read_admit(&mut c, &v, parent, id).await.unwrap() {
        apify_read::Admission::Original(claim) => assert_eq!(claim.read_request_id(), id),
        _ => panic!("original read only"),
    }
    let value = apify_read::read(&mut c, parent, id).await.unwrap();
    assert_eq!(value["read_round_limit"], 3);
    assert_eq!(value["round"], 1);
    assert_eq!(value["read_admissions"], 1);
    assert_eq!(value["provider_start_authorized"], false);
    assert_eq!(value["provider_abort_authorized"], false);
    assert_eq!(value["http_attempts"], 0);
    assert_eq!(value["reservation"]["reserved_usd"], "0.100001");
    let before = apify_read_snapshot(&mut c).await;
    let calls = f.calls.lock().await.len();
    let mut observer = connection().await;
    assert_eq!(
        apify_read::read(&mut observer, parent, id).await.unwrap(),
        value
    );
    match apify_read_admit(&mut c, &BTreeMap::new(), parent, id)
        .await
        .unwrap()
    {
        apify_read::Admission::Retained(v) => assert_eq!(v, value),
        _ => panic!("no replay grant"),
    }
    assert_eq!(apify_read_snapshot(&mut c).await, before);
    assert_eq!(f.calls.lock().await.len(), calls);
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    assert!(!value.to_string().contains("CANARY"));
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_read_enforces_three_lifetime_rounds_and_five_minute_spacing_without_refunding_original_cap()
 {
    let mut c = apify_read_fixture().await;
    let (v, f, stop, task) = apify_job_http("oversized").await;
    let parent = Uuid::from_u128(74002);
    assert!(apify_transport_acquire(&mut c, &v, 74002).await.is_err());
    apify_read_age_original(&mut c, parent).await;
    for round in 1..=3 {
        let id = Uuid::from_u128(75020 + round);
        assert!(matches!(
            apify_read_admit(&mut c, &v, parent, id).await.unwrap(),
            apify_read::Admission::Original(_)
        ));
        let before = apify_read_snapshot(&mut c).await;
        let error = apify_read_admit(&mut c, &v, parent, Uuid::from_u128(75029))
            .await
            .err()
            .unwrap();
        assert_eq!(
            error,
            Failure(if round == 3 {
                "apify_read_lifetime_limit"
            } else {
                "apify_read_spacing_required"
            })
        );
        assert_eq!(apify_read_snapshot(&mut c).await, before);
        apify_read_age_last(&mut c, parent, id).await;
    }
    assert_eq!(
        apify_admission::read(&mut c, parent).await.unwrap()["read_rounds_admitted"],
        3
    );
    assert_eq!(
        apify_admission::read(&mut c, parent).await.unwrap()["reservation"]["reserved_usd"],
        "0.100001"
    );
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_read_unknown_start_and_still_active_original_intent_cannot_admit_get_recovery() {
    for (n, mode, expected) in [
        (
            74003,
            "lost_start",
            "apify_read_original_checkpoint_invalid",
        ),
        (74004, "oversized", "apify_read_original_still_active"),
    ] {
        let mut c = apify_read_fixture().await;
        let (v, f, stop, task) = apify_job_http(mode).await;
        let parent = Uuid::from_u128(n);
        assert!(apify_transport_acquire(&mut c, &v, n).await.is_err());
        if mode == "lost_start" {
            apify_read_age_original(&mut c, parent).await;
        }
        let before = apify_read_snapshot(&mut c).await;
        let calls = f.calls.lock().await.len();
        assert_eq!(
            apify_read_admit(&mut c, &v, parent, Uuid::from_u128(n + 1000))
                .await
                .err()
                .unwrap(),
            Failure(expected)
        );
        assert_eq!(apify_read_snapshot(&mut c).await, before);
        assert_eq!(f.calls.lock().await.len(), calls);
        assert_eq!(f.starts.load(Ordering::SeqCst), 1);
        stop.cancel();
        task.await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_read_changed_credentials_and_global_old_month_cooldown_hold_admission_without_clearing_original_evidence()
 {
    let mut c = apify_read_fixture().await;
    let (v, _, stop, task) = apify_job_http("oversized").await;
    let parent = Uuid::from_u128(74005);
    let id = Uuid::from_u128(75005);
    assert!(apify_transport_acquire(&mut c, &v, 74005).await.is_err());
    apify_read_age_original(&mut c, parent).await;
    let mut changed = v.clone();
    changed.insert("APIFY_API_TOKEN".into(), "CHANGED_PRIVATE_TOKEN".into());
    let before = apify_read_snapshot(&mut c).await;
    assert_eq!(
        apify_read_admit(&mut c, &changed, parent, id)
            .await
            .err()
            .unwrap(),
        Failure("apify_read_configuration_changed")
    );
    assert_eq!(apify_read_snapshot(&mut c).await, before);
    sqlx::query("INSERT INTO discovery_monthly_budgets(provider,month,reserved,cooldown_until) VALUES('apify','1999-01',0,clock_timestamp()+interval '1 hour')").execute(&mut c).await.unwrap();
    let before = apify_read_snapshot(&mut c).await;
    assert_eq!(
        apify_read_admit(&mut c, &v, parent, id)
            .await
            .err()
            .unwrap(),
        Failure("apify_execution_cooling_down")
    );
    assert_eq!(apify_read_snapshot(&mut c).await, before);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_read_final_admission_ack_rolls_back_dropped_intent_late_original_or_exact_month_mutation()
 {
    for effect in ["drop", "original", "monthly"] {
        let mut c = apify_read_fixture().await;
        let (v, f, stop, task) = apify_job_http("oversized").await;
        let parent = Uuid::from_u128(74006);
        let id = Uuid::from_u128(75006);
        assert!(apify_transport_acquire(&mut c, &v, 74006).await.is_err());
        apify_read_age_original(&mut c, parent).await;
        let body = match effect {
            "drop" => "RETURN NULL;",
            "original" => {
                "UPDATE owner_preferences SET value=value || '{\"late_mutation\":true}'::jsonb WHERE starts_with(key,'apify_job:');RETURN NEW;"
            }
            _ => {
                "UPDATE discovery_monthly_budgets SET reserved=reserved+0.000001 WHERE provider='apify';RETURN NEW;"
            }
        };
        let timing = if effect == "drop" { "BEFORE" } else { "AFTER" };
        sqlx::raw_sql(sqlx::AssertSqlSafe(format!("CREATE FUNCTION fixture_apify_read_admit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'apify_read:') THEN {body} END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_apify_read_admit {timing} INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_apify_read_admit()"))).execute(&mut c).await.unwrap();
        let before = apify_read_snapshot(&mut c).await;
        let calls = f.calls.lock().await.len();
        assert_eq!(
            apify_read_admit(&mut c, &v, parent, id)
                .await
                .err()
                .unwrap(),
            Failure("apify_read_write_ack_failed")
        );
        assert_eq!(apify_read_snapshot(&mut c).await, before);
        assert_eq!(f.calls.lock().await.len(), calls);
        sqlx::raw_sql("DROP TRIGGER fixture_apify_read_admit ON owner_preferences;DROP FUNCTION fixture_apify_read_admit()").execute(&mut c).await.unwrap();
        stop.cancel();
        task.await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_read_missing_prior_record_keeps_original_lifetime_admission_and_cannot_be_replaced()
{
    let mut c = apify_read_fixture().await;
    let (v, _, stop, task) = apify_job_http("oversized").await;
    let parent = Uuid::from_u128(74007);
    let id = Uuid::from_u128(75007);
    assert!(apify_transport_acquire(&mut c, &v, 74007).await.is_err());
    apify_read_age_original(&mut c, parent).await;
    apify_read_admit(&mut c, &v, parent, id).await.unwrap();
    apify_read_age_last(&mut c, parent, id).await;
    sqlx::query("DELETE FROM owner_preferences WHERE key=$1")
        .bind(format!("apify_read:{}", id.simple()))
        .execute(&mut c)
        .await
        .unwrap();
    let before = apify_read_snapshot(&mut c).await;
    assert_eq!(
        apify_read_admit(&mut c, &v, parent, Uuid::from_u128(75070))
            .await
            .err()
            .unwrap(),
        Failure("apify_read_prior_intent_missing")
    );
    assert_eq!(apify_read_snapshot(&mut c).await, before);
    assert_eq!(
        apify_admission::read(&mut c, parent).await.unwrap()["read_rounds_admitted"],
        1
    );
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_read_saved_grant_expiry_is_unknown_but_never_renews_and_current_profile_is_not_read_authority()
 {
    let mut c = apify_read_fixture().await;
    let (v, f, stop, task) = apify_job_http("oversized").await;
    let parent = Uuid::from_u128(74008);
    let id = Uuid::from_u128(75008);
    assert!(apify_transport_acquire(&mut c, &v, 74008).await.is_err());
    apify_read_age_original(&mut c, parent).await;
    sqlx::query("UPDATE candidate_profiles SET version=version+1")
        .execute(&mut c)
        .await
        .unwrap();
    apify_read_admit(&mut c, &v, parent, id).await.unwrap();
    apify_read_age_last(&mut c, parent, id).await;
    let saved = apify_read::read(&mut c, parent, id).await.unwrap();
    assert_eq!(saved["status"], "outcome_unknown");
    assert_eq!(saved["http_attempts"], 0);
    let before = apify_read_snapshot(&mut c).await;
    let calls = f.calls.lock().await.len();
    assert!(matches!(
        apify_read_admit(&mut c, &BTreeMap::new(), parent, id)
            .await
            .unwrap(),
        apify_read::Admission::Retained(_)
    ));
    assert_eq!(apify_read_snapshot(&mut c).await, before);
    assert_eq!(f.calls.lock().await.len(), calls);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn apify_read_already_retained_original_finding_needs_no_read_allowance_or_current_configuration()
 {
    let mut c = apify_read_fixture().await;
    let (v, f, stop, task) = apify_job_http("ok").await;
    let parent = Uuid::from_u128(74009);
    apify_transport_acquire(&mut c, &v, 74009).await.unwrap();
    let before = apify_read_snapshot(&mut c).await;
    match apify_read_admit(&mut c, &BTreeMap::new(), parent, Uuid::from_u128(75009))
        .await
        .unwrap()
    {
        apify_read::Admission::Retained(value) => {
            assert_eq!(value["recorded_state"], "not_needed");
            assert_eq!(value["finding_retained"], true);
            assert_eq!(value["provider_calls"], 0);
        }
        _ => panic!("no read grant"),
    }
    assert_eq!(apify_read_snapshot(&mut c).await, before);
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
