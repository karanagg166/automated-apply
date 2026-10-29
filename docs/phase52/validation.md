# Phase 5.2 targeted validation receipt

Final combined release evidence is in [final-integration.md](final-integration.md).
The earlier counts below describe the reviewed implementation before final AGY
integration; they were not rerun as complete suites.


All data-changing acceptance uses fictional fixtures. No full backend suite,
complete frontend regression suite, genuine employer fill/submission, real
Telegram delivery, credential change or hosted GitHub Action was run.

## Final unit and contract checks

| Check                                                        | Observed result                                                        |
| ------------------------------------------------------------ | ---------------------------------------------------------------------- |
| Backend: six affected test files below                       | 187 passed                                                             |
| Extension: `pnpm -C extension test`                          | 104 passed                                                             |
| Frontend: five affected test files below                     | 85 passed                                                              |
| OpenAPI export and `pnpm -C frontend api:types`              | Generated successfully                                                 |
| `pnpm -C frontend typecheck`                                 | Passed                                                                 |
| Changed Python: isolated Ruff E9/F/I                         | Passed                                                                 |
| Changed frontend/extension formatting and `git diff --check` | Passed                                                                 |
| `pnpm -C extension build`                                    | MV3 1.3.0; stable ID retained                                          |
| `pnpm -C frontend build --webpack`                           | Passed; isolated external dependency symlink requires webpack fallback |

```sh
python -m pytest \
  backend/tests/test_extension_tasks.py \
  backend/tests/test_browser_forms.py \
  backend/tests/test_extension_answers.py \
  backend/tests/test_packet_telegram_questions.py \
  backend/tests/test_phase1_local_agent.py \
  backend/tests/test_phase2_telegram.py -q

pnpm -C frontend test \
  tests/extension-assistant.test.tsx \
  tests/extension-gateway.test.ts \
  tests/applications.test.tsx \
  tests/security.test.ts \
  tests/phase3-proxy.test.ts
```

Use an existing Python environment with backend dependencies. The engineering
extension test invocation sets `PYTHON` to that environment explicitly for real
native frame validation; no dependency installation is implied by this receipt.

## Focused browser evidence

| Script                                    | Observed evidence                                                                                                                                                                                                              |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `assistant-stack.browser.mjs`             | One complete real Chromium/MV3/native host/FastAPI/SQLite fictional journey: website retained field, existing value preserved, persisted receipt read through dashboard API, duplicate refused, cancel, explicit guard release |
| `assistant-native.browser.mjs`            | Seven isolated MV3/native host scenarios with fictional HTTP backend, including exact tab binding, retained fill receipt, duplicate refusal, focus change and genuine Chrome close/relaunch recovery                           |
| `network-guard.browser.mjs`               | Five actual DNR/controlled HTTP scenarios: GET/POST/direct form submit blocked, guard survives worker suspension, another tab unaffected, explicit release restores networking                                                 |
| `assistant-popup.browser.mjs`             | Nine fictional UI scenarios: exact origin prompt, separate inspect/prepare/review/fill, field selection, correlated question action, challenge block, cancel, explicit manual takeover                                         |
| `phase52-react.browser.mjs`               | Six actual installed React cases: five retained controls and one delayed reset detected                                                                                                                                        |
| `phase52-combobox.browser.mjs`            | Five real Chromium cases: exact visible option retained, reset/no selection rejected, detached/closed menu manual                                                                                                              |
| `phase52-steps.browser.mjs`               | One controlled two-step journey: three verified fields, old step rejected, duplicate employer dates distinct                                                                                                                   |
| `fill-races.browser.mjs`                  | 25 stale DOM/navigation/value/race cases; no submission or external writes                                                                                                                                                     |
| `site-forms.browser.mjs`                  | Eight fictional ATS-style form fixtures; zero form posts                                                                                                                                                                       |
| `unanswered-fields.browser.mjs`           | Existing Chromium preservation/manual-control journey passed                                                                                                                                                                   |
| `react-forms.browser.mjs`                 | Four legacy React cases passed during DOM branch validation                                                                                                                                                                    |
| Frontend `playwright.extension.config.ts` | One production-build dashboard Chromium journey with fictional API fixtures                                                                                                                                                    |

The native transport test uses a real Python length-prefixed host, origin/private
configuration/frame-size/capability checks and bounded offline behavior. The
native browser fixture and full-stack fixture install host manifests only in
fresh temporary browser profiles. Temporary native-test copies of the manifest grant only the fixture host. The
DNR HTTP test loads the production manifest with no host grants, proving that
Chrome recognizes the required block-only permission; its test driver makes no
native-host call. Employer DNS is blocked in
intercepted ATS-style native fixtures. The installed host/profile is untouched.

DNR evidence comes from a real loopback HTTP server without Playwright request
interception. It therefore measures actual blocked network requests, rather
than treating a mocked network response as proof of the submission guard.
It does not prove control of pre-existing streams or detached service workers.

## PostgreSQL concurrency smoke

`backend/scripts/verify_extension_tasks_postgres.py` ran against a fresh local
PostgreSQL 17 container using the already cached `postgres:17-alpine` image,
`--pull=never`, a random loopback-only port and a fictional password/database.
The container was removed in a finally block. It creates an isolated ORM test
schema; it does not apply migrations to any genuine database.

Four scenarios passed using independent SQLAlchemy sessions:

- Concurrent duplicate task creation produced one durable identity.
- Concurrent version updates produced one winner and one version conflict.
- Concurrent authorization consumption produced one winner.
- Different applications claiming one tab produced one owner and one denial.

One verified fill receipt persisted for the winning authorization. Every
submission flag stayed false. This checks current lock behavior on PostgreSQL;
it is not a receipt for production migrations or exhaustive database regression.

## Genuine sites and installation preservation

[Public inspection JSON](live-inspection.json) records five accessible genuine
forms and one expired posting. All five accessible forms had unverified widgets
and stayed read-only. The owner confirmed the exact Hevo proposal and explicitly
kept it read-only. No genuine field persistence is claimed.

Private hashes of the existing service definitions, host manifest/wrapper and
private configuration are checked before delivery. The primary checkout remains
on its original branch/commit with no edits. Existing release/rollback worktrees
are preserved. Review installation steps are in
[install-and-rollback.md](install-and-rollback.md).
