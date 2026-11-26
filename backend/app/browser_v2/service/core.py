"""The public BrowserService (mixins composed in MRO order)."""

from __future__ import annotations

from backend.app.browser_v2.service.apply import ApplyMixin
from backend.app.browser_v2.service.base import BrowserServiceBase
from backend.app.browser_v2.service.gates import GatesMixin
from backend.app.browser_v2.service.handoff import HandoffMixin


class BrowserService(ApplyMixin, HandoffMixin, GatesMixin, BrowserServiceBase):
    pass
