"""Python v2 AI layer: PII scrubbing, local semantic cache and the free external LLM router.

Hard rules (AGENTS.md §1.2, §2.B, §4.3):
- No local generative LLMs (Ollama, llama.cpp, LM Studio, vLLM, ...). Only the
  local CPU embedding model used by the semantic cache runs on this machine.
- Every prompt is PII-scrubbed inside the router before any HTTP dispatch.
- Only free tiers. A provider without its env key is skipped (`unconfigured`).
"""
