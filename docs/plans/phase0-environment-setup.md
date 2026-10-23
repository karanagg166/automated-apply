# Phase 0: no-cost environment setup

Observed **2026-10-21**, repository `/Users/karanagg/Desktop/Projects/automated-apply`.
**Development checks work; the real application environment is NOT ready.** No tools were
reinstalled, existing configuration replaced, database changed or account connected here.

## Installed and missing

| Component | Actual check/result | Action / acceptance |
| --- | --- | --- |
| Hardware | Apple M1, arm64, 8 CPUs, **8 GiB unified RAM**, macOS 27.0 | Run bounded services; avoid simultaneous model/build/restore load |
| Disk | About **14 GiB available**, 93% filesystem used | Recheck `df -h .` before images/models/backups; no broad cleanup of other projects |
| Python | Default `/opt/homebrew/bin/python3` is **3.15.0**; existing `backend/venv/bin/python` is **3.11.17** | Use existing venv, matching CI's 3.11; `backend/venv/bin/python -m pip check` passes |
| Node/tooling | Default Node **26.12.0**, legacy package-manager **11.20.0**; working `/opt/homebrew/opt/node@24/bin/node` **24.22.0** | Prefer process-local Node24 PATH matching CI; do not relink Homebrew globally |
| Package managers | pnpm **12.14.0** available | Use pnpm and `frontend/pnpm-lock.yaml`; pnpm is the owner-required package manager |
| PostgreSQL clients | Default `psql`/`pg_dump` **14.24**; `/opt/homebrew/opt/libpq@17/bin/*` **17.11** | Always use absolute PG17 clients for recovery; never PG14 dump against PG17 |
| PostgreSQL server | Homebrew **postgresql@14 started** | Preserve unrelated service; it is not the PG17 test/development target |
| Docker | CLI **29.9.1**, reachable server **29.8.2** | Existing `postgres:17-alpine` and `supabase/postgres:17.6.1.166` images present; do not replace them |
| Supabase CLI | `/opt/homebrew/bin/supabase` **2.121.0** | Existing linked metadata under untracked `supabase/.temp/`; no relink/push/reset/start required |
| Git/GitHub | Git **2.56.0**, gh **2.102.0**; origin fetch and connected GitHub reads work | New planning branch created; auth-read success is not account/product runtime connection |
| Browser checks | `frontend/node_modules` installed; Playwright Chromium caches 1223/1234/1248 | Existing frontend tests/typecheck pass; use version-matched browser, install only if absent |
| Encryption | `/opt/homebrew/bin/age` **1.3.2**; existing identity preserved | Working local challenge historically passes; independent retrieval still unverified |
| Ollama | Not on PATH / not installed by this task | Install native Mac package later; no model downloaded here |
| Secure utilities | Ruff/Bandit/detect-secrets workflow exists; `sops`, `gitleaks`, `uv` not found | Optional tools are not blockers; reuse existing scanners/venv and age |
| Other processes | Existing Redis service and unrelated RabbitMQ container | Not application dependencies; leave untouched |

No `AGENTS.md` was found in the repository or applicable ancestor paths. Existing skill or
setup templates do not override the owner's current authorization boundaries.

## Three database environments

| Environment | Purpose / proposed identity | Readiness and isolation |
| --- | --- | --- |
| A: disposable local PG17 | Automated fictional tests; `candidate_profile_test`, loopback **55417** proposed | Image installed; no PG test server provisioned/left running in this planning task. Verifiers create/drop random child DBs and may fixed-name roles: use a dedicated cluster, serial PG tests |
| B: persistent local PG17 | Synthetic development only; dedicated named volume, separate loopback **55418**, proposed DB `automated_apply_dev` | Not provisioned. Never reuse A, host PG14 or recovery scratch. No real-owner local persistence under the current product policy |
| C: selected shared Supabase | **jyzjgoniuwexvipbbpwa**, real persistence in **job_agent** | Historical catalog says schema absent; no fresh remote query here; R1 prerequisites missing and R2 unauthorized |

The current README requires online PostgreSQL for genuine data. Local Mac operation means local
API/UI/AI with the approved online DB. A fully local genuine-data mode would need a deliberate
policy/security review later; do not flip `DB_REMOTE_ONLY` to bypass the present policy.
`ENVIRONMENT=testing`, `DB_REMOTE_ONLY=false` and local TLS exemptions are fixture settings,
not operational credentials. Persistent B needs its own reviewed bootstrap and restricted
synthetic runtime; existing verifiers are not a general-purpose bootstrap for it.

Example A setup, **future local fictional testing only**, after checking port/name conflicts:

```sh
docker run --detach --name automated-apply-plan-test-pg17 \
  --publish 127.0.0.1:55417:5432 --memory 768m --cpus 1 \
  --tmpfs /var/lib/postgresql/data:rw,noexec,nosuid,size=512m \
  --env POSTGRES_HOST_AUTH_METHOD=trust --env POSTGRES_DB=candidate_profile_test \
  postgres:17-alpine
docker exec automated-apply-plan-test-pg17 pg_isready -U postgres -d candidate_profile_test
PROFILE_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55417/candidate_profile_test \
  backend/venv/bin/python -m pytest backend/tests -q
docker stop automated-apply-plan-test-pg17
docker rm automated-apply-plan-test-pg17
```

Trust is acceptable only for this disposable, credential-free, synthetic loopback test cluster;
other local users may connect while it runs. Never mount personal configuration/data into it.
These commands were not executed in this task. PG verifiers include privileged fixture setup;
never aim `PROFILE_TEST_DATABASE_URL` at B or C. Use the pinned Supabase image/network-none/tmpfs
procedure in the private R1 runbook for real-source recovery; A is **not** that recovery container.
For B, prepare an ignored Compose specification in a later scoped task with SCRAM, private
file-based credential input, dedicated volume, restricted app role and no shared schema grants.
Do not use `supabase db reset`, `supabase db push` or linked migration commands for any of these.

## Safe checks and existing commands

From the repository root:

```sh
backend/venv/bin/python --version
backend/venv/bin/python -m pip check
/opt/homebrew/opt/node@24/bin/node --version
/opt/homebrew/opt/libpq@17/bin/pg_dump --version
age --version
docker info --format '{{.ServerVersion}}'
backend/venv/bin/python backend/scripts/check_environment.py --env-file backend/.env
backend/venv/bin/python backend/scripts/check_workspace.py --env-file backend/.env
backend/venv/bin/python backend/scripts/migration_preflight.py
backend/venv/bin/python secrets/phase9/set_admin_password.py --check
```

Environment/workspace checks are offline, sanitized and may exit 2 for missing setup.
`check_workspace.py` is HTTPS/staging-oriented: loopback development legitimately fails its
HTTPS readiness fields. Do not label local HTTP checks a production pass. Migration preflight
without apply flags is a plan, not DDL. `check_database.py` makes a real connection; reserve it
for the explicitly selected and authorized target in the later activation task.

This audit ran the environment check and private helper: **needs_configuration / blocked before
connection**. Both existing env files choose SQLite; that cannot start the genuine runtime.
Backend `.env` has an existing valid resume key, but lacks API token, owner login/session,
Gmail OAuth/keyring and Greenhouse boards. Configuration contents/values were not printed.
All observed sending, enrichment and resume-worker gates are off. An inert template is not a
credential or connectivity test. No Telegram/Ollama settings are supported by main yet.

Development validation executed here: **134 backend tests passed, one skipped** across
readiness/database safety/source capability/LLM interface tests; the skipped `test_phase9_database_readiness.py` integration needs disposable PG.
Frontend **33 tests passed** and TypeScript passed with installed Node24; pip consistency passes.
These are fresh targeted checks on the main-based planning tree, not a full suite or live pilot.

For a fresh checkout only, if dependencies are missing, recreate Python using `python3.11`
and install `backend/requirements.txt` in a new venv, or `pnpm --dir frontend install --frozen-lockfile` with Node24.
Do not run those reinstall commands over today's working environments merely for planning.
Use `backend/venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000`
and `pnpm --dir frontend run dev --hostname localhost` **only after** intended private
configuration/DB readiness. `frontend/run.mjs` reads `backend/.env`; API Settings also read root
`.env` then `backend/.env`. Use explicit isolated fixtures for UI tests (`FRONTEND_ISOLATED=1`
is set by the existing Playwright config). Never run a genuine service with fixture bypasses.

## Private owner setup, in order

1. Read existing ignored `secrets/phase9/OWNER-SETUP.md` and
   `reports/phase9-shared-supabase/readiness-20261021/R1-EXECUTION-SCOPE.md` locally.
   The current request confirms existing R1 authorization; older “ask again” passages are
   superseded. Their technical prerequisites and database-only recovery limits remain binding.
2. In the selected project's official Connect/TLS panels, copy exact direct/session host,
   port and administrator username into `secrets/phase9/admin.pg_service.conf`; preserve
   `sslmode=verify-full`. Fetch the actual selected-project CA into
   `secrets/phase9/supabase-ca.crt`. Complete provenance in
   `secrets/phase9/connection-source.private.json`. Do not use guessed endpoints or 6543 pooling.
3. Run `backend/venv/bin/python secrets/phase9/set_admin_password.py` in an interactive terminal
   to enter the **existing** administrative password. The helper refuses populated overwrite;
   do not reset the shared password. No secret in command arguments, chat or shell history.
4. Independently back up/retrieve the existing identity at
   `/Users/karanagg/.config/automated-apply/phase9-recovery/age-identity.txt` through an existing
   password manager or owner-controlled encrypted external medium. Update only the appropriate
   path in `secrets/phase9/recovery.private.env`; harmless decryption/tamper verification must
   pass from the independently retrieved copy. Do not regenerate identity/recipients.
5. Confirm **actual project plan, no billing activation, backup entitlement and shared-app
   resource headroom** in the dashboard; record non-secret evidence privately. Export does not
   recover external Storage bytes, Vault root keys or managed services. R1 must follow the
   exact existing stream-encryption/isolated-restore runbook after gates pass.
6. After R1, obtain separate R2 approval for exact pinned Phase 9 SQL and runtime credentials.
   Configure restricted `DATABASE_URL`, `DATABASE_SCHEMA=job_agent`, `DB_SSL_ROOT_CERT`,
   `DB_REMOTE_ONLY=true`, `DB_REQUIRE_TLS=true`, `DB_ECHO=false`, small connection pools and
   strong `JOB_AGENT_API_TOKEN`/`SECRET_KEY` privately. No admin DSN in runtime/frontend.
7. Preserve `RESUME_ENCRYPTION_KEY` and any existing OAuth keyring independently. Configure
   `FRONTEND_PASSWORD_HASH`/`FRONTEND_SESSION_SECRET`, `FRONTEND_ORIGIN`, `BACKEND_ORIGIN`,
   exact backend host/origin trust and local-only `FRONTEND_LOCAL_HTTP` as applicable.
   **Do not blindly run `configure_frontend_owner.py`: it generates a new resume key alongside
   login material.** It writes `backend/frontend.private.env` exclusively; if used later,
   review only login values privately and retain the established resume key. Do not source
   generated output wholesale over an existing environment.
8. For Phase 11, authorize exactly one actual resume import and approve extracted career facts
   separately. Prefer authenticated private upload, retaining the real Drive file privately.
   Existing public-link sync is optional and requires a conscious sharing decision, not a
   reason to make a private resume public. Review projects/GitHub and preferences manually.
9. Gmail, Telegram and any later GitHub/Drive OAuth require the separate owner steps in
   [account plan](real-account-connection-plan.md). Optional providers need no keys for the
   default path. Keep all paid provider and Gmail sending gates disabled.

Keep `secrets/` at 0700, populated credential/key/env files at 0600 and ignored. The existing
`.gitignore` protects reports, secrets, env, databases and PDFs; it does **not** protect
`supabase/.temp/`, so always stage exact planning paths, never `git add .`.

## Local AI choice and reproducible evaluation

Native Ollama preserves Apple Metal acceleration; do not run Mac inference inside Docker.
Install the official [Mac build](https://docs.ollama.com/macos) only when Phase 13 is selected.
Check disk/memory first. Model comparisons below are hypotheses to benchmark, not measured
quality/latency on this machine. Published sizes are download sizes, not total RAM requirements.

| Candidate | Published size / license | Intended comparison |
| --- | --- | --- |
| [Qwen3 1.7B Q4_K_M](https://ollama.com/library/qwen3:1.7b-q4_K_M) | ~1.4 GB, Apache 2.0 | **First baseline**, bounded extraction/JSON and short grounded drafts; strongest memory margin |
| [Qwen3 4B Instruct 2507 Q4_K_M](https://ollama.com/library/qwen3:4b-instruct-2507-q4_K_M) | ~2.5 GB, Apache 2.0 | Optional later challenger for project/company prose after memory/accuracy evidence |
| [Qwen2.5 3B](https://ollama.com/library/qwen2.5:3b) | ~1.9 GB, Qwen research license (not Apache for 3B) | Comparison only if license/use review passes; not the default |

Use one loaded model, one inference at a time, initial 2,048 context tokens and bounded output;
retrieve only short approved evidence excerpts. Deterministic facts never need inference.
Do not assume advertised large model context fits 8 GiB. Phase 13 should measure RSS, swap,
time to first token, total latency, schema validity, claim grounding and unknown-fact abstention
while API/UI are running. No embeddings/vector service initially; existing deterministic
retrieval suffices. If the small model fails, use owner-authored answers; no cloud fallback.

Future Ollama launch configuration (Ollama's own variables, **not existing app variables**):

```sh
OLLAMA_NO_CLOUD=1 OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NUM_PARALLEL=1 \
  OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_CONTEXT_LENGTH=2048 ollama serve
# Purposeful later download, one model only:
ollama pull qwen3:1.7b-q4_K_M
ollama list
ollama ps
```

Official [FAQ](https://docs.ollama.com/faq) and
[structured output documentation](https://docs.ollama.com/capabilities/structured-outputs),
verified 2026-10-21. JSON schema improves format, not truth. The main app currently only accepts
`LLM_PROVIDER=gemini` and Gemini model identifiers; do not invent `OLLAMA_*` app settings or
set `LLM_PROVIDER=ollama` until provider/settings validation is implemented in Phase 13.
A 40-case benchmark should include at least ten unknown/sensitive fact cases, ten project
claims, ten extraction cases and ten adversarial/stale-context cases. Require zero unsupported
accepted factual claims, 100% unknown-sensitive abstention and all accepted responses schema
valid; rejected drafts remain reviewable failures. Record quality and resource evidence privately.

## Telegram preparation

Owner creates a bot with official [BotFather](https://core.telegram.org/bots/tutorial), starts
a private conversation and stores token privately. Phase 14 must implement a local secret reader,
`getMe` and owner challenge verification from `getUpdates` before saving the authorized numeric
chat ID. Never paste a token-bearing API URL into browser history or logs. Do not invent current
app env names: none exist. No notifications or bot probes were sent in this task. Quiet hours,
redacted content, per-event delivery dedup and 429 retry handling belong to the existing outbox
extension specified in Phase 14.

## Readiness gates

**Proceed now without credentials:** documentation/review, synthetic unit/frontend tests,
disposable PG17 fixtures, reconciliation review, ATS/Ollama/Telegram offline implementation
in later scoped tasks. **Blocked:** real DB/application start, actual owner import, genuine
persisted jobs/matches, Gmail OAuth and external notification verification. Ollama is optional
for the first manual packet; Telegram is required only for the requested notification milestone.
Phase 0 closes only when reproducible synthetic API/UI/PG checks pass, owner secrets/key recovery
are prepared and each unconfigured optional capability is visibly disabled. This planning pass
completes the inventory/runbook; it does not claim those remaining setup gates passed.
