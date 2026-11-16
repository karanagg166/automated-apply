# Dashboard local draft recovery — source checkpoint 2026-11-17

Implementation [260690770f24d2df362fe7116ab8adac1e755f0c](https://github.com/karanagg166/automated-apply/commit/260690770f24d2df362fe7116ab8adac1e755f0c), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source.

The contact dashboard persists a local draft request identity before POST, recovers exactly that request after a lost response and uses GET after receiving its saved draft ID. Recovery metadata contains only contact/request/draft UUIDs. Corrupt storage, failed first persistence, missing facts, mismatched recipients/contact identities or changed GET identities cannot produce a fabricated navigation target. A failed later pointer write retains the original request key. Local composition stays use_llm=false and mutation retries are explicitly disabled.

Contact drafts can prepare another local introduction only after a review checkbox and independent saved revision read. Historical send attempts/sent timestamps or changed revision refuse replacement. The original draft/history is preserved; an existing unresolved/newer pointer is recovered instead of discarded. Job-bound drafts do not silently become generic contact introductions. Legacy/uncertain delivery records lock edits and approval controls consistently with the backend.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Durable local request/pointer helper, people/detail controls, fresh revision/review replacement and immutable history controls; Prettier write applied |
| Frontend fixtures | NOT TESTED | 10 new declarations:8 helper cases (stable request, GET recovery, missing facts, first/later storage failure, corrupt metadata, unbound responses, reviewed replacement/history);2 UI cases (review/fresh read, changed revision refusal). Existing policy fixture uses actual not_attempted status and router mock |
| Native/backend fixture additions | NOT TESTED | No new declarations in this slice; earlier outreach fixtures remain unrun |
| Current tests/types/build/lint/browser | NOT TESTED | New executed tests0; complete source precedes combined gates |
| Actual Mac/runtime/install/provider | NOT TESTED | No owner browser interaction, credentials, installed change, real message or provider request |
| Timing/resources | NOT TESTED | Metadata bounds/GET recovery by design; no measured resource/speed comparison |

User-facing failures ask to review/recover the saved request or reload a changed draft. They do not offer a new request after uncertain storage/network outcomes. No executed failure log, candidate data, mail, private body or browser evidence is published.

Final reproduction: coordinated `scripts/run_acceptance.py`, frontend `outreach-draft-attempt.test.ts`/`outreach-policy.test.tsx`, people/review journeys, full frontend types/build and isolated browser suite. Commands are documented, not executed now. Remaining public research/company/startup/dashboard/registry/provider/CLI/conversation/eight-platform source precedes combined gates and reviewed migration/install/live evidence. Last validated9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard+262 native PG=455 distinct passes; not current-head evidence.58/42 held. STOP162/lifetime4/hour1/three uncertain quarantines/strict worker receipts0 and filters/identity/PDF/focus controls remain. No hosted Actions, merge, cleanup, sending or installation.
