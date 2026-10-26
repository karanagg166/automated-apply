"""Stage pending context privately using existing versioned services.

No approval mode exists. Source proposals live in a private JSON plan, never Git.
The running owner API authenticates the existing token; no service is restarted.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def prepare(env_file, plan_path, output):
    import httpx
    from sqlalchemy import select, text

    from backend.app.ai.schemas import GenerateRequest
    from backend.app.candidate_context.common import canonical_hash
    from backend.app.candidate_context.configuration import CandidateConfiguration
    from backend.app.candidate_context.persistence import (
        MemoryRecordStore,
        SQLRecordStore,
    )
    from backend.app.candidate_context.projects import ProjectFact
    from backend.app.candidate_context.repository import AuthorizedCheckoutReader
    from backend.app.candidate_context.review import (
        confirmation_requests,
        write_private_review,
    )
    from backend.app.candidate_context.service import CandidateContextService
    from backend.app.core.config import Settings, configure_operator
    from backend.app.dashboard.models import PrivateResume
    from backend.app.dashboard.resumes import extract_pdf, verified_pdf
    from backend.app.db.session import close_db_engine, get_session_factory
    from backend.app.models.application_answer import CandidateResource
    from backend.app.models.candidate_profile import CandidateProfile
    from backend.app.operations.onboarding import profile_readiness
    from backend.app.services.application_answer_service import ApplicationAnswerService
    from backend.app.services.applications.resume_selector import select_resume
    from backend.app.services.candidate_profile_service import CandidateProfileService

    settings = Settings(_env_file=env_file)
    configure_operator(settings)
    if not settings.DB_REMOTE_ONLY or not settings.DB_REQUIRE_TLS or settings.DB_ECHO:
        raise ValueError("owner_approved_online_tls_database_required")
    plan = json.loads(plan_path.read_text())
    # Do not carry credentials into the report, source plan, exceptions or logs.
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
        authenticated_profile = response.json()
    reader = AuthorizedCheckoutReader(
        {url: Path(path) for url, path in plan["checkouts"].items()},
        selected_paths={
            url: tuple(paths) for url, paths in plan["source_paths"].items()
        },
    )
    snapshots = []
    try:
        async with get_session_factory()() as session:
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            )
            profile = await session.scalar(
                select(CandidateProfile).where(
                    CandidateProfile.singleton_key == "primary"
                )
            )
            if (
                profile is None
                or str(profile.id) != str(authenticated_profile["id"])
                or profile.version != plan["profile_version"]
                or profile.version != authenticated_profile["version"]
            ):
                raise ValueError("profile_changed_regenerate_review")
            if not await session.scalar(
                text("SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()")
            ):
                raise ValueError("tls_connection_required")
            resume = await session.get(PrivateResume, plan["resume_id"])
            if resume is None or resume.sha256 != plan["resume_sha256"]:
                raise ValueError("resume_changed_regenerate_review")
            raw = verified_pdf(resume)
            extracted = await extract_pdf(raw)
            resources = list(
                (
                    await session.scalars(
                        select(CandidateResource).where(
                            CandidateResource.candidate_profile_id == profile.id
                        )
                    )
                ).all()
            )
            primary = [
                r for r in resources if r.resource_type == "resume" and r.is_primary
            ]
            if len(primary) > 1:
                raise ValueError("conflicting_primary_resumes")
            # Clone only versioned context records into private staging. This also
            # avoids exposing newer document-only contracts to an installed older release.
            live = SQLRecordStore(session)
            initial = {}
            for key in [
                "candidate_configuration_v1",
                *[
                    prefix + p["id"]
                    for prefix in ("candidate_", "document_")
                    for p in plan["configuration"]["projects"]
                ],
            ]:
                value = await live.read(key)
                if value is not None:
                    initial[key] = value
            records = MemoryRecordStore(initial)
            service = CandidateContextService(records, reader=reader)
            config = await service.configuration()
            base_configuration_revision = config.revision
            desired = CandidateConfiguration.model_validate(plan["configuration"])
            if desired != config.configuration:
                config = await service.save_configuration(
                    desired,
                    expected_revision=config.revision,
                    owner_ref="owner",
                    source="owner_file",
                )
            for project in config.configuration.projects:
                facts = tuple(
                    ProjectFact.model_validate(f)
                    for f in plan["facts"].get(project.id, [])
                )
                _, knowledge = await service.build(
                    project.id,
                    expected_configuration_revision=config.revision,
                    owner_facts=facts,
                )
                snapshots.append(knowledge.candidate)
            checks = []
            answers = ApplicationAnswerService(session, settings)
            for question in plan["questions"]:
                value = await answers.generate(
                    GenerateRequest(question=question, rewrite=False, save_draft=False)
                )
                checks.append({"question": question, **value.model_dump(mode="json")})
                if value.used_llm or value.draft_id is not None:
                    raise ValueError("review_must_not_invoke_models_or_save_drafts")
            saved_profile = await CandidateProfileService(session).get_profile()
            readiness = await profile_readiness(session)
            payload = {
                "profile_version": saved_profile.version,
                "profile": saved_profile.model_dump(mode="json"),
                "resume_status": "Decryption, SHA-256 and safe PDF parsing passed. Content confirmation remains pending."
                if not resume.confirmed
                else "Already confirmed; inspect before replacing the primary.",
                "resume_sha256": resume.sha256,
                "resume_text": extracted["text"],
                "differences": plan["differences"],
                "missing_information": plan["missing_information"],
                "projects": [
                    {
                        "id": p.configuration.id,
                        "name": p.configuration.name,
                        "revision": p.revision,
                        "commit_sha": p.commit_sha,
                        "limitations": plan["limitations"].get(p.configuration.id, ""),
                        "unsupported_stack_claims": p.unsupported_stack_claims,
                        "facts": [
                            {**f.model_dump(mode="json"), "approvable": f.approvable}
                            for f in p.facts
                        ],
                    }
                    for p in snapshots
                ],
                "requests": confirmation_requests(
                    profile, resume, primary[0].id if primary else None, snapshots
                ),
                "answer_checks": checks,
                "readiness": readiness.model_dump(mode="json"),
                "primary_resume_selected": select_resume(resources).selected
                is not None,
                "staging": {
                    "database_writes": False,
                    "configuration_revision": base_configuration_revision,
                    "plan_hash": canonical_hash(plan),
                    "profile_hash": canonical_hash(
                        saved_profile.model_dump(mode="json")
                    ),
                    "projects": [p.model_dump(mode="json") for p in snapshots],
                    "project_record_revisions": {
                        p.id: initial.get(
                            ("candidate_" if p.repository_url else "document_") + p.id,
                            {},
                        ).get("revision", 0)
                        for p in desired.projects
                    },
                },
            }
            if saved_profile.version != plan["profile_version"]:
                raise ValueError("profile_changed_regenerate_review")
            review = write_private_review(output, payload, pdf_bytes=raw)
            await session.rollback()
            print(
                json.dumps(
                    {
                        "review_path": str(review),
                        "profile_version": saved_profile.version,
                        "pending_projects": len(snapshots),
                        "approvals_sent": 0,
                        "answer_statuses": [c["status"] for c in checks],
                    }
                )
            )
    finally:
        await close_db_engine()


def main():
    os.umask(0o077)
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        asyncio.run(prepare(args.env_file, args.plan, args.output))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "preparation_failed",
                    "exception_type": type(exc).__name__,
                    "details": "redacted; inspect private inputs and current revisions",
                }
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
