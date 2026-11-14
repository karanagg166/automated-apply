#[tokio::main(flavor = "current_thread")]
async fn main() -> std::process::ExitCode {
    let args = std::env::args_os().skip(1).collect::<Vec<_>>();
    let result = match args.as_slice() {
        [flag, path] if flag == "--config" => {
            automated_apply_agents::mcp_bridge::serve(std::path::Path::new(path)).await
        }
        _ => Err(automated_apply_agents::Failure(
            "private_mcp_configuration_required",
        )),
    };
    match result {
        Ok(()) => std::process::ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("{}", error.0);
            std::process::ExitCode::FAILURE
        }
    }
}
