"""Conservative question routing. Unrecognized facts never reach a model."""
import re
from dataclasses import dataclass

from backend.app.ai.schemas import QuestionType
from backend.app.services.profile_link_resolver import (
    is_file_upload,
    normalize,
    resource_types,
)


@dataclass(frozen=True)
class QuestionClassification:
    question_type: QuestionType
    field: str | None = None


class ApplicationQuestionClassifier:
    def classify(self, question: str) -> QuestionClassification:
        q = normalize(question)
        if is_file_upload(q):
            return QuestionClassification("file_upload")
        if resource_types(q) and not re.search(r"\b(explain|describe|experience|built|challeng\w*|tell us|why|how did)\b", q):
            return QuestionClassification("profile_link")
        fields = [
            (r"\b(e mail|email)\b", "email"), (r"\b(phone|mobile|telephone)\b", "phone"),
            (r"\b(full name|your name)\b", "full_name"),
            (r"\b(years of (?:professional |work |total )?experience|experience (?:in )?years|total experience)\b", "verified_experience_years"),
            (r"\bnotice period\b", "notice_period_days"),
            (r"\b(?:verified |technical )?skills\b", "verified_skills"),
            (r"\btechnologies (?:have you |you have )?used\b", "verified_skills"),
            (r"\beducation(?:al background)?\b", "education"),
            (r"\bcertifications?\b", "certifications"),
            (r"\bremote (?:work )?preference\b", "remote_preference"),
        ]
        matched = [field for pattern, field in fields if re.search(pattern, q)]
        if matched:
            if re.search(r"\b(salary|compensation|ctc|sponsorship|visa|authorization|authorisation|relocation|availability)\b", q):
                return QuestionClassification("unknown")
            if len(matched) != 1 or re.search(r"\b(explain|describe|tell|why|project|using|with|in python|in java)\b", q):
                return QuestionClassification("unknown")
            return QuestionClassification("personal_details", matched[0])
        if re.search(r"\b(authorization|authorisation|visa|sponsorship|authorized to work|authorised to work|legally authorized|legally authorised|right to work)\b", q):
            return QuestionClassification("work_authorization", "work_authorization")
        if re.search(r"\b(salary|compensation|ctc|pay expectation)\b", q):
            # Minimum target is not current pay or a universal expected salary.
            return QuestionClassification("compensation", "minimum_salary" if "minimum" in q else None)
        if re.search(r"\b(project|built|build|best work|impressive thing|proudest|accomplishment)\b", q):
            return QuestionClassification("project_explanation")
        if re.search(r"\b(startup|founder|founding)\b", q) and re.search(r"\b(why|interest|join|motivat)\w*\b", q):
            return QuestionClassification("startup_interest")
        if re.search(r"\b(why|motivat\w*)\b", q):
            return QuestionClassification("motivation")
        if re.search(r"\b(technical|implemented|engineering|experience (?:with|using|in)|worked with|production issue)\b", q):
            return QuestionClassification("technical_experience")
        if re.search(r"\b(about yourself|introduce yourself|professional summary|short bio)\b", q):
            return QuestionClassification("short_text")
        return QuestionClassification("unknown")
