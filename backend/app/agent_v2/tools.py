"""Typed, guardrailed tools for the control agent. Every write goes through the same
validation as the dashboard API (PortalRulesPatch + cross-field checks, JobSearchPreferences)
and the single v2 store connection; there is no send, delete or replay tool at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError

from backend.app.browser_v2.portals import PORTALS, portal_label
from backend.app.browser_v2.rules import normalize_company
from backend.app.browser_v2.schemas import PortalRulesPatch
from backend.app.browser_v2.state import ApplicationState
from backend.app.browser_v2.store import (
    ApplicationQuery,
    ProfileMissing,
    RevisionConflict,
    RulesNotFound,
    WorkerState,
)

PREFERENCE_LISTS = ("company_blacklist", "keywords_required", "keywords_excluded", "tech_stack", "target_roles")
PREFERENCE_SCALARS = ("expected_ctc", "current_ctc", "min_ctc", "notice_period_days", "remote_policy",
                      "total_experience_years", "current_location", "willing_to_relocate", "min_match_score",
                      "skill_match_mode")
# Changes that need an explicit "confirm" in the same message.
CONFIRM_DAILY_ABOVE = 100


class GuardrailViolation(ValueError):
    pass


class NeedsConfirmation(ValueError):
    pass


@dataclass
class ToolResult:
    ok: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)


def resolve_platforms(platforms: list[str] | None) -> list[str]:
    names = list(dict.fromkeys(platforms or []))
    if not names:
        raise GuardrailViolation("Which portal? e.g. 'enable Instahyre' or 'set Naukri daily limit to 60'.")
    if "*" in names:
        return sorted(PORTALS)
    unknown = [n for n in names if n not in PORTALS]
    if unknown:
        raise GuardrailViolation(f"Unknown portal: {', '.join(unknown)}")
    return names


def validate_rule_changes(platforms: list[str], changes: dict[str, Any], rules_by_platform: dict[str, Any], *,
                          confirmed: bool) -> dict[str, dict[str, Any]]:
    """Same checks as PATCH /api/v1/v2/portal-rules (Pydantic ranges + cross-field rules)."""
    if not changes:
        raise GuardrailViolation("No rule change found.")
    plan: dict[str, dict[str, Any]] = {}
    for platform in platforms:
        current = rules_by_platform.get(platform)
        if current is None:
            raise GuardrailViolation(f"Unknown portal: {platform}")
        try:
            patch = PortalRulesPatch.model_validate({"revision": current.revision, **changes})
        except ValidationError as exc:
            first = exc.errors()[0]
            raise GuardrailViolation(f"Rejected: {'.'.join(str(p) for p in first['loc'])} {first['msg']}") from None
        values = patch.changes()
        merged = {name: values.get(name, getattr(current, name)) for name in
                  ("min_delay_sec", "max_delay_sec", "max_applies_per_hour", "max_applies_per_day")}
        if merged["max_delay_sec"] < merged["min_delay_sec"]:
            raise GuardrailViolation("Rejected: max delay must be >= min delay.")
        if merged["max_applies_per_hour"] > merged["max_applies_per_day"]:
            raise GuardrailViolation("Rejected: hourly cap cannot exceed the daily cap.")
        if not confirmed and (values.get("auto_apply_enabled") is True
                              or (values.get("max_applies_per_day") or 0) > CONFIRM_DAILY_ABOVE
                              or len(platforms) > 3 and "paused_until" not in values):
            raise NeedsConfirmation("This is a high-impact change. Resend the same message with the word "
                                    "'confirm' to apply it.")
        plan[platform] = values
    return plan


class AgentTools:
    def __init__(self, store: Any, *, ai: Any = None, mail_events: Any = None,
                 clock: Any = None) -> None:
        self.store = store
        self.ai = ai
        self.mail_events = mail_events
        self.clock = clock or (lambda: datetime.now(UTC))

    # --- update_portal_rule -------------------------------------------------------------
    async def update_portal_rule(self, platforms: list[str], changes: dict[str, Any], *,
                                 confirmed: bool = False) -> ToolResult:
        names = resolve_platforms(platforms)
        rules = {r.platform: r for r in await self.store.list_rules()}
        plan = validate_rule_changes(names, changes, rules, confirmed=confirmed)
        done = []
        for platform, values in plan.items():
            for _ in range(2):
                try:
                    updated = await self.store.update_rules(platform, values, rules[platform].revision)
                    done.append(platform)
                    rules[platform] = updated
                    break
                except RevisionConflict:
                    rules[platform] = await self.store.get_rules(platform)
                except RulesNotFound:
                    raise GuardrailViolation(f"Unknown portal: {platform}") from None
        summary = ", ".join(f"{k}={_show(v)}" for k, v in next(iter(plan.values())).items())
        labels = ", ".join(portal_label(p) for p in done)
        return ToolResult(bool(done), f"Updated {labels}: {summary}. Applies on the worker's next cycle "
                                      "(the in-flight job is never interrupted).", {"platforms": done})

    # --- update_preferences --------------------------------------------------------------
    async def update_preferences(self, op: str, key: str | None, *, value: Any = None,
                                 values: list[str] | None = None) -> ToolResult:
        if key in PREFERENCE_LISTS:
            profile, _ = await self.store.load_profile()
            current = [str(v) for v in (profile.get("preferences") or {}).get(key) or []]
            items = [v.strip() for v in values or [] if isinstance(v, str) and v.strip()]
            if not items:
                raise GuardrailViolation("Nothing to add or remove.")
            if op == "remove":
                drop = {normalize_company(v) if key == "company_blacklist" else v.lower() for v in items}
                updated = [v for v in current if (normalize_company(v) if key == "company_blacklist"
                                                  else v.lower()) not in drop]
            else:
                updated = current + [v for v in items if v.lower() not in {c.lower() for c in current}]
            changes: dict[str, Any] = {key: updated}
        elif key in PREFERENCE_SCALARS and op == "set":
            changes = {key: value}
        else:
            raise GuardrailViolation(f"Unsupported preference: {key}")
        try:
            prefs = await self.store.update_preferences(changes)
        except ProfileMissing:
            raise GuardrailViolation("Create the candidate profile on the dashboard first.") from None
        except ValueError as exc:
            raise GuardrailViolation(f"Rejected: {exc}") from None
        shown = prefs.get(key)
        return ToolResult(True, f"Saved {key.replace('_', ' ')}: {_show(shown)}. The worker re-reads preferences "
                                "every cycle.", {"key": key, "value": shown})

    # --- teach_semantic_cache --------------------------------------------------------------
    async def teach_semantic_cache(self, question: str | None, answer: str | None) -> ToolResult:
        if not question or not answer:
            raise GuardrailViolation("Say it as 'remember my <thing> is <answer>'.")
        if self.ai is None:
            raise GuardrailViolation("The semantic cache is unavailable (AI_V2_DISABLED).")
        result = await self.ai.cache.store_verified_user_answer(question, answer)
        return ToolResult(True, f"Remembered: “{question}” → “{answer}” (verified owner answer; used before any "
                                "LLM).", {"cached": getattr(result, "stored", True)})

    # --- control_worker ----------------------------------------------------------------------
    async def control_worker(self, action: str) -> ToolResult:
        if action == "pause":
            control = await self.store.set_worker_control(WorkerState.PAUSED)
            return ToolResult(True, f"Worker → {control.desired_state.value} (takes effect between jobs; the current "
                                    "application finishes first).")
        if action == "resume":
            control = await self.store.set_worker_control(WorkerState.RUNNING)
            return ToolResult(True, f"Worker → {control.desired_state.value} "
                                    f"({'DRY RUN' if control.dry_run else 'LIVE'}).")
        if action == "run_once":
            await self.store.set_worker_control(run_once=True)
            return ToolResult(True, "One cycle requested; it starts at the worker's next idle check.")
        control = await self.store.get_worker_control()
        return ToolResult(True, f"Worker desired={control.desired_state.value}, observed={control.observed_state}, "
                                f"{'DRY RUN' if control.dry_run else 'LIVE'}, current portal="
                                f"{control.current_platform or '-'}, last error={control.last_error or 'none'}.")

    # --- query_application_status --------------------------------------------------------------
    async def query_application_status(self, kind: str, *, company: str | None = None, platform: str | None = None,
                                       limit: int = 5) -> ToolResult:
        from backend.app.browser_v2.service import day_start, quota_counts

        limit = max(1, min(int(limit or 5), 15))
        now = self.clock()
        if kind == "counts":
            lines = []
            for rules in await self.store.list_rules():
                if platform and rules.platform != platform:
                    continue
                counts = await quota_counts(self.store, rules, now)
                if counts["applied_today"] or rules.enabled:
                    lines.append(f"{portal_label(rules.platform)}: {counts['applied_today']}/"
                                 f"{rules.max_applies_per_day} today")
            start = day_start(await self.store.get_rules(platform or "naukri"), now)
            drafts = await self.store.count_email_drafts("CREATED", since=start)
            waiting = await self.store.count_state(ApplicationState.WAITING_FOR_USER)
            return ToolResult(True, "; ".join(lines or ["No applications today"])
                              + f". Drafts today: {drafts}. Waiting for you: {waiting}.")
        if kind == "drafts":
            drafts, total = await self.store.list_email_drafts(platform=platform, limit=limit)
            if not drafts:
                return ToolResult(True, "No Gmail drafts yet.")
            rows = [f"• {d.company_name or '?'} — {d.role_title or '?'} [{d.status}]" for d in drafts]
            return ToolResult(True, f"Last {len(rows)} of {total} drafts:\n" + "\n".join(rows))
        if kind == "replies":
            if self.mail_events is None:
                return ToolResult(True, "Mail watcher is not configured.")
            events = await self.mail_events.recent(("RECRUITER_REPLY", "INTERVIEW"), limit=limit)
            if not events:
                return ToolResult(True, "No recruiter replies or interview alerts detected yet.")
            return ToolResult(True, "\n".join(f"• {e.kind.title()}: {e.company_name or e.sender or '?'} — "
                                              f"{e.subject or ''}" for e in events))
        if kind == "digest":
            from backend.app.browser_v2.digest import build_digest

            return ToolResult(True, await build_digest(self.store, now, ai=self.ai, mail_events=self.mail_events))
        if kind == "failed":
            failed: list[Any] = []
            for state in (ApplicationState.FAILED, ApplicationState.SUBMISSION_UNKNOWN):
                found, _ = await self.store.list_applications(ApplicationQuery(platform=platform, state=state.value,
                                                                               limit=limit))
                failed.extend(found)
            failed.sort(key=lambda r: r.updated_at or now, reverse=True)
            if not failed:
                return ToolResult(True, "No failed or ambiguous applications. 🎉")
            return ToolResult(True, "\n".join(
                f"• {r.role_title or '?'} @ {r.company_name or '?'} ({portal_label(r.platform)}): {r.state.value} — "
                f"{r.reason or 'no reason recorded'}" for r in failed[:limit]))
        if kind == "hitl":
            rows, total = await self.store.list_hitl("OPEN", limit=limit)
            if not rows:
                return ToolResult(True, "Nothing is waiting for you.")
            return ToolResult(True, f"{total} open:\n" + "\n".join(f"• [{r.ref}] {r.kind}: {r.prompt_text[:80]}"
                                                                    for r in rows))
        records, _ = await self.store.list_applications(ApplicationQuery(platform=platform, limit=500))
        if kind == "why":
            wanted = normalize_company(company)
            if not wanted:
                raise GuardrailViolation("Which company?")
            matches = [r for r in records if wanted in normalize_company(r.company_name) or
                       normalize_company(r.company_name) == wanted][:limit]
            if not matches:
                return ToolResult(True, f"I have no record of {company} in recent applications.")
            return ToolResult(True, "\n".join(f"• {r.role_title or '?'} @ {r.company_name} ({portal_label(r.platform)})"
                                              f": {r.state.value} — {r.reason or 'no reason recorded'}"
                                              for r in matches))
        rows = records[:limit]
        if not rows:
            return ToolResult(True, "No applications yet.")
        return ToolResult(True, "\n".join(f"• {r.role_title or '?'} @ {r.company_name or '?'} "
                                          f"({portal_label(r.platform)}): {r.state.value}" for r in rows))


def _show(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) or "(empty)"
    if value is None:
        return "cleared"
    if isinstance(value, timedelta):
        return str(value)
    return str(value)
