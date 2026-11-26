"""The 10-portal roster: labels, login URLs and adapter readiness.

Phase 6A: every portal has an adapter. Only naukri is seeded enabled in
public.portal_rules; the other nine stay disabled until the owner toggles them on.
Direct ATS boards (Greenhouse, Lever) and the public feeds (Himalayas, We Work
Remotely, HiringCafe search) never need a browser login for discovery or apply.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class PortalInfo:
    platform: str
    label: str
    tier: str  # interactive | feed | ats
    login_url: str | None
    default_enabled: bool = False
    needs_login: bool | None = None  # None = login_url is not None
    # Phase 8: default for portal_rules.allow_unknown_posting_age. True only where search cards
    # AND job pages never show a posting date (Instahyre lists only active openings).
    allow_unknown_age_default: bool = False

    @property
    def requires_login(self) -> bool:
        return self.login_url is not None if self.needs_login is None else self.needs_login


PORTALS: dict[str, PortalInfo] = {p.platform: p for p in (
    PortalInfo("naukri", "Naukri", "interactive", "https://www.naukri.com/nlogin/login", default_enabled=True),
    PortalInfo("instahyre", "Instahyre", "interactive", "https://www.instahyre.com/login/",
               allow_unknown_age_default=True),
    PortalInfo("internshala", "Internshala", "interactive", "https://internshala.com/login/user"),
    PortalInfo("himalayas", "Himalayas", "feed", "https://himalayas.app/login", needs_login=False),
    PortalInfo("wellfound", "Wellfound", "interactive", "https://wellfound.com/login"),
    PortalInfo("work_at_a_startup", "YC Work at a Startup", "interactive", "https://www.workatastartup.com"),
    PortalInfo("we_work_remotely", "We Work Remotely", "feed", "https://weworkremotely.com/", needs_login=False),
    PortalInfo("hiringcafe", "HiringCafe", "feed", "https://hiring.cafe/", needs_login=False),
    PortalInfo("greenhouse", "Greenhouse (direct ATS)", "ats", None),
    PortalInfo("lever", "Lever (direct ATS)", "ats", None),
    # Phase 8b: zero-cost public sources (discovery + Greenhouse/Lever handoff / manual handoff).
    PortalInfo("ashby", "Ashby (direct ATS)", "ats", None),
    PortalInfo("smartrecruiters", "SmartRecruiters (direct ATS)", "ats", None),
    PortalInfo("remotive", "Remotive", "feed", None),
    PortalInfo("arbeitnow", "Arbeitnow", "feed", None),
    PortalInfo("hacker_news", "Hacker News Who is Hiring", "feed", None),
)}

# Portals whose adapter is implemented and may run live (all 10 since Phase 6A).
ADAPTER_READY = frozenset(PORTALS)
# Portals whose session lives in the dedicated Brave profile (login-setup targets).
LOGIN_PORTALS = frozenset(name for name, info in PORTALS.items() if info.requires_login)


def adapter_status(platform: str) -> Literal["ready", "pending_phase6"]:
    return "ready" if platform in ADAPTER_READY else "pending_phase6"


def unknown_age_default(platform: str) -> bool:
    info = PORTALS.get(platform)
    return bool(info and info.allow_unknown_age_default)


def portal_label(platform: str) -> str:
    info = PORTALS.get(platform)
    return info.label if info else platform.replace("_", " ").title()
