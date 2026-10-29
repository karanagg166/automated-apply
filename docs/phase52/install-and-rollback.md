# Phase 5.2 installation and rollback

The installed runtime still points at release
`0384fb403618c396fa60c7fb79a6b4ecebafa925`. Nothing in this PR installs or activates
an upgrade, changes a credential, grants Chrome permission, or restarts a service.
The stable Chrome extension ID remains `gdjbmkffcpicbpiikcohlmokkmcpipgp`.

## Review/build without installation

Use the exact reviewed PR head, not a mutable worktree with other edits. The
engineering checkout is the linked worktree
`/Users/karanagg/Desktop/Projects/automated-apply-phase52-final`, branch
`integration/phase52-final-20261029`. The primary repository remains untouched.

```sh
pnpm -C extension build
```

This writes the ignored `extension/dist/` bundle. It does not load Chrome or
change an installed extension. The build validates stable identity, MV3 and the
permission boundary. Native messaging, activeTab, storage, scripting and context
menus are unchanged permissions. Optional `https://*/*` is a declaration for
per-origin prompts, not an automatic host grant.

## Activation after separate owner approval

Use the existing [immutable release and service upgrade procedure](../phase1/owner-upgrade-and-acceptance.md).
Its backup/freeze, private file modes and restore steps remain applicable. The
backend, frontend and extension must be upgraded together for the new task
commands and typed dashboard routes. An old backend cannot accept the new task
commands; the popup will report an unavailable connection.

1. Record the exact reviewed PR head SHA. Create a detached linked release
   worktree of the same repository under `~/Library/Application Support/Automated Apply/releases/<SHA>`.
   Preserve the installed `0384fb4…` release and all earlier rollback directories.
2. Back up the current API/Telegram/frontend service definitions, native host
   manifest/wrapper and private environment file into an owner-only directory,
   preserving existing encryption keys and credentials. Do not generate new keys
   or copy candidate information into the release repository.
3. Prepare the release's pinned Python environment and pnpm dependencies using
   the existing release procedure. Run the targeted checks in
   [validation](validation.md), build the frontend and `extension/dist`.
   A normal dependency installation should not use the engineering worktree's
   external node_modules symlink. `pnpm -C frontend build --webpack` is a tested
   fallback for an isolated engineering symlink, not a production requirement.
4. Generate and review native/service plans using the existing installer `*-plan`
   commands. Keep the approved database target, native origin, per-provider
   opt-in budgets, resume encryption keys and submission-disabled settings.
   No migration or change to genuine data is required by this PR.
5. Apply the reviewed service/wrapper changes, restart only the approved local
   services, and manually load/reload the reviewed release's unpacked
   `extension/dist` in `chrome://extensions`. Verify the unchanged extension ID.
6. Open Connection settings and check the host. On a saved application, first
   review its exact company/role/destination; Open Application then requests
   Chrome access only to that origin. Declining leaves toolbar gesture access
   available. No tab enumeration, cookies or personal profiles are needed. The separately approved declarativeNetRequest permission must be reviewed at installation because Chrome forbids optional declaration of this API. It supplies blocking rules only after an explicit Fill action, for the bound tab.
7. Run the fictional smoke first. On genuine forms use Inspect/read-only
   proposals. Do not fill the Hevo proposal: the owner explicitly kept it
   read-only. Any genuine fill needs new exact destination/field authorization,
   fresh packet review and demonstrably safe challenge state.

Input/change/blur events are separately opt-in. Guarded filling blocks new
network requests and navigation from the bound tab, including autosave and
direct form submission. After inspection, the separate Return browser control
action restores networking for manual use and warns about page-scheduled
requests. Pause/Cancel deliberately retain the guard. Pre-existing streams and
independent background channels are outside this guard's demonstrated scope;
service-worker-controlled eventful pages remain read-only.
There is no genuine employer submission button or unattended mode here.

## Rollback

If native connectivity, dashboard contracts or recovery checks fail, pause/cancel
the affected task and stop the newly activated local services. Restore the
backed-up service definitions and native wrapper/manifest to the preserved
`0384fb4…` release, restart those approved services, then manually reload that
release's extension bundle. Confirm host health and the existing approved
profile/resume. Preserve private logs for diagnosis.

No database down-migration is needed: new tasks, plan metadata and audit events
use existing JSON storage. Keep the audit rows; never erase verified receipts or
reset approved answers as part of rollback. The old release does not understand
new task controls, so do not attempt to resume a Phase 5.2 fill through it.
Chrome's per-origin grants may be revoked explicitly in extension site-access
settings. Removing a grant does not undo values already delivered to a website.

The engineering session recorded private file hashes for the installed service
plists, native wrapper, host manifest and private configuration, and verifies
those hashes before delivery. That inventory stays in ignored `reports/` and
contains no credential contents. No private backup was committed.
