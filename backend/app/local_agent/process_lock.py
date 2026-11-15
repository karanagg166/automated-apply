"""Single-host process leases shared by immutable releases and linked worktrees.

The kernel releases flock on exit/crash. Never unlink a lock file: another
process could still hold that inode. This is deliberately a local-Mac lease;
database command fences remain responsible for durable action authority.
"""

import os
import pwd
import stat
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from backend.app.operations.configuration import target_identity


class WorkerAlreadyRunning(RuntimeError):
    pass


@asynccontextmanager
async def process_lock(settings, service, *, directory=None):
    import fcntl

    if service not in {"api", "execution", "telegram", "discovery", "resume"}:
        raise ValueError("unknown_worker_service")
    default = (
        Path(pwd.getpwuid(os.geteuid()).pw_dir)
        / "Library/Application Support/Automated Apply/runtime-locks"
        if sys.platform == "darwin"
        else Path("/tmp") / f"automated-apply-{os.geteuid()}-runtime-locks"
    )
    root = directory or default
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = root.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
    ):
        raise RuntimeError("unsafe_worker_lock_directory")
    target = target_identity(settings)
    descriptors = []
    try:
        # Python's cooperating processes share this family fence. The replacement
        # Rust host takes it exclusively before opening any database connection.
        for name, mode in (("writer", fcntl.LOCK_SH), (service, fcntl.LOCK_EX)):
            path = root / (name + "-" + target + ".lock")
            descriptor = os.open(
                path,
                os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                0o600,
            )
            descriptors.append(descriptor)
            info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
            ):
                raise RuntimeError("unsafe_worker_lock_file")
            try:
                fcntl.flock(descriptor, mode | fcntl.LOCK_NB)
            except BlockingIOError:
                code = (
                    "rust_writer_already_running"
                    if name == "writer"
                    else service + "_worker_already_running"
                )
                raise WorkerAlreadyRunning(code) from None
        yield
    finally:
        # Closing the descriptor releases the lease even on cancellation.
        for descriptor in reversed(descriptors):
            os.close(descriptor)
