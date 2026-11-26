"""The config-driven persistent-Brave `InteractivePortalAdapter` (composed from mixins)."""

from __future__ import annotations

from backend.app.browser_v2.adapters.shared.discovery import PortalDiscoveryMixin
from backend.app.browser_v2.adapters.shared.portal_apply import PortalApplyMixin
from backend.app.browser_v2.adapters.shared.portal_base import (
    PortalAdapterBase,
    PortalConfig,
)


class InteractivePortalAdapter(PortalApplyMixin, PortalDiscoveryMixin, PortalAdapterBase):
    """Persistent-Brave portal adapter driven by a `PortalConfig` (one worker tab)."""

    config: PortalConfig
