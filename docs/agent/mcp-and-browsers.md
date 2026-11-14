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
never grants submission authority. No submit, owner approval, browser navigation, Gmail
send or paid-provider execution tool is exposed. The existing runtime has separate
tools whose availability is reported honestly as migrated, disabled or not migrated.

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
