"""Persistent setup/project review and approved-only answer selection.

This is a module API, not a registered HTTP/Telegram capability. The caller must
authenticate the owner and commit the injected store transaction explicitly.
"""

import re
from collections.abc import Callable
from datetime import datetime
from typing import Literal

from pydantic import Field

from backend.app.candidate_context.common import (
    ContextError,
    Contract,
    aware,
    canonical_hash,
    utc_now,
)
from backend.app.candidate_context.configuration import (
    CandidateConfiguration,
    configuration_change,
)
from backend.app.candidate_context.persistence import RecordStore
from backend.app.candidate_context.projects import (
    ProjectApproval,
    ProjectFact,
    ProjectSnapshot,
    compact,
    contexts,
)
from backend.app.candidate_context.repository import RepositoryReader, extract_project

CONFIGURATION_KEY = "candidate_configuration_v1"


class ConfigurationRecord(Contract):
    revision: int = 0
    configuration: CandidateConfiguration = Field(
        default_factory=CandidateConfiguration
    )
    audits: tuple[dict, ...] = ()


class ProjectKnowledge(Contract):
    revision: int = 0
    candidate: ProjectSnapshot | None = None
    approved: ProjectApproval | None = None
    history: tuple[ProjectApproval, ...] = Field(default=(), max_length=50)
    last_checked_commit: str | None = None
    built_at: str | None = None
    audits: tuple[dict, ...] = ()


class ApprovedResumeFact(Contract):
    text: str = Field(min_length=1, max_length=2000)
    evidence: str = Field(min_length=1, max_length=240)
    version_id: str = Field(min_length=1, max_length=80)
    fact_generation: int = Field(ge=1)
    owner_confirmed: Literal[True]


class ContextAnswer(Contract):
    text: str
    sources: tuple[dict, ...]
    generator: Literal["deterministic_extractive"] = "deterministic_extractive"
    status: Literal["draft_requires_review", "missing_approved_context"]


def audit(kind, before, after, owner_ref, now):
    return {
        "kind": kind,
        "before_hash": canonical_hash(before),
        "after_hash": canonical_hash(after),
        "actor_ref": owner_ref,
        "created_at": aware(now).isoformat(),
    }


def project_key(project_id: str) -> str:
    if not re.fullmatch(r"project-[a-z0-9][a-z0-9-]{0,30}", project_id):
        raise ContextError("invalid_project_id")
    return "candidate_" + project_id


class CandidateContextService:
    def __init__(
        self,
        records: RecordStore,
        *,
        reader: RepositoryReader | None = None,
        clock: Callable[[], datetime] = utc_now,
    ):
        self.records, self.reader, self.clock = records, reader, clock

    async def configuration(self) -> ConfigurationRecord:
        value = await self.records.read(CONFIGURATION_KEY)
        return (
            ConfigurationRecord.model_validate(value)
            if value
            else ConfigurationRecord()
        )

    async def save_configuration(
        self,
        configuration: CandidateConfiguration,
        *,
        expected_revision: int,
        owner_ref: str,
        source: Literal[
            "owner_dashboard", "private_environment", "owner_file"
        ] = "owner_dashboard",
    ) -> ConfigurationRecord:
        previous = await self.configuration()
        if previous.revision != expected_revision:
            raise ContextError("configuration_changed_reload")
        change = configuration_change(
            previous.configuration, configuration, source=source, actor_ref=owner_ref
        )
        if not change.changed_fields:
            return previous
        if len(previous.audits) >= 100:
            raise ContextError("configuration_audit_archive_required")
        event = {
            **change.model_dump(mode="json"),
            "created_at": aware(self.clock()).isoformat(),
        }
        current = ConfigurationRecord(
            revision=previous.revision + 1,
            configuration=configuration,
            audits=(*previous.audits, event),
        )
        await self.records.compare_and_swap(
            CONFIGURATION_KEY, previous.revision, current.model_dump(mode="json")
        )
        return current

    async def project(self, project_id: str) -> ProjectKnowledge:
        value = await self.records.read(project_key(project_id))
        return ProjectKnowledge.model_validate(value) if value else ProjectKnowledge()

    async def _save_project(
        self, project_id: str, previous: ProjectKnowledge, **changes
    ) -> ProjectKnowledge:
        value = ProjectKnowledge.model_validate(
            {**previous.model_dump(), **changes, "revision": previous.revision + 1}
        )
        await self.records.compare_and_swap(
            project_key(project_id), previous.revision, value.model_dump(mode="json")
        )
        return value

    async def build(
        self,
        project_id: str,
        *,
        expected_configuration_revision: int,
        owner_facts: tuple[ProjectFact, ...] = (),
    ) -> tuple[str, ProjectKnowledge]:
        config = await self.configuration()
        if config.revision != expected_configuration_revision:
            raise ContextError("configuration_changed_reload")
        project = next(
            (p for p in config.configuration.projects if p.id == project_id), None
        )
        if not project or not project.name or not project.repository_url:
            raise ContextError("project_name_and_repository_required")
        if self.reader is None:
            raise ContextError("authorized_repository_reader_required")
        source = await self.reader.snapshot(project)
        candidate = extract_project(project, source, owner_facts=owner_facts)
        previous = await self.project(project_id)
        # Revalidate setup after slow IO: never approve a snapshot against changed config.
        if (await self.configuration()).revision != config.revision:
            raise ContextError("configuration_changed_reload")
        old = previous.candidate
        # A commit containing only unrelated file changes needs no summary rebuild.
        unchanged = (
            old
            and old.source_hash == candidate.source_hash
            and old.configuration == candidate.configuration
        )
        if unchanged and old is not None:
            old_owner = [
                f.model_dump(mode="json", exclude={"id"})
                for f in old.facts
                if f.verification == "owner_supplied"
            ]
            new_owner = [
                f.model_dump(mode="json", exclude={"id"})
                for f in candidate.facts
                if f.verification == "owner_supplied"
            ]
            unchanged = old_owner == new_owner
        if unchanged:
            if previous.last_checked_commit == source.commit_sha:
                return "unchanged", previous
            return "unchanged", await self._save_project(
                project_id, previous, last_checked_commit=source.commit_sha
            )
        event = audit(
            "project_context_built", old, candidate, "static_extractor", self.clock()
        )
        if len(previous.audits) >= 100:
            raise ContextError("project_audit_archive_required")
        current = await self._save_project(
            project_id,
            previous,
            candidate=candidate,
            last_checked_commit=source.commit_sha,
            built_at=aware(self.clock()).isoformat(),
            audits=(*previous.audits, event),
        )
        return "pending_review", current

    async def approve(
        self,
        project_id: str,
        *,
        expected_revision: str,
        fact_ids: tuple[str, ...],
        owner_ref: str,
        owner_confirmed: bool,
    ) -> ProjectApproval:
        if not owner_confirmed or not owner_ref or len(owner_ref) > 120:
            raise ContextError("explicit_owner_review_required")
        previous = await self.project(project_id)
        candidate = previous.candidate
        config = (await self.configuration()).configuration
        current_config = next((p for p in config.projects if p.id == project_id), None)
        if (
            not candidate
            or candidate.revision != expected_revision
            or candidate.configuration != current_config
        ):
            raise ContextError("project_changed_rebuild_and_review")
        selected = tuple(dict.fromkeys(fact_ids))
        if not selected or len(selected) > 100:
            raise ContextError("select_supported_project_facts")
        by_id = {fact.id: fact for fact in candidate.facts}
        if any(fact_id not in by_id for fact_id in selected):
            raise ContextError("fact_selection_not_in_current_revision")
        facts = tuple(by_id[fact_id] for fact_id in selected)
        if any(not fact.approvable for fact in facts):
            raise ContextError("inferred_or_unevidenced_claim_cannot_be_approved")
        if (
            previous.approved
            and previous.approved.revision == expected_revision
            and previous.approved.fact_ids == selected
        ):
            return previous.approved
        if len(previous.history) >= 50 or len(previous.audits) >= 100:
            raise ContextError("project_history_archive_required")
        approved = ProjectApproval(
            project_id=project_id,
            revision=candidate.revision,
            commit_sha=candidate.commit_sha,
            fact_ids=selected,
            owner_ref=owner_ref,
            approved_at=aware(self.clock()).isoformat(),
            facts=facts,
            contexts=contexts(facts),
        )
        history = (
            (*previous.history, previous.approved)
            if previous.approved
            else previous.history
        )
        event = audit(
            "project_context_approved",
            previous.approved,
            approved,
            owner_ref,
            self.clock(),
        )
        await self._save_project(
            project_id,
            previous,
            approved=approved,
            history=history,
            audits=(*previous.audits, event),
        )
        return approved

    async def approved_projects(self) -> tuple[tuple[ProjectApproval, int], ...]:
        configuration = (await self.configuration()).configuration
        result = []
        for project in configuration.projects:
            knowledge = await self.project(project.id)
            candidate, approved = knowledge.candidate, knowledge.approved
            if (
                candidate
                and approved
                and candidate.revision == approved.revision
                and project == candidate.configuration
            ):
                result.append((approved, project.priority))
        return tuple(result)

    async def answer(
        self,
        question: str,
        *,
        project_rank: int | None = None,
        max_words: int = 100,
        max_characters: int = 2000,
        resume_facts: tuple[ApprovedResumeFact, ...] = (),
        current_resume_version: str | None = None,
        current_fact_generation: int | None = None,
    ) -> ContextAnswer:
        if not isinstance(question, str) or not 1 <= len(question) <= 2000:
            raise ContextError("invalid_question")
        if not 1 <= max_words <= 500 or not 1 <= max_characters <= 8000:
            raise ContextError("invalid_compaction_limit")
        if project_rank is not None and not 1 <= project_rank <= 30:
            raise ContextError("invalid_project_rank")
        projects = sorted(await self.approved_projects(), key=lambda pair: pair[1])
        if project_rank is not None:
            projects = projects[project_rank - 1 : project_rank]
        terms = set(re.findall(r"[\w+#.]+", question.casefold())) - {
            "describe",
            "explain",
            "tell",
            "what",
            "was",
            "the",
            "a",
            "an",
            "my",
            "your",
            "you",
            "me",
            "about",
            "with",
            "most",
            "important",
            "project",
            "experience",
            "best",
            "built",
            "why",
            "should",
            "we",
            "hire",
        }

        def relevance(pair):
            approval, priority = pair
            text = " ".join(fact.text for fact in approval.facts).casefold()
            score = sum(
                3 if fact.technology and fact.technology.casefold() in terms else 0
                for fact in approval.facts
            )
            score += sum(term in text for term in terms)
            return -score, priority

        projects.sort(key=relevance)
        facts: list[str] = []
        sources: list[dict] = []
        if projects:
            approval = projects[0][0]
            ordered = sorted(
                approval.facts,
                key=lambda fact: -sum(term in fact.text.casefold() for term in terms),
            )
            facts.extend(fact.text for fact in ordered)
            sources.append(
                {
                    "project_id": approval.project_id,
                    "revision": approval.revision,
                    "commit_sha": approval.commit_sha,
                    "fact_ids": [fact.id for fact in ordered],
                    "evidence": [
                        ref.model_dump(mode="json")
                        for fact in ordered
                        for ref in fact.evidence
                    ],
                }
            )
        valid_resume = [
            fact
            for fact in resume_facts
            if fact.version_id == current_resume_version
            and fact.fact_generation == current_fact_generation
        ]
        valid_resume.sort(
            key=lambda fact: -sum(term in fact.text.casefold() for term in terms)
        )
        for fact in valid_resume:
            facts.append(fact.text)
            sources.append(
                {
                    "resume_version_id": fact.version_id,
                    "fact_generation": fact.fact_generation,
                    "evidence": fact.evidence,
                }
            )
        if not facts:
            return ContextAnswer(
                text=compact(
                    "No current approved candidate context is available. Review project and resume facts in the dashboard.",
                    max_words=max_words,
                    max_characters=max_characters,
                ),
                sources=(),
                status="missing_approved_context",
            )
        return ContextAnswer(
            text=compact(
                " ".join(facts), max_words=max_words, max_characters=max_characters
            ),
            sources=tuple(sources),
            status="draft_requires_review",
        )


class TelegramKnowledgeAdapter:
    """Matches Agent 1's ApprovedKnowledge protocol; caller supplies transaction."""

    def __init__(self, service: CandidateContextService):
        self.service = service

    async def answer(
        self,
        question: str,
        *,
        project_rank: int | None = None,
        max_words: int = 100,
        max_characters: int = 2000,
    ) -> dict:
        value = await self.service.answer(
            question,
            project_rank=project_rank,
            max_words=max_words,
            max_characters=max_characters,
        )
        return value.model_dump(mode="json")
