"""Verify-then-apply runner for followup 004 (Python v2 core tables).

    check  (default) read-only: preserved row counts, v2 table presence and the
           legacy Naukri never-replay fences that would be migrated.
    apply  runs 004 as the Supabase `postgres` admin (password prompted, never
           stored), then migrates the never-replay fences into `applications`
           through the restricted runtime role, and verifies 0 data loss.
    apply-phase9  runs followup 005 (Phase 9: priority columns, circuit breakers,
           watcher state, agent audit log + memory, profile-sync runs) as admin.
           Requires 004. Additive/idempotent; verifies 0 data loss. Apply it only
           together with code that recognises 005 (the strict public-schema verifier
           of older releases refuses unknown tables at API startup).

Usage (repo root):
    backend/venv/bin/python -m backend.scripts.migrate_v2_core check
    backend/venv/bin/python -m backend.scripts.migrate_v2_core apply --expected-fences 3
    backend/venv/bin/python -m backend.scripts.migrate_v2_core apply-phase9
    backend/venv/bin/python -m backend.scripts.migrate_v2_core apply-followup 007   # then 006
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


async def _v2_present(connection, tables=None) -> list[str]:
    from backend.app.operations.v2_schema import TABLES

    rows = await connection.fetch(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relkind='r' AND c.relname=ANY($1::text[])",
        sorted(TABLES if tables is None else tables),
    )
    return sorted(r["relname"] for r in rows)


async def _phase9_columns(connection) -> dict[str, list[str]]:
    from backend.app.operations.v2_schema import PHASE9_COLUMNS

    present: dict[str, list[str]] = {}
    for table, columns in PHASE9_COLUMNS.items():
        rows = await connection.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=$1 AND column_name=ANY($2::text[])",
            table, list(columns))
        present[table] = sorted(r["column_name"] for r in rows)
    return present


async def inspect(settings) -> dict:
    connection = await _runtime(settings)
    try:
        async with connection.transaction(readonly=True):
            fences = classify_legacy_rows(await _legacy_rows(connection))
            from backend.app.operations.v2_schema import PHASE9_TABLES

            return {
                "counts": await _counts(connection),
                "v2_tables_present": await _v2_present(connection),
                "phase9_tables_present": await _v2_present(connection, PHASE9_TABLES),
                "phase9_columns_present": await _phase9_columns(connection),
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


async def apply(settings, expected_fences: int, admin_password: str | None) -> dict:
    """admin_password=None: the owner already ran 004 in the Supabase SQL Editor (as postgres);
    only the fence migration + verification run, through the restricted runtime role."""
    import asyncpg

    from backend.app.db.safety import database_connect_args, database_target

    before = await inspect(settings)
    fences = before.pop("_fences")
    if len(fences) != expected_fences:
        raise SystemExit(
            f"refusing: found {len(fences)} never-replay fences, expected {expected_fences}")
    if admin_password is not None:
        target = database_target(settings)
        admin_uri = target.set(
            drivername="postgresql", username="postgres", password=admin_password,
        ).render_as_string(hide_password=False)
        admin = await asyncpg.connect(admin_uri, **database_connect_args(settings))
        try:
            await admin.execute(MIGRATION.read_text())
        finally:
            await admin.close()
    else:
        from backend.app.operations.v2_schema import TABLES

        missing = sorted(set(TABLES) - set(before["v2_tables_present"]))
        if missing:
            raise SystemExit(f"refusing --sql-applied: v2 tables still missing {missing}; run "
                             f"{MIGRATION.relative_to(ROOT)} in the Supabase SQL Editor first")
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


def phase9_status(state: dict) -> dict:
    """Pure: is followup 005 fully, partly or not applied (from an `inspect` result)?"""
    from backend.app.operations.v2_schema import PHASE9_COLUMNS, PHASE9_TABLES

    tables = set(state.get("phase9_tables_present") or [])
    columns = state.get("phase9_columns_present") or {}
    missing_columns = {t: sorted(set(c) - set(columns.get(t, []))) for t, c in PHASE9_COLUMNS.items()}
    missing_columns = {t: c for t, c in missing_columns.items() if c}
    if tables == set(PHASE9_TABLES) and not missing_columns:
        status = "applied"
    elif not tables and len(missing_columns) == len(PHASE9_COLUMNS):
        status = "missing"
    else:
        status = "partial"
    return {"status": status, "missing_tables": sorted(set(PHASE9_TABLES) - tables),
            "missing_columns": missing_columns}


async def apply_phase9(settings, admin_password: str) -> dict:
    import asyncpg

    from backend.app.db.safety import database_connect_args, database_target
    from backend.app.operations.v2_schema import PHASE9_MIGRATION, TABLES

    before = await inspect(settings)
    before.pop("_fences")
    missing_core = sorted(set(TABLES) - set(before["v2_tables_present"]))
    if missing_core:
        raise SystemExit(f"refusing: followup 004 tables missing {missing_core}; apply 004 first")
    target = database_target(settings)
    admin_uri = target.set(
        drivername="postgresql", username="postgres", password=admin_password,
    ).render_as_string(hide_password=False)
    admin = await asyncpg.connect(admin_uri, **database_connect_args(settings))
    try:
        await admin.execute(PHASE9_MIGRATION.read_text())
    finally:
        await admin.close()
    after = await inspect(settings)
    after.pop("_fences")
    lost = {t: (before["counts"][t], after["counts"][t]) for t in PRESERVED_TABLES
            if before["counts"][t] is not None
            and (after["counts"][t] or 0) < before["counts"][t]}
    status = phase9_status(after)
    report = {"applied_at": datetime.now(UTC).isoformat(), "migration": PHASE9_MIGRATION.name,
              "before": before, "after": after, "phase9": status, "data_loss": lost}
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = EVIDENCE_DIR / f"apply-phase9-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.private.json"
    path.write_text(json.dumps(report, indent=2, default=str) + "\n")
    os.chmod(path, 0o600)
    if lost:
        raise SystemExit(f"DATA LOSS DETECTED: {lost} (evidence {path})")
    if status["status"] != "applied":
        raise SystemExit(f"phase9 migration incomplete: {status} (evidence {path})")
    report["evidence"] = str(path)
    return report


async def apply_followup(settings, admin_password: str, name: str) -> dict:
    """Run one additive followup (006, 007, ...) as the admin role, with the same no-data-loss check."""
    import asyncpg

    from backend.app.db.safety import database_connect_args, database_target
    from backend.app.operations.v2_schema import FOLLOWUP_MIGRATIONS

    path = FOLLOWUP_MIGRATIONS.get(name)
    if path is None or not path.exists():
        raise SystemExit(f"unknown followup {name!r}: choose from {sorted(FOLLOWUP_MIGRATIONS)}")
    before = await inspect(settings)
    before.pop("_fences")
    if phase9_status(before)["status"] != "applied":
        raise SystemExit("refusing: followup 005 (apply-phase9) must be applied first")
    target = database_target(settings)
    admin_uri = target.set(
        drivername="postgresql", username="postgres", password=admin_password,
    ).render_as_string(hide_password=False)
    admin = await asyncpg.connect(admin_uri, **database_connect_args(settings))
    try:
        await admin.execute(path.read_text())
    finally:
        await admin.close()
    after = await inspect(settings)
    after.pop("_fences")
    lost = {t: (before["counts"][t], after["counts"][t]) for t in PRESERVED_TABLES
            if before["counts"][t] is not None and (after["counts"][t] or 0) < before["counts"][t]}
    report = {"applied_at": datetime.now(UTC).isoformat(), "migration": path.name, "data_loss": lost,
              "before": before["counts"], "after": after["counts"]}
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    evidence = EVIDENCE_DIR / f"apply-{name}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.private.json"
    evidence.write_text(json.dumps(report, indent=2, default=str) + "\n")
    os.chmod(evidence, 0o600)
    if lost:
        raise SystemExit(f"DATA LOSS DETECTED: {lost} (evidence {evidence})")
    report["evidence"] = str(evidence)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("check", "apply", "apply-phase9", "apply-followup"), nargs="?",
                        default="check")
    parser.add_argument("followup", nargs="?", help="apply-followup: 006 | 007")
    parser.add_argument("--expected-fences", type=int)
    parser.add_argument("--sql-applied", action="store_true",
                        help="004 was already run in the Supabase SQL Editor: no admin password needed")
    parser.add_argument("--env-file", help="private env (default: $AUTOMATED_APPLY_ENV_FILE "
                        "or <repo>/.env)")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    from backend.app.browser_v2.config import load_settings

    settings = load_settings(args.env_file)
    if args.command == "check":
        result = asyncio.run(inspect(settings))
        result.pop("_fences")
        result["phase9"] = phase9_status(result)
    elif args.command == "apply-followup":
        if not args.followup:
            parser.error("apply-followup requires a name, e.g. apply-followup 007")
        from backend.app.browser_v2.env_loader import load_env

        followup_password: str = (load_env(args.env_file).get("AUTOMATED_APPLY_DB_ADMIN_PASSWORD")
                                  or getpass.getpass("Supabase postgres admin password: "))
        result = asyncio.run(apply_followup(settings, followup_password, args.followup))
    elif args.command == "apply-phase9":
        from backend.app.browser_v2.env_loader import load_env

        admin_password: str = (load_env(args.env_file).get("AUTOMATED_APPLY_DB_ADMIN_PASSWORD")
                               or getpass.getpass("Supabase postgres admin password: "))
        result = asyncio.run(apply_phase9(settings, admin_password))
    else:
        if args.expected_fences is None:
            parser.error("apply requires --expected-fences N (confirm the check output first)")
        from backend.app.browser_v2.env_loader import load_env

        password = None if args.sql_applied else (
            load_env(args.env_file).get("AUTOMATED_APPLY_DB_ADMIN_PASSWORD")
            or getpass.getpass("Supabase postgres admin password: "))
        result = asyncio.run(apply(settings, args.expected_fences, password))
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
