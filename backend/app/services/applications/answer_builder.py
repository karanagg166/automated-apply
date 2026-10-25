"""Map saved facts first; delegate narrative generation to the existing grounded engine."""

import re
from uuid import uuid4

from backend.app.ai.schemas import EvidenceReference, GenerateRequest
from backend.app.schemas.applications import PacketField, Provenance
from backend.app.services.application_question_classifier import (
    ApplicationQuestionClassifier,
)
from backend.app.services.applications.platforms.base import safe_url
from backend.app.services.profile_link_resolver import resource_types

CATEGORIES = {
    "profile_link": "professional_profile_url",
    "file_upload": "resume_upload",
    "project_explanation": "project_explanation",
    "technical_experience": "experience",
    "short_text": "free_text",
    "motivation": "motivation",
    "startup_interest": "motivation",
    "work_authorization": "work_authorization",
    "compensation": "salary",
}
FACT_CATEGORIES = {
    "email": "contact_information",
    "phone": "contact_information",
    "full_name": "personal_information",
    "education": "education",
    "verified_experience_years": "experience",
    "verified_skills": "technical_skills",
    "notice_period_days": "notice_period",
    "minimum_salary": "salary",
    "work_authorization": "work_authorization",
}


def value_error(field, answer):
    """Reject; never silently truncate a candidate claim, URL or choice."""
    if not answer or not answer.strip():
        return "Provide a nonblank answer"
    char_match = re.search(r"\b(\d+)\s*characters?\b", field.question, re.I)
    word_match = re.search(r"\b(\d+)\s*words?\b", field.question, re.I)
    max_chars = (
        min(field.max_characters, int(char_match[1]))
        if char_match
        else field.max_characters
    )
    max_words = (
        min(field.max_words or 1500, int(word_match[1]))
        if word_match
        else field.max_words
    )
    if len(answer) > max_chars or (
        max_words is not None and len(answer.split()) > max_words
    ):
        return (
            "Answer exceeds the form length limit; edit it without changing its meaning"
        )
    if field.options and answer not in field.options:
        return "Answer must exactly match a supplied form option"
    if field.field_type == "url" and not safe_url(answer):
        return "Provide a valid public HTTPS URL"
    return None


class AnswerBuilder:
    def __init__(self, answer_service):
        self.answer_service = answer_service

    async def build(
        self,
        question,
        job_id,
        profile,
        *,
        generate=False,
        rewrite=False,
        origin="user_provided",
        resume=None,
    ):
        classification = ApplicationQuestionClassifier().classify(question.question)
        category = question.category
        if category == "unknown":
            category = FACT_CATEGORIES.get(
                classification.field,
                CATEGORIES.get(classification.question_type, "unknown"),
            )
        field = PacketField(
            **{**question.model_dump(), "category": category},
            id=uuid4(),
            provenance=Provenance(origin=origin),
        )
        if (
            question.field_type == "file"
            or classification.question_type == "file_upload"
        ):
            field.validation_status = "file_upload_required"
            field.provenance.resolver = "manual_upload"
            field.requires_review = False
            field.missing_information = [
                "manual_resume_upload_required: select and upload the actual file on the official website"
            ]
            return field
        if profile is None:
            field.missing_information = ["Save the candidate profile first"]
            return field
        if (
            classification.question_type == "profile_link"
            and resource_types(question.question) == {"resume"}
            and resume is not None
        ):
            if resume.selected:
                field.provenance = Provenance(
                    origin=origin,
                    source="candidate_resource",
                    resolver="deterministic",
                    resource_id=resume.selected.resource_id,
                )
                error = value_error(field, resume.selected.url)
                if error:
                    field.validation_status, field.missing_information = (
                        "validation_failed",
                        [error],
                    )
                else:
                    field.proposed_answer = field.effective_answer = resume.selected.url
                    field.validation_status, field.requires_review = (
                        "draft_ready",
                        False,
                    )
            else:
                field.missing_information = [resume.reason]
            return field
        narrative = classification.question_type in {
            "project_explanation",
            "technical_experience",
            "short_text",
            "motivation",
            "startup_interest",
        }
        if narrative and not generate:
            field.provenance.resolver = "grounded_answer_service"
            field.missing_information = [
                "Generate a grounded draft explicitly or enter your own factual answer, then review it"
            ]
            return field
        request = GenerateRequest(
            question=question.question,
            job_id=job_id,
            writing_style=question.writing_style,
            max_characters=max(20, question.max_characters),
            max_words=question.max_words,
            # Preserve existing ApplicationAnswerDraft records for generated narratives.
            save_draft=generate and narrative,
            rewrite=rewrite,
        )
        if question.constraints and narrative and generate:
            request.question = (
                question.question + "\nForm constraints: " + question.constraints
            )
            if len(request.question) > 2000:
                field.validation_status = "validation_failed"
                field.missing_information = [
                    "Combined question and constraints exceed the supported input limit"
                ]
                return field
        result = await self.answer_service.generate(request)
        # Environment-only defaults have not been confirmed by the candidate.
        if result.source == "environment_default":
            field.missing_information = [
                "Confirm and save this profile link before using it in an application"
            ]
            return field
        field.validation_status = result.status
        field.missing_information = result.missing_information
        field.requires_review = narrative or result.requires_review
        field.proposed_answer = result.answer
        field.provenance = Provenance(
            origin=origin,
            source=result.provider
            if result.used_llm and result.answer
            else (
                result.source
                if result.source in {"candidate_profile", "candidate_resource", "deterministic_extractive"}
                else "missing"
            ),
            resolver="grounded_answer_service" if narrative else "deterministic",
            evidence_references=result.evidence_references,
            answer_draft_id=result.draft_id,
            provider=result.provider,
            model=result.model,
            error_code=result.error_code,
        )
        if (
            result.answer
            and result.source == "candidate_profile"
            and not field.provenance.evidence_references
        ):
            field.provenance.evidence_references = [
                EvidenceReference(
                    source_type="candidate_profile", source_id=str(profile.id)
                )
            ]
        if result.error_code and not field.missing_information:
            field.missing_information = [
                f"Answer generation requires attention: {result.error_code}; correct inputs/configuration or supply and review a factual answer"
            ]
        if result.answer:
            error = value_error(field, result.answer)
            if error:
                field.proposed_answer, field.validation_status = (
                    None,
                    "validation_failed",
                )
                field.missing_information = [error]
        field.effective_answer = field.proposed_answer
        return field
