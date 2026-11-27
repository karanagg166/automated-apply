# Evals for the screening agent (100% free, no resident RAM)

| What | Command | Cost |
|---|---|---|
| Real-pipeline accuracy + safety (25 golden cases, deterministic + cache + LLM) | `backend/venv/bin/python -m backend.evals.run_screening_eval` | ~5k free LLM tokens |
| Same, no LLM (CI-fast, 0 tokens) | `... run_screening_eval --no-llm` | 0 |
| Push the run to Langfuse (dataset `screening-golden-v1`, scores `eval_pass`, `eval_tokens`) | `... run_screening_eval --langfuse` | 0 extra |
| LLM-prompt-only check in the promptfoo UI | `backend/venv/bin/python -m backend.evals.make_promptfoo`, then `cd .local/evals/promptfoo && set -a && . ../../../.env && set +a && PROMPTFOO_DISABLE_TELEMETRY=1 PROMPTFOO_DISABLE_UPDATE=1 pnpm dlx promptfoo@latest eval --no-cache`, then `pnpm dlx promptfoo@latest view` | free (Groq) |

Exit code 1 on any failure, so `run_screening_eval --no-llm` can gate a deploy.
Add a case to `backend/evals/screening_golden.json` every time a real application gets a wrong or risky answer.
Langfuse Cloud removed the old trace endpoints on 2026-11-16: read data with `/api/public/v2/observations` and `/api/public/v3/scores`.
