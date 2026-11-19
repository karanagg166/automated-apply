// Deferred original startup-parent/public-child fixtures. All HTTP is explicit numeric loopback.
use automated_apply_agents::startup_catalog::job_led as startup_job_led;
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_job_parent_profile_trigger_rolls_back_original_nested_admission_without_dispatch()
{
    let mut c = startup_job_fixture().await;
    let mut input = startup_job_input();
    input["filters"]["use_profile"] = json!(true);
    sqlx::raw_sql("CREATE FUNCTION fixture_startup_profile_late() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'startup_job:') THEN UPDATE candidate_profiles SET version=version+1;END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_startup_profile_late AFTER INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_startup_profile_late()").execute(&mut c).await.unwrap();
    let before = startup_job_snapshot(&mut c).await;
    let version: i32 = sqlx::query_scalar("SELECT version FROM candidate_profiles")
        .fetch_one(&mut c)
        .await
        .unwrap();
    assert_eq!(
        startup_job_led::admit(
            &mut c,
            &public_job_settings(),
            input,
            Uuid::from_u128(68010),
            90.0
        )
        .await
        .err()
        .unwrap(),
        Failure("discovery_run_write_ack_failed")
    );
    assert_eq!(startup_job_snapshot(&mut c).await, before);
    assert_eq!(
        sqlx::query_scalar::<_, i32>("SELECT version FROM candidate_profiles")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        version
    );
    sqlx::raw_sql("DROP TRIGGER fixture_startup_profile_late ON owner_preferences;DROP FUNCTION fixture_startup_profile_late()").execute(&mut c).await.unwrap();
}
async fn startup_job_fixture() -> PgConnection {
    let mut c = public_intake_fixture().await;
    startup_shortlist_schema(&mut c).await;
    sqlx::raw_sql("DROP TABLE IF EXISTS company_source_observations CASCADE;DELETE FROM owner_preferences WHERE starts_with(key,'startup_job:')").execute(&mut c).await.unwrap();
    let schema = include_str!("../../../../supabase/fresh_public/001_phase1_public.sql");
    let start = "CREATE TABLE IF NOT EXISTS public.company_source_observations (";
    let end = schema
        .split_once(start)
        .unwrap()
        .1
        .split_once("\n);")
        .unwrap()
        .0;
    sqlx::raw_sql(sqlx::AssertSqlSafe(format!("{start}{end}\n);")))
        .execute(&mut c)
        .await
        .unwrap();
    c
}
fn startup_job_input() -> Value {
    json!({"source":"greenhouse","mode":"job_led","query":{"max_age_days":null},"filters":{"use_profile":false,"max_employees":null,"include_unknown_size":true,"application_status":"all"}})
}
async fn startup_job_snapshot(c: &mut PgConnection) -> Value {
    let base = public_intake_snapshot(c).await;
    let startup:Value=sqlx::query_scalar("SELECT coalesce(jsonb_agg(jsonb_build_object('key',key,'value',value) ORDER BY key),'[]'::jsonb) FROM owner_preferences WHERE starts_with(key,'startup_job:')").fetch_one(c).await.unwrap();
    json!({"base":base,"startup":startup})
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_job_original_loopback_composes_company_results_and_replay_preserves_child_and_source_admission()
 {
    let mut c = startup_job_fixture().await;
    let (v, remote, stop, task) = public_job_http(PublicJobSource::Greenhouse, "ok").await;
    let settings = automated_apply_agents::source_registry::Settings::from_values(&v).unwrap();
    let client = PublicJobClient::from_values(&v, true).unwrap();
    let contacts = contact_settings();
    let service = startup_job_led::Service {
        sources: &settings,
        client: &client,
        contacts: &contacts,
        timeout_seconds: 90.0,
    };
    let id = Uuid::from_u128(68001);
    let first = service.run(&mut c, startup_job_input(), id).await.unwrap();
    assert_eq!(first["status"], "success");
    assert_eq!(first["counts"]["companies_observed"], 1);
    assert_eq!(first["counts"]["companies_matching"], 1);
    assert_eq!(first["rankings"].as_array().unwrap().len(), 1);
    assert_eq!(first["local_intake_complete"], true);
    assert_eq!(
        first["child_run"]["id"],
        json!(startup_job_led::child_id(id))
    );
    assert_eq!(remote.calls.load(Ordering::SeqCst), 1);
    assert_eq!(first["application_dispatch"], false);
    assert!(!first.to_string().contains("CANARY"));
    let before = startup_job_snapshot(&mut c).await;
    assert_eq!(
        service.run(&mut c, startup_job_input(), id).await.unwrap(),
        first
    );
    assert_eq!(startup_job_led::read(&mut c, id).await.unwrap(), first);
    assert_eq!(startup_runs::read(&mut c, id, 90.0).await.unwrap(), first);
    assert_eq!(startup_job_snapshot(&mut c).await, before);
    assert_eq!(remote.calls.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_job_failed_parent_insert_rolls_back_nested_job_parent_child_journals_and_source_window()
 {
    let mut c = startup_job_fixture().await;
    sqlx::raw_sql("CREATE FUNCTION fixture_startup_job_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.source,'startup_') THEN RETURN NULL;END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_startup_job_drop BEFORE INSERT ON discovery_runs FOR EACH ROW EXECUTE FUNCTION fixture_startup_job_drop()").execute(&mut c).await.unwrap();
    let before = startup_job_snapshot(&mut c).await;
    assert_eq!(
        startup_job_led::admit(
            &mut c,
            &public_job_settings(),
            startup_job_input(),
            Uuid::from_u128(68002),
            90.0
        )
        .await
        .err()
        .unwrap(),
        Failure("startup_run_write_ack_failed")
    );
    assert_eq!(startup_job_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP TRIGGER fixture_startup_job_drop ON discovery_runs;DROP FUNCTION fixture_startup_job_drop()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_job_parent_journal_trigger_cannot_change_an_original_child_source_window_after_its_ack()
 {
    let mut c = startup_job_fixture().await;
    sqlx::raw_sql("CREATE FUNCTION fixture_startup_job_window() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'startup_job:') THEN UPDATE provider_access_windows SET next_allowed_at=next_allowed_at+interval '1 hour';END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_startup_job_window AFTER INSERT ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_startup_job_window()").execute(&mut c).await.unwrap();
    let before = startup_job_snapshot(&mut c).await;
    assert_eq!(
        startup_job_led::admit(
            &mut c,
            &public_job_settings(),
            startup_job_input(),
            Uuid::from_u128(68003),
            90.0
        )
        .await
        .err()
        .unwrap(),
        Failure("public_job_write_ack_failed")
    );
    assert_eq!(startup_job_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP TRIGGER fixture_startup_job_window ON owner_preferences;DROP FUNCTION fixture_startup_job_window()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_job_cannot_attach_a_preexisting_unscoped_native_job_child_or_change_original_filters()
 {
    let mut c = startup_job_fixture().await;
    let id = Uuid::from_u128(68004);
    let input = startup_job_input();
    let normalized = automated_apply_agents::research_contract::normalize(
        automated_apply_agents::research_contract::Kind::StartupKeyed,
        input.clone(),
        chrono::Utc::now(),
    )
    .unwrap();
    public_owner_runs::admit(
        &mut c,
        &public_job_settings(),
        startup_job_led::child_input(&normalized, id).unwrap(),
        startup_job_led::child_id(id),
        90.0,
    )
    .await
    .unwrap();
    let before = startup_job_snapshot(&mut c).await;
    assert_eq!(
        startup_job_led::admit(&mut c, &public_job_settings(), input, id, 90.0)
            .await
            .err()
            .unwrap(),
        Failure("startup_job_led_child_already_claimed")
    );
    assert_eq!(startup_job_snapshot(&mut c).await, before);
    sqlx::query("DELETE FROM provider_access_windows WHERE provider='greenhouse'")
        .execute(&mut c)
        .await
        .unwrap();
    let id = Uuid::from_u128(68005);
    startup_job_led::admit(
        &mut c,
        &public_job_settings(),
        startup_job_input(),
        id,
        90.0,
    )
    .await
    .unwrap();
    let before = startup_job_snapshot(&mut c).await;
    let mut changed = startup_job_input();
    changed["filters"]["early_stage"] = json!(true);
    assert_eq!(
        startup_job_led::admit(&mut c, &public_job_settings(), changed, id, 90.0)
            .await
            .err()
            .unwrap(),
        Failure("startup_run_idempotency_conflict")
    );
    assert_eq!(startup_job_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_job_lost_original_invocation_remains_pending_and_does_not_replay_provider_work() {
    let mut c = startup_job_fixture().await;
    let (v, remote, stop, task) = public_job_http(PublicJobSource::Greenhouse, "ok").await;
    let settings = automated_apply_agents::source_registry::Settings::from_values(&v).unwrap();
    let client = PublicJobClient::from_values(&v, true).unwrap();
    let contacts = contact_settings();
    let id = Uuid::from_u128(68006);
    startup_job_led::admit(&mut c, &settings, startup_job_input(), id, 90.0)
        .await
        .unwrap();
    let before = startup_job_snapshot(&mut c).await;
    let result = startup_job_led::Service {
        sources: &settings,
        client: &client,
        contacts: &contacts,
        timeout_seconds: 90.0,
    }
    .run(&mut c, startup_job_input(), id)
    .await
    .unwrap();
    assert_eq!(result["status"], "running");
    assert_eq!(result["local_intake_complete"], false);
    assert_eq!(result["counts"], json!({}));
    assert_eq!(remote.calls.load(Ordering::SeqCst), 0);
    assert_eq!(startup_job_snapshot(&mut c).await, before);
    stop.cancel();
    task.await.unwrap();
}
async fn startup_job_parent_drop(c: &mut PgConnection, enable: bool) {
    if enable {
        sqlx::raw_sql("CREATE FUNCTION fixture_startup_parent_update() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.source,'startup_') THEN RETURN NULL;END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_startup_parent_update BEFORE UPDATE ON discovery_runs FOR EACH ROW EXECUTE FUNCTION fixture_startup_parent_update()").execute(c).await.unwrap();
    } else {
        sqlx::raw_sql("DROP TRIGGER fixture_startup_parent_update ON discovery_runs;DROP FUNCTION fixture_startup_parent_update()").execute(c).await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_job_failed_parent_completion_preserves_completed_child_and_local_retry_keeps_job_observation_times()
 {
    let mut c = startup_job_fixture().await;
    let (v, remote, stop, task) = public_job_http(PublicJobSource::Greenhouse, "ok").await;
    let settings = automated_apply_agents::source_registry::Settings::from_values(&v).unwrap();
    let client = PublicJobClient::from_values(&v, true).unwrap();
    let contacts = contact_settings();
    let service = startup_job_led::Service {
        sources: &settings,
        client: &client,
        contacts: &contacts,
        timeout_seconds: 90.0,
    };
    let id = Uuid::from_u128(68007);
    startup_job_parent_drop(&mut c, true).await;
    assert_eq!(
        service
            .run(&mut c, startup_job_input(), id)
            .await
            .unwrap_err(),
        Failure("startup_run_write_ack_failed")
    );
    let before = public_intake_snapshot(&mut c).await["facts"].clone();
    let saved = startup_job_led::read(&mut c, id).await.unwrap();
    assert_eq!(saved["usage"]["stage"], "company_results_pending");
    assert_eq!(saved["child_run"]["local_intake_complete"], true);
    startup_job_parent_drop(&mut c, false).await;
    assert_eq!(
        service.run(&mut c, startup_job_input(), id).await.unwrap()["status"],
        "success"
    );
    assert_eq!(public_intake_snapshot(&mut c).await["facts"], before);
    assert_eq!(remote.calls.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_job_original_company_attribution_is_not_silently_rebound_by_later_job_edits() {
    let mut c = startup_job_fixture().await;
    let (v, remote, stop, task) = public_job_http(PublicJobSource::Greenhouse, "ok").await;
    let settings = automated_apply_agents::source_registry::Settings::from_values(&v).unwrap();
    let client = PublicJobClient::from_values(&v, true).unwrap();
    let contacts = contact_settings();
    let service = startup_job_led::Service {
        sources: &settings,
        client: &client,
        contacts: &contacts,
        timeout_seconds: 90.0,
    };
    let id = Uuid::from_u128(68008);
    startup_job_parent_drop(&mut c, true).await;
    assert!(service.run(&mut c, startup_job_input(), id).await.is_err());
    startup_job_parent_drop(&mut c, false).await;
    let new = Uuid::from_u128(6800801);
    sqlx::query("INSERT INTO companies(id,name) VALUES($1,'Edited Fictional Employer')")
        .bind(new)
        .execute(&mut c)
        .await
        .unwrap();
    sqlx::query("UPDATE jobs SET company_id=$1")
        .bind(new)
        .execute(&mut c)
        .await
        .unwrap();
    let before = startup_job_snapshot(&mut c).await;
    assert_eq!(
        service
            .run(&mut c, startup_job_input(), id)
            .await
            .unwrap_err(),
        Failure("startup_job_led_company_attribution_changed")
    );
    assert_eq!(startup_job_snapshot(&mut c).await, before);
    assert_eq!(remote.calls.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_job_parent_terminal_trigger_cannot_change_selected_catalog_facts_after_the_snapshot()
 {
    let mut c = startup_job_fixture().await;
    let (v, remote, stop, task) = public_job_http(PublicJobSource::Greenhouse, "ok").await;
    let settings = automated_apply_agents::source_registry::Settings::from_values(&v).unwrap();
    let client = PublicJobClient::from_values(&v, true).unwrap();
    let contacts = contact_settings();
    let service = startup_job_led::Service {
        sources: &settings,
        client: &client,
        contacts: &contacts,
        timeout_seconds: 90.0,
    };
    let id = Uuid::from_u128(68009);
    startup_job_parent_drop(&mut c, true).await;
    assert!(service.run(&mut c, startup_job_input(), id).await.is_err());
    startup_job_parent_drop(&mut c, false).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_startup_catalog_late() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'startup_job:') AND NEW.value->>'state'='completed' THEN UPDATE companies SET name='Changed after snapshot';END IF;RETURN NEW;END $$;CREATE TRIGGER fixture_startup_catalog_late AFTER UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_startup_catalog_late()").execute(&mut c).await.unwrap();
    let before = startup_job_snapshot(&mut c).await;
    assert_eq!(
        startup_job_led::finish(&mut c, id, &settings, &contacts)
            .await
            .unwrap_err(),
        Failure("startup_run_write_ack_failed")
    );
    assert_eq!(startup_job_snapshot(&mut c).await, before);
    assert_eq!(remote.calls.load(Ordering::SeqCst), 1);
    sqlx::raw_sql("DROP TRIGGER fixture_startup_catalog_late ON owner_preferences;DROP FUNCTION fixture_startup_catalog_late()").execute(&mut c).await.unwrap();
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_job_owner_http_uses_original_key_and_reads_saved_parent_child_without_more_gets() {
    let _c = startup_job_fixture().await;
    let (mut v, remote, remote_stop, remote_task) =
        public_job_http(PublicJobSource::Greenhouse, "ok").await;
    v.extend(host_values());
    let (url, stop, task) = http_fixture_values(v).await;
    let mut input = startup_job_input();
    input["idempotency_key"] = json!("fictional_startup_http_job_led");
    let http = client();
    let root = format!("{url}/api/v1/startups/discovery/runs");
    let response = http
        .post(&root)
        .bearer_auth(HOST_TOKEN)
        .json(&input)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    let first: Value = response.json().await.unwrap();
    assert_eq!(first["local_intake_complete"], true);
    let response = http
        .get(format!("{root}/{}", first["id"].as_str().unwrap()))
        .bearer_auth(HOST_TOKEN)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    assert_eq!(response.json::<Value>().await.unwrap(), first);
    assert_eq!(remote.calls.load(Ordering::SeqCst), 1);
    stop.cancel();
    task.await.unwrap();
    remote_stop.cancel();
    remote_task.await.unwrap();
}
