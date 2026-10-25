"""Refresh approved local GitHub mirrors without network access or source execution."""

import asyncio
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from backend.app.candidate_context.common import ContextError
from backend.app.candidate_context.persistence import SQLRecordStore
from backend.app.candidate_context.repository import AuthorizedCheckoutReader
from backend.app.candidate_context.service import CandidateContextService
from backend.app.candidate_context.templates import load_project_facts

CONTEXT_ROOT = Path(__file__).resolve().parents[3]


def context_service(session, settings):
    return CandidateContextService(
        SQLRecordStore(session),
        reader=AuthorizedCheckoutReader({
            url: Path(path) for url, path in settings.CANDIDATE_PROJECT_CHECKOUTS.items()
        }),
    )


async def refresh_projects(service, authorized_repositories, root=CONTEXT_ROOT):
    """Existing approvals are invalidated by changed candidates, never copied forward."""
    configuration = await service.configuration()
    results = {}
    for project in configuration.configuration.projects:
        if str(project.repository_url or "").rstrip("/") not in authorized_repositories:
            continue
        owner_facts = load_project_facts(root, project) if project.context_file else ()
        status, _ = await service.build(
            project.id,
            expected_configuration_revision=configuration.revision,
            owner_facts=owner_facts,
        )
        results[project.id] = status
    return results


async def refresh_loop(settings, session_factory):
    """Each pass commits atomically; cancellation rolls back and releases the session."""
    while True:
        try:
            async with session_factory() as session:
                await refresh_projects(context_service(session, settings), settings.CANDIDATE_PROJECT_CHECKOUTS)
                await session.commit()
        except (ContextError, SQLAlchemyError, OSError, ValueError):
            # The dashboard build endpoint provides a safe, actionable error.
            # Never log source text, personal claims or credentials from this loop.
            from backend.app.core.logging import logger
            logger.warning("Candidate project refresh failed; owner review required")
        await asyncio.sleep(settings.CANDIDATE_PROJECT_REFRESH_SECONDS)
