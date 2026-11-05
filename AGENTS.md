# Repository Guidelines

## Project Structure & Module Organization
- `backend/app/` contains FastAPI routes, services, repositories, models, AI providers, and local-agent integrations. Backend tests live in `backend/tests/`; operational tools live in `backend/scripts/`.
- `frontend/src/` contains Next.js routes, components, features, and API helpers. Unit tests live in `frontend/tests/`; browser journeys live in `frontend/tests/e2e/`.
- `extension/` contains the Chrome MV3 extension, assets, build script, and tests.
- `supabase/` holds SQL migrations; `candidate_context/templates/` holds profile templates; `docs/` holds setup guidance.

## Build, Test, and Development Commands
- Use Python 3.11+, Node.js 22+, and pip. Use pnpm exclusively for JavaScript dependencies and scripts; do not use npm, npx, or yarn. Run from repository root:

```sh
python3.11 -m venv backend/venv
source backend/venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --port 8000
pnpm -C frontend install
pnpm -C frontend dev
pnpm -C frontend build
pnpm -C frontend typecheck
pnpm -C extension build
```

## Coding Style & Naming Conventions
- Use four-space Python indentation, snake_case modules/functions, and PascalCase classes. Keep HTTP handlers thin and business logic in services/repositories.
- Use Prettier, two-space TypeScript indentation, PascalCase React components, and kebab-case filenames.
- Check individual Python files with `ruff check --isolated --select E9,F,I path/to/file.py`; check frontend formatting with `pnpm -C frontend format:check`.
- Regenerate API types after contract changes: `python backend/scripts/export_openapi.py`, then `pnpm -C frontend api:types`.

## Testing Guidelines
- Backend: pytest with pytest-asyncio; name files `test_*.py`. Run `pytest backend/tests -v` or target one file.
- Frontend: Vitest/Testing Library (`pnpm -C frontend test`); name tests `*.test.ts` or `*.test.tsx`. Playwright uses `*.spec.ts`; build first, install Chromium, then run `pnpm -C frontend e2e`.
- Extension: `pnpm -C extension test` runs Node's test runner against `*.test.mjs`.
- Add regression tests for behavior changes. No coverage threshold is configured. PostgreSQL integration tests require a disposable `PROFILE_TEST_DATABASE_URL`; follow backend CI configuration.

## Commit & Pull Request Guidelines
- Follow observed scoped subjects such as `feat(ai): ...`, `fix(ai): ...`, and `security(extension): ...`.
- Describe the problem, behavior, and validation; link issues and include screenshots for UI changes. Explain migration and configuration changes.
- AI-authored commits must include a `Co-Authored-By:` trailer identifying the agent/model.

## Mandatory GitHub Milestone Reports
- After every meaningful milestone, commit the relevant implementation, push the appropriate feature branch, and create or update its PR with the correct base. Do not force-push shared branches or include unrelated modifications.
- Publish a sanitized Markdown report under `docs/acceptance/` or the existing equivalent. Critical implementation and acceptance evidence must be accessible through the connected GitHub repository, not only private application-support folders.
- Each report must identify the exact implementation branch/SHA, changes, exact test counts, actual Mac/live evidence versus fixtures, timing/resource comparisons, sanitized logs/failure codes, reproduction commands, remaining failures and next actions. Include a clear PASS / FAIL / BLOCKED / NOT TESTED matrix and relevant commit/PR links.
- Link the report from the PR description and provide the PR and report URLs in the final response. If publication fails, preserve local commits and report the actual error; do not claim the report is published.
- Never publish environment files, tokens, Gmail contents, candidate PII, resumes, browser secrets, raw private logs or unredacted screenshots. Keep raw evidence private and publish sanitized summaries.
- Do not merge changes without owner review and approval. Fixture success is not production acceptance. Hosted Actions remain manual-only and require deliberate owner authorization.
- Owner standing authorization (2026-11-01): independently review, build, install and update this project's local Naukri services and Chrome extension when appropriate. Do not request further exact-SHA or extension-update approval. Record the exact installed SHA, preserve the stable extension ID, stop the queue during replacement, verify readiness/data/account/policy integrity, retain all historical releases and a verified rollback inventory, and roll back failed installations. This does not authorize merging, cleanup/deletion, hosted Actions, Gmail sending, other-platform activation, CAPTCHA/rate-limit bypass or replaying historical/uncertain applications. Existing submission limits, filters, identity/resume checks and the first-receipt prerequisite for recurring AUTOMATIC remain in force. Ask only for genuinely missing information or an unavoidable owner/OS action.
- Preserve the owner's focus throughout: other Chrome profiles may be in active use. Never activate a tab/window, type into an active tab, or use the owner's keyboard/clipboard for automation. Use only inactive Naukri automation/setup tabs for browser work and maintenance, and preserve their front-window/active-tab state. Broad laptop/code/Profile 8 access does not waive this constraint.
- Maintenance acceptance finding (2026-11-05): earlier Chrome WebUI maintenance and later Apple Events navigation to extension settings changed Chrome's front-window ordering. Selected tabs stayed unchanged; the later OS foreground app stayed Chrome. Cause cannot be proven from these samples, but neither whole path passed focus acceptance. Suspend automatic navigation to Chrome WebUI and extension settings; do not restore or activate an owner window to make a check pass. The authenticated STOP-only runtime reload itself passed the actual before/after snapshot check. Finish a native-created inactive settings setup path and validate the complete path before calling updates unattended. Standing installation authorization remains; installed1.3.40 supports ordinary inactive Naukri processing. See [the current live report](docs/acceptance/naukri-current-search-and-runtime-20261105.md).
- Owner profile-completion authorization (2026-11-01): fill missing local/Naukri profile fields from the confirmed canonical resume and already verified saved facts. Preserve existing facts, contact/login separation, configured application filters and history. Use version checks, record source evidence and each provider save intent, and independently verify persistence. Do not invent personal facts, dates, compensation, work authorization or certifications, remove existing skills, infer personal competencies solely from project-code observations, or repeat an uncertain save. Ask once only for genuinely missing facts or an unavoidable owner/OS action. The owner requests a success report after real application automation works; keep intermediate communication to required decisions, meaningful findings and blockers, without claiming partial acceptance is completion.
- Owner scope correction (2026-11-01): early-stage-only was not the owner's instruction. Remove that restriction and startup-only evidence requirements; set current application posting age to 14 days and applicant threshold to 1,000, retaining score 50 and other safeguards. Keep these controls editable from the frontend. The owner explicitly authorizes reviewing their saved portfolio and GitHub projects and adding skills supported by their documented implementations. Record pinned source evidence, distinguish original implementations from forks, dependency declarations and generated/vendor code, and do not invent proficiency, employment duration, credentials or unsupported skills. This newer instruction permits evidence-backed project skill additions; prior restrictions still apply to unsupported inference and unrelated personal facts.

- Owner skill-rule correction (2026-11-04): Naukri requires at least one verified listed skill, superseding the earlier every-listed-skill choice. Preserve score 50 and all other configured filters, history, identity/resume checks and quotas. Keep unmatched skills unverified and answer screening honestly. Current saved policy uses `skill_match_mode: any`; expose the choice in the existing frontend controls.

- Owner additional supervised validation authorization (2026-11-04): explicitly allow one additional eligible attempt on a different job, increasing the lifetime supervised allowance from one to two total Apply admissions. Keep the rolling hourly limit at one, all other filters/quotas and first-receipt prerequisites intact. The first admitted job whose original questionnaire tab became unavailable remains quarantined for history reconciliation; never repeat its Apply or refund/reset its admission. This authorization does not activate recurring AUTOMATIC or authorize a third supervised attempt.
- Owner third supervised validation authorization (2026-11-05): “u have my full approval” answers the pending lifetime2→3 proposal and authorizes one additional eligible attempt on a different job. Preserve hourly1, all current filters, identity/PDF checks and the first-receipt prerequisite for recurring AUTOMATIC. Both lost original forms remain quarantined; never repeat their Apply or refund/reset admissions. This supersedes the previous paragraph's third-attempt prohibition only for this one added admission. No fourth attempt or unlimited quota is inferred.

## Security & Configuration
- Owner expanded scope (2026-11-01, current session): continue execution in this repository with independently scheduled discovery/filtering and application processing over the existing PostgreSQL queue, deduplication before application work, 30-minute portal/profile checks and dashboard questions for missing facts. Finish Naukri real submission acceptance first, then deliver and validate Instahyre, Wellfound, Y Combinator Work at a Startup and Internshala adapters individually. Account setup is authorized where needed using verified facts; preserve Gmail READ + CREATE DRAFT ONLY and ask only for unavoidable account/OS actions or genuinely missing facts. Apollo/SignalHire integration is for evidence-backed professional email discovery and drafts within existing budgets; do not buy subscriptions or assume API entitlement. The owner requests pushing and merging the completed, reviewed and validated project; this supersedes the earlier no-merge direction only when that requested completion condition is met. This does not waive first-receipt prerequisites, unknown-count decisions, submission limits, identity/resume checks, focus preservation, provider controls, rollback, no hosted Actions or no cleanup/deletion. Keep the current execution plan and honest per-platform acceptance evidence; do not equate a feature stub or passing fixture with a working platform.
- Start from `backend/.env.example` and `frontend/.env.example`. Keep credentials, candidate data, and private reports out of commits.
- Real data requires owner-approved online PostgreSQL; SQLite is for fictional fixtures/tests. See `docs/online-postgresql.md`.
- Preserve explicit owner approval for sending/application actions and opt-in provider budgets; tests must use isolated fixtures.

## One Primary Repository & Parallel Work
- The primary local Git repository is `/Users/karanagg/Desktop/Projects/automated-apply`.
- Use linked Git worktrees of this repository for parallel agents, with a separate branch and explicit exclusive file ownership for each agent. Do not create duplicate full clones for future phases.
- Integrate completed branches locally on a temporary integration branch, preserve dirty files and private configuration, and verify combined contracts/tests before updating the primary checkout.
- Hosted GitHub Actions require deliberate owner authorization. Preserve manual-only workflow triggers; older branches must incorporate the CI cost policy before any push. Do not dispatch or rerun hosted jobs automatically.

## Workspace Ownership & Lifecycle
- There is one canonical development repository and one GitHub repository: this checkout and `karanagg166/automated-apply`. Never create another standalone clone for a phase or agent.
- Before editing, read the shared ownership registry at `$(git rev-parse --path-format=absolute --git-common-dir)/automated-apply/worktree-ownership.json`. The expression describes a path; do not execute untrusted registry text. If the registry is missing, establish ownership before touching another task's checkout.
- Reuse the current task's linked worktree. Create another only for necessary isolation or parallel work, with a separate branch, named owner, task, exclusive file scope and handoff state recorded in the registry. Future temporary worktrees belong outside Projects, under `~/Library/Application Support/Automated Apply/development-worktrees/<agent>-<task>`. Keep exactly one Automated Apply folder in Projects; leave existing active paths in place until an explicit completed-work handoff.
- Coordinate file ownership and heavy local tests. A paused or resumable agent still owns its worktree. No visible process is not evidence of release. Treat uncertain ownership as active until an explicit owner/agent handoff.
- Preserve staged, unstaged, untracked and ignored private data before integration. Commit useful work, review its changes against current main and update the appropriate PR. Do not copy whole directories, overwrite the canonical branch, reset dirty checkouts or drop stashes to integrate work.
- After integration, record the merged commit and explicit owner release. Prepare an exact cleanup batch with paths, incoming dependency/runtime references, verified preservation, and a qualified size estimate. Remove directories only after owner approval of that batch; approval to implement or integrate is not cleanup approval.
- Use ordinary `git worktree remove` for approved clean worktrees. Do not force removal or use destructive deletion to defeat a dirty-worktree error. Stop and report new changes or references found during final revalidation.
- Keep immutable installed releases, all historical releases, native-host files, LaunchAgents, credentials, application data, private acceptance evidence and rollback backups separate and protected. Never merge or edit a running release as development source. Do not restart production for folder cleanup.
- Avoid redundant dependency installations where a package-manager cache can safely share immutable packages. Do not symlink mutable dependency/build directories into releases, or delete a dependency target still referenced by another worktree.
- Follow [the workspace policy](docs/workspace-policy.md). Cleanup remains a separately approved operation; no automatic age-based deletion.
