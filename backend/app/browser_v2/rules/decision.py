"""Filter decision/result types shared by every rules evaluator."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Decision(StrEnum):
    PASS = "pass"
    FILTERED = "filtered"
    REVIEW = "review"


@dataclass(frozen=True)
class FilterResult:
    decision: Decision
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return self.decision is Decision.PASS


TITLE_MISMATCH_PREFIX = "title_not_in_target_roles"


def is_title_mismatch_only(result: FilterResult) -> bool:
    return result.decision is Decision.FILTERED and len(result.reasons) == 1 \
        and result.reasons[0].startswith(TITLE_MISMATCH_PREFIX)


def format_reason(result: FilterResult) -> str:
    prefix = "needs_review: " if result.decision is Decision.REVIEW else ""
    return prefix + "; ".join(result.reasons) if result.reasons else result.decision.value
