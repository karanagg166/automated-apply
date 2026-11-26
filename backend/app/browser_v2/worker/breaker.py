"""Worker mixin: Phase 9B persisted per-portal circuit breaker (replaces the in-memory back-off).

Every job/portal outcome is classified with `outcomes.classify`. CIRCUIT_TRIP_AFTER (3) consecutive
breaker outcomes (INFRA_ERROR / DOM_CHANGED / CAPTCHA_WALL) or portal-level exceptions open the
portal's breaker for 15, 30, then 60 min (cap). After expiry the breaker is half-open: exactly one
trial job runs; a breaker outcome re-opens it one level up, anything else resets failures and level
to 0. AUTH_REQUIRED keeps its own HITL flow and never counts. State is persisted with
`store.record_circuit`; `portal.circuit_open` is published once per opening. Other portals are
unaffected.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from backend.app.browser_v2.outcomes import OutcomeCode, classify, trips_breaker
from backend.app.browser_v2.store.phase9_records import CIRCUIT_MAX_LEVEL
from backend.app.browser_v2.worker.context import Circuit
from backend.app.browser_v2.worker.loop import WorkerLoop
from backend.app.browser_v2.worker.reports import (
    CIRCUIT_OPEN_SEC,
    CIRCUIT_TRIP_AFTER,
    logger,
)


def circuit_open_seconds(level: int) -> int:
    """Level 1 = 15 min, 2 = 30 min, 3+ = 60 min."""
    return CIRCUIT_OPEN_SEC[max(1, min(level, len(CIRCUIT_OPEN_SEC))) - 1]


def outcome_code(outcome: dict[str, Any]) -> OutcomeCode | None:
    """Classify a `process_job` result; None when nothing was attempted (replay refused / quota gate)."""
    if outcome.get("refused") or outcome.get("quota_blocked"):
        return None
    return classify(outcome.get("state"), str(outcome.get("reason") or ""))


class CircuitMixin(WorkerLoop):
    def circuit_blocked_until(self, platform: str, now: datetime) -> datetime | None:
        circuit = self.circuits.get(platform)
        if circuit is None or circuit.open_until is None or circuit.open_until <= now:
            return None
        return circuit.open_until

    def circuit_half_open(self, platform: str, now: datetime) -> bool:
        circuit = self.circuits.get(platform)
        return circuit is not None and circuit.level > 0 and circuit.open_until is not None \
            and circuit.open_until <= now

    async def observe(self, platform: str, code: OutcomeCode, reason: str | None = None) -> None:
        """Feed one classified outcome into `platform`'s breaker."""
        if code is OutcomeCode.AUTH_REQUIRED:
            return  # the AUTH HITL flow owns this; it neither trips nor resets the breaker
        self.turn_observed[platform] = self.turn_observed.get(platform, 0) + 1
        if trips_breaker(code):
            await self.circuit_failure(platform, f"{code.value}:{reason}" if reason else code.value)
        else:
            await self.circuit_success(platform)

    async def observe_outcome(self, platform: str, outcome: dict[str, Any]) -> None:
        code = outcome_code(outcome)
        if code is not None:
            await self.observe(platform, code, str(outcome.get("reason") or "")[:120] or None)

    async def circuit_failure(self, platform: str, reason: str) -> None:
        now = self.clock()
        circuit = self.circuits.setdefault(platform, Circuit())
        trial_failed = self.circuit_half_open(platform, now)
        circuit.failures += 1
        circuit.reason = reason
        if not trial_failed and circuit.failures < CIRCUIT_TRIP_AFTER:
            await self.persist_circuit(platform, circuit)
            return
        if circuit.open_until is not None and circuit.open_until > now:
            await self.persist_circuit(platform, circuit)  # already open (e.g. an owner run-once): no new event
            return
        circuit.level = min(circuit.level + 1, CIRCUIT_MAX_LEVEL)
        seconds = circuit_open_seconds(circuit.level)
        circuit.open_until = now + timedelta(seconds=seconds)
        logger.warning("portal %s circuit OPEN level=%s for %ss (failures=%s reason=%s)", platform, circuit.level,
                       seconds, circuit.failures, reason)
        await self.persist_circuit(platform, circuit)
        publish = getattr(self.service, "publish", None)
        if publish is not None:
            await publish("portal.circuit_open", {
                "platform": platform, "level": circuit.level, "failures": circuit.failures,
                "open_minutes": seconds // 60, "open_until": circuit.open_until.isoformat(timespec="seconds"),
                "reason": reason[:200], "half_open_trial_failed": trial_failed})

    async def circuit_success(self, platform: str) -> None:
        circuit = self.circuits.get(platform)
        if circuit is None or circuit.clean:
            return
        if circuit.open_until is not None and circuit.open_until > self.clock():
            return  # still open (an owner run-once bypassed it): only a half-open trial may close it
        if circuit.level:
            logger.info("portal %s circuit CLOSED after level %s", platform, circuit.level)
        self.circuits[platform] = Circuit()
        await self.persist_circuit(platform, self.circuits[platform])

    async def persist_circuit(self, platform: str, circuit: Circuit) -> None:
        try:
            await self.store.record_circuit(platform, failures=circuit.failures, level=circuit.level,
                                            open_until=circuit.open_until, reason=circuit.reason)
        except Exception as exc:  # noqa: BLE001 - the in-memory breaker still protects this process
            logger.warning("record_circuit %s failed: %s", platform, type(exc).__name__)
