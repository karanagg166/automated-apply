# Cohere evaluation transport

Verified against the official documentation on 2026-10-26:

- [Command A+](https://docs.cohere.com/docs/command-a-plus): `command-a-plus-05-2026`, structured output and tool use. `command-a-03-2025` is the explicitly selectable alternative. No model is substituted automatically.
- [Chat V2](https://docs.cohere.com/v2/reference/chat): fixed POST `/v2/chat`, Bearer authentication, non-streaming JSON envelope, `message.content`/`message.tool_calls`, `usage.tokens`. The transport streams response bytes locally solely to enforce a 128 KiB response bound.
- [Structured output](https://docs.cohere.com/docs/structured-outputs): JSON schema and tools are separate modes; `response_format` cannot accompany tools/documents. Tool proposals use experimental `strict_tools=true`; every tool needs a required parameter. Unsupported numeric, array and string bounds are stripped from the remote schema and remain enforced by Pydantic locally.
- [Reasoning](https://docs.cohere.com/docs/reasoning): A+ thinking is explicitly disabled to bound work.
- [Evaluation limits](https://docs.cohere.com/docs/rate-limits): 20 Chat requests/minute and 1,000 API calls/month. An account's other applications also consume its quota; local counters cannot see those calls. A 429 pauses requests durably for at least a minute.

No key was configured at implementation preflight. Account type, model access and remaining account quota are **unverified**. No live request or personal-data transfer occurred. A realistic MockTransport exercises actual V2 request and response envelopes, malformed output, strict tools, error handling, byte bounds and usage accounting.

Private opt-in configuration is in `backend/.env.example`. The API key is a SecretStr and never appears in frontend configuration or Telegram. Activation requires `COHERE_ENABLED=true` and operator confirmation that the credential is an evaluation key. The service cannot infer account billing type from a token and never changes billing. Leave these flags false until the owner verifies the key in Cohere's dashboard. Other providers are never used as a fallback.

Candidate facts/resumes require separate `COHERE_CANDIDATE_DATA_AUTHORIZED`; owner command text requires `COHERE_OWNER_TEXT_AUTHORIZED`. Initial evaluation must use fictional fixtures. Keys, prompts, raw provider errors and responses are never logged by this adapter.

One attempt consumes one independently committed request reservation. There are no Cohere retries. Atomic monthly quota rows impose a 3.1-second gap across processes and a request ceiling of at most 1,000. The monthly token budget conservatively allocates `LLM_MAX_INPUT_CHARS + LLM_MAX_OUTPUT_TOKENS` per reserved request, including failures with unknown usage. This deliberately underuses quota rather than overspending it. Observed model token counts are stored separately as actual input/output tokens; missing usage remains unknown in the response. Reserved requests include lost/failed responses and must not be described as accepted generations. A deterministic answer reserves nothing.

## Owner setup for a fictional evaluation

Sign in to [Cohere's API keys dashboard](https://dashboard.cohere.com/api-keys).
Choose a free trial/evaluation key and independently confirm its account type,
model access and remaining quota. Do not choose a production key, add billing or
upgrade a plan as part of this procedure. Current official limits are 20 Chat
requests/minute and 1,000 calls/month; other account users consume that allowance.

Privately edit the selected external mode-0600 backend env file, never frontend
settings, Telegram or a tracked file. Store the key in `COHERE_API_KEY`; keep
`COHERE_ENABLED=false` until an explicit fictional-data test is authorized. Once
authorized, confirm `COHERE_EVALUATION_KEY_CONFIRMED=true`, select
`COHERE_MODEL=command-a-plus-05-2026`, and set a small evaluation ceiling such as
`COHERE_MONTHLY_MAX_REQUESTS=6`, `COHERE_MONTHLY_MAX_TOKENS=110000`,
`LLM_MAX_CONCURRENCY=1`. Existing reservations count toward these limits.
Keep `COHERE_OWNER_TEXT_AUTHORIZED=false` and
`COHERE_CANDIDATE_DATA_AUTHORIZED=false`; evaluate an explicit fictional harness
without loading the owner's profile, projects, resume or Telegram text.

Before making any live call, review six bounded fictional cases covering intent,
structured filters and follow-up context, then record actual request/token counts
without recording raw responses or keys. Use the existing mocked suite for invalid
JSON, hallucinations, tools, provider failures and quota exhaustion; do not spend
live quota to reproduce each synthetic failure. Every proposal must still pass
local Pydantic/grounding and permission checks. Turn the provider off after the
bounded evaluation. Key presence alone never authorizes testing or data transfer.

The 2026-10-26 integration audit found no configured key or live-test authorization.
Live evaluation remains blocked; the mocked contract tests remain the evidence.

For narrative writing, the existing independent grounding validator checks every claim and source after Pydantic validation. A valid JSON object is never sufficient evidence of truth. Tool proposals never execute inside the transport.
