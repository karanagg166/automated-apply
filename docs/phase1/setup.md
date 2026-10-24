# Phase 1 operations

Use this branch's worktree. Do not copy another project's .env, encryption keys, Supabase project links or CLI tokens. All setup commands below are explicit owner actions. Application submissions, Gmail sends and paid calls remain off. No runtime SQLite fallback exists; SQLite appears only in isolated tests.

## Environment and startup

Python 3.11+ and Node 22+; npm remains the frontend dependency manager.

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
npm ci --prefix frontend
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
npm run dev --prefix frontend -- --hostname 127.0.0.1
```

The existing frontend/run.mjs reads backend/.env unless FRONTEND_ISOLATED=1. Prefer an isolated private environment for this worktree; do not point it at another project's backend. Existing docs/phase7 dashboard procedures cover password hashing. No backend token goes into client bundles. Connections and preference updates use the existing owner session/BFF/CSRF boundary.

Shutdown order: stop Telegram first, then frontend, then API with Ctrl-C/SIGTERM. Only stop processes you started. Use the `status` local_service action for sanitized database readiness. The disposable test API used for native verification is separate from live Supabase and contains fictional records only.

## Supabase

Project: `luvdmwnlwaqgvfwlmlom`; URL `https://luvdmwnlwaqgvfwlmlom.supabase.co`; JWKS `https://luvdmwnlwaqgvfwlmlom.supabase.co/auth/v1/.well-known/jwks.json`.

Rotate exposed privileged credentials locally. Preserve the previous CLI account/session; use an isolated owner terminal/account profile for official `supabase login`, inspect `supabase projects list --output json`, and verify the exact project. MCP access alone is not a direct PostgreSQL connection. Before DDL, review migration-review.md, the exact SQL, hashes, fresh-project inventory, roles/grants/default privileges and Data API settings. No remote apply script runs automatically. Never db reset. Never reuse postgres, service_role, a Supabase secret key or an administrator DSN for runtime.

The public bundle is for an empty dedicated project only, in one transaction; it refuses existing user objects, job_agent schema or colliding app roles. It never touches Auth/Storage system schemas. Keep Data API disabled if unused, or explicitly confirm that no application tables are exposed to anon/authenticated. Use direct or session-pooler port 5432 with verified TLS and the dedicated role; transaction pooler 6543 is rejected. Pooler username must carry this project ref. If a root certificate is required, configure DB_SSL_ROOT_CERT from Supabase's official connection panel. Do not disable verification for a live database.

## MCP clients

Exact endpoint (preserved in .mcp.json):

`https://mcp.supabase.com/mcp?project_ref=luvdmwnlwaqgvfwlmlom&features=docs%2Caccount%2Cdatabase%2Cdebugging%2Cdevelopment%2Cfunctions%2Cbranching`

Inspect installed help before registration. Do not replace an existing `supabase` server. Registration already performed on this machine:

```sh
codex mcp add supabase-automated-apply --url '<exact endpoint above>'
claude mcp add --scope project --transport http supabase-automated-apply '<exact endpoint above>'
agy mcp add --type http supabase-automated-apply '<exact endpoint above>'
```

Codex is global because this installed add workflow has no scope flag; existing entries are preserved. Its enabled_tools restricts discovery to read tools; execute_sql/apply_migration are not enabled. Run `codex mcp login supabase-automated-apply` only when needed. The read-only verifier uses Codex app-server's installed protocol, starts no AI turn and reads no OAuth secrets:

```sh
.venv/bin/python backend/scripts/phase1/verify_mcp.py
```

Claude registration is project-scoped; project settings deny SQL/migration/function/branch writes. Owner authorizes OAuth through Claude's MCP UI; discovery remains pending until verified there. AGY's new server is registered but disabled, because this version's mcp add/list/enable commands provide no verified per-tool allowlist. The existing enabled `supabase` entry is preserved. Do not enable unrestricted writes just to show a connected badge. OAuth tokens remain client-owned and uncommitted. The application's FastMCP authentication, draft-creation permission and spending gates are unchanged.

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

Reload after updates. Test example.org and an owner-controlled non-sensitive Google Form. Confirm popup result and matching URL in local history. Backend offline produces a retryable error; retry is a new deliberate user gesture. The scripted bridge test simulates Chrome events and cannot establish real Chrome installation evidence.

```sh
.venv/bin/python backend/scripts/phase1/install_local.py native-uninstall
```

## Telegram and locked Mac

Create a private bot with official @BotFather. The following owner-run interactive setup hides the token, calls getMe/getWebhookInfo, requires a private /start and explicit numeric identity selection. It refuses webhook conflicts; no deleteWebhook operation exists.

```sh
.venv/bin/python backend/scripts/phase1/configure_telegram.py --env-file /absolute/path/phase1.private.env
.venv/bin/python backend/scripts/phase1/local_service.py telegram --env-file /absolute/path/phase1.private.env
```

/start /help /ping /status /connections /jobs /apply <https-url>. Only the bound numeric owner and private chat are accepted. No group/forwarded commands or shell execution. Offset and bounded acknowledgment outbox persist in PostgreSQL. An ambiguous interrupted send stays `sending` and is never automatically replayed; the owner can inspect delivery history and issue a new /ping. HTTP 429 retries respect retry_after; network errors back off. A database advisory lock prevents duplicate workers. No personal resume, salary, email body or URL query appears in Telegram replies/logs. Simulated transports persist their evidence type and cannot create a live connection badge.

launchd is opt-in and not installed automatically:

```sh
.venv/bin/python backend/scripts/phase1/install_local.py launchd-plan --env-file /absolute/path/phase1.private.env
.venv/bin/python backend/scripts/phase1/install_local.py launchd-install --env-file /absolute/path/phase1.private.env
launchctl print gui/$(id -u)/com.automated-apply.telegram
.venv/bin/python backend/scripts/phase1/install_local.py launchd-uninstall
```

Private user plist, explicit interpreter/worktree/env path, restart on failure, 30-second throttle, private sanitized logs in ~/Library/Logs/Automated Apply. Clean SIGTERM/SIGINT handling allows a bounded outstanding poll to finish. No global power settings are changed. Screen lock is compatible with an awake, powered, networked Mac; sleep, shutdown and network loss interrupt execution. Actual lock+phone /ping is a pending owner-assisted test until performed. Logs/config are preserved on uninstall; rotate/remove them deliberately when no longer needed.

## AI and Gmail

`agy --version`, `agy --help`, `agy models` are availability/model checks, not answer generation or quota verification. The adapter strips backend credentials from its subprocess environment, creates a temporary workspace with a primary `tools: []` agent, uses sandbox/plan mode, structured schemas, bounded stdin/output, process-group cleanup and no retry/fallback. It now requires positive local agent discovery before any AI request. The installed CLI did not discover workspace agents. A uniquely named global profile was then installed with mode 0600 and successfully discovered by `agy agents`; existing global agents/MCPs were preserved. The adapter verifies that profile exactly before generation. Global owner hooks were detected and left untouched. No resume-based AGY generation is activated. One authorized fictional invocation was interrupted; no successful response or quota usage was observed. Its exclusive marker prevents a second smoke attempt; further live generation needs a separate owner decision after adapter tests and explicit owner authorization.

```sh
.venv/bin/python backend/scripts/phase1/install_local.py agy-profile-plan
.venv/bin/python backend/scripts/phase1/install_local.py agy-profile-install
agy agents
.venv/bin/python backend/scripts/phase1/install_local.py agy-profile-uninstall
```

Gmail retains encrypted tokens/disconnect/state/PKCE. Connect identity first through the existing Connections UI, then select future draft creation to request gmail.compose, without gmail.send. Compose's Google scope also permits sends, so the application sending gate must stay false. No draft creation or sending operation was executed in this phase. Apollo/SignalHire caches/adapters are preserved; no enrichment called. No free entitlement or unlimited credit claim is made.

## Tests

See verification.md for executed results, genuine evidence types and exact commands. New CI runs offline contracts, a separate PostgreSQL 17 fresh-public bootstrap/role suite, the actual Python-host/API/database restart lifecycle, extension event tests and security checks. Existing CI continues full backend, frontend and browser regressions. No live provider generation, OAuth consent, remote migration or real Chrome/Telegram action runs in CI.
