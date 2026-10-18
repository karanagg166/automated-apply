"""Explicit non-overwriting environment import. Run from repository root with -m."""
import argparse
import asyncio

from backend.app.core.config import get_settings
from backend.app.db.session import get_db_context, close_db_engine
from backend.app.repositories.candidate_knowledge import CandidateKnowledgeRepository, STANDARD_FIELDS
from backend.app.schemas.candidate_resources import ResourceWrite
from backend.app.services.profile_link_resolver import ENV_FIELDS


async def import_defaults(repo, settings, apply=False):
    profile = await repo.profile()
    existing = await repo.resolution_resources(profile.id)
    actions = []
    for kind, env_name in ENV_FIELDS.items():
        value = getattr(settings, env_name)
        if not value:
            continue
        standard = STANDARD_FIELDS.get(kind)
        if standard and (getattr(profile, standard) is not None or profile.version > 1):
            continue
        if any(item.resource_type == kind for item in existing):
            continue
        actions.append({"resource_type": kind, "url": str(value), "standard": bool(standard)})
    if apply:
        expected_version = profile.version
        for action in actions:
            await repo.save_resource(ResourceWrite(
                resource_type=action["resource_type"], label="Environment import", url=action["url"],
                is_primary=True, source_type="environment_import",
                user_confirmed=action["standard"],  # --apply explicitly approves listed standard fields.
                expected_profile_version=expected_version,
            ))
            if action["standard"]:
                expected_version += 1
    return actions


async def main(apply):
    try:
        async with get_db_context() as session:
            actions = await import_defaults(CandidateKnowledgeRepository(session), get_settings(), apply)
            for action in actions:
                print(action)
            print(f'{"Applied" if apply else "Dry run:"} {len(actions)} additions; no existing values overwritten')
    finally:
        await close_db_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Review defaults with --dry-run before --apply. Applying approves standard links; additional resources require separate confirmation.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    asyncio.run(main(parser.parse_args().apply))
