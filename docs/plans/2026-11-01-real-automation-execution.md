# Real application automation execution — 2026-11-01

Owner-requested continuation of PR #48 on the existing repository and PostgreSQL
architecture. This is an execution backlog, not a completion or live submission
claim. It supersedes obsolete scope and deployment assumptions in earlier plans.

## Required behavior

Discovery runs without an open dashboard. It collects actual listing details,
checks current profile and platform filters, and deduplicates by platform and
provider requisition before handing eligible work to application preparation.
Discovery observations, exclusions and missing evidence remain durable history;
they must not be presented as submitted applications. Repeated searches do not
create repeated application intents.

Application processing consumes eligible work independently of discovery timing,
rechecks facts at preparation and every write, fills supported forms, answers from
verified facts and approved answers, selects the verified PDF, submits once and
independently verifies the provider receipt. Lost or uncertain submissions are
reconciled without replaying Apply. Browser operations share the existing exclusive
inactive-tab lane; independent workers do not justify concurrent unsafe browser
actions, new brokers or higher database connection limits.

Every 30 minutes, compare supported portal profile facts with the confirmed local
profile. Create deduplicated dashboard notifications for missing facts or genuine
conflicts. Link the owner to the exact profile fields; save answers with provenance
and version checks, apply only supported verified updates and independently check
provider persistence. Platform login/contact differences remain valid after the
approved binding. Unsupported extraction must remain unknown, not a missing fact.

Initial scope is Naukri, followed by individually delivered Instahyre, Wellfound,
Y Combinator Work at a Startup and Internshala. Preserve separate OFF / REVIEW /
AUTOMATIC policies and per-platform readiness. Authorized account setup uses only
verified facts; OAuth, OTP, CAPTCHA or other unavoidable owner actions are surfaced
once. Never bypass provider restrictions or silently activate an adapter stub.

Use the existing Apollo/SignalHire adapters for professional contact evidence and
Gmail drafts. Respect actual account access and credits. Gmail sending remains
disabled. No paid plan purchase is authorized. Current runtime has neither
provider API key and both providers are disabled; live enrichment cannot be
represented as verified until account access is supplied and checked.

## Ordered work and acceptance

| ID | Concrete work | Acceptance required | Current state |
| --- | --- | --- | --- |
| A1 | Run complete eligibility checks in discovery before scheduling preparation | Real rejected observations remain history; no preparation packet/action for them; dedup/replay protections retained | In progress |
| A2 | Enable 1,800-second profile comparisons and deduplicated missing-fact notices | Actual bound portal comparison, notification, owner answer/version save and supported provider persistence | Existing comparison adapter; notifications/interval work pending |
| A3 | Finish first new supported Naukri application | Real fresh identity/PDF/job/history checks; actual fill/submit; independent persistent receipt; dashboard/Telegram outcome | No new verified submission |
| A4 | Bounded Naukri recurring AUTOMATIC | First receipt plus critical checks; repeated real submissions within quotas, no duplicates; restart and locked-operation evidence | Not enabled |
| A5 | Separate discovery/application visibility and controls | Dashboard distinguishes observed/held jobs from eligible application work and verified submissions; workers make progress independently | Existing durable stages, presentation incomplete |
| B1 | Instahyre adapter and account setup | Actual discovery/form/receipt/recurring acceptance under its own policy | Not accepted |
| B2 | Wellfound adapter and account setup | Actual discovery/form/receipt/recurring acceptance under its own policy | Not accepted |
| B3 | Y Combinator Work at a Startup adapter/account setup | Actual discovery/form/receipt/recurring acceptance under its own policy | Not accepted |
| B4 | Internshala adapter and account setup | Actual discovery/form/receipt/recurring acceptance under its own policy | Not accepted |
| C1 | Connect Apollo and SignalHire to existing contact/draft workflow | Actual authentication, bounded lookup evidence, verified recipient provenance, real Gmail draft; no send | API credentials missing |
| D1 | Integrated frontend/API/schema/worker checks and release | Relevant regressions and local integrated checks, live provider acceptance, rollback and restart evidence; sanitized report pushed | Pending |
| D2 | Review and merge the completed work | Owner's requested completion condition met, reviewed exact head, no unresolved critical acceptance failures; no hosted workflow dispatch | Pending |

The applicant threshold remains 1,000, age 14 days, score 50, all company stages.
The earlier once-asked decision about `100+` lower-bound-only counts remains
pending. A numeric threshold change alone does not authorize inventing its upper
bound. Continue useful independent work rather than repeating the question.

## Execution and evidence rules

Keep source and immutable installed releases distinct. STOP during replacements,
preserve exact prior releases, stable extension ID, credentials, approved bindings,
application history and rollback files. No owner tab/window activation or use of
keyboard/clipboard. Protect uncertain saves/submissions from repeats.

Build and run targeted regressions for changed behavior, then the relevant local
integration checks. Use actual portal evidence for live acceptance. Record exact
component SHAs, test counts, timings, failure codes and PASS / FAIL / BLOCKED /
NOT TESTED results in sanitized reports linked from PR #48. Do not publish personal
profile/resume/mailbox/browser contents. Do not trigger hosted Actions.

Completion means the agreed supported flows have demonstrated real recurring
applications and all critical acceptance checks pass. A Mac-only service requires
the Mac awake, connected and the bound browser available; no zero-error or
indefinite 24/7 guarantee is claimed from a bounded test. New desired features do
not make the current scope unbounded. Unavailable provider access and owner-only
facts remain explicit, not fabricated success.

The requested “Get Shit Done” plugin was searched in connected plugin discovery
and local skill paths; no matching installed integration was found. The search
returned unrelated integrations. Continue this executable repository plan without
claiming that plugin is installed; additional plugins may exist in the
[plugin directory](https://chatgpt.com/plugins).
