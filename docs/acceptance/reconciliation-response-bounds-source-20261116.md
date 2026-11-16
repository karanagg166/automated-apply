# Lost-response reconciliation bounds — source checkpoint 2026-11-16

Implementation [`ce9c2a6aef1ab7743adfd5d35813e4e9170f784f`](https://github.com/karanagg166/automated-apply/commit/ce9c2a6aef1ab7743adfd5d35813e4e9170f784f), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Source only; no installed/live action.

Source review confirmed that counting only returned account/history reports could miss lost poll/bind/admission responses. New durable ceilings separately count reconciliation/account leases and read admissions, alongside retained legacy report counts. At most three opportunities per counter are admitted, with existing higher counts/corruption never reset. Continued reads within one lease consume admission counts too. Failed transactions do not consume a lease; a committed response lost in transport remains consumed. No second Apply or application-budget refund follows.

Queue claim quarantines exhausted reads, unknown recovery does not requeue them, and owner unknown-outcome notice eligibility includes the new durable counters. Reports now increment their count in the shared receive transition so the future native broker cannot omit it. These limits apply only to account/history reconciliation; ordinary discovery keeps its independent bounded transport backoff. Existing report/lease/audit history and all admitted application actions are retained.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source correction | PASS (source only) | Claim/admission/report ceilings and recovery/notice integration; formatter applied |
| New standard regressions | NOT TESTED | 2 declarations: lost lease/admission ceilings; retained legacy exhaustion/corrupt counters/discovery separation |
| New native PostgreSQL regressions | NOT TESTED | 3 declarations: three lost polls across restart; continued single-lease admissions without reports; dropped claim-event ACK rollback |
| Compilation/Clippy/lint/all suites | NOT TESTED | New tests executed0; combined final gate remains deferred |
| Native broker/extension response-loss journeys | NOT TESTED | Integration still in progress; no claim of completed transport recovery acceptance |
| Actual Mac/owner DB/browser/application | NOT TESTED | No live request or state change |
| Installation/receipt/focus/restart/24h | BLOCKED / NOT TESTED | Existing gates remain; actual strict receipt count0 |

Prior validated checkpoint9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard +262 dedicated native PostgreSQL passes,455 distinct. It does not validate this source. Approximate engineering estimate remains58% complete /42% remaining.

Final reproduction is `scripts/run_acceptance.py` after all source units are integrated. New fictional declarations are tests/reconciliation_bounds.rs and tests/support/reconciliation_bounds_pg.rs. No executed failure logs exist. Relevant conservative codes include bounded_reconciliation_exhausted, invalid_execution_saved_record and execution_write_ack_failed. The extra counters live in existing private work JSON, require no new table and do not increase application allowance. No timing/RSS/resource comparison is claimed.

Continue authenticated native controls/poll/bind/check/admit/finish/abandon, remaining exact form-loss/setup/owner/legacy route/scheduler integration, then other services/providers/platforms under the [plan](../plans/completion-execution-20261116.md). A limited exhausted reconciliation may need owner review; exhaustion is not a negative provider receipt or a reset. Installed STOP162, lifetime4/hour1, three quarantines, saved filters, first strict receipt prerequisites, Gmail read/draft-only and browser focus constraints remain unchanged.
