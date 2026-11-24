// Actual native DTO/selected-profile broker fixtures; no browser/provider side effects.
fn native_queue_context(work:&Value)->Value{json!({"profile_binding_id":work["binding"]["profile_binding_id"],"profile_secret":"f".repeat(64),"browser_session_id":work["binding"]["browser_session_id"],"window_id":work["binding"]["window_id"]})}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_supervised_saved_listing_precedes_due_profile_and_search_reads() {
    let (mut connection, binding, _) = sync_fixture(json!(["summary"])).await;
    let mut config = browser_pref(&mut connection, "application_queue_policy").await;
    let setting = &mut config["policy"]["platforms"]["naukri"];
    setting["mode"] = json!("SUPERVISED");
    setting["owner_submission_authorized"] = json!(true);
    setting["sources"] = json!(["saved_verified_job", "naukri_ui_search"]);
    browser_save(&mut connection, "application_queue_policy", config).await;

    let listing = automated_apply_agents::execution::queue::enqueue(
        &mut connection,
        "https://www.naukri.com/job-listings-fictional-backend-engineer-0123456789",
        "saved_verified_job",
        None,
    )
    .await
    .unwrap();
    let context = native_queue_context(&json!({"binding": binding}));
    let poll = native_queue_call(
        &mut connection,
        &context,
        "poll_naukri_work",
        json!({}),
        &sync_resume_settings(),
    )
    .await
    .unwrap();
    let work = &poll["data"]["work"];
    assert_eq!(work["id"], listing["id"], "{poll}");
    assert_eq!(work["operation"], "inspect_job");
    assert_eq!(poll["data"]["submitted"], false);
    let reserved: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM owner_preferences WHERE starts_with(key, 'apply_budget:')",
    )
    .fetch_one(&mut connection)
    .await
    .unwrap();
    assert_eq!(reserved, 0);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_supervised_100_plus_scope_claims_only_its_listing_and_stop_clears_it() {
    let (mut connection, binding, _) = sync_fixture(json!(["summary"])).await;
    let mut config = browser_pref(&mut connection, "application_queue_policy").await;
    config["state"] = json!("STOPPED");
    config["policy"]["global_limits"]["applicant_limit"] = json!(1000);
    config["policy"]["global_limits"]["unknown_applicants"] = json!("needs_review");
    let setting = &mut config["policy"]["platforms"]["naukri"];
    setting["mode"] = json!("SUPERVISED");
    setting["owner_submission_authorized"] = json!(true);
    setting["sources"] = json!(["saved_verified_job", "naukri_ui_search"]);
    setting["hourly_submission_cap"] = json!(1);
    setting["supervised_submission_cap"] = json!(1);
    browser_save(&mut connection, "application_queue_policy", config.clone()).await;
    sqlx::query("UPDATE rust_agent_control SET mode='STOPPED'")
        .execute(&mut connection)
        .await
        .unwrap();
    browser_save(
        &mut connection,
        "chr_fixed_profile",
        json!({
            "profile_binding_id":binding["profile_binding_id"],"browser":"brave",
            "verified_via":"owner_reviewed_dedicated_brave_profile"
        }),
    )
    .await;

    let mut listings = Vec::new();
    for url in [
        "https://www.naukri.com/job-listings-fictional-backend-engineer-0123456789",
        "https://www.naukri.com/job-listings-fictional-backend-engineer-1123456789",
    ] {
        listings.push(
            automated_apply_agents::execution::queue::enqueue(
                &mut connection,
                url,
                "saved_verified_job",
                None,
            )
            .await
            .unwrap(),
        );
    }
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let path = directory.path().join("runtime.env");
    std::fs::write(
        &path,
        browser_values().iter().map(|(key, value)| format!("{key}='{value}'\n")).collect::<String>(),
    )
    .unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
    let launch = |revision: i64| {
        let path = &path;
        let url = listings[1]["url"].as_str().unwrap();
        async move {
            tokio::time::timeout(
                Duration::from_secs(10),
                tokio::process::Command::new(env!("CARGO_BIN_EXE_automated-apply-agents"))
                    .args(["start-supervised-naukri-listing", "--config"])
                    .arg(path)
                    .args(["--queue-revision", &revision.to_string(), "--listing", url])
                    .env_clear()
                    .kill_on_drop(true)
                    .output(),
            )
            .await
            .unwrap()
            .unwrap()
        }
    };
    let revision = config["revision"].as_i64().unwrap();
    let stale = launch(revision - 1).await;
    assert!(!stale.status.success());
    assert_eq!(String::from_utf8_lossy(&stale.stderr).trim(), "queue_policy_revision_conflict");
    let started = launch(revision).await;
    assert!(started.status.success(), "{}", String::from_utf8_lossy(&started.stderr));
    let started: Value = serde_json::from_slice(&started.stdout).unwrap();
    assert_eq!(started["scope"]["work_id"], listings[1]["id"]);
    assert_eq!(started["application_dispatched"], false);
    let context = native_queue_context(&json!({"binding": binding}));
    let resumes = sync_resume_settings();
    let result = native_queue_call(&mut connection, &context, "poll_naukri_work", json!({}), &resumes)
        .await
        .unwrap();
    assert_eq!(result["data"]["work"]["id"], listings[1]["id"], "{result}");
    assert_eq!(result["data"]["work"]["operation"], "inspect_job");
    let unrelated_key = format!("apply_work:{}", listings[0]["id"].as_str().unwrap());
    assert_eq!(browser_pref(&mut connection, &unrelated_key).await, listings[0]);
    let stopped = native_queue_call(
        &mut connection,
        &context,
        "naukri_queue_control",
        json!({"queue_action":"stop","expected_queue_revision":started["revision"]}),
        &resumes,
    )
    .await
    .unwrap();
    assert_eq!(stopped["data"]["queue"]["state"], "STOPPED", "{stopped}");
    let saved = browser_pref(&mut connection, "application_queue_policy").await;
    assert!(saved.get("supervised_100_plus").is_none());
    assert_eq!(saved["policy"], config["policy"]);
    let stale = native_queue_call(
        &mut connection,
        &context,
        "bind_naukri_work",
        native_queue_step(&result["data"]["work"]),
        &resumes,
    )
    .await
    .unwrap();
    assert_eq!(stale["error_code"], "queue_lease_lost");
}
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_supervised_prepared_resume_preserves_quarantine_and_requires_fresh_profile_read()
 {
    use sha2::Digest;
    let (mut connection, job) = packet_service_fixture().await;
    sqlx::raw_sql(
        "DROP TABLE IF EXISTS private_resumes;
         CREATE TABLE private_resumes(id uuid PRIMARY KEY,ciphertext bytea NOT NULL,
            sha256 varchar(64) NOT NULL,confirmed bool NOT NULL,resource_id uuid NOT NULL)",
    )
    .execute(&mut connection)
    .await
    .unwrap();
    let corpus: Value = serde_json::from_str(include_str!(
        "../../../document-worker/tests/fixtures/pdf-corpus.json"
    ))
    .unwrap();
    let pdf: Vec<u8> = serde_json::from_value(
        corpus["pdfs"]
            .as_array()
            .unwrap()
            .iter()
            .find(|entry| entry["name"] == "text")
            .unwrap()["bytes"]
            .clone(),
    )
    .unwrap();
    let encryption_key = corpus["fernet"]["key"].as_str().unwrap();
    let hash = format!("{:x}", sha2::Sha256::digest(&pdf));
    let encrypted = fernet::Fernet::new(encryption_key).unwrap().encrypt(&pdf);
    let resume = Uuid::new_v4();
    let resource: Uuid = sqlx::query_scalar(
        "UPDATE candidate_resources SET source_type='private_upload',url=$1
         WHERE resource_type='resume' RETURNING id",
    )
    .bind(format!("private-resume:{resume}"))
    .fetch_one(&mut connection)
    .await
    .unwrap();
    sqlx::query("INSERT INTO private_resumes VALUES($1,$2,$3,true,$4)")
        .bind(resume)
        .bind(encrypted.as_bytes())
        .bind(&hash)
        .bind(resource)
        .execute(&mut connection)
        .await
        .unwrap();
    sqlx::query(
        "UPDATE candidate_profiles SET phone='+919876543210',
            preferences=preferences||'{\"target_titles\":[\"Rust Engineer\"]}'::jsonb
         WHERE singleton_key='primary'",
    )
    .execute(&mut connection)
    .await
    .unwrap();
    sqlx::query(
        "UPDATE jobs SET date_posted=clock_timestamp()-interval '2 days',
            discovery_metadata=discovery_metadata||'{\"experience_min_years\":0,\"experience_max_years\":1}'::jsonb
         WHERE id=$1",
    ).bind(job).execute(&mut connection).await.unwrap();

    let packet = packet_create(
        &mut connection,
        job,
        "fictional-interrupted-read",
        json!([]),
    )
    .await
    .unwrap();
    browser_save(
        &mut connection,
        "phase1_profile_confirmation",
        json!({
            "profile_id":packet["candidate_profile_id"],
            "profile_version":packet["candidate_profile_version"],
            "confirmed_at":"2026-11-16T00:00:00Z"
        }),
    )
    .await;
    let context = browser_context();
    browser_connect(&mut connection, &context).await;
    browser_call(
        &mut connection,
        BrowserRoute::Select,
        json!({
            "expected_version":0,"profile_binding_id":context["profile_binding_id"]
        }),
    )
    .await
    .unwrap();
    browser_native(
        &mut connection,
        "heartbeat_chrome_profile",
        &context,
        json!({"profile_commands_enabled":true}),
    )
    .await
    .unwrap();
    let mut config = execution_running(&mut connection).await;
    execution_mutate(
        &mut connection,
        automated_apply_agents::execution::Route::AccountApproval,
        account_input(&context, &packet),
    )
    .await
    .unwrap();
    let account = browser_pref(&mut connection, "naukri_account_binding").await;
    config["state"] = json!("STOPPED");
    config["policy"]["platforms"]["naukri"]["sources"] = json!(["saved_verified_job"]);
    browser_save(&mut connection, "application_queue_policy", config.clone()).await;
    browser_save(
        &mut connection,
        "chr_fixed_profile",
        json!({
            "profile_binding_id":context["profile_binding_id"],"browser":"brave",
            "verified_via":"owner_reviewed_dedicated_brave_profile"
        }),
    )
    .await;
    sqlx::query("UPDATE rust_agent_control SET mode='STOPPED'")
        .execute(&mut connection)
        .await
        .unwrap();

    let mut work = execution_enqueue(&mut connection, "123456789012").await;
    let work_id = work["id"].as_str().unwrap().to_owned();
    let work_key = format!("apply_work:{work_id}");
    let at: Value = sqlx::query_scalar("SELECT to_jsonb(clock_timestamp()-interval '2 days')")
        .fetch_one(&mut connection)
        .await
        .unwrap();
    work["job_id"] = json!(job);
    work["packet_id"] = packet["id"].clone();
    work["packet_revision"] = packet["revision"].clone();
    work["candidate_profile_id"] = packet["candidate_profile_id"].clone();
    work["profile_version"] = packet["candidate_profile_version"].clone();
    work["account_binding_revision"] = account["revision"].clone();
    work["account_sha256"] = account["account_sha256"].clone();
    work["title"] = json!("Rust Engineer");
    work["company"] = json!("Fictional Labs");
    work["facts"] = json!({"posted_at":at,"applicants_min":100,"applicants_max":null});
    work["stage"] = json!("PAUSED");
    work["status"] = json!("waiting");
    work["reason"] = json!("global_stop");
    work["operation"] = json!("inspect_profile");
    work["revision"] = json!(36);
    work["paused_context"] = json!({
        "stage":"FAILED_RETRYABLE","status":"executing","operation":"inspect_profile","reason":"lease_expired"
    });
    browser_save(&mut connection, &work_key, work.clone()).await;

    let mut historical = Vec::new();
    let mut reservations = Vec::new();
    for requisition in ["223456789012", "323456789012", "423456789012"] {
        let mut quarantine = execution_enqueue(&mut connection, requisition).await;
        let key = format!("apply_work:{}", quarantine["id"].as_str().unwrap());
        reservations.push(quarantine["id"].clone());
        quarantine["stage"] = json!("SUBMISSION_UNKNOWN");
        quarantine["status"] = json!("unknown");
        quarantine["account_sha256"] = account["account_sha256"].clone();
        quarantine["form_pending"] = json!(true);
        quarantine["admitted_actions"] = json!([
            {"id":Uuid::new_v4(),"fingerprint":"apply:fictional","at":at}
        ]);
        browser_save(&mut connection, &key, quarantine.clone()).await;
        historical.push((key, quarantine));
    }
    let budget_key = "apply_budget:naukri:2000-01-01";
    let budget = json!({"reservations":reservations});
    browser_save(&mut connection, budget_key, budget.clone()).await;

    let mut expired = execution_enqueue(&mut connection, "523456789012").await;
    let expired_key = format!("apply_work:{}", expired["id"].as_str().unwrap());
    expired["status"] = json!("leased");
    expired["lease_until"] = at.clone();
    expired["lease_token"] = json!(Uuid::new_v4());
    browser_save(&mut connection, &expired_key, expired.clone()).await;

    let mut values = browser_values();
    values.insert("RESUME_ENCRYPTION_KEY".into(), encryption_key.into());
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let path = directory.path().join("runtime.env");
    let input = values
        .iter()
        .map(|(key, value)| format!("{key}='{value}'\n"))
        .collect::<String>();
    std::fs::write(&path, input).unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
    let launch = |queue_revision: i64, work_revision: i64| {
        let path = &path;
        let work_id = &work_id;
        async move {
            tokio::time::timeout(
                Duration::from_secs(10),
                tokio::process::Command::new(env!("CARGO_BIN_EXE_automated-apply-agents"))
                    .args(["resume-supervised-naukri-listing", "--config"])
                    .arg(path)
                    .args([
                        "--queue-revision",
                        &queue_revision.to_string(),
                        "--work-id",
                        work_id,
                        "--work-revision",
                        &work_revision.to_string(),
                    ])
                    .env_clear()
                    .kill_on_drop(true)
                    .output(),
            )
            .await
            .unwrap()
            .unwrap()
        }
    };
    let revision = config["revision"].as_i64().unwrap();
    for (queue_rev, work_rev, expected) in [
        (revision - 1, 36, "queue_policy_revision_conflict"),
        (revision, 35, "queue_work_revision_conflict"),
    ] {
        let denied = launch(queue_rev, work_rev).await;
        assert!(!denied.status.success());
        assert_eq!(String::from_utf8_lossy(&denied.stderr).trim(), expected);
    }
    let mut possible_form = work.clone();
    possible_form["form_binding"] = json!({"tab_id":50});
    browser_save(&mut connection, &work_key, possible_form.clone()).await;
    let denied = launch(revision, 36).await;
    assert!(!denied.status.success());
    assert_eq!(
        String::from_utf8_lossy(&denied.stderr).trim(),
        "interrupted_prepared_supervised_listing_required"
    );
    assert_eq!(
        browser_pref(&mut connection, &work_key).await,
        possible_form
    );
    assert_eq!(
        browser_pref(&mut connection, "application_queue_policy").await,
        config
    );
    browser_save(&mut connection, &work_key, work.clone()).await;

    let resumed = launch(revision, 36).await;
    assert!(
        resumed.status.success(),
        "{}",
        String::from_utf8_lossy(&resumed.stderr)
    );
    let resumed: Value = serde_json::from_slice(&resumed.stdout).unwrap();
    assert_eq!(resumed["scope"]["work_id"], work_id);
    assert_eq!(resumed["revision"], revision + 1);
    assert_eq!(resumed["application_dispatched"], false);
    let saved = browser_pref(&mut connection, &work_key).await;
    assert_eq!(saved["packet_id"], packet["id"]);
    assert_eq!(saved["packet_revision"], packet["revision"]);
    assert_eq!(saved["revision"], 37);
    assert_eq!(saved["upload_preflight"]["sha256"], hash);
    assert_eq!(saved["stage"], "READY_TO_APPLY");
    assert_eq!(saved["operation"], "inspect_profile");
    assert!(saved["account_observation"].is_null());

    let settings = automated_apply_agents::private_resume::Settings::from_values(&values).unwrap();
    let poll = native_queue_call(
        &mut connection,
        &context,
        "poll_naukri_work",
        json!({}),
        &settings,
    )
    .await
    .unwrap();
    assert_eq!(poll["data"]["work"]["id"], work_id, "{poll}");
    assert_eq!(poll["data"]["work"]["operation"], "inspect_profile");
    assert_eq!(poll["data"]["submitted"], false);
    for (key, quarantine) in historical {
        assert_eq!(browser_pref(&mut connection, &key).await, quarantine);
    }
    assert_eq!(browser_pref(&mut connection, &expired_key).await, expired);
    assert_eq!(browser_pref(&mut connection, budget_key).await, budget);
    assert_eq!(
        browser_pref(&mut connection, &work_key).await["admitted_actions"],
        json!([])
    );
}

async fn native_queue_call(c:&mut PgConnection,context:&Value,name:&str,extra:Value,resumes:&automated_apply_agents::private_resume::Settings)->Result<Value>{let mut command=context.clone();command["command"]=json!(name);command["request_id"]=json!(Uuid::new_v4());for(k,v)in extra.as_object().unwrap(){command[k]=v.clone();}let settings=browser_profiles::Settings::from_values(&browser_values()).unwrap();let answers=answer_settings();browser_profiles::dispatch(c,BrowserRoute::Native,"POST",command.to_string().as_bytes(),&settings,&packet_settings(),Some(browser_profiles::form_service::Services{answers:&answers,resumes})).await}
fn native_queue_step(work:&Value)->Value{json!({"work_id":work["id"],"expected_work_revision":work["revision"],"work_lease_token":work["lease_token"],"tab_id":50})}
async fn native_queue_fixture()->(PgConnection,Value,Value){let(mut c,inspection)=listing_fixture().await;execution_mutate(&mut c,automated_apply_agents::execution::Route::SyncPolicy,json!({"expected_revision":1,"policy":{"enabled":false}})).await.unwrap();let context=native_queue_context(&inspection);let mut queued=inspection.clone();queued["status"]=json!("queued");queued["lease_token"]=Value::Null;queued["lease_until"]=Value::Null;queued["binding"]=Value::Null;browser_save(&mut c,&format!("apply_work:{}",inspection["id"].as_str().unwrap()),queued).await;(c,context,inspection)}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_poll_reports_confirmed_owner_fence_rollback() {
    let (mut c, mut input, inspection) = native_queue_fixture().await;
    let (url, stop, server) = http_fixture_values(browser_values()).await;
    let http = client();
    let endpoint = format!("{url}{}", browser_profiles::NATIVE);
    input["command"] = json!("poll_naukri_work");
    input["request_id"] = json!(Uuid::new_v4());
    let poll = || {
        http.post(&endpoint)
            .bearer_auth(HOST_TOKEN)
            .header("x-agent-client", BROWSER_EXTENSION)
            .timeout(Duration::from_secs(6))
            .json(&input)
    };

    let before = browser_snapshot(&mut c).await;
    let mut owner = connection().await;
    let mut held = owner.begin().await.unwrap();
    sqlx::query("SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE")
        .execute(&mut *held)
        .await
        .unwrap();
    let response = poll().send().await.unwrap();
    assert_eq!(response.status(), 503);
    assert_eq!(
        response
            .headers()
            .get("x-automated-apply-transaction")
            .and_then(|value| value.to_str().ok()),
        Some("rolled-back"),
    );
    assert_eq!(
        response.json::<Value>().await.unwrap()["detail"],
        "native_poll_owner_fence_rolled_back"
    );
    assert_eq!(browser_snapshot(&mut c).await, before);
    held.rollback().await.unwrap();

    let response = poll().send().await.unwrap();
    assert_eq!(response.status(), 200);
    assert!(!response.headers().contains_key("x-automated-apply-transaction"));
    let result: Value = response.json().await.unwrap();
    assert_eq!(result["request_id"], input["request_id"]);
    assert_eq!(result["data"]["work"]["id"], inspection["id"]);
    assert_eq!(result["data"]["work"]["status"], "leased");
    assert_eq!(result["data"]["submitted"], false);
    let key = format!("apply_work:{}", inspection["id"].as_str().unwrap());
    assert_eq!(browser_pref(&mut c, &key).await["admitted_actions"], json!([]));
    let reservations: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM owner_preferences WHERE starts_with(key,'apply_budget:')",
    )
    .fetch_one(&mut c)
    .await
    .unwrap();
    assert_eq!(reservations, 0);
    stop.cancel();
    server.await.unwrap();
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_terminal_reports_confirmed_owner_fence_rollback() {
    let (mut c, input, inspection) = native_queue_fixture().await;
    let resumes = sync_resume_settings();
    let poll = native_queue_call(&mut c, &input, "poll_naukri_work", json!({}), &resumes)
        .await
        .unwrap();
    let bound = native_queue_call(
        &mut c,
        &input,
        "bind_naukri_work",
        native_queue_step(&poll["data"]["work"]),
        &resumes,
    )
    .await
    .unwrap();
    let admitted = native_queue_call(
        &mut c,
        &input,
        "admit_naukri_work",
        native_queue_step(&bound["data"]["work"]),
        &resumes,
    )
    .await
    .unwrap();
    let work = &admitted["data"]["work"];
    assert_eq!(work["id"], inspection["id"]);
    assert_eq!(work["status"], "executing");

    let (url, stop, server) = http_fixture_values(browser_values()).await;
    let http = client();
    let endpoint = format!("{url}{}", browser_profiles::NATIVE);
    let terminal = |name, report| {
        let mut command = input.clone();
        for (key, value) in native_queue_step(work).as_object().unwrap() {
            command[key] = value.clone();
        }
        command["command"] = json!(name);
        command["request_id"] = json!(Uuid::new_v4());
        command["work_report"] = report;
        command
    };
    let finish = terminal("finish_naukri_work", listing_report(work));
    let abandon = terminal(
        "abandon_naukri_work",
        json!({"kind":"needs_input","reason":"background_observation_failed"}),
    );
    let request = |input: &Value| {
        http.post(&endpoint)
            .bearer_auth(HOST_TOKEN)
            .header("x-agent-client", BROWSER_EXTENSION)
            .timeout(Duration::from_secs(6))
            .json(input)
    };

    let before = browser_snapshot(&mut c).await;
    let mut owner = connection().await;
    let mut held = owner.begin().await.unwrap();
    sqlx::query(
        "SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE",
    )
    .execute(&mut *held)
    .await
    .unwrap();
    for command in [&finish, &abandon] {
        let response = request(command).send().await.unwrap();
        assert_eq!(response.status(), 503);
        assert_eq!(
            response
                .headers()
                .get("x-automated-apply-transaction")
                .and_then(|value| value.to_str().ok()),
            Some("rolled-back"),
        );
        assert_eq!(
            response.json::<Value>().await.unwrap()["detail"],
            "native_terminal_owner_fence_rolled_back"
        );
        assert_eq!(browser_snapshot(&mut c).await, before);
    }
    held.rollback().await.unwrap();

    let response = request(&finish).send().await.unwrap();
    assert_eq!(response.status(), 200);
    assert!(
        !response
            .headers()
            .contains_key("x-automated-apply-transaction")
    );
    let result: Value = response.json().await.unwrap();
    assert_eq!(result["request_id"], finish["request_id"]);
    assert_eq!(result["data"]["work"]["id"], inspection["id"]);
    assert_eq!(result["data"]["work"]["operation"], "prepare");
    assert_eq!(result["data"]["submitted"], false);
    stop.cancel();
    server.await.unwrap();
}

#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_poll_bind_read_admit_check_and_listing_finish_use_actual_authenticated_contract(){
    let(mut c,context,_)=native_queue_fixture().await;let resumes=sync_resume_settings();let poll=native_queue_call(&mut c,&context,"poll_naukri_work",json!({}),&resumes).await.unwrap();assert_eq!(poll["ok"],true,"{poll}");let work=&poll["data"]["work"];assert_eq!(work["operation"],"inspect_job");assert!(work["binding"]["tab_id"].is_null());let bound=native_queue_call(&mut c,&context,"bind_naukri_work",native_queue_step(work),&resumes).await.unwrap();assert_eq!(bound["ok"],true,"{bound}");let work=&bound["data"]["work"];assert_eq!(work["binding"]["tab_id"],50);let admitted=native_queue_call(&mut c,&context,"admit_naukri_work",native_queue_step(work),&resumes).await.unwrap();assert_eq!(admitted["ok"],true,"{admitted}");let work=&admitted["data"]["work"];assert_eq!(work["status"],"executing");let check=native_queue_call(&mut c,&context,"check_naukri_work",native_queue_step(work),&resumes).await.unwrap();assert_eq!(check["data"]["work"]["revision"],work["revision"]);let mut finish=native_queue_step(work);finish["work_report"]=listing_report(work);let finished=native_queue_call(&mut c,&context,"finish_naukri_work",finish,&resumes).await.unwrap();assert_eq!(finished["ok"],true,"{finished}");assert_eq!(finished["data"]["continue"],false);assert_eq!(finished["data"]["work"]["operation"],"prepare");assert_eq!(finished["data"]["work"]["status"],"queued");assert_eq!(finished["data"]["submitted"],false);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'apply_budget:')").fetch_one(&mut c).await.unwrap(),0);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_status_is_read_only_under_owner_lock_and_retains_secret_and_history_redaction(){
    let(mut c,context,_)=native_queue_fixture().await;let resumes=sync_resume_settings();let before=browser_snapshot(&mut c).await;let mut other=connection().await;let mut held=other.begin().await.unwrap();sqlx::query("SELECT key FROM owner_preferences WHERE key='agent_conversation:primary' FOR UPDATE").execute(&mut *held).await.unwrap();sqlx::query("SET lock_timeout='100ms'").execute(&mut c).await.unwrap();let status=native_queue_call(&mut c,&context,"naukri_queue_status",json!({}),&resumes).await.unwrap();assert_eq!(status["ok"],true,"{status}");assert_eq!(status["capability"],"naukri_queue_controls");assert_eq!(status["data"]["queue"]["state"],"RUNNING");assert!(!status.to_string().contains(&"f".repeat(64)));assert!(!status.to_string().contains("Fictional development role"));assert_eq!(browser_snapshot(&mut c).await,before);held.rollback().await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_wrong_secret_session_window_or_tab_does_not_claim_any_work(){
    let(mut c,context,_)=native_queue_fixture().await;let resumes=sync_resume_settings();let before=browser_snapshot(&mut c).await;
    for(field,value,error)in[("profile_secret",json!("e".repeat(64)),"PROFILE_OFFLINE"),("browser_session_id",json!(Uuid::new_v4()),"PROFILE_SESSION_CHANGED"),("window_id",json!(11),"queue_window_binding_changed"),("tab_id",json!(50),"queue_poll_without_tab_required")]{let mut extra=json!({});extra[field]=value;let result=native_queue_call(&mut c,&context,"poll_naukri_work",extra,&resumes).await.unwrap();assert_eq!(result["ok"],false,"{result}");assert_eq!(result["error_code"],error);assert_eq!(browser_snapshot(&mut c).await,before);}
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_stop_revokes_an_issued_lease_and_stale_admit_cannot_spend_budget(){
    let(mut c,context,_)=native_queue_fixture().await;let resumes=sync_resume_settings();let work=native_queue_call(&mut c,&context,"poll_naukri_work",json!({}),&resumes).await.unwrap()["data"]["work"].clone();let stopped=native_queue_call(&mut c,&context,"naukri_queue_control",json!({"queue_action":"stop","expected_queue_revision":162}),&resumes).await.unwrap();assert_eq!(stopped["ok"],true,"{stopped}");assert_eq!(stopped["data"]["queue"]["state"],"STOPPED");let before=browser_snapshot(&mut c).await;let stale=native_queue_call(&mut c,&context,"bind_naukri_work",native_queue_step(&work),&resumes).await.unwrap();assert_eq!(stale["error_code"],"queue_lease_lost");assert_eq!(browser_snapshot(&mut c).await,before);assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'apply_budget:')").fetch_one(&mut c).await.unwrap(),0);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_poll_yields_to_legacy_work_and_an_existing_active_lease(){
    let(mut c,context,_)=native_queue_fixture().await;let resumes=sync_resume_settings();browser_save(&mut c,"chr_cmd:fictional-busy",json!({"state":"executing"})).await;let busy=native_queue_call(&mut c,&context,"poll_naukri_work",json!({}),&resumes).await.unwrap();assert!(busy["data"]["work"].is_null());assert_eq!(browser_pref(&mut c,"apply_consumer:naukri").await["busy"],true);browser_save(&mut c,"chr_cmd:fictional-busy",json!({"state":"completed"})).await;let claimed=native_queue_call(&mut c,&context,"poll_naukri_work",json!({}),&resumes).await.unwrap();assert!(claimed["data"]["work"].is_object());let again=native_queue_call(&mut c,&context,"poll_naukri_work",json!({}),&resumes).await.unwrap();assert!(again["data"]["work"].is_null());assert_eq!(browser_pref(&mut c,"apply_consumer:naukri").await["busy"],true);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_abandon_of_an_unattempted_read_preserves_backoff_and_cannot_become_an_apply(){
    let(mut c,context,_)=native_queue_fixture().await;let resumes=sync_resume_settings();let poll=native_queue_call(&mut c,&context,"poll_naukri_work",json!({}),&resumes).await.unwrap();let bound=native_queue_call(&mut c,&context,"bind_naukri_work",native_queue_step(&poll["data"]["work"]),&resumes).await.unwrap();let mut fields=native_queue_step(&bound["data"]["work"]);fields["work_report"]=json!({"kind":"needs_input","reason":"owner_platform_active"});let result=native_queue_call(&mut c,&context,"abandon_naukri_work",fields,&resumes).await.unwrap();assert_eq!(result["ok"],true,"{result}");assert_eq!(result["data"]["work"]["operation"],"inspect_job");assert_eq!(result["data"]["work"]["status"],"queued");let work=browser_pref(&mut c,&format!("apply_work:{}",result["data"]["work"]["id"].as_str().unwrap())).await;assert_eq!(work["admitted_actions"],json!([]));assert!(work["available_at"].is_string());
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_original_tab_loss_under_stop_closes_questions_and_never_refunds_or_replays_apply(){
    let(mut c,work,q,resumes)=queue_question_fixture().await;let context=native_queue_context(&work);let key=format!("apply_work:{}",work["id"].as_str().unwrap());let mut pending=work.clone();pending["form_pending"]=json!(true);browser_save(&mut c,&key,pending).await;let mut config=browser_pref(&mut c,"application_queue_policy").await;config["state"]=json!("STOPPED");browser_save(&mut c,"application_queue_policy",config).await;let extra=json!({"work_id":work["id"],"tab_id":50,"work_report":{"kind":"needs_input","reason":"original_questionnaire_tab_unavailable"}});let result=native_queue_call(&mut c,&context,"poll_naukri_work",extra.clone(),&resumes).await.unwrap();assert_eq!(result["ok"],true,"{result}");assert_eq!(result["data"]["form_loss_recorded"],true);assert_eq!(result["data"]["state_changed"],true);let lost=browser_pref(&mut c,&key).await;assert_eq!(lost["status"],"unknown");assert_eq!(lost["stage"],"SUBMISSION_UNKNOWN");assert_eq!(lost["admitted_actions"],work["admitted_actions"]);assert_eq!(lost["form_loss_observation"]["replay_authorized"],false);assert_eq!(browser_pref(&mut c,&format!("exec_q:{}",q["id"].as_str().unwrap())).await["state"],"closed_form_unavailable");let duplicate=native_queue_call(&mut c,&context,"poll_naukri_work",extra,&resumes).await.unwrap();assert_eq!(duplicate["data"]["state_changed"],false);assert_eq!(browser_pref(&mut c,&key).await,lost);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_suspended_webui_request_and_windowless_binding_never_return_navigation_authority(){
    let(mut c,context,_)=native_queue_fixture().await;let resumes=sync_resume_settings();let mut config=browser_pref(&mut c,"application_queue_policy").await;config["state"]=json!("STOPPED");browser_save(&mut c,"application_queue_policy",config).await;let metadata=json!({"kind":"open_extension_manager","request_id":Uuid::new_v4(),"expires_at":(chrono::Utc::now()+chrono::Duration::seconds(90)).to_rfc3339(),"binding":{"profile_binding_id":context["profile_binding_id"],"profile_version":2,"selection_version":1,"browser_session_id":context["browser_session_id"],"window_id":10,"tab_id":null}});browser_save(&mut c,"naukri_extension_maintenance",metadata.clone()).await;let result=native_queue_call(&mut c,&context,"poll_naukri_work",json!({}),&resumes).await.unwrap();assert_eq!(result["ok"],true,"{result}");assert!(result["data"]["maintenance"].is_null());assert!(result["data"]["work"].is_null());assert_eq!(browser_pref(&mut c,"naukri_extension_maintenance").await,metadata);let windowless=native_queue_call(&mut c,&context,"poll_naukri_work",json!({"window_id":null}),&resumes).await.unwrap();assert_eq!(windowless["error_code"],"queue_window_binding_changed");assert_eq!(browser_pref(&mut c,"naukri_extension_maintenance").await,metadata);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_dropped_work_ack_rolls_back_whole_poll_and_consumer_metadata(){
    let(mut c,context,_)=native_queue_fixture().await;let resumes=sync_resume_settings();let before=browser_snapshot(&mut c).await;sqlx::raw_sql("CREATE FUNCTION fixture_native_claim_drop() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF starts_with(NEW.key,'apply_work:') AND NEW.value->>'status'='leased' THEN RETURN NULL; END IF; RETURN NEW; END $$;CREATE TRIGGER fixture_native_claim_drop BEFORE UPDATE ON owner_preferences FOR EACH ROW EXECUTE FUNCTION fixture_native_claim_drop()").execute(&mut c).await.unwrap();assert_eq!(native_queue_call(&mut c,&context,"poll_naukri_work",json!({}),&resumes).await.unwrap_err(),Failure("execution_write_ack_failed"));assert_eq!(browser_snapshot(&mut c).await,before);sqlx::raw_sql("DROP TRIGGER fixture_native_claim_drop ON owner_preferences;DROP FUNCTION fixture_native_claim_drop()").execute(&mut c).await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_http_requires_host_auth_and_exact_configured_extension_before_queue_status(){
    let(_c,context,_)=native_queue_fixture().await;let(url,stop,server)=http_fixture_values(browser_values()).await;let endpoint=format!("{url}{}",browser_profiles::NATIVE);let mut command=context;command["request_id"]=json!(Uuid::new_v4());command["command"]=json!("naukri_queue_status");let http=client();assert_eq!(http.post(&endpoint).json(&command).send().await.unwrap().status(),403);assert_eq!(http.post(&endpoint).header("x-agent-client",BROWSER_EXTENSION).json(&command).send().await.unwrap().status(),401);assert_eq!(http.post(&endpoint).bearer_auth(HOST_TOKEN).header("x-agent-client","bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb").json(&command).send().await.unwrap().status(),403);let result=http.post(&endpoint).bearer_auth(HOST_TOKEN).header("x-agent-client",BROWSER_EXTENSION).json(&command).send().await.unwrap();assert_eq!(result.status(),200);let body:Value=result.json().await.unwrap();assert_eq!(body["ok"],true,"{body}");assert_eq!(body["data"]["queue"]["revision"],162);assert_eq!(body["data"]["submitted"],false);stop.cancel();server.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_automatic_start_still_requires_first_strict_current_worker_receipt(){
    let(mut c,context,_)=native_queue_fixture().await;let resumes=sync_resume_settings();let mut config=browser_pref(&mut c,"application_queue_policy").await;config["state"]=json!("STOPPED");config["policy"]["platforms"]["naukri"]["mode"]=json!("AUTOMATIC");browser_save(&mut c,"application_queue_policy",config).await;let before=browser_snapshot(&mut c).await;let denied=native_queue_call(&mut c,&context,"naukri_queue_control",json!({"queue_action":"start","expected_queue_revision":162}),&resumes).await.unwrap();assert_eq!(denied["error_code"],"automatic_first_verified_worker_receipt_required");assert_eq!(browser_snapshot(&mut c).await,before);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_profile_save_still_requires_durable_unknown_intent_and_independent_persistence_read(){
    let(mut c,binding,profile)=sync_fixture(json!(["summary"])).await;let synthetic=json!({"binding":binding});let context=native_queue_context(&synthetic);let resumes=sync_resume_settings();let poll=native_queue_call(&mut c,&context,"poll_naukri_work",json!({}),&resumes).await.unwrap();let work=&poll["data"]["work"];assert_eq!(work["operation"],"inspect_profile_sync");let bound=native_queue_call(&mut c,&context,"bind_naukri_work",native_queue_step(work),&resumes).await.unwrap();let admitted=native_queue_call(&mut c,&context,"admit_naukri_work",native_queue_step(&bound["data"]["work"]),&resumes).await.unwrap();let mut fields=native_queue_step(&admitted["data"]["work"]);fields["work_report"]=sync_report("PROFILE_OBSERVED","fictional-native-profile-one",json!({"summary":"Old fictional summary"}));let proposal=native_queue_call(&mut c,&context,"finish_naukri_work",fields,&resumes).await.unwrap();assert_eq!(proposal["ok"],true,"{proposal}");assert_eq!(proposal["data"]["work"]["operation"],"sync_profile");let save=native_queue_call(&mut c,&context,"admit_naukri_work",native_queue_step(&proposal["data"]["work"]),&resumes).await.unwrap();assert_eq!(save["ok"],true,"{save}");assert_eq!(browser_pref(&mut c,"apply_profile_sync:naukri").await["sync_attempt"]["outcome"],"UNKNOWN");assert_eq!(save["data"]["work"]["execution"]["approved_summary"],profile["summary"]);let mut fields=native_queue_step(&save["data"]["work"]);fields["work_report"]=sync_report("PROFILE_SAVE_ATTEMPTED","fictional-native-profile-one",json!({}));let reloading=native_queue_call(&mut c,&context,"finish_naukri_work",fields,&resumes).await.unwrap();let reading=native_queue_call(&mut c,&context,"admit_naukri_work",native_queue_step(&reloading["data"]["work"]),&resumes).await.unwrap();let mut fields=native_queue_step(&reading["data"]["work"]);fields["work_report"]=sync_report("PROFILE_OBSERVED","fictional-native-profile-two",json!({"summary":profile["summary"]}));let finished=native_queue_call(&mut c,&context,"finish_naukri_work",fields,&resumes).await.unwrap();assert_eq!(finished["ok"],true,"{finished}");assert_eq!(finished["data"]["continue"],false);assert_eq!(browser_pref(&mut c,"apply_profile_sync:naukri").await["previous_verified_attempt"]["outcome"],"SYNC_VERIFIED");assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM owner_preferences WHERE starts_with(key,'apply_budget:') OR starts_with(key,'naukri_worker_receipt:')").fetch_one(&mut c).await.unwrap(),0);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn naukri_native_abandon_attests_only_a_clean_leased_apply() {
    let (mut c, context, _) = native_queue_fixture().await;
    let resumes = sync_resume_settings();
    let polled = native_queue_call(&mut c, &context, "poll_naukri_work", json!({}), &resumes)
        .await
        .unwrap();
    let bound = native_queue_call(
        &mut c,
        &context,
        "bind_naukri_work",
        native_queue_step(&polled["data"]["work"]),
        &resumes,
    )
    .await
    .unwrap();
    let key = format!(
        "apply_work:{}",
        bound["data"]["work"]["id"].as_str().unwrap()
    );
    let mut leased = browser_pref(&mut c, &key).await;
    leased["operation"] = json!("apply");
    leased["stage"] = json!("READY_TO_APPLY");
    assert_eq!(leased["status"], "leased");
    assert_eq!(leased["admitted_actions"], json!([]));
    browser_save(&mut c, &key, leased.clone()).await;

    let mut report = native_queue_step(&leased);
    report["work_report"] = json!({"kind":"needs_input","reason":"provider_context_changed"});
    let finish = native_queue_call(
        &mut c,
        &context,
        "finish_naukri_work",
        report.clone(),
        &resumes,
    )
    .await
    .unwrap();
    assert_eq!(finish["error_code"], "queue_action_not_admitted");
    let mut stale = report.clone();
    stale["expected_work_revision"] = leased["revision"]
        .as_i64()
        .unwrap()
        .saturating_sub(1)
        .into();
    let denied = native_queue_call(&mut c, &context, "abandon_naukri_work", stale, &resumes)
        .await
        .unwrap();
    assert_eq!(denied["error_code"], "queue_lease_lost");
    assert_eq!(browser_pref(&mut c, &key).await, leased);

    let released = native_queue_call(
        &mut c,
        &context,
        "abandon_naukri_work",
        report.clone(),
        &resumes,
    )
    .await
    .unwrap();
    assert_eq!(released["ok"], true, "{released}");
    assert_eq!(released["data"]["unadmitted_apply_released"], true);
    assert_eq!(released["data"]["continue"], false);
    let saved = browser_pref(&mut c, &key).await;
    assert_eq!(saved["stage"], "BLOCKED_PLATFORM");
    assert_eq!(saved["status"], "waiting");
    assert_eq!(saved["reason"], "provider_context_changed");
    assert_eq!(
        saved["revision"].as_i64().unwrap(),
        leased["revision"].as_i64().unwrap() + 1
    );
    assert_eq!(saved["admitted_actions"], json!([]));
    assert!(saved["lease_token"].is_null());
    assert!(saved["lease_until"].is_null());

    for (index, (field, value)) in [
        ("stage", Some(json!("SUBMISSION_UNKNOWN"))),
        ("status", Some(json!("executing"))),
        (
            "admitted_actions",
            Some(json!([{"fingerprint":"apply:initial"}])),
        ),
        ("admitted_actions", Some(json!({}))),
        ("admitted_actions", None),
        ("form_pending", Some(json!(true))),
        ("form_binding", Some(json!({"tab_id":50}))),
        (
            "apply_dispatch_observation",
            Some(json!({"document_id":"fictional"})),
        ),
    ]
    .into_iter()
    .enumerate()
    {
        let mut uncertain = leased.clone();
        uncertain["revision"] = json!(leased["revision"].as_i64().unwrap() + 1 + index as i64);
        if let Some(value) = value {
            uncertain[field] = value;
        } else {
            uncertain.as_object_mut().unwrap().remove(field);
        }
        browser_save(&mut c, &key, uncertain.clone()).await;
        let mut report = report.clone();
        report["expected_work_revision"] = uncertain["revision"].clone();
        let abandoned =
            native_queue_call(&mut c, &context, "abandon_naukri_work", report, &resumes)
                .await
                .unwrap();
        assert_eq!(abandoned["ok"], true, "{abandoned}");
        assert!(abandoned["data"].get("unadmitted_apply_released").is_none());
        let saved = browser_pref(&mut c, &key).await;
        assert_eq!(saved["stage"], "SUBMISSION_UNKNOWN");
        assert_eq!(saved["status"], "unknown");
        assert_eq!(
            saved.get("admitted_actions"),
            uncertain.get("admitted_actions")
        );
        for evidence in ["form_pending", "form_binding", "apply_dispatch_observation"] {
            assert_eq!(saved.get(evidence), uncertain.get(evidence));
        }
    }
    let reservations: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM owner_preferences WHERE starts_with(key,'apply_budget:')",
    )
    .fetch_one(&mut c)
    .await
    .unwrap();
    assert_eq!(reservations, 0);
}
