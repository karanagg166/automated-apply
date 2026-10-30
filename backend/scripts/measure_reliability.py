"""Bounded loopback/DB observations. Emits no response bodies, SQL or credentials.

Only one observer at a time: --database consumes one runtime connection. The
profile status GET can perform the product's normal expiry reconciliation.
This script never starts workers, sends messages or admits browser commands.
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
PATHS = ("/health", "/ready", "/api/v1/browser/chrome-profiles")


def process_metrics():
    result = subprocess.run(["ps", "-axo", "pid,pcpu,rss,command"],
                            capture_output=True, text=True, check=True, timeout=5)
    groups = {service: [] for service in ("api", "execution", "telegram", "frontend")}
    for line in result.stdout.splitlines()[1:]:
        parts = line.split(None, 3)
        if len(parts) != 4:
            continue
        pid, cpu, rss, command = parts
        for service in groups:
            if ("/backend/scripts/phase1/local_service.py " + service + " --env-file" in command
                    or service == "frontend" and command.startswith("next-server ")):
                groups[service].append({"pid": int(pid), "cpu_percent": float(cpu), "rss_kib": int(rss)})
    return groups


def summary(rows):
    result = {}
    for path in PATHS:
        samples = [sample for row in rows for sample in row["http"] if sample["path"] == path]
        result[path] = {
            "samples": len(samples),
            "status_counts": dict(Counter(str(sample.get("status", sample.get("error"))) for sample in samples)),
            "mean_seconds": round(sum(sample["seconds"] for sample in samples) / len(samples), 4),
            "max_seconds": max(sample["seconds"] for sample in samples),
        }
    return result


async def measure(args):
    import asyncpg
    import httpx

    from backend.app.db.errors import database_failure_code
    from backend.app.db.safety import database_connect_args, database_target
    from backend.app.operations.configuration import load_settings

    settings = load_settings(args.env_file)
    endpoint = urlsplit(settings.LOCAL_AGENT_ENDPOINT)
    if (endpoint.scheme != "http" or endpoint.hostname not in {"127.0.0.1", "localhost", "::1"}
            or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment):
        raise ValueError("configured_loopback_endpoint_required")
    connection = None
    descriptor = os.open(Path(args.output).expanduser(),
                         os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    rows = []
    try:
        with os.fdopen(descriptor, "w") as output:
            metadata = {"type": "configuration", "pool_size": settings.DB_POOL_SIZE,
                        "max_overflow": settings.DB_MAX_OVERFLOW, "database_observer": args.database}
            if args.database:
                target = database_target(settings)
                options = database_connect_args(settings)
                options["server_settings"]["application_name"] = "automated-apply:observer"
                try:
                    connection = await asyncpg.connect(host=target.host, port=target.port or 5432,
                        user=target.username, password=target.password, database=target.database, **options)
                    limits = await connection.fetchrow("""
                        SELECT (SELECT rolconnlimit FROM pg_roles WHERE rolname=current_user) AS role_limit,
                            current_setting('max_connections')::int AS server_limit,
                            current_setting('lock_timeout') AS lock_timeout,
                            current_setting('statement_timeout') AS statement_timeout
                    """)
                    metadata.update(limits)
                except Exception as exc:
                    metadata["database_error"] = database_failure_code(exc)
            output.write(json.dumps(metadata) + "\n")
            async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=12) as client:
                async def request(path):
                    began = time.monotonic()
                    result = {"path": path}
                    try:
                        response = await client.get(settings.LOCAL_AGENT_ENDPOINT.rstrip("/") + path,
                            headers={"Authorization": "Bearer " + settings.JOB_AGENT_API_TOKEN.get_secret_value()})
                        result["status"] = response.status_code
                    except httpx.HTTPError as exc:
                        result["error"] = type(exc).__name__
                    result["seconds"] = round(time.monotonic() - began, 4)
                    return result

                for index in range(args.samples):
                    began = time.monotonic()
                    row = {"type": "sample", "at": datetime.now(timezone.utc).isoformat(),
                           "index": index, "http": await asyncio.gather(*(request(path) for path in PATHS)),
                           "processes": process_metrics()}
                    if connection:
                        try:
                            stats = await connection.fetchrow("""
                                SELECT count(*)::int AS sessions_including_observer,
                                    count(*) FILTER (WHERE cardinality(pg_blocking_pids(pid))>0)::int AS blocked,
                                    coalesce(max(extract(epoch FROM clock_timestamp()-xact_start)),0)::float AS max_transaction_seconds
                                FROM pg_stat_activity WHERE usename=current_user
                            """)
                            row["database"] = dict(stats)
                        except Exception as exc:
                            row["database"] = {"error": database_failure_code(exc)}
                    rows.append(row)
                    output.write(json.dumps(row) + "\n")
                    output.flush()
                    if index + 1 < args.samples:
                        await asyncio.sleep(max(0, args.interval_seconds - (time.monotonic() - began)))
            result = {"type": "summary", "http": summary(rows)}
            output.write(json.dumps(result) + "\n")
            print(json.dumps(result, indent=2))
    finally:
        if connection:
            await connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--interval-seconds", type=int, default=10)
    parser.add_argument("--database", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.samples <= 120 or not 5 <= args.interval_seconds <= 60 or args.samples * args.interval_seconds > 3600:
        parser.error("samples=1..120, interval=5..60s, total<=3600s required")
    asyncio.run(measure(args))
