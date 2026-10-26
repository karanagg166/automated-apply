# Phase 1 operations

Use this branch's worktree. Do not copy another project's .env, encryption keys, Supabase project links or CLI tokens. All setup commands below are explicit owner actions. Application submissions, Gmail sends and paid calls remain off. No runtime SQLite fallback exists; SQLite appears only in isolated tests.

## Environment and startup

Python 3.11+ and Node 22+; npm remains the frontend dependency manager.

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
pnpm -C frontend install --frozen-lockfile
cp backend/.env.phase1.example ./phase1.private.env
chmod 600 phase1.private.env
```

Fill private values locally, preserving any existing encryption keys. The example deliberately contains no credentials. Do not paste secrets into chat or put them in NEXT_PUBLIC variables. Use configure_database.py after a reviewed runtime role exists; it uses a hidden password prompt and SQLAlchemy URL escaping. It preserves unrelated settings and never connects or runs DDL.

```sh
.venv/bin/python backend/scripts/phase1/configure_database.py --env-file ./phase1.private.env
.venv/bin/python backend/scripts/phase1/local_service.py preflight --env-file ./phase1.private.env
.venv/bin/python backend/scripts/phase1/local_service.py api --env-file ./phase1.private.env
```

The launcher binds 127.0.0.1, disables forwarded headers/access query logging, refuses enabled discovery/email gates and performs restricted database startup checks. No worker starts with the API. In another terminal configure the existing frontend owner password/session secret and server-only JOB_AGENT_API_TOKEN with backend origin matching LOCAL_AGENT_ENDPOINT, then:

```sh
pnpm -C frontend dev --hostname 127.0.0.1
```

The existing frontend/run.mjs reads backend/.env unless FRONTEND_ISOLATED=1. Prefer an isolated private environment for this worktree; do not point it at another project's backend. Existing docs/phase7 dashboard procedures cover password hashing. No backend token goes into client bundles. Connections and preference updates use the existing owner session/BFF/CSRF boundary.

Shutdown order: stop Telegram first, then frontend, then API with Ctrl-C/SIGTERM. Only stop processes you started. Use the `status` local_service action for sanitized database readiness. The disposable test API used for native verification is separate from live Supabase and contains fictional records only.

## Supabase

Project: `luvdmwnlwaqgvfwlmlom`; URL `https://luvdmwnlwaqgvfwlmlom.supabase.co`; JWKS `https://luvdmwnlwaqgvfwlmlom.supabase.co/auth/v1/.well-known/jwks.json`.

Existing owner credentials must be retained; rotation is not authorized. Supabase CLI 2.122.0 uses a profile configuration file here, so the bare label `--profile automated-apply` failed with `Unsupported Config Type ""`. The verified isolated account uses `~/Library/Application Support/Automated Apply/supabase-cli` and its private profile file, while the previous default account is preserved. Use `supabase_account.py` to prepare/check that profile and verify the exact project before linking this checkout. CLI management OAuth, MCP OAuth and PostgreSQL passwords are independent.

The actual read-only inventory passed on 2026-10-25: dedicated project, PostgreSQL 17.11, zero public tables, no application roles or migration history. Review [migration-comparison.md](migration-comparison.md) for the exact approved bundle and managed-function preservation. Final owner approval covers SHA-256 `2887a98812a797c3ef9d10f37fe5f14959778d802e126d0170776059ccee6a9e` and the first credential for the new restricted login. The bundle committed once. Never reapply it or run `db reset`.

System trust did not verify the project certificate. The official Supabase CA is stored privately with project configuration, without modifying global trust. The session pooler accepted certificate-verified client TLS but reported an unencrypted upstream in `pg_stat_ssl`; strict verification stopped. The direct endpoint `db.luvdmwnlwaqgvfwlmlom.supabase.co:5432` is reachable over IPv6 and passes both certificate/hostname checks and server-side TLS checks with the same initialized runtime credential. This is the selected runtime endpoint; no TLS check was disabled. Never use an administrator DSN as the application runtime.
The public bundle is for an empty dedicated project only, in one transaction; it refuses existing user objects, job_agent schema or colliding app roles. It never touches Auth/Storage system schemas. Keep Data API disabled if unused, or explicitly confirm that no application tables are exposed to anon/authenticated. Use direct or session-pooler port 5432 with verified TLS and the dedicated role; transaction pooler 6543 is rejected. Pooler username must carry this project ref. If a root certificate is required, configure DB_SSL_ROOT_CERT from Supabase's official connection panel. Do not disable verification for a live database.

## MCP clients

The project server is named `supabase-automated-apply`. Shared `.mcp.json` and VS Code's supported `.vscode/mcp.json` point to:

`https://mcp.supabase.com/mcp?project_ref=luvdmwnlwaqgvfwlmlom&read_only=true&features=docs%2Cdatabase%2Cdebugging`

The existing global Codex entry and its metadata-only `enabled_tools` allowlist are preserved. `execute_sql` and migrations are unavailable to it. Actual Codex discovery and harmless project/catalog reads passed without a model turn:

```sh
.venv/bin/python backend/scripts/phase1/verify_mcp.py
```

VS Code recognizes the workspace configuration, but actual tool discovery/read access is not verified. Minimal owner action if its UI is required: **MCP: List Servers → supabase-automated-apply → Start**, complete official OAuth/trust, then verify `get_project_url`. Configuration alone must not produce a connected badge.

The unused project `.claude/settings.json` was removed; no Claude registration is required. Shared configuration and unrelated global tools are retained. AGY's named project server stays disabled because granular restrictions are unverified; its older global Supabase server is preserved. General AGY prompts must not receive SQL/migration access.

ChatGPT's Supabase plugin authorization is separate. The connection named Supabase returned the exact target project URL in this session; Primary returned permission denied. Preserve the working connection and reconnect Primary only if you intend to use it. Local CLI credentials do not repair plugin authorization.
## Chrome Native Messaging

```sh
node extension/build.mjs
node --test extension/tests/*.test.mjs
```

Load `extension/` unpacked in real Chrome via chrome://extensions and record its ID. Configure CHROME_EXTENSION_ID and CHROME_NATIVE_MESSAGING_ENABLED=true in the private file. Plans/installations refuse existing targets rather than replacing another host.

```sh
.venv/bin/python backend/scripts/phase1/install_local.py native-plan --env-file /absolute/path/phase1.private.env --extension-id YOUR_EXTENSION_ID
.venv/bin/python backend/scripts/phase1/install_local.py native-install --env-file /absolute/path/phase1.private.env --extension-id YOUR_EXTENSION_ID
```

macOS manifest: ~/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.automated_apply.agent.json. Absolute wrapper: ~/Library/Application Support/Automated Apply/native-host. Exactly one allowed Chrome origin; no wildcards, content scripts, host_permissions, tabs permission, cookie access, CDP or shell dispatch. API bearer stays in private host config. Frames are versioned, capped at 16 KiB with bounded reads and HTTP deadlines. Page data never supplies an actor or executable instruction.

The toolbar previews the active page only after a click. Context menu label: **Apply with Automated Apply**. Settings has a Verify connection action that displays the actual backend endpoint returned through the host. Unsupported local/http/browser pages show an error. Unknown HTTPS pages are URL candidates, never claimed to have been inspected. No form answers, uploads or submit clicks occur.

Reload after updates. Test example.org and an owner-controlled non-sensitive Google Form. Confirm popup result and matching URL in local history. Backend offline produces a retryable error; retry is a new deliberate user gesture. The scripted bridge test simulates Chrome events. The lifecycle `--with-chromium-extension` option additionally launches a disposable Chromium profile with actual MV3/native APIs; it still cannot establish an owner-profile context-menu gesture. The owner has separately reported a real Chrome preview matched to the backend audit; Google Form and restart acceptance remain pending.

```sh
.venv/bin/python backend/scripts/phase1/install_local.py native-uninstall
```

## Telegram and locked Mac

Create a private bot with official @BotFather. The following owner-run interactive setup hides the token, calls getMe/getWebhookInfo, checks the webhook, waits up to 120 seconds for a fresh private `/start aa_…` challenge, and requires explicit numeric identity selection. Send the entire command printed in the terminal to the verified bot username, including its fresh challenge. Do not start a second poller during setup. Empty polls continue waiting, and positive-offset pagination handles older backlogs; observed updates are acknowledged by subsequent polling without executing their commands. No negative offsets or queue-drop methods are used. HTTP 409 identifies a competing getUpdates consumer; setup stops instead of stopping another service. A webhook conflict is reported separately and no delivery mode is changed. If setup times out, no owner IDs or token are saved. It refuses webhook conflicts; no deleteWebhook operation exists.

```sh
.venv/bin/python backend/scripts/phase1/configure_telegram.py --env-file /absolute/path/phase1.private.env
.venv/bin/python backend/scripts/phase1/local_service.py telegram --env-file /absolute/path/phase1.private.env
```

/start /help /ping /status /connections /jobs /apply <https-url>, plus ordinary messages such as “Apply for Swiggy” and “Check whether Gmail is connected”. Only the bound numeric owner and private chat are accepted. No group/forwarded commands or shell execution. Offset and bounded acknowledgment outbox persist in PostgreSQL. An ambiguous interrupted send stays `sending` and is never automatically replayed; the owner can inspect delivery history and issue a new /ping. HTTP 429 retries respect retry_after; network errors back off. A database advisory lock prevents duplicate workers. No personal resume, salary, email body or URL query appears in Telegram replies/logs. Simulated transports persist their evidence type and cannot create a live connection badge.

launchd is opt-in. The owner subsequently authorized installation; `com.automated-apply.telegram` is installed using the stable detached checkout `~/Library/Application Support/Automated Apply/phase1-runtime`, its own virtual environment, and private configuration `~/Library/Application Support/Automated Apply/phase1.private.env`. Its state is transferred to online Supabase only after the old worker releases its lease and every outbox item is resolved; offsets, operations and sent replies are preserved. Do not remove that runtime checkout while using the worker. The live services now use online Supabase; local acceptance databases are retained separately. Generic installation commands:

```sh
.venv/bin/python backend/scripts/phase1/install_local.py launchd-plan --env-file /absolute/path/phase1.private.env
.venv/bin/python backend/scripts/phase1/install_local.py launchd-install --env-file /absolute/path/phase1.private.env
launchctl print gui/$(id -u)/com.automated-apply.telegram
.venv/bin/python backend/scripts/phase1/install_local.py launchd-uninstall
```

Private user plist, explicit interpreter/worktree/env path, restart on failure, 30-second throttle, private sanitized logs in ~/Library/Logs/Automated Apply. Clean SIGTERM/SIGINT handling allows a bounded outstanding poll to finish. No global power settings are changed. Screen lock is compatible with an awake, powered, networked Mac; sleep, shutdown and network loss interrupt execution. The owner-assisted lock test can be observed using `monitor_locked_worker.py --env-file /absolute/path/phase1.private.env --seconds 300`: it reads macOS IOConsoleLocked plus the live polling timestamp and a newly sent pong. It never locks the screen, changes power settings, sends messages or prints IDs. No lock/reply observation is recorded as a pass until all three signals agree. Logs/config are preserved on uninstall. Existing credentials are retained.

## AI and Gmail

`agy --version`, `agy --help`, `agy models` and `agy agents` inspect local availability. The adapter strips backend credentials from subprocesses, verifies an exact private `tools: []` primary-agent profile, sandbox/plan mode, structured schemas, bounded stdin/output, process-group cleanup and no retry/fallback. It uses the owner's explicitly trusted private workspace at `~/Library/Application Support/Automated Apply/agy-answer-workspace`, with temporary private CLI logs. The installed CLI requires the uniquely named global profile; existing agents, MCPs and owner hooks are preserved. No resume-based generation is activated.

Authentication now passes via CLI-handled `/usage` with zero model turns. This is an official metadata command, not a generation prompt ([headless contract](https://antigravity.google/docs/cli/headless#unsupported-messages)). The checker refuses `disableSlashCommands=true`, which would turn `/usage` into ordinary prompt text, strips account text from reports, and checks zero model turns/tokens before marking authentication verified. It also refuses API/Cloud billing and enabled `useG1Credits`; the official default is false ([settings reference](https://antigravity.google/docs/cli/reference/)).

```sh
.venv/bin/python backend/scripts/phase1/agy_check.py
```

Three individually authorized fictional generation attempts have now failed without a validated answer. The third used AGY 1.4.7, the discovered `gemini-3.8-flash-high` model, a 120-second CLI deadline plus cleanup allowance, and no retry. Authentication still passes. Diagnostics found inline JSON-schema references were interpreted as file references; the adapter now writes a self-contained private schema file. A separate invalid-input diagnostic sent no valid user event and exposed 60 advertised tools despite the named profile's `tools: []`. The adapter now refuses to write any user prompt until initialization proves zero tools. Generation remains degraded and disabled; no further model request is authorized. Quota metadata does not establish usage of failed attempts.
```sh
.venv/bin/python backend/scripts/phase1/install_local.py agy-profile-plan
.venv/bin/python backend/scripts/phase1/install_local.py agy-profile-install
agy agents
.venv/bin/python backend/scripts/phase1/install_local.py agy-profile-uninstall
```

The dedicated free Cloud project `automated-apply-166-20261025` has Gmail API enabled and billing disabled. Its Web OAuth client is stored only in private Application Support configuration, with exactly `http://127.0.0.1:8000/api/v1/integrations/gmail/oauth/callback` registered. The secondary account is configured as the expected identity and a testing user. Consent is External/Testing with identity, email, Gmail metadata and compose scopes. Existing encryption keys are preserved; the initially absent OAuth keyring was securely initialized. These settings do not prove a connected account.

Gmail retains encrypted tokens/disconnect/state/PKCE. Connect identity first through the existing Connections UI, then select future draft creation to request gmail.compose, without gmail.send. Compose's Google scope also permits sends, so the application sending gate must stay false. No draft creation or sending operation was executed in this phase. Apollo/SignalHire caches/adapters are preserved; no enrichment called. No free entitlement or unlimited credit claim is made.

## Tests

See verification.md for executed results, genuine evidence types and exact commands. New CI runs offline contracts, a separate PostgreSQL 17 fresh-public bootstrap/role suite, the actual Python-host/API/database restart lifecycle, extension event tests and security checks. Existing CI continues full backend, frontend and browser regressions. No live provider generation, OAuth consent, remote migration or real Chrome/Telegram action runs in CI.


The first live launch correctly rejected the disposable suite's prior fake bot identity. `prepare_telegram_state.py` provides a narrow one-time recovery path only for the known local candidate_profile_test fixture with simulated_transport/bot 999999, completed replies, a verified different bot and an observed already-bound owner update with noncolliding IDs. It preserves completed outbox records and all application/policy data, writes a private recovery snapshot, and refuses remote databases, production, any live poll state, pending/sending replies, or owner mismatch. It never removes the ordinary worker bot-identity check. This recovery has been performed on the isolated development database; do not rerun it against live state.

## Conversational and platform boundaries

Deterministic parsing supports the requested job filters, company preparation, application counts, connection checks and preview handoffs without paid AI. Complex intent classification is a bounded optional interface; it is not activated while tool-free generation is unverified. Job lookup currently searches actual cached jobs only and says when no match exists. Selection expires after ten minutes and rechecks current preferences, eligibility, policy and submission evidence. Preparation can create/reuse a grounded packet when a verified profile exists; it never submits.

The Connect Platform flow opens official login pages for Naukri, Wellfound, Instahyre, YC and Internshala. Sign-in stays in the owner's browser. The extension's explicit **Check this portal session** gesture observes fixed visible sign-in/out indicators only, without cookies, credentials or account identity export. A browser observation is not an applicant API connection. Forget removes only local metadata. Submission remains unsupported/manual handoff pending owner acceptance. Naukri's automatic preference grants no execution capability.

The legacy encrypted resume was validated locally but remains unconfirmed. No canonical approved profile exists. Review actual facts and the resume in the dashboard; missing personal details must not be inferred. Drive configuration is retained with sync disabled pending review.

The separately reviewed compose constraint follow-up was explicitly approved and applied once through the guarded operator on 2026-10-25. Real secondary-account compose consent, exact scopes, encrypted persistence and actual Google refresh passed; see [the migration review and activation record](gmail-compose-migration-review.md). Never reapply it or fold it into the initial bundle. Sending remains disabled, and no real draft test is authorized.

## Current owner acceptance controls

Use the stable private runtime dashboard at http://127.0.0.1:3000. Profile now accepts explicitly verified years of experience (blank stays unknown; zero requires owner confirmation), phone and profile links. Download the preserved private PDF, choose it for the final fact review, and save the reviewed profile. Confirmation is stored against the exact profile ID/version in online Supabase; later edits invalidate it. Imported or extracted facts do not confirm themselves. Google Drive imports retain their separate review/approval workflow. No existing canonical profile or approved PDF is inferred.

Each platform card offers Connect, deliberate extension observation, and **Accept manual-only capability**. Acceptance stores the capability decision without authenticating an account or inventing browser evidence. A later browser observation keeps that decision; Forget clears both the observation and acceptance. Each portal still needs its own owner action.

AGY's unsupported tool-free session limitation was explicitly accepted by the owner for Phase 1. Generation and project MCP remain disabled. The metadata-only `agy_protocol_probe.py` verifies initialization without sending any user event, records only bounded safe diagnostics, and reaps its subprocess group. Current AGY 1.4.7 still advertises 60 tools. No claim that those tools executed is made; no proof of their inability to execute is available. Global permissions and MCPs are preserved.

A clean worker stop and a failure have different launchd semantics: `KeepAlive.SuccessfulExit=false` restarts a failure, while a graceful successful stop requires `launchctl kickstart gui/$(id -u)/com.automated-apply.telegram`. Check a fresh live poll and lease after every explicit restart; do not infer recovery from the plist. No global power settings are changed.

ChatGPT-side Supabase reconnection: open **Settings → Apps → Supabase → Disconnect**, then reconnect from **Apps** using the Supabase account that owns `luvdmwnlwaqgvfwlmlom`. Complete the official OAuth account/organization selector. Ask ChatGPT to list the visible projects and verify that exact reference before using the plugin. Do not log out of or overwrite local Codex, CLI or VS Code connections to repair this separate authorization. An actual plugin read in this session succeeded on the Supabase connection; Primary still denied access. No plugin account was disconnected or reauthorized automatically.

## Core readiness follow-up

Use [core-readiness.md](core-readiness.md) for the current milestone and exclusions.
The existing profile wizard stores candidate facts and canonical PDF selection.
Additional profile links use the existing candidate-resource store; project review
uses the integrated PR #19 service, not a second resume engine.

Authorize project sources explicitly in the private backend environment:

```dotenv
CANDIDATE_PROJECT_CHECKOUTS={}
CANDIDATE_PROJECT_REFRESH_SECONDS=300
```

Populate the JSON map only with exact GitHub repository URLs and absolute local
checkout directories you authorize. Restart the backend to load that map. Set
project names, priorities, technologies and context-template paths in Profile,
then recompute and review facts. The background task observes committed local
mirror changes and keeps new context pending until approved; it performs no Git
fetch/clone or repository code execution. An empty map grants no repository access.

For metadata-only AGY isolation diagnosis, without copying credentials or sending
model events:

```sh
python backend/scripts/phase1/agy_isolation_check.py
```

Google Drive OAuth and all live PDF downloads are deferred. Use manual PDF upload,
checksum-verified download, explicit canonical selection and final fact review.
Saved Drive history remains available. Existing manual-only portal acceptance does
not mean the accounts are authenticated. Never substitute deterministic summaries
or AGY authentication for the real isolated-generation acceptance criterion.
