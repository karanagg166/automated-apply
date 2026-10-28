# Prepared Phase 3.5 integration PR

Publish exactly once, after the owner merges #39 and actual main is reconciled. This is a local review draft, not a published PR or merge authorization.

Base: `main`
Head: `integration/phase35-final-20261028`
Title: `feat(phase35): integrate reviewed frontend and harden Gmail and form reliability`

## Proposed body

Gmail reviewed-lead imports now reject failed persistence and remain retryable. The combined browser assistant preserves owner values, rejects stale DOM/options and delivers correct React-controlled choice events in the guarded worker. The complete final AGY frontend history is included, together with migration readiness, discovery diagnostics and final combined test repairs. Packet/browser transactions now commit before response delivery, preventing immediate follow-up revision races; commit failures return sanitized 503.

Engineering PASS on implementation `50b3a681c1d86134cdf721db7dabb5d93ca79926`: 2,549 backend cases with PostgreSQL/restart, 185 Vitest cases, 17 actual frontend/FastAPI/PostgreSQL browser journeys, 12 dashboard journeys, 49 extension units, 25 DOM races, four actual React cases, popup/unanswered journeys and 23 MV3/native scenarios. Production build, final typecheck/format, Ruff, full-app Bandit, secret/private-artifact checks, pinned dependency audits and generated API consistency passed. See `docs/phase3/phase35-engineering-conclusion.md` for exact accounting, failures corrected and fixture limitations.

External activation remains PARTIAL. The additive Gmail schema change is prepared and tested locally but unapplied online. Each mailbox requires its own selected read consent. Provider collection, current allowance verification, deployment and genuine employer acceptance remain separate gates. Zero genuine messages or employer applications were sent/submitted. Hosted workflows remain manual-only.

Preserves the complete Codex and final AGY histories through merges, including `cc903b71`, `709c814`, `ae84afc` and `0721857`. Depends on #39; no auto-merge or deployment requested.

![Fictional saved-question review dialog](docs/phase3/screenshots/phase35-question-review-fictional.png)
