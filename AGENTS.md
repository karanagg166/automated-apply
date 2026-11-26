# AGENTS.md — Repository Governance & Engineering Contract (`automated-apply`)

This file is the authoritative instruction set for every AI coding agent and developer working in `automated-apply`. Read this entire document before inspecting, modifying, or creating any file. If any existing code in the repository conflicts with this file, **this file wins**—propose a refactor to align the code with these rules.

---

## 1. System Mission & Non-Negotiable Constraints

`automated-apply` is a **100% free (₹0), 24/7 autonomous agentic job-application system** running continuously on a **MacBook Air M1** (plugged in, lid open, screen locked).

1. **Zero Paid Dependencies:** Never introduce paid APIs, paid proxies, paid cloud hosting, paid tunnels (e.g., paid ngrok), or paid vector databases. Every component must operate strictly within free tiers or local open-source tooling.
2. **No Local Generative LLMs:** Never configure Ollama, llama.cpp, or local generative models. All reasoning/generation must go through the **Free External LLM Fallback Router**. *(Exception: lightweight local CPU ONNX/FastEmbed embedding models ~80 MB RAM for semantic caching are required.)*
3. **Single Primary Orchestrator (Python v2):** Do NOT duplicate orchestration, scheduling, auth, or business logic across multiple runtimes (Python + Rust + Extension). **Python (`uv` + `asyncio` + `FastAPI` + `Playwright` + `FastMCP`)** is the only primary orchestrator (`backend/app/browser_v2/` for in-process browser automation and `backend/app/browser_v2/browser_mcp.py` for FastMCP exposure). The v1 runtimes are gone: `rust/`, `extension/` and the native messaging host were removed on 2026-11-26, and Phase 9E removed the v1 Python agent/browser-assistant/execution/FastMCP packages (`backend/app/{agent,browser,execution,mcp}`), the v1 Telegram bot and their scripts. Do not reintroduce them; `backend/tests/test_v2_isolation.py` keeps them deleted and unimported.
4. **Deterministic First, LLM Second:** Never spend LLM tokens on tasks that deterministic code can handle (navigation, pagination, login detection, filtering, standard profile fields, resume uploads). Call an LLM only for JD-to-preference scoring, dynamic/unseen screening questions, and personalized email draft copy.
5. **M1 Fanless Resource Budget:** Keep total steady-state browser + worker footprint lean. Max **1 active browser worker tab** at any time (`tidy_tabs()` closes stray popups/tabs). No parallel multi-tab scraping storms. Keep SQLAlchemy pools clamped to `pool_size=2, max_overflow=1` (`backend/app/db/session.py`) and use one `asyncpg` connection per v2 worker process to respect Supabase's 5-connection runtime role ceiling.

---

## 2. Hard Safety, Privacy & Git Guardrails (NEVER VIOLATE)

### A. Gmail Permission Lock (STRICTLY READ + DRAFT ONLY)
- The system MUST NEVER send an email autonomously under any code path, flag, or prompt.
- **Hard code-level enforcement:** Do NOT implement, register, or expose any `send_email`, `mail.send`, `gmail.send` OAuth scope, or SMTP-send route/tool inside the Mail MCP server, REST API, or anywhere in the agent runtime.
- Allowed Gmail operations only: **read/search** (for status/lead tracking) and **create/save draft** (`[Gmail]/Drafts`).
- `backend/tests/test_gmail_no_send_guardrail.py` enforces this invariant; every relevant test suite must verify that no send tool is registered in MCP tool manifests. Frozen legacy send modules (`backend/app/services/gmail_sending.py`, `backend/app/integrations/gmail/send_client.py`) must remain unimported until owner-approved deletion.

### B. PII, Free-Tier LLM Scrubbing & Profile Truthfulness
- Free external LLM providers may log prompts.
- Fill sensitive personal fields (full phone number, street address, government IDs, exact current/expected CTC if not needed for reasoning) **deterministically from the local/Supabase DB**.
- Pass only a PII-scrubbed candidate profile summary (skills, projects, experience years, tech stack, role preferences) to external LLMs—never raw credentials, cookies, tokens, or sensitive personal identifiers.
- Never fabricate personal facts, dates, compensation, work authorization, or certifications. Distinguish original portfolio/GitHub implementations from forks, dependency declarations, and generated/vendor code (`2026-11-01` owner rule).

### C. Secrets & Repository Hygiene
- This is a **private GitHub repository**, but **zero real secrets** (API keys, Gmail App Passwords, Telegram bot tokens, Supabase service keys, session cookies, Brave profile data) may ever appear in source files, docs, or test fixtures.
- All test fixtures must use clearly synthetic placeholders (e.g., `TEST_FAKE_TOKEN_ONLY`, `example.com`) that pass `secretlint` (`.secretlintrc.json` + `.secretlintignore`) cleanly.
- Keep test fixtures compact—never commit multi-megabyte JSON corpora into git. Private env files (`~/Library/Application Support/Automated Apply/phase1.private.env`, `backend/.env`), `.local/`, `reports/`, and screenshots remain untracked/gitignored.

### D. Git Operations & Local Completion Only (STRICTLY PROHIBITED WITHOUT EXPLICIT USER COMMAND)
- **NEVER** run `git commit`, `git push`, `git reset --hard`, or `git push --force` on your own initiative.
- Leave all changes cleanly in the working tree so the user can review diffs and commit manually.
- **Local completion only (`2026-11-17` owner direction):** Do not push to GitHub, create/update PRs, publish remote reports, dispatch/rerun hosted GitHub Actions, or merge until explicitly reauthorized by the owner.

---

## 3. Runtime Topology: Docker vs. macOS Host Split

Because this system runs on macOS (Apple Silicon M1) and interacts with native desktop apps, maintain a strict boundary between containerized workloads and host-native bridges:

| Layer | Runs Where | Rationale |
| :--- | :--- | :--- |
| **Core Orchestrator API, Scheduler, Frontend, DB/Migrations, Linting, Type-Checking, Full Test Suite** | **Docker / Docker Compose** | Reproducible environment, isolated dependencies, clean CI parity. |
| **Browser MCP (Playwright + Dedicated Brave Profile)** | **macOS Host** | Requires native ARM64 headful Brave binary, persistent local profile directory, and low M1 memory overhead. |
| **Local Mail.app MCP (AppleScript / `imaplib`)** | **macOS Host** | Requires macOS `osascript` Automation bridge to `Mail.app`. |
| **24/7 Keep-Awake Daemon (`launchd` + `caffeinate -i`)** | **macOS Host** | Prevents idle system sleep while the MacBook screen is locked (`Ctrl + Cmd + Q`, lid open, plugged in). |

- **Target Containerization:** Package installations, DB migrations, linting, type-checking, and test suites for core services should run inside Docker containers once the Compose stack is wired; during active host transition on macOS, use `backend/venv` via `uv` strictly (never bare `pip`, `pip3`, or `python -m pip`).
- **Frontend/JS Package Manager:** Use **`pnpm` strictly**. Never run `npm`, `npx`, `yarn`, or `bun`, and never commit `package-lock.json` or `yarn.lock`.
- **Database & Migrations:** Authoritative live state resides in **online Supabase PostgreSQL** (`public` schema + `pgvector` in schema `extensions`). v2 core tables (`portal_rules`, `applications`, `application_state_events`, `hitl_requests`, `semantic_cache`, `llm_provider_usage`, `enrichment_cache`, `enrichment_credits`, `email_drafts`) come from `supabase/fresh_public/followups/004_python_v2_core_tables.sql`; Phase 9 followup `005_python_v2_phase9.sql` adds `watcher_state`, `agent_audit_log` (append-only), `agent_conversation_turns`, `profile_sync_runs` plus priority/circuit-breaker columns on `applications`/`portal_rules`. Both are applied ONLY through `backend/scripts/migrate_v2_core.py` (`apply`, then `apply-phase9`; always run read-only `check` first). SQLite (including `sqlite-vec` when used locally) is restricted to tests, offline fixtures, and local cache benchmarks—never production job/application state.

---

## 4. Architecture & MCP Component Contracts

### 4.1 Browser MCP (`Playwright` + Persistent `Brave`)
- **Retired Path:** The Chrome Extension, Rust workspace and Native Messaging Host were removed (Manifest V3 suspends idle service workers and breaks on cross-origin ATS redirects). Do not rebuild them for the 24/7 application loop.
- **Dedicated Brave Profile & Login Flow:**
  - Use Playwright `launch_persistent_context` pointed at macOS Brave (`/Applications/Brave Browser.app/Contents/MacOS/Brave Browser`) with the single dedicated user-data directory `~/Library/Application Support/automated-apply/brave` (override via `AUTOMATED_APPLY_BRAVE_PROFILE_DIR`; never under `~/Desktop`, `~/Documents`, or `~/Downloads`), isolated from the user's personal Brave profiles.
  - One-time manual login uses `backend/venv/bin/python -m backend.app.browser_v2.cli login-setup`, which launches plain Brave with zero Playwright/CDP/`--enable-automation` flags. Automation launches headful with `--enable-automation` removed and refuses concurrent runs against the same profile lock.
  - Never wipe or launch ephemeral browser contexts during scheduled runs.
  - **Tab Control (`2026-11-23` owner direction + M1 budget):** Direct tab/window control within the dedicated project Brave profile is authorized; inventory/reuse the active worker tab and close popups/stray tabs (`tidy_tabs()`) so at most **1 active browser worker tab** runs at any time.
- **Anti-Bot & Stability Rules:**
  - Run **headful** (minimized or isolated macOS Space; never raw headless on Indian job portals).
  - Abort heavy non-essential resources (media, fonts, ad/tracker beacons) via `page.route()` without blocking portal auth, CAPTCHA, or form scripts.
  - Extract compact **accessibility trees / interactive form element JSON** (`backend/app/browser_v2/forms.py`)—never dump raw full-page HTML to an LLM.
  - **Session Health Check:** Before every portal cycle, verify authenticated state (allowing one clean refresh/reload for cookie renewal). If redirected to login, OTP, or session expired:
    1. Immediately mark portal `auth_status` as `AUTH_REQUIRED` in `portal_rules`.
    2. Send a Telegram HITL alert (`[Portal] Session expired — run login-setup & reply /resume <portal>`).
    3. Pause **only that portal**; continue running all other enabled portals.
  - **Memory Hygiene:** Gracefully restart/recycle the Brave process every **3 hours** (`RECYCLE_AFTER_SEC = 10800`, only between jobs, never mid-submission) to clear Chromium memory leaks.
- **Submission Verification & Dry-Run:** Every live submission must verify a concrete confirmation signal (confirmation DOM text, history verification, API 2xx response, or applied badge) and log a timestamped receipt/screenshot path (under `~/Library/Application Support/automated-apply/receipts/`) before transitioning state to `APPLIED`. Support `dry_run=True` (`--dry-run` / `DRY_RUN=true`) stopping cleanly before the final Submit/Apply action.

### 4.2 Portal Adapters (Deterministic-First, Expanded Coverage)
Supported portals and job sources are organized into four explicit tiers:

- **Tier 1 — Primary Interactive Job Portals (8 Portals: Playwright Brave Persistent Profile / Hybrid MCP + `portal_rules`):**
  1. `naukri` (Naukri.com — live Phase 1 adapter implemented in `backend/app/browser_v2/adapters/naukri.py`)
  2. `instahyre` (Instahyre)
  3. `wellfound` (Wellfound / AngelList Talent)
  4. `work_at_a_startup` (YC Work at a Startup)
  5. `internshala` (Internshala)
  6. `hiringcafe` (HiringCafe — official conversational MCP `https://hiringcafe.com/api/mcp`, posting-ID deduplication, external employer ATS handoff / Brave)
  7. `himalayas` (Himalayas — official public API `https://himalayas.app/jobs/api` / hosted MCP + persistent Brave login-setup where direct portal action is needed)
  8. `we_work_remotely` (We Work Remotely — official public RSS `https://weworkremotely.com/remote-jobs.rss` with required attribution + external employer ATS handoff)
- **Tier 2 — Direct ATS Public Job Boards (4 ATS Boards: Zero-Cost Public Read APIs + Hosted Form Filling / Manual Handoff):**
  9. `greenhouse` (`boards-api.greenhouse.io`)
  10. `lever` (`api.lever.co` / `api.eu.lever.co`)
  11. `ashby` (`api.ashbyhq.com`)
  12. `smartrecruiters` (`api.smartrecruiters.com`)
- **Tier 3 — Free Public Job Feeds (3 Feeds: Zero-Cost Discovery + External Employer Application Handoff):**
  13. `remotive` (`remotive.com/api/remote-jobs`; respect rate limits and ≤4 fetches/day cap)
  14. `arbeitnow` (`arbeitnow.com/api/job-board-api`)
  15. `hacker_news` (`hn.algolia.com` Who is Hiring threads)
- **Tier 4 — Restricted / Assisted Targets:**
  - `linkedin`: Strictly manual-import / permitted public search links only—**never** automate login, scraping, connection requests, messaging, or applications.
  - `company_careers`, `workday`, `google_forms`, `employer_forms`: Assisted inspection and manual handoff unless a verified adapter is implemented.

Every portal adapter (`backend/app/browser_v2/adapters/base.py`) MUST implement the same typed contract:
1. `check_session(page) -> SessionCheck` (`AuthStatus`)
2. `discover_jobs(page, ...) -> list[JobListing]`
3. `inspect_job(page, listing) -> JobDetail` & `extract_form(page) -> dict` (`extract_application_form`)
4. `detect_portal_limit(page) -> str | None` (`bool` / limit signal)
5. `apply_job(page, detail, profile, dry_run) -> ApplyResult` (`submit_application`)

### 4.3 Semantic Cache + Free External LLM Fallback Router
- **Semantic Cache:**
  - Local lightweight CPU embeddings (`all-MiniLM-L6-v2` or `bge-small-en-v1.5` via FastEmbed/ONNX) stored in Supabase `pgvector` (`public.semantic_cache` with `extensions.vector(384)` + HNSW cosine index) or `sqlite-vec` for offline tests.
  - Lookup threshold: **cosine similarity >= 0.88** (configurable).
  - Cache hit returns answer immediately (**0 LLM tokens**, ~5 ms).
  - Every verified answer provided by the user via Telegram HITL MUST be automatically normalized and upserted into `semantic_cache`.
- **Pluggable Free LLM Fallback Router:**
  - Single OpenAI-compatible router interface with local RPM/RPD/TPD rate tracking in `public.llm_provider_usage`, exponential backoff, and per-provider circuit breakers.
  - Automatic failover on `HTTP 429`, `5xx`, quota exhaustion, or timeout in priority order:
    1. **Groq Free Tier** (fast JSON / form-field mapping)
    2. **Google AI Studio Free Tier** (Gemini Flash / Flash-Lite for long JDs & email drafts)
    3. **Mistral Experiment Tier / OpenRouter `:free` models**
    4. **Cloudflare Workers AI / GitHub Models**
  - Adding a new free LLM fallback provider in the future must require only a config entry + env var, zero orchestrator rewrites. Never route to Ollama or paid LLM tiers.

### 4.4 Enrichment MCP (Free-Tier Email Discovery)
Triggered **only** when a platform reaches a daily limit (dashboard cap or portal cap) and a Gmail draft is needed:
1. **Tier 1 (Zero Cost):** Regex/DOM extraction of recruiter/HR email from the JD text and company careers/about page.
2. **Tier 2 (Free Credits):** Apollo MCP / Apify MCP contact lookup (strictly within free credits; never buy subscriptions).
3. **Strict Credit Protection:** Cache enrichment lookups by `company_domain` + `role_family` in `public.enrichment_cache` (TTL 30 days) so the same company is never queried twice, and enforce daily free-tier credit caps in `public.enrichment_credits` before calling external enrichment tools.

### 4.5 Local Mail.app MCP (macOS Gmail Draft Bridge)
- **Primary:** Python `imaplib` (`APPEND` directly to `[Gmail]/Drafts` using Gmail App Password from private env) or silent AppleScript via `osascript` targeting `Mail.app` synced with Gmail (`make new outgoing message with properties {visible:false, ...}` -> `save`)—ordered so locked-screen runs remain 100% reliable without GUI stalls.
  - **CRITICAL:** Never call `activate` on `Mail.app` (causes stalls/failures behind a locked screen).
- **Idempotency:** Record `created_at` (`draft_created_at`) and `external_draft_id` (`draft_message_id`) in `public.email_drafts` and `public.applications` keyed by `(platform, external_job_id)` so a job never generates duplicate Gmail drafts.

### 4.6 Telegram HITL MCP (Free Long Polling)
- Use Telegram Bot API **long polling** (never require a public webhook server or paid tunnel).
- **LLM-first agent:** free-text messages go to the v2 agent (`backend/app/agent_v2`), which may only call allow-listed, audited tools; every tool call is recorded in `public.agent_audit_log` and conversation memory in `public.agent_conversation_turns`. Slash commands remain deterministic.
- Triggers: CAPTCHA, OTP, `AUTH_REQUIRED` login expiry, ambiguous/unseen screening question (below confidence threshold / not in stored facts or semantic cache), or repeated submission failure.
- **Non-Blocking Rule:** When a job needs human input:
  1. Transition **only that job** to `WAITING_FOR_USER` and persist a `public.hitl_requests` row + form context.
  2. Send a concise Telegram prompt containing job title, company, portal, exact question/blocker, and expected reply format.
  3. Immediately continue processing other jobs and portals in the queue.
  4. On receiving the user's Telegram reply, save Q&A to `public.semantic_cache` and re-enqueue the paused job with priority.

---

## 5. Dashboard Rules Engine & Idempotent Job State Machine

### A. Live-Configurable Per-Portal Permissions (`public.portal_rules` table)
Every portal rule MUST be editable live from the frontend dashboard and read dynamically by the scheduler without restarting processes:
- `enabled` (bool) & `auto_apply_enabled` (bool)
- `max_applies_per_day` (int, Naukri default `50`) & `max_applies_per_hour` (int, Naukri default `10`)
- `max_job_age_days` (int, default `7` — reject jobs posted more than N days ago; live-configurable)
- `max_applicants` (int, default `300`) & `unknown_applicants_policy` (`allow_lower_bound` default so `"100+"` counts as `100`, or `allow` / `skip` / `needs_review`)
- `min_delay_sec` & `max_delay_sec` (randomized human-like jitter between applications, default `45`–`150` seconds)
- `active_hours_start` / `active_hours_end` + `timezone` (default `08:00`–`23:30` `Asia/Kolkata` IST)
- Candidate preferences in `candidate_profiles.preferences`: `target_roles`, `keywords_required`, `keywords_excluded`, `tech_stack`, `remote_policy`, `min_ctc`, `company_blacklist`, `skill_match_mode` (e.g., `any`), minimum match score.
- **Policy Transition Note:** `public.portal_rules` supersedes the older Naukri lifetime 3→4 / hourly 1 supervised allowances once migration 004 is active.
- Dashboard must display a locked read-only badge: **`Gmail Permission: Read + Draft Only (Sending Disabled)`**.

### B. Idempotent Job State Machine & Never-Replay Guardrail
Every application is uniquely identified in `public.applications` by `(platform, external_job_id)` plus secondary cross-platform deduplication on normalized `dedup_key` `(company_name, role_title)`.

Valid state transitions (`backend/app/browser_v2/state.py`):
```text
DISCOVERED
  -> FILTERED_OUT          (failed age, applicant count, blacklist, external site, or preference rule)
  -> SCORED                (passed hard filters + preference match)
  -> APPLYING              (acquired worker lock / reserved BEFORE clicking Apply)
  -> WAITING_FOR_USER      (Telegram HITL triggered; non-blocking)
  -> APPLIED               (verified portal submission receipt; TERMINAL)
  -> QUOTA_HIT_PENDING     (dashboard or portal daily/hourly limit reached)
  -> DRAFTED_AND_QUEUED    (Gmail draft created + retry_after set for next reset)
  -> SUBMISSION_UNKNOWN    (ambiguous post-click outcome or migrated quarantine; TERMINAL)
  -> FAILED                (permanent error after bounded retries; dead-letter logged)
```

**Never-Replay Guardrail:** `APPLIED` and `SUBMISSION_UNKNOWN` are terminal for automation and MUST NEVER be applied to again, including the historical quarantined Naukri jobs migrated as `SUBMISSION_UNKNOWN` (`reason=migrated_historical_quarantine_never_replay`) and prior confirmed applications migrated as `APPLIED`. Every live apply reserves `APPLYING` before clicking; any exception or ambiguous confirmation after clicking transitions to `SUBMISSION_UNKNOWN`.

---

## 6. Continuity, Workspace Ownership, Coding Standards & Verification

### A. Account-Independent Continuity & Workspace Lifecycle
- Canonical local repository: `/Users/karanagg/Desktop/Projects/automated-apply` (`karanagg166/automated-apply`). Never create duplicate full clones; use linked Git worktrees under `<repo>/.worktrees/<name>` if isolation is needed, and inspect `.git/automated-apply/worktree-ownership.json` before touching shared checkouts. Follow [the workspace policy](docs/workspace-policy.md).
- Keep [the resume record](docs/project-state.md) and private snapshots updated at milestones (`uv run --no-project python scripts/project_continuity.py snapshot|verify|resume`). Never rewrite Codex account ownership or session identities.
- Never delete directories, historical releases or worktrees without separate explicit owner approval of the exact cleanup batch.

### B. Coding Style & Development Commands
- **Python:** 4-space indentation, `snake_case` modules/functions, `PascalCase` classes; keep HTTP handlers thin and business logic in services/repositories (`backend/app/browser_v2/`, `backend/app/services/`).
- **TypeScript / Next.js:** Prettier, 2-space indentation, `PascalCase` React components, `kebab-case` filenames (`frontend/src/`). Regenerate OpenAPI types after API contract changes (`backend/venv/bin/python backend/scripts/export_openapi.py`, then `pnpm -C frontend api:types`).
- **Standard Commands:**
  - Migration check/apply: `backend/venv/bin/python -m backend.scripts.migrate_v2_core check` (then `apply --expected-fences N`, then `apply-phase9` for followup 005)
  - Browser v2 CLI: `backend/venv/bin/python -m backend.app.browser_v2.cli {login-setup|check-session|test-apply|mcp|sync-profile|health-check}`
  - API & Frontend dev: `uvicorn backend.app.main:app --reload --port 8000` and `pnpm -C frontend {install|dev|build|typecheck|format:check|test|e2e}`

### C. Mandatory Post-Edit Verification Gate & Turn Reporting
After every change, run and verify (never weaken or delete tests to get green):
1. `backend/venv/bin/ruff check --isolated --select E9,F,I <changed Python files>` (and full `ruff check` on v2 modules)
2. `uvx --python 3.11 mypy@1.18.2 --python-executable backend/venv/bin/python --ignore-missing-imports --follow-imports=silent --check-untyped-defs --warn-unused-ignores --explicit-package-bases <new/modified v2 modules>`
3. Relevant `pytest` suites (`backend/venv/bin/python -m pytest ...`, plus full `backend/tests` suite at milestones; PostgreSQL integration tests via `PROFILE_TEST_DATABASE_URL` or local disposable PG17)
4. Frontend checks when UI/contracts change (`pnpm -C frontend typecheck`, `pnpm -C frontend format:check`, `pnpm -C frontend test`)
5. `secretlint --secretlintrc .secretlintrc.json --secretlintignore .secretlintignore` over tracked and new untracked files (excluding `repomix-output.xml`)
6. **Turn Reporting:** At the end of each turn, overwrite `LATEST_REPORT.md` (gitignored) with only that turn's report, and keep chat replies to **three short lines**.
