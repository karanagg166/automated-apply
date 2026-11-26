"""v2 control plane: portal rules (list + optimistic-revision patch)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.api.v1.v2.deps import StoreDep
from backend.app.browser_v2.schemas import PortalRulesPatch, PortalRulesRead
from backend.app.browser_v2.store import ProfileMissing, RevisionConflict, RulesNotFound

router = APIRouter()


# --- portal rules -------------------------------------------------------------------
@router.get("/portal-rules", response_model=list[PortalRulesRead])
async def list_portal_rules(store: StoreDep) -> list[PortalRulesRead]:
    return [PortalRulesRead.from_rules(rules) for rules in await store.list_rules()]


@router.patch("/portal-rules/{platform}", response_model=PortalRulesRead,
              responses={404: {"description": "Unknown portal"},
                         409: {"description": "Revision conflict; reload and retry"}})
async def patch_portal_rules(platform: str, data: PortalRulesPatch,
                             store: StoreDep) -> PortalRulesRead:
    current = {r.platform: r for r in await store.list_rules()}.get(platform)
    if current is None:
        raise HTTPException(404, "Unknown portal")
    changes = data.changes()
    merged = {**{name: getattr(current, name) for name in changes}, **changes}
    min_delay = merged.get("min_delay_sec", current.min_delay_sec)
    max_delay = merged.get("max_delay_sec", current.max_delay_sec)
    if max_delay < min_delay:
        raise HTTPException(422, "max_delay_sec must be greater than or equal to min_delay_sec")
    per_hour = merged.get("max_applies_per_hour", current.max_applies_per_hour)
    per_day = merged.get("max_applies_per_day", current.max_applies_per_day)
    if per_hour > per_day:
        raise HTTPException(422, "max_applies_per_hour cannot exceed max_applies_per_day")
    try:
        updated = await store.update_rules(platform, changes, data.revision)
    except RulesNotFound:
        raise HTTPException(404, "Unknown portal") from None
    except RevisionConflict as exc:
        raise HTTPException(409, f"Rules changed (current revision {exc.current}); reload and retry") from None
    except ProfileMissing:
        raise HTTPException(409, "allow_unknown_posting_age is stored with the candidate profile; "
                                 "create the profile first") from None
    return PortalRulesRead.from_rules(updated)
