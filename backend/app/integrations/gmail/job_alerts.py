"""Saved status of the retired Gmail Naukri job-alert intake (read-only).

The intake fed the v1 Naukri execution queue, which was retired in Phase 9E
together with its worker. Saved per-account policy rows are still reported so the
Connections page keeps rendering, but nothing polls them any more: ``enabled`` is
always false and configuring or syncing alerts is refused with ``RETIRED``.
"""

from pydantic import Field, StrictBool

from backend.app.ai.schemas import Contract
from backend.app.dashboard.models import OwnerPreference

PREFIX = "gm54_alerts:"
SENDER = "naukrialerts@naukri.com"
RETIRED = "gmail_job_alerts_retired"


class AlertPolicy(Contract):
    expected_version: int = Field(ge=0)
    expected_generation: int = Field(ge=1)
    enabled: StrictBool
    interval_seconds: int = Field(900, ge=900, le=86400)


async def status(session, slot):
    row = await session.get(OwnerPreference, PREFIX + slot, populate_existing=True)
    value = row.value if row else {"version": 0, "enabled": False}
    return {k: v for k, v in value.items() if k not in {"lease", "lease_until", "page_token"}} | {
        "enabled": False, "configured_enabled": value.get("enabled", False), "retired": True,
        "sender": SENDER, "sending_enabled": False, "links_opened": False,
    }
