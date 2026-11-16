# Contact credit ledger — source checkpoint 2026-11-17

Implementation [7fdd777f4cb3149a20f8d5ffdd39782c06895b32](https://github.com/karanagg166/automated-apply/commit/7fdd777f4cb3149a20f8d5ffdd39782c06895b32), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source.

The native contact integration now has durable local credit accounting over the original discovery monthly/reservation tables. Shared owner/SERIALIZABLE transactions commit a unique reservation and exact numeric monthly increment together. Reusing a reservation identity is refused across providers and outcomes; a lost response provides no new reservation. Global saved cooldowns apply across month boundaries. Provider-reported actuals are retained findings and never subtract the full safety reservation. Finish changes a reserved finding once, permits identical acknowledgment and refuses a conflicting later finding. The opaque reservation type is not serialized and grants no provider entitlement, remote dispatch or lookup retry.

Cooldown updates preserve longer prior deadlines, reserved balances and provider/month identities. The bounded inventory includes at most120 months; missing current month is inserted with zero reserved credits only when within that bound. Complete returned acknowledgments cover reservation fields, monthly identities/balances/cooldowns and one-way finish fields. Suppressed/altered writes roll back their whole transaction. No runtime DDL, remote provider request or remotely callable budget-control endpoint is added.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Ledger source | PASS (source only) | Existing table compatibility, exact SQL numeric accounting, owner fence, guarded finish and monotonic bounded cooldown; formatter applied |
| Dedicated native PostgreSQL | NOT TESTED | 10 new declarations: exact durable fraction/full-cap retention; single-use/lost-response/terminal conflict; cap/cross-month cooldown; concurrent cap;2 reservation insert ACK faults;5 monthly update ACK faults;3 finish ACK faults; monotonic/new-month cooldown;2 cooldown ACK faults; invalid input/owner ACK |
| Standard/frontend count | NOT TESTED | 0 new declarations; this slice is database behavior only |
| Current-head build/lint/combined tests | NOT TESTED | New executed tests0; full source precedes combined execution |
| Provider dispatch/identity integration | NOT TESTED / INCOMPLETE | This ledger is not yet wired to a native lookup controller; provider execution readiness remains false |
| Actual account/Mac/runtime/install | NOT TESTED | No real credits reserved, provider account request, purchase, service restart or installed change |
| Timing/resources | NOT TESTED | Bounded short transaction structure only; no measured comparison |

Source review strengthened cooldown acknowledgments to compare the exact prior-or-new maximum deadline and unchanged balance, rather than merely checking the requested minimum. Fixed findings include `contact_reservation_already_used`, `contact_provider_budget_exhausted`, `contact_provider_cooling_down`, `contact_reservation_terminal_conflict` and `contact_budget_write_ack_failed`. No executed failure log or private budget/account record is published.

Final reproduction: coordinated `scripts/run_acceptance.py`, dedicated disposable PostgreSQL `contact_budget_*` cases, combined provider/controller/identity recovery cases once integrated, then complete contracts/build/browser/UI gates. Durable run/lookup admission, live capability proof, fixed provider IO, conservative identity reconciliation and grounded outreach still require source integration before tests. Prior validated9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard +262 native PG passes,455 distinct; it does not validate this head.58/42 held. STOP162/lifetime4/hour1/three quarantines/strict worker receipts0, saved identity/PDF/focus/filter/history controls remain. No hosted Actions, merge, cleanup or provider activation.
