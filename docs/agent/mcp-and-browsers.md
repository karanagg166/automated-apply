# MCP, Telegram and browser setup

The Rust tool bridge uses the [official MCP Rust SDK](https://rust.sdk.modelcontextprotocol.io/),
pinned at 3.10.0. It runs one process with bounded stdio requests, two concurrent local
HTTP requests, a 64KiB incoming line cap, a 256KiB response cap and fixed API routes.
No model can provide an arbitrary URL, recipient, freeform Telegram message or policy
override. API authentication, verified-profile checks and the durable outbox remain
authoritative. Protocol errors never print private configuration or upstream bodies.

Build from the canonical checkout:

```sh
cargo build --locked --workspace --bins
target/debug/automated-apply-tools --config /absolute/path/to/owner.private.env
```

The config uses the same literal, owner-only file as the Rust host: start with
`backend/.env.example`, then the host settings documented in
[the runtime README](../../rust/agent-runtime/README.md). The bridge connects to the
explicit `RUST_AGENT_LISTEN` loopback address; it never opens a DB connection itself.
Do not point it at the legacy backend: the new Rust tool routes need the Rust host.
Loopback transport must match the host's existing TLS/proxy policy; it does not forge
forwarded TLS headers. Start the host only after its installation prerequisites pass.

## Available tools

| Tool | Actual scope |
| --- | --- |
| `runtime_status` | Runtime capabilities, including adapters still missing |
| `browser_readiness` | Passive Brave/Edge/Safari inventory; never launches a browser |
| `naukri_saved_jobs` | At most 50 saved Naukri jobs; no live discovery or application |
| `instahyre_saved_jobs` | At most 50 saved Instahyre jobs; no live adapter acceptance inferred |
| `match_saved_job` | Saved job/profile scoring; no caller profile override |
| `application_history` | Confirmed profile's bounded history |
| `telegram_status` | Enabled/binding policy without credentials |
| `telegram_notify_run` | Optional, when Telegram is configured; one fixed notice per existing run |

Website titles, descriptions and all tool content are untrusted data. A catalog entry
never grants submission authority. No submit, owner approval, browser navigation or Gmail
send tool is exposed. The existing runtime has separate
tools whose availability is reported honestly as migrated, disabled or not migrated.

The discovery bridge extension is source only and awaits the combined validation gate.
Eight additional default tools expose source registries, saved Apify metadata, original
job/startup/read UUID status and actual-query previews: `discovery_sources`,
`startup_sources`, `apify_status`, `discovery_run_status`, `startup_discovery_status`,
`apify_read_status`, `discovery_preview`, `startup_discovery_preview`. Status GETs and
previews cannot dispatch providers or reserve budget.

Private `RUST_AGENT_MCP_ALLOW_DISCOVERY=true` additionally exposes `discovery_run`,
`startup_discovery_run`, `apify_read_recover` and the three corresponding `_complete`
tools (`discovery_complete`, `startup_discovery_complete`, `apify_read_complete`).
Original PUTs require a caller-retained nonnil `run_id`, `consent:true` and `request`.
Paid requests also require `request.allow_paid:true` plus existing current saved
Actor/build/schema review and exact local budgets. No manual imports, alternate keys,
provider run/dataset targets or URLs are accepted by these tools. Unknown attempts retain
their UUIDs; use saved status instead of replacing them. Local completion only combines
retained findings/pages; provider read recovery needs a distinct retained
`read_request_id` and explicit consent, with the original allowance/spacing still enforced.
This flag enables discovery actions, not platform application admissions.

Separate `RUST_AGENT_MCP_ALLOW_METADATA_INSPECTION=true` exposes account and allowlisted
Actor metadata inspection. Both require `consent:true`; they share the host's durable
pacing and selected cache without enabling an Actor start. Optional group flags are
checked on direct calls as well as catalog discovery. They default to false and accept
only literal `true` or `false`.

Per-request deadlines cover the configured discovery host budget plus15 seconds
(outer plus5), metadata35 seconds (outer40), other requests15 seconds (outer20).
The two-request MCP limit and host's single long-request slot remain. No redirect,
proxy, automatic retry, new DB pool or unknown-action replay is added. Error context
contains only validated original UUIDs, never the search query or credentials.
The256KiB selected response limit can leave a large saved result available through the
dashboard/API while MCP reports a bounded response error; it does not undo its reservation.

Telegram reuses the existing Bot API, owner chat/user binding and durable outbox.
The notification ID is deterministic per run; repeated calls preserve `pending`,
`sending` or `sent`. An uncertain send is never reset. `queued` means local persistence,
not a Telegram delivery receipt. No live message was sent during implementation.

## Apify

The official server is registered in the owner's Codex configuration and
`.vscode/mcp.json` with only:

```text
https://mcp.apify.com?tools=search-actors,fetch-actor-details,search-apify-docs,fetch-apify-docs
```

These four [public tools](https://docs.apify.com/mcp#use-without-an-account) support
discovery/documentation without an actor run. A live initialize and tool-list check
verified HTTP 200 and exactly those four tools. Codex's add command also completed its
OAuth flow. That does not establish API credits or authorize spending. The endpoint
does not expose actor execution. Existing approved actor/run/dataset controls and
provider budgets remain necessary for application discovery through Apify. MCP config
changes may require a fresh client session before its catalog is visible.

A live public `search-apify-docs` call from the project laptop succeeded in
3.868 seconds, including initialization and tool listing. The catalog
contained the same four public tools. The call used the official public
endpoint and requested documentation without starting an actor.

## HiringCafe

The project VS Code and shared MCP configurations register HiringCafe's official
Streamable HTTP connector at `https://hiringcafe.com/api/mcp`. Use its public
`search_jobs` and `get_job_details` tools for conversational searches, then
review the posting and import its listing URL in the dashboard's HiringCafe
source. Public search needs no account. The connector documents rate limits and
separate approval for account reads. Employer applications are handled outside
the connector. [HiringCafe connector documentation](https://hiringcafe.com/documentation/hiringcafe-claude-connector)

A live public `search_jobs` call from the laptop returned a successful
response in 1.886 seconds, including initialization and tool listing.
The catalog showed two public tools. The request used the provider's
`search` argument and a limit of two. The signed-in tracker and employer
handoff still need their own live verification.

## Browsers

New browser-assistant defaults use `BROWSER_CHANNEL=brave`. `msedge` selects installed
Microsoft Edge; legacy explicit `chrome` and fictional `chromium` fixtures remain
compatible. Brave uses a fixed installed executable and never falls back. Existing
private environment overrides and installed releases are not changed by source defaults.
The Rust inventory selects `RUST_BROWSER_ENGINE=brave` by default, with `edge` and
`safari` choices. Inventory always requires fresh account, extension and focus validation
before reporting readiness. Brave is installed locally; Edge has not been installed.

Safari WebDriver uses actual automation windows; Playwright WebKit is not Safari.
The present Chromium DNS/network/native-messaging guards cannot simply be claimed for
Safari. Its live transport and complete OS focus acceptance remain blocked pending an
appropriate implementation. Do not start Safari automation or navigate browser settings
to work around the owner's focus constraint.

### Replace a fixed Chrome profile with Brave

The local `automated-apply-agents replace-fixed-brave-profile` command uses
the existing owner lock and fixed-profile selector. Run it with
`--config` and `--review` pointing to absolute owner-private files.
The default command previews the replacement. The same review with
`--apply` archives the old pin, disconnects the old binding, and selects
the confirmed Brave binding in one transaction.

Prepare the review from the current dashboard revisions and a fresh
independent check of the signed-in Naukri account and downloaded resume
bytes in the dedicated Brave profile. The review contains the old and new
binding UUIDs, selection revision, both browser profile versions, new
browser session UUID and window ID, current approved Naukri account
revision, confirmed candidate version, account and PDF SHA-256 values,
evidence SHA-256, observation timestamp, canonical private Brave profile
directory, and explicit owner confirmation. Keep the review local at mode
0600. The database checks the saved account and confirmed resume hashes and
rejects changed versions, expired observations, and active work. See the
[review JSON field names](../../rust/agent-runtime/src/browser_profiles/pin_replacement.rs).

The replacement keeps the legacy mapping in the private owner store and
leaves both application queues and the Rust coordinator stopped. It leaves
Naukri's existing account approval bound to the former profile. Use the
ordinary owner account approval on the newly selected profile after
confirming its live identity. The supervised attempt still requires the
current browser, account, resume, job and quota checks.

Reproduce the real Brave/fictional-page checks without a personal profile:

```sh
AUTOMATED_APPLY_TEST_BROWSER=brave pnpm -C extension exec node tests/naukri-execution.browser.mjs
AUTOMATED_APPLY_TEST_BROWSER=brave pnpm -C extension exec node tests/naukri-queue.browser.mjs
AUTOMATED_APPLY_TEST_BROWSER=brave uv run --no-project --python .venv/bin/python python -m pytest backend/tests/test_browser_engine.py backend/tests/test_browser_assistant.py -q
```

These launch isolated headless profiles, intercept fictional pages and never establish
real Naukri/Instahyre account or submission acceptance. Full platform/browser migration,
installed services, identity/PDF/history/policy/focus/resource checks and a genuine
worker receipt remain necessary before recurring automatic execution.

## Owner Naukri setup in Brave

The owned automation profile passed real Brave native messaging and profile connection
with commands disabled. A later reload temporarily left the extension marked as reloading;
subsequent cold-start verification restored its connection. Automatic setup now refuses
disabled extensions. Later checks report the Naukri grant present, but an unloaded
restored login tab still needs an actual signed-in account check. When ready, the owner can run from
the canonical project directory:

```sh
pnpm -C frontend exec node ../scripts/open_brave_owner_setup.mjs
```

This owner-invoked command opens the separate Brave automation profile interactively.
If **Automated Apply** is disabled, enable it in `brave://extensions`. Then open
`chrome-extension://gdjbmkffcpicbpiikcohlmokkmcpipgp/settings.html`,
click **Allow Naukri background page access**, and sign in to Naukri normally. Keep queue
commands disabled and close that Brave window when finished. The agent does not run this
interactive launcher or handle the owner's keyboard/clipboard. Credentials and cookies
stay in the same private profile. Real account binding and application acceptance follow
only after the owner completes this browser action. Failed automatic reload and repair
attempts are not accepted as unattended maintenance. No protected browser preference
file is edited to clear a disable reason. The temporary repair helper was independently
confirmed unregistered and its unreferenced files retired; it is not part of the product.

The subsequent windowless-profile native inactive/minimized-window experiment failed
focus acceptance. That creation path is suspended. Agent-side
`scripts/prepare_brave_login.mjs` now reuses an existing verifiable neutral window only,
refuses existing portal tabs/pending navigation and preserves any admitted intent.
It never launches or creates a window. A safe refusal is not successful login setup.
Preserve the restored Naukri sign-in tab; do not request the same owner setup again.
See [the actual failure and guard evidence](../acceptance/brave-window-focus-and-login-20261115.md).
