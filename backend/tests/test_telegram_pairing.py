"""Owner pairing uses genuine update identity fields, never inferred IDs."""
import httpx
import pytest

from backend.app.core.config import Settings
from backend.app.local_agent.telegram import BotAPI, TelegramError, parse_command
from backend.app.local_agent.telegram_pairing import discover_owner, private_start_pair

CHALLENGE = "aa_0123456789abcdef01234567"


def private_message(text=None):
    return {"from": {"id": 4242, "is_bot": False}, "chat": {"id": 4242, "type": "private"},
            "text": text or "/start " + CHALLENGE}


@pytest.mark.parametrize("text", ["/start " + CHALLENGE, "/start@FictionalBot " + CHALLENGE,
                                  "  /start   " + CHALLENGE + "\n"])
def test_pairing_private_fresh_start(text):
    assert private_start_pair(private_message(text), "fictionalbot", CHALLENGE) == (4242, 4242)


@pytest.mark.parametrize("change", [
    {"text": "/start"}, {"text": "/start stale"}, {"text": "/start@otherbot " + CHALLENGE},
    {"text": "/start " + CHALLENGE + " shell"}, {"text": "/apply https://example.org"},
    {"from": {"id": True}}, {"from": {"id": "4242"}}, {"from": {"id": 4242, "is_bot": True}},
    {"chat": {"id": -42, "type": "group"}}, {"chat": {"id": "4242", "type": "private"}},
    {"forward_origin": {"type": "user"}}, {"forward_date": 123}, {"sender_chat": {"id": 42}},
])
def test_pairing_does_not_bind_stale_forwarded_wrong_bot_or_invalid_identity(change):
    assert private_start_pair(private_message() | change, "fictionalbot", CHALLENGE) is None


@pytest.mark.asyncio
async def test_pairing_waits_for_later_message_and_pages_past_old_twenty_updates():
    calls, progress = [], []
    backlog = [{"update_id": index, "message": private_message("/start")} for index in range(100)]
    batches = [[], backlog, [], [{"update_id": 100, "message": private_message()}]]
    class Bot:
        async def call(self, method, payload):
            assert method == "getUpdates"
            calls.append(payload)
            return batches.pop(0)
    async def no_wait(_):
        pass
    pair = await discover_owner(Bot(), "fictionalbot", CHALLENGE, sleep=no_wait, on_progress=progress.append)
    assert pair == (4242, 4242)
    assert len(calls) == 4 and calls[0]["timeout"] > 0 and calls[0]["limit"] == 100
    assert "offset" not in calls[0] and calls[-1]["offset"] == 100
    assert all(payload.get("offset", 0) >= 0 for payload in calls)
    assert all("text" not in event and "message" not in event for event in progress)


@pytest.mark.asyncio
async def test_pairing_timeout_never_asks_to_guess_identity():
    now = [0]
    class Bot:
        async def call(self, method, payload):
            now[0] += 1
            return []
    async def advance(seconds):
        now[0] += seconds
    with pytest.raises(TelegramError, match="private_start_not_observed_before_deadline"):
        await discover_owner(Bot(), "fictionalbot", CHALLENGE, timeout_seconds=2,
                             clock=lambda: now[0], sleep=advance)


@pytest.mark.asyncio
async def test_pairing_stops_on_other_poller_instead_of_retrying_or_changing_webhook():
    calls = []
    class Bot:
        async def call(self, method, payload):
            calls.append(method)
            raise TelegramError("telegram_polling_conflict")
    with pytest.raises(TelegramError, match="telegram_polling_conflict"):
        await discover_owner(Bot(), "fictionalbot", CHALLENGE)
    assert calls == ["getUpdates"]


@pytest.mark.parametrize("status,body,expected", [
    (409, {"ok": False, "description": "Conflict: terminated by other getUpdates request"}, "telegram_polling_conflict"),
    (409, {"ok": False, "description": "Conflict: webhook is active"}, "telegram_webhook_conflict_owner_approval_required"),
    (401, {"ok": False}, "telegram_authentication_failed"),
    (200, [], "telegram_api_error"),
])
@pytest.mark.asyncio
async def test_telegram_transport_conflict_classification_without_token_disclosure(status, body, expected, caplog):
    def handler(_):
        return httpx.Response(status, json=body)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = BotAPI(Settings(_env_file=None, TELEGRAM_BOT_TOKEN="123:fictional-private"), client)
        with pytest.raises(TelegramError, match=expected) as exc:
            await api.call("getUpdates", {"timeout": 20})
        assert "fictional-private" not in str(exc.value) and "fictional-private" not in caplog.text


@pytest.mark.parametrize("updates", [None, {}, [None], [{"update_id": True}], [{"update_id": -1}]])
@pytest.mark.asyncio
async def test_pairing_rejects_malformed_updates(updates):
    class Bot:
        async def call(self, method, payload):
            return updates
    with pytest.raises(TelegramError, match="telegram_updates_response_invalid"):
        await discover_owner(Bot(), "fictionalbot", CHALLENGE)


@pytest.mark.asyncio
async def test_pairing_transient_failure_backoff_is_bounded():
    calls, delays = [], []
    class Bot:
        async def call(self, method, payload):
            calls.append(payload)
            if len(calls) == 1:
                raise TelegramError("telegram_rate_limited", retry_after=3)
            return [{"update_id": 1, "message": private_message()}]
    async def sleep(seconds):
        delays.append(seconds)
    assert await discover_owner(Bot(), "fictionalbot", CHALLENGE, sleep=sleep) == (4242, 4242)
    assert delays == [3]


def test_pairing_start_payload_returns_help_without_gaining_commands():
    assert parse_command("/start " + CHALLENGE) == ("/start", CHALLENGE)
    with pytest.raises(TelegramError, match="unexpected_argument"):
        parse_command("/start run_shell")
