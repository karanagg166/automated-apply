"""Bounded database diagnostics; never publish exception text or SQL parameters."""

import asyncpg
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.exc import TimeoutError as PoolTimeout

DATABASE_ERRORS = (SQLAlchemyError, asyncpg.PostgresError, asyncpg.InterfaceError)


def database_failure_code(error):
    codes = {
        "55P03": "lock_timeout",
        "40P01": "deadlock",
        "40001": "serialization_failure",
        "53300": "connection_limit",
        "57014": "statement_timeout",
        "08003": "connection_failure",
        "08006": "connection_failure",
        "57P01": "database_shutdown",
    }
    current = error
    seen = set()
    for _ in range(5):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        code = codes.get(getattr(current, "sqlstate", None))
        if code:
            return code
        if isinstance(current, PoolTimeout):
            return "pool_timeout"
        if isinstance(current, TimeoutError):
            return "probe_timeout"
        current = getattr(current, "orig", None) or getattr(current, "__cause__", None)
    return "storage_unavailable"
