"""Shared Phase 6A adapter engine.

- `classify_ats(url)`: greenhouse | lever | None for external employer links.
- `HostedFormFiller`: deterministic-first filler for hosted ATS forms and portal apply
  modals. Identity fields (name, email, phone, links, city) come from stored profile
  facts and are typed into the DOM only (never sent to an LLM). The best-matching
  resume PDF is uploaded. Every other REQUIRED question goes HITL answer -> 4-tier
  resolver (profile -> semantic cache -> free LLM) -> WAITING_FOR_USER. Optional
  unknown fields (EEO, demographics, "how did you hear") are left untouched.
- `HostedAtsApplier`: navigate to a Greenhouse/Lever form, fill, stop before Submit
  on dry-run, otherwise submit and verify a concrete confirmation signal.
- `InteractivePortalAdapter`: config-driven persistent-Brave portal adapter (session
  check with one reload, card discovery, detail parsing, Apply click + modal handling,
  confirmation / applied-badge verification, limit + challenge detection).

Selectors for the interactive portals are text/attribute based on purpose so small DOM
changes degrade to FAILED / SUBMISSION_UNKNOWN (never a blind replay).
"""

# Phase 9A: the engine lives in `adapters/shared/`; this module is a thin re-export facade so
# every existing `from backend.app.browser_v2.adapters.common import ...` keeps working.

from __future__ import annotations

from backend.app.browser_v2.adapters.shared import (
    _GENERIC_LABELS,
    _GH_ID,
    _LEVER_ID,
    AUTOCOMPLETE_MAP,
    CARDS_JS,
    COMPANY_BADGE,
    CONFIRM_TEXT,
    CONFIRM_URL,
    COVER_FILE,
    COVER_NOTE,
    DETAIL_JS,
    DIALOG_JS,
    FORM_STATE_JS,
    GREENHOUSE_HOSTS,
    GREENHOUSE_PATH,
    IDENTITY_FIELDS,
    LEVER_HOSTS,
    LEVER_PATH,
    MARK_APPLY_JS,
    MAX_DESCRIPTION,
    MAX_FORM_STEPS,
    NAME_ATTR_MAP,
    NEXT_TEXT,
    OPTIONS_JS,
    PROBE_JS,
    RESUME_FIELD,
    SCAN_JS,
    SUBMIT_TEXT,
    SUPPORTED_ATS,
    AtsHandoff,
    FillOutcome,
    HostedAtsApplier,
    HostedFormFiller,
    InteractivePortalAdapter,
    NoteComposer,
    PortalAdapterBase,
    PortalApplyMixin,
    PortalConfig,
    PortalDiscoveryMixin,
    S,
    _board_guess,
    age_days_from,
    ats_form_url,
    ats_handoff_target,
    button_locator,
    classify_ats,
    clean_label,
    confirmation_source,
    deterministic_intro,
    form_state,
    html_to_text,
    identity_key,
    poll_state,
    resolve_question,
    role_query_match,
    visible_buttons,
)

__all__ = [
    "AUTOCOMPLETE_MAP",
    "CARDS_JS",
    "COMPANY_BADGE",
    "CONFIRM_TEXT",
    "CONFIRM_URL",
    "COVER_FILE",
    "COVER_NOTE",
    "DETAIL_JS",
    "DIALOG_JS",
    "FORM_STATE_JS",
    "GREENHOUSE_HOSTS",
    "GREENHOUSE_PATH",
    "IDENTITY_FIELDS",
    "LEVER_HOSTS",
    "LEVER_PATH",
    "MARK_APPLY_JS",
    "MAX_DESCRIPTION",
    "MAX_FORM_STEPS",
    "NAME_ATTR_MAP",
    "NEXT_TEXT",
    "OPTIONS_JS",
    "PROBE_JS",
    "RESUME_FIELD",
    "SCAN_JS",
    "SUBMIT_TEXT",
    "SUPPORTED_ATS",
    "_GENERIC_LABELS",
    "_GH_ID",
    "_LEVER_ID",
    "AtsHandoff",
    "FillOutcome",
    "HostedAtsApplier",
    "HostedFormFiller",
    "InteractivePortalAdapter",
    "NoteComposer",
    "PortalAdapterBase",
    "PortalApplyMixin",
    "PortalConfig",
    "PortalDiscoveryMixin",
    "S",
    "_board_guess",
    "age_days_from",
    "ats_form_url",
    "ats_handoff_target",
    "button_locator",
    "classify_ats",
    "clean_label",
    "confirmation_source",
    "deterministic_intro",
    "form_state",
    "html_to_text",
    "identity_key",
    "poll_state",
    "resolve_question",
    "role_query_match",
    "visible_buttons",
]

