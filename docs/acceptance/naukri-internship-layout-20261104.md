# Real internship metadata supported; first new receipt remains open

[PR #48](https://github.com/karanagg166/automated-apply/pull/48), branch
`fix/live-prepare-discovery-20261030`. **Naukri remains OPEN.**

An actual leased inactive Software Engineer Intern page displays `3 months
duration` in the element used for regular jobs' experience. Its structured posting
separately states a one-month experience minimum. Treating placement duration as
work experience, using the URL's range or inventing an upper experience bound
would misrepresent the employer's facts. The page also has an explicit separate
Remote widget and conflicting internship/permanent-employment evidence.

[Exact implementationb6b0690](https://github.com/karanagg166/automated-apply/commit/b6b069051cdddc26683e67ef64646a90a2a7f753)
recognizes that observed internship-duration layout only when the Internship badge
and a valid structured experience minimum are present. It retains that minimum,
leaves the unstated maximum null, recognizes the explicit Remote widget and keeps
conflicting work-mode/employment facts unknown. Existing regular experience
conflicts, missing/invalid minimums and ambiguous metadata remain held.

The queue enforces the known minimum against verified experience. It applies a
known maximum when present; any configured custom advertised-experience ceiling
still requires a known source maximum. This models a minimum-only requirement
without treating missing data as a fabricated range. It does not change the
owner's preferences, experience, skills or other application filters. The native/
API observation contract now accepts a nullable maximum; OpenAPI/frontend types
were regenerated. No database schema migration was needed.

## Validation and actual installation

- Source:140 relevant queue/submission/questionnaire/catalog regressions passed
  in21.98 seconds. The exact immutable candidate independently passed the same140
  tests in24.00 seconds; these overlapping counts are not added together.
- Parser:54 Node tests passed, including six new internship/missing/conflicting
  metadata cases. The exact candidate independently passed54 in1.275 seconds.
- Replaying the genuinely captured page with the actual new parser returned
  `job_facts`, minimum1/12 year, maximumnull, remote, employmentnull and applicants
  minimum100/maximumnull. This is real captured-DOM evidence with zero provider
  requests; it is not a new live observation or application.
- Frontend typecheck, generated contract, Ruff E9/F/I, Prettier, syntax/build,
  `pip check` and diff checks passed. The stable extension ID and permissions are
  unchanged. The prior44 isolated execution/control checks were not rerun because
  that execution module did not change in this candidate.
- Actual coordinated installation passed at15:19:33UTC November4: API, execution,
  Telegram, native host and extension1.3.26 all point to exactb6b0690. Frontend
  remainsae66975; no frontend behavior changed in this update.
- Queue STOP121,1,924 retained records, full online003 catalog audit, ready200,
  frontend200, fresh native reconnect, profile5 and approved account binding1.
  Stop plus its subsequent verification took7.594 seconds; this is not an isolated
  Stop response timing. Protected environments/frontend files stayed exact, and
  Chrome front-window/active-tab snapshots matched.
- Exact priorae66975 service plists, native414a260 wrapper and all24 extension
  1.3.25/2959cd7 files remain in the verified rollback inventory. Failure rollback
  restores those exact components under STOP with current online003 catalog; it
  never restores old database rows, narrows worker history or replays an action.
- Actual installed dashboard Start returned RUN122 with score50, any verified
  listed skill,14 days,1,000 applicants, unknown-count review and the unchanged
  lifetime-one/hour-one SUPERVISED scope. Zero unexpected frontend requests.
- A single audited batch scheduled20 ordinary fresh reads of never-attempted
  junior parser-held identities. It added no eligibility claim, packet, Apply
  authority or quota. Historical QTrino and the uncertain internship were excluded.
  Those reads are being observed through the normal installed worker and filters.

| Acceptance | Result | Evidence / remaining limit |
| --- | --- | --- |
| Genuine internship layout diagnosis | PASS | Actual leased inactive page; separate duration/minimum/Remote evidence |
| Parser and minimum-only requirement enforcement | PASS |54 parser/140 backend tests, genuine captured DOM replay |
| Exact coordinated release/rollback and actual dashboard | PASS | STOP121/1924, ready200, native reconnect, preserved focus/data; RUN122 |
| Fresh portal parsing through installed worker | IN PROGRESS |20 ordinary reinspection reads; no eligibility assumed |
| First new application / independent persistent receipt | NOT ACHIEVED | Zero committed Apply admissions/new verified receipts at last checkpoint |
| Recurring AUTOMATIC / restart / locked application acceptance | NOT TESTED | First worker receipt remains a prerequisite |
| Other platforms / contact-provider workflows | NOT TESTED | Disabled; Naukri first |

Reproduce source checks with:

```sh
node --test extension/tests/naukri-observation.test.mjs
.venv/bin/python -m pytest backend/tests/test_naukri_background_queue.py \
  backend/tests/test_naukri_submission.py backend/tests/test_naukri_questionnaires.py \
  backend/tests/test_application_queue.py backend/tests/test_public_worker_catalog.py -q
.venv/bin/python backend/scripts/export_openapi.py
pnpm -C frontend api:types
pnpm -C frontend typecheck
pnpm -C extension build
git diff --check
```

The [online repair/recovery](naukri-online-worker-repair-20261104.md) and
[follow-control](naukri-follow-control-20261104.md) evidence remains separate from
submission acceptance. Next: finish actual fresh reads, prepare/fill/submit one
eligible supported direct application and independently verify its persistent
history before bounded AUTO. No Gmail send, other-platform activation, CAPTCHA/
rate bypass, hosted Actions, merge, cleanup or release deletion. Raw candidate,
account/resume, DOM, restore and installation evidence remains private.
