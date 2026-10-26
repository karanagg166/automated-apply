"""Fictional fixtures and injected provider: no network and no account credentials."""
from backend.app.ai.schemas import ModelAnswer, ProviderAnswer, SupportedClaim, EvidenceReference, TokenUsage

PROJECT = {
    "name": "Example Relay", "purpose": "A service for sharing task updates.",
    "contribution": "I implemented backend authentication using Python and FastAPI.",
    "implementation_details": "I used signed tokens to authenticate requests.",
    "engineering_challenges": "I faced a challenge: Concurrent connections required consistent authentication.",
    "solutions": "I checked authentication before accepting each connection.",
    "technologies": ["Python", "FastAPI"], "url": "https://github.com/example/relay",
}


class FakeProvider:
    def __init__(self, answer=None, error=None):
        self.calls = []
        self.answer, self.error = answer, error

    async def generate_structured_answer(self, question, grounded_context, instructions):
        self.calls.append((question, grounded_context, instructions))
        if self.error:
            raise self.error
        fact = grounded_context["evidence"][0]
        data = fact["facts"]
        project = data.get("project", data)
        quote = project.get("contribution", "I implemented backend authentication using Python and FastAPI.")
        reference = EvidenceReference.model_validate(fact["reference"])
        answer = self.answer or quote
        claims = [SupportedClaim(text=answer, source=reference, quote=quote)]
        if self.answer is None and "challeng" in question.casefold() and project.get("solutions"):
            purpose = project["purpose"]
            first = f"{project['name']} is {purpose[0].lower() + purpose[1:]}"
            segments = [(first, purpose), (quote, quote),
                        (project["engineering_challenges"], project["engineering_challenges"]),
                        (project["solutions"], project["solutions"])]
            answer = " ".join(text for text, _ in segments)
            claims = [SupportedClaim(text=text, source=reference, quote=support) for text, support in segments]
        content = ModelAnswer(answer=answer, evidence_references=[reference], claims=claims)
        return ProviderAnswer(content=content, usage=TokenUsage(input_tokens=120, output_tokens=30))
