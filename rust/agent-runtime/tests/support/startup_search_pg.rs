// Deferred filtered catalog and original shortlist fixtures; no provider/application action.
use automated_apply_agents::startup_catalog::{
    search as startup_search, shortlist as startup_shortlist,
};
async fn startup_search_call(c: &mut PgConnection, filters: Value) -> Result<Value> {
    startup_search::dispatch(
        c,
        startup_search::Route::Search,
        "POST",
        None,
        &serde_json::to_vec(&filters).unwrap(),
        &contact_settings(),
    )
    .await
}
async fn startup_save(c: &mut PgConnection, company: Uuid, input: Value) -> Result<Value> {
    startup_shortlist::save(
        c,
        company,
        "POST",
        None,
        &serde_json::to_vec(&input).unwrap(),
        &contact_settings(),
    )
    .await
}
async fn startup_shortlist_snapshot(c: &mut PgConnection) -> Value {
    sqlx::query_scalar("SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY company_id),'[]') FROM startup_shortlist_entries s").fetch_one(c).await.unwrap()
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_search_get_post_share_actual_filters_total_stable_rank_and_read_only_evidence() {
    let (mut c, company, _) = startup_detail_fixture().await;
    let before = companies_snapshot(&mut c).await;
    let post=startup_search_call(&mut c,json!({"max_employees":null,"use_profile":false,"query":"Fictional Contact Employer","limit":1})).await.unwrap();
    let get = startup_search::dispatch(
        &mut c,
        startup_search::Route::Search,
        "GET",
        Some(
            "max_employees=10000000&use_profile=false&query=Fictional%20Contact%20Employer&limit=1",
        ),
        &[],
        &contact_settings(),
    )
    .await
    .unwrap();
    assert_eq!(post["total"], 1);
    assert_eq!(post["startups"][0]["company_id"], company.to_string());
    assert_eq!(post, get);
    assert_eq!(companies_snapshot(&mut c).await, before);
    let empty = startup_search_call(
        &mut c,
        json!({"max_employees":null,"query":"Fictional Contact Employer","page":250}),
    )
    .await
    .unwrap();
    assert_eq!(empty["total"], 1);
    assert_eq!(empty["startups"], json!([]));
    use std::io::Write as _;
    let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let mut p=std::process::Command::new(root.join(".venv/bin/python")).current_dir(root).args(["-B","-c","import json,runpy,sys;runpy.run_path('rust/scripts/export_startup_contracts.py')['models']()['startup-search'].model_validate(json.load(sys.stdin));assert 'backend.app.core.config' not in sys.modules"]).stdin(std::process::Stdio::piped()).stderr(std::process::Stdio::piped()).spawn().unwrap();
    p.stdin
        .take()
        .unwrap()
        .write_all(post.to_string().as_bytes())
        .unwrap();
    let out = p.wait_with_output().unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_search_explicit_country_industry_size_skills_and_remote_filter_saved_facts() {
    let (mut c, company, _) = startup_detail_fixture().await;
    for (extra, want) in [
        (json!({"country":"IN"}), 1),
        (json!({"country":"US"}), 0),
        (json!({"industries":["developer tools"]}), 1),
        (json!({"industries":["AI"]}), 0),
        (
            json!({"min_employees":11,"max_employees":50,"exact_employee_count":true}),
            1,
        ),
        (json!({"max_employees":10}), 0),
        (json!({"skills":["Rust"]}), 1),
        (json!({"skills":["Unsupported skill"]}), 0),
        (json!({"verified_yc":true}), 0),
        (json!({"early_stage":true}), 0),
        (json!({"remote_preference":"remote"}), 1),
        (json!({"remote_preference":"onsite"}), 0),
    ] {
        let mut input =
            json!({"use_profile":false,"max_employees":null,"query":"Fictional Contact Employer"});
        for (k, v) in extra.as_object().unwrap() {
            input[k] = v.clone();
        }
        let result = startup_search_call(&mut c, input).await.unwrap();
        assert_eq!(result["total"], want, "{extra}");
        if want == 1 {
            assert_eq!(result["startups"][0]["company_id"], company.to_string());
        }
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_search_preserves_legacy_applied_and_multiple_packet_submission_evidence() {
    let (mut c, company, job) = startup_detail_fixture().await;
    sqlx::query("UPDATE jobs SET company_id=NULL WHERE company_id=$1 AND id<>$2")
        .bind(company)
        .bind(job)
        .execute(&mut c)
        .await
        .unwrap();
    let query = |status: &str| json!({"use_profile":false,"max_employees":null,"query":"Fictional Contact Employer","application_status":status});
    assert_eq!(
        startup_search_call(&mut c, query("not_applied"))
            .await
            .unwrap()["total"],
        1
    );
    assert_eq!(
        startup_search_call(&mut c, query("applied")).await.unwrap()["total"],
        0
    );
    sqlx::query("UPDATE jobs SET status='applied' WHERE id=$1")
        .bind(job)
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        startup_search_call(&mut c, query("applied")).await.unwrap()["total"],
        1
    );
    assert_eq!(
        startup_search_call(&mut c, query("not_applied"))
            .await
            .unwrap()["total"],
        0
    );
    assert!(!startup_search::matches_status(
        &json!({"status":"applied"}),
        &[json!({"lifecycle_state":"created"})],
        "packet_prepared"
    ));
    assert!(startup_search::matches_status(
        &json!({"status":"discovered"}),
        &[
            json!({"lifecycle_state":"created"}),
            json!({"lifecycle_state":"provider_confirmed_submitted"})
        ],
        "applied"
    ));
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_shortlist_preserves_first_note_snapshot_and_run_and_updates_saved_detail_flag() {
    let (mut c, company, _) = startup_detail_fixture().await;
    let saved = startup_save(&mut c, company, json!({"note":"Fictional owner note"}))
        .await
        .unwrap();
    assert_eq!(saved["created"], true);
    let before = startup_shortlist_snapshot(&mut c).await;
    sqlx::query("UPDATE companies SET name='Changed fictional company' WHERE id=$1")
        .bind(company)
        .execute(&mut c)
        .await
        .unwrap();
    let replay = startup_save(
        &mut c,
        company,
        json!({"note":"Different note","run_id":Uuid::nil()}),
    )
    .await
    .unwrap();
    assert_eq!(replay["created"], false);
    assert_eq!(replay["snapshot"], saved["snapshot"]);
    assert_eq!(startup_shortlist_snapshot(&mut c).await, before);
    assert_eq!(
        startup_read(&mut c, company).await.unwrap()["shortlisted"],
        true
    );
    let list = startup_search::dispatch(
        &mut c,
        startup_search::Route::Shortlist,
        "GET",
        Some("max_employees=10000000&use_profile=false"),
        &[],
        &contact_settings(),
    )
    .await
    .unwrap();
    assert_eq!(list["total"], 1);
    assert_eq!(list["startups"][0]["company_id"], company.to_string());
    assert_eq!(list["startups"][0]["shortlisted"], true);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_shortlist_complete_insert_after_trigger_ack_roll_back_the_new_entry() {
    let (mut c, company, _) = startup_detail_fixture().await;
    let before = startup_shortlist_snapshot(&mut c).await;
    for (timing, body) in [
        ("BEFORE", "RETURN NULL;"),
        ("BEFORE", "NEW.note='Changed by fixture';RETURN NEW;"),
        (
            "AFTER",
            "IF pg_trigger_depth()=1 THEN UPDATE startup_shortlist_entries SET note='Changed by fixture' WHERE company_id=NEW.company_id;END IF;RETURN NEW;",
        ),
    ] {
        let sql = format!(
            "CREATE FUNCTION fixture_startup_shortlist_corrupt() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {body} END $$;CREATE TRIGGER fixture_startup_shortlist_corrupt {timing} INSERT ON startup_shortlist_entries FOR EACH ROW EXECUTE FUNCTION fixture_startup_shortlist_corrupt()"
        );
        sqlx::raw_sql(sqlx::AssertSqlSafe(sql))
            .execute(&mut c)
            .await
            .unwrap();
        assert_eq!(
            startup_save(&mut c, company, json!({"note":"Fictional note"}))
                .await
                .unwrap_err(),
            Failure("startup_catalog_write_ack_failed")
        );
        assert_eq!(startup_shortlist_snapshot(&mut c).await, before);
        sqlx::raw_sql("DROP TRIGGER fixture_startup_shortlist_corrupt ON startup_shortlist_entries;DROP FUNCTION fixture_startup_shortlist_corrupt()").execute(&mut c).await.unwrap();
    }
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_shortlist_replay_filters_private_historical_fields_without_rewriting_saved_snapshot()
 {
    let (mut c, company, _) = startup_detail_fixture().await;
    startup_save(&mut c, company, json!({})).await.unwrap();
    sqlx::query("UPDATE startup_shortlist_entries SET snapshot=snapshot||'{\"private_vendor\":\"PRIVATE_SHORTLIST_CANARY\"}'::jsonb,note='PRIVATE_OWNER_NOTE_CANARY'").execute(&mut c).await.unwrap();
    let before = startup_shortlist_snapshot(&mut c).await;
    let result = startup_save(&mut c, company, json!({})).await.unwrap();
    assert!(!result.to_string().contains("PRIVATE_SHORTLIST_CANARY"));
    assert!(!result.to_string().contains("PRIVATE_OWNER_NOTE_CANARY"));
    assert_eq!(startup_shortlist_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_catalog_missing_query_contract_boundaries_fail_before_shortlist_writes() {
    let (mut c, company, _) = startup_detail_fixture().await;
    let before = startup_shortlist_snapshot(&mut c).await;
    assert_eq!(
        startup_save(&mut c, Uuid::nil(), json!({}))
            .await
            .unwrap_err(),
        Failure("startup_catalog_not_found")
    );
    assert_eq!(
        startup_save(&mut c, company, json!({"note":"x".repeat(2001)}))
            .await
            .unwrap_err(),
        Failure("invalid_startup_contract")
    );
    assert_eq!(
        startup_search_call(&mut c, json!({"unknown":true}))
            .await
            .unwrap_err(),
        Failure("invalid_startup_contract")
    );
    assert_eq!(
        startup_search::dispatch(
            &mut c,
            startup_search::Route::Search,
            "GET",
            Some("page=1&page=2"),
            &[],
            &contact_settings()
        )
        .await
        .unwrap_err(),
        Failure("invalid_startup_query")
    );
    assert_eq!(startup_shortlist_snapshot(&mut c).await, before);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_search_shortlist_owner_http_auth_and_methods_grant_no_submission_authority() {
    let (mut c, company, _) = startup_detail_fixture().await;
    let (url, stop, task) = http_fixture_values(host_values()).await;
    let http = client();
    let search = format!("{url}/api/v1/startups/search");
    assert_eq!(http.get(&search).send().await.unwrap().status(), 401);
    assert_eq!(
        http.post(&search)
            .bearer_auth(HOST_TOKEN)
            .header("x-agent-client", "extension")
            .json(&json!({}))
            .send()
            .await
            .unwrap()
            .status(),
        403
    );
    assert_eq!(
        http.post(&search)
            .bearer_auth(HOST_TOKEN)
            .json(&json!({"max_employees":null}))
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    assert_eq!(
        http.patch(&search)
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        405
    );
    let save = format!("{url}/api/v1/startups/{company}/shortlist");
    assert_eq!(
        http.get(&save)
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        405
    );
    let result: Value = http
        .post(&save)
        .bearer_auth(HOST_TOKEN)
        .json(&json!({"note":"Fictional shortlist"}))
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(result["created"], true);
    assert!(result.get("application_allowed").is_none());
    assert_eq!(
        http.get(format!("{url}/api/v1/startups/shortlist"))
            .bearer_auth(HOST_TOKEN)
            .send()
            .await
            .unwrap()
            .status(),
        200
    );
    stop.cancel();
    task.await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_search_reads_do_not_wait_for_owner_mutex_or_mutate_runtime_state() {
    let (mut c, _, _) = startup_detail_fixture().await;
    let before = browser_snapshot(&mut c).await;
    let mut other = connection().await;
    let mut tx = other.begin().await.unwrap();
    sqlx::query(
        "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
    )
    .execute(&mut *tx)
    .await
    .unwrap();
    sqlx::query("SET lock_timeout='100ms'")
        .execute(&mut c)
        .await
        .unwrap();
    startup_search_call(&mut c, json!({"max_employees":null}))
        .await
        .unwrap();
    assert_eq!(browser_snapshot(&mut c).await, before);
    tx.rollback().await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_shortlist_concurrent_saves_keep_one_original_snapshot_and_never_change_job_states()
{
    let (mut c, company, _) = startup_detail_fixture().await;
    let before = companies_snapshot(&mut c).await;
    sqlx::raw_sql("CREATE FUNCTION fixture_startup_slow_insert() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_sleep(0.05);RETURN NEW;END $$;CREATE TRIGGER fixture_startup_slow_insert BEFORE INSERT ON startup_shortlist_entries FOR EACH ROW EXECUTE FUNCTION fixture_startup_slow_insert()").execute(&mut c).await.unwrap();
    let mut other = connection().await;
    let (a, b) = tokio::join!(
        startup_save(&mut c, company, json!({"note":"Fictional first request"})),
        startup_save(
            &mut other,
            company,
            json!({"note":"Fictional second request"})
        )
    );
    assert!(a.is_ok() || b.is_ok());
    if let (Ok(a), Ok(b)) = (a, b) {
        assert_eq!(a["snapshot"], b["snapshot"]);
    }
    assert_eq!(
        startup_shortlist_snapshot(&mut c)
            .await
            .as_array()
            .unwrap()
            .len(),
        1
    );
    assert_eq!(companies_snapshot(&mut c).await, before);
    sqlx::raw_sql("DROP TRIGGER fixture_startup_slow_insert ON startup_shortlist_entries;DROP FUNCTION fixture_startup_slow_insert()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_search_company_limit_requires_narrower_source_without_silently_truncating_the_total()
 {
    let (mut c, _, _) = startup_detail_fixture().await;
    sqlx::query("INSERT INTO companies(id,name,domain) SELECT md5('fictional-startup-company-'||n)::uuid,'Fictional bounded company '||n,'company-'||n||'.fixture.example' FROM generate_series(1,501) n").execute(&mut c).await.unwrap();
    assert_eq!(
        startup_search_call(&mut c, json!({"use_profile":false,"max_employees":null}))
            .await
            .unwrap_err(),
        Failure("startup_catalog_company_limit")
    );
    let narrow = startup_search_call(
        &mut c,
        json!({"use_profile":false,"max_employees":null,"source":"manual"}),
    )
    .await
    .unwrap();
    assert!(narrow["total"].as_u64().unwrap() <= 500);
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn startup_shortlist_requires_a_saved_startup_run_and_preserves_its_identity_without_provider_work()
 {
    let (mut c, company, _) = startup_detail_fixture().await;
    sqlx::raw_sql("DROP TABLE IF EXISTS discovery_runs CASCADE;CREATE TABLE discovery_runs(id uuid PRIMARY KEY,source text NOT NULL)").execute(&mut c).await.unwrap();
    let run = Uuid::from_u128(994001);
    sqlx::query("INSERT INTO discovery_runs(id,source) VALUES($1,'manual')")
        .bind(run)
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        startup_save(&mut c, company, json!({"run_id":run}))
            .await
            .unwrap_err(),
        Failure("startup_catalog_run_not_found")
    );
    assert_eq!(startup_shortlist_snapshot(&mut c).await, json!([]));
    sqlx::query("UPDATE discovery_runs SET source='startup_manual'")
        .execute(&mut c)
        .await
        .unwrap();
    assert_eq!(
        startup_save(&mut c, company, json!({"run_id":run}))
            .await
            .unwrap()["created"],
        true
    );
    assert_eq!(
        startup_shortlist_snapshot(&mut c).await[0]["run_id"],
        run.to_string()
    );
}
