"""Single-host process leases shared by immutable releases and linked worktrees.

The kernel releases flock on exit/crash. Never unlink a lock file: another
process could still hold that inode. This is deliberately a local-Mac lease;
database command fences remain responsible for durable action authority.
"""

import os
import stat
from contextlib import asynccontextmanager
from pathlib import Path

from backend.app.operations.configuration import target_identity


class WorkerAlreadyRunning(RuntimeError):
    pass


@asynccontextmanager
async def process_lock(settings, service, *, directory=None):
    import fcntl

    if service not in {"execution", "telegram"}:
        raise ValueError("unknown_worker_service")
    root = directory or Path.home() / "Library/Application Support/Automated Apply/runtime-locks"
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / (service + "-" + target_identity(settings) + ".lock")
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError("unsafe_worker_lock_file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise WorkerAlreadyRunning(service + "_worker_already_running") from None
        yield
    finally:
        # Closing the descriptor releases the lease even on cancellation.
        os.close(descriptor)
