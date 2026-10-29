# Phase 5.2 backend/native contract

Base: `0384fb403618c396fa60c7fb79a6b4ecebafa925`. No schema migration, installed release change, genuine employer write, real Telegram send or private credential change.

Audit findings: the existing native origin and bearer boundary, single-use fill plans, profile/resume freshness, packet answer revisions and owner reply-to-message checks are reusable. Missing pieces were durable Chrome tab ownership, browser-session scoping, task lifecycle visible to the dashboard, extension questions on public ATS packets, a distinction between immediate assignment and verified retention, and a 16 KiB protocol cap too small for contextual forms. Previously employment fields could fall through to aggregate profile answers when their labels were repeated.

Native version 1 adds `open_application_task`, `get_application_task`, `update_application_task`, `ask_form_questions`. Task operations carry `task_id`, `expected_task_version`, `browser_session_id`, `tab_id`; creation requires `application_id` and browser session, and optionally an existing tab. Update accepts `task_event` (bind, navigation, refresh/refreshed, pause/paused, resume, cancel, tab_closed, recover/recovered, focus_lost/active_tab_changed, network_timeout, inspection_prepared, fill_started, fill_finished, guard_installed, guard_released, worker_restart) and optional `observed_url`/`plan_id`. `fill_finished` cannot assert success: it requires `record_form_fill` instead. The existing inspect/authorize/receipt commands accept task identity and return `data.task`. Once attached, a plan cannot be authorized through an unbound legacy request.

Task storage is private `OwnerPreference` JSON under `ext_task:<UUID>`, serialized using the existing durable owner row lock. The identity is deterministic per packet. Active job ownership and browser-session/tab ownership are exclusive. A new browser session must recover explicitly; recovery clears tab, plan and authorization and pauses. Navigation, refresh, focus change, closed tab, cancellation, network interruption and the existing global stop invalidate executable plans. Resume requires fresh packet/profile context, and filling requires fresh inspection and review. Stale version updates fail. Duplicate native requests never replay executable values.

Inspection adds semantic key, control identity, page step, completed-count and explicit challenge state. Contextual employment and education controls abstain unless an exact approved packet answer supports the specific contextual question. Names are never split: individual first/middle/last names require separately reviewed answers. Challenge widget, blocking challenge and unknown verification produce read-only plans. Widget disappearance is not backend proof of success.

Fill plans retain extension task and original authorization IDs. `FillReceipt.verification_method` defaults to `dom_assignment`; only `retained_after_blur` advances verified task status. Partial fills and validation errors remain NEEDS_INPUT. Receipt persistence never confirms submission. Cancellation preserves partial audit receipts without restoring execution rights. Pre-existing completed fields are counted separately from website-retained assistant values. Native request/response sizes and the authenticated Chrome HTTP body limit are 256 KiB, below Chrome's native response limit; field and action counts remain bounded.

Owner endpoints:

- GET `/api/v1/browser/extension-tasks`: task array.
- GET `/api/v1/browser/extension-tasks/application/{application_id}`: task or null.
- POST `/api/v1/browser/extension-tasks/{task_id}/control`: `{action: pause|resume|cancel, expected_version}` → task.

Responses are typed in OpenAPI. Task fields include exact packet/profile/context and answer revisions, company/role, current step and destination, Chrome session/tab identity and connection, counts, challenge state, authorization identity, bounded receipts and actual next action. Capabilities advertise ASSISTED_FILL only, with reviewed/unattended submission false.

Ask on Telegram is an explicit action. Actual unresolved questions are persisted as packet fields with semantic provenance, then queued through the existing question-only execution context and owner-authenticated bot. Each prompt includes employer, role, packet, execution, question and expected answer type; only reply-to-message owner answers can resolve it. ISO dates/months, numbers, email, HTTPS URLs and choices are validated. Answers remain pending review, update exact task answer revisions, retain step/tab, invalidate plans, and require fresh inspection. Sibling envelopes follow the same packet's new revision. An interrupted extension send is marked delivery_unknown and is not blindly resent after restart because Telegram does not provide a send idempotency key; dashboard answering/reconciliation remains available.

Limits: exact saved destination only; URL-changing steps or redirects require manual destination review. Same-URL multi-step forms resume by fresh inspection, never automatic continue. Extension resume upload remains owner-operated. No backend claim of universal custom calendar/framework support. Telegram factual truth remains owner attestation; no model fabricates unknown history or dates. Extension-native transport is trusted local evidence, not an independently signed employer receipt. Disconnected browser status becomes visible when Chrome reports recovery/connection events; this is not a permanent browser heartbeat guarantee. Fictional SQLite tests verify persistence and contracts locally; the final integration also exercises four locking scenarios against a fresh disposable PostgreSQL 17 fixture, as detailed below.

Integration followup: inspection now retains bounded manual control diagnostics
and page manual reasons, so dashboard counts include custom controls rather
than only fillable fields. Receipt metadata includes whether the owner-approved
per-tab network guard was active. Guard installation/release status persists
on the task; release pauses a nonterminal execution, and can clear the guard
status after cancellation without reopening execution. A worker_restart event
records an uncertain fill outcome, clears the plan/authorization and pauses.
Native polling also pauses FILLING when candidate/packet context changes.
Global stop acquires the owner lock before plan rows and retains consumed
extension plans only for eventual partial audit receipts, never authorization.
The integration verification includes four disposable PostgreSQL 17 race
scenarios; see validation.md for exact scope and final counts.
