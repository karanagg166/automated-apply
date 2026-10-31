"""Owner-approved portal identity, independent of candidate contact information.

Only a hash of the ordinary profile UI identity is stored. Reconnection keeps
the approval; changing the candidate or selected Chrome installation does not.
"""

from uuid import UUID

from pydantic import Field

from backend.app.agent.tools import ToolDenied
from backend.app.automation.store import instant
from backend.app.browser import chrome_profiles
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import store
from backend.app.execution.contracts import Contract

KEY = "naukri_account_binding"


class AccountApproval(Contract):
    expected_revision: int = Field(ge=0)
    candidate_profile_id: UUID
    profile_binding_id: UUID
    account_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    owner_confirmed: bool


async def status(session):
    row = await session.get(OwnerPreference, KEY, populate_existing=True)
    return dict(row.value) if row else {"revision": 0, "approved": False}


async def approve(session, data):
    await store.memory_row(session, lock=True)
    current = await status(session)
    if data.expected_revision != current["revision"]:
        raise ToolDenied("account_binding_revision_conflict")
    if not data.owner_confirmed:
        raise ToolDenied("owner_account_confirmation_required")
    from backend.app.models.candidate_profile import CandidateProfile

    profile = await session.get(CandidateProfile, data.candidate_profile_id)
    selected = await chrome_profiles.selection(session)
    chrome = await session.get(OwnerPreference, chrome_profiles.PROFILE + str(data.profile_binding_id))
    if (not profile or profile.singleton_key != "primary" or not chrome
            or selected["profile_binding_id"] != str(data.profile_binding_id)):
        raise ToolDenied("account_binding_context_changed")
    value = {"revision": current["revision"] + 1, "approved": True,
             "candidate_profile_id": str(profile.id),
             "profile_binding_id": str(data.profile_binding_id),
             "account_sha256": data.account_sha256,
             "evidence_sha256": data.evidence_sha256,
             "source": "owner_confirmed_profile_ui", "approved_at": (await instant(session)).isoformat()}
    from backend.app.execution.application_queue import put

    await put(session, KEY, value)
    return value


async def require(session, candidate_profile_id=None, profile_binding_id=None):
    value = await status(session)
    selected = await chrome_profiles.selection(session)
    if not value.get("approved"):
        raise ToolDenied("approved_naukri_account_binding_required")
    if (value["profile_binding_id"] != selected["profile_binding_id"]
            or (profile_binding_id is not None and value["profile_binding_id"] != str(profile_binding_id))
            or (candidate_profile_id is not None and value["candidate_profile_id"] != str(candidate_profile_id))):
        raise ToolDenied("naukri_account_binding_context_changed")
    return value


async def check_work(session, value):
    binding = await require(session, value.get("candidate_profile_id"),
                            (value.get("binding") or {}).get("profile_binding_id"))
    if (binding["revision"] != value.get("account_binding_revision")
            or binding["account_sha256"] != value.get("account_sha256")):
        raise ToolDenied("naukri_account_binding_changed")
    return binding
