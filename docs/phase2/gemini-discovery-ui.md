# Phase 2 Job Discovery Dashboard — Gemini Frontend Report

## 1. Executive Summary & Architectural Overview

As part of Phase 2 Job Discovery, the Next.js workspace frontend was improved to support genuine job discovery from legitimately free providers, inspect stored job records, apply supported search filters, and prepare manual application packets without automated actions.

All work was conducted in strict isolation:
- **Baseline commit:** `975b8fc0afa6b9ce1f30a21c0cdfa667bcfc3009`
- **Branch:** `feat/phase2-gemini-discovery-ui`
- **Isolated working directory:** `/Users/karanagg/Desktop/Projects/automated-apply-gemini-phase2`
- **Scope boundary:** Edited only `frontend/src/features/**`, related unit/E2E tests (`frontend/tests/**`), and documentation in `docs/phase2/gemini-*`. No backend code, database schemas, Supabase migrations, GitHub workflows, or extension files were modified.

---

## 2. Task A — Existing UI and API Review

The existing codebase and checked-in OpenAPI contracts (`frontend/src/types/api.d.ts`, `backend/app/schemas/discovery.py`, `backend/app/api/v1/discovery.py`) were thoroughly reviewed:

- **Startup Discovery Preservation:** The original Discover page (`frontend/src/features/discover.tsx`) supported startup-led discovery (`/startups/discovery/preview` and `/startups/discovery/runs`). This was preserved completely intact. An accessible tabbed interface was introduced to clearly separate **Job discovery** from **Startup discovery**.
- **Available Job Discovery Contracts:**
  - `GET /api/v1/discovery/sources`: Returns registered sources with adapter type, availability status, pricing (`free` vs `paid`), and board configurations.
  - `POST /api/v1/discovery/preview`: Takes `RunRequest` (strict schema forbidding extra fields) and generates an execution plan with 0 provider calls, estimated cost ($0.00 for free sources), and query parameters.
  - `POST /api/v1/discovery/runs`: Takes `RunRequest` with `idempotency_key`, queries upstream providers, ingests listings into the local database, and returns real insertion/duplicate/rejection counts.
  - `GET /api/v1/discovery/runs/{run_id}`: Inspects individual run statuses.
  - `GET /api/v1/jobs/search`: Queries stored job listings with parameters `role`, `location`, `skill`, `platform`, `remote_type`, `application_status`, `rank`, `page`, and `limit`.

---

## 3. Task B — Job Discovery Interface (`frontend/src/features/job-discovery.tsx`)

The new component provides a production-grade discovery interface:

1. **Source Selection & Provider Integrity:**
   - Legitimately free providers (`arbeitnow`, `remotive`, `hacker_news`, and `greenhouse` when boards are configured) are displayed as enabled and selectable.
   - Unconfigured sources (e.g. Greenhouse without board tokens) are marked `Configuration required` and disabled.
   - Paid or Apify-dependent providers (e.g. `naukri`, `indeed`, `glassdoor`) are marked with their pricing and disabled, preventing unintended charges.
   - Provider capability tags display pricing, adapter type, and read-only status.

2. **Search Parameters:**
   - Role / technology keywords input (parsed into `query.keywords`).
   - Location input (parsed into `query.locations`).
   - Workplace selector: Any, Remote only, Hybrid, On-site (mapped to `query.remote_preference`).
   - Result limit selector: 10, 20, 50 (bounded between 1 and 100).
   - "Incorporate target preferences from saved profile" checkbox (`use_profile: true/false`).

3. **Preview Workflow Before Execution:**
   - "Preview discovery plan" calls `POST /discovery/preview`.
   - Renders plan summary: effective keywords/locations, remote preference, result limit, estimated cost (Free $0.00), and confirms 0 provider calls were made.
   - Requires explicit user acknowledgment via a confirmation checkbox before the execution button is enabled.

4. **Stable Idempotency Key Across Retries:**
   - When a preview or run is prepared, a unique key (`job_disc_<hex>`) is generated.
   - If a run fails due to network timeout (504), rate limits (429), or upstream provider hiccups, clicking **"Retry discovery with same key"** reuses the identical `idempotency_key`. This ensures the backend `on_conflict_do_nothing` logic retrieves existing run records rather than creating duplicate jobs or replay anomalies.
   - Changing search criteria (source, keywords, locations, etc.) or clicking "Start new search" clears the key so subsequent runs receive fresh idempotency tokens.

5. **Honest Outcomes & Cache Refresh:**
   - On completion, `runResult` displays real ingestion numbers: Discovered, Saved (New), Duplicate, Rejected, and Failed counts.
   - Automatically invalidates `jobs` query cache in React Query (`client.invalidateQueries({ queryKey: ["jobs"] })`).
   - Handles distinct statuses honestly:
     - `no_results`: Clear guidance that provider found zero matching jobs.
     - `rate_limited`: Explains provider throttling and provides retry options.
     - `source_unavailable`: Informs user the upstream service is unreachable.
     - `configuration_required`: Prompts user to check credentials in connections.

---

## 4. Task C — Improved Job Results & Filtering (`frontend/src/features/jobs.tsx`)

The stored jobs explorer was updated to provide accurate, transparent evidence:

1. **Supported Views & Status Tabs:**
   - Dedicated views for `Not Applied`, `Shortlisted`, `Applied`, `Packet Prepared`, `Interview`, `Rejected`, and `All`.
   - Uses backend `application_status` parameter to filter by actual lifecycle states.

2. **Supported Filters:**
   - Role / Title (`role`)
   - Location (`location`)
   - Skill (`skill`)
   - Source Platform (`platform`: Arbeitnow, Greenhouse, Remotive, Hacker News)
   - Workplace preference (`remote_type`: Remote, Hybrid, On-site)
   - Profile match ranking (`rank=true`)

3. **Truthful Labels & Missing Evidence Handling:**
   - **Dates:** Explicit distinction between publication date (`date_posted`) and observation date (`last_observed_at`). If publication date is missing, labeled honestly as `Published date unknown`. Observation dates are labeled as `Observed <date>`.
   - **Company Evidence:** If `company_name` is absent, displays `Company evidence not available`.
   - **Team Size:** Displays `Team size: <count>` if established in company intelligence; otherwise displays `Team size: Unknown`.
   - **Salary:** Formats minimum, maximum, currency, and period if supplied; otherwise displays `Salary: Not disclosed`.
   - **Remote Status:** Displays explicit remote status (`Remote`, `Hybrid`, `On-site`) or `Remote status unknown`.

4. **Clear Action Boundaries:**
   - **Prepare application:** Prominent button to create/view an application packet (`/applications/{id}`).
   - **Open application site:** Verified external link using `External` component (enforces HTTPS, blocks credentials and `javascript:` URIs).
   - **Application submitted:** Displayed as a clear `<Badge tone="green">Application submitted</Badge>` when an application has been recorded as submitted (`user_reported_submitted`, `provider_confirmed_submitted`, or `status == "applied"`).

---

## 5. Task D — Mocked UI and E2E Test Report

### Vitest Unit Test Suite (`frontend/tests/`)
- Total test files: **16 passed** (0 failed)
- Total tests: **88 passed** (0 failed)
- Execution time: ~6.5 seconds

Key test coverage added:
- `tests/job-discovery.test.tsx`:
  - Free available vs disabled/unconfigured provider visibility
  - Plan preview without live provider execution
  - Explicit consent gating before execution
  - Idempotency key stability across network retries
  - Fresh idempotency key on new search parameters
  - Honest handling of `no_results`, `rate_limited`, `source_unavailable`, and `configuration_required`
  - Invalidation of `jobs` cache upon run completion
- `tests/jobs.test.tsx`:
  - Status tabs (`not_applied`, `shortlisted`, `applied`)
  - Filter queries for title, location, skill, and source platform
  - Safe external link validation (blocking dangerous URLs like `javascript:`)
  - Distinction between "Prepare application", "Open application site", and "Application submitted"
  - Display of match scores and missing skills
  - Truthful labels for missing salary, unverified company, unknown team size, and unknown dates
  - Pagination controls and empty state display
  - Verification that no job submission or Gmail sending occurs from UI

### Playwright E2E Fixture Journeys (`frontend/tests/e2e/`)
Executed against isolated FastAPI test backend with fictional SQLite fixture:
- `tests/e2e/phase2-discovery.spec.ts`: Passed (3.0s)
  - Full journey: login -> discover -> job discovery tab -> preview plan -> inspect 0 provider calls -> navigate to jobs table -> verify status tabs -> filter by title -> verify pagination.
  - WCAG 2.1 AA accessibility audit: 0 critical or serious violations.
- `tests/e2e/journeys.spec.ts`: Passed (8/8 tests, 30.7s)
- `tests/e2e/phase1-connections.spec.ts`: Passed (1/1 test, 8.1s)

### Quality Checks
- `pnpm -C frontend typecheck`: Passed (`tsc --noEmit` exited 0)
- `pnpm -C frontend format:check`: Passed (All files match Prettier code style)
- `pnpm -C frontend build`: Passed (Next.js production build succeeded in 1.5s)

---

## 6. Screenshots Generated from Fictional Fixtures

Screenshots were captured during automated Playwright fixture execution and saved in `reports/`:
1. `reports/phase2-job-discovery.png`: Job discovery interface showing source configuration, search filters, and preview plan evidence card.
2. `reports/phase2-jobs-table.png`: Jobs results table displaying truthful salary, company evidence, match scores, observation dates, and action boundaries.

---

## 7. Honest List of Features Blocked by Unavailable Backend Data

1. **Apify / Paid Portals (Naukri, Indeed, Glassdoor, Wellfound):**
   - The backend Apify adapter requires live API tokens and configured actors. Because no paid credentials or actor budgets are configured in this environment, these providers remain disabled in the source selector.
2. **Greenhouse Public Discovery Without Boards:**
   - Greenhouse requires configured company board tokens in `GREENHOUSE_BOARDS`. Without configured boards, Greenhouse is correctly labeled as `Configuration required` and cannot be queried.
3. **True Publication Dates for Feeds Without Posted Timestamps:**
   - Certain upstream feeds only provide ingestion/observation timestamps rather than original posting timestamps. The UI does not fabricate publication dates; it truthfully labels them as `Published date unknown` while showing `Observed <date>`.
4. **Company Team Size & Headcount Evidence:**
   - Job postings typically lack independent company verification. Unless company intelligence was established by startup discovery, team size remains truthfully labeled as `Team size: Unknown`.

---

## 8. Hosted GitHub CI Statement

Hosted GitHub Actions CI was **intentionally not executed** in accordance with project safety guidelines:
- Work remained completely isolated in local branch `feat/phase2-gemini-discovery-ui`.
- All verification was completed using local mocked unit tests, local Next.js builds, and isolated local Playwright fixtures.
- No push to remote GitHub will occur until Codex confirms the workflow trigger policy is safely updated.
