"""Injected fictional provider for local demonstrations; never performs inference/HTTP."""

from backend.app.ai.schemas import (
    EvidenceReference,
    ModelAnswer,
    ProviderAnswer,
    SupportedClaim,
)


class OpportunityFixtureProvider:
    async def generate_structured_answer(self, question, context, instructions):
        work = next(
            f
            for f in context["evidence"]
            if f["reference"]["source_type"] == "verified_project"
        )
        applicant = work["facts"]["contribution"]
        employer = instructions["opportunity_evidence"][-1]
        candidate_ref = EvidenceReference.model_validate(work["reference"])
        employer_ref = EvidenceReference.model_validate(employer["reference"])
        return ProviderAnswer(
            content=ModelAnswer(
                answer=employer["facts"] + " " + applicant,
                evidence_references=[candidate_ref, employer_ref],
                claims=[
                    SupportedClaim(
                        text=applicant, source=candidate_ref, quote=applicant
                    )
                ],
                opportunity_claims=[
                    SupportedClaim(
                        text=employer["facts"],
                        source=employer_ref,
                        quote=employer["facts"],
                    )
                ],
            )
        )
