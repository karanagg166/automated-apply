"""Receipt + failure screenshots with a bounded failure ring buffer (Phase 6A).

Verified submission receipts live under `receipts/<platform>/` and are never pruned.
Every other screenshot (dry-run, question, stalled, error) goes to
`receipts/failures/` and only the newest `FAILURE_KEEP` files survive, so a 24/7
M1 run never fills the disk.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.browser_v2 import profile as brave_profile

FAILURE_KEEP = 20
RECEIPT_LABELS = frozenset({"receipt"})
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def receipts_root() -> Path:
    return brave_profile.runtime_dir() / "receipts"


def failures_dir(root: Path | None = None) -> Path:
    return (root or receipts_root()) / "failures"


def prune_failures(directory: Path | None = None, keep: int = FAILURE_KEEP) -> int:
    """Delete all but the newest `keep` files in the failures folder. Returns files removed.

    Only touches regular files directly inside `failures/` (never receipts, never folders).
    """
    folder = directory or failures_dir()
    if folder.name != "failures" or not folder.is_dir():
        return 0
    files = [p for p in folder.iterdir() if p.is_file() and not p.is_symlink()]
    files.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    removed = 0
    for path in files[max(keep, 0):]:
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def screenshot_path(platform: str, job_id: str, label: str, *, root: Path | None = None) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    base = root or receipts_root()
    folder = base / _SAFE.sub("_", platform) if label in RECEIPT_LABELS else failures_dir(base)
    return folder / f"{_SAFE.sub('_', platform)}-{_SAFE.sub('_', job_id)[:80]}-{stamp}-{_SAFE.sub('_', label)}.png"


async def capture(page: Any, platform: str, job_id: str, label: str, *, root: Path | None = None) -> str | None:
    """Best-effort screenshot; a missing screenshot never changes an outcome."""
    path = screenshot_path(platform, job_id, label, root=root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        await page.screenshot(path=str(path), full_page=False)
    except Exception:  # noqa: BLE001
        return None
    if label not in RECEIPT_LABELS:
        prune_failures(path.parent)
    return str(path)
