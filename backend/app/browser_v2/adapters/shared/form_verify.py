"""Pre-submit read-back verification for hosted forms (Milestone 2).

Before the final Submit the filler re-scans the form and checks that every required field it
filled still holds a value (React widgets sometimes silently revert) and that the resume really
is attached to its file input. Any miss aborts to an owner question instead of submitting a
half-empty application. react-select comboboxes are skipped: their visible input is cleared by
design once an option is picked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SKIP_READBACK = frozenset({"combobox"})


def field_key(item: dict[str, Any], label: str) -> str:
    return f"{item.get('kind')}|{item.get('name') or ''}|{label}"


@dataclass(frozen=True)
class Expectation:
    key: str
    label: str
    kind: str
    resume: bool = False


@dataclass(frozen=True)
class ReadbackFailure:
    reason: str  # form_readback_failed | resume_not_attached
    label: str


def check_readback(expectations: list[Expectation], scanned: list[dict[str, Any]],
                   label_of: Any) -> ReadbackFailure | None:
    """First expectation whose field is still present but empty; vanished fields are ignored
    (a conditional block may legitimately collapse after a later answer)."""
    current: dict[str, dict[str, Any]] = {}
    for item in scanned:
        current.setdefault(field_key(item, label_of(item.get("label"))), item)
    for expected in expectations:
        if expected.kind in SKIP_READBACK:
            continue
        found = current.get(expected.key)
        if found is None:
            continue
        if not found.get("value_present"):
            return ReadbackFailure("resume_not_attached" if expected.resume else "form_readback_failed",
                                   expected.label)
    return None
