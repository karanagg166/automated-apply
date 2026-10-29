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
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


def lock_observation(document, uid):
    """Missing/ambiguous OS telemetry is unknown, never assumed locked."""
    sessions = []

    def walk(node):
        if isinstance(node, dict):
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
    if (
        len(sessions) != 1
        or type(sessions[0].get("CGSSessionScreenIsLocked")) is not bool
    ):
        return "UNKNOWN"
    return "LOCKED" if sessions[0]["CGSSessionScreenIsLocked"] else "UNLOCKED"


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
    if (
        parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.scheme != "http"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("approved_loopback_endpoint_required")
    output = Path(args.output).expanduser()
    descriptor = os.open(
        output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    try:
        async with httpx.AsyncClient(
            trust_env=False, follow_redirects=False, timeout=15
        ) as client:
            with os.fdopen(descriptor, "w") as log:
                started = asyncio.get_running_loop().time()
                while (
                    asyncio.get_running_loop().time() - started <= args.duration_seconds
                ):
                    sample = {
                        "at": datetime.now(timezone.utc).isoformat(),
                        "screen": mac_lock_state(),
                        "evidence_type": "live_readonly_monitoring",
                        "submitted_by_monitor": False,
                    }
                    try:
                        response = await client.get(
                            endpoint + "/api/v1/execution/naukri",
                            headers={
                                "Authorization": "Bearer "
                                + settings.JOB_AGENT_API_TOKEN.get_secret_value()
                            },
                        )
                        response.raise_for_status()
                        api = response.json()["automation"]
                        async with get_session_factory()() as session:
                            rows = {
                                row.key: row.value
                                for row in (
                                    await session.scalars(
                                        select(OwnerPreference).where(
                                            OwnerPreference.key.in_(
                                                [KEY, HEALTH, "chr_selection"]
                                            )
                                        )
                                    )
                                ).all()
                            }
                        actual = rows.get(KEY, {"state": "STOPPED", "revision": 0})
                        sample.update(
                            state=api["state"],
                            revision=api["revision"],
                            database_agrees=actual["state"] == api["state"]
                            and actual["revision"] == api["revision"],
                            worker_heartbeat_at=rows.get(HEALTH, {}).get(
                                "heartbeat_at"
                            ),
                            selected_profile=rows.get("chr_selection", {}).get(
                                "profile_binding_id"
                            ),
                            extension_heartbeat_at=(
                                api.get("chrome_profile") or {}
                            ).get("last_heartbeat"),
                            last_check_at=api.get("last_check_at"),
                            source_last_check_at=api.get("source_last_check_at"),
                            counts=api["counts"],
                            blockers=api["blockers"],
                        )
                    except Exception:
                        sample["error"] = (
                            "api_or_independent_database_observation_failed"
                        )
                    log.write(json.dumps(sample) + "\n")
                    log.flush()
                    os.fsync(log.fileno())
                    if (
                        asyncio.get_running_loop().time()
                        - started
                        + args.interval_seconds
                        > args.duration_seconds
                    ):
                        break
                    await asyncio.sleep(args.interval_seconds)
    finally:
        await close_db_engine()


if __name__ == "__main__":
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
