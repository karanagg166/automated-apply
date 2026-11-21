//! Private localhost service host. Never auto-migrates or loads an ambient env file.
use automated_apply_agents::{
    Failure, Result,
    configuration::Configuration,
    process_lock::ProcessLock,
    recovery,
    server::{self, Api},
    telegram,
    worker::Wake,
};
use std::{path::PathBuf, sync::Arc};
use tokio_util::sync::CancellationToken;

mod cutover;

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
    if arguments.len() == 5
        && arguments[0] == "prepare-native-config"
        && arguments[1] == "--config"
        && arguments[3] == "--output-directory"
    {
        return automated_apply_agents::native_setup::prepare(
            &PathBuf::from(&arguments[2]),
            &PathBuf::from(&arguments[4]),
        );
    }
    if arguments.len() == 3 && arguments[0] == "cutover-preflight" && arguments[1] == "--config" {
        return cutover::report(&PathBuf::from(&arguments[2])).await;
    }
    if (arguments.len() == 5 || arguments.len() == 6 && arguments[5] == "--apply")
        && arguments[0] == "replace-fixed-brave-profile"
        && arguments[1] == "--config"
        && arguments[3] == "--review"
    {
        return automated_apply_agents::browser_profiles::pin_replacement::run(
            &PathBuf::from(&arguments[2]),
            &PathBuf::from(&arguments[4]),
            arguments.len() == 6,
        )
        .await;
    }
    if arguments.len() == 3 && arguments[0] == "provider-status" && arguments[1] == "--config" {
        let result =
            automated_apply_agents::provider_status::check(&PathBuf::from(&arguments[2])).await?;
        println!(
            "{}",
            serde_json::to_string(&result).map_err(|_| Failure("invalid_provider_metadata"))?
        );
        return Ok(());
    }
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
    let _writer = ProcessLock::acquire_writer(&config, fixture_directory.as_deref())?;
    let _telegram_lease = if config.telegram_enabled() {
        Some(ProcessLock::acquire_telegram(
            &config,
            fixture_directory.as_deref(),
        )?)
    } else {
        None
    };
    let mut local_socket = match config.local_socket() {
        Some(path) => Some(automated_apply_agents::local_socket::BoundSocket::bind(path).await?),
        None => None,
    };
    let mut control = config.connect(false).await?;
    server::readiness(&mut control, &config).await?;
    let execution = config.connect(true).await?;
    let relay = telegram::prepare(&config).await?;
    let listener = tokio::net::TcpListener::bind(config.listen())
        .await
        .map_err(|_| Failure("loopback_listener_unavailable"))?;
    let address = listener
        .local_addr()
        .map_err(|_| Failure("loopback_listener_unavailable"))?;
    let wake = Wake::default();
    let shutdown = CancellationToken::new();
    let api = Api::new(config.clone(), control, wake.clone());
    let mut terminate = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
        .map_err(|_| Failure("shutdown_signal_unavailable"))?;
    println!(
        "{}",
        serde_json::json!({"event":"rust_agent_ready","address":address.to_string(),"scope":"owner_policy_fenced_runtime"})
    );
    let http = async {
        let result = axum::serve(
            listener,
            server::router(api.clone())
                .into_make_service_with_connect_info::<std::net::SocketAddr>(),
        )
        .with_graceful_shutdown(shutdown.clone().cancelled_owned())
        .await
        .map_err(|_| Failure("owner_server_failed"));
        shutdown.cancel();
        result
    };
    let local_http = async {
        if let Some(bound) = local_socket.as_mut() {
            let listener = bound
                .listener
                .take()
                .ok_or(Failure("private_socket_bind_failed"))?;
            let result=axum::serve(listener,server::router(api.clone()).into_make_service_with_connect_info::<automated_apply_agents::local_socket::OwnerPeer>()).with_graceful_shutdown(shutdown.clone().cancelled_owned()).await.map_err(|_|Failure("owner_server_failed"));
            shutdown.cancel();
            result
        } else {
            shutdown.cancelled().await;
            Ok(())
        }
    };
    let executor = async {
        let result = recovery::supervise(&config, execution, wake.clone(), shutdown.clone()).await;
        shutdown.cancel();
        result
    };
    let signals = async {
        tokio::select! {_=tokio::signal::ctrl_c()=>{},_=terminate.recv()=>{},_=shutdown.cancelled()=>{}}
        shutdown.cancel();
    };
    let telegram = async {
        let result = match relay {
            Some(relay) => relay.run(&config, wake.clone(), shutdown.clone()).await,
            None => {
                shutdown.cancelled().await;
                Ok(())
            }
        };
        shutdown.cancel();
        result
    };
    let queue_generation = async {
        let result = server::serve_queue_generation(api.clone(), shutdown.clone()).await;
        shutdown.cancel();
        result
    };
    let (http, local_http, executor, telegram, queue_generation, ()) = tokio::join!(
        http,
        local_http,
        executor,
        telegram,
        queue_generation,
        signals
    );
    // A handler that was already running when SIGTERM arrived may have changed
    // control after the worker stopped. Reconcile only after every handler drains.
    tokio::time::timeout(std::time::Duration::from_secs(5), server::quiesce(&api))
        .await
        .map_err(|_| Failure("shutdown_pause_unconfirmed"))?
        .map_err(|_| Failure("shutdown_pause_unconfirmed"))?;
    http?;
    local_http?;
    telegram?;
    queue_generation?;
    executor
}
