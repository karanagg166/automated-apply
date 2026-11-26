"""Export verified, PII-scrubbed Q&A as chat-completion JSONL for future QLoRA/Unsloth fine-tuning.

Sources (human-verified only, never LLM-generated answers):
  - public.semantic_cache rows with source='user' (Telegram/dashboard HITL answers)
  - application_answer_drafts with review_status='reviewed' (approved screening answers)
Every line is scrubbed with the same owner-identifier + PII scrubber used for LLM prompts.
The file is written 0600 and never uploaded anywhere by this tool.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from backend.app.ai_v2.pii import profile_secrets, scrub_pii
from backend.app.ai_v2.semantic_cache import normalize_question

SYSTEM = ("You answer job-application screening questions for one candidate, truthfully and concisely, using only "
          "verified facts. If unsure, say you need to check.")
PAGE = 200


async def collect_pairs(cache_store: Any, reviewed: list[tuple[str, str]] | None = None,
                        kind: str = "screening_qa", max_rows: int = 10_000) -> list[tuple[str, str, str]]:
    pairs: dict[str, tuple[str, str, str]] = {}
    offset = 0
    while offset < max_rows and cache_store is not None:
        entries, total = await cache_store.list_entries(kind, None, PAGE, offset)
        for entry in entries:
            if entry.source == "user":
                pairs.setdefault(normalize_question(entry.question_text),
                                 (entry.question_text, entry.answer_text, "semantic_cache_user"))
        offset += PAGE
        if offset >= int(total or 0) or not entries:
            break
    for question, answer in reviewed or []:
        key = normalize_question(question)
        if key and answer and answer.strip():
            pairs.setdefault(key, (question, answer, "reviewed_answer_draft"))
    return list(pairs.values())


def to_jsonl_lines(pairs: list[tuple[str, str, str]], profile: Mapping[str, Any]) -> list[str]:
    secrets = profile_secrets(profile)
    lines = []
    for question, answer, source in pairs:
        q, a = scrub_pii(question.strip(), secrets), scrub_pii(answer.strip(), secrets)
        if not q or not a:
            continue
        lines.append(json.dumps({"messages": [{"role": "system", "content": SYSTEM},
                                              {"role": "user", "content": q},
                                              {"role": "assistant", "content": a}],
                                 "metadata": {"source": source}}, ensure_ascii=False))
    return lines


async def export_sft_dataset(out_path: str | os.PathLike[str], *, cache_store: Any,
                             reviewed: list[tuple[str, str]] | None, profile: Mapping[str, Any]) -> dict[str, Any]:
    path = Path(out_path).expanduser()
    if path.suffix != ".jsonl":
        raise ValueError("output must be a .jsonl file")
    pairs = await collect_pairs(cache_store, reviewed)
    lines = to_jsonl_lines(pairs, profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + ("\n" if lines else ""))
    os.chmod(path, 0o600)
    by_source: dict[str, int] = {}
    for _, _, source in pairs:
        by_source[source] = by_source.get(source, 0) + 1
    return {"path": str(path), "examples": len(lines), "by_source": by_source, "pii_scrubbed": True,
            "format": "chat-completion JSONL (messages: system/user/assistant)"}
