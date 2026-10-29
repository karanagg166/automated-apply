# Phase 5.2 dashboard extension contract

The application detail now reads the extension's persisted task independently
of the existing dedicated browser automation assistant. The extension remains
responsible for choosing an application tab, inspecting a page and authorizing
the exact reviewed fields. Dashboard Pause, Resume and Cancel affect that same
durable task. Resume does not authorize filling or submission.

## Audit findings

- The existing application detail had no extension task identity, browser-tab
  association, recovery state or retained-value receipt status. Its browser
  assistant reads the separate dedicated automation browser status, so it could
  not establish the current extension task's state.
- The owner gateway uses fixed paths and methods. New extension state routes
  required explicit allowlist entries; extending a wildcard proxy would expose
  unnecessary backend capabilities.
- The proposed completed-field counter initially included pre-existing values.
  Contract review with backend separated `counts.existing` from
  `counts.completed`; the latter must represent verified retained fill values.

## Agreed owner API

All paths below are under `/api/v1`. The frontend gateway continues to require
the private owner session, exact origin and mutation CSRF token; it supplies the
backend bearer server-side.

| Method | Path                                                   | Result                                   |
| ------ | ------------------------------------------------------ | ---------------------------------------- |
| GET    | `browser/extension-tasks`                              | Task array; read-only gateway capability |
| GET    | `browser/extension-tasks/application/{application_id}` | Exact task or `null`                     |
| POST   | `browser/extension-tasks/{task_id}/control`            | Updated task                             |

Control body: `{ action: "pause" | "resume" | "cancel", expected_version: number }`.
Cancel produces `FAILED_FINAL` with reason `owner_cancel`. A version conflict
refreshes saved state without retrying the mutation. No fill, authorization,
submission, tabs or cookies path is added to this gateway contract.

The displayed task contains exact application/job identities, packet revision,
profile version, company/role, destination/current URL, associated tab ID and
active state, browser connection, current step, lifecycle, challenge state,
counts, reason, next action and last update time. Mode capabilities explicitly
keep reviewed and unattended submission disabled. The shared TypeScript shape
is in `frontend/src/features/extension-assistant.tsx`; backend owns persistence
and the native protocol. Parent integration must regenerate OpenAPI types after
the backend contract lands.

## Presentation and recovery

The panel polls its exact application ID every five seconds while the page is
active. Query cancellation is propagated through the API helper. It never reads
unrelated browser tabs. A transport failure displays connection unverified and
prevents resume, while the last observed status retains its timestamp. A task
whose application or job identity differs is hidden and receives no controls.

Ready answers, pre-existing completed fields, verified retained field values,
missing answers, manual-only fields and validation errors remain separate.
Packet revision changes or unsaved edits prevent resume. Pause and cancel stay
available for a stale packet so the owner can stop an execution. Terminal
submission-unknown and final states receive no restart controls.

All five challenge states have explicit text. Widget presence stays unverified;
manual resolution requires supported site signals and a fresh inspection,
answer review and authorization. The panel provides no challenge manipulation
or employer submission control. Employer strings use React text nodes and
external links require HTTPS without embedded credentials.

## Focused validation

- `pnpm -C frontend typecheck`
- `pnpm -C frontend test tests/extension-assistant.test.tsx tests/extension-gateway.test.ts tests/applications.test.tsx tests/security.test.ts tests/phase3-proxy.test.ts`: 84 tests passed.
- Changed frontend files pass Prettier checks.
- Production build: `pnpm -C frontend build --webpack` passed. The default
  Turbopack build rejects this isolated worktree's dependency symlink outside
  its workspace root. No application configuration or dependencies were changed
  for the webpack build. Standalone tracing warns about the external symlink.
- `pnpm -C frontend exec playwright test --config playwright.extension.config.ts`:
  one focused Chromium test passed. It exercises the production application
  detail with fictional intercepted API responses, a challenge state, exact
  versioned pause, page reload and stale-packet resume rejection. It starts no
  backend/database and takes no genuine employer action. `next start` serves
  the worktree build for this fixture; it emits the existing standalone-output
  deployment advisory.

Screenshots contain only fictional fixture data:

- [Challenge state](screenshots/extension-dashboard-challenge-fictional.png)
- [Stale packet after reload](screenshots/extension-dashboard-stale-fictional.png)

These dashboard observations do not demonstrate real-site form filling or
backend database persistence; the extension/backend acceptance receipts cover
those separate contracts. No full frontend regression suite, live Telegram,
owner database, private credential changes or hosted CI was used here.

Final integration adds an observed per-task network_guard_active indicator and
explains how to return browser control through the extension. The dashboard
cannot release Chrome's rules itself. Its dedicated regression raises the
focused frontend count to 85. Final OpenAPI types are regenerated by the
integration branch.
