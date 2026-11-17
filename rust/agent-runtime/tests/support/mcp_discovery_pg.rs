//! Deferred MCP -> authenticated Unix owner API -> fictional providers. No real accounts.
fn discovery_mcp_bridge(values: &BTreeMap<String,String>) -> (automated_apply_agents::mcp_bridge::Bridge,tempfile::TempDir) {
    use std::os::unix::fs::PermissionsExt;
    let directory=tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(),std::fs::Permissions::from_mode(0o700)).unwrap();
    let path=directory.path().join("fictional.private.env");
    let raw=values.iter().map(|(key,value)|format!("{key}='{value}'\n")).collect::<String>();
    std::fs::write(&path,raw).unwrap();
    std::fs::set_permissions(&path,std::fs::Permissions::from_mode(0o600)).unwrap();
    (automated_apply_agents::mcp_bridge::Bridge::load(&path).unwrap(),directory)
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn mcp_default_discovery_reads_and_previews_do_not_dispatch_or_write_and_direct_actions_refuse() {
    let mut c=apify_owner_fixture().await;
    let (v,remote,remote_stop,remote_task)=apify_job_http("ok").await;
    let (values,_socket,stop,server)=unix_http_fixture_values(v).await;
    let (bridge,_config)=discovery_mcp_bridge(&values);
    let before=apify_owner_snapshot(&mut c).await;
    for name in ["discovery_sources","startup_sources","apify_status"] {
        let result=bridge.call(name,json!({})).await.unwrap();
        assert!(!result.to_string().contains("CANARY"));
    }
    let preview=bridge.call("discovery_preview",json!({"request":{"source":"naukri","use_profile":false,"query":{"limit":2},"allow_paid":true}})).await.unwrap();
    assert_eq!(preview["writes"],0);assert_eq!(preview["provider_calls"],0);
    assert!(preview["paid_execution"].is_object());
    for (name,args) in [
        ("discovery_run",json!({"run_id":Uuid::new_v4(),"consent":true,"request":{"source":"naukri"}})),
        ("discovery_complete",json!({"run_id":Uuid::new_v4()})),
        ("apify_read_recover",json!({"run_id":Uuid::new_v4(),"read_request_id":Uuid::new_v4(),"consent":true})),
        ("apify_inspect_account",json!({"consent":true})),
    ] { assert_eq!(bridge.call(name,args).await.unwrap_err().0,"mcp_capability_not_enabled"); }
    assert_eq!(apify_owner_snapshot(&mut c).await,before);
    assert_eq!(remote.calls.lock().await.len(),0);
    stop.cancel();server.await.unwrap();remote_stop.cancel();remote_task.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn mcp_original_paid_put_status_and_local_completion_share_one_start_and_reservation() {
    let mut c=apify_owner_fixture().await;
    let (mut v,remote,remote_stop,remote_task)=apify_job_http("ok").await;
    v.insert("RUST_AGENT_MCP_ALLOW_DISCOVERY".into(),"true".into());
    let (values,_socket,stop,server)=unix_http_fixture_values(v).await;
    let (bridge,_config)=discovery_mcp_bridge(&values);
    let id=Uuid::from_u128(78001);
    let mut request=apify_job_input();request.as_object_mut().unwrap().remove("idempotency_key");
    let args=json!({"run_id":id,"consent":true,"request":request});
    let first=bridge.call("discovery_run",args.clone()).await.unwrap();
    assert_eq!(first["id"],json!(id));assert_eq!(first["local_intake_complete"],true);
    assert_eq!(first["provider_run_id"],"originalRun");assert_eq!(first["billing_final"],false);
    let before=apify_owner_snapshot(&mut c).await;
    for (name,args) in [("discovery_run",args),("discovery_run_status",json!({"run_id":id})),("discovery_complete",json!({"run_id":id}))] {
        assert_eq!(bridge.call(name,args).await.unwrap(),first);
    }
    assert_eq!(remote.starts.load(Ordering::SeqCst),1);
    assert_eq!(remote.calls.lock().await.len(),5);
    assert_eq!(apify_owner_snapshot(&mut c).await,before);
    stop.cancel();server.await.unwrap();remote_stop.cancel();remote_task.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn mcp_explicit_metadata_inspection_remains_separate_from_paid_execution_and_saved_status() {
    let mut c=apify_metadata_fixture().await;
    let (mut v,remote,remote_stop,remote_task)=apify_metadata_http(false).await;
    v.insert("RUST_AGENT_MCP_ALLOW_METADATA_INSPECTION".into(),"true".into());
    let (values,_socket,stop,server)=unix_http_fixture_values(v).await;
    let (bridge,_config)=discovery_mcp_bridge(&values);
    assert_eq!(bridge.call("apify_inspect_account",json!({"consent":false})).await.unwrap_err().0,"mcp_explicit_consent_required");
    assert_eq!(remote.calls.load(Ordering::SeqCst),0);
    let result=bridge.call("apify_inspect_account",json!({"consent":true})).await.unwrap();
    assert_eq!(result["execution_authorized"],false);assert!(!result.to_string().contains("CANARY"));
    assert_eq!(remote.calls.load(Ordering::SeqCst),2);
    let before=apify_metadata_snapshot(&mut c).await;
    let status=bridge.call("apify_status",json!({})).await.unwrap();
    assert_eq!(status["inspection_cache_state"],"saved");assert_eq!(status["provider_calls_performed_by_read"],0);
    assert_eq!(apify_metadata_snapshot(&mut c).await,before);assert_eq!(remote.calls.load(Ordering::SeqCst),2);
    assert_eq!(bridge.call("discovery_complete",json!({"run_id":Uuid::new_v4()})).await.unwrap_err().0,"mcp_capability_not_enabled");
    stop.cancel();server.await.unwrap();remote_stop.cancel();remote_task.await.unwrap();
}

#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn framed_mcp_discovery_preserves_missing_original_uuid_and_never_dispatches_without_consent() {
    use tokio::io::{AsyncBufReadExt,AsyncWriteExt,BufReader};
    use std::{os::unix::fs::PermissionsExt,process::Stdio};
    let mut c=apify_owner_fixture().await;
    let custom=BTreeMap::from([("RUST_AGENT_MCP_ALLOW_DISCOVERY".into(),"true".into())]);
    let (values,_socket,stop,server)=unix_http_fixture_values(custom).await;
    let temp=tempfile::tempdir().unwrap();let path=temp.path().join("fictional.private.env");
    std::fs::write(&path,values.iter().map(|(key,value)|format!("{key}='{value}'\n")).collect::<String>()).unwrap();
    std::fs::set_permissions(&path,std::fs::Permissions::from_mode(0o600)).unwrap();
    let mut child=tokio::process::Command::new(env!("CARGO_BIN_EXE_automated-apply-tools"))
        .arg("--config").arg(path).env_clear().env("PATH","/usr/bin:/bin")
        .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null()).kill_on_drop(true).spawn().unwrap();
    let mut input=child.stdin.take().unwrap();let mut lines=BufReader::new(child.stdout.take().unwrap()).lines();
    let id=Uuid::from_u128(78002);let before=apify_owner_snapshot(&mut c).await;
    for (message,expected) in [
        (json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"fictional-discovery","version":"1"}}}),1),
        (json!({"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"discovery_sources","arguments":{}}}),2),
        (json!({"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"discovery_run_status","arguments":{"run_id":id}}}),3),
        (json!({"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"discovery_run","arguments":{"run_id":id,"consent":false,"request":{"source":"naukri","allow_paid":true}}}}),4),
    ] {
        input.write_all(format!("{message}\n").as_bytes()).await.unwrap();input.flush().await.unwrap();
        let raw=tokio::time::timeout(Duration::from_secs(5),lines.next_line()).await.unwrap().unwrap().unwrap();
        assert!(!raw.contains(HOST_TOKEN));assert!(!raw.contains("PRIVATE_"));
        let response:Value=serde_json::from_str(&raw).unwrap();assert_eq!(response["id"],expected);
        match expected {
            1=>{input.write_all(b"{\"jsonrpc\":\"2.0\",\"method\":\"notifications/initialized\"}\n").await.unwrap();},
            2=>{assert!(response["result"]["isError"]!=true);assert!(response["result"]["structuredContent"]["sources"].is_array());},
            3=>{assert_eq!(response["result"]["isError"],true);assert_eq!(response["result"]["structuredContent"]["retained_attempt"]["run_id"],json!(id));assert_eq!(response["result"]["structuredContent"]["automatic_retry"],false);},
            4=>assert!(response["error"].is_object() || response["result"]["isError"]==true),
            _=>unreachable!(),
        }
    }
    drop(input);assert!(tokio::time::timeout(Duration::from_secs(5),child.wait()).await.unwrap().unwrap().success());
    assert_eq!(apify_owner_snapshot(&mut c).await,before);
    stop.cancel();server.await.unwrap();
}
