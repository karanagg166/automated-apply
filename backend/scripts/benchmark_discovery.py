"""Fictional local PostgreSQL benchmark. Never contacts a job provider.

Creates and drops a unique database under the disposable CI database target.
Optional simulated SQL latency is a sensitivity model, not live timing evidence.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


async def benchmark(args):
    parsed = urlsplit(os.environ["PROFILE_TEST_DATABASE_URL"])
    if (
        parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.path != "/candidate_profile_test"
    ):
        raise ValueError("Requires a disposable local candidate_profile_test database")
    admin = await asyncpg.connect(urlunsplit(parsed))
    database = "candidate_profile_test_p22_" + uuid4().hex
    await admin.execute(f'CREATE DATABASE "{database}"')
    url = urlunsplit(parsed._replace(path="/" + database)).replace(
        "postgresql://", "postgresql+asyncpg://", 1
    )
    os.environ.update(
        ENVIRONMENT="testing",
        DATABASE_URL=url,
        DATABASE_SCHEMA="public",
        LOG_LEVEL="ERROR",
    )
    engine = None
    try:
        from sqlalchemy import event
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        from backend.app.models.base import Base
        from backend.app.models.candidate_profile import CandidateProfile
        from backend.app.schemas.discovery import RunRequest
        from backend.app.services.job_discovery_service import JobDiscoveryService
        from backend.app.services.job_sources.direct_api import GreenhouseAdapter
        from backend.app.services.job_sources.factory import JobSourceFactory
        from backend.app.services.job_sources.public_ats import (
            AshbyAdapter,
            LeverAdapter,
        )
        from backend.tests.discovery_fakes import job
        from backend.tests.test_public_ats import configuration, feed, posting

        settings = configuration()

        commit_seconds = []

        class TimedSession(AsyncSession):
            async def commit(self):
                started = time.perf_counter()
                try:
                    return await super().commit()
                finally:
                    commit_seconds.append(round(time.perf_counter() - started, 6))

        engine = create_async_engine(url, pool_size=1, max_overflow=0, pool_timeout=2)
        factory = async_sessionmaker(engine, class_=TimedSession, expire_on_commit=False, autoflush=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            session.add(
                CandidateProfile(
                    full_name="Alex Fictional", email="alex@example.com", version=1
                )
            )
            await session.commit()
        statements = Counter()
        sql_seconds = Counter()

        @event.listens_for(engine.sync_engine, "before_cursor_execute")
        def count_sql(conn, cursor, statement, parameters, context, executemany):
            context.benchmark_started = time.perf_counter()
            statements[statement.split()[0]] += 1
            if args.sql_latency_ms:
                # Runs in SQLAlchemy's greenlet, so other tasks remain responsive.
                from sqlalchemy.util.concurrency import await_only

                await_only(asyncio.sleep(args.sql_latency_ms / 1000))

        @event.listens_for(engine.sync_engine, "after_cursor_execute")
        def time_sql(conn, cursor, statement, parameters, context, executemany):
            sql_seconds[statement.split()[0]] += time.perf_counter() - context.benchmark_started

        for size in args.sizes:
            records = [
                job(
                    source_name="manual",
                    source_job_id=f"{size}-{i}",
                    original_url=f"https://example.com/fictional/{size}/{i}",
                    company_domain=None,
                ).model_dump(mode="json")
                for i in range(size)
            ]
            adapter = {"lever": LeverAdapter, "ashby": AshbyAdapter,
                       "greenhouse": GreenhouseAdapter}.get(args.source)
            http_client = None
            if adapter:
                import httpx

                payload = []
                for i in range(size):
                    record = ({
                        "id": f"{size}-{i}", "title": "Python Engineer",
                        "absolute_url": f"https://boards.greenhouse.io/fictional/jobs/{size}-{i}",
                        "content": "Build APIs using Python. " * 30,
                        "location": {"name": "Bengaluru"},
                    } if adapter is GreenhouseAdapter else posting(adapter))
                    for key in ("id", "jobUrl", "applyUrl", "hostedUrl"):
                        if key in record and isinstance(record[key], str):
                            record[key] = record[key].replace(
                                "fictional-post-001", f"fictional-{size}-post-{i:03}"
                            )
                    payload.append(record)

                async def fictional_feed(request):
                    assert request.method == "GET" and request.url.host in {
                        "api.lever.co",
                        "api.ashbyhq.com",
                        "boards-api.greenhouse.io",
                    }
                    await asyncio.sleep(args.network_latency_ms / 1000)
                    return httpx.Response(200, json={"jobs": payload}
                                          if adapter is GreenhouseAdapter else feed(adapter, payload))

                http_client = httpx.AsyncClient(
                    transport=httpx.MockTransport(fictional_feed)
                )

                class FixtureAdapter(adapter):
                    def __init__(self, **kwargs):
                        if adapter is GreenhouseAdapter:
                            super().__init__(board_token="fictional", company_name="Fictional Employer", http_client=http_client)
                        else:
                            super().__init__(http_client=http_client, settings=settings)

                JobSourceFactory._adapters[args.source] = FixtureAdapter
            statements.clear()
            sql_seconds.clear()
            commit_seconds.clear()
            started = time.perf_counter()
            async with factory() as session:
                result = await JobDiscoveryService(session, factory, settings).run(
                    RunRequest(
                        source=args.source,
                        query={"limit": size},
                        manual_jobs=records if args.source == "manual" else [],
                        idempotency_key=f"benchmark-{size}",
                    )
                )
            if http_client:
                await http_client.aclose()
            print(
                json.dumps(
                    {
                        "size": size,
                        "source": args.source,
                        "seconds": round(time.perf_counter() - started, 4),
                        "sql": dict(statements),
                        "sql_seconds": {k: round(v, 6) for k, v in sql_seconds.items()},
                        "commit_ack_seconds": commit_seconds,
                        "pool_checked_out_after_run": engine.pool.checkedout(),
                        "simulated_sql_latency_ms": args.sql_latency_ms,
                        "simulated_network_latency_ms": args.network_latency_ms,
                        "status": result["status"],
                        "counts": result["counts"],
                        "usage": result["usage"],
                    }
                ),
                flush=True,
            )
    finally:
        if engine:
            await engine.dispose()
        await admin.execute(f'DROP DATABASE "{database}" WITH (FORCE)')
        await admin.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sizes", type=int, nargs="+", default=[3, 27, 100], choices=range(1, 101)
    )
    parser.add_argument(
        "--sql-latency-ms", type=float, default=0, choices=range(0, 101)
    )
    parser.add_argument(
        "--source", choices=["manual", "lever", "ashby", "greenhouse"], default="manual"
    )
    parser.add_argument("--network-latency-ms", type=float, default=0, choices=range(0, 1001))
    asyncio.run(benchmark(parser.parse_args()))
