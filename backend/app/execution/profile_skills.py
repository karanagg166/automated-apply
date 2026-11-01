"""Add-only plans for verified skills; editing is separate from Save authority."""

from backend.app.agent.tools import ToolDenied
from backend.app.services.application_assistant import skill_key


def skills(value, *, empty=False):
    if (not isinstance(value, list) or not (0 if empty else 1) <= len(value) <= 100
            or any(not isinstance(item, str) or not item.strip() or len(item) > 200 for item in value)):
        raise ToolDenied("profile_skills_bounded_observation_required")
    return [" ".join(item.split()) for item in value]


def additions(canonical, existing):
    """Published aliases avoid duplicate chips, never imply related expertise."""
    before = {skill_key(item) for item in skills(existing, empty=True)}
    result = []
    for item in skills(canonical):
        key = skill_key(item)
        if key not in before:
            result.append(item)
            before.add(key)
    return result


def prepared(before, approved, observed):
    """The editor must retain every original chip and add only approved facts."""
    before, observed = skills(before, empty=True), skills(observed)
    if observed[:len(before)] != before or len(observed) <= len(before):
        raise ToolDenied("profile_skills_existing_chips_changed_or_no_addition")
    approved_keys = {item.casefold() for item in skills(approved)}
    added = observed[len(before):]
    if (any(item.casefold() not in approved_keys for item in added)
            or len({skill_key(item) for item in observed}) != len({skill_key(item) for item in before}) + len(added)):
        raise ToolDenied("profile_skills_unapproved_or_duplicate_addition")
    return observed
