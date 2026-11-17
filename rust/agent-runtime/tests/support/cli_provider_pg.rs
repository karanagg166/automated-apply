//! Deferred fictional executable and disposable PostgreSQL only. No AGY login/model calls.
fn cli_answer_values(mode:&str)->(BTreeMap<String,String>,tempfile::TempDir,std::path::PathBuf) {
    use std::{fs,os::unix::fs::PermissionsExt};
    let dir=tempfile::tempdir().unwrap();let home=dir.path();
    let workspace=home.join("Library/Application Support/Automated Apply/agy-answer-workspace");
    for path in [home.to_path_buf(),workspace.clone(),home.join(".gemini/antigravity-cli"),home.join(".gemini/config/agents"),workspace.join(".agents/agents")] {
        fs::create_dir_all(&path).unwrap();fs::set_permissions(path,fs::Permissions::from_mode(0o700)).unwrap();
    }
    let write=|path:std::path::PathBuf,bytes:&[u8],mode:u32| {fs::write(&path,bytes).unwrap();fs::set_permissions(path,fs::Permissions::from_mode(mode)).unwrap();};
    write(home.join(".gemini/antigravity-cli/settings.json"),json!({"useG1Credits":false,"trustedWorkspaces":[workspace.to_str().unwrap()]}).to_string().as_bytes(),0o600);
    let agent=include_bytes!("../../schemas/agy-agent.md");
    write(home.join(".gemini/config/agents/automated-apply-answer.md"),agent,0o600);
    write(workspace.join(".agents/agents/automated-apply-answer.md"),agent,0o600);
    let reference=json!({"source_type":"verified_project","source_id":format!("{}:project:0",profile_pin().id)});
    let content=json!({"answer":"I built Rust workers.","evidence_references":[reference],"claims":[{"text":"I built Rust workers.","quote":"I built Rust workers.","source":reference}],"opportunity_claims":[]});
    let result=json!({"event":"result","result":{"status":"SUCCESS","num_turns":1,"structured_output":content,"usage":{"input_tokens":100,"output_tokens":20}}});
    let init=if mode=="tool" {json!({"event":"init","init":{"tools":["run_command"]}})} else {json!({"event":"init","init":{"tools":[]}})};
    let extra=match mode {
        "quota"=>"printf 'private quota 429' >&2; exit 1",
        "wait"=>"printf 'waiting' > waiting; while [ ! -f release ]; do /bin/sleep 0.02; done",
        _=>"",
    };
    let exe=home.join("fictional-agy");
    let script=format!("#!/bin/sh\n[ -z \"${{JOB_AGENT_API_TOKEN}}${{APIFY_API_TOKEN}}${{GEMINI_API_KEY}}\" ] || exit 9\nif [ \"$1\" = agents ]; then printf 'seen' >> agents-seen; printf 'automated-apply-answer\\n'; exit 0; fi\nprintf '%s\\n' '{init}'\nreceived=$(/bin/cat)\n[ -z \"$received\" ] || printf '%s' \"$received\" > received\n{extra}\nprintf '%s' '{result}'\n");
    write(exe.clone(),script.as_bytes(),0o700);
    let values=BTreeMap::from([("LLM_PROVIDER".into(),"agy".into()),("AGY_ENABLED".into(),"true".into()),("AGY_QUOTA_AUTHORIZED".into(),"true".into()),("AGY_MODEL".into(),"fictional-high".into()),("AGY_EXECUTABLE".into(),exe.to_string_lossy().into()),("RUST_AGY_FIXTURE_HOME".into(),home.to_string_lossy().into()),("LLM_MONTHLY_MAX_REQUESTS".into(),"2".into())]);
    (values,dir,workspace)
}
fn cli_native_settings(values:&BTreeMap<String,String>)->automated_apply_agents::answer_service::Settings {
    automated_apply_agents::answer_service::Settings::from_values(values,true,BTreeMap::new()).unwrap()
}
async fn cli_generate(c:&mut PgConnection,values:&BTreeMap<String,String>)->Value {
    automated_apply_agents::answer_service::generate(c,json!({"question":"Describe a project you built","rewrite":true,"save_draft":true}),&cli_native_settings(values)).await.unwrap()
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn cli_writer_reuses_legacy_monthly_counts_and_saves_only_grounded_reviewable_draft() {
    let mut c=narrative_fixture().await;
    sqlx::query("INSERT INTO llm_monthly_usage(provider,month,requests) VALUES('agy',to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM'),1),('cohere',to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM'),4)").execute(&mut c).await.unwrap();
    let (values,_dir,workspace)=cli_answer_values("ok");
    let first=cli_generate(&mut c,&values).await;
    assert_eq!(first["status"],"draft_ready");assert_eq!(first["provider"],"agy");assert_eq!(first["model"],"fictional-high");assert_eq!(first["used_llm"],true);assert_eq!(first["requires_review"],true);assert!(first["draft_id"].is_string());
    assert_eq!(first["usage"],json!({"input_tokens":100,"output_tokens":20}));
    let row:(i32,i32,i32)=sqlx::query_as("SELECT requests,input_tokens,output_tokens FROM llm_monthly_usage WHERE provider='agy'").fetch_one(&mut c).await.unwrap();assert_eq!(row,(2,100,20));
    assert_eq!(sqlx::query_scalar::<_,i32>("SELECT requests FROM llm_monthly_usage WHERE provider='cohere'").fetch_one(&mut c).await.unwrap(),4);
    let before=std::fs::read(workspace.join("agents-seen")).unwrap();
    let exhausted=cli_generate(&mut c,&values).await;assert_eq!(exhausted["error_code"],"monthly_request_limit");assert_eq!(exhausted["used_llm"],false);assert_eq!(std::fs::read(workspace.join("agents-seen")).unwrap(),before);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn cli_advertised_tools_consume_one_reserved_attempt_without_prompt_draft_or_retry() {
    let mut c=narrative_fixture().await;let (values,_dir,workspace)=cli_answer_values("tool");
    let before:i64=sqlx::query_scalar("SELECT count(*) FROM application_answer_drafts").fetch_one(&mut c).await.unwrap();
    let result=cli_generate(&mut c,&values).await;assert_eq!(result["error_code"],"provider_tool_use_denied");assert_eq!(result["used_llm"],true);assert!(result["answer"].is_null());
    assert!(!workspace.join("received").exists());assert_eq!(std::fs::read(workspace.join("agents-seen")).unwrap(),b"seen");
    assert_eq!(sqlx::query_scalar::<_,i32>("SELECT requests FROM llm_monthly_usage WHERE provider='agy'").fetch_one(&mut c).await.unwrap(),1);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_answer_drafts").fetch_one(&mut c).await.unwrap(),before);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn cli_quota_failure_persists_cooldown_and_never_replays_original_process() {
    let mut c=narrative_fixture().await;let (values,_dir,workspace)=cli_answer_values("quota");
    let result=cli_generate(&mut c,&values).await;assert_eq!(result["error_code"],"rate_limited");assert_eq!(result["retry_after_seconds"],60.0);
    assert!(sqlx::query_scalar::<_,bool>("SELECT cooldown_until>clock_timestamp()+interval '50 seconds' FROM llm_monthly_usage WHERE provider='agy'").fetch_one(&mut c).await.unwrap());
    let before=std::fs::read(workspace.join("agents-seen")).unwrap();
    let second=cli_generate(&mut c,&values).await;assert_eq!(second["error_code"],"rate_limited");assert_eq!(second["used_llm"],false);assert_eq!(std::fs::read(workspace.join("agents-seen")).unwrap(),before);
    assert_eq!(sqlx::query_scalar::<_,i32>("SELECT requests FROM llm_monthly_usage WHERE provider='agy'").fetch_one(&mut c).await.unwrap(),1);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn cli_generation_releases_profile_locks_and_rejects_facts_changed_during_process_wait() {
    let mut c=narrative_fixture().await;let (values,_dir,workspace)=cli_answer_values("wait");
    let baseline:i64=sqlx::query_scalar("SELECT count(*) FROM application_answer_drafts").fetch_one(&mut c).await.unwrap();
    let mut writer=connection().await;let settings=cli_native_settings(&values);
    let task=tokio::spawn(async move {automated_apply_agents::answer_service::generate(&mut writer,json!({"question":"Describe a project you built","rewrite":true,"save_draft":true}),&settings).await});
    tokio::time::timeout(Duration::from_secs(3),async {while !workspace.join("waiting").exists() {tokio::time::sleep(Duration::from_millis(20)).await;}}).await.unwrap();
    tokio::time::timeout(Duration::from_secs(1),sqlx::query("UPDATE candidate_profiles SET version=version+1 WHERE singleton_key='primary'").execute(&mut c)).await.unwrap().unwrap();
    std::fs::write(workspace.join("release"),b"release").unwrap();
    let result=task.await.unwrap().unwrap();assert_eq!(result["error_code"],"generation_context_changed");assert!(result["answer"].is_null());assert!(result["draft_id"].is_null());
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_answer_drafts").fetch_one(&mut c).await.unwrap(),baseline);
    assert_eq!(sqlx::query_scalar::<_,i32>("SELECT requests FROM llm_monthly_usage WHERE provider='agy'").fetch_one(&mut c).await.unwrap(),1);
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn cli_private_policy_or_missing_owner_authorization_stops_before_any_reservation() {
    let mut c=narrative_fixture().await;let (mut values,dir,workspace)=cli_answer_values("ok");
    std::fs::write(dir.path().join(".gemini/antigravity-cli/settings.json"),b"{\"useG1Credits\":true}").unwrap();
    let result=cli_generate(&mut c,&values).await;assert_eq!(result["error_code"],"paid_overage_configuration_forbidden");assert_eq!(result["used_llm"],false);assert!(!workspace.join("agents-seen").exists());
    values.insert("AGY_QUOTA_AUTHORIZED".into(),"false".into());let result=cli_generate(&mut c,&values).await;assert_eq!(result["error_code"],"provider_execution_not_authorized");
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM llm_monthly_usage WHERE provider='agy'").fetch_one(&mut c).await.unwrap(),0);
}
