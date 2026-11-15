# Expanded job platform delivery

Owner instruction,2026-11-15: include HiringCafe, Himalayas, Wellfound, Y Combinator Work
at a Startup (the owner's “y2 combinator”) and We Work Remotely. Create accounts where
missing and necessary, using verified saved facts; add project MCP tools/adapters where
useful. Continue the full Rust/agentic project to completion. Existing Naukri, Instahyre
and Internshala scope remains. No new application count or recurring activation is
inferred from adding a platform.

| Platform | Verified public source / starting point | Implementation and live acceptance |
| --- | --- | --- |
| HiringCafe | [Official site](https://hiring.cafe/) currently redirects to `hiringcafe.com`; current public page offers account creation and original job posting links | NOT TESTED: native adapter, account binding, actual employer form/receipt and recurring workflow |
| Himalayas | [Official API](https://himalayas.app/docs/remote-jobs-api), [official MCP documentation](https://himalayas.app/docs/remote-jobs-mcp), hosted `https://mcp.himalayas.app/mcp` | Official HTTP MCP registered in project VS Code config; native runtime allowlist, public discovery ingestion, account/OAuth and actual employer receipt NOT TESTED |
| Wellfound | [Official candidate entry](https://wellfound.com/) offers candidate sign-up and job browsing | Existing legacy labels/references are not accepted native discovery/form/receipt/account automation |
| YC Work at a Startup | [Official site](https://www.workatastartup.com/) | Existing legacy labels/references are not accepted native discovery/form/receipt/account automation |
| We Work Remotely | [Official public RSS documentation](https://weworkremotely.com/remote-job-rss-feed), `https://weworkremotely.com/remote-jobs.rss`; retain attribution and original links | NOT TESTED: bounded native feed ingestion, employer destination/form/receipt, necessary account setup |

Research used official sources. Himalayas documents unauthenticated job/company/salary
tools and OAuth for profile/tracker operations; tracking a role is not applying to the
employer. No password or API entitlement is inferred from public access. VS Code MCP
registration is configuration, not proof of successful runtime integration or account
connection. Actual native HTTPS validation during this continuation returned200 for
SSE initialization (protocol2025-03-26, server1.0.0),200 for the78-tool catalog, and200
with a non-error result for one public `search_jobs` query (Rust, India, entry-level,
page1), reporting five jobs. These are search results, not locally filtered eligible
jobs or applications. Documentation's79-tool total differs from the observed78; use
actual schemas rather than assuming the count. No account token or write tool was used.
Private raw captures remain ignored under `.local/himalayas-mcp-*`.
The project agent must retain a bounded jobseeker tool allowlist and owner
approval for account/application changes; employer/recruiter tools do not belong in its
default tool set. Existing tool-plugin discovery did not return a relevant installed
provider, so use the documented official endpoint and project adapters.

Delivery sequence: finish shared packet generation/review/handoff and native durable
execution; implement attributed Himalayas/WWR public discovery with limits, retries,
freshness and cross-source deduplication; implement each remaining official site adapter,
necessary account setup and profile binding independently. Feed success alone does not
establish application acceptance. Custom MCP tools must call these guarded services,
not bypass budgets, candidate identity, human review or receipt reconciliation.

For each platform, record actual public network behavior separately from fixtures;
account creation/login verification separately from stored status; employer form/upload
and durable receipt separately from local packet/tracker events. Preserve independently
editable OFF/REVIEW/AUTOMATIC settings, quotas, missing-fact questions, history and STOP.
Do not buy a plan, silently fall back to Chrome, copy cookies or disturb owner focus.
The separate pending physical browser/account handoff remains pending; continue source
work without repeating the question. Never bypass an OTP/CAPTCHA or replay an uncertain
registration/application intent.
