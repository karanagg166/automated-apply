"""Fictional Phase 3 transport inside the disposable PostgreSQL browser harness.

Uses actual account storage, encryption, selected-message sync, evidence, imports
and owner APIs. Provider HTTP is intercepted; no genuine account is contacted.
"""

import asyncio
import base64
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import httpx
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.security import require_api_token
from backend.app.db.session import get_db_session
from backend.app.integrations.gmail.read_service import GmailReadService, ReadPolicy
from backend.app.integrations.google_oauth import READ_SCOPES
from backend.app.integrations.token_store import TokenStore
from backend.app.models.connected_account import GmailReadAccount

ACCOUNT_IDS = [UUID("10000000-0000-4000-8000-000000000001"), UUID("10000000-0000-4000-8000-000000000002")]
QUESTION = "Describe the fictional payment gateway incident you personally resolved in October."


async def install(app, settings, factory):
    from backend.app.api.v1.integrations import read_service

    calls = []
    addresses = ["first-fixture@example.com", "second-fixture@example.com"]
    tokens = {"fixture-access-1": 0, "fixture-access-2": 1}

    def respond(request):
        # Only the production GmailReadClient's GET requests are accepted here.
        assert request.method == "GET"
        assert request.url.host == "gmail.googleapis.com"
        index = tokens[request.headers["Authorization"].removeprefix("Bearer ")]
        prefix = "/gmail/v1/users/me/messages"
        calls.append({"method": request.method, "path": request.url.path, "account_id": str(ACCOUNT_IDS[index])})
        message = f"fixture-message-{index + 1}"
        if request.url.path == prefix:
            return httpx.Response(200, json={"messages": [{"id": message}]})
        assert request.url.path == prefix + "/" + message
        payload = {
            "mimeType": "text/plain",
            "headers": [{"name": "From", "value": "jobs@example.org"}, {"name": "Subject", "value": "Job alert: fictional engineer"}],
        }
        if request.url.params.get("format") == "full":
            raw = f"Job alert https://fixture-company-{index + 1}.example/jobs/backend?tracking=discarded"
            payload["body"] = {"data": base64.urlsafe_b64encode(raw.encode()).decode()}
        return httpx.Response(200, json={"id": message, "threadId": f"fixture-thread-{index + 1}", "internalDate": str(int((datetime.now(timezone.utc) - timedelta(minutes=2)).timestamp() * 1000)), "labelIds": ["Label_Jobs"], "payload": payload})

    class FixtureIdentity:
        async def identity(self, token):
            index = tokens[token]
            return f"fixture-subject-{index + 1}", addresses[index]

        async def revoke(self, token):
            return None  # Local fictional revocation, never a provider request.

    def service(session):
        # MockTransport has no sockets; production read, path and evidence guards run.
        return GmailReadService(session, settings, google=FixtureIdentity(), client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))

    async def dependency(session: AsyncSession = Depends(get_db_session)):
        instance = service(session)
        try:
            yield instance
        finally:
            await instance.client.aclose()

    store = TokenStore(settings)
    async with factory() as session:
        for index, account_id in enumerate(ACCOUNT_IDS):
            session.add(GmailReadAccount(
                id=account_id, google_subject=f"fixture-subject-{index + 1}",
                account_email=addresses[index], connected_at=datetime.now(timezone.utc),
                last_verified_at=datetime.now(timezone.utc), status="connected",
                granted_scopes=sorted(READ_SCOPES), encryption_key_id="fixture-v1",
                encrypted_access_token=store.encrypt(f"fixture-access-{index + 1}", str(account_id) + ":access"),
                encrypted_refresh_token=store.encrypt(f"fixture-refresh-{index + 1}", str(account_id) + ":refresh"),
                token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ))
        await session.commit()
        for account_id in ACCOUNT_IDS:
            instance = service(session)
            try:
                await instance.configure(account_id, ReadPolicy(expected_version=0, enabled=True, label_allowlist=["Label_Jobs"], read_body=True, body_purpose="Fictional browser test of selected job alerts"))
                await instance.sync(account_id)
            finally:
                await instance.client.aclose()

    app.dependency_overrides[read_service] = dependency

    @app.get("/_fictional_test/phase3-provider-audit", dependencies=[Depends(require_api_token)])
    async def audit():
        return {"fixture": True, "calls": calls, "mailbox_writes": 0, "external_requests": 0}

    output = Path(__file__).resolve().parents[2] / "reports/phase3-browser-fixture.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps({"fixture": True, "account_ids": [str(value) for value in ACCOUNT_IDS], "question": QUESTION}))


if __name__ == "__main__":
    from backend.scripts.browser_mock_demo import run

    asyncio.run(run(os.environ["PROFILE_TEST_DATABASE_URL"], serve=True, submission_demo=True, phase3_demo=True))
