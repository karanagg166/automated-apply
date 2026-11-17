use super::*;
use protocol::Stream;
use serde_json::{Value, json};
use std::{collections::BTreeMap, fs, os::unix::fs::PermissionsExt};
fn answer() -> Value {
    let reference = json!({"source_type":"verified_project","source_id":"fictional:project:0"});
    json!({"answer":"I built Rust workers.","evidence_references":[reference],"claims":[{"text":"I built Rust workers.","quote":"I built Rust workers.","source":reference}],"opportunity_claims":[]})
}
fn initialized() -> Stream {
    let mut stream = Stream::default();
    assert!(
        stream
            .frame(br#"{"event":"init","init":{"tools":[]}}"#, false)
            .unwrap()
    );
    stream
}
#[test]
fn stream_requires_initialization_and_exactly_one_successful_one_turn_result() {
    let mut stream = initialized();
    stream.frame(json!({"event":"result","result":{"status":"SUCCESS","num_turns":1,"structured_output":answer(),"usage":{"input_tokens":3,"output_tokens":4}}}).to_string().as_bytes(),true).unwrap();
    let result = stream.finish().unwrap();
    assert_eq!(result.content.answer, "I built Rust workers.");
    assert_eq!(result.input, Some(3));
    assert_eq!(result.output, Some(4));
    assert_eq!(
        Stream::default()
            .frame(br#"{"event":"result","result":{}}"#, false)
            .unwrap_err()
            .0,
        "provider_init_unverified"
    );
    assert_eq!(
        initialized().finish().err().unwrap().0,
        "invalid_structured_response"
    );
}
#[test]
fn every_frame_refuses_tools_subagents_malformed_or_duplicate_initialization() {
    for value in [
        json!({"event":"step_update","step_update":{"step_type":"tool"}}),
        json!({"event":"step_update","step_update":{"subagent_info":{"name":"injected"}}}),
        json!({"event":"step_update","step_update":{"tool_info":{"name":"shell"}}}),
        json!({"event":"step_update","step_update":{"tool_name":"browser"}}),
    ] {
        assert_eq!(
            initialized()
                .frame(value.to_string().as_bytes(), true)
                .unwrap_err()
                .0,
            "provider_tool_use_denied"
        );
    }
    for raw in [
        br#"{"event":"init","init":{"tools":["run_command"]}}"#.as_slice(),
        br#"{"event":"init","init":null}"#,
        b"[]",
        b"not-json",
        br#"{"event":"unknown"}"#,
    ] {
        assert!(Stream::default().frame(raw, false).is_err());
    }
    assert!(
        initialized()
            .frame(br#"{"event":"init","init":{"tools":[]}}"#, false)
            .is_err()
    );
}
#[test]
fn terminal_errors_tool_calls_usage_and_duplicate_results_are_rejected() {
    for (key, value) in [
        ("status", json!("ERROR")),
        ("num_turns", json!(2)),
        ("num_turns", json!(true)),
        ("tool_calls", json!([{}])),
        ("permission_denials", json!([{}])),
        ("is_error", json!(true)),
        ("usage", json!({"input_tokens":true})),
        ("usage", json!({"thinking_tokens":-1})),
    ] {
        let mut result = json!({"structured_output":answer()});
        result[key] = value;
        let mut stream = initialized();
        stream
            .frame(
                json!({"event":"result","result":result})
                    .to_string()
                    .as_bytes(),
                true,
            )
            .unwrap();
        assert!(stream.finish().is_err());
    }
    let mut stream = initialized();
    let raw = json!({"event":"result","result":{"response":answer().to_string()}}).to_string();
    stream.frame(raw.as_bytes(), true).unwrap();
    assert!(stream.frame(raw.as_bytes(), true).is_err());
}
#[test]
fn pre_prompt_authentication_and_nonzero_diagnostics_are_fixed_codes_only() {
    assert_eq!(
        Stream::default()
            .frame(
                br#"{"event":"result","result":{"error":"Login required PRIVATE_CANARY"}}"#,
                false
            )
            .unwrap_err()
            .0,
        "provider_authentication"
    );
    for (raw, code) in [
        ("private quota 429", "rate_limited"),
        ("authentication required", "provider_authentication"),
        ("invalid --json-schema", "cli_schema_rejected"),
        ("unknown flag --private", "unsupported_cli_argument"),
        ("PRIVATE_CANARY", "cli_nonzero_exit"),
    ] {
        assert_eq!(protocol::exit_error(raw.as_bytes()).0, code);
    }
}
fn fixture(body: &str) -> (CliModel, tempfile::TempDir) {
    let directory = tempfile::tempdir().unwrap();
    let home = directory.path();
    let workspace = home.join("Library/Application Support/Automated Apply/agy-answer-workspace");
    for path in [
        home.to_path_buf(),
        workspace.clone(),
        home.join(".gemini/antigravity-cli"),
        home.join(".gemini/config/agents"),
        workspace.join(".agents/agents"),
    ] {
        fs::create_dir_all(&path).unwrap();
        fs::set_permissions(path, fs::Permissions::from_mode(0o700)).unwrap();
    }
    fn file(path: std::path::PathBuf, bytes: &[u8], mode: u32) {
        fs::write(&path, bytes).unwrap();
        fs::set_permissions(path, fs::Permissions::from_mode(mode)).unwrap();
    }
    file(
        home.join(".gemini/antigravity-cli/settings.json"),
        json!({"useG1Credits":false,"trustedWorkspaces":[workspace.to_str().unwrap()]})
            .to_string()
            .as_bytes(),
        0o600,
    );
    file(
        home.join(".gemini/config/agents/automated-apply-answer.md"),
        settings::AGENT.as_bytes(),
        0o600,
    );
    file(
        workspace.join(".agents/agents/automated-apply-answer.md"),
        settings::AGENT.as_bytes(),
        0o600,
    );
    let exe = home.join("fictional-agy");
    file(exe.clone(),format!("#!/bin/sh\nif [ \"$1\" = agents ]; then printf 'automated-apply-answer\\n'; exit 0; fi\n{body}\n").as_bytes(),0o700);
    let values = BTreeMap::from([
        ("AGY_ENABLED".into(), "true".into()),
        ("AGY_QUOTA_AUTHORIZED".into(), "true".into()),
        ("AGY_MODEL".into(), "fictional-high".into()),
        ("AGY_EXECUTABLE".into(), exe.to_string_lossy().into()),
        (
            "RUST_AGY_FIXTURE_HOME".into(),
            home.to_string_lossy().into(),
        ),
    ]);
    (CliModel::from_values(&values, true).unwrap(), directory)
}
fn success_body() -> String {
    let result = json!({"event":"result","result":{"status":"SUCCESS","num_turns":1,"structured_output":answer()}});
    format!(
        "printf '%s\\n' '{{\"event\":\"init\",\"init\":{{\"tools\":[]}}}}'\nreceived=$(/bin/cat)\n[ -n \"$received\" ] || exit 3\nprintf '%s' \"$received\" > received\nprintf '%s' '{result}'"
    )
}
#[test]
fn private_policy_profiles_workspace_and_executable_are_verified_without_mutation() {
    let (model, _directory) = fixture(&success_body());
    assert!(model.verify().is_ok());
    let path = model.home.join(".gemini/antigravity-cli/settings.json");
    let before = fs::read(&path).unwrap();
    for value in [
        json!({"useG1Credits":true}),
        json!({"modelProvider":"cloud"}),
        json!({"gcp":{"project":"private"}}),
        json!({"customModelsConfig":[{}]}),
    ] {
        fs::write(&path, value.to_string()).unwrap();
        assert_eq!(
            model.verify().unwrap_err().0,
            "paid_overage_configuration_forbidden"
        );
    }
    fs::write(&path, &before).unwrap();
    assert!(model.verify().is_ok());
    fs::write(
        model
            .workspace()
            .join(".agents/agents/automated-apply-answer.md"),
        "changed",
    )
    .unwrap();
    assert_eq!(
        model.verify().unwrap_err().0,
        "restricted_agent_profile_unavailable"
    );
    fs::write(
        model
            .workspace()
            .join(".agents/agents/automated-apply-answer.md"),
        settings::AGENT,
    )
    .unwrap();
    fs::set_permissions(&model.executable, fs::Permissions::from_mode(0o777)).unwrap();
    assert_eq!(model.verify().unwrap_err().0, "cli_unavailable");
}
#[test]
fn symlink_and_public_files_never_supply_cli_billing_or_profile_authority() {
    use std::os::unix::fs::symlink;
    let (model, _directory) = fixture(&success_body());
    let path = model.home.join(".gemini/antigravity-cli/settings.json");
    fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).unwrap();
    assert!(model.verify().is_err());
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
    let copy = model.home.join("preserved.json");
    fs::rename(&path, &copy).unwrap();
    symlink(copy, &path).unwrap();
    assert!(model.verify().is_err());
}
#[test]
fn cli_configuration_and_environment_exclude_shell_models_and_inherited_credentials() {
    let (model, _directory) = fixture(&success_body());
    let environment = model.environment();
    assert!(environment.keys().all(|k| {
        [
            "HOME",
            "PATH",
            "LANG",
            "USER",
            "AGY_CLI_DISABLE_AUTO_UPDATE",
        ]
        .contains(&k.as_str())
    }));
    assert_eq!(environment["AGY_CLI_DISABLE_AUTO_UPDATE"], "1");
    let base = BTreeMap::from([
        ("AGY_ENABLED".into(), "true".into()),
        ("AGY_QUOTA_AUTHORIZED".into(), "true".into()),
        ("AGY_MODEL".into(), "fictional-high".into()),
    ]);
    for (key, value) in [
        ("AGY_MODEL", "--run-shell"),
        ("AGY_MODEL", "model; cat"),
        ("AGY_EFFORT", "unbounded"),
        ("AGY_TIMEOUT_SECONDS", "NaN"),
        ("AGY_EXECUTABLE", "agy"),
        ("AGY_QUOTA_AUTHORIZED", "false"),
    ] {
        let mut values = base.clone();
        values.insert(key.into(), value.into());
        assert!(CliModel::from_values(&values, true).is_err());
    }
    let mut values = base;
    values.insert(
        "RUST_AGY_FIXTURE_HOME".into(),
        model.home.to_string_lossy().into(),
    );
    assert_eq!(
        CliModel::from_values(&values, false).err().unwrap().0,
        "provider_fixture_home_denied"
    );
}
#[test]
fn generated_schema_and_argv_keep_fixed_profile_and_private_artifacts() {
    let (model, _directory) = fixture(&success_body());
    let scratch = settings::scratch(&model).unwrap();
    settings::write_schema(&scratch.join("answer.schema.json")).unwrap();
    assert_eq!(
        fs::metadata(&scratch).unwrap().permissions().mode() & 0o777,
        0o700
    );
    assert_eq!(
        fs::metadata(scratch.join("answer.schema.json"))
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o600
    );
    let schema: Value =
        serde_json::from_slice(&fs::read(scratch.join("answer.schema.json")).unwrap()).unwrap();
    assert!(!schema.to_string().contains("$ref"));
    assert_eq!(schema["additionalProperties"], false);
    let args = model.arguments(&scratch, Duration::from_secs(30));
    assert!(
        args.windows(2)
            .any(|a| a == ["--agent", "automated-apply-answer"])
    );
    assert!(args.contains(&"--sandbox".into()));
    assert!(!args.iter().any(|a| a.contains("skip-permissions")));
}
#[tokio::test(flavor = "current_thread")]
async fn actual_fictional_cli_handshake_precedes_prompt_and_accepts_unterminated_final_result() {
    let (model, _directory) = fixture(&success_body());
    model.verify().unwrap();
    process::discover(&model, Duration::from_secs(2))
        .await
        .unwrap();
    let result = process::generate(
        &model,
        &[],
        b"fictional prompt\n".to_vec(),
        Duration::from_secs(2),
    )
    .await
    .unwrap();
    assert_eq!(result.content.answer, "I built Rust workers.");
    assert_eq!(
        fs::read(model.workspace().join("received")).unwrap(),
        b"fictional prompt"
    );
}
#[tokio::test(flavor = "current_thread")]
async fn actual_denied_or_malformed_init_never_writes_prompt_and_pipes_are_bounded() {
    for init in [
        "not-json",
        "[]",
        "{\"event\":\"init\",\"init\":{\"tools\":[\"run_command\"]}}",
    ] {
        let body = format!(
            "printf '%s\\n' '{init}'\nreceived=$(/bin/cat)\n[ -z \"$received\" ] || printf '%s' \"$received\" > received"
        );
        let (model, _directory) = fixture(&body);
        assert!(
            process::generate(&model, &[], b"never-send".to_vec(), Duration::from_secs(1))
                .await
                .is_err()
        );
        assert!(!model.workspace().join("received").exists());
    }
    let (model, _directory) = fixture("/usr/bin/head -c 65537 /dev/zero");
    assert_eq!(
        process::generate(&model, &[], b"never-send".to_vec(), Duration::from_secs(1))
            .await
            .err()
            .unwrap()
            .0,
        "provider_output_size"
    );
}
#[tokio::test(flavor = "current_thread")]
async fn policy_change_before_init_and_final_tool_frame_are_both_rejected() {
    let body = "printf 'changed' > .agents/agents/automated-apply-answer.md\nprintf '%s\\n' '{\"event\":\"init\",\"init\":{\"tools\":[]}}'\n/bin/cat > received";
    let (model, _directory) = fixture(body);
    assert_eq!(
        process::generate(&model, &[], b"never-send".to_vec(), Duration::from_secs(1))
            .await
            .err()
            .unwrap()
            .0,
        "restricted_agent_profile_unavailable"
    );
    assert!(
        fs::metadata(model.workspace().join("received"))
            .map(|m| m.len() == 0)
            .unwrap_or(true)
    );
    let body = "printf '%s\\n' '{\"event\":\"init\",\"init\":{\"tools\":[]}}'\n/bin/cat >/dev/null\nprintf '%s' '{\"event\":\"step_update\",\"step_update\":{\"tool_name\":\"apply\"}}'";
    let (model, _directory) = fixture(body);
    assert_eq!(
        process::generate(&model, &[], b"fictional\n".to_vec(), Duration::from_secs(1))
            .await
            .err()
            .unwrap()
            .0,
        "provider_tool_use_denied"
    );
}
#[tokio::test(flavor = "current_thread")]
async fn timeout_and_cancellation_stop_owned_descendants_without_later_marker() {
    let body = "( /bin/sleep 0.4; printf 'escaped' > descendant-marker ) &\n/bin/sleep 10";
    let (model, _directory) = fixture(body);
    let model = model.clone();
    assert_eq!(
        process::generate(
            &model,
            &[],
            b"never-send".to_vec(),
            Duration::from_millis(80)
        )
        .await
        .err()
        .unwrap()
        .0,
        "timeout"
    );
    tokio::time::sleep(Duration::from_millis(500)).await;
    assert!(!model.workspace().join("descendant-marker").exists());
    let copy = model.clone();
    let task = tokio::spawn(async move {
        process::generate(&copy, &[], b"never-send".to_vec(), Duration::from_secs(10)).await
    });
    tokio::time::sleep(Duration::from_millis(80)).await;
    task.abort();
    let _ = task.await;
    tokio::time::sleep(Duration::from_millis(500)).await;
    assert!(!model.workspace().join("descendant-marker").exists());
}
