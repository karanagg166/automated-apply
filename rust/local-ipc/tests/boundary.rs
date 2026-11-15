use automated_apply_local_ipc::{Error, Identity, bind_private, checked_path};
use std::{
    fs,
    os::unix::fs::{MetadataExt, PermissionsExt, symlink},
    path::PathBuf,
};
fn fixture() -> (tempfile::TempDir, PathBuf) {
    let dir = tempfile::tempdir().unwrap();
    fs::set_permissions(dir.path(), fs::Permissions::from_mode(0o700)).unwrap();
    let path = fs::canonicalize(dir.path()).unwrap().join("s.sock");
    (dir, path)
}
#[test]
fn only_canonical_absolute_private_owner_paths_are_allowed() {
    let (_dir, path) = fixture();
    assert_eq!(checked_path(path.to_str().unwrap()).unwrap(), path);
    for raw in [
        "relative.sock".to_owned(),
        format!("{}/./s.sock", path.parent().unwrap().display()),
        format!("{}/../s.sock", path.parent().unwrap().display()),
        "/".to_owned(),
        format!("{}/{}", path.parent().unwrap().display(), "x".repeat(100)),
        "\0".into(),
    ] {
        assert!(checked_path(&raw).is_err());
    }
    fs::set_permissions(path.parent().unwrap(), fs::Permissions::from_mode(0o750)).unwrap();
    assert_eq!(
        checked_path(path.to_str().unwrap()).err(),
        Some(Error("private_socket_directory_required"))
    );
}
#[test]
fn symlinks_regular_files_and_open_sockets_are_refused() {
    let (dir, path) = fixture();
    fs::write(&path, b"preserve").unwrap();
    assert!(checked_path(path.to_str().unwrap()).is_err());
    let alias = dir.path().join("alias");
    symlink(&path, &alias).unwrap();
    assert!(checked_path(alias.to_str().unwrap()).is_err());
    let parent_alias = dir.path().join("directory");
    symlink(path.parent().unwrap(), &parent_alias).unwrap();
    assert!(checked_path(parent_alias.join("socket").to_str().unwrap()).is_err());
    fs::remove_file(&path).unwrap();
    let _listener = bind_private(&path).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o660)).unwrap();
    assert!(checked_path(path.to_str().unwrap()).is_err());
}
#[test]
fn atomic_private_bind_and_exact_inode_cleanup_preserve_replacements() {
    let (_dir, path) = fixture();
    let listener = bind_private(&path).unwrap();
    assert_eq!(fs::symlink_metadata(&path).unwrap().mode() & 0o777, 0o600);
    let identity = Identity::capture(&path).unwrap();
    assert!(bind_private(&path).is_err());
    drop(listener);
    assert!(identity.remove_if_unchanged(&path).unwrap());
    assert!(!identity.remove_if_unchanged(&path).unwrap());
    // Keep the original inode allocated while a replacement is created.
    let listener = bind_private(&path).unwrap();
    let identity = Identity::capture(&path).unwrap();
    fs::remove_file(&path).unwrap();
    let replacement = bind_private(&path).unwrap();
    assert!(!identity.remove_if_unchanged(&path).unwrap());
    assert!(path.exists());
    drop(replacement);
    drop(listener);
    fs::remove_file(&path).unwrap();
    fs::write(&path, b"preserve").unwrap();
    assert!(identity.remove_if_unchanged(&path).is_err());
    assert_eq!(fs::read(&path).unwrap(), b"preserve");
}
