# Genuine Naukri skills Save verified; applications remain OPEN

Branch `fix/live-prepare-discovery-20261030`, [PR #48](https://github.com/karanagg166/automated-apply/pull/48).
Implementation [414a260](https://github.com/karanagg166/automated-apply/commit/414a260a01b94609bc71eddd2bb037fbb274c3b9),
initialization correction [23c9fdb](https://github.com/karanagg166/automated-apply/commit/23c9fdbb374e40920b6a22df0c59b6d199d08039),
native frame regression [0b05202](https://github.com/karanagg166/automated-apply/commit/0b05202).
Times are UTC, November 2 unless stated otherwise. Raw private evidence is retained
outside Git; this report contains no account identities, resume or private DOM.

## Actual outcome

At09:36:07 the installed system persisted one skills Save intent. At09:36:21,
a separate provider document verified its exact expected result: **31 saved
skills, preserving all28 original skills and adding three confirmed skills**.
The recorded outcome is `SYNC_VERIFIED`, not an inferred success from a click.
The independent verification also downloaded the provider-saved PDF and matched
its actual100198 bytes/checksum against the canonical PDF. The approved Naukri
account binding and canonical profile version5 remained unchanged.

The skills permitted by the canonical profile exceed the portal's available
capacity. This operation added only values that fit the actual input limit;
it did not remove skills or attempt to stuff the complete75-skill local list
into the provider field. No assertion is made that all missing profile fields
are complete. Projects still need supported verified date/status facts, and
other unsupported/unconfirmed fields remain explicit.

**Zero new verified job applications at the latest checked dashboard.** This is
real provider profile-write acceptance, not application or24/7 acceptance.
QTrino remains the one historical application and is never replayed.

## Behavior

The adapter uses the actual observed Key skills form and ordinary blur-to-chip
behavior. It preserves each original chip, adds only approved canonical skills
within the current `maxlength`, and never assigns hidden provider values or
calls a private provider endpoint. It uses DOM input/change/blur events in its
own inactive tab, without owner keyboard/clipboard or selecting a tab/window.

Preparation and Save are separate. The prepared exact chip list returns to the
server; the server checks the unchanged confirmed profile, account, browser,
policy and document plus add-only preservation, then durably records Save intent
before its short permit. A lost/uncertain Save is reconciled, never replayed.
Verification requires a different provider document and matching final skills.
A partial-capacity Save can be verified even though the complete canonical list
still differs. Summary approval and skills approval are separate dashboard
controls. Current write scope is skills-only, pinned to profile version5;
profile checks retain1800seconds and actual saved-PDF verification.

## Exact installed components and corrected deployment evidence

| Component | Installed SHA/version |
| --- | --- |
| API | `414a260a01b94609bc71eddd2bb037fbb274c3b9` |
| Frontend, including actual launcher target | `414a260a01b94609bc71eddd2bb037fbb274c3b9` |
| Native host | `414a260a01b94609bc71eddd2bb037fbb274c3b9` |
| Extension | `23c9fdbb374e40920b6a22df0c59b6d199d08039`,1.3.20, all24 files verified |
| Execution and Telegram | `2ceea5e4ab5662e041a58c6ec7d4aa73e86d51f7` |

Stable extension ID remains `gdjbmkffcpicbpiikcohlmokkmcpipgp`. Credentials,
approved binding, profile, queue filters and historical/uncertain outcomes were
preserved. Every replacement used a stopped queue, exact component snapshots,
protected-file checks and retained rollback inventories. No release was deleted.

The initial1.3.19 real run refused `profile_skills_input_unsupported` before Save.
A bounded initialization wait and more precise input refusal codes were added;
the precise initial failing input state was not captured and is not claimed as
proven. A real follow-up probe observed one correct combobox without modifying
it. Isolated regression covers delayed role initialization.

The next1.3.20 run prepared edits but hit `native_protocol_error`: the retained
native9cf6cb6 contract rejected `PROFILE_SKILLS_PREPARED`. A framed local
reproduction proved rejection by9cf6cb6 and acceptance by414a260. The first native
installation health probe omitted Chrome's required origin argument, failed and
restored the original wrapper under STOP92. A corrected probe supplied the exact
stable extension origin. Native414a260 installed successfully at09:34:14,
framed health15.256s, ready200, all663 records and other components preserved.
A preflight also rejected a stale expected error after Stop changed it to
`global_stop`; no replacement occurred in that preflight.

A rendered dashboard check caught another deployment defect: although the
frontend plist's WorkingDirectory named414a260, its Python launcher still started
cd342bf. The old launcher was retained, and a new exact414a260 launcher was
installed under STOP94. **Earlier HTTP200/plist-path evidence did not prove the
new frontend was running.** The corrected rendered check at09:38:25 verified the
separate controls and their actual saved states: skills checked, summary unchecked,
30-minute interval; age14, threshold1000, score50 and unknown-count review. It
issued zero writes/external requests, using isolated headless Chrome and a local
owner session; the password-login flow was not retested. Render took31.833s,
so frontend/backend responsiveness remains an unresolved issue.

The extension-only1.3.20 installation used STOP90 and verified readiness, native
reconnect, all24 files,568 records, protected services and equal front/active-tab
snapshots. The1.3.19 API/frontend installation likewise recorded equal focus
snapshots. These are bounded samples, not general focus/locked-screen proof.

## Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Exact414a260 backend candidate | PASS | 98 tests,15.44s; skills preservation/Save/reload plus profile sync/background/setup |
| Exact414a260 queue Node tests | PASS | 33 tests,0.143s; staged preparation, lost preparation response, Stop before Save |
| Exact414a260 dashboard unit tests | PASS | 9 tests; independent field approvals and interval edits |
| Exact414a260 build | PASS | Own venv, pip check, frozen/offline pnpm install, frontend11.591s, extension same ID |
| Exact414a260 isolated skills Chromium | PASS | 7 cases,13.092s, no chooser/external request, original tab selection unchanged |
| Exact23c9fdb isolated skills code | PASS | 8 cases,14.481s; candidate bytes matched all loaded source modules/driver, exact snapshot built |
| Existing isolated browser regressions | PASS | 38 execution cases109.096s,6 setup2.198s,12 background21.499s; fictional provider/native evidence |
| Native framing/rollback regression | PASS | 33 tests,2.43s; includes new prepared-skills framing test |
| Ruff, type generation/typecheck, selected formatting, diff | PASS | Relevant changed files/contracts only |
| Genuine provider skills Save and independent reload | PASS | One durable Save intent,31 final/28 preserved, `SYNC_VERIFIED`09:36:21 |
| Genuine saved PDF and account | PASS | Exact byte verification on independent profile read, approved platform account binding |
| Actual new application/receipt | BLOCKED | No inspected eligible application admitted;0 new verified receipts |
| Recurring AUTOMATIC, questionnaires, restart/locked Mac | OPEN / NOT ACCEPTED | Requires first real supported submission and further critical checks |
| Performance | FAIL / OPEN | Actual read timeouts; dashboard31.833s; native health15.256s; no timeout/pool-limit increase |

Counts overlap across suites; do not sum them as unique tests. Isolated Chromium
fixtures cannot prove a live provider Save; the separate genuine observation above
provides that evidence. The frozen candidate has its own environment/build outputs;
no mutable dependency directory was symlinked into a release.

At09:38:16, a retained-fact diagnostic analyzed584 records among670 identities
and found0 fully eligible by its conservative diagnostic. This is not584 new
provider page visits. Several strong matches remain held by lower-bound-only
applicant counts; the previously asked decision remains pending, not assumed.
Other exclusions include required skills, experience, age and missing evidence.
Discovery continues; historical observations and filter holds are not applications.

Reproduction:

```sh
.venv/bin/python -m pytest backend/tests/test_profile_skills.py backend/tests/test_naukri_profile_sync.py backend/tests/test_profile_setup_maintenance.py backend/tests/test_naukri_background_queue.py -q
pnpm -C extension exec node --test tests/naukri-queue.test.mjs
pnpm -C extension exec node tests/naukri-profile-skills.browser.mjs
pnpm -C frontend exec vitest run tests/application-queue.test.tsx
pnpm -C frontend typecheck
pnpm -C frontend build
```

Next work is real eligible-job processing and first supported submission with an
independent receipt, ongoing performance diagnosis, supported remaining profile
facts/questionnaires, then bounded AUTOMATIC and genuine restart/locked acceptance.
Other platforms remain disabled, Gmail read/draft-only, no hosted Actions or merge.
