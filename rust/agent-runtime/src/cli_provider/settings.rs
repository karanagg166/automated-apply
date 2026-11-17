use crate::{Failure, Result, configuration::boolean};
use serde_json::Value;
use std::{
    collections::BTreeMap,
    fs,
    io::Read,
    os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt},
    path::{Path, PathBuf},
    sync::Arc,
    time::Duration,
};
pub(super) const AGENT: &str = include_str!("../../schemas/agy-agent.md");
#[derive(Clone)]
pub(crate) struct CliModel {
    pub(super) executable: PathBuf,
    pub(super) home: PathBuf,
    pub(super) model: String,
    pub(super) effort: String,
    pub(super) timeout: Duration,
    pub(super) input: usize,
    pub(super) output: u32,
    pub(super) requests: u32,
    pub(crate) gate: Arc<tokio::sync::Semaphore>,
}
impl CliModel {
    pub(crate) fn from_values(values: &BTreeMap<String, String>, fixture: bool) -> Result<Self> {
        if !boolean(values, "AGY_ENABLED", false)?
            || !boolean(values, "AGY_QUOTA_AUTHORIZED", false)?
        {
            return Err(Failure("provider_execution_not_authorized"));
        }
        let model = values
            .get("AGY_MODEL")
            .filter(|s| {
                !s.is_empty()
                    && s.len() <= 121
                    && s.as_bytes()[0].is_ascii_alphanumeric()
                    && s.bytes()
                        .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
            })
            .ok_or(Failure("explicit_model_required"))?
            .clone();
        let effort = values
            .get("AGY_EFFORT")
            .map(String::as_str)
            .unwrap_or("high");
        if !["low", "medium", "high", "xhigh", "max"].contains(&effort) {
            return Err(Failure("invalid_provider_configuration"));
        }
        let executable = PathBuf::from(
            values
                .get("AGY_EXECUTABLE")
                .map(String::as_str)
                .unwrap_or("/opt/homebrew/bin/agy"),
        );
        if !executable.is_absolute() {
            return Err(Failure("cli_unavailable"));
        }
        let home = match values.get("RUST_AGY_FIXTURE_HOME") {
            Some(path) if fixture && Path::new(path).is_absolute() => PathBuf::from(path),
            Some(_) => return Err(Failure("provider_fixture_home_denied")),
            None => std::env::var_os("HOME")
                .map(PathBuf::from)
                .filter(|p| p.is_absolute())
                .ok_or(Failure("cli_owner_home_unavailable"))?,
        };
        let seconds = values
            .get("AGY_TIMEOUT_SECONDS")
            .map(|s| s.parse::<f64>().unwrap_or(f64::NAN))
            .unwrap_or(60.0);
        if !seconds.is_finite() || !(1.0..=120.0).contains(&seconds) {
            return Err(Failure("invalid_provider_configuration"));
        }
        fn number(
            values: &BTreeMap<String, String>,
            key: &str,
            default: u32,
            min: u32,
            max: u32,
        ) -> Result<u32> {
            values
                .get(key)
                .map(|s| {
                    s.parse::<u32>()
                        .ok()
                        .filter(|n| (min..=max).contains(n))
                        .ok_or(Failure("invalid_provider_configuration"))
                })
                .unwrap_or(Ok(default))
        }
        Ok(Self {
            executable,
            home,
            model,
            effort: effort.into(),
            timeout: Duration::from_secs_f64(seconds),
            input: number(values, "LLM_MAX_INPUT_CHARS", 16000, 1000, 64000)? as usize,
            output: number(values, "LLM_MAX_OUTPUT_TOKENS", 1000, 64, 8192)?,
            requests: number(values, "LLM_MONTHLY_MAX_REQUESTS", 200, 0, 10000)?,
            gate: Arc::new(tokio::sync::Semaphore::new(1)),
        })
    }
    pub(super) fn workspace(&self) -> PathBuf {
        self.home
            .join("Library/Application Support/Automated Apply/agy-answer-workspace")
    }
    pub(super) fn verify(&self) -> Result<()> {
        let executable = fs::metadata(&self.executable).map_err(|_| Failure("cli_unavailable"))?;
        if !executable.is_file()
            || executable.mode() & 0o111 == 0
            || executable.mode() & 0o022 != 0
            || ![0, unsafe { libc::geteuid() }].contains(&executable.uid())
        {
            return Err(Failure("cli_unavailable"));
        }
        let workspace = self.workspace();
        private_dir(&workspace).map_err(|_| Failure("owner_workspace_authorization_required"))?;
        let raw = private_file(
            &self.home.join(".gemini/antigravity-cli/settings.json"),
            65536,
        )
        .map_err(|_| Failure("quota_billing_configuration_unverified"))?;
        let config: Value = serde_json::from_slice(&raw)
            .map_err(|_| Failure("quota_billing_configuration_unverified"))?;
        if !config.is_object()
            || config.get("useG1Credits").is_some_and(|v| v != false)
            || ["modelProvider", "gcp", "customModelsConfig"]
                .iter()
                .any(|key| super::protocol::truthy(config.get(*key)))
        {
            return Err(Failure("paid_overage_configuration_forbidden"));
        }
        if !config["trustedWorkspaces"]
            .as_array()
            .is_some_and(|a| a.iter().any(|v| v.as_str() == workspace.to_str()))
        {
            return Err(Failure("owner_workspace_authorization_required"));
        }
        for path in [
            self.home
                .join(".gemini/config/agents/automated-apply-answer.md"),
            workspace.join(".agents/agents/automated-apply-answer.md"),
        ] {
            if private_file(&path, 32768)
                .map_err(|_| Failure("restricted_agent_profile_unavailable"))?
                != AGENT.as_bytes()
            {
                return Err(Failure("restricted_agent_profile_unavailable"));
            }
        }
        Ok(())
    }
    pub(super) fn environment(&self) -> BTreeMap<String, String> {
        let mut env = BTreeMap::from([
            (
                "PATH".into(),
                "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin".into(),
            ),
            ("HOME".into(), self.home.to_string_lossy().into()),
            ("LANG".into(), "en_US.UTF-8".into()),
            ("AGY_CLI_DISABLE_AUTO_UPDATE".into(), "1".into()),
        ]);
        if let Some(user) = std::env::var_os("USER")
            .and_then(|s| s.into_string().ok())
            .filter(|s| !s.chars().any(char::is_control))
        {
            env.insert("USER".into(), user);
        }
        env
    }
}
pub(super) fn private_dir(path: &Path) -> Result<()> {
    let m = fs::symlink_metadata(path).map_err(|_| Failure("cli_private_file_unavailable"))?;
    if !m.is_dir()
        || m.file_type().is_symlink()
        || m.uid() != unsafe { libc::geteuid() }
        || m.mode() & 0o077 != 0
    {
        return Err(Failure("cli_private_file_unavailable"));
    }
    Ok(())
}
fn private_file(path: &Path, limit: u64) -> Result<Vec<u8>> {
    let file = fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)
        .map_err(|_| Failure("cli_private_file_unavailable"))?;
    let m = file
        .metadata()
        .map_err(|_| Failure("cli_private_file_unavailable"))?;
    if !m.is_file()
        || m.uid() != unsafe { libc::geteuid() }
        || m.mode() & 0o077 != 0
        || m.len() > limit
    {
        return Err(Failure("cli_private_file_unavailable"));
    }
    let mut bytes = vec![];
    file.take(limit + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| Failure("cli_private_file_unavailable"))?;
    if bytes.len() as u64 > limit {
        return Err(Failure("cli_private_file_unavailable"));
    }
    Ok(bytes)
}
pub(super) fn scratch(model: &CliModel) -> Result<PathBuf> {
    let path = model
        .workspace()
        .join(format!("rust-request-{}", uuid::Uuid::new_v4()));
    use std::os::unix::fs::DirBuilderExt;
    fs::DirBuilder::new()
        .mode(0o700)
        .create(&path)
        .map_err(|_| Failure("cli_private_file_unavailable"))?;
    fs::set_permissions(&path, fs::Permissions::from_mode(0o700))
        .map_err(|_| Failure("cli_private_file_unavailable"))?;
    Ok(path)
}
pub(super) fn write_schema(path: &Path) -> Result<()> {
    use std::io::Write;
    let bytes = serde_json::to_vec(&crate::provider::answer_schema())
        .map_err(|_| Failure("unsupported_provider_schema"))?;
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)
        .map_err(|_| Failure("cli_private_file_unavailable"))?;
    file.write_all(&bytes)
        .map_err(|_| Failure("cli_private_file_unavailable"))
}
