"""PII scrubber + safe LLM profile: nothing identifying reaches a free external LLM."""

import json

import httpx
from pydantic import BaseModel

from backend.app.ai_v2.pii import build_safe_llm_profile, profile_secrets, scrub_pii
from backend.app.ai_v2.router import LLMRouter

# Assembled at runtime so the source never contains a literal credential URL (secretlint).
CREDENTIAL_URL = "https://" + ":".join(("user", "pw")) + "@db.example.org/x"
PROFILE = {
    "full_name": "Test Candidate Person",
    "email": "test.candidate@gmail.com",
    "phone": "+91 98765 43210",
    "linkedin_url": "https://www.linkedin.com/in/test-candidate-fake",
    "github_url": "https://github.com/test-candidate-fake",
    "verified_experience_years": 2,
    "verified_skills": [{"name": "Python"}, "FastAPI"],
    "verified_roles": ["Backend Engineer"],
    "projects": [{"name": "Job Agent", "technologies": ["Python", "Playwright"]}],
    "preferences": {
        "target_roles": ["Backend Engineer"], "tech_stack": ["Python"], "skill_years": {"python": 2},
        "total_experience_years": 2.5, "notice_period_days": 30, "remote_policy": "any",
        "current_location": "Bengaluru, Karnataka 560001", "willing_to_relocate": True,
        "current_ctc": "8", "expected_ctc": "14", "address": "42 Example Street, Koramangala",
    },
}


def test_regex_scrubs_phones_emails_ids_tokens_and_credential_urls():
    text = ("Call +91 98765 43210 or 9876543210 or (415) 555-0134; mail me@gmail.com; "
            "PAN ABCDE1234F; Aadhaar 2345 6789 0123; Authorization: Bearer abcdefghijklmnop1234; "
            "key gsk_TESTFAKETOKENONLY12345; " + CREDENTIAL_URL + "; "
            "https://example.org/cb?token=abc123&x=1; cookie=sessionvalue123; HR: jobs@example.com")
    out = scrub_pii(text)
    for leaked in ("98765", "9876543210", "555-0134", "me@gmail.com", "ABCDE1234F", "2345 6789 0123",
                   "abcdefghijklmnop1234", "gsk_TESTFAKE", "user:pw", "token=abc123", "sessionvalue123"):
        assert leaked not in out, leaked
    assert "jobs@example.com" in out  # placeholder domain allowed
    assert "[REDACTED_PHONE]" in out and "[REDACTED_PAN]" in out and "[REDACTED_AADHAAR]" in out


def test_extra_secrets_remove_owner_identifiers_and_variants():
    secrets = profile_secrets(PROFILE)
    text = ("I am Test Candidate Person (candidate), reach 919876543210, "
            "linkedin.com/in/test-candidate-fake, 42 Example Street, Koramangala")
    out = scrub_pii(text, secrets)
    assert "Person" not in out and "9876543210" not in out
    assert "test-candidate-fake" not in out and "42 Example Street" not in out
    assert "[REDACTED]" in out


def test_safe_profile_keeps_only_professional_context():
    safe = build_safe_llm_profile(PROFILE)
    dumped = json.dumps(safe)
    for forbidden in ("Test Candidate", "gmail", "98765", "linkedin", "github.com", "Koramangala",
                      "560001", "Example Street", '"8"', '"14"', "current_ctc", "expected_ctc"):
        assert forbidden not in dumped, forbidden
    assert safe["city"] == "Bengaluru" and safe["skill_years"] == {"python": 2.0}
    assert safe["total_experience_years"] == 2.5 and safe["notice_period_days"] == 30
    assert safe["skills"] == ["Python", "FastAPI"] and safe["projects"][0]["tech"] == ["Python", "Playwright"]


class Echo(BaseModel):
    ok: bool


async def test_router_scrubs_every_prompt_before_http_dispatch():
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.content.decode())
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}],
                                         "usage": {"prompt_tokens": 10, "completion_tokens": 2}})

    router = LLMRouter(env={"GROQ_API_KEY": "TEST_FAKE_TOKEN_ONLY"}, transport=httpx.MockTransport(handler))
    router.register_secrets(profile_secrets(PROFILE))
    await router.generate_json(
        "screening_qa", "system for test.candidate@gmail.com",
        "<div>Hi Test Candidate Person +91 98765 43210, PAN ABCDE1234F</div><script>x()</script>",
        Echo, extra_secrets=["Koramangala"])
    body = sent[0]
    for leaked in ("test.candidate@gmail.com", "Candidate Person", "98765", "ABCDE1234F", "<div>", "x()"):
        assert leaked not in body, leaked
    assert "TEST_FAKE_TOKEN_ONLY" not in body  # key travels only in the header


async def test_router_truncates_oversized_prompts():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    router = LLMRouter(env={"GROQ_API_KEY": "TEST_FAKE_TOKEN_ONLY"}, transport=httpx.MockTransport(handler))
    await router.generate_json("screening_qa", "s", "word " * 5000, Echo)
    user = sent[0]["messages"][1]["content"]
    assert len(user) <= 8_000 + 20 and user.endswith("[truncated]")
