"""Offline accuracy eval for the screening-answer pipeline (real tiers, real profile, free LLMs).

    backend/venv/bin/python -m backend.evals.run_screening_eval [--no-llm] [--langfuse]

Checks the golden set in screening_golden.json: correctness of profile facts, sensitive-question
safety (never auto-answer password/OTP/IDs/religion/orientation), hallucination traps, and that
deterministic cases cost 0 tokens. Never writes to the semantic cache. With --langfuse the run is
pushed as a dataset experiment (one item per case, scores: eval_pass, tokens). Exit code 1 on any
failure, so it can gate a deploy.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

GOLDEN = Path(__file__).with_name("screening_golden.json")
DATASET = "screening-golden-v1"


def judge_case(case: dict[str, Any], resolved: Any) -> tuple[bool, str]:
    answer = (resolved.answer or "").strip()
    expect = case["expect"]
    if expect == "human":
        return (not answer, f"auto-answered {answer[:40]!r}" if answer else "sent to human")
    if expect == "human_or_low":
        nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", answer)]
        return (not answer or all(n <= 1 for n in nums), f"answered {answer[:40]!r}" if answer else "sent to human")
    if expect == "not_equals":
        return (answer.lower() != case["value"].lower(), f"answered {answer[:40]!r}" if answer else "sent to human")
    if not answer:
        return False, "no answer (went to human)"
    want = case["value"].lower()
    hit = answer.lower() == want if expect == "equals" else want in answer.lower()
    if hit and case.get("no_llm") and (resolved.input_tokens or resolved.output_tokens):
        return False, f"correct but spent {resolved.input_tokens + resolved.output_tokens} LLM tokens"
    return hit, f"got {answer[:60]!r}"


async def run(no_llm: bool, langfuse: bool) -> int:
    from backend.app.ai_v2.runtime import AIRuntime
    from backend.app.browser_v2.answers import CandidateFacts
    from backend.app.browser_v2.service import open_store

    cases = json.loads(GOLDEN.read_text())["cases"]
    store, _ = await open_store(require_db=False)
    try:
        ai = await AIRuntime.for_store(store)
        profile, reviewed = await store.load_profile()
        ai.bind_profile(profile)
        ai.answerer.save_llm_answers = False  # an eval must never teach the cache
        if no_llm:
            ai.answerer.router = None
        facts = CandidateFacts.from_profile(profile, reviewed)
        client = _langfuse_client() if langfuse else None
        if client:
            _ensure_dataset(client, cases)
        failures, tokens, rows = 0, 0, []
        for case in cases:
            resolved = await ai.answerer.resolve(case["q"], tuple(case["options"]), facts)
            ok, detail = judge_case(case, resolved)
            used = resolved.input_tokens + resolved.output_tokens
            tokens += used
            failures += 0 if ok else 1
            rows.append((case["id"], ok, f"tier{resolved.tier}", used, detail))
            if client:
                _record(client, case, resolved, ok, detail, used)
        if client:
            client.flush()
        width = max(len(r[0]) for r in rows)
        for cid, ok, tier, used, detail in rows:
            print(f"{'PASS' if ok else 'FAIL'}  {cid:<{width}}  {tier}  tok={used:<4} {detail}")
        print(f"\n{len(rows) - failures}/{len(rows)} passed, {tokens} LLM tokens total"
              + ("  (LLM disabled)" if no_llm else ""))
        return 1 if failures else 0
    finally:
        await store.close()


def _langfuse_client() -> Any:
    from backend.app.ai_v2.observability import tracer_from_env
    from backend.app.ai_v2.router import load_env

    tracer = tracer_from_env(load_env(None))
    return getattr(tracer, "_client", None)


def _ensure_dataset(client: Any, cases: list[dict[str, Any]]) -> None:
    try:
        client.create_dataset(name=DATASET, description="Golden screening questions (owner facts + safety traps)")
    except Exception:  # noqa: BLE001 - already exists
        pass
    for case in cases:
        try:
            client.create_dataset_item(dataset_name=DATASET, id=f"{DATASET}:{case['id']}",
                                       input={"question": case["q"], "options": case["options"]},
                                       expected_output={"expect": case["expect"], "value": case.get("value")},
                                       metadata={"id": case["id"]})
        except Exception:  # noqa: BLE001 - idempotent upsert by id
            pass


def _record(client: Any, case: dict[str, Any], resolved: Any, ok: bool, detail: str, used: int) -> None:
    try:
        with client.start_as_current_observation(as_type="span", name="eval.screening", input={"question": case["q"]}) as span:
            span.update(output={"answer": resolved.answer, "tier": resolved.tier, "detail": detail})
            span.score_trace(name="eval_pass", value=1.0 if ok else 0.0, data_type="NUMERIC", comment=detail)
            span.score_trace(name="eval_tokens", value=float(used), data_type="NUMERIC")
    except Exception:  # noqa: BLE001 - reporting must never fail the eval
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-llm", action="store_true", help="deterministic + cache tiers only")
    parser.add_argument("--langfuse", action="store_true", help="push results to the Langfuse dataset")
    args = parser.parse_args()
    return asyncio.run(run(args.no_llm, args.langfuse))


if __name__ == "__main__":
    sys.exit(main())
