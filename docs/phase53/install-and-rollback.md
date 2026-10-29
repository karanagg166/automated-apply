# Phase 5.3 installation and rollback boundary

This PR does not install anything. The API/frontend/native services remain pinned
to `8c1635139a8943e9c2b72f39c4db593e1ccaa5b5`. During supervision the owner manually
loaded that installed release's extension 1.3.0 into their chosen Chrome profile.
The proposed bundle is 1.3.1 and must not be loaded until separately approved.

## Approval and activation

1. Review and pin the exact Phase 5.3 PR head SHA. Obtain specific owner approval
   for its installation; PR creation or approval does not imply merge/installation.
2. Use the existing [immutable release procedure](../phase1/owner-upgrade-and-acceptance.md).
   Create a detached linked release worktree in the same primary repository.
   Preserve the current release, prior rollback directories, service/native files,
   private configuration, existing database target and encryption keys.
3. Install the pinned Python/pnpm dependencies inside that release and build
   frontend and extension. Do not deploy the engineering dependency symlink.
   No migration/DDL or credential/key change is required.
4. Generate and review the existing installer plan commands before applying
   separately approved backend/frontend/native-wrapper changes. Keep genuine
   submission, new provider budgets and background polling disabled.
5. In the owner-selected Chrome profile only, load the approved release's
   `extension/dist`. Verify version 1.3.1 and unchanged ID
   `gdjbmkffcpicbpiikcohlmokkmcpipgp`. Settings shows the loaded version and queries
   whether Chrome actually grants its network-blocking permission.
6. Permissions are `contextMenus`, `activeTab`, `nativeMessaging`, `storage`,
   `scripting`, required `declarativeNetRequest`, and new `alarms` (Chrome 120+). Optional `https://*/*` is a
   declaration for individual origin prompts, not blanket host access. Do not
   broaden permissions or add tabs, cookies, debugger, session export or credentials.
7. For each approved normal Chrome profile, connect through extension Settings
   using a distinct owner-visible label, then explicitly select one in the
   dashboard. Do not enable the command channel during installation.
   `CHROME_PROFILE_COMMANDS_ENABLED` remains false; activating it requires a
   separate owner approval, plus that profile's extension opt-in. The 30-second
   metadata heartbeat starts only after explicit connection. No genuine field
   permission follows from connection, selection or channel activation.
8. Verify native health through the extension in that same profile. A static
   unverified Settings line or an isolated fixture is not an installed connection
   receipt. Refresh Naukri pages before inspecting with changed DOM rules.
   After separate channel approval, read-only acceptance should Open an approved
   application in the selected job profile, switch to an unrelated tab/window,
   and Prepare that exact bound application without changing focus or filling.
   The isolated regression does not replace this installed acceptance.
9. Existing Naukri packets require refresh and fresh revision review because
   imported criteria/expiry now participate in their context digest. Preserve
   owner edits and approved source facts. Resume never restores old fill authority.
10. A genuine fill still requires a separately reviewed eligible form, exact packet,
   field values/sources, challenge evidence, possible side effects and specific
   owner authorization. Plain Apply may immediately submit; do not click it just
   to discover what happens. Real Telegram delivery requires separate exact
   question/chat approval and explicit Ask; do not start a new watcher for this test.

The tab guard is limited to new tab-associated requests. Existing streams and
independent background activity remain outside the demonstrated scope. Pause and
cancel retain the guard. Explicit Return browser control restores networking and
may release page-scheduled requests. Never describe it as universal isolation.

## Rollback

Disable the approved profile command channel, disconnect new bindings, pause/cancel
new tasks and stop only the newly approved services. Restore the
saved service/native definitions to preserved release `8c16351…`, then reload its
1.3.0 extension in the same owner-selected profile. Restore prior permissions only
through the owner's Chrome controls; keep genuine submission disabled.

Keep new jobs, packets, partial/unknown receipts and audit history. There is no
schema down-migration. Do not resume new plans through an old runtime. The old
Naukri automatic question queue/search-field behavior remains a reason to keep
that workflow manual during rollback; never use rollback as authorization to
send a question or fill a form.
