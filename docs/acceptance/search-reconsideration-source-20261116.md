# Search, batch intake and filter reconsideration — source checkpoint 2026-11-16

Implementation [`1a993d496dcbe7f6af8c7c5e22a311c4b5c1917e`](https://github.com/karanagg166/automated-apply/commit/1a993d496dcbe7f6af8c7c5e22a311c4b5c1917e), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. No runtime installation or provider/browser operation.

Ordinary search scheduling now rotates confirmed saved/custom target roles. Verified experience below one year interleaves the previously observed Fresher search and internship keyword discovery; it never changes candidate facts or establishes fit. Only the existing unfiltered ordinary path shape may paginate, at most three pages, one page per saved interval. Active lease/next interval, source consent, queue state, execution mode, local disabled preference and confirmed profile are checked first.

Intake accepts at most20 URLs, normalizes/deduplicates requisitions and checks permanent work, damaged-or-valid receipt existence, canonical slug variants, applied job history and submitting/unknown packets before inserting. Capacity and outbox insertion are set-based and require exact acknowledgements; a missing work/event acknowledgement rolls back the whole batch. Admission arrays, original identities and old records are never renewed or removed. The existing single-item path shares the same capacity query.

A ten-record reconsideration tick processes only untouched filter holds. It skips the contended owner fence, rereads authority after acquisition, respects current confirmation/source/history and keeps the cursor before a candidate waiting for capacity. Retained facts may produce a current exclusion or queue a fresh inspect_job read; they never prepare a packet or authorize Apply. Local writes, events and marker advance share one transaction.

| Gate | Result | Evidence / limitation |
| --- | --- | --- |
| Source implementation | PASS (source only) | Search, bounded batch intake and reconsideration written; formatter applied |
| New standard regressions | NOT TESTED | 2 declarations; actual AST-only Python search function oracle contains280 rotation/encoding/pagination/timing comparisons; disabled/empty/corrupt proposal cases |
| New PostgreSQL regressions | NOT TESTED | 9 declarations: search scheduling/Stop; permanent unknown/damaged receipt/aliases; capacity/drop-ACK rollback; actual guarded applied/unknown packet history; fresh-read-only recheck; spent/receipt preservation; cursor backpressure; owner contention/Stop; event-ACK rollback |
| Compilation/Clippy/lint/full suites | NOT TESTED | New tests executed0; source-first/final combined gate remains active |
| Actual Mac/browser/search/provider/owner data | NOT TESTED | No live listing, source request, browser navigation or application |
| Authenticated native dispatch/job ingestion/scheduler | NOT TESTED | Still incomplete; these library primitives are not live automation |
| Install/strict receipt/focus/restart/24h resources | BLOCKED / NOT TESTED | Existing external/install gates and focus findings remain; actual strict receipt count0 |

Prior fully validated checkpoint9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard +262 dedicated disposable PostgreSQL passes,455 distinct. Those results do not validate this head. Engineering estimate remains58% complete /42% remaining.

Run `scripts/run_acceptance.py` only after all source units are integrated. New fixtures are tests/execution_search.rs and tests/support/execution_{search,reconsideration}_pg.rs; no test or check was invoked. All fixture data is fictional. No executed failure logs exist; relevant fail-closed codes include bounded_supported_queue_batch_required, queue_source_disabled, execution_write_ack_failed and execution_commit_outcome_unknown. No action replays on unknown commit.

The maximum batch is20 and reconsideration is10 per tick. Business reads/insertions are grouped rather than opening a transaction per candidate; no measured latency, resource or speed gain is claimed. Reconsideration intentionally does bounded local eligibility work under the acquired owner fence; final Stop-latency/connection/load comparisons must assess that cost. Existing source operations still require native integration, full listing ingestion, questionnaires/owner replies and scheduler work, followed by all remaining services/providers/platforms under the [completion plan](../plans/completion-execution-20261116.md). Preserve STOP162, lifetime4/hour1, three quarantines, filters, Gmail read/draft-only and actual browser focus constraints.
