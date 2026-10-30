"""Owner-invoked, read-only acceptance monitor. Never locks/unlocks the Mac.

Run only after approving the exact release, installation, channels and live
monitoring scope. This records observations, not an acceptance PASS or uptime
promise. Genuine DOM/fill/submission evidence must be reviewed separately.
"""

import argparse
import asyncio
import json
import os
import plistlib
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


def lock_observation(document, uid):
    """Missing/ambiguous OS telemetry is unknown, never assumed locked."""
    sessions = []
    console_locks = []

    def walk(node):
        if isinstance(node, dict):
            console_users = node.get("IOConsoleUsers", [])
            current_console = [s for s in console_users if isinstance(s, dict)
                               and s.get("kCGSSessionOnConsoleKey") is True]
            if (len(current_console) == 1
                    and current_console[0].get("kCGSSessionUserIDKey") == uid
                    and type(node.get("IOConsoleLocked")) is bool):
                console_locks.append(node["IOConsoleLocked"])
            sessions.extend(
                s
                for s in node.get("IOConsoleUsers", [])
                if isinstance(s, dict) and s.get("kCGSSessionUserIDKey") == uid
            )
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(document)
    if len(sessions) != 1:
        return "UNKNOWN"
    per_session = sessions[0].get("CGSSessionScreenIsLocked")
    if type(per_session) is bool:
        if console_locks and any(value != per_session for value in console_locks):
            return "UNKNOWN"
        return "LOCKED" if per_session else "UNLOCKED"
    # macOS 27 exposes the console property instead of a per-session lock key.
    # Accept it only when the sole active console belongs to this exact user.
    if len(console_locks) == 1:
        return "LOCKED" if console_locks[0] else "UNLOCKED"
    return "UNKNOWN"


def mac_lock_state():
    try:
        result = subprocess.run(
            ["/usr/sbin/ioreg", "-a", "-n", "Root", "-d", "1"],
            check=True,
            capture_output=True,
            timeout=5,
        )
        return lock_observation(plistlib.loads(result.stdout), os.getuid())
    except (
        OSError,
        ValueError,
        subprocess.SubprocessError,
        plistlib.InvalidFileException,
    ):
        return "UNKNOWN"


async def observe(operation):
    """Retain independent dependency results without private exception text."""
    started = asyncio.get_running_loop().time()
    try:
        async with asyncio.timeout(15):
            data = await operation()
        return {"status": "PASS", "seconds": round(asyncio.get_running_loop().time() - started, 3), "data": data}
    except Exception as exc:
        response = getattr(exc, "response", None)
        return {"status": "FAIL", "seconds": round(asyncio.get_running_loop().time() - started, 3),
                "error_type": type(exc).__name__, "http_status": getattr(response, "status_code", None)}


async def dependency_sample(api, database, health, ready):
    results = await asyncio.gather(*(observe(op) for op in (api, database, health, ready)))
    sample = dict(zip(("api", "database", "health", "ready"), results, strict=True))
    if sample["api"]["status"] == sample["database"]["status"] == "PASS":
        actual = sample["database"]["data"].get("automation", {"state": "STOPPED", "revision": 0})
        reported = sample["api"]["data"]
        sample["database_agrees"] = all(actual.get(k) == reported.get(k) for k in ("state", "revision"))
    return sample


async def monitor(args):
    import httpx
    from sqlalchemy import select

    from backend.app.core.config import configure_operator
    from backend.app.operations.configuration import load_settings

    settings = load_settings(args.env_file)
    configure_operator(settings)
    from backend.app.dashboard.models import OwnerPreference
    from backend.app.db.session import close_db_engine, get_session_factory
    from backend.app.execution.recurring import HEALTH, KEY

    endpoint = settings.LOCAL_AGENT_ENDPOINT.rstrip("/")
    parsed = urlsplit(endpoint)
    if (parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.scheme != "http" or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise ValueError("approved_loopback_endpoint_required")
    output = Path(args.output).expanduser()
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=15) as client:
            async def request(path):
                response = await client.get(endpoint + path, headers={
                    "Authorization": "Bearer " + settings.JOB_AGENT_API_TOKEN.get_secret_value()})
                response.raise_for_status()
                return response.json()

            async def api():
                return (await request("/api/v1/execution/naukri"))["automation"]

            async def database():
                async with get_session_factory()() as session:
                    rows = {row.key: row.value for row in (await session.scalars(
                        select(OwnerPreference).where(OwnerPreference.key.in_([KEY, HEALTH, "chr_selection"]))
                    )).all()}
                return {"automation": rows.get(KEY, {"state": "STOPPED", "revision": 0}),
                        "worker_heartbeat_at": rows.get(HEALTH, {}).get("heartbeat_at"),
                        "selected_profile": rows.get("chr_selection", {}).get("profile_binding_id")}

            with os.fdopen(descriptor, "w") as log:
                loop = asyncio.get_running_loop()
                started = loop.time()
                previous = None
                while loop.time() - started <= args.duration_seconds:
                    began = loop.time()
                    sample = {"at": datetime.now(timezone.utc).isoformat(), "screen": mac_lock_state(),
                              "sample_gap_seconds": None if previous is None else round(began - previous, 3),
                              "evidence_type": "live_readonly_monitoring", "submitted_by_monitor": False}
                    sample.update(await dependency_sample(api, database,
                        lambda: request("/health"), lambda: request("/ready")))
                    sample["screen_after"] = mac_lock_state()
                    sample["completed_at"] = datetime.now(timezone.utc).isoformat()
                    log.write(json.dumps(sample) + "\n")
                    log.flush()
                    os.fsync(log.fileno())
                    previous = began
                    delay = max(0, args.interval_seconds - (loop.time() - began))
                    if loop.time() - started + delay >= args.duration_seconds:
                        break
                    await asyncio.sleep(delay)
    finally:
        await close_db_engine()


if __name__ == "__main__":
    # Immutable releases invoke tools by absolute path, including outside the
    # checkout. Resolve this release rather than relying on cwd or PYTHONPATH.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--duration-seconds", type=int, default=300)
    parser.add_argument("--interval-seconds", type=int, default=30)
    args = parser.parse_args()
    if (
        not 30 <= args.duration_seconds <= 3600
        or not 15 <= args.interval_seconds <= 300
    ):
        parser.error("duration must be 30..3600 seconds; interval 15..300 seconds")
    asyncio.run(monitor(args))
