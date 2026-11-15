# Expanded platform scope and official Himalayas MCP — 2026-11-15

Implementation [`4b9c05add5eb558b6c08408dc38c6b0c7e19ca9d`](https://github.com/karanagg166/automated-apply/commit/4b9c05add5eb558b6c08408dc38c6b0c7e19ca9d),
branch `feat/rust-agent-runtime`, [draft PR50](https://github.com/karanagg166/automated-apply/pull/50),
base `chore/uv-python-tooling`. Pending packet-generation changes are separate and are
not claimed as part of this configuration/scope implementation.

Recorded the owner's added HiringCafe, Himalayas, Wellfound, YC Work at a Startup and We
Work Remotely requirements, including necessary account creation with verified saved facts
and project MCP adapters. Existing Naukri, Instahyre and Internshala work remains. See
[the implementation/acceptance plan](../plans/expanded-platforms-20261115.md).

Registered Himalayas' documented Streamable HTTP server in `.vscode/mcp.json` without
credentials, a new process or dependency. Official sources:
[MCP reference](https://himalayas.app/docs/remote-jobs-mcp),
[server](https://mcp.himalayas.app/), [API](https://himalayas.app/docs/remote-jobs-api).
Public job/company/salary tools are separate from OAuth account/tracker operations.

| Check | Result | Exact actual evidence / limit |
| --- | --- | --- |
| Native public HTTPS initialization | PASS | One request, HTTP200, SSE JSON-RPC id1, protocol2025-03-26, server1.0.0 |
| Native tool discovery | PASS | One request, HTTP200, JSON-RPC id2,78 tools; response75,028bytes |
| Native public job search | PASS | One request, HTTP200, JSON-RPC id3, `isError=false`; Rust/India/entry-level/page1/recent search reported five jobs; response6,444bytes |
| Protocol request total | PASS | **3 actual public requests,0 fixture requests**, no account token or write tool |
| Config JSON / fixed official endpoint | PASS | Local JSON parse and exact configured HTTP URL verified |
| New automated regression tests | NOT TESTED | None added for this reversible configuration change; retained source2ffe01b baseline is139 standard+158 PG, not a new run or proof of these platforms |
| Native project ingestion/tool curation | NOT TESTED | VS Code registration and protocol calls are not the Rust runtime adapter/queue integration |
| Account inventory/creation/OAuth | NOT TESTED | No existing-account absence inferred; no account created or connected in this milestone |
| Real employer form/upload/submission/receipt | NOT TESTED | Five search results are not locally eligible applications or receipts |
| Physical browser/account handoff | BLOCKED | Retained owner unlock/profile-open or Brave sign-in step remains pending; no repeat request or launch |
| Mac CPU/RSS/GPU/latency comparison | NOT TESTED | Native request timings/resource counters were not collected |
| Full project completion | FAIL | Rust/lifecycle/browser/platform/installed/resource acceptance is incomplete |

The official documentation lists79 tools; actual discovery returned78. Use the observed
tool schemas rather than assuming the documentation count. The selected public search
needed no API key or account. The project runtime still needs a bounded jobseeker tool
allowlist and separate owner approval for account/application changes. Employer/recruiter
tools are outside its default scope. A connected-plugin search returned unrelated
providers, so this uses the official endpoint instead of installing an unrelated plugin.

Other verified starting points: [HiringCafe](https://hiring.cafe/) currently redirects to
`hiringcafe.com`; [Wellfound](https://wellfound.com/) exposes candidate sign-up/browsing;
[YC Work at a Startup](https://www.workatastartup.com/) is the intended YC platform;
[We Work Remotely's official RSS documentation](https://weworkremotely.com/remote-job-rss-feed)
provides an attributed feed. These observations are not working account/application
adapters. Preserve attribution and original employer links when implementing discovery.

Reproduce public protocol checks with a20s bound and1MiB response limit, `curl --proto
'=https'`, JSON content type, `Accept: application/json, text/event-stream` and protocol
header2025-03-26 against `https://mcp.himalayas.app/mcp`. Send `initialize`, `tools/list`,
then `tools/call` for `search_jobs` with the filters above. Parse SSE `data:` JSON; a200
status alone is insufficient. No redirect, account or write call is needed. Exact private
captures are ignored under `.local/himalayas-mcp-{initialize,tools,search}.{headers,response}`.
No raw provider payload, environment file, token or candidate facts are published.

Next finish shared Rust packet review/generation/handoff/execution, then bounded native
Himalayas/WWR public discovery and each remaining site/account/form/receipt adapter.
Preserve per-platform STOP/review/quotas, deduplication, identity/resume checks and honest
per-platform acceptance. No purchase, application admission, quota reset, browser focus
change, Gmail send, hosted Actions, merge, cleanup or duplicate source/build was performed.
