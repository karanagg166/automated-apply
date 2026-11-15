#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn platform_tools_read_only_current_saved_data_and_refuse_unknown_platform_or_inputs(){
    let mut c=knowledge_fixture().await;
    let naukri=Uuid::new_v4();let instahyre=Uuid::new_v4();
    for (id,platform) in [(naukri,"naukri"),(instahyre,"instahyre")]{
        sqlx::query("INSERT INTO jobs(id,title,job_url,source_platform)VALUES($1,'Fictional role','https://example.com/fictional',$2)").bind(id).bind(platform).execute(&mut c).await.unwrap();
    }
    let (url,stop,server)=http_fixture().await;let http=client();
    for (platform,id) in [("naukri",naukri),("instahyre",instahyre)]{
        let target=format!("{url}/api/v1/rust-agent/platforms/{platform}/saved-jobs");
        assert_eq!(http.post(&target).json(&json!({"limit":20})).send().await.unwrap().status(),401);
        let response=http.post(&target).bearer_auth(HOST_TOKEN).json(&json!({"limit":20})).send().await.unwrap();assert_eq!(response.status(),200);
        let data:Value=response.json().await.unwrap();assert_eq!(data["jobs"].as_array().unwrap().len(),1);assert_eq!(data["jobs"][0]["id"],json!(id));assert_eq!(data["application_dispatch"],false);
        for args in [json!({"limit":0}),json!({"limit":51}),json!({"limit":2,"submit":true})]{assert_eq!(http.post(&target).bearer_auth(HOST_TOKEN).json(&args).send().await.unwrap().status(),400);}
    }
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_packets").fetch_one(&mut c).await.unwrap(),0);
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM rust_agent_runs").fetch_one(&mut c).await.unwrap(),0);
    assert_eq!(http.post(format!("{url}/api/v1/rust-agent/platforms/unknown/saved-jobs")).bearer_auth(HOST_TOKEN).json(&json!({"limit":20})).send().await.unwrap().status(),400);
    stop.cancel();server.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn mcp_telegram_notice_is_fixed_owner_bound_and_never_requeues_an_unknown_send(){
    let (mut c,settings,_)=telegram_fixture().await;
    let run=run();Store{connection:&mut c}.create(&run).await.unwrap();
    let (url,stop,server)=http_fixture_values(telegram_values("http://127.0.0.1:54321")).await;
    let target=format!("{url}/api/v1/rust-agent/runs/{}/notify-telegram",run.id);
    let http=client();
    for body in [json!({"text":"untrusted"}),json!({"chat_id":99})]{assert_eq!(http.post(&target).bearer_auth(HOST_TOKEN).json(&body).send().await.unwrap().status(),400);}
    let mut first=None;
    for _ in 0..2{
        let response=http.post(&target).bearer_auth(HOST_TOKEN).json(&json!({})).send().await.unwrap();assert_eq!(response.status(),200);
        let value:Value=response.json().await.unwrap();assert_eq!(value["queued"],true);
        if let Some(ref before)=first{assert_eq!(before,&value)}else{first=Some(value)}
    }
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM rust_telegram_outbox").fetch_one(&mut c).await.unwrap(),1);
    let saved=telegram::claim_delivery(&mut c,&settings).await.unwrap().unwrap();
    // A dispatched send with no receipt remains quarantined as sending. A
    // repeated MCP request retains that row and cannot admit a second send.
    assert_eq!(http.post(&target).bearer_auth(HOST_TOKEN).json(&json!({})).send().await.unwrap().status(),200);
    assert!(telegram::claim_delivery(&mut c,&settings).await.unwrap().is_none());
    assert_eq!(sqlx::query_scalar::<_,String>("SELECT state FROM rust_telegram_outbox WHERE id=$1").bind(saved.id).fetch_one(&mut c).await.unwrap(),"sending");
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_packets").fetch_one(&mut c).await.unwrap(),0);
    stop.cancel();server.await.unwrap();
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn actual_mcp_stdio_handshake_catalog_and_tool_calls_use_authenticated_api_without_secrets(){
    use tokio::io::{AsyncBufReadExt,AsyncWriteExt,BufReader};
    use std::{os::unix::fs::PermissionsExt,process::Stdio};
    let mut c=knowledge_fixture().await;
    let id=Uuid::new_v4();sqlx::query("INSERT INTO jobs(id,title,job_url,source_platform)VALUES($1,'Fictional Instahyre role','https://example.com/fictional','instahyre')").bind(id).execute(&mut c).await.unwrap();
    let (values,_socket_directory,stop,server)=unix_http_fixture().await;
    let temp=tempfile::tempdir().unwrap();let path=temp.path().join("fictional.private.env");
    let raw=values.into_iter().map(|(k,v)|format!("{k}='{v}'\n")).collect::<String>();
    std::fs::write(&path,raw).unwrap();std::fs::set_permissions(&path,std::fs::Permissions::from_mode(0o600)).unwrap();
    let mut child=tokio::process::Command::new(env!("CARGO_BIN_EXE_automated-apply-tools")).arg("--config").arg(&path).env_clear().env("PATH","/usr/bin:/bin").stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null()).kill_on_drop(true).spawn().unwrap();
    let mut input=child.stdin.take().unwrap();let mut lines=BufReader::new(child.stdout.take().unwrap()).lines();
    for (message,expected) in [
        (json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"fictional-test","version":"1"}}}),1),
        (json!({"jsonrpc":"2.0","id":2,"method":"tools/list"}),2),
        (json!({"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"instahyre_saved_jobs","arguments":{"limit":2}}}),3),
        (json!({"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"browser_readiness","arguments":{}}}),4),
        (json!({"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"telegram_notify_run","arguments":{"run_id":Uuid::new_v4(),"text":"injected"}}}),5),
    ]{
        input.write_all(format!("{message}\n").as_bytes()).await.unwrap();input.flush().await.unwrap();
        let line=tokio::time::timeout(Duration::from_secs(5),lines.next_line()).await.unwrap().unwrap().unwrap();
        assert!(!line.contains(HOST_TOKEN));assert!(!line.contains("private-fictional"));
        let response:Value=serde_json::from_str(&line).unwrap();assert_eq!(response["id"],expected);
        match expected{
            1=>{assert_eq!(response["result"]["serverInfo"]["name"],"automated-apply-tools");input.write_all(b"{\"jsonrpc\":\"2.0\",\"method\":\"notifications/initialized\"}\n").await.unwrap();},
            2=>{let tools=response["result"]["tools"].as_array().unwrap();let mut names=tools.iter().map(|t|t["name"].as_str().unwrap()).collect::<Vec<_>>(); names.sort(); let mut expected=vec!["runtime_status","browser_readiness","naukri_saved_jobs","instahyre_saved_jobs","application_history","telegram_status","match_saved_job","himalayas_discover","we_work_remotely_discover","internshala_saved_jobs","wellfound_saved_jobs","ycombinator_saved_jobs","hiringcafe_saved_jobs","himalayas_saved_jobs","we_work_remotely_saved_jobs","himalayas_ingest","we_work_remotely_ingest"]; expected.sort(); assert_eq!(names,expected);assert!(tools.iter().all(|tool|tool["annotations"]["readOnlyHint"]==!tool["name"].as_str().unwrap().ends_with("_ingest")));},
            3=>{assert_eq!(response["result"]["structuredContent"]["jobs"][0]["id"],json!(id));assert_eq!(response["result"]["structuredContent"]["application_dispatch"],false);},
            4=>{assert_eq!(response["result"]["structuredContent"]["selected"],"brave");assert_eq!(response["result"]["structuredContent"]["browser_launched"],false);},
            5=>assert!(response["error"].is_object()||response["result"]["isError"]==true),
            _=>unreachable!(),
        }
    }
    drop(input);assert!(tokio::time::timeout(Duration::from_secs(5),child.wait()).await.unwrap().unwrap().success());
    assert_eq!(sqlx::query_scalar::<_,i64>("SELECT count(*) FROM application_packets").fetch_one(&mut c).await.unwrap(),0);
    stop.cancel();server.await.unwrap();
}
