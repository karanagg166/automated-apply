# Local-answer v1 engine — source only

The native library now has `local_answer::Engine` and immutable serializable
`SafeAnswer` outcomes. Deterministic extraction, needs-input and validation failure keep
separate provenance. A successful sentence-checked rewrite uses
`ollama_generated_verified`; failed/unsafe rewrites preserve the deterministic answer,
fixed error, attempt flag and selected usage. That name is the existing contract label
for sentence matching, not a claim that an external party verified personal facts.

Native answer preparation uses the deterministic resolver. Factual/summary, profile-link,
resume-status, low-memory, missing-fact and single-clause paths cannot dispatch through
this engine. The service does not configure an asynchronous rewrite callback here;
its existing explicit writer adapters still own provider authorization, budgets and IO.
The library adds no model startup, configuration changes, daemon calls or DB connection.

Optional `Rewriter` callbacks receive only the prepared permitted sentence/options payload.
They perform bounded transport only; durable reservations/commits must not occur inside
these cancellable callbacks. Returned text is independently matched again before its
claims/quotes are constructed. A callback is not a host permission or provider grant.
Production callback wiring remains a separate reviewed integration decision; no automatic
writer is enabled by adding this library.

An engine instance shares only overlapping identical question/context/instructions hashes,
at most eight. Completed results leave the map when the last waiter exits; there is no
persistent candidate cache. One waiter cancelling does not cancel another. Last-waiter
drop removes only its nonce-bound flight and aborts its transport. Source-only fictional
fixtures cover these cases; cancellation, concurrency and model behavior have not run.

The general explicit CLI and sentence-only writer paths extend native draft-provider
selection beyond the legacy application-answer service's refusal of those branches.
They still require their saved enable/quota or local-generation flags. Questionnaire
automation remains separately Cohere-only. None of these source additions establishes
installed runtime acceptance or authorizes applications, sending or paid overage.
