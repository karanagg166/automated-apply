#[tokio::test(flavor = "current_thread")]
#[ignore = "requires dedicated disposable PostgreSQL harness"]
async fn cutover_cli_reads_only_stopped_controls_and_sanitizes_output() {
    let mut c = knowledge_fixture().await;
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let path = directory.path().join("runtime.env");
    std::fs::write(
        &path,
        host_values()
            .iter()
            .map(|(key, value)| format!("{key}='{value}'\n"))
            .collect::<String>(),
    )
    .unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
    let preflight = || async {
        tokio::time::timeout(
            Duration::from_secs(10),
            tokio::process::Command::new(env!("CARGO_BIN_EXE_automated-apply-agents"))
                .args(["cutover-preflight", "--config"])
                .arg(&path)
                .env_clear()
                .kill_on_drop(true)
                .output(),
        )
        .await
        .unwrap()
        .unwrap()
    };
    let expect_refusal = |result: std::process::Output, code: &str| {
        assert!(!result.status.success());
        assert!(result.stdout.is_empty());
        assert_eq!(String::from_utf8(result.stderr).unwrap().trim(), code);
    };

    expect_refusal(
        preflight().await,
        "cutover_stopped_rust_coordinator_required",
    );
    lifecycle::set_control(&mut c, 1, Mode::Stopped)
        .await
        .unwrap();
    expect_refusal(
        preflight().await,
        "cutover_stopped_application_queue_required",
    );
    sqlx::query("INSERT INTO owner_preferences VALUES ('application_queue_policy',$1)")
        .bind(json!({"state":"STOPPED","revision":162,"policy":{"private":"fictional-cutover-canary"}}))
        .execute(&mut c)
        .await
        .unwrap();
    let absent = preflight().await;
    assert!(absent.status.success());
    let report: Value = serde_json::from_slice(&absent.stdout).unwrap();
    assert!(report["legacy_preparation_revision"].is_null());
    sqlx::query("INSERT INTO owner_preferences VALUES ('naukri_automation',$1)")
        .bind(json!({"state":"RUNNING","revision":11}))
        .execute(&mut c)
        .await
        .unwrap();
    expect_refusal(
        preflight().await,
        "cutover_stopped_legacy_preparation_required",
    );
    for (revision, accepted) in [(json!("12"), false), (json!(12), true)] {
        sqlx::query("UPDATE owner_preferences SET value=$1 WHERE key='naukri_automation'")
            .bind(json!({"state":"STOPPED","revision":revision}))
            .execute(&mut c)
            .await
            .unwrap();
        let result = preflight().await;
        if !accepted {
            expect_refusal(result, "cutover_stopped_legacy_preparation_required");
            continue;
        }
        assert!(result.status.success());
        assert!(result.stderr.is_empty());
        let stdout = String::from_utf8(result.stdout).unwrap();
        for private in [HOST_TOKEN, "fictional-cutover-canary", "rust_agent_fixture"] {
            assert!(!stdout.contains(private));
        }
        let report: Value = serde_json::from_str(&stdout).unwrap();
        assert_eq!(report["scope"], "read_only_database_observation");
        assert_eq!(report["queue_revision"], 162);
        assert_eq!(report["legacy_preparation_revision"], 12);
        assert_eq!(report["rust_control"]["mode"], "STOPPED");
        assert_eq!(report["rust_control"]["revision"], 2);
        assert!(report["other_visible_role_sessions"].as_i64().unwrap() >= 1);
        assert_eq!(report["planned_rust_session_peak"], 3);
    }
    let saved: Value = sqlx::query_scalar(
        "SELECT jsonb_object_agg(key,value) FROM owner_preferences
         WHERE key IN ('application_queue_policy','naukri_automation')",
    )
    .fetch_one(&mut c)
    .await
    .unwrap();
    assert_eq!(
        saved,
        json!({
            "application_queue_policy":{"state":"STOPPED","revision":162,"policy":{"private":"fictional-cutover-canary"}},
            "naukri_automation":{"state":"STOPPED","revision":12},
        })
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT count(*) FROM rust_agent_control_events")
            .fetch_one(&mut c)
            .await
            .unwrap(),
        2,
    );
}
