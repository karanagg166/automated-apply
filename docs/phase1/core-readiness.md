# Core Phase 1 readiness

The current milestone is **Core Phase 1 Ready**, separate from full platform onboarding. It requires all seven criteria below; accepting an AI limitation does not replace successful isolated generation. PR #18 remains draft and unmerged. Phase 2 has not started.

| Criterion | Evidence and current limit |
| --- | --- |
| Secure AI generation | **Blocked.** AGY 1.4.7 authenticated initialization advertises 60 tools, including shell and browser tools, despite the explicit empty tool list. The guard terminates before sending input. No new generation request was made. |
| Owner-reviewed profile and canonical PDF | **Pending owner.** The owner intends to review the dashboard; intent is not confirmation. The live inventory contained one checksum-valid encrypted PDF, no confirmed canonical version, and no saved candidate profile at the verification timestamp. |
| Projects and precomputed context | The existing PR #19 engine now has dashboard configuration/review controls, an explicit repository checkout allowlist, bounded periodic recomputation and approval invalidation. Actual committed-source changes and approved-only Telegram retrieval are tested. Live project names, checkout authorization and approvals remain empty. |
| Installed Chrome extension | A controlled Chrome for Testing 156 profile passed 13 checks, including real Google Forms, redirect, worker stop/recovery, popup, reload, restart, offline/recovery, duplicate coalescing and stale-origin rejection. Eight returned preview results exactly matched eight online Supabase JSON audit records. Installed native transport timeout classification was reproduced, fixed and verified with open stdin. Historical owner gestures remain separate evidence. |
| Telegram | Live polling is healthy. Approved project selection/retrieval and supported request routing pass deterministic tests. The live database has no approved projects, so live retrieval of owner project context remains pending configuration and review. No messages were sent by this verification. |
| Supabase and Gmail | Live restricted PostgreSQL 17.11, verified TLS/catalog, encrypted resume checksum and unchanged Gmail identity/exact compose scopes passed. No remote DDL, sends or draft creation occurred. |
| Final commit CI | The PR checks for the actual final head are authoritative. Local or prior-commit results do not satisfy this criterion. Final check URLs are recorded on PR #18 after pushing. |

## AGY investigation

The installed CLI exposes agent/model selection, sandbox/plan mode, streaming input/output, schema files and print deadlines. Its help exposes no tool allowlist or per-session configuration-file flag. Global configuration contains 65 agent files, two installed plugins, nine configured MCP entries, and SessionStart/BeforeTool/AfterTool hooks. Global permissions are broader than this application's policy. None were changed.

`backend/scripts/phase1/agy_isolation_check.py` creates a private disposable home and workspace with only the restricted primary agent, empty MCP configurations, no plugins/hooks, strict deny rules, sandbox enabled and `useG1Credits=false`. Metadata discovery proves that global agents, plugins and MCP configurations are absent there. This clean home terminates before authenticated tool initialization; it does not establish a usable authenticated provider. Temporary experiments with copies of only CLI-owned state did not restore authentication and were deleted. Keeping the real home while setting the discovered directory-override variables retained global agents/plugins/MCP entries and still advertised 60 tools; those variables did not establish isolation.

The exact limitation is **no demonstrated authenticated, tool-free headless session with the installed CLI and supported flags**. The observed behavior is that AGY 1.4.7 initializes and advertises all 60 built-in system tools (including shell execution `run_command` and browser automation tools) during main-agent headless sessions, ignoring `tools: []` declared in agent frontmatter. The backend initialization guard correctly intercepted the advertised tools and terminated with `provider_tool_use_denied` before sending any user input. Zero prompt events were sent, and zero model quota was consumed.

A separately isolated, free local-model alternative suitable for an 8 GB Mac has been prepared in `backend/app/ai/providers/ollama.py`. The recommended model is `qwen2.5:1.5b-instruct` (or `qwen3:1.7b-q4_K_M`, ~1.4 GB memory footprint, leaving ~6.5 GB RAM free on an 8 GB Mac, Apache 2.0 license, native JSON schema support). The provider enforces loopback-only binding (`127.0.0.1:11434`), single model concurrency, context length 2048, strict JSON schema validation, and zero tools or external network calls. In accordance with project instructions, Ollama is **not installed or activated**; it remains unconfigured until explicit owner approval. Once approved, marking AI generation working requires:
1. A real fictional generation test
2. Valid structured output adhering to `ModelAnswer`
3. A grounded project-answer test.

The existing billing check rejects API/Cloud/custom-provider billing and enabled G1-credit overage, while provider credentials are excluded from the child environment. The official documented default for `useG1Credits` is false. The metadata usage command reported zero model turns and zero tokens. No generation authorization was requested because the isolation prerequisite failed.

Structured-output handling now rejects malformed protocol frames, tool-bearing initialization and unterminated final tool frames. Existing schema inlining retains nested restrictions; terminal JSON is validated with Pydantic. Deadlines, stream-size limits, one-attempt behavior and process-group cleanup remain enforced. A fictional real generation and grounded project generation remain **unexecuted**, so valid provider JSON, grounding and length acceptance are not claimed.

Official contracts: [headless protocol](https://antigravity.google/docs/cli/headless), [agent frontmatter](https://antigravity.google/docs/subagents), [CLI flags and billing settings](https://antigravity.google/docs/cli/reference/).

## Profile, resume and project behavior

The existing encrypted PDF store and single resume-sync engine are preserved. Each manual PDF upload remains an immutable encrypted version. The dashboard exposes version checksums, permits reselecting an already confirmed PDF, verifies PDF checksums on download and confirmation, and switches canonical selection atomically against the expected current resource. A stale selection fails without demoting the existing canonical file. A canonical change invalidates the previous profile review, and the wizard records the new review after all selected resources are saved. No keys or historical encrypted versions are replaced.

Additional reviewed profile links use the existing candidate-resource endpoints, so deterministic link answers see the same values. Project extraction uses the existing candidate-context service. New claims and changed source revisions remain pending; deterministic summaries retain their `deterministic_extractive` label. Inferred or unevidenced facts cannot be approved. The owner supplies architecture, design choices, APIs, database, caching, deployment, challenges, personal contribution and references through the existing Markdown context templates. Empty fields remain empty.

`CANDIDATE_PROJECT_CHECKOUTS` maps exact GitHub repository URLs to explicitly authorized absolute local checkout paths. The API uses that map for manual builds and a bounded refresh task. Polling observes committed changes in those local mirrors; it never fetches, clones or executes repository code. Updates on GitHub become visible after the authorized mirror is updated. No live source is implicitly authorized by naming a project. Configure this map and project templates before claiming live project acceptance.

Live Drive downloading is now blocked before the default downloader runs, including manual HTTP checks and scheduled service calls. Enabling automatic checks through the dashboard is rejected. Existing version review remains available. The same engine is exercised with injected fictional adapters in tests; no replacement engine was created.

## Scope and evidence boundaries

Deferred without blocking core readiness: Google Drive OAuth/live PDF download; real Naukri, Wellfound, Instahyre, YC and Internshala connections; and actual job submissions. Existing manual-only acceptances remain intact and do not claim authentication. VS Code MCP acceptance and the historical six-example Telegram checklist remain separate follow-ups, not new core gates.

Real-browser tests invoke the extension entry point and exercise the rendered popup in a controlled profile. They do not claim new personal-profile toolbar/right-click gestures. Offline tests use a refused loopback endpoint; a separate actual FastAPI/restricted-PostgreSQL lifecycle stops/restarts the disposable backend and verifies persistence. Early failed probes are retained privately: a preview failure before detailed diagnostics, an incorrect form evidence-file argument, and a browser-target CDP command later corrected to a page session. They are not counted as passing runs.

Local test logs and private inventories stay under ignored `reports/core-readiness/`. No personal profile values, PDF contents, tokens or private Form URL are included in the public report. The full backend suite runs against disposable PostgreSQL 17; excluded live-provider, OAuth and real-submission exercises are documented separately from pytest skips.


## Owner-authorized current-browser follow-up

The owner subsequently authorized inspection of the current personal Chrome session. Native Chrome page automation inspected only portal navigation/sign-in controls; cookies, login state, chat content and form values were not exported. Account menus exposed supported visible sign-in indicators on Naukri, Wellfound, Instahyre and Internshala. Four observations and four owner-sourced audit records were persisted and reread with evidence type `owner_authorized_browser_dom_indicator`, preserving manual-only acceptance. They are not labeled as new extension-toolbar gestures or account/API authentication.

This reproduced a detector defect: Naukri's visible Logout link has an ordinary action URL without the word logout, so the original attribute-only selector missed it even with the account drawer open. Extension 1.2.1 accepts exact visible Logout/Log out/Sign out labels on interactive controls. Hidden controls, page prose and simultaneous login/logout indicators remain inconclusive. The fixed predicate still returns only enums. The public key, stable extension ID and permissions are unchanged; the installed owner extension was reloaded through Chrome's actual Extensions UI.

The packaged `extension/dist` build passed all 13 real Chrome checks. Nineteen extension tests passed. Eight returned preview results matched seven persisted audit records exactly because one repeated redirected URL was correctly coalesced. The earlier eight-distinct-record run remains historical evidence. YC reached `/application/personal` and remains unverified; no personal details or onboarding fields were changed or submitted. Instahyre still shows its onboarding page despite the observed browser session. Full portal onboarding and applicant APIs remain deferred.
