"""Bounded diagnostic timings. Never retain SQL, arguments or business values."""
import json
import time
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

from backend.app.core.logging import logger

trace = ContextVar("request_timing", default=None)


def record(stage, seconds):
    current = trace.get()
    if current is not None:
        entry = current["stages"].setdefault(stage, {"count": 0, "seconds": 0.0, "max_seconds": 0.0})
        entry["count"] += 1
        entry["seconds"] += seconds
        entry["max_seconds"] = max(entry["max_seconds"], seconds)


@contextmanager
def span(stage):
    start = time.perf_counter()
    try:
        yield
    finally:
        record(stage, time.perf_counter() - start)


def timed(stage):
    def decorate(function):
        @wraps(function)
        async def measured(*args, **kwargs):
            with span(stage):
                return await function(*args, **kwargs)
        return measured
    return decorate


def emit(current):
    logger.info("request_timing %s", json.dumps(current, separators=(",", ":")))


def instrument_engine(engine):
    from sqlalchemy import event
    if getattr(engine.sync_engine, "_request_timing_installed", False):
        return
    engine.sync_engine._request_timing_installed = True

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def before(connection, cursor, statement, parameters, context, executemany):
        context._timing_start = time.perf_counter()

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def after(connection, cursor, statement, parameters, context, executemany):
        operation = "write" if context.isinsert or context.isupdate or context.isdelete else "read"
        record("sql_" + operation, time.perf_counter() - context._timing_start)

    @event.listens_for(engine.sync_engine, "handle_error")
    def failed(context):
        execution = context.execution_context
        if execution is not None and hasattr(execution, "_timing_start"):
            record("sql_failed", time.perf_counter() - execution._timing_start)

    @event.listens_for(engine.sync_engine, "checkout")
    def checkout(connection, connection_record, proxy):
        connection_record.info["timing_checkout"] = (time.perf_counter(), trace.get())
        current = trace.get()
        pool = engine.sync_engine.pool
        if current is not None and hasattr(pool, "checkedout"):
            current["pool_peak_checked_out"] = max(current.get("pool_peak_checked_out", 0), pool.checkedout())

    @event.listens_for(engine.sync_engine, "checkin")
    def checkin(connection, connection_record):
        saved = connection_record.info.pop("timing_checkout", None)
        if saved:
            token = trace.set(saved[1])
            try:
                record("connection_occupancy", time.perf_counter() - saved[0])
            finally:
                trace.reset(token)


class RequestTimingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        from uuid import uuid4
        current = {"request_id": str(uuid4()), "stages": {}}
        token = trace.set(current)
        start = time.perf_counter()

        async def measured_send(message):
            if message["type"] == "http.response.start":
                current["status"] = message["status"]
                current["response_start_seconds"] = time.perf_counter() - start
                message = {**message, "headers": [*message.get("headers", []),
                    (b"x-request-id", current["request_id"].encode())]}
            await send(message)

        try:
            await self.app(scope, receive, measured_send)
        finally:
            current["http_seconds"] = time.perf_counter() - start
            emit(current)
            trace.reset(token)
