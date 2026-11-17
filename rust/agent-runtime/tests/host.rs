//! Fictional configuration and lock files only. No network or existing owner env is used.
use automated_apply_agents::{Failure, configuration::Configuration, process_lock::ProcessLock};
use std::{
    collections::BTreeMap,
    fs,
    os::unix::fs::{PermissionsExt, symlink},
};
fn fixture() -> BTreeMap<String, String> {
    BTreeMap::from([
        ("ENVIRONMENT".into(), "testing".into()),
        ("RUST_RUNTIME_FIXTURE".into(), "true".into()),
        (
            "DATABASE_URL".into(),
            "postgresql://rust_agent_fixture@127.0.0.1:54321/rust_agent_fixture".into(),
        ),
        (
            "JOB_AGENT_API_TOKEN".into(),
            "0123456789abcdefghijklmnopqrstuvwxyzABCDEF".into(),
        ),
        ("API_REQUIRE_TLS".into(), "false".into()),
    ])
}
fn production() -> BTreeMap<String, String> {
    let mut values = fixture();
    values.extend([
    ("ENVIRONMENT".into(),"production".into()),("RUST_RUNTIME_FIXTURE".into(),"false".into()),
    ("DATABASE_URL".into(),"postgresql+asyncpg://job_agent_runtime.luvdmwnlwaqgvfwlmlom:password-one@aws-0-ap-south-1.pooler.supabase.com:5432/postgres".into()),
    ("API_ALLOWED_HOSTS".into(),"[\"runtime.example.net\"]".into()),("API_REQUIRE_TLS".into(),"true".into()),
]);
    values
}
fn write(path: &std::path::Path, values: &BTreeMap<String, String>) {
    fs::write(
        path,
        values
            .iter()
            .map(|(k, v)| format!("{k}='{v}'\n"))
            .collect::<String>(),
    )
    .unwrap();
    fs::set_permissions(path, fs::Permissions::from_mode(0o600)).unwrap();
}
#[test]
fn native_companion_uses_the_same_private_socket_and_preserves_an_existing_file() {
    use automated_apply_agents::native_setup;

    let temporary_root = std::path::Path::new("/tmp").canonicalize().unwrap();
    let directory = tempfile::tempdir_in(temporary_root).unwrap();
    fs::set_permissions(directory.path(), fs::Permissions::from_mode(0o700)).unwrap();
    let runtime = directory.path().join("runtime.env");
    let socket = directory.path().join("rust.sock");
    let mut values = fixture();
    values.extend([
        (
            "RUST_AGENT_UNIX_SOCKET".into(),
            socket.to_str().unwrap().into(),
        ),
        ("CHROME_NATIVE_MESSAGING_ENABLED".into(), "true".into()),
        (
            "CHROME_EXTENSION_ID".into(),
            "gdjbmkffcpicbpiikcohlmokkmcpipgp".into(),
        ),
    ]);
    write(&runtime, &values);
    native_setup::prepare(&runtime, directory.path()).unwrap();
    let companion = directory.path().join("automated-apply-native.private.env");
    let saved = fs::read(&companion).unwrap();
    let native: BTreeMap<_, _> = dotenvy::from_read_iter(saved.as_slice())
        .collect::<std::result::Result<_, _>>()
        .unwrap();
    assert_eq!(native.len(), 5);
    assert_eq!(native["LOCAL_AGENT_UNIX_SOCKET"], socket.to_str().unwrap());
    assert_eq!(native["JOB_AGENT_API_TOKEN"], values["JOB_AGENT_API_TOKEN"]);
    assert_eq!(
        companion.metadata().unwrap().permissions().mode() & 0o777,
        0o600
    );
    assert!(native_setup::prepare(&runtime, directory.path()).is_err());
    assert_eq!(fs::read(&companion).unwrap(), saved);
}

#[test]
fn exact_fixture_boundary_cannot_be_used_for_another_database_or_listener() {
    let valid = Configuration::from_values(&fixture()).unwrap();
    assert!(valid.is_fixture());
    for (key, value) in [
        ("RUST_RUNTIME_FIXTURE", "false"),
        (
            "DATABASE_URL",
            "postgresql://rust_agent_fixture@localhost:54321/rust_agent_fixture",
        ),
        (
            "DATABASE_URL",
            "postgresql://rust_agent_fixture@127.0.0.1:54321/owner_database",
        ),
        (
            "DATABASE_URL",
            "postgresql://rust_agent_fixture@127.0.0.1:54321/rust_agent_fixture?host=elsewhere",
        ),
        ("RUST_AGENT_LISTEN", "0.0.0.0:8011"),
    ] {
        let mut values = fixture();
        values.insert(key.into(), value.into());
        assert!(Configuration::from_values(&values).is_err(), "{key}");
    }
}
#[test]
fn production_requires_pinned_unprivileged_tls_postgresql() {
    assert!(Configuration::from_values(&production()).is_ok());
    for (key, value) in [
        ("DB_REQUIRE_TLS", "false"),
        ("DB_REMOTE_ONLY", "false"),
        ("DB_ECHO", "true"),
        ("API_REQUIRE_TLS", "false"),
        ("SUPABASE_PROJECT_REF", "other_project"),
        ("SUPABASE_URL", "https://other.example.com"),
        (
            "DATABASE_URL",
            "postgresql://postgres:password@db.luvdmwnlwaqgvfwlmlom.supabase.co:5432/postgres",
        ),
        (
            "DATABASE_URL",
            "postgresql://job_agent_runtime.luvdmwnlwaqgvfwlmlom:password@aws-0-ap-south-1.pooler.supabase.com:6543/postgres",
        ),
        (
            "DATABASE_URL",
            "postgresql://job_agent_runtime:password@127.0.0.1:5432/postgres",
        ),
        (
            "DATABASE_URL",
            "postgresql://job_agent_runtime:password@db.other.supabase.co:5432/postgres",
        ),
    ] {
        let mut values = production();
        values.insert(key.into(), value.into());
        assert!(Configuration::from_values(&values).is_err(), "{key}");
    }
}
#[test]
fn worker_identity_matches_the_legacy_python_contract_and_ignores_password_rotation() {
    let first = Configuration::from_values(&fixture()).unwrap();
    assert_eq!(
        first.target_identity(),
        "fe4c6682b5fb06e2f4f4ccc48879bfe9e9fe305f058827cb74e1fb481485b0fc"
    );
    let values = production();
    let first = Configuration::from_values(&values).unwrap();
    assert_eq!(
        first.target_identity(),
        "6a14f1d0325ed93b35101492d25b4476784257be0bb4b4ed550bf75f77c9456b"
    );
    let mut rotated = values.clone();
    rotated.insert(
        "DATABASE_URL".into(),
        values["DATABASE_URL"].replace("password-one", "different%40password"),
    );
    assert_eq!(
        Configuration::from_values(&rotated)
            .unwrap()
            .target_identity(),
        first.target_identity()
    );
    rotated.insert("DATABASE_SCHEMA".into(), "job_agent".into());
    assert_ne!(
        Configuration::from_values(&rotated)
            .unwrap()
            .target_identity(),
        first.target_identity()
    );
}
#[test]
fn configuration_requires_owner_private_regular_file_and_rejects_symlinks() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("runtime.env");
    write(&path, &fixture());
    assert!(Configuration::load(&path).is_ok());
    fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).unwrap();
    assert_eq!(
        Configuration::load(&path).err(),
        Some(Failure("private_configuration_required"))
    );
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
    let alias = directory.path().join("alias");
    symlink(&path, &alias).unwrap();
    assert!(Configuration::load(&alias).is_err());
    assert!(Configuration::load(directory.path()).is_err());
    assert!(Configuration::load(std::path::Path::new("relative.env")).is_err());
    fs::write(&path, vec![b'x'; 1_048_577]).unwrap();
    assert!(Configuration::load(&path).is_err());
}
#[test]
fn literal_configuration_rejects_ambient_substitutions_and_duplicate_keys() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("runtime.env");
    write(&path, &fixture());
    let text = fs::read_to_string(&path).unwrap();
    fs::write(&path, format!("{text}\nUNUSED=${{HOME}}\n")).unwrap();
    assert_eq!(
        Configuration::load(&path).err(),
        Some(Failure("configuration_interpolation_forbidden"))
    );
    fs::write(&path, format!("{text}\nENVIRONMENT=production\n")).unwrap();
    assert_eq!(
        Configuration::load(&path).err(),
        Some(Failure("duplicate_configuration_key"))
    );
}
#[test]
fn explicit_trust_lists_cannot_widen_to_wildcards_or_credential_urls() {
    for (key, value) in [
        ("API_ALLOWED_HOSTS", "[\"*\"]"),
        ("API_ALLOWED_HOSTS", "[]"),
        (
            "API_ALLOWED_ORIGINS",
            "[\"https://user:password@example.net\"]",
        ),
        ("API_ALLOWED_ORIGINS", "[\"https://example.net/path\"]"),
        ("API_ALLOWED_ORIGINS", "[\"null\"]"),
        ("JOB_AGENT_API_TOKEN", "short"),
        ("DB_REQUIRE_TLS", "not-a-boolean"),
    ] {
        let mut values = production();
        values.insert(key.into(), value.into());
        assert!(Configuration::from_values(&values).is_err(), "{key}");
    }
}
#[test]
fn kernel_lease_prevents_duplicates_and_releases_without_unlinking() {
    let directory = tempfile::tempdir().unwrap();
    fs::set_permissions(directory.path(), fs::Permissions::from_mode(0o700)).unwrap();
    let config = Configuration::from_values(&fixture()).unwrap();
    let first = ProcessLock::acquire(&config, Some(directory.path())).unwrap();
    assert_eq!(
        ProcessLock::acquire(&config, Some(directory.path()))
            .err()
            .map(|e| e.0),
        Some("execution_worker_already_running")
    );
    let lock = directory
        .path()
        .join(format!("execution-{}.lock", config.target_identity()));
    let inode = std::os::unix::fs::MetadataExt::ino(&lock.metadata().unwrap());
    drop(first);
    let second = ProcessLock::acquire(&config, Some(directory.path())).unwrap();
    assert_eq!(
        std::os::unix::fs::MetadataExt::ino(&lock.metadata().unwrap()),
        inode
    );
    drop(second);
    assert!(lock.exists());
}
#[test]
fn fixture_requires_private_lock_directory_and_production_forbids_overrides() {
    let directory = tempfile::tempdir().unwrap();
    let config = Configuration::from_values(&fixture()).unwrap();
    assert!(ProcessLock::acquire(&config, None).is_err());
    fs::set_permissions(directory.path(), fs::Permissions::from_mode(0o755)).unwrap();
    assert!(ProcessLock::acquire(&config, Some(directory.path())).is_err());
    let production = Configuration::from_values(&production()).unwrap();
    assert_eq!(
        ProcessLock::acquire(&production, Some(directory.path()))
            .err()
            .map(|e| e.0),
        Some("production_lock_override_forbidden")
    );
}

#[test]
fn telegram_and_execution_have_distinct_legacy_compatible_kernel_leases() {
    let directory = tempfile::tempdir().unwrap();
    fs::set_permissions(directory.path(), fs::Permissions::from_mode(0o700)).unwrap();
    let config = Configuration::from_values(&fixture()).unwrap();
    let _execution = ProcessLock::acquire(&config, Some(directory.path())).unwrap();
    let _telegram = ProcessLock::acquire_telegram(&config, Some(directory.path())).unwrap();
    assert_eq!(
        ProcessLock::acquire_telegram(&config, Some(directory.path()))
            .err()
            .map(|e| e.0),
        Some("telegram_worker_already_running")
    );
}

#[test]
fn runtime_writer_fence_excludes_shared_python_family_and_releases_on_close() {
    use std::fs::OpenOptions;
    use std::os::fd::AsRawFd;
    let directory = tempfile::tempdir().unwrap();
    fs::set_permissions(directory.path(), fs::Permissions::from_mode(0o700)).unwrap();
    let config = Configuration::from_values(&fixture()).unwrap();
    let path = directory
        .path()
        .join(format!("writer-{}.lock", config.target_identity()));
    use std::os::unix::fs::OpenOptionsExt;
    let python = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .open(&path)
        .unwrap();
    // SAFETY: live descriptor and documented flock operation flags.
    assert_eq!(
        unsafe { libc::flock(python.as_raw_fd(), libc::LOCK_SH | libc::LOCK_NB) },
        0
    );
    assert_eq!(
        ProcessLock::acquire_writer(&config, Some(directory.path()))
            .err()
            .map(|e| e.0),
        Some("legacy_writer_already_running")
    );
    drop(python);
    let rust = ProcessLock::acquire_writer(&config, Some(directory.path())).unwrap();
    let python = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&path)
        .unwrap();
    // SAFETY: live descriptor and documented flock operation flags.
    assert_ne!(
        unsafe { libc::flock(python.as_raw_fd(), libc::LOCK_SH | libc::LOCK_NB) },
        0
    );
    drop(rust);
    // SAFETY: live descriptor and documented flock operation flags.
    assert_eq!(
        unsafe { libc::flock(python.as_raw_fd(), libc::LOCK_SH | libc::LOCK_NB) },
        0
    );
}

#[test]
fn production_mcp_requires_private_ipc_and_uses_the_same_literal_configuration() {
    use automated_apply_agents::mcp_bridge::Bridge;
    let dir = tempfile::tempdir().unwrap();
    fs::set_permissions(dir.path(), fs::Permissions::from_mode(0o700)).unwrap();
    let path = dir.path().join("mcp.env");
    let mut values = production();
    write(&path, &values);
    assert_eq!(
        Bridge::load(&path).err().map(|e| e.0),
        Some("mcp_private_socket_required")
    );
    let socket = fs::canonicalize(dir.path()).unwrap().join("s.sock");
    values.insert(
        "RUST_AGENT_UNIX_SOCKET".into(),
        socket.to_str().unwrap().into(),
    );
    write(&path, &values);
    assert!(Bridge::load(&path).is_ok());
    fs::write(&socket, b"preserve").unwrap();
    assert!(Bridge::load(&path).is_err());
}
