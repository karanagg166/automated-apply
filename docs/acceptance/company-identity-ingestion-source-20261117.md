# Canonical company evidence ingestion — source checkpoint 2026-11-17

Implementation [987d64bcc77c2a0cfabf5931a770acd8acd1085b](https://github.com/karanagg166/automated-apply/commit/987d64bcc77c2a0cfabf5931a770acd8acd1085b), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source.

Company ingestion preserves the actual source-ID/domain/source-URL identity hierarchy and content serialization/hash. Under owner-first serializable and existing ingestion advisory fences, source mappings to multiple companies or conflicting domains fail closed. URL-only identities require the same normalized employer name; display-name equality never merges different domain/source identities. Existing canonical names/facts remain intact; only a missing domain can be filled after identity-review checks.

Normalized observations are immutable and uniquely replayed by source/identity/content. Duplicate imports preserve the first run, time and status; corrupted replay timestamps fail. Complete company/observation RETURNING and post-trigger reload checks roll back unexpected mutations. Database-generated update timestamps are accepted only inside the operation's database time window. Public results contain company/observation IDs and created/replay labels, without raw metadata. This is a local domain service; owner startup-run/manual flow integration follows.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Exact identity/content hash port, conservative canonical resolution, immutable observation replay, complete ACK/rollback; formatting applied |
| Standard fixtures | NOT TESTED | 1 declaration:20 actual identity-key and actual ingest digest-expression comparisons, including Unicode/ASCII escaping and source priority |
| Native PG fixtures | NOT TESTED | 10 declarations: create/replay; domain reuse/name separation; source/domain conflict; URL-only identity; missing-domain fill/review; ambiguous mappings;4 INSERT ACK corruption modes; post-trigger/replay timestamp corruption; concurrent duplicate; invalid time/run rollback |
| Frontend additions | NOT TESTED | No new declarations in this slice; previous source remains unrun |
| Current tests/build/check/lint/types | NOT TESTED | New executed tests0; all source precedes combined gates |
| Actual Mac/provider/runtime/install | NOT TESTED | No provider/account/browser/production/installed action |
| Timing/resources/concurrency | NOT TESTED | Source fences/bounds and deferred concurrency fixtures; no measured runtime comparison |

Fixed findings include `startup_source_identity_ambiguous`, `startup_source_company_domain_conflict`, `startup_unqualified_company_url_conflict`, `startup_company_identity_review_required`, `startup_company_observation_replay_conflict` and `startup_identity_write_ack_failed`. No executed failure logs, candidate data, mail or raw private evidence are published. Normalized company evidence grants no application authority or verified mailbox claim.

Final reproduction: coordinated `scripts/run_acceptance.py`, Rust `startup_identity`, complete dedicated disposable native PG `startup_identity_*`, later full startup-run/manual/UI/browser gates. Commands are documented, not executed now. Continue manual startup-run orchestration, durable public research/provider status and remaining dashboard/registry/provider/CLI/conversation/eight-platform source, then coordinated gates and reviewed migration/install/live evidence. Last validated9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard+262 native PG=455 distinct passes; not current-head evidence.58/42 held. Last observed STOP162/lifetime4/hour1/three uncertain quarantines/strict worker receipts0 and filters/identity/PDF/focus rules remain unchanged. No hosted Actions, merge, cleanup, sending or installation.
