"""Phase 5 Layer 5: opt-in, non-destructive live smoke harness.

Skipped by default (pytest.ini addopts `-m "not live"`). Run explicitly:

    backend/venv/bin/python -m pytest -m live backend/tests/test_v2_live_smoke.py -s
    LIVE_SMOKE_BROWSER=1 ...   # also launch Brave on the dedicated profile (check-session)
    LIVE_SMOKE_MAIL_APP=1 ...  # also probe Mail.app scripting (one-time Automation prompt)

Zero applications submitted, zero emails created or delivered, zero database writes.
Unconfigured integrations are skipped, not failed.
"""

import os

import pytest

from backend.app.browser_v2 import live_smoke

pytestmark = pytest.mark.live
LIVE_ENV_NAMES = ("DATABASE_URL", "DATABASE_SCHEMA", "ENVIRONMENT", "LOG_LEVEL", "SECRET_KEY")


@pytest.fixture(autouse=True)
def block_external_http():
    """Override the unit-test HTTP ban: live smoke must reach the real (free) services."""
    yield


@pytest.fixture(autouse=True)
def private_env(monkeypatch):
    """conftest blanks credentials for unit tests; restore the owner's private env file values."""
    for name, value in list(os.environ.items()):
        if value == "" or name in LIVE_ENV_NAMES:
            monkeypatch.delenv(name, raising=False)
    for name in ("MAIL_APP_FALLBACK_DISABLED", "ENRICHMENT_FETCH_CAREERS_PAGE"):
        monkeypatch.delenv(name, raising=False)


def report(result):
    print(f"\n[{result['check']}] ok={result['ok']} skipped={result['skipped']} details={result['details']}")
    if result["skipped"]:
        pytest.skip(f"{result['check']}: {result['skipped']}")
    return result


async def test_live_supabase_schema_is_ready_read_only():
    result = report(await live_smoke.check_db())
    assert result["ok"], result["details"]


@pytest.mark.skipif(os.environ.get("LIVE_SMOKE_BROWSER") != "1", reason="set LIVE_SMOKE_BROWSER=1 to launch Brave")
async def test_live_brave_profile_session_check():
    result = report(await live_smoke.check_browser("naukri"))
    assert result["ok"], result["details"]


async def test_live_embedding_and_free_llm_health():
    result = report(await live_smoke.check_ai())
    assert result["details"]["dimensions"] == 384


async def test_live_telegram_get_me_and_conflict_probe():
    result = report(await live_smoke.check_telegram())
    assert result["details"].get("bot_username") and result["ok"], result["details"]


async def test_live_imap_drafts_readonly_login():
    result = report(await live_smoke.check_mail(mail_app=os.environ.get("LIVE_SMOKE_MAIL_APP") == "1"))
    assert result["ok"], result["details"]
    assert result["details"]["config"]["permission"] == "READ_AND_DRAFT_ONLY"


async def test_live_enrichment_status_spends_no_credits():
    result = report(await live_smoke.check_enrichment())
    before = {p["provider"]: p["used_today"] for p in result["details"]["providers"]}
    again = await live_smoke.check_enrichment()
    assert {p["provider"]: p["used_today"] for p in again["details"]["providers"]} == before
