"""Deterministic-first application answers; every narrative remains a reviewable draft."""
import re

from pydantic import ValidationError

from backend.app.ai.answer_engine import LocalAnswerEngine
from backend.app.ai.base import ProviderError
from backend.app.ai.prompts import STYLE_INSTRUCTIONS, SYSTEM_INSTRUCTION, build_payload
from backend.app.ai.provider_factory import configured_model, create_provider
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
        self.usage = usage_manager or LLMUsageManager(get_session_factory(), self.settings)

    async def generate(self, request):
        profile = await self.repo.profile()
        if request.job_id:
            job = await JobRepository(self.repo.session).get_by_id(request.job_id)
            if job is None:
                raise ProfileNotFoundError("Job not found")
            company = await CompanyRepository(self.repo.session).get_by_id(job.company_id) if job.company_id else None
            request = request.model_copy(update={
                "company_name": request.company_name or (company.name if company else None),
                "job_description": request.job_description or job.description,
            })
        classification = ApplicationQuestionClassifier().classify(request.question)
        category = classification.question_type
        resources = await self.repo.resolution_resources(profile.id)
        resolver = ProfileLinkResolver(profile, resources, self.settings)
        result = AnswerGenerationResult(question_type=category, writing_style=request.writing_style)
        # A limit embedded in the question can only tighten the explicitly supplied API limit.
        char_match = re.search(r"\b(\d+)\s*characters?\b", request.question, re.I)
        word_match = re.search(r"\b(\d+)\s*words?\b", request.question, re.I)
        max_chars = min(request.max_characters, int(char_match[1])) if char_match else request.max_characters
        max_words = min(request.max_words or 1500, int(word_match[1])) if word_match else request.max_words
        if category in {"profile_link", "file_upload"}:
            result = resolver.resolve(request.question)
            result.writing_style = request.writing_style
        elif classification.field:
            field = classification.field
            if field in {"notice_period_days", "work_authorization", "remote_preference", "minimum_salary"}:
                value = profile.preferences.get(field)
            else:
                value = getattr(profile, field, None)
            # A generic authorization string doesn't establish sponsorship needs or a particular country.
            if category == "work_authorization" and not re.fullmatch(r"(?:what is your |your )?(?:work )?authori[sz]ation(?: status)?[?.]?", request.question, re.I):
                value = None
            if value is not None and value != []:
                answer = str(value)
                if field == "verified_skills":
                    answer = ", ".join(value)
                elif field == "education":
                    answer = "; ".join(f"{row['qualification']}, {row['institution']}" for row in value)
                elif field == "certifications":
                    answer = "; ".join(row['name'] + (f", {row['issuer']}" if row.get('issuer') else "") for row in value)
                if field == "verified_experience_years":
                    answer = f"{value:g} years"
                elif field == "notice_period_days":
                    answer = f"{value} days"
                elif field == "minimum_salary":
                    currency = profile.preferences.get("salary_currency")
                    answer = f"{value:g} {currency}" if currency else None
                if answer:
                    result.status, result.answer, result.requires_review = "draft_ready", answer, False
                    result.source, result.confidence = "candidate_profile", 1.0
                    result.evidence_references = [EvidenceReference(source_type="candidate_profile", source_id=str(profile.id))]
            if result.answer is None:
                result.missing_information = [f"Provide the exact {field.replace('_', ' ')} requested by this form"]
        elif category in {"unknown", "compensation", "work_authorization"}:
            custom = resolver.resolve(request.question)
            if custom.answer:
                result = custom
                result.writing_style = request.writing_style
            else:
                result.missing_information = ["Provide a verified fact or clarify the question; no answer can be inferred"]
        else:
            evidence = await self.repo.relevant_evidence(profile.id, request.question)
            facts = retrieve(profile, evidence, request.question, category)
            if not facts:
                result.missing_information = [self._missing(category)]
            elif category in {"motivation", "startup_interest"} and not (request.company_name and request.job_description):
                result.missing_information = ["Supply company_name and job_description, plus saved preferences explaining your interest"]
            else:
                result = await self._compose(request, category, facts, max_chars, max_words)
        if result.answer is not None and (len(result.answer) > max_chars or (max_words is not None and len(result.answer.split()) > max_words)):
            # Never truncate URLs or factual values to fit a form.
            result.answer, result.status, result.requires_review = None, "validation_failed", True
            result.error_code = "output_length_exceeded"
        if request.save_draft and result.status == "draft_ready" and result.answer:
            draft = await self.repo.save_draft(profile, request, result)
            result.draft_id = draft.id
        return result

    def _missing(self, category):
        if category in {"project_explanation", "technical_experience"}:
            return "Describe a relevant project's purpose, your actual contribution, implementation details, and (if asked) its engineering challenge and solution; confirm this evidence"
        if category in {"motivation", "startup_interest"}:
            return "Save your actual role, industry, technology or company-stage preferences explaining why this opportunity interests you"
        return "Supply a reviewed professional summary or career evidence relevant to this question"

    async def _compose(self, request, category, facts, max_chars, max_words):
        result = AnswerGenerationResult(question_type=category, writing_style=request.writing_style)
        context = {"evidence": facts}
        instructions = {"style_instruction": STYLE_INSTRUCTIONS[request.writing_style],
                        "max_characters": max_chars, "max_words": max_words,
                        "job_context": {"company_name": request.company_name, "job_description": request.job_description}}
        # local-answer-integration.v1: no provider construction or quota reservation.
        safe = await LocalAnswerEngine().answer(request.question, context, instructions,
            route="approved_summary" if category == "short_text" else "narrative",
            low_memory=True)
        if not request.rewrite or safe.content is None:
            result.source = safe.source
            result.missing_information = list(safe.missing_information)
            result.error_code = safe.error_code
            result.status = safe.status
            if safe.content:
                result.answer = safe.content.answer
                result.evidence_references = safe.content.evidence_references
                result.requires_review = True
                result.warnings = ["Extracted approved facts; review before use."]
            return result
        # Local inference remains disabled for the shared answer service.
        if self.settings.LLM_PROVIDER in {"ollama", "agy"}:
            result.status, result.error_code = "provider_unavailable", "provider_execution_not_authorized"
            return result
        result.provider, result.model = self.settings.LLM_PROVIDER, configured_model(self.settings)
        # Bound the whole provider payload, not just the question or job description.
        if len(SYSTEM_INSTRUCTION) + len(build_payload(request.question, context, instructions)) > self.settings.LLM_MAX_INPUT_CHARS:
            result.status, result.error_code = "validation_failed", "input_limit_exceeded"
            return result
        try:
            if self.settings.LLM_PROVIDER == "cohere" and not self.settings.COHERE_CANDIDATE_DATA_AUTHORIZED:
                raise ProviderError("candidate_cloud_authorization_required")
            provider = self.provider or create_provider(self.settings)
            result.used_llm = True
            response = ProviderAnswer.model_validate(await self.usage.generate(provider, request.question, context, instructions))
            result.usage = response.usage
        except ProviderError as exc:
            result.status = "validation_failed" if exc.code == "invalid_structured_response" else "provider_unavailable"
            result.error_code = exc.code
            result.used_llm = exc.attempted
            result.usage = exc.usage
            if exc.retry_after is not None:
                result.retry_after_seconds = exc.retry_after
            if exc.code in {"llm_not_configured", "unsupported_provider"}:
                result.used_llm = False
                result.missing_information = ["Configure the explicitly selected server-side cloud provider to generate narrative drafts"]
            return result
        except ValidationError:
            result.status, result.error_code = "validation_failed", "invalid_structured_response"
            return result
        error = validate_grounding(response.content, facts, max_chars, max_words)
        if error:
            result.status, result.error_code = "validation_failed", error
            return result
        result.answer, result.status = response.content.answer, "draft_ready"
        result.evidence_references = response.content.evidence_references
        result.warnings = ["Factual checks are conservative safeguards, not verification; review every narrative claim"]
        return result
