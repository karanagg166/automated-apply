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
TABLES = {"gmail_read_accounts", "gmail_read_oauth_states"}


def render_review_sql(schema):
    if schema not in {"public", "job_agent"}:
        raise ValueError("approved_application_schema_required")
    return MIGRATION.read_text().replace("job_agent.", schema + ".")


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
