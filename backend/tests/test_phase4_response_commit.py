"""Success must not reach a browser before the packet transaction commits."""

import httpx
import pytest

from backend.app.db.session import get_db_session
from backend.app.main import app


@pytest.mark.parametrize("path", ["/api/v1/applications/platforms", "/api/v1/application-packets"])
async def test_packet_and_browser_transaction_ends_before_response_start(db_session, phase2_auth, path):
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
            response = await client.get(path, headers=phase2_auth)
        assert response.status_code == 200, response.text
        assert events == ["committed", "response_started"]
    finally:
        app.dependency_overrides.pop(get_db_session, None)


async def test_packet_commit_failure_returns_storage_error_before_any_success(db_session, phase2_auth, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError

    from backend.app.db import session as sessions

    async def failed_commit():
        raise SQLAlchemyError("fictional commit failure")
    monkeypatch.setattr(db_session, "commit", failed_commit)
    monkeypatch.setattr(sessions, "get_session_factory", lambda: lambda: db_session)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/applications/platforms", headers=phase2_auth)
    assert response.status_code == 503
    assert response.json() == {"detail": "Database storage unavailable"}
