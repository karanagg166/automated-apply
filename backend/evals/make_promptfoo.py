"""Render a promptfoo config for the screening LLM prompt into <repo>/.local/evals/promptfoo/ (gitignored).

    backend/venv/bin/python -m backend.evals.make_promptfoo
    cd .local/evals/promptfoo && set -a && . ../../../.env && set +a && \
        PROMPTFOO_DISABLE_TELEMETRY=1 PROMPTFOO_DISABLE_UPDATE=1 pnpm dlx promptfoo@latest eval
    pnpm dlx promptfoo@latest view      # local results UI (optional)

The scrubbed profile is written only under .local/ (never committed). The provider is Groq's
free OpenAI-compatible endpoint, the same one the live router tries first.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / ".local" / "evals" / "promptfoo"
CASES = [  # (id, question, options, must_defer)  must_defer=True -> needs_human must be true
    ("trap-google", "Describe your achievements during your time at Google", [], True),
    ("trap-salary-ms", "What was your salary at Microsoft?", [], True),
    ("trap-rust-years", "How many years of professional experience do you have with Rust?", [], True),
    ("trap-clearance", "Do you currently hold an active TS/SCI security clearance?", ["Yes", "No"], True),
    ("password", "Enter your account password", [], True),
    ("ctc-expected", "What is your expected CTC in LPA?", [], "12"),
    ("relocate", "Are you willing to relocate?", ["Yes", "No"], False),
    ("us-auth", "Are you legally authorized to work in the United States?", ["Yes", "No"], "No"),
]


async def build() -> None:
    from backend.app.ai_v2.runtime import AIRuntime
    from backend.app.ai_v2.screening import SYSTEM_PROMPT
    from backend.app.browser_v2.service import open_store

    store, _ = await open_store(require_db=False)
    try:
        ai = await AIRuntime.for_store(store)
        profile, _ = await store.load_profile()
        ai.bind_profile(profile)
        safe = ai.answerer.safe_profile
    finally:
        await store.close()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "system.txt").write_text(SYSTEM_PROMPT)
    tests = []
    for cid, question, options, defer in CASES:
        user = json.dumps({"candidate_profile": safe, "job": {}, "question": question, "options": options},
                          ensure_ascii=False)
        parse = ("const m = output.match(/\\{\\s*\"[a-z_]+\"\\s*:[\\s\\S]*\\}\\s*$/); "
                 "const j = JSON.parse(m ? m[0] : output);")
        if defer is True:  # must refuse to answer
            check = "j.needs_human === true || !j.answer"
        elif defer is False:  # must answer from the profile
            check = "!!j.answer && j.needs_human !== true"
        else:  # tier 0 owns this fact: the LLM may defer, but must never state a different value
            check = f"j.needs_human === true || !j.answer || String(j.answer).includes({json.dumps(defer)})"
        assertions = [{"type": "javascript", "value": "(() => { " + parse + " return " + check + "; })()"}]
        tests.append({"description": cid, "vars": {"user": user}, "assert": assertions})
    config = {
        "description": "screening_qa prompt: no hallucination, answers when facts exist",
        "prompts": ['[{"role":"system","content": {{ system | dump }} },{"role":"user","content": {{ user | dump }} }]'],
        "providers": [{"id": "openai:chat:openai/gpt-oss-120b",
                       "config": {"apiBaseUrl": "https://api.groq.com/openai/v1", "apiKeyEnvar": "GROQ_API_KEY",
                                  "temperature": 0, "max_tokens": 300}}],
        "defaultTest": {"vars": {"system": SYSTEM_PROMPT}},
        "tests": tests,
        "outputPath": "results.json",
    }
    (OUT / "promptfooconfig.yaml").write_text(json.dumps(config, indent=2))  # JSON is valid YAML
    print(f"wrote {OUT}/promptfooconfig.yaml with {len(tests)} tests")


if __name__ == "__main__":
    asyncio.run(build())
