# Saved contacts and recommendations — source checkpoint 2026-11-17

Implementation [1910d515d08c1a53755452a2d099cb54fa76b289](https://github.com/karanagg166/automated-apply/commit/1910d515d08c1a53755452a2d099cb54fa76b289), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source.

The native owner API now reads saved company contacts, contact evidence and job-specific recommendations. Count/page/projection share one read-only repeatable-read snapshot and one database clock. Filters retain provider/strength same-record semantics; role wildcard characters are escaped literally. Public pages cap at100, evidence at100, public job references at100 and recommendations inspect at most1000 saved candidates. A probe row discloses candidate inventory truncation. Target-job association uses the full saved array before public reference truncation. No provider, token, DNS or paid request occurs.

Legacy ranking/retention/publication digest rules are ported with actual-source comparison fixtures. Suppression, stale evidence, conflicts and expiry remain distinct. Expired provenance is hidden in responses without GET writes; vendor payloads do not cross the projection. Unsafe profile URLs are hidden. Role inbox recognition is conservatively case-insensitive. `email_send_ready` is always false under owner policy; the prior reviewed-mailbox qualification is exposed separately as `email_draft_review_ready`. The UI says “Supported identity evidence” instead of conflating strong identity evidence with a verified mailbox.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Three GET routes, settings, owner authentication/error mapping, bounded saved projection and UI wording; formatter applied |
| Standard fixtures | NOT TESTED | 3 declarations:40 actual contact/ranking cases;16 actual business-mailbox/category cases plus uppercase role inboxes; query/settings/malformed metadata bounds |
| Dedicated native PostgreSQL/HTTP | NOT TESTED | 10 declarations: saved claims/privacy/retention; filters/paging/literals; same-evidence filters; evidence expiry/cap/no GET writes; full job association; no owner lock/state writes; unsafe/oversized data; missing records; auth/method/query limits; inventory truncation |
| Frontend | NOT TESTED | 1 new declaration plus1 updated existing assertion separating identity and mailbox evidence |
| Current-head build/types/lint/test | NOT TESTED | New executed tests0; combined gates remain deferred until full source integration |
| Actual Mac/provider/production | NOT TESTED | No installed/runtime/database/browser/provider change; fixtures are fictional |
| Timing/resources | NOT TESTED | Bounded query structure only; no measured speed or resource comparison |

Formatting caught a Rust query-parser guard spacing error during writing; it was corrected. This was a source parse finding, not an executed test failure. Fixed public failures include `invalid_contact_query`, `invalid_contact_saved_record` and explicit missing job/company/contact codes. No raw records or private logs are published.

Final reproduction: run the coordinated `scripts/run_acceptance.py` gate, including Rust `contact_rules`, disposable PostgreSQL `contacts_*` cases and `pnpm -C frontend test` for `people-research.test.tsx`, then types/build/browser journeys. Correction/enrichment and remaining contacts/outreach/provider/platform source still require implementation before that gate.

Prior validated9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard +262 dedicated native PostgreSQL passes,455 distinct; those results do not validate this head. Estimate58% complete/42% remaining held. STOP162/lifetime4/hour1/three quarantines/strict worker receipts0 and saved filters/identity/PDF/focus/history controls remain. No hosted Actions, merge, cleanup, provider activation or current installation.
