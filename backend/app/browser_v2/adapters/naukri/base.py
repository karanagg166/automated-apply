"""Shared attributes of the `NaukriAdapter` mixins (set in `NaukriAdapter.__init__`)."""

from __future__ import annotations

from pathlib import Path

from backend.app.browser_v2.adapters.naukri.constants import OtpProvider
from backend.app.browser_v2.answers import ScreeningResolver


class NaukriAdapterBase:
    """Attribute declarations only; `NaukriAdapter.__init__` assigns them."""

    platform: str
    refresh_wait_ms: int
    otp_provider: OtpProvider | None
    answerer: ScreeningResolver | None
    settle_ms: int
    receipts_dir: Path
    jitter: tuple[float, float]
