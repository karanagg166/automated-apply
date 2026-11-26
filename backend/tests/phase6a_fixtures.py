"""Shared Phase 6A test fixtures: a real headless Chromium page whose network is fully
intercepted (no request ever leaves the machine) and small synthetic portal pages."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from backend.app.browser_v2.answers import CandidateFacts

NOW = datetime.now(UTC)
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def facts(tmp_path: Path, **overrides: Any) -> CandidateFacts:
    resume = tmp_path / "backend.pdf"
    resume.write_bytes(PDF)
    ai = tmp_path / "ai.pdf"
    ai.write_bytes(PDF)
    values: dict[str, Any] = dict(
        experience_years=3, skills=("Python", "FastAPI", "PostgreSQL"), skill_years={"python": 3.0},
        notice_period_days=30, willing_to_relocate=True, current_location="Bengaluru",
        identity={"full_name": "Test Candidate", "first_name": "Test", "last_name": "Candidate",
                  "email": "candidate@example.com", "phone": "+910000000000",
                  "linkedin_url": "https://www.linkedin.com/in/example", "current_location": "Bengaluru"},
        resume_files={"backend": str(resume), "ai": {"path": str(ai), "keywords": ["llm"]}})
    values.update(overrides)
    return CandidateFacts(**values)


class Site:
    """URL -> HTML (or callable) map served through context.route; everything else 404s."""

    def __init__(self) -> None:
        self.pages: dict[str, Any] = {}
        self.hits: list[str] = []

    def add(self, url: str, body: Any, *, content_type: str = "text/html") -> None:
        self.pages[url.split("#")[0].split("?")[0].rstrip("/")] = (body, content_type)

    async def handler(self, route: Any) -> None:
        url = route.request.url
        self.hits.append(url)
        key = url.split("#")[0].split("?")[0].rstrip("/")
        if key not in self.pages:
            await route.fulfill(status=404, content_type="text/html", body="<html><body>Not found</body></html>")
            return
        body, content_type = self.pages[key]
        if callable(body):
            body = body(route.request)
        await route.fulfill(status=200, content_type=content_type,
                            body=body if isinstance(body, str) else json.dumps(body))


@pytest_asyncio.fixture(scope="module", loop_scope="module", name="chromium")
async def chromium_fixture():
    try:
        from playwright.async_api import async_playwright

        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=True)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"headless chromium unavailable: {type(exc).__name__}")
    yield browser
    await browser.close()
    await playwright.stop()


@pytest_asyncio.fixture(loop_scope="module", name="web")
async def web_fixture(chromium):
    context = await chromium.new_context()
    site = Site()
    await context.route("**/*", site.handler)
    page = await context.new_page()
    yield page, site
    await context.close()


def html(body: str, title: str = "Test") -> str:
    return f"<!doctype html><html><head><title>{title}</title></head><body>{body}</body></html>"


def days_ago(days: int) -> str:
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
