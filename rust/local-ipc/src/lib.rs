//! Owner-only Unix socket filesystem checks shared by local clients and server.
use std::{
    fs,
    os::unix::fs::{FileTypeExt, MetadataExt, PermissionsExt},
    path::{Component, Path, PathBuf},
};
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Error(pub &'static str);
pub fn owner_uid() -> u32 {
    unsafe { libc::geteuid() }
}
pub fn checked_path(raw: &str) -> Result<PathBuf, Error> {
    let path = PathBuf::from(raw);
    if !path.is_absolute()
        || raw.len() > 100
        || raw.as_bytes().contains(&0)
        || path
            .components()
            .any(|c| matches!(c, Component::ParentDir | Component::CurDir))
        || path.file_name().is_none()
    {
        return Err(Error("private_socket_path_required"));
    }
    let parent = path
        .parent()
        .ok_or(Error("private_socket_directory_required"))?;
    if format!(
        "{}/{}",
        parent.display(),
        path.file_name().unwrap().to_string_lossy()
    ) != raw
    {
        return Err(Error("private_socket_path_required"));
    }
    let metadata =
        fs::symlink_metadata(parent).map_err(|_| Error("private_socket_directory_required"))?;
    if !metadata.is_dir()
        || metadata.file_type().is_symlink()
        || metadata.uid() != owner_uid()
        || metadata.mode() & 0o777 != 0o700
        || fs::canonicalize(parent).map_err(|_| Error("private_socket_directory_required"))?
            != parent
    {
        return Err(Error("private_socket_directory_required"));
    }
    match fs::symlink_metadata(&path) {
        Ok(metadata) => {
            if !metadata.file_type().is_socket()
                || metadata.uid() != owner_uid()
                || metadata.mode() & 0o777 != 0o600
            {
                return Err(Error("private_socket_identity_required"));
            }
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
        Err(_) => return Err(Error("private_socket_identity_required")),
    }
    Ok(path)
}
#[derive(Clone, Copy)]
pub struct Identity {
    device: u64,
    inode: u64,
}
impl Identity {
    pub fn capture(path: &Path) -> Result<Self, Error> {
        checked_path(path.to_str().ok_or(Error("private_socket_path_required"))?)?;
        let metadata =
            fs::symlink_metadata(path).map_err(|_| Error("private_socket_identity_required"))?;
        if !metadata.file_type().is_socket() {
            return Err(Error("private_socket_identity_required"));
        }
        Ok(Self {
            device: metadata.dev(),
            inode: metadata.ino(),
        })
    }
    /// Only the exact owned ephemeral socket inode; never a replaced file or directory.
    pub fn remove_if_unchanged(&self, path: &Path) -> Result<bool, Error> {
        checked_path(path.to_str().ok_or(Error("private_socket_path_required"))?)?;
        let current = match fs::symlink_metadata(path) {
            Ok(v) => v,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(false),
            Err(_) => return Err(Error("private_socket_identity_required")),
        };
        if current.dev() != self.device || current.ino() != self.inode {
            return Ok(false);
        }
        fs::remove_file(path).map_err(|_| Error("private_socket_cleanup_failed"))?;
        Ok(true)
    }
}

/// The verified 0700 parent protects creation. Set 0600 before returning the listener.
/// Never change the process-wide umask: concurrent work must retain its own file modes.
pub fn bind_private(path: &Path) -> Result<std::os::unix::net::UnixListener, Error> {
    checked_path(path.to_str().ok_or(Error("private_socket_path_required"))?)?;
    let listener = std::os::unix::net::UnixListener::bind(path)
        .map_err(|_| Error("private_socket_bind_failed"))?;
    fs::set_permissions(path, fs::Permissions::from_mode(0o600))
        .map_err(|_| Error("private_socket_bind_failed"))?;
    listener
        .set_nonblocking(true)
        .map_err(|_| Error("private_socket_bind_failed"))?;
    checked_path(path.to_str().ok_or(Error("private_socket_path_required"))?)?;
    Ok(listener)
}
