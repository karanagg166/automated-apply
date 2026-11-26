"""Deterministic Naukri adapter for the persistent Brave context.

DOM knowledge ported from the frozen v1 extension content scripts and the v1
Naukri questionnaire handler; nothing from v1 is imported at runtime. Actions
use real Playwright input (trusted events) in the single worker tab.

Naukri has no separate final Submit: clicking "Apply" either submits at once or
opens the chatbot, whose last answer submits. Dry-run therefore stops before
the Apply click.

Phase 8 (live `apply_control_changed` x2): inspection counted only VISIBLE Apply buttons in
the main JD header, but the click path re-counted with a page-wide locator over every
`[class*=jd-header]` (incl. the hidden sticky-header copy and pre-hydration duplicates), so a
single real button looked like two. The click path now resolves the control with the same
JS as inspection (visible + enabled, same header root), waits up to ~6 s for the React
header to settle (two identical consecutive reads), re-classifies hydration swaps
("Apply" -> "Apply on company site" / "Applied") instead of failing, and clicks the one
element it marked (`data-aa-apply`). Two genuinely visible Apply buttons still fail closed.
"""

# Phase 9A: split into the modules of this package; every old `adapters.naukri` name is re-exported.

from __future__ import annotations

from backend.app.browser_v2.adapters.naukri.adapter import (
    NaukriAdapter,
)
from backend.app.browser_v2.adapters.naukri.apply_flow import (
    NaukriApplyMixin,
)
from backend.app.browser_v2.adapters.naukri.auth import (
    NaukriAuthMixin,
    classify_auth,
)
from backend.app.browser_v2.adapters.naukri.base import (
    NaukriAdapterBase,
)
from backend.app.browser_v2.adapters.naukri.constants import (
    APPLY_SETTLE_POLLS,
    APPLY_SUCCESS,
    HISTORY_SENT,
    HISTORY_URL,
    HOME_URL,
    JOB_PATH,
    MAX_QUESTION_STEPS,
    OPTIONAL_QUESTION,
    ORIGIN,
    OTP_VALUE,
    PORTAL_LIMIT,
    PROFILE_URL,
    OtpProvider,
)
from backend.app.browser_v2.adapters.naukri.discovery import (
    NaukriDiscoveryMixin,
    external_job_id,
    search_url,
)
from backend.app.browser_v2.adapters.naukri.dom_scripts import (
    AUTH_PROBE_JS,
    DETAIL_JS,
    HISTORY_ALL_JS,
    HISTORY_JS,
    LISTING_JS,
    MARK_APPLY_JS,
    OTP_STATE_JS,
    PAGE_STATE_JS,
    VISIBLE_JS,
)
from backend.app.browser_v2.adapters.naukri.page_state import (
    NaukriPageStateMixin,
)
from backend.app.browser_v2.adapters.naukri.questionnaire import (
    NaukriQuestionnaireMixin,
)

__all__ = [
    "APPLY_SETTLE_POLLS",
    "APPLY_SUCCESS",
    "AUTH_PROBE_JS",
    "DETAIL_JS",
    "HISTORY_ALL_JS",
    "HISTORY_JS",
    "HISTORY_SENT",
    "HISTORY_URL",
    "HOME_URL",
    "JOB_PATH",
    "LISTING_JS",
    "MARK_APPLY_JS",
    "MAX_QUESTION_STEPS",
    "OPTIONAL_QUESTION",
    "ORIGIN",
    "OTP_STATE_JS",
    "OTP_VALUE",
    "PAGE_STATE_JS",
    "PORTAL_LIMIT",
    "PROFILE_URL",
    "VISIBLE_JS",
    "NaukriAdapter",
    "NaukriAdapterBase",
    "NaukriApplyMixin",
    "NaukriAuthMixin",
    "NaukriDiscoveryMixin",
    "NaukriPageStateMixin",
    "NaukriQuestionnaireMixin",
    "OtpProvider",
    "classify_auth",
    "external_job_id",
    "search_url",
]

