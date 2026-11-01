# Naukri inactive setup and actual skills editor — OPEN

PR: [#48](https://github.com/karanagg166/automated-apply/pull/48), branch
`fix/live-prepare-discovery-20261030`. Implementation:
[`204b2d1fb469e10915d5d70c5df43ee4904ed18f`](https://github.com/karanagg166/automated-apply/commit/204b2d1fb469e10915d5d70c5df43ee4904ed18f).
Observation times below are UTC on 2026-11-01; local Mac date is November 2.
This is not real application or recurring automation acceptance.

## Change and exact installation

A stopped queue can issue a bounded, account-bound profile setup intent. The
extension creates only its own inactive tab at the fixed Naukri profile URL.
Creation is journaled before the tab request; lost creation responses do not
cause duplicate creation. An idempotent ACK records ownership, and owner adoption
is retained across service-worker reconstruction. ACK uses the existing work
identifier; Chrome command lease validation remains intact. No job or profile
Save authority is granted by this setup operation.

| Installed component | Exact SHA/version |
| --- | --- |
| API | `204b2d1fb469e10915d5d70c5df43ee4904ed18f` |
| Extension | Same SHA, 1.3.18, all 23 files verified; stable ID `gdjbmkffcpicbpiikcohlmokkmcpipgp` |
| Execution and Telegram | `2ceea5e4ab5662e041a58c6ec7d4aa73e86d51f7` |
| Frontend | `cd342bf4698c0d182a2f2cbc445760fa5ee693a7` |
| Native host | `9cf6cb6f3bda0973daca2a62d0b4ae63ef1fd401` |

The first installer preflight found its prior owned extension-manager tab
unavailable and exited before replacing files. The installed extension's existing
maintenance operation opened a new inactive setup tab. Queue STOP revision78
committed in 5.086 seconds. The successful installation completed at20:30:32:
API startup retained its complete database audit; `/ready` returned200; the
extension's ordinary Reload and a fresh native heartbeat were verified. The
approved binding revision1, profile version5, profile-sync policy, all566 records,
credentials, other LaunchAgents and native wrapper were preserved. Previous API
plist, all23 previous extension1.3.17 files and their hashes remain in the private
rollback inventory; no releases or data were deleted. No failed replacement
required rollback. Queue resumed unchanged SUPERVISED cap1/hour1 at revision79;
recurring AUTOMATIC remains disabled.

## Actual provider evidence

The extension created an inactive tab and acknowledged it against the current
approved account and browser binding. The loaded genuine profile document was
checked separately from the tab URL; its ordinary UI identity matched the
approved platform-account hash, without comparing or replacing candidate contact
email. At20:35:04, the actual Key skills editor was opened and its DOM captured
privately. Zero inputs were filled and zero Save controls clicked.

The genuine editor uses `form[name="keySkillsForm"]`, `#keySkillSugg` with role
`combobox`/label `Add skills`, a suggestions listbox, removable existing chips,
and `button#saveKeySkills`. There are28 saved chips. The current input reports
`maxlength=13`; the existing comma-separated value has236 characters. This is
observed remaining input capacity, not proof of a universal provider limit.
The complete canonical skill list must not simply overwrite the provider list
or bypass its input restrictions. Supported additions, preservation of existing
skills, save intent and independent persistence verification remain unfinished.

Two inspection assumptions were corrected using actual DOM evidence: hidden
photo-editor dialogs do not mean a visible editing session exists; opening Key
skills changes the ordinary profile URL to `?action=modalOpen`. The first
post-open read safely refused that changed URL. No Save was attempted or retried.
A subsequent bounded inspection recognized the observed URL and read the editor.
Private operator probes are not production profile-write support.

Installation before/after front-window IDs differed, while each window's active
tab IDs were unchanged. No tab/window activation, URL navigation, keyboard or
clipboard operation was issued by the installer. Cause of the front-window change
is unproven; this sample does not establish complete focus preservation. Both
front-window and active-tab IDs matched throughout the successful actual editor
inspection. No claim about all future focus behavior follows from that sample.

## Validation and limits

| Check | Result | Evidence |
| --- | --- | --- |
| Exact-candidate backend regressions | PASS | 61 tests,7.58s; setup ACK/context plus existing background queue |
| Exact-candidate extension queue tests | PASS | 30 tests,0.186s |
| Isolated Chromium setup ownership | PASS | 6 cases,3.333s; adoption, lost responses, invalid intents; no chooser, no live Naukri request, owner selection unchanged |
| Isolated Chromium provider document load | NOT TESTED | Provider DNS blocked; browser cases test ownership, not loaded profile DOM |
| Actual installed profile/account/editor | PASS | Genuine loaded document and editor; approved identity match; no fill/Save |
| Profile skills update/persistence | NOT TESTED | Actual supported addition workflow still required |
| Saved PDF | PASS, previous real observation | Repeated installed checks at18:08:43 and18:38:53 matched actual100198-byte provider PDF to canonical bytes; not rerun by setup probe |
| Discovery/eligibility | OPEN | Retained-fact diagnostic at20:37:01:538 fact records of566 identities,0 fully eligible by diagnostic; not538 new provider reads |
| New application/independent receipt | BLOCKED | Zero new verified submissions; historical QTrino remains excluded |
| Recurring AUTOMATIC/restart/locked Mac | NOT ACCEPTED | First new receipt and critical live checks still required |

The diagnostic has overlapping exclusion reasons; these are not distinct job
counts. Policy remains all company stages, score50,14-day age, applicant
threshold1000 and unknown-count review. The once-asked lower-bound-count decision
remains pending; no exception was selected. No other platform, Gmail sending,
hosted Actions or merge was enabled.

Reproduce targeted checks from the exact candidate with its own environment:

```sh
.venv/bin/python -m pytest backend/tests/test_profile_setup_maintenance.py backend/tests/test_naukri_background_queue.py -q
pnpm -C extension exec node --test tests/naukri-queue.test.mjs
pnpm -C extension build
```

The isolated browser driver is `extension/tests/naukri-profile-setup.browser.mjs`.
Its tester dependencies were supplied from the canonical checkout only after byte
comparison of the candidate driver and six loaded extension modules. No mutable
dependency directory was symlinked into the installed candidate. Raw DOM, account
identities, private logs and rollback files remain outside Git. Next: implement
observed supported skill additions, continue real eligible discovery, obtain the
first new supported submission and independent receipt, then validate bounded
recurrence and actual locked/restart behavior.
