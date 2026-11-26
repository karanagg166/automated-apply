"""Phase 5 Layer 2: CLI (mail-status, test-draft, enrichment-status, live-smoke) and FastMCP tools.

No real IMAP, osascript, Supabase or HTTP: the private env file is replaced by an
empty temp file and services fall back to the in-memory store.
"""

import json

import pytest

from backend.app.browser_v2 import browser_mcp, cli
from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import MemoryStore


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    private = tmp_path / "test.env"
    private.write_text("")
    monkeypatch.setenv("AUTOMATED_APPLY_ENV_FILE", str(private))
    monkeypatch.setenv("AI_V2_DISABLED", "true")


def run(capsys, *argv):
    code = cli.main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def test_mail_status_reports_the_locked_permission_and_unconfigured_channel(capsys):
    code, body = run(capsys, "mail-status")
    assert code == 1 and body["permission"] == "READ_AND_DRAFT_ONLY"
    assert body["label"] == "Gmail Permission: Read + Draft Only (Sending Disabled)"
    assert body["config"]["active_channel"] == "unconfigured"


def test_test_draft_dry_run_previews_a_marked_template_without_saving(capsys):
    code, body = run(capsys, "test-draft", "--to", "hr@example.com", "--company", 'Acme"; rm -rf /',
                     "--role", "Backend Engineer", "--dry-run", "--no-llm")
    assert code == 0 and body["dry_run"] is True and body["saved"] is False
    assert body["preview"]["subject"].startswith("[TEST DRAFT] Application: Backend Engineer")
    assert body["preview"]["composer"] == "template" and body["preview"]["channel"] == "unconfigured"


def test_test_draft_refuses_an_invalid_recipient_and_unconfigured_mail(capsys):
    code, body = run(capsys, "test-draft", "--to", "a@b.io, c@d.io", "--company", "Acme", "--role", "Dev")
    assert code == 2 and body["error"] == "invalid_recipient"
    code, body = run(capsys, "test-draft", "--to", "hr@example.com", "--company", "Acme", "--role", "Dev",
                     "--no-llm")
    assert code == 1 and body["saved"] is False and body["error"] == "mail_unconfigured"


def test_enrichment_status_lists_three_providers_with_caps(capsys):
    code, body = run(capsys, "enrichment-status")
    assert code == 0 and [p["provider"] for p in body["providers"]] == ["apollo", "apify", "signalhire"]
    assert [p["daily_cap"] for p in body["providers"]] == [10, 5, 5]


def test_live_smoke_reports_json_and_skips_unconfigured_checks(capsys):
    code, body = run(capsys, "live-smoke", "--check", "mail", "--check", "telegram", "--check", "enrichment")
    by = {c["check"]: c for c in body["checks"]}
    assert code == 0 and body["ok"] is True
    assert by["mail"]["skipped"].startswith("imap_unconfigured") and by["telegram"]["skipped"] == "unconfigured"
    assert by["enrichment"]["ok"] and "no email created or delivered" in body["guarantees"]


def test_login_setup_defaults_to_adapter_ready_portals(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "login_setup", lambda portals: seen.setdefault("portals", portals) and 0)
    cli.main(["login-setup"])
    # Phase 6A: every login portal now has an adapter (feeds/ATS boards need no login).
    assert seen["portals"] == ["instahyre", "internshala", "naukri", "wellfound", "work_at_a_startup"]
    seen.clear()
    cli.main(["login-setup", "--all"])
    assert len(seen["portals"]) == 8 and "greenhouse" not in seen["portals"]


# --- FastMCP --------------------------------------------------------------------------------
@pytest.fixture
def mcp_store(monkeypatch):
    from backend.app.browser_v2.service import BrowserService
    from backend.tests.test_browser_v2_worker import FakeManager

    store = MemoryStore(profile={"full_name": "Test Candidate"})
    service = BrowserService(FakeManager(), store)  # type: ignore[arg-type]
    monkeypatch.setattr(browser_mcp, "_service", service)
    return store


async def test_mcp_registers_the_phase5_tools_and_no_delivery_tool():
    names = {tool.name for tool in await browser_mcp.mcp.list_tools()}
    assert {"enrich_company_contact", "create_application_gmail_draft", "list_email_drafts",
            "get_mail_and_enrichment_status"} <= names
    assert not [n for n in names if "send" in n or "deliver" in n]


async def test_mcp_enrich_and_status_tools(mcp_store):
    enriched = await browser_mcp.enrich_company_contact(company_name="Acme", company_domain="acme.io",
                                                        jd_text="Write to jobs@acme.io")
    assert (enriched["status"], enriched["email"]) == ("FOUND", "jobs@acme.io")
    status = await browser_mcp.get_mail_and_enrichment_status()
    assert status["mail"]["permission"] == "READ_AND_DRAFT_ONLY" and len(status["enrichment"]["providers"]) == 3


async def test_mcp_draft_tool_without_mail_config_queues_nothing_and_lists_nothing(mcp_store):
    record = await mcp_store.upsert_discovered(JobListing(platform="naukri", external_job_id="m-1",
                                                          url="https://example.com/m", title="Dev", company="Acme"))
    result = await browser_mcp.create_application_gmail_draft(record.id)
    assert result["ok"] is False and result["code"] == "quota_hit_queued_draft_unavailable"
    assert (await browser_mcp.create_application_gmail_draft("missing"))["code"] == "not_found"
    mcp_store.records[("naukri", "m-1")].state = S.APPLYING
    assert (await browser_mcp.create_application_gmail_draft(record.id))["code"] == "application_in_flight"
    assert await browser_mcp.list_email_drafts() == {"total": 0, "items": []}
