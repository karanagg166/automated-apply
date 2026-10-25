"""Private macOS test runtime. No launch agent, global environment or app integration.

Run from the repository root with the backend Python environment. Downloading the
official standalone Ollama archive is a separate, explicit installation step.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import signal
import socket

# Only the fixed local runtime and measurement executables below may run.
import subprocess  # nosec B404
import time
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

ENDPOINT = "http://127.0.0.1:11434"
MODEL = "qwen2.5:1.5b-instruct"
# Owner-specified shared advisory lock, never a data or credential file.
LOCK = "/tmp/automated-apply-heavy-tests.lock"  # nosec B108
SANDBOX = """(version 1)
(allow default)
(deny network*)
(allow network-inbound (local ip "localhost:*"))
(allow network-outbound (remote ip "localhost:*"))
"""


def command(argv: list[str]) -> str:
    # Only local measurement callers reach this helper; model text never does.
    if not argv or argv[0] not in {
        "/usr/sbin/sysctl", "/usr/bin/memory_pressure", "/usr/bin/vm_stat",
        "/bin/df", "/bin/ps", "/usr/sbin/lsof",
    }:
        raise ValueError("measurement_executable_denied")
    return subprocess.check_output(argv, text=True, timeout=10).strip()  # nosec B603


def snapshot() -> dict:
    return {
        "swap": command(["/usr/sbin/sysctl", "vm.swapusage"]),
        "pressure_level": command(["/usr/sbin/sysctl", "kern.memorystatus_vm_pressure_level"]),
        "memory_pressure": command(["/usr/bin/memory_pressure", "-Q"]),
        "vm_stat": command(["/usr/bin/vm_stat"]),
        "disk": command(["/bin/df", "-k", "."]),
    }


def resource_values(row):
    """VM counters are system-wide; they cannot attribute paging to this daemon."""
    import re

    page_size = int(re.search(r"page size of (\d+)", row["vm_stat"])[1])
    swapouts = int(re.search(r"Swapouts:\s+(\d+)", row["vm_stat"])[1])
    swapins = int(re.search(r"Swapins:\s+(\d+)", row["vm_stat"])[1])
    return {
        "pressure": int(row["pressure_level"].split(":")[-1]),
        "free_percent": int(re.search(r"free percentage:\s+(\d+)", row["memory_pressure"])[1]),
        "swap_used_mib": float(re.search(r"used =\s*([\d.]+)M", row["swap"])[1]),
        "swapout_mib": swapouts * page_size / 1048576,
        "swapin_mib": swapins * page_size / 1048576,
    }


def excessive_pressure(current, before=None):
    values = resource_values(current)
    if values["pressure"] >= 4 or values["free_percent"] < 10:
        return True
    if before:
        previous = resource_values(before)
        return (values["swap_used_mib"] - previous["swap_used_mib"] > 768
                or values["swapout_mib"] - previous["swapout_mib"] > 1024)
    return False


@contextlib.contextmanager
def heavy_lock(wait_seconds: float = 600):
    """Same inode and macOS flock protocol used by the independent Chrome agent."""
    with open(LOCK, "a", encoding="utf-8") as handle:
        deadline = time.monotonic() + wait_seconds
        announced = False
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if not announced:
                    print("Waiting for shared heavy-test lock", flush=True)
                    announced = True
                if time.monotonic() >= deadline:
                    raise TimeoutError("heavy_test_lock_busy") from None
                time.sleep(0.25)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def local_json(path: str, data: dict | None = None, timeout: float = 2) -> dict:
    # No ambient HTTP proxies or credentials; callers supply only fixed API paths.
    wire = None if data is None else json.dumps(data).encode()
    request = Request(
        ENDPOINT + path, data=wire, headers={"Content-Type": "application/json"}
    )
    with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
        return json.load(response)


class PrivateRuntime:
    def __init__(self, directory: Path, *, allow_download: bool = False):
        self.directory = directory.resolve()
        self.allow_download = allow_download
        self.process = None
        self.log = None

    def __enter__(self):
        binary = self.directory / "ollama"
        if not binary.is_file():
            raise RuntimeError("Install the official standalone Ollama archive in runtime-directory")
        # Do not connect to, stop, or reuse another agent's daemon.
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", 11434))
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.directory.chmod(0o700)
        env = {key: os.environ[key] for key in ("HOME", "USER", "TMPDIR") if key in os.environ}
        env.update({
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "OLLAMA_HOST": "127.0.0.1:11434",
            "OLLAMA_MODELS": str(self.directory / "models"),
            "OLLAMA_NO_CLOUD": "1",
            "OLLAMA_NOHISTORY": "1",
            "OLLAMA_MAX_LOADED_MODELS": "1",
            "OLLAMA_NUM_PARALLEL": "1",
            "OLLAMA_MAX_QUEUE": "1",
            "OLLAMA_CONTEXT_LENGTH": "2048",
            "OLLAMA_KEEP_ALIVE": "0",
            "OLLAMA_LOAD_TIMEOUT": "30s",
        })
        argv = [str(binary), "serve"]
        if not self.allow_download:
            argv = ["/usr/bin/sandbox-exec", "-p", SANDBOX, *argv]
        self.log = (self.directory / "server.log").open("a", encoding="utf-8")
        os.chmod(self.directory / "server.log", 0o600)
        try:
            self.process = subprocess.Popen(  # nosec B603
                argv, env=env, stdout=self.log, stderr=self.log, start_new_session=True,
            )
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError("private_server_exited; inspect private server.log")
                try:
                    self.version = local_json("/api/version")["version"]
                    return self
                except OSError:
                    time.sleep(0.1)
            raise TimeoutError("private_server_startup_timeout")
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        if self.process is not None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
                self.process.wait(timeout=10)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass
            finally:
                # Also reap any runner in this runtime's process group.
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.process.wait(timeout=10)
        if self.log:
            self.log.close()


def process_sample(root_pid: int) -> dict:
    rows = []
    for line in command(["/bin/ps", "-axo", "pid=,ppid=,rss=,%cpu="]).splitlines():
        pid, parent, rss, cpu = line.split()
        rows.append((int(pid), int(parent), int(rss), float(cpu)))
    descendants = {root_pid}
    while True:
        found = {pid for pid, parent, _, _ in rows if parent in descendants}
        if found <= descendants:
            break
        descendants |= found
    return {
        "rss_mib": sum(rss for pid, _, rss, _ in rows if pid in descendants) / 1024,
        "cpu_percent": sum(cpu for pid, _, _, cpu in rows if pid in descendants),
        "pids": sorted(descendants),
    }
