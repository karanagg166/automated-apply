# LLM observability and the answer judge (Langfuse)

Hosted Langfuse Cloud (free Hobby tier). Nothing extra runs on the Mac: the worker only batches
spans on a background thread and posts them over HTTPS.

## Setup (once)

1. Create a free project at <https://cloud.langfuse.com> (EU) or <https://us.cloud.langfuse.com> (US).
2. Project settings → API keys → create a key pair.
3. Add to `<repo>/.env` (never to a committed file):

   ```
   LANGFUSE_PUBLIC_KEY=...
   LANGFUSE_SECRET_KEY=...
   LANGFUSE_BASE_URL=https://cloud.langfuse.com
   AI_V2_JUDGE_MODE=shadow
   ```

4. Install the dependency into the runtime venv and verify:

   ```
   uv pip install --python backend/venv/bin/python -c backend/requirements.lock -r backend/requirements-runtime.txt
   backend/venv/bin/python -m backend.app.browser_v2.cli langfuse-test
   ```

   `langfuse-test` checks the keys and sends one synthetic trace; it prints the trace URL.
5. Restart the api and worker so they pick up the keys.

With the keys blank, or `LANGFUSE_TRACING_ENABLED=false`, tracing is completely off.

## What is recorded

| Where | What |
|---|---|
| Trace `llm.<task>` | One per `LLMRouter.generate_json` call. Tasks: `screening_qa`, `jd_scoring`, `email_draft`, `cover_note`, `agent_intent`, `agent_react`, `answer_judge`. |
| Generation per provider attempt | Model, PII-scrubbed prompt, raw reply, token counts, latency, and the failure reason (`http_429`, `timeout`, `invalid_json:…`) when it failed over. |
| Trace metadata | `chain` (every provider tried or skipped), `failovers`, final `provider`, `outcome`. |
| Scores on `llm.screening_qa` | `answer_accepted` (bool, comment = reason), `llm_confidence`, `judge_supported` (bool), `judge_score`, `judge_available`. |

Deterministic answers (profile facts, semantic-cache hits) make no LLM call, so they create no
trace and use none of the free quota.

## Privacy

- The router scrubs every prompt before dispatch; the tracer records only that scrubbed text.
- A Langfuse `mask` hook re-scrubs every payload with the owner identifiers registered by
  `AIRuntime.bind_profile` (name, phone, email, links).
- A private OpenTelemetry provider is used, so spans from other libraries (FastMCP tool calls)
  are never exported.

## The judge (`AI_V2_JUDGE_MODE`)

After the generator model answers a screening question and passes the confidence gate, a model
from a **different provider** audits the answer against the same PII-free profile.

| Mode | Behaviour |
|---|---|
| `off` | Judge never runs. |
| `shadow` (default) | Runs only when Langfuse is on. The answer is still used; the verdict is scored. A rejected answer is not saved to the semantic cache. |
| `enforce` | A rejected answer is dropped and the question goes to Telegram (`llm_judge_rejected`). |

If no other provider can judge (quota or outage), the answer is handled as before (fail-open).

Recommended path: run `shadow` for a few days, filter traces in Langfuse by
`judge_supported = 0`, read them, and switch to `enforce` once the rejections look right.

## Using it to improve accuracy

- **Wrong answers:** filter `llm.screening_qa` by `judge_supported = 0`. Each one is either a
  prompt problem (fix `SYSTEM_PROMPT` in `ai_v2/screening.py`) or a missing profile fact (add it
  with `cli facts set`, which makes the question deterministic).
- **Questions the LLM punts:** filter `answer_accepted = 0`; the comment says why
  (`llm_needs_human`, `llm_low_confidence`, `llm_answer_not_an_option`).
- **Provider health:** group by `metadata.provider` and look at latency and `failovers`.
- **Regression set:** add good and bad traces to a Langfuse dataset from the UI and re-run them
  after a prompt change.
