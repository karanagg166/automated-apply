# DevTools MCP installed; Naukri automation goal remains OPEN

Branch `fix/live-prepare-discovery-20261030`, [PR #48](https://github.com/karanagg166/automated-apply/pull/48).
The owner asked whether the goal was complete and requested DevTools MCP.
This report covers that setup; it is not an application-submission milestone.
Exact MCP verifier/setup implementation: [`0fa13dc1189ea34a68c4c353588cbbbbd8726e08`](https://github.com/karanagg166/automated-apply/commit/0fa13dc1189ea34a68c4c353588cbbbbd8726e08).

## Actual goal and installation state

At12:56:54UTC November4, a fresh online read found STOPPED117,1884 identities,
0 admitted Apply actions,0 new verified submissions and1 historical recorded
application. Other stages:1266 SKIPPED,599 NEEDS_INPUT,18 PAUSED. The source remains
ahead of the immutable installed runtime; do not equate documentation with deployment.

The [existing database repair report](naukri-any-skill-public-schema-20261104.md)
remains current: exact003 cloud DDL and its backup/restore decision are pending the
once-requested owner action. No migration was approved by the request to add MCP.
The queue was not started and no Apply/history/profile Save was replayed.

Installed app API/execution/Telegram/frontend remain
`ae66975691a75cb0a3a43010dcfdba26a5100128`; native414a260 and extension1.3.24/2c9d481
remain unchanged. Stable extension ID, profile/account binding, filters and all
historical releases/rollback files remain protected.

## DevTools setup and real protocol/browser verification

- Added global Codex stdio server `chrome-devtools` using the official package
 `chrome-devtools-mcp@1.12.0`, pinned after registry/CLI verification, through pnpm.
 Installed Node26.12.1 satisfies the package's published engine range; pnpm12.15.0.
 No application dependency or runtime component was replaced.
- An exact private config backup was retained first. Parsed before/after comparison
 confirmed that all other Codex settings, including Supabase MCP, were unchanged.
 The global private configuration/authentication files are not published.
- Configured a separate persistent **headless** browser profile under this app's
 developer-tools directory, with usage statistics and performance CrUX lookups
 disabled. No autoConnect/browserUrl/wsEndpoint or authenticated Profile8 profile
 was used. No remote-debugging switch or OS permission was changed.
- At13:01:01UTC, the registered server reported version1.12.0 and32 available tools.
 **Five actual checks passed:** protocol initialize/tool discovery; creation of an
 owned background about:blank page; DOM evaluation with actual HeadlessChrome;
 accessibility snapshot containing that DOM marker; close of only the owned page.
 This is real local MCP/Chrome evidence, using synthetic page content, with0 provider
 navigations,0 queue mutations and0 application submissions.
- Read-only metadata confirmed identical frontmost-application and personal Chrome
 window/active-tab IDs before/after. No owner URL/title/cookie, keyboard or clipboard
 access occurred. The helper avoids launching personal Chrome if it is closed.
 No MCP/browser helper matching this setup remained after the verification exited.
- Ruff E9/F/I and diff checks passed. No unchanged backend/frontend/extension suites
 were rerun. No throughput or resource improvement is claimed; there is no relevant
 before/after performance benchmark for adding a development connection.

The [setup guide](../chrome-devtools-mcp.md) and
[real verification command](../../backend/scripts/verify_chrome_devtools_mcp.py)
are reviewable in the repository. New Codex clients can load the saved configuration;
automatic refresh of this already-running conversation's native tool catalog was
NOT TESTED. Direct protocol/browser use was verified without a model turn.

| Requirement | Result | Actual limit |
| --- | --- | --- |
| Register DevTools MCP and preserve other settings | PASS | Exact private backup and parsed config comparison |
| Real MCP/browser connection | PASS |32 tools discovered;5 browser/protocol checks |
| Preserve owner Chrome focus and tabs | PASS | Before/after metadata equal; separate headless profile |
| Attach DevTools to authenticated Naukri Profile8 | NOT TESTED | Not configured; approved extension flow remains |
| Refresh current conversation's native tool catalog | NOT TESTED | New configuration/direct client verified |
| First new Naukri submission/receipt | BLOCKED | Existing cloud-schema action remains pending;0 new receipts |
| Recurring AUTO / locked/restart application acceptance | NOT TESTED | First receipt and critical live checks still required |

Reproduce the registered connection only:

```sh
codex mcp get chrome-devtools --json
.venv/bin/python backend/scripts/verify_chrome_devtools_mcp.py
.venv/bin/ruff check --isolated --select E9,F,I backend/scripts/verify_chrome_devtools_mcp.py
```

Rollback removes only the `chrome-devtools` registration through `codex mcp remove`.
Preserve its exact config backup and browser profile; do not overwrite newer Codex
settings or delete directories. The application queue/release/database rollback path
is unchanged. No hosted Actions, merge, Gmail send, other-platform activation,
release deletion or cleanup occurred. Private/raw evidence stays outside Git.
