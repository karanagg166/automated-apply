"""The public Worker class: the control loop plus its portal, scheduling, quota and housekeeping mixins."""

from __future__ import annotations

from backend.app.browser_v2.worker.breaker import CircuitMixin
from backend.app.browser_v2.worker.cycle import CycleMixin
from backend.app.browser_v2.worker.executor import ExecutorMixin
from backend.app.browser_v2.worker.maintenance import MaintenanceMixin
from backend.app.browser_v2.worker.quota_flow import QuotaFlowMixin
from backend.app.browser_v2.worker.sweeps import SweepMixin


class Worker(ExecutorMixin, CycleMixin, SweepMixin, CircuitMixin, QuotaFlowMixin, MaintenanceMixin):
    """Crash-safe, single-tab 24/7 worker (see the `backend.app.browser_v2.worker` package docstring)."""
