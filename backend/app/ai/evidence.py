"""Closed-language evidence preparation. No model, network or profile mutation.

Only reviewed evidence supplied by the caller belongs here. Unknown fields are
not evidence. Matching vocabulary alone cannot prove entailment: the rewriter
must use a complete permitted sentence, including its original subject/negation.
"""

import re
from dataclasses import dataclass

from pydantic import ValidationError

from backend.app.ai.schemas import EvidenceReference, ModelAnswer, SupportedClaim
from backend.app.ai.validation import validate_grounding

MAX_FACTS = 6
MAX_CLAUSES = 8
MAX_PREPARATION_CHARS = 12000
FIELDS = ("summary", "description", "purpose", "contribution", "notes", "content",
          "highlight", "engineering_challenges", "solutions", "technologies", "stack")
INJECTION = re.compile(
    r"ignore\s|instructions?|system\s|execute[_ ]|https?://|print\s|disclose\s|"
    r"override\s|call\s.*tool|rules?|sentinel|INJECTION_", re.IGNORECASE,
)


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n", text) if s.strip()]


@dataclass(frozen=True)
class Clause:
    text: str
    quote: str
    source: EvidenceReference

    @property
    def variants(self):
        variants = [self.text]
        if self.text.startswith("My project uses ") and self.text.endswith("."):
            variants.append("My project is using " + self.text[len("My project uses "):])
        return tuple(variants)


@dataclass(frozen=True)
class PreparedEvidence:
    clauses: tuple[Clause, ...] = ()
    missing: tuple[str, ...] = ()
    error: str | None = None
    sentence_count: int | None = None


def prepare_evidence(question, context, instructions):
    """Select one relevant source; preserve whole facts and exact source quotes.

    Deliberately narrow v1: opaque/non-narrative facts require approved sentences
    upstream. This never infers decisions, achievements, scale or personal roles.
    """
    import json

    if len(question) > 2000 or len(json.dumps(context)) > MAX_PREPARATION_CHARS:
        return PreparedEvidence(error="input_size_exceeded")
    evidence = context.get("evidence", [])
    if not isinstance(evidence, list) or len(evidence) > MAX_FACTS:
        return PreparedEvidence(error="invalid_evidence")
    count_match = re.search(r"\b(two|three|[1-8]) sentences?\b", question, re.IGNORECASE)
    count = None
    if count_match:
        token = count_match[1].lower()
        count = {"two": 2, "three": 3}[token] if token in {"two", "three"} else int(token)
    requirements = []
    for pattern, topic in ((r"\busers?\b", "users"), (r"\brevenue\b", "revenue"),
                           (r"\b(?:awards?|achievements?)\b", "achievement"),
                           (r"\b(?:salary|compensation)\b", "salary"),
                           (r"\bteam\s+size\b", "team size"),
                           (r"\blatency\b", "latency"),
                           (r"\b(?:challenge|challenges|challenging|bug|bugs|failure)\b", "challenge"),
                           (r"\bAPIs?\b", "API"),
                           (r"\b(?:why|decision|decisions)\b", "decision")):
        if re.search(pattern, question, re.IGNORECASE):
            requirements.append(topic)
    candidates = []
    query = set(re.findall(r"[a-z0-9]+", question.casefold()))
    for fact in evidence:
        try:
            reference = EvidenceReference.model_validate(fact["reference"])
            data = fact["facts"]
            if not isinstance(data, dict):
                continue
            data = data.get("project", data)
            if not isinstance(data, dict):
                continue
        except (KeyError, TypeError, ValidationError):
            return PreparedEvidence(error="invalid_evidence_reference")
        clauses = []
        for field in FIELDS:
            value = data.get(field)
            if not isinstance(value, str) or INJECTION.search(value):
                continue
            for quote in sentences(value):
                # No synthesized ownership from a bare technology/skill list.
                if len(quote) > 4000 or not re.search(r"\b(?:I|my)\b", quote, re.IGNORECASE):
                    continue
                clause = Clause(quote, quote, reference)
                if clause.text not in {c.text for c in clauses}:
                    clauses.append(clause)
        if clauses:
            name = data.get("name", "")
            score = len(query & set(re.findall(r"[a-z0-9]+", " ".join(c.text for c in clauses).casefold())))
            if isinstance(name, str) and name and name.casefold() in question.casefold():
                score += 100
            candidates.append((score, clauses))
    if not candidates:
        return PreparedEvidence(missing=("Provide approved first-person facts for the requested answer.",))
    clauses = max(candidates, key=lambda row: row[0])[1]
    # Exact topics are intentionally conservative; a related project isn't a count.
    def covers(topic, clause):
        pattern = {"challenge": r"\b(?:challeng\w*|bugs?|failure)\b", "API": r"\bAPIs?\b",
                   "decision": r"\b(?:decision|tradeoff|trade-off)\b"}.get(topic, r"\b" + topic + r"\b")
        return re.search(pattern, clause.text, re.IGNORECASE)

    missing = tuple(f"Provide approved {topic} information." for topic in requirements
                    if not any(covers(topic, c) for c in clauses))
    if missing:
        return PreparedEvidence(missing=missing)
    if "users" in requirements and not any(re.search(r"\b\d+\b.*\busers\b", c.text, re.IGNORECASE) for c in clauses):
        return PreparedEvidence(missing=("Provide an approved numeric user count.",))
    if requirements:
        clauses = [c for c in clauses if any(covers(t, c) for t in requirements)]
    # Stack extraction and skill-specific explanations omit unrelated facts.
    if re.search(r"\b(?:stack|technologies)\b", question, re.IGNORECASE) and not re.search(r"features|describe|summary", question, re.IGNORECASE):
        clauses = [c for c in clauses if re.search(r"\b(?:uses?|using|stack|technologies)\b", c.text, re.IGNORECASE)]
    selected = []
    for clause in clauses[:MAX_CLAUSES]:
        answer = " ".join(c.text for c in [*selected, clause])
        if len(answer) <= instructions["max_characters"] and (
            instructions.get("max_words") is None or len(answer.split()) <= instructions["max_words"]
        ):
            selected.append(clause)
        if count and len(selected) == count:
            break
    if not selected or (count and len(selected) != count):
        return PreparedEvidence(error="output_constraints_unsatisfied")
    return PreparedEvidence(tuple(selected), sentence_count=count)


def match_answer(answer, prepared, facts, instructions):
    """Construct provenance from exact permitted clauses, then use unchanged guard.

    A rewrite may reorder facts or use a narrow pre-proven template. Token overlap,
    invented quotes, extra clauses and changing who did what never pass this layer.
    """
    parts = sentences(answer)
    if prepared.error or prepared.missing or not prepared.clauses:
        return None, "evidence_not_prepared"
    if len(parts) != len(prepared.clauses):
        return None, "sentence_count_mismatch" if prepared.sentence_count else "clause_coverage_mismatch"
    remaining = list(prepared.clauses)
    claims = []
    for part in parts:
        match = next((c for c in remaining if part in c.variants), None)
        if match is None:
            return None, "unpermitted_clause"
        remaining.remove(match)
        claims.append(SupportedClaim(text=part, source=match.source, quote=match.quote))
    references = list({(c.source.source_type, c.source.source_id): c.source for c in claims}.values())
    content = ModelAnswer(answer=answer, claims=claims, evidence_references=references)
    error = validate_grounding(content, facts, instructions["max_characters"], instructions.get("max_words"))
    return (None, error) if error else (content, None)
