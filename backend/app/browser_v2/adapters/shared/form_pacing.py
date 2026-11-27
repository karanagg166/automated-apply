"""Human Pulse: human-velocity pacing for hosted-form filling (Milestone 2).

ATS submission-velocity sensors flag forms completed in < 500 ms. The filler therefore pauses
180-550 ms between fields, types short text inputs key by key (40-120 ms per character) and
waits 1.2-2.5 s before the final Submit, like a person re-reading the form.

`AUTOMATED_APPLY_HUMAN_PULSE=0` (the test suite sets it) or an explicit zero jitter turns every
pause off; nothing here changes WHAT is filled, only how fast.
"""

from __future__ import annotations

import asyncio
import os
import random
from collections.abc import Awaitable, Callable
from typing import Any

ENV = "AUTOMATED_APPLY_HUMAN_PULSE"
FIELD_PAUSE = (0.18, 0.55)
KEYSTROKE_MS = (40, 120)
SUBMIT_PAUSE = (1.2, 2.5)
SHORT_TEXT_MAX = 40


def pulse_enabled(env: dict[str, str] | None = None) -> bool:
    value = ((env if env is not None else os.environ).get(ENV) or "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


class HumanPulse:
    def __init__(self, *, field_pause: tuple[float, float] = FIELD_PAUSE,
                 keystroke_ms: tuple[int, int] = KEYSTROKE_MS, submit_pause: tuple[float, float] = SUBMIT_PAUSE,
                 enabled: bool | None = None, rng: random.Random | None = None,
                 sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep) -> None:
        self.enabled = pulse_enabled() if enabled is None else enabled
        self.field_pause = field_pause
        self.keystroke_ms = keystroke_ms
        self.submit_pause = submit_pause
        self.rng = rng or random.Random()  # timing jitter, not security
        self.sleep = sleep

    @classmethod
    def from_jitter(cls, jitter: tuple[float, float]) -> HumanPulse:
        """Legacy `jitter=(0, 0)` (tests, calibration) disables every pause."""
        if jitter[1] <= 0:
            return cls(enabled=False)
        return cls(field_pause=jitter)

    async def _pause(self, bounds: tuple[float, float]) -> None:
        if self.enabled and bounds[1] > 0:
            await self.sleep(self.rng.uniform(*bounds))

    async def between_fields(self) -> None:
        await self._pause(self.field_pause)

    async def before_submit(self) -> None:
        await self._pause(self.submit_pause)

    def keystroke_delay(self, value: str) -> int | None:
        """Per-key delay (ms) for short free-text values; None = fill at once."""
        if not self.enabled or not value or len(value) > SHORT_TEXT_MAX:
            return None
        return int(self.rng.uniform(*self.keystroke_ms))


async def type_like_a_human(locator: Any, value: str, pulse: HumanPulse, *, timeout_ms: int) -> None:
    """fill() at once, or clear + key-by-key typing for short text when the pulse is on."""
    delay = pulse.keystroke_delay(value)
    sequential = getattr(locator, "press_sequentially", None)
    if delay is None or sequential is None:
        await locator.fill(value, timeout=timeout_ms)
        return
    await locator.fill("", timeout=timeout_ms)
    await sequential(value, delay=delay, timeout=timeout_ms + delay * len(value))
