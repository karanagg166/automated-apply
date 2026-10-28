"""Read-only recognition of the staged, isolated Gmail read account schema."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from sqlalchemy import text

from backend.app.integrations.gmail.schema_checksum import REVIEW_SQL_SHA256
from backend.app.integrations.token_store import ConnectionError

ROOT = Path(__file__).resolve().parents[4]
MIGRATION = ROOT / "backend/scripts/migrations/phase3_gmail_readonly.review.sql"
MANIFEST = Path(__file__).with_name("schema_manifest.json")
ROLLBACK = ROOT / "backend/scripts/migrations/phase35_gmail_readonly_rollback.review.sql"
TABLES = {"gmail_read_accounts", "gmail_read_oauth_states"}


def render_review_sql(schema):
    if schema not in {"public", "job_agent"}:
        raise ValueError("approved_application_schema_required")
    return MIGRATION.read_text().replace("job_agent.", schema + ".")


def render_rollback_sql(schema):
    if schema not in {"public", "job_agent"}:
        raise ValueError("approved_application_schema_required")
    return ROLLBACK.read_text().replace("job_agent.", schema + ".")


async def migration_preflight(connection, schema):
    """Read-only inspection, never repairs partial installs or infers DDL history.

    Run again under the maintenance transaction before executing owner-approved
    DDL. Catalog agreement does not prove backup readiness or owner approval.
    """
    from backend.app.operations.migrations import catalog

    if schema not in {"public", "job_agent"}:
        raise ValueError("approved_application_schema_required")
    actual = await catalog(connection, schema)
    present = TABLES.intersection(actual["tables"])
    if present and present != TABLES:
        raise RuntimeError("gmail_read_schema_partial_install")
    overlay = json.loads(MANIFEST.read_text())["catalogs"][schema]
    if REVIEW_SQL_SHA256 != hashlib.sha256(MIGRATION.read_bytes()).hexdigest():
        raise RuntimeError("gmail_read_schema_reverification_required")
    if present:
        for category, objects in overlay.items():
            if any(actual.get(category, {}).get(k) != v for k, v in objects.items()):
                raise RuntimeError("gmail_read_schema_drift")
        # Extra columns, constraints, policies, triggers and indexes also matter.
        for category in ("columns", "constraints", "policies", "triggers"):
            related = {k: v for k, v in actual[category].items()
                       if k.split(".", 1)[0] in TABLES}
            if related != overlay[category]:
                raise RuntimeError("gmail_read_schema_drift")
        indexes = {row["indexname"]: row["indexdef"] for row in await connection.fetch(
            "SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=$1 AND tablename=ANY($2::text[])",
            schema, sorted(TABLES),
        )}
        if indexes != overlay["indexes"]:
            raise RuntimeError("gmail_read_schema_drift")
    if schema == "public":
        from backend.app.core.config import Settings
        from backend.app.local_agent.public_database import verify_public_database

        await verify_public_database(connection, Settings(
            _env_file=None, DATABASE_SCHEMA=schema, DB_REQUIRE_TLS=False,
        ))
    else:
        from backend.app.operations.runtime_security import verify_restricted_runtime

        await verify_restricted_runtime(connection, actual["tables"], schema=schema)
    return {"status": "installed" if present else "absent", "ddl_executed": False,
            "history": "catalog_evidence_only", "owner_approval_required": True}


def expected_overlay(expected, actual, schema):
    """Accept only a complete pinned catalog overlay; no DDL or silent widening."""
    if not TABLES.intersection(actual.get("tables", {})):
        return expected
    manifest = json.loads(MANIFEST.read_text())
    if REVIEW_SQL_SHA256 != hashlib.sha256(MIGRATION.read_bytes()).hexdigest():
        raise RuntimeError("gmail_read_schema_reverification_required")
    result = deepcopy(expected)
    for category, objects in manifest["catalogs"][schema].items():
        if category == "unsafe_grants":
            continue
        result.setdefault(category, {}).update(objects)
    return result


async def require_read_schema(session, settings):
    if session.get_bind().dialect.name != "postgresql":
        return  # Isolated ORM fixture schemas are created by the test harness.
    for table in sorted(TABLES):
        present = await session.scalar(
            text("SELECT to_regclass(:name) IS NOT NULL"),
            {"name": settings.DATABASE_SCHEMA + "." + table},
        )
        if not present:
            raise ConnectionError("gmail_readonly_schema_update_required")
