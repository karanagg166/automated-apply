"""Shared fakes for the Phase 9C agent tests: a scripted LLM router (no network) and helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from backend.app.agent_v2.control_graph import ControlAgent
from backend.app.agent_v2.tools import (
    AuditedToolRunner,
    PendingConfirmations,
    ToolContext,
)
from backend.app.ai_v2.embeddings import DeterministicTestEmbedder
from backend.app.ai_v2.router import LLMResult
from backend.app.ai_v2.semantic_cache import MemoryCacheStore, SemanticCache
from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import MemoryStore

NOW = datetime(2026, 11, 27, 6, 0, tzinfo=UTC)
PROFILE = {"full_name": "Owner Example", "email": "owner.example@gmail.com", "phone": "+91 98111 22333",
           "verified_skills": [{"name": "Python"}],
           "preferences": {"target_roles": ["Backend Engineer"], "expected_ctc": 18, "notice_period_days": 60,
                           "company_blacklist": ["Wipro"]}}


class ScriptedRouter:
    """Returns the scripted AgentStep dicts in order; an Exception item is raised instead."""

    any_configured = True

    def __init__(self, steps: list[Any]) -> None:
        self.steps = list(steps)
        self.prompts: list[tuple[str, str, str]] = []

    async def generate_json(self, task, system_prompt, user_prompt, response_model, *, extra_secrets=(),
                            max_output_tokens=400):
        self.prompts.append((task, system_prompt, user_prompt))
        if not self.steps:
            raise AssertionError("router called more often than scripted")
        item = self.steps.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResult(response_model.model_validate(item), "fake", "fake-model", 1.0, 10, 10)

    async def status(self):
        return [{"provider": "fake", "status": "healthy"}]

    def seen(self) -> str:
        return "\n".join(user for _, _, user in self.prompts)


def tool(name: str, **args: Any) -> dict[str, Any]:
    return {"thought": f"use {name}", "action": "tool", "tool_name": name, "tool_args": args}


def final(reply: str) -> dict[str, Any]:
    return {"thought": "done", "action": "final", "reply": reply}


def cache() -> SemanticCache:
    return SemanticCache(MemoryCacheStore(), DeterministicTestEmbedder())


def fake_ai(router: Any = None, semantic: SemanticCache | None = None) -> Any:
    return SimpleNamespace(router=router, cache=semantic or cache())


def store_with_profile(profile: dict[str, Any] | None = None) -> MemoryStore:
    import copy

    return MemoryStore(profile=copy.deepcopy(profile or PROFILE))


def agent(store: MemoryStore, router: Any = None, *, clock: Any = None, **kw: Any) -> ControlAgent:
    kw.setdefault("pending", PendingConfirmations())
    return ControlAgent(store, ai=fake_ai(router, kw.pop("semantic", None)), clock=clock or (lambda: NOW), **kw)


def runner(store: MemoryStore, ai: Any = None, **kw: Any) -> AuditedToolRunner:
    ctx = ToolContext(store, ai=ai, clock=kw.pop("clock", lambda: NOW), **kw)
    return AuditedToolRunner(ctx, pending=PendingConfirmations())


async def job(store: MemoryStore, i: int = 1, *, platform: str = "greenhouse", state: S | None = None,
              company: str = "Acme", url: str | None = None) -> Any:
    record = await store.upsert_discovered(JobListing(
        platform=platform, external_job_id=f"{1000 + i}", company=company, title="Backend Engineer",
        url=url or f"https://job-boards.greenhouse.io/acme/jobs/{1000 + i}"))
    if state is None:
        return record
    if state in (S.APPLIED, S.SUBMISSION_UNKNOWN, S.WAITING_FOR_USER, S.FAILED):
        record = await store.transition(record, S.APPLYING, "apply_started", count_attempt=True)
    if state is not S.APPLYING:
        record = await store.transition(record, state, "test", receipt={"source": "test"}
                                        if state is S.APPLIED else None)
    return record
