"""Profile adapter port + the fail-closed base for portals whose profile UI is not calibrated.

SELECTORS ARE NEVER INVENTED. An adapter is ``calibrated = True`` only when its selectors come
from a verified source (live probe or the legacy reference implementation) AND a fixture test
covers them. An uncalibrated adapter's ``read`` reports every supported field as
``skipped_not_calibrated`` and its ``write`` / ``touch`` return False, all WITHOUT touching
the page. ``calibrated_fields`` narrows writes further on a calibrated adapter.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from backend.app.browser_v2.profile_sync.models import FieldStatus, FieldValue


@runtime_checkable
class ProfileAdapter(Protocol):
    # Read-only members: plain class attributes on the implementations satisfy them.
    @property
    def platform(self) -> str: ...

    @property
    def supported_fields(self) -> frozenset[str]: ...

    @property
    def calibrated(self) -> bool: ...

    @property
    def calibrated_fields(self) -> frozenset[str]: ...

    @property
    def freshness_touch(self) -> bool:
        """Naukri: a re-upload of the identical PDF bumps "Profile last updated"."""
        ...

    @property
    def selectors(self) -> Mapping[str, str | None]: ...

    @property
    def profile_url(self) -> str | None: ...

    async def read(self, page: Any) -> dict[str, FieldValue]:
        """Current portal values for `supported_fields` (FieldValue.status set when unreadable)."""
        ...

    async def write(self, page: Any, field: str, value: Any) -> bool:
        """Save ONE field. key_skills receives only the skills to ADD. True = the save was clicked."""
        ...

    async def touch(self, page: Any, resume_path: str | None = None) -> bool:
        """Freshness touch (True only when the page proves the profile was updated)."""
        ...


def not_calibrated(fields: frozenset[str], reason: str = "selectors_not_calibrated") -> dict[str, FieldValue]:
    return {name: FieldValue(status=FieldStatus.SKIPPED_NOT_CALIBRATED, reason=reason) for name in sorted(fields)}


def can_write(adapter: ProfileAdapter, field: str) -> bool:
    return bool(adapter.calibrated and field in adapter.supported_fields and field in adapter.calibrated_fields)


class UncalibratedProfileAdapter:
    """Declares what a portal profile supports; never reads or writes the page."""

    platform = ""
    supported_fields: frozenset[str] = frozenset()
    calibrated = False
    calibrated_fields: frozenset[str] = frozenset()
    freshness_touch = False
    selectors: Mapping[str, str | None] = MappingProxyType({})
    profile_url: str | None = None

    async def read(self, page: Any) -> dict[str, FieldValue]:
        return not_calibrated(self.supported_fields)

    async def write(self, page: Any, field: str, value: Any) -> bool:
        return False

    async def touch(self, page: Any, resume_path: str | None = None) -> bool:
        return False
