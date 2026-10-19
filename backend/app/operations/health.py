"""Dependency health uses bounded reads. Optional integrations never gate liveness."""

import asyncio

from sqlalchemy import literal, select, table, text


async def database_health(engine, settings):
    async with asyncio.timeout(10):
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            if settings.ENVIRONMENT in {"staging", "production"}:
                # Prepared statements inspect only catalog entries; no DDL or table data.
                import json

                from backend.app.operations.migrations import MANIFEST

                tables = json.loads(MANIFEST.read_text())["catalog"]["tables"]
                for table_name in tables:
                    exists = await connection.scalar(
                        text("SELECT to_regclass(:table)"),
                        {"table": settings.DATABASE_SCHEMA + "." + table_name},
                    )
                    if exists is None:
                        raise RuntimeError("required_database_schema_missing")
                    # Table names come only from the committed fixed manifest.
                    await connection.execute(
                        select(literal(1)).select_from(table(table_name, schema="job_agent")).limit(0)
                    )
