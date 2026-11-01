"""Queue controls must never acknowledge an uncommitted policy or Stop."""

import httpx
import pytest

from backend.app.db.session import get_db_session
from backend.app.execution.queue_contracts import QueuePolicy
from backend.app.main import app


def payload(operation):
    return ({"expected_revision": 0, "action": "stop"} if operation == "control"
            else {"expected_revision": 0, "policy": QueuePolicy().model_dump(mode="json")})


@pytest.mark.parametrize("operation", ["control", "policy"])
async def test_queue_mutation_commits_before_response_start(db_session, phase2_auth, operation):
    events = []

    async def transaction():
        try:
            yield db_session
            await db_session.commit()
            events.append("committed")
        except Exception:
            await db_session.rollback()
            raise

    async def observed_app(scope, receive, send):
        async def observed_send(message):
            if message["type"] == "http.response.start":
                events.append("response_started")
            await send(message)
        await app(scope, receive, observed_send)

    app.dependency_overrides[get_db_session] = transaction
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=observed_app), base_url="http://test") as client:
            response = await client.request("POST" if operation == "control" else "PUT",
                "/api/v1/execution/queue/" + operation, headers=phase2_auth, json=payload(operation))
        assert response.status_code == 200, response.text
        assert events == ["committed", "response_started"]
    finally:
        app.dependency_overrides.pop(get_db_session, None)


@pytest.mark.parametrize("operation", ["control", "policy"])
async def test_queue_mutation_cannot_acknowledge_failed_commit(db_session, phase2_auth, monkeypatch, operation):
    from sqlalchemy.exc import SQLAlchemyError

    from backend.app.db import session as sessions

    async def failed_commit():
        raise SQLAlchemyError("fictional commit failure")

    monkeypatch.setattr(db_session, "commit", failed_commit)
    monkeypatch.setattr(sessions, "get_session_factory", lambda: lambda: db_session)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request("POST" if operation == "control" else "PUT",
            "/api/v1/execution/queue/" + operation, headers=phase2_auth, json=payload(operation))
    assert response.status_code == 503
    assert response.json() == {"detail": "Database storage unavailable"}
