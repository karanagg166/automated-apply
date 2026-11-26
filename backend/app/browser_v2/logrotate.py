"""Bounded log rotation for the 24/7 launchd services (keeps the M1 SSD lean).

launchd opens `StandardOutPath`/`StandardErrorPath` once, before the process starts,
and keeps that descriptor for the process lifetime. Renaming the live file would make
launchd keep writing into the renamed backup, so rotation is copy-then-truncate:
backups shift `.2 -> .3`, `.1 -> .2`, the live file is copied to `.1`, then truncated
in place (launchd appends, so writes continue at the new end of file).
"""

from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import Iterable
from pathlib import Path

LOG_DIR_VARIABLE = "AUTOMATED_APPLY_LOG_DIR"
DEFAULT_LOG_DIR = Path.home() / "Library/Logs/automated-apply"
MAX_BYTES = 10 * 1024 * 1024
BACKUPS = 3
PERIODIC_SEC = 3600


def log_dir() -> Path:
    raw = os.environ.get(LOG_DIR_VARIABLE)
    return Path(raw).expanduser() if raw else DEFAULT_LOG_DIR


def service_logs(service: str, directory: Path | None = None) -> list[Path]:
    """`<service>.out.log` and `<service>.err.log` (the names the v2 plists use)."""
    base = directory or log_dir()
    return [base / f"{service}.out.log", base / f"{service}.err.log"]


def rotate_file(path: Path, *, max_bytes: int = MAX_BYTES, backups: int = BACKUPS) -> bool:
    """Rotate one regular file when it exceeds `max_bytes`; True if rotated."""
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size <= max_bytes:
            return False
    except OSError:
        return False
    backups = max(1, backups)
    oldest = path.with_name(f"{path.name}.{backups}")
    if oldest.exists() and not oldest.is_symlink():
        oldest.unlink()
    for index in range(backups - 1, 0, -1):
        source = path.with_name(f"{path.name}.{index}")
        if source.exists() and not source.is_symlink():
            source.rename(path.with_name(f"{path.name}.{index + 1}"))
    target = path.with_name(f"{path.name}.1")
    shutil.copyfile(path, target)
    os.chmod(target, 0o600)
    with open(path, "r+b") as handle:  # truncate in place: launchd keeps its descriptor
        handle.truncate(0)
    return True


def rotate_logs(paths: Iterable[Path], *, max_bytes: int = MAX_BYTES, backups: int = BACKUPS) -> list[str]:
    rotated = []
    for path in paths:
        try:
            if rotate_file(Path(path), max_bytes=max_bytes, backups=backups):
                rotated.append(str(path))
        except OSError:
            continue  # rotation is best effort; never block a service start
    return rotated


def rotate_service_logs(service: str, directory: Path | None = None) -> list[str]:
    return rotate_logs(service_logs(service, directory))


async def rotate_periodically(service: str, stop: asyncio.Event, *, interval: float = PERIODIC_SEC,
                              directory: Path | None = None) -> None:
    """Hourly rotation for long-lived processes (the worker runs for days)."""
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            await asyncio.to_thread(rotate_service_logs, service, directory)
