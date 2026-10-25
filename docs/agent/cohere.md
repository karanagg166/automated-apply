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

For narrative writing, the existing independent grounding validator checks every claim and source after Pydantic validation. A valid JSON object is never sufficient evidence of truth. Tool proposals never execute inside the transport.
