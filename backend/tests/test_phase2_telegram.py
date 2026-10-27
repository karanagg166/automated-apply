"""Private-owner mock delivery only; no Bot API network traffic."""

import asyncio

import pytest
from sqlalchemy import select

from backend.app.db.session import get_session_factory
from backend.app.local_agent.models import TelegramDelivery
from backend.app.local_agent.telegram import TelegramError, reply_for, run_worker
from backend.app.models.discovery import DiscoveryRun
from backend.tests.test_agent_execution import config


def message(text):
    return {"from": {"id": 111}, "chat": {"id": 111, "type": "private"}, "text": text}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["success", "no_results", "failed", "running"])
async def test_jobs_distinguishes_empty_failed_and_unknown_suitability(
    db_session, status
):
    db_session.add(
        DiscoveryRun(
            source="manual",
            request_hash="f" * 64,
            status=status,
            counts={"discovered": 0},
            query_summary={"job_ids": []},
        )
    )
    await db_session.commit()
    reply = await reply_for(
        db_session,
        config(TELEGRAM_OWNER_USER_ID=111, TELEGRAM_OWNER_CHAT_ID=111),
        message("/jobs"),
        200,
        "fixture_bot",
    )
    assert "0 saved jobs" in reply and "Suitability requires owner review" in reply
    assert "failed or incomplete run is not a successful zero-match" in reply
    assert "No discovery executed by this command" in reply


@pytest.mark.asyncio
async def test_mock_rate_limit_retries_once_and_restart_never_resends(db_session):
    settings = config(TELEGRAM_OWNER_USER_ID=111, TELEGRAM_OWNER_CHAT_ID=111)
    db_session.add(
        TelegramDelivery(update_id=950, reply="Fictional status", state="pending")
    )
    await db_session.commit()
    stop = asyncio.Event()
    calls = []

    class Bot:
        async def verify(self):
            return {"id": 123, "username": "fixture_bot", "is_bot": True}

        async def call(self, method, payload):
            if method == "getUpdates":
                return []
            assert method == "sendMessage"
            calls.append(payload)
            if len(calls) == 1:
                raise TelegramError("telegram_rate_limited")
            stop.set()
            return {"message_id": 1}

    await run_worker(settings, get_session_factory(), api=Bot(), stop=stop)
    await db_session.refresh(await db_session.get(TelegramDelivery, 950))
    assert (await db_session.get(TelegramDelivery, 950)).state == "sent"
    assert len(calls) == 2 and all(p["chat_id"] == 111 for p in calls)
    # A new process/session never dispatches sent or ambiguous outbox entries.
    db_session.add(
        TelegramDelivery(
            update_id=951, reply="Ambiguous fictional status", state="sending"
        )
    )
    await db_session.commit()
    stop = asyncio.Event()

    class Restarted(Bot):
        async def call(self, method, payload):
            assert method == "getUpdates", "No replay of sent or ambiguous delivery"
            stop.set()
            return []

    await run_worker(settings, get_session_factory(), api=Restarted(), stop=stop)
    assert len(calls) == 2
    assert len((await db_session.scalars(select(TelegramDelivery))).all()) == 2
