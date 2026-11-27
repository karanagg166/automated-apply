"""Single-instance lease for the v2 worker (one per host + profile).

A second `cli worker` (a manual run beside launchd) used to start duplicate watchers, a second
Telegram poller (409 loops) and fight over the Brave profile, whose ProfileInUse failures were
persisted as INFRA_ERROR circuits that then blocked the healthy worker too. The kernel releases
the flock on exit or crash; the lock file is never unlinked (another process may hold the inode).
Lives in <repo>/.local/runtime-locks (project-dir rule), override with AUTOMATED_APPLY_LOCK_DIR.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from backend.app.browser_v2.config import REPO_ROOT

LOCK_DIR_VARIABLE = "AUTOMATED_APPLY_LOCK_DIR"


class WorkerAlreadyRunning(RuntimeError):
    pass


def lock_dir(environ: Mapping[str, str] | None = None) -> Path:
    value = (environ if environ is not None else os.environ).get(LOCK_DIR_VARIABLE, "").strip()
    return Path(value).expanduser() if value else REPO_ROOT / ".local" / "runtime-locks"


@contextmanager
def instance_lock(name: str = "worker-v2", *, directory: Path | None = None) -> Iterator[Path]:
    import fcntl

    root = directory or lock_dir()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise RuntimeError("unsafe_lock_directory")
    path = root / f"{name}.lock"
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise WorkerAlreadyRunning(f"{name}_already_running") from None
        os.ftruncate(descriptor, 0)
        os.write(descriptor, str(os.getpid()).encode())
        yield path
    finally:
        os.close(descriptor)  # releases the flock, also on cancellation
