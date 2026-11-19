// Deferred startup parent + original paid child composition. All provider IO is fictional numeric loopback.
async fn startup_paid_fixture() -> PgConnection {
    let mut c = apify_owner_fixture().await;
    startup_shortlist_schema(&mut c).await;
    sqlx::raw_sql("DROP TABLE IF EXISTS company_source_observations CASCADE;DELETE FROM owner_preferences WHERE starts_with(key,'startup_job:')").execute(&mut c).await.unwrap();
    let schema = include_str!("../../../../supabase/fresh_public/001_phase1_public.sql");
    let start = "CREATE TABLE IF NOT EXISTS public.company_source_observations (";
    let segment = schema
        .split_once(start)
        .unwrap()
        .1
        .split_once("\n);")
        .unwrap()
        .0;
    sqlx::raw_sql(sqlx::AssertSqlSafe(format!("{start}{segment}\n);")))
        .execute(&mut c)
        .await
        .unwrap();
    c
}
fn startup_paid_values(mut v: BTreeMap<String, String>) -> BTreeMap<String, String> {
    for key in ["APIFY_SOURCES", "APIFY_BUILD_REVIEWS"] {
        let mut map: Value = serde_json::from_str(&v[key]).unwrap();
        let original = map["naukri"].clone();
        map["wellfound"] = original.clone();
        map["work_at_a_startup"] = original;
        v.insert(key.into(), map.to_string());
    }
    v
}
fn startup_paid_input() -> Value {
    let mut input = startup_job_input();
    input["source"] = json!("wellfound");
    input["allow_paid"] = json!(true);
    input
}
async fn startup_paid_snapshot(c: &mut PgConnection) -> Value {
    let jobs = apify_owner_snapshot(c).await;
    let startup:Value=sqlx::query_scalar("SELECT coalesce(jsonb_agg(to_jsonb(p) ORDER BY key),'[]'::jsonb) FROM owner_preferences p WHERE starts_with(key,'startup_job:')").fetch_one(c).await.unwrap();
    json!({"jobs":jobs,"startup":startup})
}
async fn startup_paid_run(
    c: &mut PgConnection,
    v: &BTreeMap<String, String>,
    n: u128,
) -> Result<Value> {
    let sources = automated_apply_agents::source_registry::Settings::from_values(v)?;
    let public = PublicJobClient::from_values(v, true)?;
    let paid = ApifyJobSettings::from_values(v)?;
    let client = ApifyJobClient::from_values(v, true)?;
    startup_job_led::Service {
        sources: &sources,
        client: &public,
        contacts: &contact_settings(),
        timeout_seconds: 90.0,
    }
    .run_with_paid(
        c,
        startup_paid_input(),
        Uuid::from_u128(n),
        Some(&paid),
        Some(&client),
    )
    .await
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_paid_original_loopback_composes_company_results_without_promoting_source_claims_and_replay_does_not_pay_again()
 {
    let mut c = startup_paid_fixture().await;
    let (v, f, stop, task) = apify_job_http("ok").await;
    let v = startup_paid_values(v);
    let id = Uuid::from_u128(80001);
    let result = startup_paid_run(&mut c, &v, 80001).await.unwrap();
    assert_eq!(result["status"], "success");
    assert_eq!(result["local_intake_complete"], true);
    assert_eq!(result["counts"]["companies_observed"], 1);
    assert_eq!(result["counts"]["companies_matching"], 1);
    assert_eq!(
        result["child_run"]["id"],
        json!(startup_job_led::child_id(id))
    );
    assert_eq!(
        result["child_run"]["reservation"]["reserved_usd"],
        "0.100001"
    );
    assert_eq!(result["child_run"]["billing_final"], false);
    assert_eq!(result["application_dispatch"], false);
    assert!(!result.to_string().contains("CANARY"));
    let before = startup_paid_snapshot(&mut c).await;
    assert_eq!(startup_paid_run(&mut c, &v, 80001).await.unwrap(), result);
    assert_eq!(startup_job_led::read(&mut c, id).await.unwrap(), result);
    assert_eq!(startup_paid_snapshot(&mut c).await, before);
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    assert_eq!(f.calls.lock().await.len(), 5);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_paid_final_parent_admission_ack_rolls_back_child_reservation_and_exact_month_after_late_trigger()
 {
    let mut c = startup_paid_fixture().await;
    let (v, f, stop, task) = apify_job_http("ok").await;
    let v = startup_paid_values(v);
    sqlx::raw_sql("CREATE FUNCTION fixture_startup_paid_month() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'startup_job:') THEN UPDATE discovery_monthly_budgets SET reserved=reserved+0.000001 WHERE provider='apify';END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_startup_paid_month AFTER INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_startup_paid_month()").execute(&mut c).await.unwrap();
    let before = startup_paid_snapshot(&mut c).await;
    assert_eq!(
        startup_paid_run(&mut c, &v, 80002).await.unwrap_err(),
        Failure("apify_execution_write_ack_failed")
    );
    assert_eq!(startup_paid_snapshot(&mut c).await, before);
    assert_eq!(f.calls.lock().await.len(), 0);
    sqlx::raw_sql("DROP TRIGGER fixture_startup_paid_month ON owner_preferences;DROP FUNCTION fixture_startup_paid_month()").execute(&mut c).await.unwrap();
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_paid_dropped_parent_insertion_leaves_no_nested_job_parent_intent_or_reservation() {
    let mut c = startup_paid_fixture().await;
    let (v, f, stop, task) = apify_job_http("ok").await;
    let v = startup_paid_values(v);
    sqlx::raw_sql("CREATE FUNCTION fixture_startup_paid_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.source,'startup_') THEN RETURN NULL;END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_startup_paid_drop BEFORE INSERT ON discovery_runs FOR EACH ROW EXECUTE FUNCTION fixture_startup_paid_drop()").execute(&mut c).await.unwrap();
    let before = startup_paid_snapshot(&mut c).await;
    assert_eq!(
        startup_paid_run(&mut c, &v, 80003).await.unwrap_err(),
        Failure("startup_run_write_ack_failed")
    );
    assert_eq!(startup_paid_snapshot(&mut c).await, before);
    assert_eq!(f.calls.lock().await.len(), 0);
    sqlx::raw_sql("DROP TRIGGER fixture_startup_paid_drop ON discovery_runs;DROP FUNCTION fixture_startup_paid_drop()").execute(&mut c).await.unwrap();
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_paid_unknown_child_start_retains_parent_and_budget_without_another_paid_start_on_replay()
 {
    let mut c = startup_paid_fixture().await;
    let (v, f, stop, task) = apify_job_http("lost_start").await;
    let v = startup_paid_values(v);
    let id = Uuid::from_u128(80004);
    assert!(startup_paid_run(&mut c, &v, 80004).await.is_err());
    let before = startup_paid_snapshot(&mut c).await;
    let result = startup_paid_run(&mut c, &v, 80004).await.unwrap();
    assert_eq!(result["local_intake_complete"], false);
    assert_eq!(result["child_run"]["status"], "recovery_required");
    assert_eq!(
        result["child_run"]["reservation"]["reserved_usd"],
        "0.100001"
    );
    assert_eq!(startup_job_led::read(&mut c, id).await.unwrap(), result);
    assert_eq!(startup_paid_snapshot(&mut c).await, before);
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_paid_failed_company_finalization_preserves_completed_child_and_recovers_locally_without_refreshing_jobs()
 {
    let mut c = startup_paid_fixture().await;
    let (v, f, stop, task) = apify_job_http("ok").await;
    let v = startup_paid_values(v);
    sqlx::raw_sql("CREATE FUNCTION fixture_startup_paid_finish() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.source,'startup_') THEN RETURN NULL;END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_startup_paid_finish BEFORE UPDATE ON discovery_runs FOR EACH ROW EXECUTE FUNCTION fixture_startup_paid_finish()").execute(&mut c).await.unwrap();
    assert_eq!(
        startup_paid_run(&mut c, &v, 80005).await.unwrap_err(),
        Failure("startup_run_write_ack_failed")
    );
    let facts = apify_intake_snapshot(&mut c).await["facts"].clone();
    sqlx::raw_sql("DROP TRIGGER fixture_startup_paid_finish ON discovery_runs;DROP FUNCTION fixture_startup_paid_finish()").execute(&mut c).await.unwrap();
    assert_eq!(
        startup_paid_run(&mut c, &v, 80005).await.unwrap()["local_intake_complete"],
        true
    );
    assert_eq!(apify_intake_snapshot(&mut c).await["facts"], facts);
    assert_eq!(f.calls.lock().await.len(), 5);
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_paid_terminal_result_read_and_replay_do_not_require_current_credential_or_profile()
{
    let mut c = startup_paid_fixture().await;
    let (v, f, stop, task) = apify_job_http("ok").await;
    let v = startup_paid_values(v);
    let id = Uuid::from_u128(80006);
    let original = startup_paid_run(&mut c, &v, 80006).await.unwrap();
    sqlx::raw_sql("DROP TABLE candidate_profiles CASCADE")
        .execute(&mut c)
        .await
        .unwrap();
    let before = startup_paid_snapshot(&mut c).await;
    assert_eq!(
        startup_paid_run(&mut c, &BTreeMap::new(), 80006)
            .await
            .unwrap(),
        original
    );
    assert_eq!(startup_job_led::read(&mut c, id).await.unwrap(), original);
    assert_eq!(startup_paid_snapshot(&mut c).await, before);
    assert_eq!(f.calls.lock().await.len(), 5);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_paid_finalization_ack_detects_late_budget_change_without_refunding_or_replaying_child()
 {
    let mut c = startup_paid_fixture().await;
    let (v, f, stop, task) = apify_job_http("ok").await;
    let v = startup_paid_values(v);
    sqlx::raw_sql("CREATE FUNCTION fixture_startup_paid_final_month() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.source,'startup_') THEN UPDATE discovery_monthly_budgets SET reserved=reserved+0.000001 WHERE provider='apify';END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_startup_paid_final_month AFTER UPDATE ON discovery_runs FOR EACH ROW EXECUTE FUNCTION fixture_startup_paid_final_month()").execute(&mut c).await.unwrap();
    assert_eq!(
        startup_paid_run(&mut c, &v, 80007).await.unwrap_err(),
        Failure("startup_run_write_ack_failed")
    );
    assert_eq!(
        sqlx::query_scalar::<_, String>(
            "SELECT reserved::text FROM discovery_monthly_budgets WHERE provider='apify'"
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        "0.100001"
    );
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    sqlx::raw_sql("DROP TRIGGER fixture_startup_paid_final_month ON discovery_runs;DROP FUNCTION fixture_startup_paid_final_month()").execute(&mut c).await.unwrap();
    assert_eq!(
        startup_paid_run(&mut c, &v, 80007).await.unwrap()["local_intake_complete"],
        true
    );
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_paid_owner_http_uses_original_keyed_parent_and_saved_child_without_another_actor_start()
 {
    let _c = startup_paid_fixture().await;
    let (v, f, remote_stop, remote_task) = apify_job_http("ok").await;
    let mut v = startup_paid_values(v);
    v.extend(host_values());
    let (url, stop, task) = http_fixture_values(v).await;
    let http = client();
    let mut input = startup_paid_input();
    input["idempotency_key"] = json!("fictional_startup_paid_http");
    let path = format!("{url}/api/v1/startups/discovery/runs");
    let response = http
        .post(&path)
        .bearer_auth(HOST_TOKEN)
        .json(&input)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let result: Value = response.json().await.unwrap();
    assert_eq!(result["local_intake_complete"], true);
    let response = http
        .post(&path)
        .bearer_auth(HOST_TOKEN)
        .json(&input)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    assert_eq!(response.json::<Value>().await.unwrap(), result);
    let saved: Value = http
        .get(format!("{path}/{}", result["id"].as_str().unwrap()))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(saved, result);
    assert_eq!(f.starts.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
    remote_stop.cancel();
    remote_task.await.unwrap();
}
