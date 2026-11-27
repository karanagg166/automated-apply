"""Multi-resume picker (Phase 6A): the best-matching local PDF for each JD.

`candidate_profiles.preferences.resume_files` maps a variant label to a local PDF,
either as a plain path or `{"path": ..., "keywords": [...], "primary": true}`:

    {"backend": "~/Resumes/backend.pdf",
     "fullstack": {"path": "~/Resumes/fullstack.pdf", "keywords": ["react", "next.js"]},
     "ai": "~/Resumes/ai.pdf"}

Selection is deterministic (no LLM): whole-word keyword hits in the title (x3) and JD,
using built-in keyword sets for common labels plus the owner's own keywords. Ties
and zero-signal JDs fall back to the unique `primary` variant, then `default`, then
MAIL_DRAFT_RESUME_PATH. Mirrors services/applications/resume_selector.py: only a
confirmed (here: existing, readable, <= 5 MB, %PDF-) file is ever selected; a link
is never treated as bytes. The same PDF is attached to the job's Gmail draft.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.browser_v2.rules import contains_term, normalize_text

LABEL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "backend": ("backend", "back end", "api", "apis", "microservices", "fastapi", "django", "flask", "node.js",
                "golang", "go", "java", "spring", "postgres", "postgresql", "sql", "redis", "kafka",
                "distributed systems"),
    "fullstack": ("full stack", "fullstack", "react", "next.js", "nextjs", "typescript", "frontend", "node.js",
                  "mern", "vue", "angular"),
    "frontend": ("frontend", "front end", "react", "next.js", "css", "ui", "typescript", "javascript"),
    "ai": ("ai", "ml", "machine learning", "llm", "llms", "genai", "generative ai", "nlp", "pytorch",
           "tensorflow", "rag", "langchain", "langgraph", "deep learning", "computer vision", "agents"),
    "data": ("data engineer", "etl", "spark", "airflow", "dbt", "warehouse", "analytics", "pandas"),
    "devops": ("devops", "sre", "kubernetes", "docker", "terraform", "aws", "gcp", "azure", "ci cd"),
    "mobile": ("android", "ios", "kotlin", "swift", "flutter", "react native"),
}
ALIASES = {"full_stack": "fullstack", "full-stack": "fullstack", "ml": "ai", "genai": "ai", "fe": "frontend",
           "be": "backend", "sre": "devops",
           # Milestone 2: the owner's variant names (default / backend / fullstack / ai_ml ...).
           "ai_ml": "ai", "ai-ml": "ai", "aiml": "ai", "ml_ai": "ai", "machine_learning": "ai", "llm": "ai",
           "back_end": "backend", "back-end": "backend", "front_end": "frontend", "front-end": "frontend",
           "data_engineering": "data"}


@dataclass(frozen=True)
class ResumeChoice:
    label: str | None
    path: str | None
    score: int
    reason: str


def _variants(resume_files: Mapping[str, Any]) -> list[tuple[str, str, tuple[str, ...], bool]]:
    variants: list[tuple[str, str, tuple[str, ...], bool]] = []
    for label, value in (resume_files or {}).items():
        if not isinstance(label, str):
            continue
        path: str | None = None
        keywords: tuple[str, ...] = ()
        primary = False
        if isinstance(value, str):
            path = value
        elif isinstance(value, Mapping):
            raw = value.get("path")
            path = raw if isinstance(raw, str) else None
            keywords = tuple(k for k in value.get("keywords") or () if isinstance(k, str) and k.strip())
            primary = value.get("primary") is True
        if path and path.strip():
            variants.append((label, str(Path(path.strip()).expanduser()), keywords, primary))
    return variants


def _usable(path: str) -> bool:
    from backend.app.mail_v2.message import resume_attachment

    found, _ = resume_attachment(path)
    return found is not None


def score_variant(label: str, keywords: tuple[str, ...], title: str | None, description: str | None) -> int:
    canonical = ALIASES.get(label.lower(), label.lower())
    terms = (*LABEL_KEYWORDS.get(canonical, ()), *keywords)
    title_text, jd_text = normalize_text(title), normalize_text(description)
    score = 0
    for term in dict.fromkeys(t.lower() for t in terms):
        if contains_term(title_text, term):
            score += 3
        if jd_text and contains_term(jd_text, term):
            score += 1
    return score


def pick_resume(resume_files: Mapping[str, Any] | None, *, title: str | None, description: str | None,
                fallback_path: str | None = None, check_files: bool = True) -> ResumeChoice:
    usable = [(label, path, keywords, primary) for label, path, keywords, primary in _variants(resume_files or {})
              if not check_files or _usable(path)]
    if usable:
        scored = sorted(((score_variant(label, keywords, title, description), label, path, primary)
                         for label, path, keywords, primary in usable), key=lambda item: -item[0])
        best = scored[0]
        tied = [item for item in scored if item[0] == best[0]]
        if best[0] > 0 and len(tied) == 1:
            return ResumeChoice(best[1], best[2], best[0], "best_keyword_match")
        pool = tied if best[0] > 0 else scored
        primaries = [item for item in pool if item[3]]
        if len(primaries) == 1:
            return ResumeChoice(primaries[0][1], primaries[0][2], primaries[0][0], "primary_variant")
        default = next((item for item in pool if item[1].lower() == "default"), None)
        if default is not None:
            return ResumeChoice(default[1], default[2], default[0], "default_variant")
        if len(usable) == 1:
            return ResumeChoice(best[1], best[2], best[0], "only_variant")
        if best[0] > 0:
            return ResumeChoice(pool[0][1], pool[0][2], pool[0][0], "first_tied_variant")
    if fallback_path and (not check_files or _usable(fallback_path)):
        return ResumeChoice(None, str(Path(fallback_path).expanduser()), 0, "fallback_resume_path")
    if usable:
        label, path, _, _ = usable[0]
        return ResumeChoice(label, path, 0, "no_signal_first_variant")
    return ResumeChoice(None, None, 0, "no_resume_configured")


def variant_used(answers: Any, *, uploaded_fallback: str | None = None) -> str | None:
    """`resume_variant_used` for a receipt: the label of the PDF the filler uploaded (answers entries
    with source "resume_picker" carry it as "variant"), else `uploaded_fallback`."""
    for answer in answers or ():
        if isinstance(answer, Mapping) and answer.get("source") == "resume_picker":
            return str(answer.get("variant") or answer.get("answer") or "") or uploaded_fallback
    return uploaded_fallback
