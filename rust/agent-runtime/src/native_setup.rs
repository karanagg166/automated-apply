//! Stage the browser companion configuration from the exact candidate runtime settings.
use crate::{Failure, Result, configuration::Configuration};
use std::{
    fs::{self, OpenOptions},
    io::Write,
    os::unix::fs::{MetadataExt, OpenOptionsExt},
    path::Path,
};

const CONFIG_FILE: &str = "automated-apply-native.private.env";

pub fn prepare(config_path: &Path, output: &Path) -> Result<()> {
    let config = Configuration::load(config_path)?;
    // The live legacy Telegram poller is off for the initial laptop cutover.
    if config.telegram_enabled() {
        return Err(Failure("initial_cutover_requires_telegram_disabled"));
    }
    let id = config
        .browser_profiles
        .extension
        .as_deref()
        .filter(|id| config.browser_profiles.permits(Some(id)))
        .ok_or(Failure("cutover_native_extension_not_enabled"))?;
    let path = config
        .local_socket()
        .and_then(Path::to_str)
        .ok_or(Failure("cutover_private_socket_required"))?;
    if config.listen().port() <= 1024 || path.chars().any(char::is_control) {
        return Err(Failure("cutover_private_socket_required"));
    }
    let metadata = output.symlink_metadata().map_err(output_error)?;
    if !output.is_absolute()
        || !metadata.is_dir()
        || metadata.uid() != automated_apply_local_ipc::owner_uid()
        || metadata.mode() & 0o777 != 0o700
        || output.canonicalize().map_err(output_error)? != output
    {
        return Err(Failure("private_native_configuration_output_required"));
    }
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW)
        .open(output.join(CONFIG_FILE))
        .map_err(output_error)?;
    for (key, value) in [
        ("CHROME_NATIVE_MESSAGING_ENABLED", "true"),
        ("CHROME_EXTENSION_ID", id),
        ("JOB_AGENT_API_TOKEN", &config.token),
        (
            "LOCAL_AGENT_ENDPOINT",
            &format!("http://{}", config.listen()),
        ),
        ("LOCAL_AGENT_UNIX_SOCKET", path),
    ] {
        let literal = value
            .replace('\\', "\\\\")
            .replace('"', "\\\"")
            .replace('$', "\\$");
        writeln!(file, "{key}=\"{literal}\"").map_err(output_error)?;
    }
    file.sync_all().map_err(output_error)?;
    // The approval key, database credentials and other provider settings stay in runtime.env.
    println!(
        "{}",
        serde_json::json!({
            "extension_id": id,
            "fixture": config.is_fixture(),
            "telegram_enabled": false,
        })
    );
    Ok(())
}

fn output_error(_: std::io::Error) -> Failure {
    Failure("private_native_configuration_output_unavailable")
}
