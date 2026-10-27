# Phase 2 local integration — 2026-10-27

The primary repository is `/Users/karanagg/Desktop/Projects/automated-apply`. Its local integration branch is `integration/phase2-combined-20261027`. No integration push, GitHub feature merge, deployment or installed-service replacement was performed.

## Preserved histories and local integration

- Original checkout: `feat/phase1-local-connections` at `7dfe694`, with 13 tracked changes and three untracked source/instruction files.
- Backend: `582f0dd`, preserved on `feat/phase2-codex-live-discovery` and in PR #33. The workflow-only policy is already on remote main through PR #32.
- Gemini: verified actual head `695df6a`, including implementation commits `52a32eb` and `b1aa304`. Its branch was fetched directly from `/Users/karanagg/Desktop/Projects/automated-apply-gemini-phase2` into the original repository. No Gemini GitHub push was required.
- Merge `130d101` preserves both agent histories and the original checkout's ancestry. Testing used `/tmp/automated-apply-phase2-integration`, a linked worktree of the original repository, rather than a duplicate clone.
- Integration fixes are `66d09ab`; combined-session test setup is `018d250`. The tested implementation is `018d250`. The final checkout/report commit is recorded in the private manifest and delivery response; no application code differs from the tested implementation.

The repository's AGENTS.md now requires one primary repository, separate branches/linked worktrees for parallel agents, explicit exclusive file ownership, and intentional hosted CI.

## Original dirty-file reconciliation

Before any checkout change, a mode-0700 private evidence directory received the original status, binary patch, exact dirty-file archive, configuration fingerprints and a verified complete Git bundle. Branch `backup/original-before-phase2-integration-20261027` preserves the original HEAD. A retained stash object preserves the tracked edits without rewriting their history.

The tracked edits were pnpm changes already covered by the newer integrated source. Their six overlap conflicts were reviewed individually:

| Path | Resolution |
| --- | --- |
| `.gitignore` | Retain pnpm lockfile exclusions and newer browser-artifact exclusions. |
| `docs/google-drive-resume-sync.md` | Retain the working `pnpm -C frontend test` invocation. |
| `docs/phase10-automation.md` | Retain pnpm test/build commands and the converted E2E command. |
| `docs/phase7-deployment.md` | Retain the working pnpm test invocation. |
| `docs/phase7-frontend.md` | Retain the working pnpm test invocation and pnpm browser installation. |
| `frontend/Dockerfile` | Retain the pnpm workspace input and preinstall guard. |

The package script merge duplicated the same preinstall property; the canonical single entry was retained. Other original documentation edits were already present upstream. The original untracked command-tool draft differs from the reviewed current implementation; its exact contents and comparison remain archived privately. It was preserved for recovery and was not installed over current profile, permission and lifecycle gates. The untracked instruction/preinstall files were already represented in tracked source; the integrated instructions also contain the new repository policy.

The original dirty files and private configuration were checked byte-for-byte against the inventory before final reconciliation. Only reviewed tracked/source paths were moved or restored. Ignored credentials, resumes, reports, existing Git history, service wiring and installed release directories were preserved.

## Combined behavior fixes

- Public discovery selection honors `enabled`, direct-API/read-only capability, supported job operations, pricing and availability. Manual imports and disabled providers remain unavailable in that selector.
- Approved criteria remain stable while a request is pending. Running/interrupted outcomes are explained, and the refresh action reads the saved run through GET without repeating provider execution.
- Job rows distinguish owner-reported submissions, provider confirmation and a legacy applied flag. They accept the backend's `employee_count`/`team_size_band` evidence and display a salary upper bound without inventing a minimum.
- The combined E2E suite reuses an actually issued owner session within a worker. Every journey starts with an anonymous browser context; security assertions run before session restoration. Authentication, CSRF and login throttling are unchanged.

## Local verification

| Check | Result |
| --- | --- |
| Full integrated backend, disposable PostgreSQL 17.11 | 2,264 passed, zero failed/skipped; two existing pypdf warnings; 659.46 seconds |
| Frontend unit tests | 93 passed across 16 files |
| Frontend TypeScript | Passed |
| Frontend Prettier | Passed |
| Next.js production build | Passed |
| Dashboard E2E through actual FastAPI/BFF | 12 passed, including discovery failure persistence/status inspection and packet review |
| PostgreSQL/browser E2E | 12 passed, 1.1 minutes |
| OpenAPI export and generated frontend types | Regenerated locally; no contract/type diff |
| Ruff, full-app Bandit, Actionlint | Passed |
| Secret/private-artifact/ownership checks | Passed; scanner policy unchanged and private artifacts excluded |
| Original-checkout verification | Source/configuration fingerprints verified; post-switch smoke results are retained in the private final manifest |

Heavy browser and database suites ran sequentially. Tests used fictional profiles, dedicated fixture browser contexts, temporary databases and existing outbound-HTTP denials. No live candidate data, online database operations, employer submissions, Gmail/LinkedIn actions or paid calls were involved. Existing fixture-only submission tests do not establish a real submitted application.

Initial combined E2E failed at the eleventh login because separately authored files exhausted the existing ten-attempt limiter. A first session-helper attempt captured cookies before authentication completed; that timing error was corrected. The final full E2E suite passed with no skips and no authentication-policy changes. Initial failure logs remain private.

Commands and detailed logs are retained outside Git under `~/Library/Application Support/Automated Apply/phase2-integration-evidence`. The Python interpreter is the primary repository's Python 3.11 venv, updated to the existing lockfile. Frontend installation used only pinned pnpm with the frozen lockfile and offline store.

Representative commands, from the integration worktree:

```sh
pnpm -C frontend install --frozen-lockfile --offline
pnpm -C frontend test
pnpm -C frontend typecheck
pnpm -C frontend format:check
/path/to/primary/backend/venv/bin/python backend/scripts/export_openapi.py
pnpm -C frontend api:types
git diff --exit-code -- frontend/src/types/api.d.ts
pnpm -C frontend build
PYTHON=/path/to/primary/backend/venv/bin/python pnpm -C frontend e2e
PROFILE_TEST_DATABASE_URL="$PROFILE_TEST_DATABASE_URL" PYTHON=/path/to/primary/backend/venv/bin/python pnpm -C frontend e2e:browser
PROFILE_TEST_DATABASE_URL="$PROFILE_TEST_DATABASE_URL" /path/to/primary/backend/venv/bin/python -u backend/scripts/run_backend_ci.py \
  --output "$PRIVATE_EVIDENCE/full-backend" --seconds 900 \
  /path/to/primary/backend/venv/bin/python -u -m pytest backend/tests -q --durations=15 \
  -o faulthandler_timeout=60 --junitxml="$PRIVATE_EVIDENCE/full-backend/pytest.xml"
```

The PostgreSQL URL pointed only to the dedicated localhost fixture container, limited to 512 MiB. Existing installed API/frontend/Telegram processes retained their baseline release paths and configuration. The installed UI remains at its prior release until a separately authorized rollout.

## CI and cleanup

All three integrated workflows have only `workflow_dispatch`. Actionlint and YAML checks verified the definitions. GitHub's latest observed hosted run still belongs to baseline `975b8fc`; no integration branch was pushed, and no hosted workflow was dispatched or rerun. Older branches need the manual-only policy before any push.

After successful verification and checkout reconciliation, these Phase 2 paths are eligible for cleanup:

- `/Users/karanagg/Desktop/Projects/automated-apply-gemini-phase2`: a full temporary clone. Its complete feature history is retained in the primary repository; its ignored verification reports, including the fictional PDF, are archived privately. Check for new changes before removing the directory.
- `/Users/karanagg/Desktop/Projects/automated-apply-codex-phase2`: a linked worktree, not a second clone. Its branch/history/evidence are preserved. Remove it through `git worktree remove`, after checking for new changes.
- `/tmp/automated-apply-phase2-integration`: the testing worktree, detached after the verified branch moves to the primary checkout. Its reports are archived. Remove through `git worktree remove` after checking for new changes.

Example worktree cleanup, after verifying clean status:

```sh
git -C /Users/karanagg/Desktop/Projects/automated-apply worktree remove /Users/karanagg/Desktop/Projects/automated-apply-codex-phase2
git -C /Users/karanagg/Desktop/Projects/automated-apply worktree remove /tmp/automated-apply-phase2-integration
```

No temporary clone or worktree was deleted automatically. Do not remove installed release/rollback worktrees, the private application-support backups, other dirty worktrees or the separate Zoho clone as part of this cleanup. They were inventoried and left intact. Preserve the original backup branch and stash until the owner no longer needs the old checkout state. New parallel work must use linked worktrees of the primary repository.

**Local tests passed; hosted CI not run by cost policy.**
