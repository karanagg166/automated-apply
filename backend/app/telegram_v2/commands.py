"""TelegramBot slash commands (incl. /forget for the agent memory), swipe-replies, plain-text answers and /status."""

from __future__ import annotations

from backend.app.browser_v2.store import HitlRecord, WorkerState, agent_chat_key
from backend.app.telegram_v2.base import MAX_PENDING_LISTED
from backend.app.telegram_v2.commands_ops import OpsCommandsMixin
from backend.app.telegram_v2.formatting import (
    HELP_TEXT,
    render_disambiguation,
    render_pending,
    render_status,
)
from backend.app.telegram_v2.outbound import _html, _outcome


class CommandsMixin(OpsCommandsMixin):
    # --- commands -------------------------------------------------------------------
    async def handle_command(self, text: str) -> str | tuple[str, dict]:
        head, _, argument = text.partition(" ")
        command, _, _mention = head.partition("@")
        command, argument = command.lower(), argument.strip()
        if command in {"/help", "/start"}:
            return HELP_TEXT
        ops = await self.handle_ops_command(command, argument)
        if ops is not None:
            return ops
        if command == "/status":
            return await self.status_text()
        if command == "/forget":
            try:
                removed = await self.store.clear_turns(agent_chat_key("telegram", self.chat_id))
            except Exception:  # noqa: BLE001 - followup 005 not applied yet: nothing is remembered
                removed = 0
            return f"🧹 Forgot {removed} remembered chat message(s). Settings and audit history are unchanged."
        if command == "/pending":
            rows, total = await self.store.list_hitl("OPEN", limit=MAX_PENDING_LISTED)
            return render_pending(rows, total)
        if command == "/pause":
            control = await self.store.set_worker_control(WorkerState.PAUSED)
            return f"⏸ Worker desired state: <b>{control.desired_state.value}</b> (takes effect between jobs)."
        if command in {"/start_worker", "/unpause"}:
            control = await self.store.set_worker_control(WorkerState.RUNNING)
            mode = "DRY RUN" if control.dry_run else "LIVE"
            return f"▶️ Worker desired state: <b>{control.desired_state.value}</b> ({mode})."
        if command == "/resume":
            if not argument:
                return "Usage: <code>/resume &lt;portal&gt;</code>"
            await self.unpause_portal(argument.split()[0].lower())
            outcome = await self.resolver.resume_portal(argument.split()[0], via="telegram")
            await self._close_messages(outcome)
            return ("🔓 " if outcome.ok else "") + _html(outcome.message)
        if command in {"/answer", "/once", "/skip", "/retry"}:
            ref, _, answer = argument.partition(" ")
            if not ref:
                return f"Usage: <code>{command} &lt;ref&gt;{' &lt;text&gt;' if command in {'/answer', '/once'} else ''}</code>"
            hitl, problem = await self.resolver.by_ref(ref)
            if problem is not None or hitl is None:
                return _html(problem.message if problem else "Not found.")
            if command == "/skip":
                result = await self.resolver.skip(hitl.id, via="telegram")
            elif command == "/retry":
                result = await self.resolver.retry(hitl.id, via="telegram")
            else:
                if not answer.strip():
                    return f"Usage: <code>{command} {hitl.ref} &lt;text&gt;</code>"
                result = await self.resolver.answer(hitl.id, answer, cache_answer=command == "/answer",
                                                    via="telegram")
            await self._after_resolution(result)
            return _outcome(result)
        return "Unknown command. /help"

    async def handle_reply(self, hitl: HitlRecord, text: str) -> str:
        if hitl.status != "OPEN":
            return f"Request <code>{hitl.ref}</code> is already {hitl.status.lower()} — nothing changed."
        if hitl.kind == "AUTH":
            outcome = await self.resolver.resume_portal(hitl.platform, via="telegram")
            await self._close_messages(outcome)
            return "🔓 " + _html(outcome.message)
        if hitl.kind == "ERROR":
            lowered = text.lower()
            if lowered in {"retry", "skip"}:
                result = await (self.resolver.retry if lowered == "retry" else self.resolver.skip)(
                    hitl.id, via="telegram")
                await self._after_resolution(result)
                return _outcome(result)
            return f"Reply <b>retry</b> or <b>skip</b>, or use <code>/retry {hitl.ref}</code>."
        if not text:
            return "Send the answer as text."
        result = await self.resolver.answer(hitl.id, text, cache_answer=True, via="telegram")
        await self._after_resolution(result)
        return _outcome(result)

    async def handle_plain(self, text: str) -> str:
        if not text:
            return "Send the answer as text. /help"
        candidates = await self.answerable()
        if not candidates:
            return "Nothing is waiting for an answer. /pending · /help"
        if len(candidates) > 1:
            return render_disambiguation(candidates)
        result = await self.resolver.answer(candidates[0].id, text, cache_answer=True, via="telegram")
        await self._after_resolution(result)
        return _outcome(result)

    async def status_text(self) -> str:
        from backend.app.browser_v2.service import quota_counts

        now = self.clock()
        portals = []
        for rules in await self.store.list_rules():
            counts = await quota_counts(self.store, rules, now)
            portals.append({"platform": rules.platform, "enabled": rules.enabled,
                            "auto_apply_enabled": rules.auto_apply_enabled, "auth_status": rules.auth_status,
                            "applied_today": counts["applied_today"],
                            "max_applies_per_day": rules.max_applies_per_day})
        providers = None
        if self.ai is not None:
            providers = [p["provider"] for p in await self.ai.router.status() if p["status"] != "unconfigured"]
        telegram = (await self.store.get_telegram_state()).polling_state
        text = render_status(worker=await self.store.get_worker_control(), portals=portals,
                             open_hitl=await self.store.count_open_hitl(), providers=providers,
                             telegram_state=telegram, now=now)
        latency = await self.latency_line(now)
        return text + ("\n" + latency if latency else "")
