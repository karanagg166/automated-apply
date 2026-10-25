# Phase 1 live verification and remaining acceptance

Phase 1 remains incomplete. The genuine backend and Telegram worker now use online Supabase PostgreSQL. No Phase 2 work or merge was performed. No job application, Gmail message, real Gmail draft, paid enrichment request or paid service activation occurred. Existing credentials were retained; only the approved first restricted-runtime credential and initially missing local/OAuth configuration were initialized.

## Real Supabase activation

Project `luvdmwnlwaqgvfwlmlom` was verified independently through the isolated CLI account, Codex MCP and a TLS-authenticated PostgreSQL inventory. CLI 2.122.0 lists the intended ACTIVE_HEALTHY project in ap-northeast-1. The old default account and unrelated project links remain intact. The Phase 1 checkout alone was linked. The bare CLI profile label had been interpreted as a configuration path; the verified setup uses a separate private profile file/home.

The read-only inventory found zero public tables, zero application roles and zero migration history before activation, plus the existing postgres-owned `rls_auto_enable()`/`ensure_rls` managed function and event trigger. After exact comparison and final owner approval, bundle SHA-256 `2887a98812a797c3ef9d10f37fe5f14959778d802e126d0170776059ccee6a9e` committed exactly once on 2026-10-25. All 47 tables have forced RLS and exact restricted grants. The managed function/trigger definition is preserved and client EXECUTE grants were removed. No historical migration checksum changed. Supabase's CLI migration ledger still has zero entries: the directly executed bundle is documented through activation and catalog evidence, without fabricating historical migrations.

The initial operator stopped after commit because the session pooler's upstream connection reported `pg_stat_ssl=false`, despite verified client TLS. The direct IPv6 endpoint is reachable and passes hostname/official-CA verification, TLS 1.3, server-side SSL and every catalog/role/grant/RLS check with the same initialized `job_agent_runtime` credential. No TLS check was weakened and no migration or credential initialization was repeated.

A harmless preference timestamp persisted through an actual FastAPI restart, then its original value was restored. Real runtime attempts to delete audit/preferences, read Auth users and execute the managed RLS function were denied. Supabase security advisors returned no findings. The genuine API listens on loopback port 8000, the owner dashboard on 3000, and per-user launchd services use the stable private Application Support runtime. The five-connection runtime limit is preserved: two pooled API sessions, one worker session plus its lease, leaving one operator slot. Bounded catalog/queue deadlines account for measured network latency.

## Genuine account and browser evidence

| Connection | Verified result | Remaining acceptance |
|---|---|---|
| Codex MCP | Actual discovery of six read-only tools; URL, 47 public tables, extensions and zero CLI migrations read without a model turn | Preserve global allowlist and OAuth |
| VS Code MCP | Correct workspace configuration observed through VS Code extension APIs; supported start command available | Actual discovery/read call remains unverified; use MCP: List Servers → supabase-automated-apply → Start and verify get_project_url |
| AGY MCP | Named project entry disabled; old global entry preserved | Keep disabled until granular permissions are proven |
| Claude | Unused project setup removed; shared MCP retained | None; owner does not use Claude |
| Telegram | Actual owner-confirmed “Check whether Gmail is connected” and “Apply for Swiggy” replies, corresponding online audit and 16 sent outbox records | New remote locked-screen test pending; prior awake locked-screen test passed against the old local database |
| Gmail | Expected secondary identity/subject and exact metadata scopes verified through real Google OAuth; encrypted access/refresh tokens in online Supabase; actual refresh and identity check passed | Compose upgrade blocked by inherited SQL discriminator check; separate reviewed DDL approval and browser compose consent needed |
| Chrome/native host | Earlier owner Chrome preview correlated with stored audit; actual installed native executable reached the online backend and rejected an incorrect origin; genuine isolated Chromium MV3/native/Python/FastAPI/PostgreSQL restart smoke passed | Load stable extension folder, bind its displayed ID, real ordinary-page and non-sensitive Google Form gestures, reload/restart acceptance |
| Candidate/resume | One existing encrypted PDF decrypted safely and hash checked; ciphertext preserved in online Supabase with existing key and confirmed=false | Canonical profile is absent; owner must review actual facts and confirm the canonical resume. Drive source retained, sync disabled |
| Naukri, Wellfound, Instahyre, YC, Internshala | Official Connect/manual handoff and bounded gesture observation implemented; no cookies/passwords captured | Each account observation and owner acceptance of manual/unsupported capability remain pending |

The Telegram Swiggy request honestly returned no matching cached jobs. No vacancy was invented and no external search or application was claimed. Parsing, durable selection context, current eligibility/policy checks, packet preparation and bounded rate limits are tested; live discovery is not activated. Complex AI interpretation is optional and remains disabled while tool-free generation is unverified.

Gmail's dedicated Cloud project `automated-apply-166-20261025` has the Gmail API enabled and billing disabled, with External/Testing consent and the designated test user. Its Web client registers only `http://127.0.0.1:8000/api/v1/integrations/gmail/oauth/callback`. Secrets and the initialized encryption keyring stay in private configuration. The backend's existing compose upgrade hit the original `oauth_states_authorization_mode_check` allowing metadata/send only. [The separate tested constraint migration](gmail-compose-migration-review.md) adds compose without changing data, credentials, RLS or grants; it has not been remotely applied. Identity remains connected. `GMAIL_SENDING_ENABLED=false`.

AGY 1.4.7 authentication and discovered model/quota metadata pass. Exactly one additional owner-authorized fictional request failed without retry, bringing total individually approved attempts to three and validated structured answers to zero. Diagnostics found inline schema reference incompatibility and 60 tools advertised despite `tools: []`. The adapter now supplies a self-contained private schema file and refuses to transmit any prompt unless initialization proves zero tools. No further generation is authorized; no API/Cloud fallback or credit overage is enabled. Failed-attempt usage is unknown.

The ChatGPT Supabase plugin is separate and still needs owner-side reconnection for its ineligible linked account. Local credentials do not repair that connection.

## Executed checks

| Check | Result and scope |
|---|---|
| Full backend `pytest backend/tests -q` with owned PostgreSQL 17 | **1,472 passed, zero failed/skipped, 122.20 seconds**; XML/log retained privately in reports/phase1 |
| Frontend unit/typecheck/format/production build | **40 unit tests passed**; other checks passed; stable runtime production build also passed |
| Existing Playwright frontend journeys | **8 passed**, actual Next/BFF/FastAPI with fictional isolated data |
| Extension build/permission checks and event tests | **12 passed**; Chrome event transport simulated |
| Isolated Chromium/native/API/PostgreSQL lifecycle | Passed actual MV3, native framing, restricted SQL and actual API restart; context-menu events and Telegram transport simulated |
| Disposable managed Supabase-style schema | **47 tables**, exact forced RLS/ACL catalog, **5 denied operations and 12 rejected security faults**; unexpected function and replay refused |
| Separate compose follow-up on disposable PostgreSQL | Original failure reproduced; metadata/send/compose accepted; unknown mode, replay and missing constraint rejected; fixtures/faults rolled back |
| Filesystem installer checks | **5 passed**; private logs, preserved content, symlink/hardlink refusal and separate API logs |
| Focused backend after network deadline/pool changes | **180**, then **63** cases passed; final full suite includes these changes |
| Focused account/OAuth/foundation after follow-up preparation | **149 passed** |
| Compose identity/scope preservation and refresh regressions | **46 OAuth tests passed**, including compose success/rejection and schema-error recovery cases; provider transport mocked |
| Ruff E9/F/I and Bandit | Passed changed production/operator code; whole backend app scan passed |
| Secrets baseline / diff whitespace / generated API contract | Checked without provider verification requests; public SQL hashes explicitly classified, secrets remain untracked |
| Hosted CI | Initial PR #18 head ce883679 was green; f276bb2 backend and Phase 1 workflows passed. Latest e81aa51 checks are pending; see GitHub and readiness.json for exact run IDs. |

The suites retain rejection coverage for wrong account/project, profile preservation, privileged runtime, non-TLS connections, grant/RLS drift, OAuth state/PKCE/redirect/scopes, duplicate and unauthorized Telegram updates, unknown/malformed/injected intents, ambiguous selection and expiry, generation timeout/no retry/overage guards, native origin/framing validation and disabled submission/sending/enrichment. Mocked scenarios are not presented as live account evidence.

See [readiness.json](readiness.json) for each connection's configuration, authentication, verified scope, blocker, timestamp and next action; [live-evidence.json](live-evidence.json) for sanitized live results. Original worktrees and unrelated changes are preserved. Phase 1 cannot be declared complete until mandatory live checks and owner acceptance of manual-only platform capabilities are finished.

Repeated live compose clicks reproduced the inherited mode constraint failure. The service now rolls back that exact driver-metadata-identified failure and returns an actionable HTTP 409 setup requirement instead of a generic 500. The connected identity and encrypted refresh token are preserved; this error handling performs no DDL. Two additional regression cases verify recovery and the safe API response.
