# HiringCafe connector listings and local import

Local branch `feat/rust-agent-runtime`, implementation `4161b16c800ef45cd0082def8a00a7a203e6c01a`.

The shared and VS Code MCP configurations register HiringCafe's published Streamable HTTP endpoint. An external research request verified the public search and detail tools are listed, and one search returned an attributed listing URL. The observed link has a title and employer slug followed by a 16-character posting ID. The project importer and packet selector now support that shape and the existing bare-ID format. [Official connector documentation](https://hiringcafe.com/documentation/hiringcafe-claude-connector)

Local import retains the original attributed source observation. Reimports with a changed slug can reuse the original job and observation, including a job keyed on a retained employer ATS URL. Conflicting employer destinations and ambiguous saved identities are refused. The dashboard links to the public listings and continues to require a reviewed import.

| Gate | Status | Evidence |
| --- | --- | --- |
| Official MCP research | PASS | Public tools list returned five tools, including `search_jobs` and `get_job_details`. One bounded public search returned a slugged listing. No account, personal search data or mutation was used. |
| Source and static configuration | PASS | Rust formatting, dashboard Prettier, parsing both MCP configurations, and Git whitespace checks completed. |
| Rust and disposable PostgreSQL | NOT TESTED | Two new fixtures cover connector URL shape, posting identity, alias reimport, attribution, conflicting employer links, and packet handoff. |
| Installed project and actual application | NOT TESTED | The external lookup did not run through the installed project. No live import, account change, employer form or application occurred. |
| Scheduled HiringCafe or Internshala collection | BLOCKED | Provider permission for recurring collection was not established. HiringCafe documents limits for conversational use. Available Internshala terms mention written consent for AI-related collection. [HiringCafe limits](https://hiringcafe.com/documentation/hiringcafe-claude-connector#limits) [Internshala terms](https://staging.internshala.com/terms/) |

Include the packet platform fixtures and `uv run --no-project python rust/scripts/run_postgres_tests.py` in the combined local gate. The estimate remains 58% complete and 42% remaining. Actual applicant identity, supported employer form handling and a verified application receipt remain open.
