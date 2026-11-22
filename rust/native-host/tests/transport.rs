use automated_apply_native::*;
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    fs,
    io::{Cursor, Read, Write},
    net::TcpListener,
    os::unix::fs::PermissionsExt,
    process::{Command as Process, Stdio},
    thread,
    time::Duration,
};
use tempfile::TempDir;

const ID: &str = "gdjbmkffcpicbpiikcohlmokkmcpipgp";
const ORIGIN: &str = "chrome-extension://gdjbmkffcpicbpiikcohlmokkmcpipgp/";
fn values(endpoint: &str) -> BTreeMap<String, String> {
    BTreeMap::from([
        (
            "JOB_AGENT_API_TOKEN".into(),
            "fictional-native-token".into(),
        ),
        ("CHROME_EXTENSION_ID".into(), ID.into()),
        ("CHROME_NATIVE_MESSAGING_ENABLED".into(), "true".into()),
        ("LOCAL_AGENT_ENDPOINT".into(), endpoint.into()),
    ])
}
fn command(op: &str) -> automated_apply_native::Command {
    automated_apply_native::Command::parse(&serde_json::to_vec(&json!({"command":op})).unwrap())
        .unwrap()
}
type FixtureResponse = (u16, Vec<(&'static str, String)>, String);
fn fixture(responses: Vec<FixtureResponse>) -> (Configuration, thread::JoinHandle<Vec<Value>>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let config = Configuration::from_values(
        &values(&format!("http://{}", listener.local_addr().unwrap())),
        ORIGIN,
    )
    .unwrap();
    let handle = thread::spawn(move || {
        listener.set_nonblocking(true).unwrap();
        let mut captured = vec![];
        for (status, headers, body) in responses {
            let start = std::time::Instant::now();
            let mut stream = loop {
                match listener.accept() {
                    Ok((stream, _)) => break stream,
                    Err(e)
                        if e.kind() == std::io::ErrorKind::WouldBlock
                            && start.elapsed() < Duration::from_secs(5) =>
                    {
                        thread::sleep(Duration::from_millis(5))
                    }
                    e => panic!("fixture accept failed: {e:?}"),
                }
            };
            stream.set_nonblocking(false).unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(3)))
                .unwrap();
            let mut request = Vec::new();
            let header_end = loop {
                let mut b = [0];
                stream.read_exact(&mut b).unwrap();
                request.push(b[0]);
                if request.ends_with(b"\r\n\r\n") {
                    break request.len();
                }
            };
            let header = String::from_utf8(request.clone()).unwrap();
            assert!(header.starts_with("POST /api/v1/local-agent/chrome HTTP/1.1\r\n"));
            assert!(
                header
                    .to_lowercase()
                    .contains("authorization: bearer fictional-native-token")
            );
            let length: usize = header
                .lines()
                .find_map(|s| {
                    s.to_lowercase()
                        .strip_prefix("content-length:")
                        .map(|s| s.trim().parse().unwrap())
                })
                .unwrap();
            request.resize(header_end + length, 0);
            stream.read_exact(&mut request[header_end..]).unwrap();
            captured.push(serde_json::from_slice(&request[header_end..]).unwrap());
            write!(
                stream,
                "HTTP/1.1 {status} Fixture\r\nContent-Length: {}\r\nConnection: close\r\n",
                body.len()
            )
            .unwrap();
            for (key, value) in headers {
                write!(stream, "{key}: {value}\r\n").unwrap();
            }
            write!(stream, "\r\n{body}").unwrap();
        }
        captured
    });
    (config, handle)
}
fn success(c: &automated_apply_native::Command) -> String {
    json!({"version":1,"request_id":c.request_id,"ok":true,"capability":c.operation,"data":{"fixture":true}}).to_string()
}

#[test]
fn frame_round_trip_and_fragmented_input() {
    let value = json!({"command":"health"});
    let mut bytes = vec![];
    write_frame(&mut bytes, &value).unwrap();
    let mut input = Cursor::new(bytes);
    let c = read_frame(|b| {
        for x in b {
            input
                .read_exact(std::slice::from_mut(x))
                .map_err(|_| Failure("native_truncated_message"))?;
        }
        Ok(())
    })
    .unwrap();
    assert_eq!(c.operation, "health");
}
#[test]
fn malformed_and_oversized_frames() {
    for size in [0, MAX_MESSAGE_BYTES + 1, u32::MAX as usize] {
        let mut input = Cursor::new((size as u32).to_le_bytes());
        assert_eq!(
            read_frame(|b| input
                .read_exact(b)
                .map_err(|_| Failure("native_truncated_message")))
            .err(),
            Some(Failure("native_message_size"))
        );
    }
    for bytes in [
        b"{".as_slice(),
        b"[]",
        b"null",
        b"\xff",
        b"{\"command\":\"health\",\"version\":2}",
        b"{\"command\":\"health\",\"request_id\":\"bad\"}",
        b"{\"command\":\"health\",\"tab_id\":0,\"token\":\"secret\"}",
        b"{\"command\":\"health\",\"work_id\":3}",
    ] {
        assert_eq!(
            automated_apply_native::Command::parse(bytes).err(),
            Some(Failure("native_invalid_message"))
        );
    }
}
#[test]
fn allowlist_and_retry_scope() {
    for op in PROFILE_OPERATIONS
        .iter()
        .chain(QUEUE_OPERATIONS)
        .chain(OTHER_OPERATIONS)
    {
        assert_eq!(command(op).operation, *op);
    }
    for op in ["conversation", "preview_job_filters"] {
        assert_eq!(
            automated_apply_native::Command::parse(
                &serde_json::to_vec(&json!({"command":op})).unwrap()
            )
            .err(),
            Some(Failure("native_capability_denied"))
        );
    }
    assert!(!command("authorize_form").retry_allowed());
    assert!(!command("record_form_fill").retry_allowed());
    assert!(command("admit_naukri_work").retry_allowed());
}
#[test]
fn endpoint_and_origin_fail_closed() {
    for url in [
        "https://127.0.0.1:8000",
        "http://localhost:8000",
        "http://example.org",
        "http://127.0.0.1.evil.test",
        "http://user:pass@127.0.0.1",
        "http://127.0.0.1/path",
        "http://127.0.0.1?x=y",
        "http://127.0.0.1#fragment",
    ] {
        assert_eq!(
            Configuration::from_values(&values(url), ORIGIN).err(),
            Some(Failure("native_configuration_error"))
        );
    }
    for origin in [
        "https://naukri.com",
        "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/",
        "",
    ] {
        assert_eq!(
            Configuration::from_values(&values("http://127.0.0.1:8000"), origin).err(),
            Some(Failure("native_origin_denied"))
        );
    }
    assert!(Configuration::from_values(&values("http://[::1]:8000"), ORIGIN).is_err());
}
#[test]
fn private_configuration_checks() {
    let dir = TempDir::new().unwrap();
    let path = dir.path().join("host.env");
    let text = values("http://127.0.0.1:8000")
        .iter()
        .map(|(k, v)| format!("{k}={v}\n"))
        .collect::<String>();
    fs::write(&path, &text).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
    assert!(Configuration::load(&path, ORIGIN).is_ok());
    let link = dir.path().join("link.env");
    std::os::unix::fs::symlink(&path, &link).unwrap();
    assert_eq!(
        Configuration::load(&link, ORIGIN).err(),
        Some(Failure("native_private_configuration_required"))
    );
    fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).unwrap();
    assert_eq!(
        Configuration::load(&path, ORIGIN).err(),
        Some(Failure("native_private_configuration_required"))
    );
    assert_eq!(
        Configuration::load(std::path::Path::new("relative.env"), ORIGIN).err(),
        Some(Failure("native_private_configuration_required"))
    );
}
#[test]
fn forwards_exact_nested_facts_and_secret_only_to_backend() {
    let value = json!({"command":"finish_naukri_work","profile_secret":"f".repeat(64),"work_report":{"kind":"needs_input","reason":"fixture_missing_fact"}});
    let c = automated_apply_native::Command::parse(&serde_json::to_vec(&value).unwrap()).unwrap();
    let (config, h) = fixture(vec![(200, vec![], success(&c))]);
    assert_eq!(forward(&c, &config).unwrap()["data"]["fixture"], true);
    let captured = h.join().unwrap();
    assert_eq!(captured[0]["work_report"], value["work_report"]);
    assert_eq!(captured[0]["profile_secret"], value["profile_secret"]);
}
#[test]
fn retries_only_explicit_database_rollback_with_same_request_id() {
    let c = command("poll_naukri_work");
    let (config, h) = fixture(vec![
        (
            503,
            vec![("X-Automated-Apply-Transaction", "rolled-back".into())],
            "private error".into(),
        ),
        (200, vec![], success(&c)),
    ]);
    assert!(forward(&c, &config).is_ok());
    let captured = h.join().unwrap();
    assert_eq!(captured.len(), 2);
    assert_eq!(captured[0], captured[1]);
}
#[test]
fn exhausted_rollbacks_have_fixed_code() {
    let c = command("poll_naukri_work");
    let (config, h) = fixture(
        (0..3)
            .map(|_| {
                (
                    503,
                    vec![("X-Automated-Apply-Transaction", "rolled-back".into())],
                    "private".into(),
                )
            })
            .collect(),
    );
    assert_eq!(
        forward(&c, &config),
        Err(Failure("backend_transaction_rolled_back"))
    );
    assert_eq!(h.join().unwrap().len(), 3);
}
#[test]
fn ambiguous_errors_and_mutations_are_not_retried() {
    for (status, headers, operation, code) in [
        (503, vec![], "poll_naukri_work", "backend_not_ready"),
        (
            503,
            vec![("X-Automated-Apply-Transaction", "rolled-back".into())],
            "authorize_form",
            "backend_not_ready",
        ),
        (401, vec![], "health", "backend_authentication_failed"),
        (403, vec![], "health", "backend_authentication_failed"),
        (
            302,
            vec![("Location", "http://example.invalid/private".into())],
            "health",
            "backend_not_ready",
        ),
    ] {
        let (config, h) = fixture(vec![(status, headers, "secret body".into())]);
        assert_eq!(forward(&command(operation), &config), Err(Failure(code)));
        assert_eq!(h.join().unwrap().len(), 1);
    }
}
#[test]
fn rejects_wrong_request_and_invalid_or_large_backend_response() {
    for (body, code) in [
        (
            json!({"request_id":uuid::Uuid::new_v4(),"ok":true,"capability":"health"}).to_string(),
            "native_request_id_mismatch",
        ),
        ("{}".into(), "backend_invalid_response"),
        ("private".into(), "backend_invalid_response"),
        ("x".repeat(MAX_MESSAGE_BYTES + 1), "native_response_size"),
    ] {
        let (config, h) = fixture(vec![(200, vec![], body)]);
        assert_eq!(forward(&command("health"), &config), Err(Failure(code)));
        h.join().unwrap();
    }
}
#[test]
fn executable_handles_open_stdin_without_prefetch_timeout() {
    // An origin error can finish without reading stdin; test the real read path with offline loopback.
    let dir = TempDir::new().unwrap();
    let path = dir.path().join("host.env");
    let text = values("http://127.0.0.1:1")
        .iter()
        .map(|(k, v)| format!("{k}={v}\n"))
        .collect::<String>();
    fs::write(&path, text).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
    let mut child = Process::new(env!("CARGO_BIN_EXE_automated-apply-native"))
        .args([path.to_str().unwrap(), ORIGIN])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    let mut stdin = child.stdin.take().unwrap();
    write_frame(&mut stdin, &json!({"command":"health"})).unwrap();
    let start = std::time::Instant::now();
    while child.try_wait().unwrap().is_none() && start.elapsed() < Duration::from_secs(3) {
        thread::sleep(Duration::from_millis(10));
    }
    if child.try_wait().unwrap().is_none() {
        child.kill().unwrap();
        panic!("host stalled with complete frame and open stdin");
    }
    drop(stdin);
    let output = child.wait_with_output().unwrap();
    assert!(output.stderr.is_empty());
    let size = u32::from_le_bytes(output.stdout[..4].try_into().unwrap()) as usize;
    assert_eq!(size + 4, output.stdout.len());
    let result: Value = serde_json::from_slice(&output.stdout[4..]).unwrap();
    assert_eq!(result["error_code"], "backend_offline");
}
#[test]
fn direct_native_executable_launch_uses_private_adjacent_configuration_and_origin_fences() {
    let dir = TempDir::new().unwrap();
    let binary = dir.path().join("automated-apply-native");
    // Same-volume hard link: no redundant binary copy or shell launcher.
    fs::hard_link(env!("CARGO_BIN_EXE_automated-apply-native"), &binary).unwrap();
    let path = dir.path().join("automated-apply-native.private.env");
    let text = values("http://127.0.0.1:1")
        .iter()
        .map(|(k, v)| format!("{k}={v}\n"))
        .collect::<String>();
    fs::write(&path, text).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
    for (origin, code) in [
        (ORIGIN, "backend_offline"),
        (
            "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/",
            "native_origin_denied",
        ),
    ] {
        let mut child = Process::new(&binary)
            .arg(origin)
            .env_clear()
            .env("JOB_AGENT_API_TOKEN", "must-not-use-ambient-credentials")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        let mut stdin = child.stdin.take().unwrap();
        // A denied origin exits before reading a frame and may close the pipe immediately.
        if origin == ORIGIN {
            write_frame(&mut stdin, &json!({"command":"health"})).unwrap();
        }
        drop(stdin);
        let output = child.wait_with_output().unwrap();
        assert!(output.stderr.is_empty());
        let size = u32::from_le_bytes(output.stdout[..4].try_into().unwrap()) as usize;
        assert_eq!(size + 4, output.stdout.len());
        let value: Value = serde_json::from_slice(&output.stdout[4..]).unwrap();
        assert_eq!(value["error_code"], code);
    }
    fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).unwrap();
    let output = Process::new(&binary).arg(ORIGIN).output().unwrap();
    let value: Value = serde_json::from_slice(&output.stdout[4..]).unwrap();
    assert_eq!(value["error_code"], "native_private_configuration_required");
}
#[test]
fn output_is_bounded_and_contains_only_fixed_failure_code() {
    let result = error_frame(Failure("backend_offline"), None);
    let mut out = vec![];
    write_frame(&mut out, &result).unwrap();
    assert!(!String::from_utf8_lossy(&out).contains("fictional-native-token"));
    assert_eq!(
        write_frame(&mut vec![], &json!({"data":"x".repeat(MAX_MESSAGE_BYTES)})),
        Err(Failure("native_response_size"))
    );
}

#[test]
fn nested_schema_and_field_bounds_are_enforced() {
    for value in [
        json!({"command":"health","tab_id":-1}),
        json!({"command":"health","profile_secret":"short"}),
        json!({"command":"health","profile_commands_enabled":"yes"}),
        json!({"command":"health","queue_action":"reset"}),
        json!({"command":"finish_naukri_work","work_report":{"kind":"execution_observation","execution":{"state":"APPLIED"}}}),
        json!({"command":"health","receipt":{"submitted":true}}),
        json!({"command":"health","inspection":{"document_id":"not-a-document","extra":"forbidden"}}),
    ] {
        assert_eq!(
            automated_apply_native::Command::parse(&serde_json::to_vec(&value).unwrap()).err(),
            Some(Failure("native_invalid_message"))
        );
    }
}
#[test]
fn partial_pipe_times_out_and_closed_pipe_is_truncated() {
    use std::os::{fd::AsRawFd, unix::net::UnixStream};
    let (mut reader, mut writer) = UnixStream::pair().unwrap();
    writer.write_all(&[1]).unwrap();
    let fd = reader.as_raw_fd();
    assert_eq!(
        read_pipe_exact(&mut reader, fd, &mut [0; 2], Duration::from_millis(50)),
        Err(Failure("native_read_timeout"))
    );
    drop(writer);
    assert_eq!(
        read_pipe_exact(&mut reader, fd, &mut [0], Duration::from_millis(50)),
        Err(Failure("native_truncated_message"))
    );
}

#[test]
fn private_socket_forwarding_never_connects_to_configured_tcp_endpoint() {
    use std::os::unix::net::UnixListener;
    let dir = TempDir::new().unwrap();
    fs::set_permissions(dir.path(), fs::Permissions::from_mode(0o700)).unwrap();
    let path = fs::canonicalize(dir.path()).unwrap().join("native.sock");
    let listener = UnixListener::bind(&path).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
    let tcp = TcpListener::bind("127.0.0.1:0").unwrap();
    tcp.set_nonblocking(true).unwrap();
    let mut vars = values(&format!("http://{}", tcp.local_addr().unwrap()));
    vars.insert(
        "LOCAL_AGENT_UNIX_SOCKET".into(),
        path.to_str().unwrap().into(),
    );
    let config = Configuration::from_values(&vars, ORIGIN).unwrap();
    let c = command("health");
    let response = success(&c);
    let server = thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(3)))
            .unwrap();
        let mut bytes = vec![];
        while !bytes.ends_with(b"\r\n\r\n") {
            let mut byte = [0];
            stream.read_exact(&mut byte).unwrap();
            bytes.push(byte[0]);
        }
        let header = String::from_utf8(bytes).unwrap().to_lowercase();
        assert!(header.starts_with("post /api/v1/local-agent/chrome http/1.1"));
        assert!(header.contains("authorization: bearer fictional-native-token"));
        assert!(header.contains(&format!("x-agent-client: {ID}")));
        assert!(!header.contains("x-forwarded-proto"));
        let length: usize = header
            .lines()
            .find_map(|line| line.strip_prefix("content-length:"))
            .unwrap()
            .trim()
            .parse()
            .unwrap();
        let mut body = vec![0; length];
        stream.read_exact(&mut body).unwrap();
        assert_eq!(
            serde_json::from_slice::<Value>(&body).unwrap()["command"],
            "health"
        );
        write!(
            stream,
            "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
            response.len(),
            response
        )
        .unwrap();
    });
    assert_eq!(forward(&c, &config).unwrap()["ok"], true);
    server.join().unwrap();
    assert!(matches!(tcp.accept(),Err(e) if e.kind()==std::io::ErrorKind::WouldBlock));
    // A formerly valid socket that disappeared never causes fallback to TCP.
    fs::remove_file(&path).unwrap();
    assert_eq!(forward(&c, &config), Err(Failure("backend_offline")));
    assert!(matches!(tcp.accept(),Err(e) if e.kind()==std::io::ErrorKind::WouldBlock));
    vars.insert("LOCAL_AGENT_UNIX_SOCKET".into(), "relative.sock".into());
    assert!(Configuration::from_values(&vars, ORIGIN).is_err());
}
