"""Conservative rejection checks; these are safeguards, never proof of factual accuracy."""

import re


def flat_strings(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(flat_strings(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(flat_strings(v) for v in value)
    return str(value) if value is not None else ""


def validate_grounding(content, facts, max_characters, max_words, opportunity=()):
    """Validate employer statements independently; never borrow them for applicant claims.

    Employer statements currently use complete verbatim source sentences. Mixed
    employer/applicant clauses and paraphrased employer claims require manual edit.
    This conservative boundary does not pretend to solve semantic entailment.
    """
    if not content.opportunity_claims:
        return validate_candidate(content, facts, max_characters, max_words)
    if len(content.answer) > max_characters or (
        max_words is not None and len(content.answer.split()) > max_words
    ):
        return "output_length_exceeded"
    sources = {
        (f["reference"]["source_type"], f["reference"]["source_id"]): f["facts"]
        for f in opportunity
    }
    references = {(r.source_type, r.source_id) for r in content.evidence_references}
    candidate_keys = {
        (f["reference"]["source_type"], f["reference"]["source_id"]) for f in facts
    }
    if references - sources.keys() - candidate_keys:
        return "invalid_evidence_reference"
    removed = set()
    sentences = re.split(r"(?<=[.!?])\s+|\n", content.answer)
    for claim in content.opportunity_claims:
        from backend.app.knowledge.opportunity import unsafe_instruction

        if unsafe_instruction(claim.text):
            return "unsafe_opportunity_instruction"
        key = (claim.source.source_type, claim.source.source_id)
        if key not in sources or key not in references:
            return "invalid_opportunity_reference"
        if (
            claim.text != claim.quote
            or claim.quote not in sources[key]
            or re.search(r"\b(i|my|me|we|our|you|your)\b", claim.text, re.I)
        ):
            return "unsupported_opportunity_claim"
        if claim.text not in sentences:
            return "opportunity_claim_requires_separate_sentence"
        # A quote may not remove words from the middle of an employer sentence.
        if claim.quote not in re.split(r"(?<=[.!?])\s+|\n", sources[key]):
            return "unsupported_opportunity_claim"
        removed.add(claim.text)
    candidate_answer = " ".join(s for s in sentences if s not in removed)
    candidate_references = [
        r
        for r in content.evidence_references
        if not r.source_type.startswith("opportunity_")
    ]
    if not candidate_answer or not candidate_references:
        return "candidate_evidence_required"
    candidate = content.model_copy(
        update={
            "answer": candidate_answer,
            "evidence_references": candidate_references,
            "opportunity_claims": [],
        }
    )
    # The validator below checks every candidate claim against candidate sources only.
    return validate_candidate(candidate, facts, max_characters, max_words)


def validate_candidate(content, facts, max_characters, max_words):
    answer = content.answer
    if not re.search(r"\b(?:I|my)\b", answer, re.I):
        return "first_person_required"
    if len(answer) > max_characters or (
        max_words is not None and len(answer.split()) > max_words
    ):
        return "output_length_exceeded"
    sources = {
        (f["reference"]["source_type"], f["reference"]["source_id"]): flat_strings(
            f["facts"]
        )
        for f in facts
    }
    references = {(r.source_type, r.source_id) for r in content.evidence_references}
    if not references or references - sources.keys():
        return "invalid_evidence_reference"
    selected = " ".join(sources[key] for key in references)
    for claim in content.claims:
        key = (claim.source.source_type, claim.source.source_id)
        if (
            key not in references
            or claim.quote.casefold() not in sources[key].casefold()
            or claim.text not in answer
        ):
            return "unsupported_claim"
    # Each sentence must be covered by a supplied claim; a citation alone isn't enough.
    for sentence in re.split(r"(?<=[.!?])\s+|\n", answer):
        if sentence.strip() and not any(
            sentence.strip().rstrip(".!?") in c.text for c in content.claims
        ):
            return "uncited_claim"
    # Names, dates, numbers, percentages, technology identifiers and strong impact language.
    numbers = re.findall(r"\b\d[\d,.]*(?:%|[kKmMbB])?\b", answer)
    supported_numbers = {
        n.casefold() for n in re.findall(r"\b\d[\d,.]*(?:%|[kKmMbB])?\b", selected)
    }
    if any(n.casefold() not in supported_numbers for n in numbers):
        return "unsupported_number"
    safe_words = {
        "i",
        "my",
        "the",
        "a",
        "an",
        "at",
        "in",
        "for",
        "this",
        "it",
        "we",
        "to",
        "using",
        "by",
    }
    names = re.findall(r"\b[A-Z][A-Za-z0-9+#]*(?:[.][A-Za-z]+)?\b", answer)
    if any(
        name.casefold() not in safe_words
        and not re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", selected, re.I)
        for name in names
    ):
        return "unsupported_name"
    risky = r"\b(?:led|managed|founded|scaled|increased|reduced|improved|optimized|optimised|million|billion|revenue|users|customers|awarded|promoted|passionate|expert|expertise)\b"
    if any(
        word.casefold() not in selected.casefold()
        for word in re.findall(risky, answer, re.I)
    ):
        return "unsupported_accomplishment"
    # Number words are just as capable of inventing metrics as digits.
    for word in re.findall(
        r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand)\b",
        answer,
        re.I,
    ):
        if not re.search(r"\b" + word + r"\b", selected, re.I):
            return "unsupported_number"
    # Reject novel domain vocabulary, including lowercase invented accomplishments. This
    # intentionally prefers false negatives over unsupported fluency; human review remains required.
    connective = set(
        "i my me we our a an the and or but with without to of for from on in at by as it its this that these those was were is are be been being have has had do did can could would will used use using built build worked work implemented implement implementation developed develop designed design chose choose needed need wanted want because so then when while after before through during into about also which where how what why one own contribution project solution challenge problem approach role involved focused focus helped help allowed allow made make keep kept rather than together explain part responsible personally specifically technical engineering purpose main decision decisions experience request requests service application backend".split()
    )

    def stem(word):
        for suffix in ("ing", "ed", "es", "s"):
            if word.endswith(suffix) and len(word) > len(suffix) + 3:
                return word[: -len(suffix)]
        return word

    supported = {stem(word) for word in re.findall(r"[a-z]+", selected.casefold())} | {
        stem(word) for word in connective
    }
    novel = {
        stem(word) for word in re.findall(r"[a-z]+", answer.casefold())
    } - supported
    if novel:
        return "unsupported_claim"
    return None
