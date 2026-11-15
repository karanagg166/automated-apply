use automated_apply_agents::{Failure, local_socket::BoundSocket};
use std::{fs, os::unix::fs::PermissionsExt, path::PathBuf};
fn fixture() -> (tempfile::TempDir, PathBuf) {
    let dir = tempfile::tempdir().unwrap();
    fs::set_permissions(dir.path(), fs::Permissions::from_mode(0o700)).unwrap();
    let path = fs::canonicalize(dir.path()).unwrap().join("s.sock");
    (dir, path)
}
#[tokio::test]
async fn live_socket_is_never_replaced_and_guard_cleans_only_its_inode() {
    let (_dir, path) = fixture();
    let bound = BoundSocket::bind(&path).await.unwrap();
    assert_eq!(
        BoundSocket::bind(&path).await.err().map(|e| e.0),
        Some("private_socket_already_active_or_uncertain")
    );
    assert!(path.exists());
    drop(bound);
    assert!(!path.exists());
}
#[tokio::test]
async fn stale_owned_socket_is_recovered_but_regular_replacement_is_retained() {
    let (_dir, path) = fixture();
    drop(automated_apply_local_ipc::bind_private(&path).unwrap());
    let bound = BoundSocket::bind(&path).await.unwrap();
    fs::remove_file(&path).unwrap();
    fs::write(&path, b"preserve").unwrap();
    drop(bound);
    assert_eq!(fs::read(&path).unwrap(), b"preserve");
    assert_eq!(
        BoundSocket::bind(&path).await.err(),
        Some(Failure("private_socket_identity_required"))
    );
}
