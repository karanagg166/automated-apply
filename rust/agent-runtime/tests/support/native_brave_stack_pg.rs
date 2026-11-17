#[tokio::test(flavor = "current_thread")]
#[ignore = "requires disposable PostgreSQL, built Brave bundle, and isolated browser harness"]
async fn native_brave_extension_fixture_exercises_real_framing_and_saved_broker_state() {
    let mut c = browser_fixture().await;
    let policy = execution_seed_policy(&mut c).await;
    let (base, stop, server) = http_fixture_values(browser_values()).await;
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let bridge = std::path::Path::new(env!("CARGO_BIN_EXE_automated-apply-agents"))
        .with_file_name("automated-apply-native");
    assert!(
        bridge.is_file(),
        "build the locked workspace binaries first"
    );
    let result = tokio::process::Command::new("node")
        .args(["extension/tests/native-rust-stack.browser.mjs", &base])
        .arg(bridge)
        .current_dir(root)
        .env_clear()
        .env("PATH", std::env::var_os("PATH").unwrap_or_default())
        .env("AUTOMATED_APPLY_TEST_BROWSER", "brave")
        .env("RUST_NATIVE_BROWSER_FIXTURE_TOKEN", HOST_TOKEN)
        .kill_on_drop(true)
        .output()
        .await
        .expect("headless native fixture process");
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr),
    );
    assert_eq!(
        browser_pref(&mut c, "application_queue_policy").await,
        policy
    );
    let observation = browser_pref(&mut c, "portal_naukri").await;
    assert_eq!(observation["browser_scope"]["selection_version"], 1);
    assert_eq!(observation["observation"], "signed_in_indicator");
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT count(*) FROM owner_preferences WHERE starts_with(key,'apply_work:') OR starts_with(key,'apply_budget:')",
        )
        .fetch_one(&mut c)
        .await
        .unwrap(),
        0
    );
    stop.cancel();
    server.await.unwrap();
}
