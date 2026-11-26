"""WRITE tools for portal rules (incl. ATS board slugs), worker control and portal profile sync.

Risk rules (the runner asks the owner to confirm first): more than 3 portals, enabling
auto-apply, a daily cap above 100, switching the worker from dry run to live, and a live
portal profile sync.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from backend.app.agent_v2.tools.args import (
    BOARD_PORTALS,
    ControlWorkerArgs,
    ProfileSyncArgs,
    UpdateRuleArgs,
)
from backend.app.agent_v2.tools.base import (
    GuardrailViolation,
    ToolResult,
    _show,
    resolve_platforms,
)
from backend.app.agent_v2.tools.guardrails import forbidden_patch_keys, rule_patch_risk
from backend.app.agent_v2.tools.spec import ToolContext, ToolSpec, h, refused
from backend.app.browser_v2.portals import PORTALS, portal_label

SYNC_TRIGGERS = {"telegram": "telegram", "api": "dashboard", "mcp": "mcp", "cli": "cli", "worker": "schedule"}


# --- update_portal_rule ---------------------------------------------------------------------------
async def rule_guard(ctx: ToolContext, args: UpdateRuleArgs) -> str | None:
    bad = forbidden_patch_keys(args.patch)
    if bad:
        return f"Application state, receipts, auth and circuit fields can't be changed from chat ({', '.join(bad)})."
    try:
        names = resolve_platforms(args.portals)
    except GuardrailViolation as exc:
        return str(exc)
    if (args.boards_add or args.boards_remove) and set(names) - set(BOARD_PORTALS):
        return f"Board slugs exist only for {', '.join(BOARD_PORTALS)}."
    if not args.patch and not args.boards_add and not args.boards_remove:
        return "No rule change found."
    return None


async def rule_risk(ctx: ToolContext, args: UpdateRuleArgs) -> str | None:
    try:
        names = resolve_platforms(args.portals)
    except GuardrailViolation:
        return None
    return rule_patch_risk(names, args.patch)


async def rule_snapshot(ctx: ToolContext, args: UpdateRuleArgs) -> dict[str, Any] | None:
    try:
        names = set(resolve_platforms(args.portals))
    except GuardrailViolation:
        return None
    rules = {r.platform: r for r in await ctx.store.list_rules() if r.platform in names}
    snap: dict[str, Any] = {p: {k: getattr(r, k, None) for k in args.patch} for p, r in rules.items()}
    if args.boards_add or args.boards_remove:
        profile, _ = await ctx.store.load_profile()
        prefs = (profile or {}).get("preferences") or {}
        snap["boards"] = {p: sorted(prefs.get(f"{p}_boards") or {}) for p in names if p in BOARD_PORTALS}
    return snap


async def _update_boards(ctx: ToolContext, names: list[str], args: UpdateRuleArgs) -> list[str]:
    profile, _ = await ctx.store.load_profile()
    if not profile:
        raise GuardrailViolation("Create the candidate profile on the dashboard first.")
    prefs = profile.get("preferences") or {}
    changes: dict[str, Any] = {}
    lines = []
    for portal in names:
        key = f"{portal}_boards"
        current = dict(prefs.get(key) or {})
        updated = {k: v for k, v in current.items() if k.lower() not in set(args.boards_remove)}
        updated |= {slug: None for slug in args.boards_add if slug not in {k.lower() for k in updated}}
        changes[key] = updated
        lines.append(f"• {h(portal_label(portal), 40)} boards: {h(', '.join(sorted(current)) or '(none)', 200)}"
                     f" → {h(', '.join(sorted(updated)) or '(none)', 200)}")
    try:
        await ctx.store.update_preferences(changes)
    except ValueError as exc:
        raise GuardrailViolation(f"Rejected by profile validation: {exc}") from None
    return lines


async def update_portal_rule(ctx: ToolContext, args: UpdateRuleArgs, confirmed: bool) -> ToolResult:
    names = resolve_platforms(args.portals)
    lines: list[str] = []
    done: list[str] = []
    if args.patch:
        before = {r.platform: r for r in await ctx.store.list_rules()}
        result = await ctx.legacy.update_portal_rule(names, args.patch, confirmed=True)
        done = list(result.data.get("platforms") or [])
        after = {r.platform: r for r in await ctx.store.list_rules()}
        for portal in done:
            diff = ", ".join(f"{k}: {_show(getattr(before[portal], k, None))} → {_show(getattr(after[portal], k, None))}"
                             for k in args.patch)
            lines.append(f"• <b>{h(portal_label(portal), 40)}</b>: {h(diff, 400)}")
    if args.boards_add or args.boards_remove:
        lines += await _update_boards(ctx, names, args)
    if not lines:
        return refused("Nothing was changed (the portal rows were busy; try again).")
    return ToolResult(True, f"Updated {', '.join(done or names)}.", {"platforms": done or names},
                      user_html=("⚙️ <b>Portal rules updated</b> (applies on the worker's next cycle; the in-flight "
                                 "job is never interrupted)\n" + "\n".join(lines)),
                      llm_summary=f"ok: updated {', '.join(done or names)}")


# --- control_worker ---------------------------------------------------------------------------------
async def worker_risk(ctx: ToolContext, args: ControlWorkerArgs) -> str | None:
    if args.dry_run is False and (await ctx.store.get_worker_control()).dry_run:
        return "switches the worker from DRY RUN to LIVE submissions"
    return None


async def worker_snapshot(ctx: ToolContext, args: ControlWorkerArgs) -> dict[str, Any] | None:
    control = await ctx.store.get_worker_control()
    snap = {"desired_state": control.desired_state.value, "dry_run": control.dry_run,
            "run_once_requested_at": control.run_once_requested_at}
    if args.portal:
        snap["paused_until"] = (await ctx.store.get_rules(args.portal)).paused_until
    return snap


async def control_worker(ctx: ToolContext, args: ControlWorkerArgs, confirmed: bool) -> ToolResult:
    if args.portal and args.portal not in PORTALS:
        return refused(f"Unknown portal: {args.portal}")
    lines: list[str] = []
    if args.dry_run is not None:
        control = await ctx.store.set_worker_control(dry_run=args.dry_run)
        lines.append(f"• Mode → <b>{'DRY RUN' if control.dry_run else 'LIVE'}</b>")
    if args.portal and args.action in ("pause", "resume"):
        until = ctx.clock() + timedelta(hours=24) if args.action == "pause" else None
        await ctx.legacy.update_portal_rule([args.portal], {"paused_until": until}, confirmed=True)
        lines.append(f"• {h(portal_label(args.portal), 40)} paused until → {h(_show(until), 40)}")
    elif args.action == "digest":
        from backend.app.browser_v2.digest import build_digest

        text = await build_digest(ctx.store, ctx.clock(), ai=ctx.ai, mail_events=ctx.mail_events)
        return ToolResult(True, "digest", {}, user_html=h(text, 3500), llm_summary="ok: digest shown to the owner")
    elif args.action == "sweep":
        await ctx.store.set_worker_control(run_once=True)
        if ctx.event_bus is not None:
            try:
                await ctx.event_bus.publish("agent.sweep_requested", {"portal": args.portal, "source": ctx.source})
            except Exception:  # noqa: BLE001, S110 - the run-once request already carries it
                pass
        woke = await ctx.notify_wake()
        lines.append(f"• Fresh sweep requested{(' for ' + h(portal_label(args.portal), 40)) if args.portal else ''}"
                     f" ({'worker woken' if woke else 'starts at the next idle check'})")
    else:
        result = await ctx.legacy.control_worker(args.action)
        if args.action == "run_once":
            await ctx.notify_wake()
        if args.action == "status":
            return ToolResult(True, result.message, {}, llm_summary=result.message)
        lines.append(f"• {h(result.message, 300)}")
    return ToolResult(True, "worker updated", {"action": args.action},
                      user_html="🛠 <b>Worker control</b>\n" + "\n".join(lines),
                      llm_summary="ok: " + "; ".join(line.lstrip("• ") for line in lines)[:500])


# --- trigger_portal_profile_sync ------------------------------------------------------------------------
async def sync_risk(ctx: ToolContext, args: ProfileSyncArgs) -> str | None:
    return None if args.dry_run else "writes your profile to the live portals"


async def trigger_portal_profile_sync(ctx: ToolContext, args: ProfileSyncArgs, confirmed: bool) -> ToolResult:
    unknown = [p for p in args.portals if p not in PORTALS]
    if unknown:
        return refused(f"Unknown portal: {', '.join(unknown)}")
    if ctx.profile_sync is None:
        return refused("Portal profile sync is not available yet (it arrives with Stage 9D).")
    report = await ctx.profile_sync.sync(list(args.portals), dry_run=args.dry_run,
                                         trigger=SYNC_TRIGGERS.get(ctx.source, "telegram"))
    mode = "dry run" if args.dry_run else "LIVE"
    rows = [f"• {h(portal_label(p), 40)}: {h((report.get(p) or {}).get('status', 'requested'), 40)}"
            for p in args.portals] if isinstance(report, dict) else []
    return ToolResult(True, f"Profile sync ({mode}) requested.", {"report": report},
                      user_html=f"🔄 <b>Portal profile sync ({mode})</b>\n" + "\n".join(rows),
                      llm_summary=f"ok: profile sync {mode} for {', '.join(args.portals)}")


OPS_SPECS = (
    ToolSpec("update_portal_rule", "Change portal rules for one or more portals (patch keys: enabled, "
             "auto_apply_enabled, max_applies_per_day, max_applies_per_hour, max_job_age_days, max_applicants, "
             "min_delay_sec, max_delay_sec, paused_until (ISO time or null), allow_unknown_posting_age, "
             "quota_fallback_daily_cap, quota_drafts_per_cycle) and/or add/remove greenhouse/lever/ashby/"
             "smartrecruiters board slugs.", UpdateRuleArgs, "write", update_portal_rule,
             assess=rule_risk, guard=rule_guard, snapshot=rule_snapshot),
    ToolSpec("control_worker", "Worker control (portal: pause/resume only that portal; dry_run true/false "
             "switches the mode).", ControlWorkerArgs,
             "write", control_worker, assess=worker_risk, snapshot=worker_snapshot),
    ToolSpec("trigger_portal_profile_sync", "Push the profile to portal profiles (dry_run only reports diffs).", ProfileSyncArgs, "write", trigger_portal_profile_sync,
             assess=sync_risk),
)
