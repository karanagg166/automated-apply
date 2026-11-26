"""Short portal intro / cover notes (Wellfound, YC Work at a Startup, Internshala).

Free LLM router (task `cover_note`, PII-scrubbed, facts-only system prompt) first; a
deterministic facts-only template when no provider answers. Never invents employers,
dates, numbers or links; owner identifiers are scrubbed by the router before dispatch.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.app.ai_v2.router import AllLLMProvidersExhaustedError, LLMRouter

MAX_NOTE_CHARS = 600
SYSTEM_PROMPT = (
    "Write a short, warm, specific note (2-4 sentences, under 500 characters) from a job candidate to the "
    "hiring team. Use ONLY facts in the candidate profile JSON and the job title/company/description. Never "
    "invent employers, dates, metrics, links, degrees or work authorization. No greetings with placeholder "
    'names, no signature. Reply with one JSON object: {"note": string}.')


class IntroNote(BaseModel):
    model_config = ConfigDict(extra="ignore")
    note: str = Field(min_length=20, max_length=1200)


class IntroComposer:
    def __init__(self, router: LLMRouter | None, safe_profile: dict[str, Any] | None = None) -> None:
        self.router = router
        self.safe_profile = dict(safe_profile or {})

    def bind_profile(self, safe_profile: dict[str, Any]) -> None:
        self.safe_profile = dict(safe_profile)

    async def __call__(self, detail: Any, facts: Any) -> str | None:
        from backend.app.browser_v2.adapters.common import deterministic_intro

        if self.router is not None and self.router.any_configured:
            job = {"title": detail.listing.title, "company": detail.listing.company,
                   "description": (detail.description or "")[:2500]}
            prompt = json.dumps({"candidate_profile": self.safe_profile, "job": job}, ensure_ascii=False)
            try:
                result = await self.router.generate_json("cover_note", SYSTEM_PROMPT, prompt, IntroNote,
                                                         max_output_tokens=250)
                note = " ".join(result.value.note.split())
                if note:
                    return note[:MAX_NOTE_CHARS]
            except AllLLMProvidersExhaustedError:
                pass
        return deterministic_intro(detail, facts)
