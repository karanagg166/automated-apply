"""Phase 8: controlled 1-job live canary (`cli apply-one`).

    backend/venv/bin/python -m backend.app.browser_v2.cli apply-one --portal <portal> --url <job_url>
        -> dry-run (default): inspect + fill, stop before the Apply/Submit click
    ... apply-one --portal <portal> --url <job_url> --confirm-live
        -> ONE real application after a typed confirmation (`APPLY <portal>`)

Guardrails, all checked BEFORE the browser opens:
- live requires `--confirm-live` AND the typed confirmation (or `--yes` from a TTY-less script
  only together with `--confirm-live`); never more than one job per run;
- live requires Postgres (no in-memory store: the never-replay state must persist);
- the URL must map to a stable job id for that portal; a job already APPLIED or
  SUBMISSION_UNKNOWN (never-replay), APPLYING or WAITING_FOR_USER is refused;
- the portal session must be OK and the dashboard quota open (`process_job` re-checks it).

Evidence: pre/post screenshots + a JSON outcome under
`<runtime>/receipts/canary/` (0700), the adapter's own receipt screenshot when the portal
confirms, and one Telegram summary when Telegram is configured.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.browser_v2.state import ApplicationState as S

REFUSE_STATES = frozenset({S.APPLIED.value, S.SUBMISSION_UNKNOWN.value, S.APPLYING.value,
                           S.WAITING_FOR_USER.value})
CONFIRM_WORD = "APPLY"


class CanaryRefused(RuntimeError):
    pass


def canary_dir() -> Path:
    from backend.app.browser_v2 import profile as brave_profile

    folder = brave_profile.runtime_dir() / "receipts" / "canary"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    return folder


async def _screenshot(service: Any, path: Path, url: str | None = None) -> str | None:
    if url is None and not getattr(service.manager, "running", False):
        return None
    try:
        async with service.manager.job() as page:
            if url is not None:
                await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                await page.wait_for_timeout(1500)
            await page.screenshot(path=str(path), full_page=False)
        return str(path)
    except Exception:  # noqa: BLE001 - evidence is best effort, never changes the outcome
        return None


def preflight(portal: str, url: str, *, live: bool, confirm_live: bool, backend: str) -> str:
    """Pure guardrails (no I/O). Returns the external job id or raises CanaryRefused."""
    from backend.app.browser_v2.portals import PORTALS
    from backend.app.browser_v2.service import job_id_from_url

    if portal not in PORTALS:
        raise CanaryRefused(f"unknown_portal:{portal}")
    if live and not confirm_live:
        raise CanaryRefused("live_requires_--confirm-live")
    if live and backend != "postgres":
        raise CanaryRefused("live_requires_postgres_store (never-replay state must persist)")
    job_id = job_id_from_url(portal, url)
    if not job_id:
        raise CanaryRefused("unrecognized_job_url_for_portal")
    return job_id


async def apply_one(portal: str, url: str, *, confirm_live: bool, assume_yes: bool = False,
                    service_factory: Callable[..., Awaitable[tuple[Any, str]]] | None = None,
                    notify: Callable[[str], Awaitable[None]] | None = None,
                    input_fn: Callable[[str], str] = input, is_tty: bool | None = None,
                    evidence_dir: Path | None = None) -> dict[str, Any]:
    from backend.app.browser_v2.service import build_service

    live = confirm_live
    factory = service_factory or build_service
    service, backend = await factory(require_db=live)
    store_name = backend.split(" ")[0]
    report: dict[str, Any] = {"portal": portal, "url": url, "mode": "live" if live else "dry_run",
                              "store": store_name}
    try:
        job_id = preflight(portal, url, live=live, confirm_live=confirm_live, backend=store_name)
        report["external_job_id"] = job_id
        existing = await service.store.get(portal, job_id)
        if existing is not None and existing.state.value in REFUSE_STATES:
            raise CanaryRefused(f"never_replay_or_in_flight:{existing.state.value}")
        rules = await service.store.get_rules(portal)
        if live:
            blocked = await service.quota_block(portal, rules)
            if blocked:
                raise CanaryRefused(f"quota_closed:{blocked}")
        await service.configure_adapters()
        session = await service.check_portal_session(portal)
        report["session"] = session.get("status")
        if session.get("status") != "OK":
            raise CanaryRefused(f"session_not_ok:{session.get('reason') or session.get('status')}")
        if live:
            tty = sys.stdin.isatty() if is_tty is None else is_tty
            if not assume_yes:
                if not tty:
                    raise CanaryRefused("live_needs_typed_confirmation (run in a terminal or add --yes)")
                typed = input_fn(f"ONE live application on {portal} ({url}). Type '{CONFIRM_WORD} {portal}': ")
                if typed.strip() != f"{CONFIRM_WORD} {portal}":
                    raise CanaryRefused("confirmation_mismatch")
        folder = evidence_dir or canary_dir()
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        base = folder / f"{portal}-{job_id}-{stamp}"
        report["pre_screenshot"] = await _screenshot(service, Path(f"{base}-pre.png"), url)
        outcome = await service.apply_to_job(portal, url, dry_run=not live)
        report["adapter_screenshot"] = outcome.get("screenshot")
        report["post_screenshot"] = await _screenshot(service, Path(f"{base}-post.png"))
        report["outcome"] = {k: outcome.get(k) for k in (
            "state", "reason", "title", "company", "filter", "filter_reasons", "clicked_apply", "receipt",
            "hitl_request_id", "refused", "planned_action", "quota_blocked")}
        record = await service.store.get(portal, job_id)
        report["final_state"] = record.state.value if record is not None else None
        report["verified"] = bool(live and report["final_state"] == S.APPLIED.value
                                  and (outcome.get("receipt") or {}).get("source"))
        evidence = Path(f"{base}.json")
        evidence.write_text(json.dumps(report, indent=2, default=str))
        evidence.chmod(0o600)
        report["evidence"] = str(evidence)
        report["ok"] = True
    except CanaryRefused as exc:
        report |= {"ok": False, "refused": str(exc)}
    finally:
        await service.manager.close()
        await service.store.close()
    if notify is not None:
        try:
            await notify(summary(report))
        except Exception:  # noqa: BLE001 - notification is best effort
            report["telegram"] = "notify_failed"
    return report


def summary(report: dict[str, Any]) -> str:
    outcome = report.get("outcome") or {}
    head = "🧪 Canary " + ("LIVE" if report.get("mode") == "live" else "dry-run")
    if not report.get("ok"):
        return f"{head} refused on {report.get('portal')}: {report.get('refused')}"
    who = " @ ".join(p for p in (outcome.get("title"), outcome.get("company")) if p) or report.get("url")
    verified = " ✅ verified receipt" if report.get("verified") else ""
    return (f"{head} {report.get('portal')}: {who}\n"
            f"state={report.get('final_state') or outcome.get('state')} reason={outcome.get('reason')}{verified}")
