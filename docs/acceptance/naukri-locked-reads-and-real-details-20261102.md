# Genuine locked-screen reads and current listing details — Naukri OPEN

[PR #48](https://github.com/karanagg166/automated-apply/pull/48), branch
`fix/live-prepare-discovery-20261030`; exact extension implementation
[`44bbc4cc597b99f6f0fcd58cc5fc9a5791a0a0a9`](https://github.com/karanagg166/automated-apply/commit/44bbc4cc597b99f6f0fcd58cc5fc9a5791a0a0a9).
All observation times below are UTC on November2. No new submission is claimed.

## Real locked-screen evidence, separate from heartbeat

The Mac naturally reported LOCKED. The agent did not lock/unlock it, change power
settings, select a tab/window or use keyboard/clipboard. Existing services kept
running. At10:12:48, the queue was RUNNING97 with704 identities, a fresh worker
heartbeat and overdue search; a profile inspection was leased. This alone was
not accepted as working locked-screen automation.

Subsequent actual provider work established more:

- A new independent profile observation at10:12:51 verified the actual saved PDF
  against canonical bytes,100198 bytes, and retained `SYNC_VERIFIED` for the
  previously saved skills. This was a fresh read, not a repeated Save.
- Ordinary UI discovery ran10:13:28–10:13:45, found19 new provider identities and
  finished without error. OS lock observations bracketed this interval.
- Between10:13:48 and10:14:15, one retained listing progressed from DISCOVERED to
  SKIPPED; both samples reported LOCKED. Fresh inactive worker listing DOM was
  also read at10:15 and10:19 while LOCKED, without navigation or clicks.
- Four separate `/ready` calls returned200 in2.556,2.485,2.406 and2.113seconds.
  Each sample recorded LOCKED before and after the request, at10:13:48,
  10:14:15,10:14:40 and10:15:06.

These are bounded observations of readiness and actual provider discovery/read
operations. They improve on the earlier three503 samples, but do not prove the
cause of that earlier failure, uninterrupted overnight operation, sleep recovery,
or locked-screen questionnaire filling/upload/Apply/receipt. Sampling cannot
prove an uninterrupted OS state between every pair of observations. No heartbeat
alone is used as proof of browser operation.

## Actual listing compatibility change

A genuine leased listing showed that the broad job-desc-container also contains
Naukri highlights, match scores, Key skills, education and sharing controls.
The adapter now prefers the unique actual `JDC__dang-inner-html__` description
body, preserves paragraph/list boundaries and excludes script/style content.
Multiple bodies require review. The existing legacy fallback remains supported.

The genuine details also expose an explicit Employment Type label and value.
That label can supply a recognized type when structured metadata is missing.
Contradictory visible/structured types remain unknown; no easier requirement is
selected. Unknown counts, experience, dates and all configured filters remain
unchanged. A preferred-keyskills legend does not establish that every skill in
an employer's description is optional; no skill requirement was removed.

Offline replay of a captured genuine same-document DOM showed description
length2442→1685 characters and removal of surrounding platform UI. Employment
was already full_time in that particular sample. This replay is not a fresh
provider operation or proof of every missing-type fallback. Missing, conflicting
and ambiguous cases have separate isolated regressions.

After installation, the actual worker stored fresh listing facts at10:26:10.
The955-character description excluded surrounding platform UI; employment was
full_time. The job was SKIPPED with `required_experience_outside_verified_band`.
The observation at10:26:16 reported LOCKED. This is real parser/filter acceptance,
not a reason to submit the rejected job or invent a receipt.

## Exact installation, rollback and tests

Extension1.3.21 retains ID `gdjbmkffcpicbpiikcohlmokkmcpipgp`, key and permissions.
All24 installed files match44bbc4c. Initial preflight found the previous owned
extension-manager tab closed and exited before replacing files. The existing
extension's trusted maintenance path created a new inactive manager tab under
STOP98. Stop took5.583seconds. No manual URL navigation or owner tab activation
was used.

Installation completed10:24:33 with734 records, ready200, frontend200, fresh
native reconnect, unchanged profile5/account binding1/policies/protected component
files, and equal front-window/active-tab snapshots. Exact prior1.3.20 bytes,
hashes and rollback inventory remain retained. No replacement failed and no
rollback was needed. Queue resumed RUNNING99 under the unchanged SUPERVISED
cap1/hour1. API remainsb3abc9e, actual frontend and native414a260,
execution/Telegram2ceea5e; no other component was replaced.

| Validation | Result | Scope |
| --- | --- | --- |
| Node observer and queue regressions | PASS | 81 tests,1.102s, exact candidate byte-equivalent modules/tests |
| Isolated Chromium background checks | PASS | 15 cases,25.880s;3 current-details cases;0 live Naukri requests,0 unexpected requests,0 choosers |
| Build, formatting, diff | PASS | Exact candidate24 files; same ID/permissions |
| Genuine DOM replay | PASS | Captured current structure; excludes surrounding UI, preserves known employment |
| Installed genuine listing/filter | PASS | Fresh955-character facts, rejected excessive experience; LOCKED sample |
| Locked readiness and actual discovery/profile/listing reads | PASS, bounded | Four200s plus actual provider work above |
| Locked fill/questionnaire/upload/Apply/receipt | NOT TESTED | No eligible new submission admitted |
| New real application and independent receipt | BLOCKED |0 new verified submissions |
| Recurring AUTOMATIC/restart/full uptime | OPEN / NOT ACCEPTED | First receipt and remaining critical checks required |

Candidate tests used the existing canonical tester dependencies only after exact
byte comparisons of all seven loaded extension modules and three test drivers.
No mutable dependency directory was symlinked into the installed release. Counts
include existing regressions; do not add earlier overlapping runs as unique tests.
Backend contracts were unchanged, so the previous large suites were not repeated.

At10:26, the next real discovery had completed10:25:24–10:25:40, adding15 jobs.
The durable total was749:103 awaiting listing inspection,214 needing evidence or
input,431 skipped,1 historical application and0 new confirmed submissions.
Next search was scheduled10:30:24. These are observed identities and filter holds,
not749 applications. No historical/uncertain application was replayed.

Reproduction:

```sh
pnpm -C extension exec node --test tests/naukri-observation.test.mjs tests/naukri-queue.test.mjs
pnpm -C extension exec node tests/naukri-queue.browser.mjs
pnpm -C extension build
```

All company stages, score50,14-day age, applicant threshold1000, remaining filters
and unknown-count review remain enforced. The existing once-asked lower-bound
count decision remains pending; no exception was silently selected. Missing
personal facts are not fabricated. Next: process fresh eligible listings and
complete the first supported genuine application with independent receipt, then
bounded recurrence and actual restart/locked application acceptance. Other
platforms remain disabled, Gmail read/draft-only, no hosted Actions or merge.
