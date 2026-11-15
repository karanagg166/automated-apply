//! Kernel-authenticated owner IPC. HTTP callers cannot create the peer marker.
use crate::{Failure, Result};
use automated_apply_local_ipc::{Identity, checked_path};
use std::{
    path::{Path, PathBuf},
    time::Duration,
};
use tokio::net::{UnixListener, UnixStream};
pub struct BoundSocket {
    pub listener: Option<UnixListener>,
    path: PathBuf,
    identity: Identity,
}
impl BoundSocket {
    /// The process must already hold the runtime writer/service locks.
    pub async fn bind(path: &Path) -> Result<Self> {
        let path = checked_path(
            path.to_str()
                .ok_or(Failure("private_socket_path_required"))?,
        )
        .map_err(|e| Failure(e.0))?;
        if path.exists() {
            let identity = Identity::capture(&path).map_err(|e| Failure(e.0))?;
            match tokio::time::timeout(Duration::from_millis(250), UnixStream::connect(&path)).await
            {
                Ok(Err(e)) if e.kind() == std::io::ErrorKind::ConnectionRefused => {
                    identity
                        .remove_if_unchanged(&path)
                        .map_err(|e| Failure(e.0))?;
                }
                _ => return Err(Failure("private_socket_already_active_or_uncertain")),
            }
        }
        let listener = automated_apply_local_ipc::bind_private(&path).map_err(|e| Failure(e.0))?;
        let identity = Identity::capture(&path).map_err(|e| Failure(e.0))?;
        let listener =
            UnixListener::from_std(listener).map_err(|_| Failure("private_socket_bind_failed"))?;
        Ok(Self {
            listener: Some(listener),
            path,
            identity,
        })
    }
}
impl Drop for BoundSocket {
    fn drop(&mut self) {
        self.listener.take();
        let _ = self.identity.remove_if_unchanged(&self.path);
    }
}
#[derive(Clone, Copy)]
pub struct OwnerPeer {
    accepted: bool,
}
impl OwnerPeer {
    pub(crate) fn accepted(&self) -> bool {
        self.accepted
    }
}
impl axum::extract::connect_info::Connected<axum::serve::IncomingStream<'_, UnixListener>>
    for OwnerPeer
{
    fn connect_info(stream: axum::serve::IncomingStream<'_, UnixListener>) -> Self {
        Self {
            accepted: stream
                .io()
                .peer_cred()
                .is_ok_and(|peer| peer.uid() == automated_apply_local_ipc::owner_uid()),
        }
    }
}
