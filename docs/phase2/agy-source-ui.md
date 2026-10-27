# Phase 2 AGY Job Source UI Improvement Report

## 1. Executive Summary & Git Isolation

This work improves the Opportunities (Jobs) dashboard in the Automated Apply frontend without modifying backend contracts, schemas, or API-generated types.

- **Baseline Commit:** `e08b7f0c6c961b0228eddfd70dabb8dbb4c63a88` (PR #34 integration base)
- **Worktree:** `/Users/karanagg/Desktop/Projects/automated-apply-agy-p22`
- **Branch:** `feat/p22-agy-job-source-ui`
- **Agent:** AGY Gemini 3.8 Flash High (lightweight frontend agent)
- **Exclusive Files Modified:**
  - `frontend/src/features/jobs.tsx`
  - `frontend/tests/jobs.test.tsx`
  - `docs/phase2/agy-source-ui.md` (this report)

All work was completed strictly inside the designated Git worktree without touching the primary checkout (`/Users/karanagg/Desktop/Projects/automated-apply`), Codex worktrees, backend code, database schemas, or hosted GitHub Actions.

---

## 2. Key Enhancements Delivered

### 2.1 Dynamic Source Derivation from `GET /discovery/sources`
- Previously, the source platform filter contained hardcoded providers (`arbeitnow`, `greenhouse`, `remotive`, `hacker_news`).
- The component now invokes `GET /discovery/sources` via TanStack Query (`sourcesQuery`) to dynamically populate the available source platform options.
- When new providers (such as Lever, Ashby, or future aggregators) are added to the backend source registry, the Jobs dashboard immediately reflects them without frontend code modifications.
- If a user previously selected a platform not yet in the catalog or observed in a saved job, that selection is preserved in the dropdown options to prevent unexpected filter resets.

### 2.2 Distinguishing Saved-Job Filters from Live Discovery Availability
- Saved-job search filters filter already-stored records in the database by their origin source platform.
- The UI avoids misleading users: providers are not marked as "live-verified" or "Free API" in the saved-jobs filter simply because they exist in the discovery catalog.
- Added explicit clarification in the filter panel:
  > *"Source filter searches saved opportunities by origin; catalog presence does not imply live verification."*
- Live discovery status, verification, and credentials remain managed separately on the Discover page (`/discover`).

### 2.3 Resilient and Graceful Degradation
- If `GET /discovery/sources` is delayed, fails with an HTTP error (e.g. 500, 503, network drop), or returns an empty/malformed list, the component gracefully falls back to `FALLBACK_SOURCE_OPTIONS` (`arbeitnow`, `greenhouse`, `remotive`, `hacker_news`).
- The Jobs dashboard remains completely interactive and never throws unhandled errors or displays broken UI.

### 2.4 Improved Zero-Results States
The zero-results state now distinguishes whether the user's active filters yielded no matches or whether the repository contains no saved jobs at all:
1. **Active Filters Match Nothing:**
   - **Title:** *"Room for the right opportunity."*
   - **Description:** *"No saved jobs match these filters. Broaden your criteria, reset your filters, or run a fresh discovery."*
   - **Actions:** Includes a prominent **"Reset filters"** button and a direct **"Discover jobs"** link (`/discover`).
2. **Unfiltered Repository Empty State (e.g. All tab with no criteria, or after reset):**
   - **Title:** *"No saved jobs yet"*
   - **Description:** *"No saved jobs found in your repository. Run a discovery to find and import opportunities."*
   - **Actions:** Includes a primary **"Discover jobs"** link (`/discover`).
3. **Filter Panel Reset Button:**
   - When any filter criteria are active, a ghost *"Reset filters"* button is also accessible directly inside the filter panel for quick resets.

### 2.5 Preservation of Core Features & Action Boundaries
- Preserved all status tabs (`not_applied`, `shortlisted`, `applied`, `packet_prepared`, `interview`, `rejected`, `all`).
- Preserved application packet preparation (`PrepareButton` -> `/applications/{id}`), shortlisting, external link verification (sanitizing unsafe schemes like `javascript:`), and submission badges (`provider_confirmed_submitted`, `user_reported_submitted`, `applied`).
- No changes to backend API contracts or schemas.

---

## 3. Local Verification Results

All checks executed locally using `pnpm`:

### 3.1 Unit & Feature Tests (`pnpm -C frontend test`)
- Total test files: **16 passed** (0 failed)
- Total tests: **100 passed** (0 failed)
- Focused `jobs.test.tsx`: **18 passed** (0 failed), including comprehensive coverage for:
  - Dynamic source derivation (including Lever and Ashby)
  - Distinguishing saved-job filters from live verification
  - Graceful fallback on failed source metadata requests (503 / network errors)
  - Fallback on missing or empty source metadata
  - Distinguishing filtered vs unfiltered zero-results states
  - Reset filters action in empty state and filter panel
  - Preservation of custom/uncataloged selected platforms
  - Accessible attributes (`aria-label`, `aria-pressed`)
  - Preparation buttons, external links, submission badges, and status tabs

### 3.2 TypeScript Typecheck (`pnpm -C frontend typecheck`)
- Command: `tsc --noEmit`
- Result: Clean exit (code 0), zero type errors.

### 3.3 Formatting Check (`pnpm -C frontend format:check`)
- Command: `prettier --check src tests *.ts *.mjs`
- Result: Clean exit (code 0), all files formatted with Prettier.

### 3.4 Production Build (`pnpm -C frontend build`)
- Command: `next build`
- Result: Compiled successfully in 2.5s via Turbopack, static page generation and route optimization passed with zero errors.

---

## 4. API Contract & Behavioral Observations

- `GET /api/v1/jobs/search` takes query parameter `platform` and filters saved job records by `source_platform` or source observations.
- `GET /api/v1/discovery/sources` returns a list of configured providers (`sources`) and public search settings (`people_search`).
- Because `GET /jobs/search` only returns `{ total, jobs }` for the queried parameters, the frontend distinguishes between filtered empty states and unfiltered empty states based on active query parameters (`status !== "all"` or active search terms/switches). When filters are reset to `status="all"` with no search terms, a 0-count cleanly signals an empty saved-job repository.
