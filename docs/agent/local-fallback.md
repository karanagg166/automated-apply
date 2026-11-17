# Native local fallback — source only

`LLM_LOCAL_FALLBACK_ENABLED=true` may select a separately enabled/configured Ollama
writer after an eligible primary-provider failure. It never selects another remote
provider, starts a daemon, pulls a model or enables paid billing. Default remains false.
Ollama must independently prove cloud-disabled daemon status and local model metadata
before receiving candidate facts. This source is untested and uninstalled.

The existing primary writer keeps its own reservation and cooldown. The original writing
deadline gives the primary transport55% when local fallback is configured; the local
transport receives its remainder. Provider-specific maximum deadlines are also retained.
Ledger reservation, token and cooldown commits remain outside network cancellation;
slow/unknown persistence can exceed the transport deadline and never becomes a refund or
automatic primary retry. Local metadata and generation share the remaining transport
window. No new pool, recurring task or candidate cache is introduced.

Only bounded provider availability/quota/transport/schema failures may fall back. Unknown
ledger, context change, usage overrun, unsafe tools, unverified CLI initialization or
private policy failures stop explicitly. An invalid local model reports a local
configuration failure without contacting it. A cloud-capable/unknown local daemon refuses
the private prompt. Primary Ollama cannot chain into fallback.

The response reports the selected actual provider/model and selected-attempt usage.
Fixed warnings preserve the fact that a primary reservation remains consumed when one
was made; `used_llm` conservatively retains either attempt's reservation provenance.
It is not evidence that both remote/local requests reached a model. Successful text must
still pass the existing grounding and unchanged candidate/job generation checks, and any
saved draft requires review. Questionnaire automation has a separately configured
Cohere-only writer with fallback disabled; general draft settings do not widen it.

The native sentence-only provider branch now has separate source: with
`LLM_PROVIDER=ollama`, `OLLAMA_ENABLED=false` and
`OLLAMA_GENERATION_AUTHORIZED=true`, it uses bounded `/api/chat` with only permitted
whole sentence variants and an answer-only schema. Existing extractive matching rebuilds
citations locally and rejects additions, omissions, merges and repeats. The same local
metadata proof, optional ledger, shared gate and current-context checks remain.
Generic `OLLAMA_ENABLED=true` drafting stays a distinct branch.

The legacy internal `LocalAnswerEngine` v1 provenance/coalescing contract still needs its
separate parity integration. Neither provider branch is acceptance of that contract.
Combined fictional provider/PG/deadline and actual daemon checks are pending; no local
or cloud request was executed to validate these source checkpoints.
