"""YC Work at a Startup profile adapter: declared fields only (uncalibrated: no verified selectors yet).

Calibrate with `cli probe-profile-page --portal work_at_a_startup --url <profile edit page>` (worker stopped),
then fill `selectors`, add a fixture test and only then set `calibrated = True`.
"""

from __future__ import annotations

from types import MappingProxyType

from backend.app.browser_v2.profile_sync.adapters.base import UncalibratedProfileAdapter

FIELDS = frozenset({"resume_pdf", "profile_summary", "key_skills", "current_location"})


class WorkAtAStartupProfileAdapter(UncalibratedProfileAdapter):
    platform = "work_at_a_startup"
    supported_fields = FIELDS
    calibrated = False
    selectors = MappingProxyType(dict.fromkeys(sorted(FIELDS)))  # every selector unknown (None)
    profile_url = None  # not verified: pass --url to probe-profile-page
