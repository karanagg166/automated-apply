"""The single dedicated Brave profile: location, permissions and lock detection."""

from __future__ import annotations

import json
import os
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

PROFILE_DIR_VARIABLE = "AUTOMATED_APPLY_BRAVE_PROFILE_DIR"
EXECUTABLE_VARIABLE = "AUTOMATED_APPLY_BRAVE_EXECUTABLE"
DEFAULT_PROFILE_DIR = Path.home() / "Library/Application Support/automated-apply/brave"
DEFAULT_RUNTIME_DIR = DEFAULT_PROFILE_DIR.parent
DEFAULT_EXECUTABLE = Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser")
FORBIDDEN_ROOTS = (Path.home() / "Desktop", Path.home() / "Documents", Path.home() / "Downloads")

LOGIN_URLS = {
    "naukri": "https://www.naukri.com/nlogin/login",
    "instahyre": "https://www.instahyre.com/login/",
    "himalayas": "https://himalayas.app/login",
    "internshala": "https://internshala.com/login/user",
}


class ProfileError(RuntimeError):
    pass


class ProfileInUse(ProfileError):
    pass


def profile_dir() -> Path:
    raw = os.environ.get(PROFILE_DIR_VARIABLE)
    path = Path(raw).expanduser() if raw else DEFAULT_PROFILE_DIR
    return path.resolve() if path.exists() else path.absolute()


def runtime_dir() -> Path:
    """Receipts and logs live beside the profile, never inside the repository."""
    return profile_dir().parent


def brave_executable() -> Path:
    raw = os.environ.get(EXECUTABLE_VARIABLE)
    return Path(raw).expanduser() if raw else DEFAULT_EXECUTABLE


def assert_allowed_location(path: Path) -> None:
    """macOS TCC stalls hit helpers under protected folders such as ~/Desktop."""
    resolved = path.expanduser().absolute()
    for root in FORBIDDEN_ROOTS:
        if resolved == root or root in resolved.parents:
            raise ProfileError(f"profile_dir_in_protected_folder:{root.name}")


def ensure_profile_dir(path: Path | None = None) -> Path:
    path = path or profile_dir()
    assert_allowed_location(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return path


@dataclass(frozen=True)
class ProfileLock:
    pid: int | None
    source: str


def _lock_owner(path: Path) -> ProfileLock | None:
    lock = path / "SingletonLock"
    if not lock.is_symlink():
        return None
    target = os.readlink(lock)
    host, _, pid_text = target.rpartition("-")
    if not pid_text.isdigit():
        return ProfileLock(None, "singleton_lock_unparsed")
    pid = int(pid_text)
    if host and host != socket.gethostname():
        return ProfileLock(pid, "singleton_lock_other_host")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None  # stale lock; Chromium clears it on next launch
    except PermissionError:
        pass
    return ProfileLock(pid, "singleton_lock")


def _process_owner(path: Path) -> ProfileLock | None:
    try:
        output = subprocess.run(["/bin/ps", "-axo", "pid=,args="], capture_output=True,
                                text=True, timeout=5, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    needle = f"--user-data-dir={path}"
    for line in output.splitlines():
        pid_text, _, args = line.strip().partition(" ")
        if needle in args and "--type=" not in args:
            return ProfileLock(int(pid_text), "process_args")
    return None


def profile_lock(path: Path | None = None) -> ProfileLock | None:
    path = path or profile_dir()
    return _lock_owner(path) or _process_owner(path)


def assert_profile_free(path: Path | None = None) -> None:
    path = path or profile_dir()
    owner = profile_lock(path)
    if owner:
        raise ProfileInUse(
            f"Brave is already using {path} (pid {owner.pid}, {owner.source}). "
            "Quit that Brave window (Cmd+Q) and retry; two browsers on one profile corrupt it."
        )


def last_exit_type(path: Path | None = None) -> str | None:
    """Brave records profile.exit_type ('Normal' or 'Crashed') in Default/Preferences."""
    preferences = (path or profile_dir()) / "Default/Preferences"
    try:
        return json.loads(preferences.read_text()).get("profile", {}).get("exit_type")
    except (OSError, ValueError):
        return None
