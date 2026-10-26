"""Apply only explicit selections exported from a private owner review.

Authenticates with the existing owner API and revalidates all pins before committing
through the existing resume and project services. Never invoked by preparation.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


async def apply(env_file, plan_path, manifest_path, selection_path):
    import httpx
    from sqlalchemy import select

    from backend.app.candidate_context.common import canonical_hash
    from backend.app.candidate_context.configuration import CandidateConfiguration
    from backend.app.candidate_context.persistence import SQLRecordStore
    from backend.app.candidate_context.projects import ProjectFact
    from backend.app.candidate_context.repository import AuthorizedCheckoutReader
    from backend.app.candidate_context.review import selected_requests
    from backend.app.candidate_context.service import CandidateContextService
    from backend.app.core.config import Settings, configure_operator
    from backend.app.dashboard.models import PrivateResume
    from backend.app.dashboard.resumes import verified_pdf
    from backend.app.dashboard.router import confirm_resume
    from backend.app.dashboard.schemas import ResumeConfirm
    from backend.app.db.session import close_db_engine, get_session_factory
    from backend.app.local_agent.profile_confirmation import confirm_profile
    from backend.app.models.application_answer import CandidateResource
    from backend.app.models.candidate_profile import CandidateProfile
    from backend.app.services.applications.resume_selector import select_resume
    from backend.app.services.candidate_profile_service import CandidateProfileService

    settings = Settings(_env_file=env_file)
    configure_operator(settings)
    if not settings.DB_REMOTE_ONLY or not settings.DB_REQUIRE_TLS or settings.DB_ECHO:
        raise ValueError("owner_approved_online_tls_database_required")
    plan = json.loads(plan_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    selection = json.loads(selection_path.read_text())
    requests = selected_requests(manifest, selection)
    if canonical_hash(plan) != manifest["staging"]["plan_hash"]:
        raise ValueError("preparation_plan_changed")
    async with httpx.AsyncClient(
        base_url=settings.LOCAL_AGENT_ENDPOINT, timeout=30, follow_redirects=False
    ) as client:
        response = await client.get(
            "/api/v1/profile",
            headers={
                "Authorization": "Bearer "
                + settings.JOB_AGENT_API_TOKEN.get_secret_value(),
            },
        )
        response.raise_for_status()
        if str(response.json()["id"]) != selection["profile_id"]:
            raise ValueError("owner_profile_changed")
    reader = AuthorizedCheckoutReader(
        {url: Path(path) for url, path in plan["checkouts"].items()},
        selected_paths={
            url: tuple(paths) for url, paths in plan["source_paths"].items()
        },
    )
    try:
        async with get_session_factory()() as session:
            # Lock identity before either canonical-resume selection or context CAS.
            profile = await session.scalar(
                select(CandidateProfile)
                .where(CandidateProfile.singleton_key == "primary")
                .with_for_update()
            )
            current = await CandidateProfileService(session).get_profile()
            if (
                str(profile.id) != selection["profile_id"]
                or current.version != selection["profile_version"]
                or canonical_hash(current.model_dump(mode="json"))
                != manifest["staging"]["profile_hash"]
            ):
                raise ValueError("profile_changed_regenerate_review")
            resume = await session.get(
                PrivateResume, plan["resume_id"], with_for_update=True
            )
            if resume is None or resume.sha256 != plan["resume_sha256"]:
                raise ValueError("resume_changed_regenerate_review")
            verified_pdf(resume)
            service = CandidateContextService(SQLRecordStore(session), reader=reader)
            config = await service.configuration()
            desired = CandidateConfiguration.model_validate(plan["configuration"])
            project_requests = [r for r in requests if "fact_ids" in r["body"]]
            if project_requests and config.configuration != desired:
                config = await service.save_configuration(
                    desired,
                    expected_revision=manifest["staging"]["configuration_revision"],
                    owner_ref="owner",
                    source="owner_file",
                )
            # Build every selected revision first. Any mismatch rolls back the
            # entire transaction, including previously staged changes.
            for request in project_requests:
                project_id = request["path"].split("/")[-2]
                facts = tuple(
                    ProjectFact.model_validate(f) for f in plan["facts"][project_id]
                )
                previous = await service.project(project_id)
                baseline = manifest["staging"]["project_record_revisions"][project_id]
                retry = (
                    previous.candidate
                    and previous.approved
                    and previous.candidate.revision
                    == request["body"]["expected_revision"]
                    and previous.approved.revision
                    == request["body"]["expected_revision"]
                    and previous.approved.fact_ids == tuple(request["body"]["fact_ids"])
                )
                if previous.revision != baseline and not retry:
                    raise ValueError("project_changed_rebuild_and_review")
                _, knowledge = await service.build(
                    project_id,
                    expected_configuration_revision=config.revision,
                    owner_facts=facts,
                    expected_project_revision=previous.revision,
                )
                if knowledge.candidate.revision != request["body"]["expected_revision"]:
                    raise ValueError("project_changed_rebuild_and_review")
            for request in project_requests:
                await service.approve(
                    request["path"].split("/")[-2],
                    expected_revision=request["body"]["expected_revision"],
                    fact_ids=tuple(request["body"]["fact_ids"]),
                    owner_ref="owner",
                    owner_confirmed=request["body"]["owner_confirmed"],
                )
            for request in requests:
                if request["path"] == manifest["requests"]["resume"]["path"]:
                    await confirm_resume(
                        resume.id,
                        ResumeConfirm.model_validate(request["body"]),
                        session,
                    )
            # Finish any invalidation before optionally restoring the explicitly
            # selected profile binding, including promotion of an existing PDF.
            await session.flush()
            for request in requests:
                if request["path"] == "/api/v1/local-agent/profile-confirmation":
                    await confirm_profile(
                        session, profile, request["body"]["expected_version"]
                    )
            await session.flush()
            resources = list(
                (
                    await session.scalars(
                        select(CandidateResource).where(
                            CandidateResource.candidate_profile_id == profile.id
                        )
                    )
                ).all()
            )
            selected = select_resume(resources).selected
            if (
                any(
                    r["path"] == manifest["requests"]["resume"]["path"]
                    for r in requests
                )
                and selected is None
            ):
                raise ValueError("unique_primary_resume_required")
            if profile.version != selection["profile_version"]:
                raise ValueError("profile_version_must_be_preserved")
            await session.commit()
            print(
                json.dumps(
                    {
                        "selected_requests_saved": len(requests),
                        "profile_version": profile.version,
                        "primary_resume_selected": selected is not None,
                    }
                )
            )
    finally:
        await close_db_engine()


def main():
    os.umask(0o077)
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("env-file", "plan", "manifest", "selection"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        asyncio.run(apply(args.env_file, args.plan, args.manifest, args.selection))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "approval_not_committed",
                    "exception_type": type(exc).__name__,
                    "details": "redacted; regenerate the private review if any revision changed",
                }
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
