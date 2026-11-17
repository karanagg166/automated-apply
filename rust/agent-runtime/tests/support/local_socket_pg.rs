async fn unix_http_fixture() -> (BTreeMap<String,String>,tempfile::TempDir,CancellationToken,tokio::task::JoinHandle<()>) {
    unix_http_fixture_values(BTreeMap::new()).await
}
async fn unix_http_fixture_values(custom:BTreeMap<String,String>) -> (BTreeMap<String,String>,tempfile::TempDir,CancellationToken,tokio::task::JoinHandle<()>) {
    use automated_apply_agents::local_socket::{BoundSocket,OwnerPeer};
    let directory=tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(),std::fs::Permissions::from_mode(0o700)).unwrap();
    let path=std::fs::canonicalize(directory.path()).unwrap().join("api.sock");
    let mut values=host_values();
    values.extend(custom);
    values.insert("API_REQUIRE_TLS".into(),"true".into());
    values.insert("RUST_AGENT_TRUST_LOOPBACK_PROXY".into(),"false".into());
    values.insert("API_ALLOWED_HOSTS".into(),r#"["runtime.example.net"]"#.into());
    values.insert("RUST_AGENT_LISTEN".into(),"127.0.0.1:18011".into());
    values.insert("RUST_AGENT_UNIX_SOCKET".into(),path.to_str().unwrap().into());
    let config=Arc::new(Configuration::from_values(&values).unwrap());
    let mut c=config.connect(false).await.unwrap();server::readiness(&mut c,&config).await.unwrap();
    let mut bound=BoundSocket::bind(&path).await.unwrap();let listener=bound.listener.take().unwrap();
    let api=Api::new(config,c,Wake::default());let stop=CancellationToken::new();let shutdown=stop.clone();
    let task=tokio::spawn(async move {
        axum::serve(listener,server::router(api).into_make_service_with_connect_info::<OwnerPeer>()).with_graceful_shutdown(shutdown.cancelled_owned()).await.unwrap();
        drop(bound);
    });
    (values,directory,stop,task)
}
#[tokio::test(flavor="current_thread")]
#[ignore="requires dedicated disposable PostgreSQL harness"]
async fn actual_mcp_private_socket_authentication_preserves_bearer_origin_host_and_tcp_tls_guards() {
    let _source=knowledge_fixture().await;
    let (values,_directory,stop,task)=unix_http_fixture().await;
    let socket=values["RUST_AGENT_UNIX_SOCKET"].clone();
    let http=reqwest::Client::builder().no_proxy().redirect(reqwest::redirect::Policy::none()).retry(reqwest::retry::never()).unix_socket(socket.as_str()).timeout(Duration::from_secs(2)).build().unwrap();
    let url="http://127.0.0.1:18011/api/v1/rust-agent/capabilities";
    assert_eq!(http.get(url).send().await.unwrap().status(),401);
    assert_eq!(http.get(url).bearer_auth("wrong").send().await.unwrap().status(),401);
    assert_eq!(http.get(url).bearer_auth(HOST_TOKEN).send().await.unwrap().status(),200);
    for (header,value) in [("origin","https://untrusted.example.net"),("host","attacker.example.net"),("host","127.0.0.1:18012"),("x-agent-client","fake-owner")] {
        assert_eq!(http.get(url).bearer_auth(HOST_TOKEN).header(header,value).send().await.unwrap().status(),403);
    }
    // Headers asserting TLS or IPC never authorize an ordinary plaintext TCP caller.
    let (tcp,tcp_stop,tcp_task)=http_fixture_values(values).await;
    let response=client().get(format!("{tcp}/api/v1/rust-agent/capabilities")).header("host","runtime.example.net").header("x-forwarded-proto","https").header("x-private-peer","owner").bearer_auth(HOST_TOKEN).send().await.unwrap();
    assert_eq!(response.status(),426);
    tcp_stop.cancel();tcp_task.await.unwrap();stop.cancel();task.await.unwrap();assert!(!std::path::Path::new(&socket).exists());
}
