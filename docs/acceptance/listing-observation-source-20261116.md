# Bound listing observation and ingestion — source checkpoint 2026-11-16

Implementation [`24923ef7ca6ebc2379115f39d717989ce4f8007d`](https://github.com/karanagg166/automated-apply/commit/24923ef7ca6ebc2379115f39d717989ce4f8007d), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Source only, uninstalled and untested.

The internal listing-report path validates the existing native DTO, exact normalized document/requisition, current execution/policy/lease and saved preference. Posting/applicant filters run before ingestion; unknown applicant estimates produce a deduplicated dashboard choice without changing policy. Receipt/applied/unknown history blocks the complete requisition before further preparation. Only current confirmed-profile factual eligibility queues prepare; no packet, browser action or quota is created by this transition.

Observed normalization retains source facts, salary units, publication precision, evidence reference and explicit experience requirements. Identity resolution uses the existing advisory ingestion lock, source observation first, exact URL second and bounded relevant legacy URL rows last. Only tracking-only legacy query differences are normalized; arbitrary query identity and employer conflicts are not silently merged. Equal titles do not merge jobs. Company names without domains follow existing ambiguity handling; no domain or company fact is invented.

Reobservations preserve saved title, status, score, explanation, URL and employer association. The latest observed listing is stored separately in discovery_metadata. Salary evidence is filled only when its entire existing group is empty, preventing mixed units/currencies. Employer rejection rolls back its savepoint; failed work/observation acknowledgements roll back the whole outer transition. Unattempted listing transport failures have at most three backed-off retries; spent, packet-bound and form-pending work never takes that retry path. Owner platform activity yields an untouched read for60 seconds, preserving the existing activity gate requirement.

| Gate | Result | Evidence / limitation |
| --- | --- | --- |
| Source implementation | PASS (source only) | Normalizer, identity/ingestion, observation transition and applicant notice implemented; formatter applied |
| New standard regression | NOT TESTED | 1 declaration with48 actual NormalizedJob model/default/provenance comparisons; timestamp representations compared semantically |
| New native PostgreSQL regressions | NOT TESTED | 6 declarations: eligible preparation handoff; canonical review preservation; employer conflict rollback; unknown applicant hold; dropped source ACK rollback; bounded read-only transport retry |
| Compilation/Clippy/lint/all tests | NOT TESTED | New tests executed0; final combined gate remains deferred |
| Native broker/questionnaires/scheduler integration | NOT TESTED | Still incomplete; no operational automation claim |
| Actual Mac/provider/browser/listing/application | NOT TESTED | No live request, owner-data query, profile change or application |
| Installation/strict receipts/focus/restart/24h | BLOCKED / NOT TESTED | Existing install/account/focus gates remain; actual strict receipt count0 |

Prior fully validated checkpoint9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard +262 native PostgreSQL passes,455 distinct. It does not validate this source. The approximate engineering estimate remains58% complete /42% remaining.

Final reproduction is `scripts/run_acceptance.py` after all source is integrated. New fictional declarations are tests/listing_normalization.rs and tests/support/listing_observation_pg.rs. No executed failure log exists. Relevant conservative codes: queue_document_identity_changed, queue_requisition_changed, job_identity_requires_review, execution_write_ack_failed and execution_commit_outcome_unknown. No replay follows an unknown commit.

One observation has one ingestion identity lock and a nested rejection savepoint. The relevant legacy fallback is capped at10,000 matching-requisition rows and refuses overflow. No measured speed/RSS/latency comparison is claimed; final owner-lock latency and schema/grant compatibility must be measured. This slice handles bound Naukri observations, not generic normalization parity for all platforms or a finished native dispatcher. Continue original questionnaires/owner replies and authenticated native/scheduler work, then remaining services/providers/platforms under the [plan](../plans/completion-execution-20261116.md). Existing lifetime4/hour1, three quarantines, STOP162, current saved filters, Gmail read/draft-only and focus constraints remain.

Documentation correction: the previous search oracle contains280 comparisons (5 experience cases ×2 preference modes ×7 cursor cases ×4 prior-work shapes), not560. No test was executed to establish this count; it is the declared Cartesian corpus size. The earlier source report and resume record are corrected accordingly.
