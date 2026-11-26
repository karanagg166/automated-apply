"""The deterministic `NaukriAdapter` (composed from the naukri mixins)."""

from __future__ import annotations

from pathlib import Path

from backend.app.browser_v2 import profile as brave_profile
from backend.app.browser_v2.adapters.naukri.apply_flow import NaukriApplyMixin
from backend.app.browser_v2.adapters.naukri.auth import NaukriAuthMixin
from backend.app.browser_v2.adapters.naukri.base import NaukriAdapterBase
from backend.app.browser_v2.adapters.naukri.constants import OtpProvider
from backend.app.browser_v2.adapters.naukri.discovery import NaukriDiscoveryMixin
from backend.app.browser_v2.adapters.naukri.page_state import NaukriPageStateMixin
from backend.app.browser_v2.adapters.naukri.questionnaire import (
    NaukriQuestionnaireMixin,
)
from backend.app.browser_v2.answers import ScreeningResolver


class NaukriAdapter(NaukriApplyMixin, NaukriQuestionnaireMixin, NaukriPageStateMixin, NaukriDiscoveryMixin,
                    NaukriAuthMixin, NaukriAdapterBase):
    platform = "naukri"

    def __init__(self, *, refresh_wait_ms: int = 3000, settle_ms: int = 1500,
                 receipts_dir: Path | None = None, jitter: tuple[float, float] = (0.8, 2.2),
                 answerer: ScreeningResolver | None = None,
                 otp_provider: OtpProvider | None = None) -> None:
        self.refresh_wait_ms = refresh_wait_ms
        # Phase 6A: auto email-OTP (MailReadService.fetch_recent_otp) when no owner answer exists.
        self.otp_provider = otp_provider
        # Phase 3: Tier 0 profile -> Tier 1 semantic cache -> Tier 2 free LLM; None = HITL.
        self.answerer = answerer
        self.settle_ms = settle_ms
        self.receipts_dir = receipts_dir or brave_profile.runtime_dir() / "receipts" / "naukri"
        self.jitter = jitter
