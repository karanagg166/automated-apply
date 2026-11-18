//! Bounded pipes and an owned process group; no shell, PTY, clipboard or interactive input.
use super::{
    protocol::{self, Answer, Stream},
    settings::CliModel,
};
use crate::{Failure, Result};
use std::{
    collections::BTreeMap,
    path::Path,
    process::Stdio,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};
use tokio::{
    io::{AsyncRead, AsyncReadExt, AsyncWriteExt},
    process::{Child, Command},
    sync::oneshot,
};
const MAX: usize = 65536;
struct Process {
    child: Child,
    group: Option<i32>,
}
impl Process {
    fn spawn(
        executable: &Path,
        args: &[String],
        cwd: &Path,
        env: &BTreeMap<String, String>,
    ) -> Result<Self> {
        let mut command = Command::new(executable);
        command
            .args(args)
            .current_dir(cwd)
            .env_clear()
            .envs(env)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true)
            .process_group(0);
        // Private CLI logs inherit this child-only mask; the owner's process is unchanged.
        unsafe {
            command.pre_exec(|| {
                libc::umask(0o077);
                Ok(())
            });
        }
        let child = command.spawn().map_err(|_| Failure("cli_unavailable"))?;
        let group = child
            .id()
            .and_then(|id| i32::try_from(id).ok())
            .ok_or(Failure("cli_unavailable"))?;
        Ok(Self {
            child,
            group: Some(group),
        })
    }
    fn terminate(&mut self) {
        // Only this spawn's group, never an inherited owner process group.
        if let Some(group) = self.group.take() {
            unsafe {
                libc::kill(-group, libc::SIGKILL);
            }
        }
        let _ = self.child.start_kill();
    }
}
impl Drop for Process {
    fn drop(&mut self) {
        self.terminate();
    }
}
async fn bounded<R: AsyncRead + Unpin>(mut reader: R) -> Result<Vec<u8>> {
    let mut bytes = vec![];
    let mut buffer = [0u8; 4096];
    loop {
        let n = reader
            .read(&mut buffer)
            .await
            .map_err(|_| Failure("cli_transport_error"))?;
        if n == 0 {
            return Ok(bytes);
        }
        if bytes.len() + n > MAX {
            return Err(Failure("provider_output_size"));
        }
        bytes.extend_from_slice(&buffer[..n]);
    }
}
async fn frames<R: AsyncRead + Unpin>(
    mut reader: R,
    model: &CliModel,
    ready: oneshot::Sender<()>,
    sent: Arc<AtomicBool>,
) -> Result<Stream> {
    let mut parser = Stream::default();
    let mut ready = Some(ready);
    let mut pending = vec![];
    let mut size = 0;
    let mut buffer = [0u8; 4096];
    loop {
        let n = reader
            .read(&mut buffer)
            .await
            .map_err(|_| Failure("cli_transport_error"))?;
        if n == 0 {
            break;
        }
        size += n;
        if size > MAX {
            return Err(Failure("provider_output_size"));
        }
        pending.extend_from_slice(&buffer[..n]);
        while let Some(end) = pending.iter().position(|b| *b == b'\n') {
            let line = pending.drain(..=end).collect::<Vec<_>>();
            if line.iter().all(u8::is_ascii_whitespace) {
                continue;
            }
            if parser.frame(&line, sent.load(Ordering::Acquire))? {
                model.verify()?;
                ready
                    .take()
                    .ok_or(Failure("invalid_provider_stream"))?
                    .send(())
                    .map_err(|_| Failure("cli_transport_error"))?;
            }
        }
    }
    if !pending.iter().all(u8::is_ascii_whitespace) {
        if parser.frame(&pending, sent.load(Ordering::Acquire))? {
            return Err(Failure("provider_init_unverified"));
        }
    }
    Ok(parser)
}
pub(super) async fn discover(model: &CliModel, budget: Duration) -> Result<()> {
    let mut process = Process::spawn(
        &model.executable,
        &["agents".into()],
        &model.workspace(),
        &model.environment(),
    )?;
    drop(process.child.stdin.take());
    let stdout = process
        .child
        .stdout
        .take()
        .ok_or(Failure("cli_transport_error"))?;
    let stderr = process
        .child
        .stderr
        .take()
        .ok_or(Failure("cli_transport_error"))?;
    let result = tokio::time::timeout(budget.min(Duration::from_secs(15)), async {
        let (stdout, stderr, status) = tokio::try_join!(bounded(stdout), bounded(stderr), async {
            process
                .child
                .wait()
                .await
                .map_err(|_| Failure("cli_transport_error"))
        })?;
        if !status.success() {
            return Err(protocol::exit_error(&stderr));
        }
        if !std::str::from_utf8(&stdout)
            .map_err(|_| Failure("restricted_agent_profile_unavailable"))?
            .split_whitespace()
            .any(|s| s == "automated-apply-answer")
        {
            return Err(Failure("restricted_agent_profile_unavailable"));
        }
        Ok(())
    })
    .await
    .unwrap_or(Err(Failure("timeout")));
    process.terminate();
    let _ = process.child.wait().await;
    result
}
pub(super) async fn generate(
    model: &CliModel,
    args: &[String],
    payload: Vec<u8>,
    timeout: Duration,
) -> Result<Answer> {
    let mut process = Process::spawn(
        &model.executable,
        args,
        &model.workspace(),
        &model.environment(),
    )?;
    let mut stdin = process
        .child
        .stdin
        .take()
        .ok_or(Failure("cli_transport_error"))?;
    let stdout = process
        .child
        .stdout
        .take()
        .ok_or(Failure("cli_transport_error"))?;
    let stderr = process
        .child
        .stderr
        .take()
        .ok_or(Failure("cli_transport_error"))?;
    let (ready, wait) = oneshot::channel();
    let sent = Arc::new(AtomicBool::new(false));
    let written = sent.clone();
    let result = tokio::time::timeout(timeout, async {
        let (stream, stderr, (), status) = tokio::try_join!(
            frames(stdout, model, ready, sent),
            bounded(stderr),
            async move {
                if wait.await.is_err() {
                    return Ok(());
                }
                // A failed or partial write fails the whole operation without replay.
                written.store(true, Ordering::Release);
                stdin
                    .write_all(&payload)
                    .await
                    .map_err(|_| Failure("cli_transport_error"))?;
                stdin
                    .shutdown()
                    .await
                    .map_err(|_| Failure("cli_transport_error"))?;
                // The provider may wait for EOF before it emits its final frame.
                drop(stdin);
                Ok(())
            },
            async {
                process
                    .child
                    .wait()
                    .await
                    .map_err(|_| Failure("cli_transport_error"))
            }
        )?;
        if !status.success() {
            return Err(protocol::exit_error(&stderr));
        }
        stream.finish()
    })
    .await
    .unwrap_or(Err(Failure("timeout")));
    process.terminate();
    let _ = process.child.wait().await;
    result
}
