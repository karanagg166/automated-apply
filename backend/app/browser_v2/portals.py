"""The 10-portal roster (Phase 5): labels, login URLs and adapter readiness.

Only portals listed in `ADAPTER_READY` have a live Playwright adapter today; the
rest are seeded disabled in public.portal_rules so the dashboard can manage them
before Phase 6 wires their adapters. Direct ATS boards (Greenhouse, Lever) are
public read APIs and never need a browser login.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class PortalInfo:
    platform: str
    label: str
    tier: str  # interactive | ats
    login_url: str | None
    default_enabled: bool = False

    @property
    def requires_login(self) -> bool:
        return self.login_url is not None


PORTALS: dict[str, PortalInfo] = {p.platform: p for p in (
    PortalInfo("naukri", "Naukri", "interactive", "https://www.naukri.com/nlogin/login", default_enabled=True),
    PortalInfo("instahyre", "Instahyre", "interactive", "https://www.instahyre.com/login/"),
    PortalInfo("internshala", "Internshala", "interactive", "https://internshala.com/login/user"),
    PortalInfo("himalayas", "Himalayas", "interactive", "https://himalayas.app/login"),
    PortalInfo("wellfound", "Wellfound", "interactive", "https://wellfound.com/login"),
    PortalInfo("work_at_a_startup", "YC Work at a Startup", "interactive", "https://www.workatastartup.com"),
    PortalInfo("we_work_remotely", "We Work Remotely", "interactive", "https://weworkremotely.com/"),
    PortalInfo("hiringcafe", "HiringCafe", "interactive", "https://hiringcafe.com/"),
    PortalInfo("greenhouse", "Greenhouse (direct ATS)", "ats", None),
    PortalInfo("lever", "Lever (direct ATS)", "ats", None),
)}

# Portals whose adapter is implemented and may run live (Phase 6 extends this set).
ADAPTER_READY = frozenset({"naukri"})


def adapter_status(platform: str) -> Literal["ready", "pending_phase6"]:
    return "ready" if platform in ADAPTER_READY else "pending_phase6"


def portal_label(platform: str) -> str:
    info = PORTALS.get(platform)
    return info.label if info else platform.replace("_", " ").title()
