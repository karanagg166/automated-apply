"""Verify-then-apply runner for followup 004 (Python v2 core tables).

    check  (default) read-only: preserved row counts, v2 table presence and the
           legacy Naukri never-replay fences that would be migrated.
    apply  runs 004 as the Supabase `postgres` admin (password prompted, never
           stored), then migrates the never-replay fences into `applications`
           through the restricted runtime role, and verifies 0 data loss.

Usage (repo root):
    backend/venv/bin/python -m backend.scripts.migrate_v2_core check
    backend/venv/bin/python -m backend.scripts.migrate_v2_core apply --expected-fences 3
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from backend.app.browser_v2.store import dedup_key

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase/fresh_public/followups/004_python_v2_core_tables.sql"
EVIDENCE_DIR = ROOT / "reports/v2-migration"
PRESERVED_TABLES = (
    "jobs", "candidate_profiles", "private_resumes", "application_answer_drafts",
    "owner_preferences", "application_packets", "application_events",
)
SUBMITTED_STAGES = frozenset({"SUBMITTED_RECORDED", "SUBMITTED_CONFIRMED"})
QUARANTINE_REASON = "migrated_historical_quarantine_never_replay"
SUBMITTED_REASON = "migrated_historical_submitted_never_replay"
RECEIPT_REASON = "migrated_receipt_fence_never_replay"
RECEIPT_PREFIXES = ("naukri_receipt:", "naukri_worker_receipt:")
REQUISITION = re.compile(r"^[0-9]{10,20}$")
PGVECTOR_BLOCK = re.compile(r"-- BEGIN pgvector\n.*?-- END pgvector\n", re.DOTALL)


@dataclass(frozen=True)
class MigratedApplication:
    external_job_id: str
    state: str
    reason: str
    company_name: str | None = None
    role_title: str | None = None
    job_url: str | None = None
    job_id: str | None = None
    legacy_key: str | None = None
    platform: str = "naukri"


def _admitted_apply(value: dict) -> bool:
    return any(
        isinstance(action, dict) and str(action.get("fingerprint", "")).startswith("apply:")
        for action in value.get("admitted_actions") or []
    )


def classify_legacy_rows(rows: list[tuple[str, dict]]) -> list[MigratedApplication]:
    """Map legacy owner_preferences rows to never-replay `applications` rows.

    Mirrors the legacy fences: a submitted stage, an unknown submission, an
    admitted Apply action, or any retained receipt row blocks replay forever.
    """
    found: dict[str, MigratedApplication] = {}
    for key, value in rows:
        if not isinstance(value, dict) or not key.startswith("apply_work:"):
            continue
        if value.get("platform") != "naukri":
            continue
        requisition = str(value.get("requisition") or "")
        if not REQUISITION.match(requisition):
            continue
        stage = value.get("stage")
        if stage in SUBMITTED_STAGES:
            state, reason = "APPLIED", SUBMITTED_REASON
        elif stage == "SUBMISSION_UNKNOWN" or _admitted_apply(value):
            state, reason = "SUBMISSION_UNKNOWN", QUARANTINE_REASON
        else:
            continue
        found[requisition] = MigratedApplication(
            external_job_id=requisition, state=state, reason=reason,
            company_name=value.get("company"), role_title=value.get("title"),
            job_url=value.get("url"), job_id=value.get("job_id"), legacy_key=key,
        )
    for key, _value in rows:
        prefix = next((p for p in RECEIPT_PREFIXES if key.startswith(p)), None)
        if prefix is None:
            continue
        requisition = key[len(prefix):]
        if REQUISITION.match(requisition) and requisition not in found:
            found[requisition] = MigratedApplication(
                external_job_id=requisition, state="SUBMISSION_UNKNOWN",
                reason=RECEIPT_REASON, legacy_key=key,
            )
    return sorted(found.values(), key=lambda item: item.external_job_id)


def strip_pgvector(sql: str) -> str:
    """Disposable-database variant for hosts without the pgvector extension."""
    return PGVECTOR_BLOCK.sub("", sql)


def _plain_url(settings) -> str:
    return settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)


async def _runtime(settings):
    import asyncpg

    from backend.app.db.safety import database_connect_args

    return await asyncpg.connect(_plain_url(settings), **database_connect_args(settings))


async def _counts(connection) -> dict[str, int | None]:
    result: dict[str, int | None] = {}
    for table in PRESERVED_TABLES:
        exists = await connection.fetchval("SELECT to_regclass($1) IS NOT NULL", "public." + table)
        result[table] = (
            await connection.fetchval(f'SELECT count(*) FROM public."{table}"') if exists else None
        )
    return result


async def _legacy_rows(connection) -> list[tuple[str, dict]]:
    records = await connection.fetch(
        "SELECT key, value::text AS value FROM public.owner_preferences "
        "WHERE key LIKE 'apply_work:%' OR key LIKE 'naukri_receipt:%' "
        "OR key LIKE 'naukri_worker_receipt:%'"
    )
    return [(r["key"], json.loads(r["value"])) for r in records]


async def _v2_present(connection) -> list[str]:
    from backend.app.operations.v2_schema import TABLES

    rows = await connection.fetch(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relkind='r' AND c.relname=ANY($1::text[])",
        sorted(TABLES),
    )
    return sorted(r["relname"] for r in rows)


async def inspect(settings) -> dict:
    connection = await _runtime(settings)
    try:
        async with connection.transaction(readonly=True):
            fences = classify_legacy_rows(await _legacy_rows(connection))
            return {
                "counts": await _counts(connection),
                "v2_tables_present": await _v2_present(connection),
                "never_replay_fences": [
                    {"external_job_id": f.external_job_id, "state": f.state, "reason": f.reason}
                    for f in fences
                ],
                "_fences": fences,
            }
    finally:
        await connection.close()


async def insert_fences(connection, fences: list[MigratedApplication]) -> int:
    """Idempotent: never downgrades APPLIED/SUBMISSION_UNKNOWN, never deletes."""
    written = 0
    for fence in fences:
        row = await connection.fetchrow(
            """
            INSERT INTO public.applications
                (platform, external_job_id, company_name, role_title, job_url, dedup_key,
                 state, reason, job_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8,
                    (SELECT id FROM public.jobs WHERE id::text = $9))
            ON CONFLICT (platform, external_job_id) DO UPDATE
                SET state = EXCLUDED.state, reason = EXCLUDED.reason,
                    version = public.applications.version + 1, updated_at = now()
                WHERE public.applications.state NOT IN ('APPLIED', 'SUBMISSION_UNKNOWN')
            RETURNING id
            """,
            fence.platform, fence.external_job_id, fence.company_name, fence.role_title,
            fence.job_url, dedup_key(fence.company_name, fence.role_title), fence.state,
            fence.reason, fence.job_id,
        )
        if row is None:
            continue
        written += 1
        await connection.execute(
            "INSERT INTO public.application_state_events "
            "(application_id, from_state, to_state, event_type, payload) "
            "VALUES ($1, NULL, $2, 'migrated_legacy_fence', $3::jsonb)",
            row["id"], fence.state,
            json.dumps({"legacy_key": fence.legacy_key, "reason": fence.reason}),
        )
    return written


async def apply(settings, expected_fences: int, admin_password: str) -> dict:
    import asyncpg

    from backend.app.db.safety import database_connect_args, database_target

    before = await inspect(settings)
    fences = before.pop("_fences")
    if len(fences) != expected_fences:
        raise SystemExit(
            f"refusing: found {len(fences)} never-replay fences, expected {expected_fences}")
    target = database_target(settings)
    admin_uri = target.set(
        drivername="postgresql", username="postgres", password=admin_password,
    ).render_as_string(hide_password=False)
    admin = await asyncpg.connect(admin_uri, **database_connect_args(settings))
    try:
        await admin.execute(MIGRATION.read_text())
    finally:
        await admin.close()
    runtime = await _runtime(settings)
    try:
        async with runtime.transaction():
            written = await insert_fences(runtime, fences)
    finally:
        await runtime.close()
    after = await inspect(settings)
    after.pop("_fences")
    lost = {t: (before["counts"][t], after["counts"][t]) for t in PRESERVED_TABLES
            if before["counts"][t] is not None
            and (after["counts"][t] or 0) < before["counts"][t]}
    report = {"applied_at": datetime.now(UTC).isoformat(), "before": before,
              "after": after, "fences_written": written, "data_loss": lost,
              "fences": [asdict(f) | {"company_name": None, "role_title": None, "job_url": None}
                         for f in fences]}
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = EVIDENCE_DIR / f"apply-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.private.json"
    path.write_text(json.dumps(report, indent=2, default=str) + "\n")
    os.chmod(path, 0o600)
    if lost:
        raise SystemExit(f"DATA LOSS DETECTED: {lost} (evidence {path})")
    report["evidence"] = str(path)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("check", "apply"), nargs="?", default="check")
    parser.add_argument("--expected-fences", type=int)
    parser.add_argument("--env-file", help="private env (default: $AUTOMATED_APPLY_ENV_FILE "
                        "or ~/Library/Application Support/Automated Apply/phase1.private.env)")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    from backend.app.browser_v2.config import load_settings

    settings = load_settings(args.env_file)
    if args.command == "check":
        result = asyncio.run(inspect(settings))
        result.pop("_fences")
    else:
        if args.expected_fences is None:
            parser.error("apply requires --expected-fences N (confirm the check output first)")
        password = os.environ.get("AUTOMATED_APPLY_DB_ADMIN_PASSWORD") or getpass.getpass(
            "Supabase postgres admin password: ")
        result = asyncio.run(apply(settings, args.expected_fences, password))
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
