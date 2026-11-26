"""Selector self-diagnostic bundles for live adapter verification (Phase 6B).

`cli check-session --debug-selectors` and `cli test-apply --dry-run --debug-selectors` save
one compact bundle per probed page under
`~/Library/Application Support/automated-apply/receipts/diagnostics/<portal>-<ts>/`:

- `page.png`        viewport screenshot (local only, never uploaded)
- `dom_probe.json`  <= 30 KB, PII-scrubbed: buttons, headings, input *descriptors* (never
                    values), modal candidates, applicant/age snippets, and which adapter
                    selectors / button regexes matched vs. missed.

No raw HTML, cookies, storage, tokens or input values are read. Refused outside dry-run.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from backend.app.ai_v2.pii import scrub_pii

MAX_PROBE_BYTES = 30 * 1024
MAX_TEXT = 100
LIST_LIMITS = {"buttons": 40, "headings": 15, "inputs": 40, "modals": 10, "snippets": 12}
# Whitelists: an input's value (or anything else a page might expose) is never persisted.
BUTTON_KEYS = ("tag", "text", "id", "cls", "disabled")
INPUT_KEYS = ("tag", "type", "name", "id", "aria", "placeholder", "required")
MODAL_KEYS = ("tag", "role", "cls", "fields", "buttons")

# Naukri's adapter keeps its selectors inside JS probes; mirror the auth ones here.
NAUKRI_SELECTORS = {
    "logged_in": ".nI-gNb-drawer__icon,.nI-gNb-icon-img,.nI-gNb-info,.nI-gNb-drawer,"
                 "a[href*=\"/mnjuser/profile\"],.view-profile-wrapper",
    "login_form": "input[type=password],#usernameField,form[name=\"login-form\"],#loginForm,[class*=\"loginForm\"]",
    "otp": "input[autocomplete=\"one-time-code\"],input[name*=\"otp\" i],input[id*=\"otp\" i]",
    "captcha": "iframe[src*=\"captcha\"],[data-sitekey]",
    "apply_button": "#apply-button,button[id*=\"apply\" i],[class*=\"apply-button\" i]",
    "chatbot_drawer": "[class*=\"chatbot\" i],[class*=\"_chatBotContainer\" i]",
}
NAUKRI_PATTERNS = {"apply_text": r"^(?:apply|apply now|easy apply)$", "applied_text": r"^applied$",
                   "external_text": r"apply on company (?:site|website)"}

DOM_PROBE_JS = r"""
({selectors, limits}) => {
  const visible = (el) => !!el && el.isConnected && el.getClientRects().length > 0
    && getComputedStyle(el).visibility !== "hidden";
  const clip = (s, n) => (s || "").replace(/\s+/g, " ").trim().slice(0, n || 100);
  const label = (el) => clip(el.innerText || el.value && el.type === "submit" && el.value
    || el.getAttribute("aria-label") || el.getAttribute("title") || "");
  const all = (sel) => { try { return [...document.querySelectorAll(sel)]; } catch (e) { return null; } };
  const buttons = (all("button, [role=button], a[role=button], input[type=submit], input[type=button], a[class*='apply' i]") || [])
    .filter(visible).slice(0, limits.buttons).map(el => ({tag: el.tagName.toLowerCase(), text: label(el),
      id: clip(el.id, 60) || null, cls: clip(el.className && el.className.baseVal === undefined ? el.className : "", 80) || null,
      disabled: !!el.disabled || el.getAttribute("aria-disabled") === "true"}));
  const headings = (all("h1, h2, h3, [role=heading]") || []).filter(visible).slice(0, limits.headings)
    .map(el => clip(el.innerText, 120));
  const inputs = (all("input:not([type=hidden]), textarea, select") || []).filter(visible).slice(0, limits.inputs)
    .map(el => ({tag: el.tagName.toLowerCase(), type: el.type || null, name: clip(el.name, 60) || null,
      id: clip(el.id, 60) || null, aria: clip(el.getAttribute("aria-label"), 80) || null,
      placeholder: clip(el.getAttribute("placeholder"), 80) || null, required: !!el.required}));
  const modals = (all("[role=dialog], [aria-modal=true], .modal, [class*='modal' i], [class*='drawer' i]") || [])
    .filter(visible).slice(0, limits.modals).map(el => ({tag: el.tagName.toLowerCase(),
      role: el.getAttribute("role"), cls: clip(typeof el.className === "string" ? el.className : "", 80) || null,
      fields: el.querySelectorAll("input, textarea, select").length,
      buttons: el.querySelectorAll("button").length}));
  const body = (document.body && document.body.innerText || "").slice(0, 40000);
  const snippetRe = /(?:less than\s+)?\d[\d,]*\+?\s+applicants?|(?:posted\s*(?:on)?\s*:?\s*)?(?:just now|today|yesterday|\d+\+?\s*(?:minute|hour|day|week|month)s?\s+ago)/gi;
  const snippets = [...new Set((body.match(snippetRe) || []).map(s => clip(s, 60)))].slice(0, limits.snippets);
  const matches = {};
  for (const [name, sel] of Object.entries(selectors)) {
    const found = all(sel);
    matches[name] = found === null ? {valid: false, total: 0, visible: 0}
      : {valid: true, total: found.length, visible: found.filter(visible).length};
  }
  return {url: location.href, title: clip(document.title, 120), buttons, headings, inputs, modals, snippets,
    selector_matches: matches};
}
"""


class DiagnosticsRefused(RuntimeError):
    pass


def diagnostics_root() -> Path:
    from backend.app.browser_v2.receipts import receipts_root

    return receipts_root() / "diagnostics"


def adapter_selectors(adapter: Any) -> tuple[dict[str, str], dict[str, str]]:
    """(CSS selectors, button-label regexes) the adapter relies on."""
    config = getattr(adapter, "config", None)
    if config is not None and hasattr(config, "logged_in"):
        css = {"logged_in": config.logged_in, "login_form": config.login_form}
        css |= {f"dialog[{i}]": sel for i, sel in enumerate(config.dialog_selectors)}
        patterns = {"apply_text": config.apply_text, "applied_text": config.applied_text,
                    "external_text": config.external_text}
        return css, patterns
    if getattr(adapter, "platform", None) == "naukri" or type(adapter).__name__.lower().startswith("naukri"):
        return dict(NAUKRI_SELECTORS), dict(NAUKRI_PATTERNS)
    return {}, {}


def strip_url(url: str) -> str:
    """Drop query string and fragment (tokens, session ids, tracking)."""
    try:
        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except ValueError:
        return ""


def match_patterns(buttons: Iterable[Mapping[str, Any]], patterns: Mapping[str, str]) -> dict[str, Any]:
    labels = [str(b.get("text") or "").strip() for b in buttons]
    result = {}
    for name, pattern in patterns.items():
        try:
            hits = [label for label in labels if label and re.search(pattern, label, re.IGNORECASE)]
        except re.error:
            result[name] = {"valid": False, "matched": []}
            continue
        result[name] = {"valid": True, "matched": hits[:5], "count": len(hits)}
    return result


def _scrub(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, str):
        return scrub_pii(value, secrets)
    if isinstance(value, list):
        return [_scrub(v, secrets) for v in value]
    if isinstance(value, dict):
        return {k: _scrub(v, secrets) for k, v in value.items()}
    return value


def _pick(items: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    picked = []
    for item in items:
        if isinstance(item, Mapping):
            picked.append({k: (item[k][:MAX_TEXT] if isinstance(item.get(k), str) else item.get(k))
                           for k in keys if k in item})
    return picked


def _size(payload: Mapping[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))


def cap_payload(payload: dict[str, Any], limit: int = MAX_PROBE_BYTES) -> dict[str, Any]:
    """Halve the longest lists until the JSON fits in `limit` bytes."""
    keys = ("buttons", "inputs", "headings", "modals", "snippets")
    while _size(payload) > limit:
        longest = max(keys, key=lambda k: len(payload.get(k) or []))
        items = payload.get(longest) or []
        if not items:
            payload = {k: v for k, v in payload.items() if k in {"portal", "url", "captured_at", "selector_matches",
                                                                  "pattern_matches", "truncated"}}
            payload["truncated"] = True
            if _size(payload) > limit:
                payload["selector_matches"] = {}
                payload["pattern_matches"] = {}
            break
        payload[longest] = items[: len(items) // 2]
        payload["truncated"] = True
    return payload


def build_probe(raw: Mapping[str, Any], portal: str, patterns: Mapping[str, str],
                secrets: Iterable[str] = (), captured_at: datetime | None = None) -> dict[str, Any]:
    """Pure: raw DOM probe -> scrubbed, capped `dom_probe.json` payload."""
    scrub_terms = tuple(s for s in secrets if isinstance(s, str) and len(s.strip()) >= 3)
    buttons = _pick(raw.get("buttons"), BUTTON_KEYS)
    selector_matches = dict(raw.get("selector_matches") or {})
    payload: dict[str, Any] = {
        "portal": portal,
        "captured_at": (captured_at or datetime.now(UTC)).isoformat(),
        "url": strip_url(str(raw.get("url") or "")),
        "title": str(raw.get("title") or "")[:MAX_TEXT * 2] or None,
        "selector_matches": selector_matches,
        "selectors_missed": sorted(n for n, m in selector_matches.items()
                                   if isinstance(m, Mapping) and not m.get("visible")),
        "pattern_matches": match_patterns(buttons, patterns),
        "headings": [h[:MAX_TEXT * 2] for h in raw.get("headings") or [] if isinstance(h, str)],
        "buttons": buttons,
        "inputs": _pick(raw.get("inputs"), INPUT_KEYS),
        "modals": _pick(raw.get("modals"), MODAL_KEYS),
        "snippets": [s for s in raw.get("snippets") or [] if isinstance(s, str)],
    }
    for key, limit in LIST_LIMITS.items():
        payload[key] = payload[key][:limit]
    return cap_payload(_scrub(payload, scrub_terms))


def profile_secrets(profile: Mapping[str, Any] | None) -> tuple[str, ...]:
    if not profile:
        return ()
    keys = ("full_name", "email", "phone", "phone_number", "address", "current_location", "linkedin_url")
    return tuple(str(profile[k]) for k in keys if isinstance(profile.get(k), str) and profile.get(k))


def bundle_dir(portal: str, root: Path | None = None, now: datetime | None = None) -> Path:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%S%fZ")
    safe = re.sub(r"[^a-z0-9_]+", "_", portal.lower())[:40] or "portal"
    return (root or diagnostics_root()) / f"{safe}-{stamp}"


async def capture_bundle(page: Any, portal: str, adapter: Any, *, dry_run: bool,
                         profile: Mapping[str, Any] | None = None, root: Path | None = None) -> dict[str, Any]:
    """Screenshot + scrubbed DOM probe of the current page. Refuses anything but a dry run."""
    if not dry_run:
        raise DiagnosticsRefused("debug_selectors_requires_dry_run")
    css, patterns = adapter_selectors(adapter)
    raw = await page.evaluate(DOM_PROBE_JS, {"selectors": css, "limits": LIST_LIMITS})
    payload = build_probe(raw or {}, portal, patterns, profile_secrets(profile))
    folder = bundle_dir(portal, root)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    probe_path = folder / "dom_probe.json"
    probe_path.write_text(json.dumps(payload, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    os.chmod(probe_path, 0o600)
    screenshot: str | None = str(folder / "page.png")
    try:
        await page.screenshot(path=screenshot, full_page=False)
        os.chmod(folder / "page.png", 0o600)
    except Exception:  # noqa: BLE001 - the probe is still useful without the image
        screenshot = None
    return {"bundle": str(folder), "dom_probe": str(probe_path), "screenshot": screenshot,
            "bytes": probe_path.stat().st_size, "selectors_missed": payload.get("selectors_missed", []),
            "pattern_matches": {k: v.get("count", 0) for k, v in (payload.get("pattern_matches") or {}).items()}}
