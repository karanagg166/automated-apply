"""Transport-only rollback tests. No browser action or provider request."""

import json

import httpx
import pytest

from backend.app.local_agent import native_host
from backend.app.local_agent.contracts import NAUKRI_QUEUE_OPERATIONS, Command
from backend.tests.test_phase1_local_agent import settings


@pytest.mark.parametrize("operation", sorted(NAUKRI_QUEUE_OPERATIONS))
@pytest.mark.parametrize("outcome", ["rollback_then_success", "unmarked_503", "timeout", "three_rollbacks"])
def test_queue_transport_only_retries_explicitly_rolled_back_transactions(operation, outcome, monkeypatch):
    monkeypatch.setattr(native_host.time, "sleep", lambda _: None)
    calls = []
    command = Command(command=operation)
    config = settings(JOB_AGENT_API_TOKEN="fictional-token", CHROME_NATIVE_MESSAGING_ENABLED=True,
                      CHROME_EXTENSION_ID="a" * 32)

    def handler(request):
        calls.append(json.loads(request.content))
        if outcome == "timeout":
            raise httpx.ReadTimeout("fictional uncertain response")
        if outcome == "unmarked_503":
            return httpx.Response(503)
        if outcome == "three_rollbacks" or len(calls) == 1:
            return httpx.Response(503, headers={"X-Automated-Apply-Transaction": "rolled-back"})
        return httpx.Response(200, json={"request_id": str(command.request_id), "ok": True,
                                       "capability": "queue", "data": {"submitted": False}})

    transport = httpx.Client(transport=httpx.MockTransport(handler))
    if outcome == "rollback_then_success":
        result = native_host.forward(command, config, transport)
        assert result["ok"] and not result["data"]["submitted"]
        assert len(calls) == 2 and calls[0] == calls[1]
    else:
        code = {"unmarked_503": "backend_not_ready", "timeout": "backend_timeout",
                "three_rollbacks": "backend_transaction_rolled_back"}[outcome]
        with pytest.raises(ValueError, match=code):
            native_host.forward(command, config, transport)
        assert len(calls) == (3 if outcome == "three_rollbacks" else 1)
