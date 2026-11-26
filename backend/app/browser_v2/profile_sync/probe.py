"""PII-scrubbed outline of a logged-in portal profile page, for selector calibration.

Captures section headings, field labels, button texts, input descriptors (type/name/id/aria/
placeholder: NEVER values) and which known adapter selectors matched. No screenshot, no raw
HTML, no cookies. Every string is passed through ``ai_v2.pii.scrub_pii`` plus the owner's own
identity values. Written 0600 under ``<runtime>/receipts/profile-probe/``.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.ai_v2.pii import scrub_pii
from backend.app.browser_v2.diagnostics import (
    DOM_PROBE_JS,
    LIST_LIMITS,
    build_probe,
    profile_secrets,
)
from backend.app.browser_v2.receipts import receipts_root

MAX_LABELS = 80
LABELS_JS = r"""
() => {
  const visible = (e) => !!e && e.getClientRects().length > 0 && getComputedStyle(e).visibility !== "hidden";
  const clip = (s) => (s || "").replace(/\s+/g, " ").trim().slice(0, 100);
  const labels = [...document.querySelectorAll("label, legend, [class*='label' i], [class*='widgetTitle']")]
    .filter(visible).map((e) => clip(e.innerText)).filter(Boolean);
  return [...new Set(labels)].slice(0, 80);
}
"""


class ProbeRefused(RuntimeError):
    pass


def probe_dir(root: Path | None = None) -> Path:
    return (root or receipts_root()) / "profile-probe"


def outline(raw: Mapping[str, Any], labels: Any, portal: str, secrets: tuple[str, ...],
            captured_at: datetime | None = None) -> dict[str, Any]:
    """Pure: raw DOM probe + label texts -> scrubbed outline (diagnostics.build_probe whitelists)."""
    payload = build_probe(raw, portal, {}, secrets, captured_at)
    payload.pop("snippets", None)  # free page text (may hold profile values): not needed here
    terms = tuple(s for s in secrets if len(s.strip()) >= 3)
    payload["labels"] = [scrub_pii(str(label)[:100], terms) for label in (labels or [])
                         if isinstance(label, str)][:MAX_LABELS]
    payload["kind"] = "profile_page_outline"
    return payload


async def capture_outline(page: Any, portal: str, adapter: Any, url: str, *,
                          profile: Mapping[str, Any] | None = None, root: Path | None = None) -> dict[str, Any]:
    if not re.match(r"^https://", url or ""):
        raise ProbeRefused("probe_url_must_be_https")
    await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    await page.wait_for_timeout(2500)
    selectors = {name: css for name, css in dict(getattr(adapter, "selectors", {}) or {}).items()
                 if isinstance(css, str) and ":visible" not in css and ":text-is" not in css}
    raw = await page.evaluate(DOM_PROBE_JS, {"selectors": selectors, "limits": LIST_LIMITS})
    labels = await page.evaluate(LABELS_JS)
    payload = outline(raw or {}, labels, portal, profile_secrets(profile))
    folder = probe_dir(root)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / f"{re.sub(r'[^a-z0-9_]+', '_', portal)}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return {"outline": str(path), "bytes": path.stat().st_size,
            "selectors_missed": payload.get("selectors_missed", []), "labels": len(payload["labels"])}
