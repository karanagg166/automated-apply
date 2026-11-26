"""Wellfound profile adapter: declared fields only (uncalibrated: no verified selectors yet).

Calibrate with `cli probe-profile-page --portal wellfound --url <profile edit page>` (worker stopped),
then fill `selectors`, add a fixture test and only then set `calibrated = True`.
"""

from __future__ import annotations

from types import MappingProxyType

from backend.app.browser_v2.profile_sync.adapters.base import UncalibratedProfileAdapter

FIELDS = frozenset({"resume_pdf", "resume_headline", "profile_summary", "key_skills", "current_location",
                    "preferred_locations", "notice_period"})


class WellfoundProfileAdapter(UncalibratedProfileAdapter):
    platform = "wellfound"
    supported_fields = FIELDS
    calibrated = False
    selectors = MappingProxyType(dict.fromkeys(sorted(FIELDS)))  # every selector unknown (None)
    profile_url = None  # not verified: pass --url to probe-profile-page
