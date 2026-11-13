//! Chrome native messaging transport. Authorization remains at the backend boundary.
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::BTreeMap,
    fs::File,
    io::{Read, Write},
    os::{
        fd::{AsRawFd, FromRawFd},
        unix::fs::{MetadataExt, OpenOptionsExt},
    },
    path::Path,
    time::{Duration, Instant},
};
use uuid::Uuid;

pub const MAX_MESSAGE_BYTES: usize = 262_144;
pub const READ_TIMEOUT: Duration = Duration::from_secs(10);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Failure(pub &'static str);
pub type Result<T> = std::result::Result<T, Failure>;

pub const PROFILE_OPERATIONS: &[&str] = &[
    "connect_chrome_profile",
    "heartbeat_chrome_profile",
    "disconnect_chrome_profile",
    "poll_chrome_command",
    "start_chrome_command",
    "ack_chrome_command",
];
pub const QUEUE_OPERATIONS: &[&str] = &[
    "poll_naukri_work",
    "bind_naukri_work",
    "admit_naukri_work",
    "finish_naukri_work",
    "abandon_naukri_work",
    "check_naukri_work",
    "naukri_queue_status",
    "naukri_queue_control",
];
pub const OTHER_OPERATIONS: &[&str] = &[
    "health",
    "connection_status",
    "get_agent_capabilities",
    "preview_application_url",
    "observe_platform_session",
    "inspect_form",
    "prepare_form_answers",
    "authorize_form",
    "record_form_fill",
    "open_application_task",
    "get_application_task",
    "update_application_task",
    "ask_form_questions",
];
fn command_schema() -> &'static jsonschema::Validator {
    static SCHEMA: std::sync::OnceLock<jsonschema::Validator> = std::sync::OnceLock::new();
    SCHEMA.get_or_init(|| {
        let schema: Value = serde_json::from_str(include_str!("../schemas/command.json"))
            .expect("checked-in public command schema");
        jsonschema::draft202012::options()
            .should_validate_formats(true)
            .build(&schema)
            .expect("valid public command schema")
    })
}

// Intentionally never Debug: this holds a bearer token.
pub struct Configuration {
    token: String,
    extension_id: String,
    endpoint: String,
}
impl Configuration {
    pub fn load(path: &Path, origin: &str) -> Result<Self> {
        if !path.is_absolute() {
            return Err(Failure("native_private_configuration_required"));
        }
        let file = File::options()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(path)
            .map_err(|_| Failure("native_private_configuration_required"))?;
        let meta = file
            .metadata()
            .map_err(|_| Failure("native_private_configuration_required"))?;
        // SAFETY: geteuid has no preconditions or pointer arguments.
        if !meta.is_file()
            || meta.mode() & 0o077 != 0
            || meta.uid() != unsafe { libc::geteuid() }
            || meta.len() > 1_048_576
        {
            return Err(Failure("native_private_configuration_required"));
        }
        let vars: BTreeMap<String, String> = dotenvy::from_read_iter(file)
            .collect::<std::result::Result<_, _>>()
            .map_err(|_| Failure("native_configuration_error"))?;
        Self::from_values(&vars, origin)
    }
    pub fn from_values(vars: &BTreeMap<String, String>, origin: &str) -> Result<Self> {
        let extension_id = vars
            .get("CHROME_EXTENSION_ID")
            .filter(|s| s.len() == 32 && s.bytes().all(|b| (b'a'..=b'p').contains(&b)))
            .ok_or(Failure("native_not_configured"))?
            .clone();
        if origin != format!("chrome-extension://{extension_id}/") {
            return Err(Failure("native_origin_denied"));
        }
        if !vars
            .get("CHROME_NATIVE_MESSAGING_ENABLED")
            .is_some_and(|x| matches!(x.to_ascii_lowercase().as_str(), "true" | "1" | "yes" | "on"))
        {
            return Err(Failure("native_not_configured"));
        }
        let token = vars
            .get("JOB_AGENT_API_TOKEN")
            .filter(|s| !s.is_empty() && !s.chars().any(char::is_control))
            .ok_or(Failure("native_not_configured"))?
            .clone();
        let endpoint = vars
            .get("LOCAL_AGENT_ENDPOINT")
            .map(String::as_str)
            .unwrap_or("http://127.0.0.1:8000");
        let url =
            reqwest::Url::parse(endpoint).map_err(|_| Failure("native_configuration_error"))?;
        // No DNS, proxy, remote credential forwarding, redirect or TLS downgrade.
        if url.scheme() != "http"
            || url.host_str() != Some("127.0.0.1")
            || url.port().is_none()
            || !url.username().is_empty()
            || url.password().is_some()
            || url.query().is_some()
            || url.fragment().is_some()
            || url.path() != "/"
        {
            return Err(Failure("native_configuration_error"));
        }
        Ok(Self {
            token,
            extension_id,
            endpoint: endpoint.trim_end_matches('/').to_owned(),
        })
    }
}

// Avoid Debug/Display of incoming data: profile secrets and private facts may be present.
pub struct Command {
    pub request_id: Uuid,
    pub operation: String,
    payload: Value,
}
impl Command {
    pub fn parse(bytes: &[u8]) -> Result<Self> {
        let mut payload: Value =
            serde_json::from_slice(bytes).map_err(|_| Failure("native_invalid_message"))?;
        if !command_schema().is_valid(&payload) {
            return Err(Failure("native_invalid_message"));
        }
        let obj = payload
            .as_object_mut()
            .ok_or(Failure("native_invalid_message"))?;
        let request_id = match obj.get("request_id") {
            Some(Value::String(s)) => {
                Uuid::parse_str(s).map_err(|_| Failure("native_invalid_message"))?
            }
            None => Uuid::new_v4(),
            _ => return Err(Failure("native_invalid_message")),
        };
        let operation = obj
            .get("command")
            .and_then(Value::as_str)
            .ok_or(Failure("native_invalid_message"))?
            .to_owned();
        if !PROFILE_OPERATIONS.contains(&operation.as_str())
            && !QUEUE_OPERATIONS.contains(&operation.as_str())
            && !OTHER_OPERATIONS.contains(&operation.as_str())
        {
            return Err(Failure("native_capability_denied"));
        }
        obj.insert(
            "request_id".to_owned(),
            Value::String(request_id.to_string()),
        );
        obj.insert("version".to_owned(), Value::from(1));
        // Public JSON schema is checked here; cross-field and business validators remain at the authenticated backend.
        // The bridge does not reinterpret reports, grants, personal facts or policy.
        Ok(Self {
            request_id,
            operation,
            payload,
        })
    }
    pub fn retry_allowed(&self) -> bool {
        PROFILE_OPERATIONS.contains(&self.operation.as_str())
            || QUEUE_OPERATIONS.contains(&self.operation.as_str())
            || [
                "get_application_task",
                "open_application_task",
                "update_application_task",
                "inspect_form",
                "prepare_form_answers",
            ]
            .contains(&self.operation.as_str())
    }
}

pub fn read_frame(mut read_exact: impl FnMut(&mut [u8]) -> Result<()>) -> Result<Command> {
    let mut header = [0; 4];
    read_exact(&mut header)?;
    let size = u32::from_le_bytes(header) as usize;
    if size == 0 || size > MAX_MESSAGE_BYTES {
        return Err(Failure("native_message_size"));
    }
    let mut bytes = vec![0; size];
    read_exact(&mut bytes)?;
    Command::parse(&bytes)
}

pub fn read_pipe_exact(
    file: &mut impl Read,
    fd: i32,
    mut bytes: &mut [u8],
    timeout: Duration,
) -> Result<()> {
    while !bytes.is_empty() {
        let deadline = Instant::now() + timeout;
        loop {
            let mut poll = libc::pollfd {
                fd,
                events: libc::POLLIN,
                revents: 0,
            };
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err(Failure("native_read_timeout"));
            }
            // SAFETY: poll points to exactly one valid pollfd, alive for the call.
            let status = unsafe {
                libc::poll(
                    &mut poll,
                    1,
                    remaining.as_millis().max(1).min(i32::MAX as u128) as i32,
                )
            };
            if status == 0 {
                return Err(Failure("native_read_timeout"));
            }
            if status < 0 {
                if std::io::Error::last_os_error().kind() == std::io::ErrorKind::Interrupted {
                    continue;
                }
                return Err(Failure("native_truncated_message"));
            }
            break;
        }
        match file.read(bytes) {
            Ok(0) => return Err(Failure("native_truncated_message")),
            Ok(n) => bytes = &mut bytes[n..],
            Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(_) => return Err(Failure("native_truncated_message")),
        }
    }
    Ok(())
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct BackendResult {
    #[serde(default = "version_one")]
    version: u8,
    request_id: Uuid,
    #[serde(default = "Uuid::new_v4")]
    correlation_id: Uuid,
    ok: bool,
    capability: String,
    #[serde(default)]
    error_code: Option<String>,
    #[serde(default)]
    data: BTreeMap<String, Value>,
}
fn version_one() -> u8 {
    1
}

pub fn forward(command: &Command, config: &Configuration) -> Result<Value> {
    let client = reqwest::blocking::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|_| Failure("native_configuration_error"))?;
    let deadline = Instant::now() + Duration::from_secs(35);
    for attempt in 0..3 {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return Err(Failure("backend_timeout"));
        }
        let mut response = client
            .post(format!("{}/api/v1/local-agent/chrome", config.endpoint))
            .header("Authorization", format!("Bearer {}", config.token))
            .header("X-Agent-Client", &config.extension_id)
            .json(&command.payload)
            .timeout(remaining)
            .send()
            .map_err(transport_failure)?;
        if response.status() != 200 {
            let status = response.status().as_u16();
            let rolled_back = status == 503
                && command.retry_allowed()
                && response
                    .headers()
                    .get("X-Automated-Apply-Transaction")
                    .is_some_and(|v| v == "rolled-back");
            if rolled_back && attempt < 2 && Instant::now() + Duration::from_secs(1) < deadline {
                drop(response);
                std::thread::sleep(Duration::from_millis(200 * (attempt + 1)));
                continue;
            }
            return Err(Failure(if matches!(status, 401 | 403) {
                "backend_authentication_failed"
            } else if rolled_back {
                "backend_transaction_rolled_back"
            } else {
                "backend_not_ready"
            }));
        }
        if response
            .content_length()
            .is_some_and(|n| n > MAX_MESSAGE_BYTES as u64)
        {
            return Err(Failure("native_response_size"));
        }
        let mut bytes = Vec::new();
        response
            .by_ref()
            .take((MAX_MESSAGE_BYTES + 1) as u64)
            .read_to_end(&mut bytes)
            .map_err(|e| {
                Failure(
                    if e.kind() == std::io::ErrorKind::TimedOut
                        || e.get_ref()
                            .and_then(|e| e.downcast_ref::<reqwest::Error>())
                            .is_some_and(reqwest::Error::is_timeout)
                    {
                        "backend_timeout"
                    } else {
                        "backend_offline"
                    },
                )
            })?;
        if bytes.len() > MAX_MESSAGE_BYTES {
            return Err(Failure("native_response_size"));
        }
        let result: BackendResult =
            serde_json::from_slice(&bytes).map_err(|_| Failure("backend_invalid_response"))?;
        if result.version != 1 {
            return Err(Failure("backend_invalid_response"));
        }
        if result.request_id != command.request_id {
            return Err(Failure("native_request_id_mismatch"));
        }
        return serde_json::to_value(result).map_err(|_| Failure("backend_invalid_response"));
    }
    Err(Failure("backend_not_ready"))
}
fn transport_failure(e: reqwest::Error) -> Failure {
    Failure(if e.is_timeout() {
        "backend_timeout"
    } else {
        "backend_offline"
    })
}

pub fn error_frame(error: Failure, request_id: Option<Uuid>) -> Value {
    let mut value = serde_json::json!({"version":1,"ok":false,"error_code":error.0});
    if let Some(id) = request_id {
        value["request_id"] = Value::String(id.to_string());
    }
    value
}
pub fn write_frame(output: &mut impl Write, value: &Value) -> Result<()> {
    let bytes = serde_json::to_vec(value).map_err(|_| Failure("native_invalid_message"))?;
    if bytes.len() > MAX_MESSAGE_BYTES {
        return Err(Failure("native_response_size"));
    }
    output
        .write_all(&(bytes.len() as u32).to_le_bytes())
        .and_then(|_| output.write_all(&bytes))
        .and_then(|_| output.flush())
        .map_err(|_| Failure("native_output_closed"))
}
pub fn run(path: &Path, origin: &str) -> Value {
    let mut request_id = None;
    let result = (|| {
        let config = Configuration::load(path, origin)?;
        // Read an unbuffered duplicated descriptor: polling StdinLock can miss prefetched payload.
        // SAFETY: dup returns a fresh owned descriptor; File closes only that duplicate.
        let raw_fd = unsafe { libc::dup(libc::STDIN_FILENO) };
        if raw_fd < 0 {
            return Err(Failure("native_truncated_message"));
        }
        let mut input = unsafe { File::from_raw_fd(raw_fd) };
        let fd = input.as_raw_fd();
        let command = read_frame(|b| read_pipe_exact(&mut input, fd, b, READ_TIMEOUT))?;
        request_id = Some(command.request_id);
        forward(&command, &config)
    })();
    result.unwrap_or_else(|e| error_frame(e, request_id))
}
