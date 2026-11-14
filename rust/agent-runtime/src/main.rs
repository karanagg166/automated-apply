//! Private localhost service host. Never auto-migrates or loads an ambient env file.
use automated_apply_agents::{
    Failure, Result,
    configuration::Configuration,
    process_lock::ProcessLock,
    server::{self, Api},
    worker::{self, Wake},
};
use std::{path::PathBuf, sync::Arc};
use tokio_util::sync::CancellationToken;

#[tokio::main(flavor = "current_thread")]
async fn main() -> std::process::ExitCode {
    match run().await {
        Ok(()) => std::process::ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("{}", error.0);
            std::process::ExitCode::FAILURE
        }
    }
}
async fn run() -> Result<()> {
    let arguments = std::env::args_os().skip(1).collect::<Vec<_>>();
    if !(arguments.len() == 3 || arguments.len() == 5)
        || arguments[0] != "serve"
        || arguments[1] != "--config"
        || (arguments.len() == 5 && arguments[3] != "--fixture-lock-directory")
    {
        return Err(Failure("usage_serve_config_absolute_private_path"));
    }
    let config = Arc::new(Configuration::load(&PathBuf::from(&arguments[2]))?);
    let fixture_directory = arguments.get(4).map(PathBuf::from);
    let _lease = ProcessLock::acquire(&config, fixture_directory.as_deref())?;
    let mut control = config.connect(false).await?;
    server::readiness(&mut control, &config).await?;
    let mut execution = config.connect(true).await?;
    let listener = tokio::net::TcpListener::bind(config.listen())
        .await
        .map_err(|_| Failure("loopback_listener_unavailable"))?;
    let address = listener
        .local_addr()
        .map_err(|_| Failure("loopback_listener_unavailable"))?;
    let wake = Wake::default();
    let shutdown = CancellationToken::new();
    let api = Api::new(config, control, wake.clone());
    let mut terminate = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
        .map_err(|_| Failure("shutdown_signal_unavailable"))?;
    println!(
        "{}",
        serde_json::json!({"event":"rust_agent_ready","address":address.to_string(),"scope":"saved_job_review_no_application_dispatch"})
    );
    let http = async {
        let result = axum::serve(
            listener,
            server::router(api).into_make_service_with_connect_info::<std::net::SocketAddr>(),
        )
        .with_graceful_shutdown(shutdown.clone().cancelled_owned())
        .await
        .map_err(|_| Failure("owner_server_failed"));
        shutdown.cancel();
        result
    };
    let executor = async {
        let result = worker::serve(&mut execution, wake, shutdown.clone()).await;
        shutdown.cancel();
        result
    };
    let signals = async {
        tokio::select! {_=tokio::signal::ctrl_c()=>{},_=terminate.recv()=>{},_=shutdown.cancelled()=>{}}
        shutdown.cancel();
    };
    let (http, executor, ()) = tokio::join!(http, executor, signals);
    http?;
    executor
}
