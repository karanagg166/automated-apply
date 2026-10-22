"""Deterministic-first application answers; every narrative remains a reviewable draft."""

import re

from pydantic import ValidationError

from backend.app.ai.base import ProviderError
from backend.app.ai.prompts import STYLE_INSTRUCTIONS, SYSTEM_INSTRUCTION, build_payload
from backend.app.ai.schemas import (
    AnswerGenerationResult,
    EvidenceReference,
    ProviderAnswer,
)
from backend.app.ai.usage import LLMUsageManager
from backend.app.ai.validation import validate_grounding
from backend.app.core.config import get_settings
from backend.app.db.session import get_session_factory
from backend.app.repositories.candidate_knowledge import CandidateKnowledgeRepository
from backend.app.repositories.candidate_profile import ProfileNotFoundError
from backend.app.repositories.company import CompanyRepository
from backend.app.repositories.job import JobRepository
from backend.app.services.application_question_classifier import (
    ApplicationQuestionClassifier,
)
from backend.app.services.candidate_evidence_retrieval import retrieve
from backend.app.services.profile_link_resolver import ProfileLinkResolver


class ApplicationAnswerService:
    def __init__(self, session, settings=None, provider=None, usage_manager=None):
        self.repo = CandidateKnowledgeRepository(session)
        self.settings = settings or get_settings()
        self.provider = provider
        from backend.app.ai.optional_usage import OptionalUsageManager

        usage_type = (
            OptionalUsageManager
            if self.settings.LLM_PROVIDER in {"ollama", "cohere"}
            else LLMUsageManager
        )
        usage_settings = self.settings
        if provider is None and self.settings.LLM_PROVIDER == "gemini":
            usage_settings = self.settings.model_copy(
                update={
                    "LLM_MONTHLY_MAX_REQUESTS": min(
                        self.settings.LLM_MONTHLY_MAX_REQUESTS,
                        self.settings.GEMINI_APPROVED_MONTHLY_REQUESTS,
                    )
                }
            )
        self.usage = usage_manager or usage_type(get_session_factory(), usage_settings)

    async def generate(self, request):
        profile = await self.repo.profile()
        opportunity = []
        if request.job_id:
            job = await JobRepository(self.repo.session).get_by_id(request.job_id)
            if job is None:
                raise ProfileNotFoundError("Job not found")
            company = (
                await CompanyRepository(self.repo.session).get_by_id(job.company_id)
                if job.company_id
                else None
            )
            if (
                request.company_name
                and company
                and request.company_name.casefold().strip()
                != company.name.casefold().strip()
            ):
                return AnswerGenerationResult(
                    question_type="unknown",
                    status="validation_failed",
                    error_code="company_context_mismatch",
                    missing_information=[
                        "Requested company does not match the saved job; correct the context before generation"
                    ],
                )
            if (
                request.job_description
                and job.description
                and request.job_description.strip() != job.description.strip()
            ):
                return AnswerGenerationResult(
                    question_type="unknown",
                    status="validation_failed",
                    error_code="job_context_mismatch",
                    missing_information=[
                        "Requested description differs from the saved job; update and review that job first"
                    ],
                )
            request = request.model_copy(
                update={
                    "company_name": request.company_name
                    or (company.name if company else None),
                    "job_description": request.job_description or job.description,
                }
            )
            if self.settings.OPPORTUNITY_CONTEXT_ENABLED:
                from backend.app.knowledge.opportunity import reviewed_context

                opportunity = reviewed_context(job, company)
                if opportunity and not request.job_description:
                    request = request.model_copy(
                        update={"job_description": opportunity[0]["facts"]}
                    )
        classification = ApplicationQuestionClassifier().classify(request.question)
        category = classification.question_type
        resources = await self.repo.resolution_resources(profile.id)
        resolver = ProfileLinkResolver(profile, resources, self.settings)
        result = AnswerGenerationResult(
            question_type=category, writing_style=request.writing_style
        )
        # A limit embedded in the question can only tighten the explicitly supplied API limit.
        char_match = re.search(r"\b(\d+)\s*characters?\b", request.question, re.I)
        word_match = re.search(r"\b(\d+)\s*words?\b", request.question, re.I)
        max_chars = (
            min(request.max_characters, int(char_match[1]))
            if char_match
            else request.max_characters
        )
        max_words = (
            min(request.max_words or 1500, int(word_match[1]))
            if word_match
            else request.max_words
        )
        from backend.app.knowledge.facts import resolve_fact

        factual = resolve_fact(profile, request.question, category)
        if factual.handled:
            result.question_type = factual.category
            if factual.answer is not None:
                result.status, result.answer, result.requires_review = (
                    "draft_ready",
                    factual.answer,
                    False,
                )
                result.source, result.confidence = "candidate_profile", 1.0
                result.evidence_references = [
                    EvidenceReference(
                        source_type="candidate_profile", source_id=str(profile.id)
                    )
                ]
            else:
                result.missing_information = [
                    f"Provide the exact approved {factual.field} requested by this form; no value is inferred"
                ]
        elif category in {"profile_link", "file_upload"}:
            result = resolver.resolve(request.question)
            result.writing_style = request.writing_style
        elif classification.field:
            field = classification.field
            if field in {
                "notice_period_days",
                "work_authorization",
                "remote_preference",
                "minimum_salary",
            }:
                value = profile.preferences.get(field)
            else:
                value = getattr(profile, field, None)
            # A generic authorization string doesn't establish sponsorship needs or a particular country.
            if category == "work_authorization" and not re.fullmatch(
                r"(?:what is your |your )?(?:work )?authori[sz]ation(?: status)?[?.]?",
                request.question,
                re.I,
            ):
                value = None
            if value is not None and value != []:
                answer = str(value)
                if field == "verified_skills":
                    answer = ", ".join(value)
                elif field == "education":
                    answer = "; ".join(
                        f"{row['qualification']}, {row['institution']}" for row in value
                    )
                elif field == "certifications":
                    answer = "; ".join(
                        row["name"]
                        + (f", {row['issuer']}" if row.get("issuer") else "")
                        for row in value
                    )
                if field == "verified_experience_years":
                    answer = f"{value:g} years"
                elif field == "notice_period_days":
                    answer = f"{value} days"
                elif field == "minimum_salary":
                    currency = profile.preferences.get("salary_currency")
                    answer = f"{value:g} {currency}" if currency else None
                if answer:
                    result.status, result.answer, result.requires_review = (
                        "draft_ready",
                        answer,
                        False,
                    )
                    result.source, result.confidence = "candidate_profile", 1.0
                    result.evidence_references = [
                        EvidenceReference(
                            source_type="candidate_profile", source_id=str(profile.id)
                        )
                    ]
            if result.answer is None:
                result.missing_information = [
                    f"Provide the exact {field.replace('_', ' ')} requested by this form"
                ]
        elif category in {"unknown", "compensation", "work_authorization"}:
            custom = resolver.resolve(request.question)
            if custom.answer:
                result = custom
                result.writing_style = request.writing_style
            else:
                result.missing_information = [
                    "Provide a verified fact or clarify the question; no answer can be inferred"
                ]
        else:
            evidence = await self.repo.relevant_evidence(profile.id, request.question)
            facts = retrieve(profile, evidence, request.question, category)
            if opportunity and category in {"motivation", "startup_interest"}:
                # Work must be attributable to the candidate, never copied from
                # the role's desired skills. Rank existing verified projects.
                work = retrieve(
                    profile,
                    evidence,
                    request.job_description or request.question,
                    "project_explanation",
                )
                import json

                from backend.app.services.candidate_evidence_retrieval import tokens

                target_tokens = tokens(" ".join(f["facts"] for f in opportunity))
                work = [
                    f for f in work if target_tokens & tokens(json.dumps(f["facts"]))
                ]
                facts += work[:3]
                if not work:
                    facts = []
            if not facts:
                result.missing_information = [self._missing(category)]
            elif category in {"motivation", "startup_interest"} and not (
                request.company_name and request.job_description
            ):
                result.missing_information = [
                    "Supply company_name and job_description, plus saved preferences explaining your interest"
                ]
            else:
                from backend.app.knowledge.reuse import reuse

                result = (
                    await reuse(
                        self.repo.session,
                        profile,
                        request,
                        category,
                        max_chars,
                        max_words,
                        allow_opportunity=self.settings.OPPORTUNITY_CONTEXT_ENABLED,
                    )
                    if self.settings.APPROVED_ANSWER_REUSE_ENABLED
                    else None
                )
                if result is None:
                    result = await self._compose(
                        request,
                        category,
                        facts,
                        max_chars,
                        max_words,
                        opportunity
                        if category in {"motivation", "startup_interest"}
                        else [],
                    )
        if result.answer is not None and (
            len(result.answer) > max_chars
            or (max_words is not None and len(result.answer.split()) > max_words)
        ):
            # Never truncate URLs or factual values to fit a form.
            result.answer, result.status, result.requires_review = (
                None,
                "validation_failed",
                True,
            )
            result.error_code = "output_length_exceeded"
        if (
            request.save_draft
            and result.status == "draft_ready"
            and result.answer
            and not result.reused_draft_id
        ):
            draft = await self.repo.save_draft(profile, request, result)
            result.draft_id = draft.id
        return result

    def _missing(self, category):
        if category in {"project_explanation", "technical_experience"}:
            return "Describe a relevant project's purpose, your actual contribution, implementation details, and (if asked) its engineering challenge and solution; confirm this evidence"
        if category in {"motivation", "startup_interest"}:
            return "Save your actual role, industry, technology or company-stage preferences explaining why this opportunity interests you"
        return "Supply a reviewed professional summary or career evidence relevant to this question"

    async def _compose(
        self, request, category, facts, max_chars, max_words, opportunity=()
    ):
        result = AnswerGenerationResult(
            question_type=category,
            writing_style=request.writing_style,
            provider=self.settings.LLM_PROVIDER,
            model=(
                self.settings.OLLAMA_MODEL
                if self.settings.LLM_PROVIDER == "ollama"
                else self.settings.COHERE_MODEL
                if self.settings.LLM_PROVIDER == "cohere"
                else self.settings.LLM_MODEL
            ),
        )
        context = {"evidence": facts}
        instructions = {
            # URLs can carry private invitation/query tokens. Provider citations
            # use opaque source IDs; source URLs remain in protected local storage.
            "opportunity_evidence": [
                {"reference": f["reference"], "facts": f["facts"]} for f in opportunity
            ],
            "style_instruction": STYLE_INSTRUCTIONS[request.writing_style],
            "max_characters": max_chars,
            "max_words": max_words,
            "job_context": {
                "company_name": request.company_name,
                "job_description": request.job_description,
            },
        }
        # Bound the whole provider payload, not just the question or job description.
        if (
            len(SYSTEM_INSTRUCTION)
            + len(build_payload(request.question, context, instructions))
            > self.settings.LLM_MAX_INPUT_CHARS
        ):
            result.status, result.error_code = (
                "validation_failed",
                "input_limit_exceeded",
            )
            return result
        try:
            from backend.app.ai.fallback import generate

            result.used_llm = True
            call = await generate(
                self.settings,
                self.usage,
                self.provider,
                request.question,
                context,
                instructions,
            )
            response = ProviderAnswer.model_validate(call.response)
            result.provider, result.model = call.provider, call.model
            if call.fallback_from:
                result.warnings.append(
                    "Primary provider unavailable; this proposal used the explicitly enabled local Ollama fallback"
                )
            result.usage = response.usage
        except ProviderError as exc:
            result.provider = getattr(exc, "provider", result.provider)
            result.model = getattr(exc, "model", result.model)
            result.status = (
                "validation_failed"
                if exc.code == "invalid_structured_response"
                else "provider_unavailable"
            )
            result.error_code = exc.code
            result.used_llm = exc.attempted
            result.usage = exc.usage
            if exc.retry_after is not None:
                result.retry_after_seconds = exc.retry_after
            if exc.code in {"llm_not_configured", "unsupported_provider"}:
                result.used_llm = False
                result.missing_information = [
                    "Enable a configured local Ollama model or an independently authorized remote provider to generate narrative drafts"
                ]
            return result
        except ValidationError:
            result.status, result.error_code = (
                "validation_failed",
                "invalid_structured_response",
            )
            return result
        if opportunity and (
            not response.content.opportunity_claims
            or not any(
                r.source_type
                in {"verified_project", "verified_role", "candidate_evidence"}
                for r in response.content.evidence_references
            )
        ):
            result.status, result.error_code = (
                "validation_failed",
                "company_and_candidate_evidence_required",
            )
            return result
        error = validate_grounding(
            response.content, facts, max_chars, max_words, opportunity
        )
        if error:
            result.status, result.error_code = "validation_failed", error
            return result
        result.answer, result.status = response.content.answer, "draft_ready"
        result.evidence_references = response.content.evidence_references
        result.warnings.append(
            "Factual checks are conservative safeguards, not verification; review every narrative claim"
        )
        return result
