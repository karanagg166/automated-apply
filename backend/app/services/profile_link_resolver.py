"""Deterministic links with explicit provenance; no downloads and no model calls."""
import re

from pydantic import TypeAdapter, ValidationError

from backend.app.ai.schemas import AnswerGenerationResult
from backend.app.core.config import Settings
from backend.app.core.text import normalize, phrase_in
from backend.app.core.urls import PublicHTTPSURL
from backend.app.repositories.candidate_knowledge import STANDARD_FIELDS
from backend.app.schemas.candidate_resources import ResolvedLink

ALIASES = {
    "github": ("github", "git hub"), "linkedin": ("linkedin", "linked in"),
    "portfolio": ("portfolio", "personal website"), "resume": ("resume", "résumé", "cv", "curriculum vitae"),
    "leetcode": ("leetcode", "leet code"), "codeforces": ("codeforces", "code forces"),
    "geeksforgeeks": ("geeksforgeeks", "geeks for geeks", "gfg"),
    "hackerrank": ("hackerrank", "hacker rank"), "kaggle": ("kaggle",),
}
ENV_FIELDS = {
    "resume": "CANDIDATE_RESUME_DRIVE_URL", "github": "CANDIDATE_GITHUB_URL",
    "linkedin": "CANDIDATE_ORIGINAL_LINKEDIN_URL", "portfolio": "CANDIDATE_PORTFOLIO_URL",
    "leetcode": "CANDIDATE_LEETCODE_URL", "codeforces": "CANDIDATE_CODEFORCES_URL",
    "geeksforgeeks": "CANDIDATE_GFG_URL", "hackerrank": "CANDIDATE_HACKERRANK_URL",
}


def resource_types(question):
    return {kind for kind, aliases in ALIASES.items() if any(phrase_in(alias, question) for alias in aliases)}


def is_file_upload(question):
    return bool(re.search(r"\b(upload|attach|attachment|browse file|choose file|select file)\b", normalize(question)))


class ProfileLinkResolver:
    def __init__(self, profile, resources, settings: Settings):
        self.profile, self.resources, self.settings = profile, resources, settings

    def _valid(self, url):
        try:
            return str(TypeAdapter(PublicHTTPSURL).validate_python(url))
        except ValidationError:
            return None

    def resolved(self, kind):
        if kind in STANDARD_FIELDS and self.profile is not None:
            saved = getattr(self.profile, STANDARD_FIELDS[kind])
            if saved is not None:
                return ResolvedLink(resource_type=kind, url=self._valid(saved), source="candidate_profile", user_confirmed=True)
        items = [r for r in self.resources if r.resource_type == kind and r.user_confirmed]
        primary = [r for r in items if r.is_primary]
        if len(primary) == 1 or len(items) == 1:
            item = (primary or items)[0]
            return ResolvedLink(resource_type=kind, url=self._valid(item.url), source="candidate_resource", resource_id=item.id, user_confirmed=True)
        # Persisted but unconfirmed/ambiguous data must not be masked by defaults.
        if any(r.resource_type == kind for r in self.resources):
            return ResolvedLink(resource_type=kind)
        # Once an edited profile clears a standard field, do not resurrect its env default.
        if kind in STANDARD_FIELDS and self.profile is not None and self.profile.version > 1:
            return ResolvedLink(resource_type=kind)
        default = getattr(self.settings, ENV_FIELDS.get(kind, ""), None)
        return ResolvedLink(resource_type=kind, url=str(default) if default else None,
                            source="environment_default" if default else None)

    def resolve(self, question):
        kinds = resource_types(question)
        result = AnswerGenerationResult(question_type="profile_link")
        if is_file_upload(question):
            result.question_type, result.status = "file_upload", "file_upload_required"
            result.resources = [{"id": str(r.id), "label": r.label, "url": r.url,
                                 "user_confirmed": r.user_confirmed, "accessibility": "not_checked"}
                                for r in self.resources if r.resource_type == "resume"][:100]
            link = self.resolved("resume")
            if not result.resources and link.url:
                result.resources = [{"url": link.url, "source": link.source, "accessibility": "not_checked"}]
            result.missing_information = ["Select and upload an actual file in the application form; no file was uploaded"]
            return result
        # Narrative/compound prompts must not be mistaken for an exact link question.
        if re.search(r"\b(explain|describe|experience|built|challeng\w*|tell us|why|how did)\b", normalize(question)):
            result.missing_information = ["This question requires more than a saved profile link"]
            return result
        generic_labels = {normalize(alias) for aliases in ALIASES.values() for alias in aliases}
        label_matches = [r for r in self.resources if r.user_confirmed and
                         normalize(r.label) not in generic_labels and phrase_in(r.label, question)]
        if len(kinds) > 1:
            result.missing_information = ["Ask for one resource type at a time"]
            return result
        if label_matches:
            matches = [r for r in label_matches if not kinds or r.resource_type in kinds]
            if len(matches) == 1:
                item = matches[0]
                url = self._valid(item.url)
                if url:
                    result.answer, result.source, result.confidence = url, "candidate_resource", 1.0
                    result.status, result.requires_review = "draft_ready", False
                    return result
            result.missing_information = ["Several resources match this label; specify a unique resource label"]
            return result
        if re.search(r"\b(projects?|repo|repositories|repository|username|email|phone|notice|salary)\b", normalize(question)):
            result.missing_information = ["Specify one profile URL or an exact saved resource label; this question asks for additional facts"]
            return result
        if len(kinds) != 1:
            result.missing_information = ["Specify a saved resource type or its exact label"]
            return result
        kind = next(iter(kinds))
        link = self.resolved(kind)
        if link.url:
            result.answer, result.source = link.url, link.source
            result.status = "draft_ready"
            result.confidence = 1.0 if link.user_confirmed else 0.75
            result.requires_review = not link.user_confirmed
        else:
            result.missing_information = [f"{kind.title()} profile URL has not been configured, confirmed, or uniquely selected"]
        return result
