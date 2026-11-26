"""Per-portal profile adapters for the profile sync.

``NaukriProfileUpdater`` lives in ``browser_v2/adapters/naukri/profile_updater.py`` (next to the
Naukri apply adapter) and is re-exported here LAZILY: that module imports
``profile_sync.adapters.base``, so an eager import here would be a runtime import cycle
whenever the Naukri module is imported first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.app.browser_v2.profile_sync.adapters.base import (
    ProfileAdapter,
    UncalibratedProfileAdapter,
    can_write,
    not_calibrated,
)
from backend.app.browser_v2.profile_sync.adapters.instahyre import (
    InstahyreProfileAdapter,
)
from backend.app.browser_v2.profile_sync.adapters.internshala import (
    InternshalaProfileAdapter,
)
from backend.app.browser_v2.profile_sync.adapters.wellfound import (
    WellfoundProfileAdapter,
)
from backend.app.browser_v2.profile_sync.adapters.work_at_a_startup import (
    WorkAtAStartupProfileAdapter,
)

if TYPE_CHECKING:
    from backend.app.browser_v2.adapters.naukri.profile_updater import (
        NaukriProfileUpdater,
    )

PROFILE_PORTALS = ("naukri", "instahyre", "internshala", "wellfound", "work_at_a_startup")

__all__ = [
    "PROFILE_PORTALS",
    "InstahyreProfileAdapter",
    "InternshalaProfileAdapter",
    "NaukriProfileUpdater",
    "ProfileAdapter",
    "UncalibratedProfileAdapter",
    "WellfoundProfileAdapter",
    "WorkAtAStartupProfileAdapter",
    "can_write",
    "default_profile_adapters",
    "not_calibrated",
]


def __getattr__(name: str) -> Any:
    if name == "NaukriProfileUpdater":
        from backend.app.browser_v2.adapters.naukri.profile_updater import (
            NaukriProfileUpdater,
        )

        return NaukriProfileUpdater
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def default_profile_adapters() -> dict[str, ProfileAdapter]:
    from backend.app.browser_v2.adapters.naukri.profile_updater import (
        NaukriProfileUpdater,
    )

    return {"naukri": NaukriProfileUpdater(), "instahyre": InstahyreProfileAdapter(),
            "internshala": InternshalaProfileAdapter(), "wellfound": WellfoundProfileAdapter(),
            "work_at_a_startup": WorkAtAStartupProfileAdapter()}
