"""Review-only Phase 3 DDL and transaction tests in unique loopback databases."""

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def verify(url, write_manifest=False):
    parsed = urlsplit(url)
    if (
        parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.path != "/candidate_profile_test"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Only disposable localhost candidate_profile_test is permitted"
        )
    cluster = await asyncpg.connect(url)
    if await cluster.fetchval(
        "SELECT EXISTS(SELECT FROM pg_roles WHERE rolname IN ('job_agent_owner','job_agent_runtime'))"
    ):
        await cluster.close()
        raise RuntimeError("dedicated_fixture_roles_must_be_absent")
    from backend.app.integrations.gmail.schema import (
        MANIFEST,
        MIGRATION,
        TABLES,
        render_review_sql,
    )
    from backend.app.operations.migrations import catalog

    catalogs = {}
    try:
        for schema in ("job_agent", "public"):
            database = "candidate_profile_test_p3_" + uuid4().hex
            await cluster.execute(f'CREATE DATABASE "{database}"')
            child = await asyncpg.connect(
                urlunsplit(parsed._replace(path="/" + database))
            )
            created_roles = False
            try:
                assert (
                    int(await child.fetchval("SHOW server_version_num")) // 10000 == 17
                )
                for name in ("anon", "authenticated", "service_role"):
                    if not await child.fetchval(
                        "SELECT EXISTS(SELECT FROM pg_roles WHERE rolname=$1)", name
                    ):
                        await child.execute(f'CREATE ROLE "{name}" NOLOGIN')
                if schema == "public":
                    await child.execute(
                        (
                            ROOT / "supabase/fresh_public/001_phase1_public.sql"
                        ).read_text()
                    )
                else:
                    await child.execute(
                        (ROOT / "docs/sql/phase9-role-bootstrap.sql").read_text()
                    )
                    for path in sorted((ROOT / "supabase/migrations").glob("*.sql")):
                        await child.execute(path.read_text())
                    await child.execute(
                        (ROOT / "docs/sql/phase9-runtime-hardening.sql").read_text()
                    )
                    await child.execute(
                        (ROOT / "docs/sql/phase10-runtime-addendum.sql").read_text()
                    )
                created_roles = True
                before = await catalog(child, schema)
                await child.execute(render_review_sql(schema))
                await child.execute(render_review_sql(schema))
                after = await catalog(child, schema)
                # No baseline object, grant, constraint or function changes.
                for category, entries in before.items():
                    if category == "unsafe_grants":
                        assert after[category] == entries == []
                    else:
                        assert all(
                            after[category].get(k) == v for k, v in entries.items()
                        ), category
                delta = {
                    k: {
                        name: value
                        for name, value in values.items()
                        if name not in before[k]
                    }
                    for k, values in after.items()
                    if k != "unsafe_grants"
                }
                assert set(delta["tables"]) == TABLES
                catalogs[schema] = delta
                # Runtime can use exactly these private tables, never write scopes.
                await child.execute("SET ROLE job_agent_runtime")
                account_id = await child.fetchval(
                    f"INSERT INTO {schema}.gmail_read_accounts(provider,google_subject,account_email,connected_at) VALUES('gmail','first-subject','first@example.com',now()) RETURNING id"
                )
                await child.execute(
                    f"INSERT INTO {schema}.gmail_read_accounts(provider,google_subject,account_email,connected_at) VALUES('gmail','second-subject','second@example.com',now())"
                )
                assert (
                    await child.fetchval(
                        f"SELECT count(*) FROM {schema}.gmail_read_accounts"
                    )
                    == 2
                )
                async with child.transaction():
                    await child.execute(
                        f"UPDATE {schema}.gmail_read_accounts SET token_generation=2 WHERE id=$1",
                        account_id,
                    )
                for statement in (
                    f"UPDATE {schema}.gmail_read_accounts SET granted_scopes='[\"https://www.googleapis.com/auth/gmail.send\"]'",
                    f"DELETE FROM {schema}.gmail_read_accounts",
                    f"ALTER TABLE {schema}.gmail_read_accounts DISABLE ROW LEVEL SECURITY",
                ):
                    try:
                        async with child.transaction():
                            await child.execute(statement)
                    except (
                        asyncpg.CheckViolationError,
                        asyncpg.InsufficientPrivilegeError,
                    ):
                        pass
                    else:
                        raise AssertionError("Forbidden credential operation succeeded")
                await child.execute("RESET ROLE")
                # Verify the exact pinned catalog overlay under the restricted role.
                if not write_manifest:
                    from backend.app.core.config import Settings
                    from backend.app.integrations.gmail.schema import expected_overlay
                    from backend.app.operations.runtime_security import (
                        verify_restricted_runtime,
                    )

                    expected = expected_overlay(before, after, schema)
                    assert expected == after
                    await child.execute("SET ROLE job_agent_runtime")
                    await verify_restricted_runtime(
                        child, expected["tables"], schema=schema
                    )
                    if schema == "public":
                        from backend.app.local_agent.public_database import (
                            verify_public_database,
                        )

                        await verify_public_database(
                            child,
                            Settings(
                                _env_file=None,
                                DATABASE_SCHEMA="public",
                                DB_REQUIRE_TLS=False,
                            ),
                        )
                    await child.execute("RESET ROLE")
                for role in ("anon", "authenticated", "service_role"):
                    await child.execute(f'SET ROLE "{role}"')
                    try:
                        async with child.transaction():
                            await child.fetch(
                                f"SELECT * FROM {schema}.gmail_read_accounts"
                            )
                    except asyncpg.InsufficientPrivilegeError:
                        pass
                    else:
                        raise AssertionError(
                            "Browser/service role could read private tokens"
                        )
                    await child.execute("RESET ROLE")
                # A separate database session sees committed state and cannot see rollback.
                other = await asyncpg.connect(
                    urlunsplit(parsed._replace(path="/" + database))
                )
                try:
                    assert (
                        await other.fetchval(
                            f"SELECT token_generation FROM {schema}.gmail_read_accounts WHERE id=$1",
                            account_id,
                        )
                        == 2
                    )
                    transaction = child.transaction()
                    await transaction.start()
                    await child.execute(
                        f"UPDATE {schema}.gmail_read_accounts SET token_generation=3 WHERE id=$1",
                        account_id,
                    )
                    await transaction.rollback()
                    assert (
                        await other.fetchval(
                            f"SELECT token_generation FROM {schema}.gmail_read_accounts WHERE id=$1",
                            account_id,
                        )
                        == 2
                    )
                finally:
                    await other.close()
                if schema == "job_agent":
                    os.environ.update(
                        ENVIRONMENT="testing",
                        DATABASE_SCHEMA="job_agent",
                        DATABASE_URL=urlunsplit(
                            parsed._replace(path="/" + database)
                        ).replace("postgresql://", "postgresql+asyncpg://", 1),
                    )
                    from sqlalchemy.ext.asyncio import (
                        async_sessionmaker,
                        create_async_engine,
                    )

                    from backend.app.core.config import Settings, configure_operator

                    configure_operator(Settings(_env_file=None))
                    from backend.app.ai.schemas import GenerateRequest
                    from backend.app.knowledge.missing_input import (
                        MissingInputApprove,
                        MissingInputEdit,
                        MissingInputService,
                    )
                    from backend.app.repositories.candidate_profile import (
                        CandidateProfileRepository,
                        ProfileConflictError,
                    )
                    from backend.app.schemas.candidate_profile import (
                        CandidateProfileCreate,
                    )
                    from backend.app.services.application_answer_service import (
                        ApplicationAnswerService,
                    )

                    engine = create_async_engine(
                        os.environ["DATABASE_URL"], hide_parameters=True
                    )
                    factory = async_sessionmaker(engine, expire_on_commit=False)
                    try:
                        async with factory() as session:
                            profile = await CandidateProfileRepository(
                                session
                            ).create_primary_profile(
                                CandidateProfileCreate(
                                    full_name="Fictional Phase3",
                                    email="fictional@example.com",
                                )
                            )
                            await session.commit()
                            generated = await ApplicationAnswerService(
                                session
                            ).generate(
                                GenerateRequest(
                                    question="Describe the hardest API integration bug you personally solved"
                                )
                            )
                            assert (
                                generated.status == "needs_input"
                                and generated.answer is None
                            )
                            request_id = generated.missing_input_id
                            await session.commit()

                        async def writer(answer):
                            async with factory() as session:
                                try:
                                    return await MissingInputService(session).edit(
                                        request_id,
                                        MissingInputEdit(
                                            expected_version=1,
                                            answer=answer,
                                            evidence_note="Fictional owner incident notes",
                                        ),
                                    )
                                except ProfileConflictError:
                                    await session.rollback()
                                    return None

                        writers = await asyncio.gather(
                            writer("First factual draft"),
                            writer("Second factual draft"),
                        )
                        assert sum(value is not None for value in writers) == 1
                        async with factory() as session:
                            service = MissingInputService(session)
                            saved = await service.read(request_id)
                            assert saved["version"] == 2 and saved["status"] == "draft"
                            await service.approve(
                                request_id,
                                MissingInputApprove(
                                    expected_version=2,
                                    expected_profile_version=profile.version,
                                    factual_confirmation=True,
                                ),
                            )
                        await engine.dispose()
                        # Reopen the pool to demonstrate durable acknowledgments after restart.
                        async with factory() as session:
                            saved = await MissingInputService(session).read(request_id)
                            assert (
                                saved["status"] == "approved"
                                and len(
                                    await MissingInputService(session).history(
                                        request_id
                                    )
                                )
                                == 2
                            )
                    finally:
                        await engine.dispose()
            finally:
                await child.close()
                await cluster.execute(f'DROP DATABASE "{database}" WITH (FORCE)')
                if created_roles:
                    await cluster.execute(
                        "DROP ROLE job_agent_runtime, job_agent_owner"
                    )
        manifest = {"catalogs": catalogs}
        checksum = hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
        checksum_file = MANIFEST.with_name("schema_checksum.py")
        if write_manifest:
            MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            checksum_file.write_text(
                '"""Public checksum of the reviewed SQL template, generated by the PostgreSQL verifier."""\n\nREVIEW_SQL_SHA256 = '
                + repr(checksum)
                + "  # pragma: allowlist secret -- public SQL SHA-256, not a credential\n"
            )
        else:
            assert json.loads(MANIFEST.read_text()) == manifest
            from backend.app.integrations.gmail.schema_checksum import REVIEW_SQL_SHA256

            assert REVIEW_SQL_SHA256 == checksum
        print(
            "Phase 3 PostgreSQL PASS: 2 schemas, replay-safe staged DDL, unchanged baseline catalog, isolated accounts, read-only scope constraint, RLS/grant denials, commit/rollback and session recovery"
        )
    finally:
        await cluster.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()
    asyncio.run(verify(os.environ["PROFILE_TEST_DATABASE_URL"], args.write_manifest))
