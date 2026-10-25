"""Seven fictional safe answers with no daemon, model loading or HTTP requests."""

import argparse
import asyncio
import json
import resource
import sys
import time
from pathlib import Path

from backend.app.ai.answer_engine import LocalAnswerEngine
from backend.app.ai.validation import validate_grounding
from backend.scripts.phase1.ollama_evaluate import cases
from backend.scripts.phase1.ollama_runtime import snapshot


async def evaluate():
    rows = []
    engine = LocalAnswerEngine()
    for name, question, context, words, style in cases():
        started = time.monotonic()
        answer = await engine.answer(question, context, {
            "max_characters": 1800, "max_words": words, "style_instruction": style,
        })
        elapsed = time.monotonic() - started
        grounding_error = (validate_grounding(answer.content, context["evidence"], 1800, words)
                           if answer.content else None)
        rows.append({
            "name": name, "source": answer.source, "status": answer.status,
            "content": answer.content.model_dump() if answer.content else None,
            "missing_information": answer.missing_information,
            "model_attempted": False, "schema_valid": None, "model_accepted": False,
            "grounding_error": grounding_error, "error_code": answer.error_code,
            "latency_seconds": elapsed,
            # ru_maxrss is a cumulative process high-water mark, not per-answer allocation.
            "process_peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                / (1048576 if sys.platform == "darwin" else 1024),
            "model_loaded": False,
            "passed": (answer.source == "needs_input" if name == "C_missing_users" else
                       answer.content is not None and grounding_error is None),
        })
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    before = snapshot()
    rows = asyncio.run(evaluate())
    report = {"mode": "deterministic_only_no_model", "before": before,
              "after": snapshot(), "cases": rows,
              "safe_results": sum(r["passed"] for r in rows), "model_attempts": 0}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    args.output.chmod(0o600)
    print(json.dumps(rows, indent=2))
    return 0 if all(r["passed"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
