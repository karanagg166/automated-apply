# Phase 2.2 public ATS discovery — 2026-10-27

Implementation commit: `37173ac0722ebd26536d2fedce50ea03bb80f7ea`.

The linked worktree is `/Users/karanagg/Desktop/Projects/automated-apply-codex-p22`, branch `feat/p22-codex-public-ats`, based on PR #34's integrated head `e08b7f0c6c961b0228eddfd70dabb8dbb4c63a88`. Initial inspection confirmed a clean primary checkout, the expected ancestry and existing recovery/runtime worktrees. No original checkout, AGY worktree, recovery branch, private configuration or installed service was changed.

## Public interfaces and configuration

Documentation was reviewed on 2026-10-27. These are verified **documented interfaces**, not live-tested employer feeds. The owner explicitly selected fictional-only verification; no live Lever or Ashby board was requested.

| Provider | Public GET interface | Required operator configuration |
| --- | --- | --- |
| Lever global | `https://api.lever.co/v0/postings/{SITE}?mode=json` | `LEVER_BOARDS` maps allowlisted site IDs to employer names; `LEVER_REGION=global` |
| Lever EU | `https://api.eu.lever.co/v0/postings/{SITE}?mode=json` | The same allowlist with `LEVER_REGION=eu` |
| Ashby | `https://api.ashbyhq.com/posting-api/job-board/{JOB_BOARD_NAME}?includeCompensation=true` | `ASHBY_BOARDS` maps allowlisted board IDs to employer names |

Lever's [official Postings API documentation](https://github.com/lever/postings-api) describes public published postings and site identifiers. Its [API FAQ](https://hire.lever.co/developer/support) distinguishes this public interface from the credentialed employer API. The implementation uses only GET. The [official API reference](https://hire.lever.co/developer/documentation) supplies explicit salary interval spellings, including `per-year-salary` and `per-hour-wage`; reading that documentation does not call its authenticated endpoints.

Ashby's [official public Job Postings API documentation](https://developers.ashbyhq.com/docs/public-job-posting-api) defines the board identifier, optional public compensation, listed visibility, workplace fields and publication timestamp. Unlisted postings are excluded. `isRemote=true` can include hybrid, so the adapter relies on `workplaceType` for the precise remote policy. `publishedAt` means last publication, retained with that provenance. Missing fields stay unknown.

Both allowlists default to `{}` and advertise `configuration_required` until configured. Each allows at most ten distinct board IDs, restricted to 1–100 ASCII letters, digits, underscores or hyphens, paired with a nonempty employer name. Employer display names come from that reviewed mapping; the provenance records their basis. Case-duplicate boards, URLs, path injection and blank company names are rejected. Lever region is a fixed global/EU enum. No request may override the board or supply a feed URL.

The existing fixed-host HTTP transport retains disabled redirects, a decoded 8 MiB response limit, 15-second HTTP operation limits, at most two read-only transport/5xx attempts and the 75-second adapter deadline. There is no retry for 401/403/404/429 or redirects. Returned posting/application links must belong to the configured board on the exact hosted ATS domain; links are validated, never fetched. Board reads are sequential, use existing local pagination and obey the existing maximum of 100 selected records. An oversized employer feed fails explicitly rather than bypassing the cap. Both sources use the existing durable source pacing with a conservative local 60-second interval, not a claim of a vendor-published quota.

Titles, descriptions, locations, employer mappings, hosted URLs, explicit remote/employment fields, and usable structured salary groups are normalized through `NormalizedJob`. Lever publication dates remain unknown: the public field reference does not establish one. Salary amounts require finite numeric bounds, an explicit ISO-style currency code and a representable period. Equity, ambiguous ranges, unsupported intervals and multiple Ashby salary summary components do not become asserted salary. Raw evidence remains in provenance.

Configuration is an operator-reviewed employer allowlist, not an assertion of blanket bulk-collection or redistribution rights. Review an employer board and scope before any future live verification. No paid actor, generic scraper, LinkedIn automation or submission path was added or enabled.

## Reliability investigation and changes

The earlier 27-listing online Greenhouse batch exceeded the 90-second deadline and rolled back. Historical evidence also records a separate one-connection profile/pacing deadlock fixed before this branch. The failed larger batch did not retain provider/ingestion/matching stage timings, so its **precise historical bottleneck cannot be established** without inventing evidence. This work does not claim that local fixtures reproduce online latency or that the larger online batch now passes.

Measurements against fictional PostgreSQL 17 batches with a one-connection pool did identify redundant work. The original ingestion repeated source/URL/legacy identity checks after resolving the company, repeated company resolution, then individually reloaded jobs and companies for matching. The benchmark counted actual SQL statements, including SAVEPOINT/RELEASE, while preserving unique insert guards and human state.

| Fictional batch | Original SQL statements | Revised SQL statements |
| --- | ---: | ---: |
| 3 jobs | 55 | 38 |
| 27 jobs | 438 | 277 |
| 100 jobs | 1,606 | 1,007 |

Each benchmark sequence inserts all requested distinct job URLs; fixture company domains are unknown, preventing false content-identity merges. Each row commits the complete batch and its matching/audit output. Company reuse across rows accounts for one statement compared with a fresh database for a single size.

A separate sensitivity experiment injected **50 ms of artificial latency before each SQL statement**, without contacting a remote database. A fresh 27-job batch fell from 24.2000 seconds / 439 statements to 15.4713 seconds / 278 statements. This supports reducing round trips; it is not a real network measurement or a proof of the earlier timeout's exact cause.

The implementation reuses the existing architecture:

- Continue company/content identity checks after the first source/URL/legacy checks under the same transaction-scoped ingestion lock. Retain unique insert-conflict guards and every record's savepoint.
- Cache only consecutive, identical employer evidence resolved by the company repository. A source job's stronger identity never resolves a different employer-ambiguous job. Cache invalidation and ambiguity regression cases cover domain discoveries within a batch.
- Load at most 100 saved jobs and companies for matching with one outer join. Scores, explanations and human statuses stored on jobs remain untouched; rankings retain the saved profile version.
- Retain the default 90-second discovery deadline and existing concurrency cap. Extend deadline coverage to profile loading and finalization/commit. No pool-size increase, ingestion parallelism, timeout increase or incremental batch commit was introduced.
- Save bounded stage durations, record-attempt count, maximum per-record duration, and public HTTP attempts/bytes/JSON timings in the existing `DiscoveryRun.usage` JSON. Execution timing/deadline begins after the durable idempotency claim; saved timings exclude commit acknowledgement time. Benchmark wall time includes both claim and commit. An interrupted worker with no final audit remains inspectable through the existing lease-expiry `recovery_required` rendering.
- Inspect the durable audit after an exception during commit. A successful committed result with a lost acknowledgement is returned unchanged. Failed batches roll back; independent failure audits retain the failed phase. If the database prevents that audit too, the original running claim remains for explicit recovery. Nothing automatically replays a provider, paid request, application or other ambiguous operation.

## Verification

All new feed bodies, profiles, employer identities and application packets were fictional. External HTTP is blocked by the existing pytest fixture; injected transports assert GET and known provider hosts. PostgreSQL was a new dedicated `postgres:17-alpine` container, version **17.11**, on loopback port 55432 with a one-connection runtime test pool. Tests create and remove uniquely named databases. Restart testing targets only the explicitly named disposable container.

| Check | Result |
| --- | --- |
| Focused discovery/application regression suite, final implementation | **298 passed, 0 failed, 0 skipped; 31.25 seconds** |
| New PostgreSQL integration cases | **12 passed**, including actual container restart, disconnect, rollback, ambiguous commit acknowledgement, repeated/concurrent idempotency, source pacing, bounded concurrency, profile/ingestion deadlines, company ambiguity and saved human application state |
| Ruff `--isolated --select E9,F,I` on changed Python files | Passed |
| Bandit on changed production Python files | Passed |
| `git diff --check` | Passed |
| OpenAPI schema comparison against the starting primary checkout | Identical canonical JSON: 265,139 bytes; SHA-256 `9afa7044efc484a60bd2cf32ee1550a5018f8925efe2ced6f22910413930b1da` |
| Full backend suite after implementation commit | **2,402 passed, 0 failed, 0 skipped; 906.61 seconds**; two existing pypdf fixture warnings; supervisor exit 0 |

Adapter cases cover valid/malformed top-level feeds and records, missing optional fields, inconsistent/duplicate postings, unlisted visibility, unconfigured boards, HTTP 401/403/404/429/500, redirects, timeouts, invalid JSON, oversized bodies, SSRF/host/path injection, global/EU namespace isolation, salary intervals and invalid bounds, publication evidence, remote semantics, local pagination, multiple boards, later-board failure and adapter reuse. Existing packet creation/review/idempotency suites are included in the focused run. No test submission is described as a real application.

An initial fixture run had two incorrect assumptions: SQLAlchemy initializes a new versioned profile at version 1, and the job model has no notes column. Fixtures were corrected to establish version 7 through a real update and verify persisted human match score/explanation. Those failures were not hidden as passing checks.

Representative commands, using the primary repository's existing Python 3.11 environment without changing its dependencies. Set `PROFILE_TEST_DATABASE_URL` privately to the dedicated disposable local PostgreSQL fixture before running these commands; never place credentials in this report:

```sh
P22_TEST_POSTGRES_CONTAINER=codex-p22-pg17 \
/path/to/primary/backend/venv/bin/python -u backend/scripts/run_backend_ci.py \
  --output /tmp/automated-apply-codex-p22-evidence/full-backend --seconds 1200 \
  /path/to/primary/backend/venv/bin/python -u -m pytest backend/tests -q --durations=15 \
  -o faulthandler_timeout=60 \
  --junitxml=/tmp/automated-apply-codex-p22-evidence/full-backend/pytest.xml

/path/to/primary/backend/venv/bin/python backend/scripts/benchmark_discovery.py --source ashby
```

The 1,200-second bound supervises the full test process tree; it does not change application timeouts. Detailed logs stay outside Git under `/tmp/automated-apply-codex-p22-evidence`.

## Fictional batch timings

End-to-end local runs include profile loading, one mocked public feed GET, normalization, ingestion, matching, durable run status and commit. Each uses the real PostgreSQL driver and a single pooled connection. These are individual measurements on the M1 machine, not throughput guarantees or live API measurements.

| Selected jobs | Lever fixture | Ashby fixture |
| --- | ---: | ---: |
| 3 | 0.0605 s | 0.0566 s |
| 27 | 0.2008 s | 0.1968 s |
| 100 | 1.2919 s | 0.9046 s |

The largest fixture bodies were 44,901 decoded bytes for Lever and 64,527 for Ashby; JSON decoding was below 1 ms in both measurements. Full adapter handling, including normalization, took 13.804 ms and 12.187 ms respectively. Ingestion dominated these local runs. The final measurements were refreshed sequentially after the full suite finished. Genuine live results from this branch: **zero board requests, zero real listings and zero real application packets**, as requested. Earlier verified three-listing online batches remain historical evidence only. Larger online batches and end-to-end live matching remain unverified.

## Changed files and publication status

- `backend/.env.example`, `backend/app/core/config.py`: empty allowlists and fixed Lever region.
- `backend/app/services/job_sources/{public_ats.py,direct_api.py,factory.py,registry.py}`: two adapters through the shared bounded transport, registry and factory; bounded diagnostics.
- `backend/app/services/startup_discovery/{source_registry.py,connectivity.py}`: free-source metadata, source pacing and configuration-aware connectivity fingerprints.
- `backend/app/repositories/job.py`, `backend/app/services/{job_deduplication.py,job_ingestion.py,job_discovery_service.py}`: fewer redundant reads, bounded matching and durable recovery evidence.
- `backend/scripts/benchmark_discovery.py`, `backend/tests/test_public_ats.py`, `backend/tests/test_public_ats_postgres.py`: fictional measurement and regression tools.
- This Codex-specific report.

No migration or typed API schema changed. Frontend files, AGY documentation, AGENTS.md and all three workflow files are outside the diff. Hosted CI was not dispatched, and no merge or deployment was performed.

The new sources are available through the registry, owner-triggered discovery API and existing job-led startup discovery service. Legacy natural-language planner, pilot CLI and scheduled-automation source allowlists were not expanded; configuring a board does not start scheduled collection.

PR #34 subsequently merged with explicit owner approval as `1ad14a4d37cbef59548df2b6ec75c9495719b61f`. This branch was rebased onto that exact main commit. Publication requires the final local checks before pushing and opening one scoped backend PR. Live employer-board approval remains a separate future decision; current verification is fictional-only.

## Production integration preparation follow-up

The fresh review found PR #34 open and mergeable at `e08b7f0`, with no unresolved review threads. After explicit owner authorization, #34 merged with a merge commit. Fetched main `1ad14a4` contains `e08b7f0`, PR #33's `582f0dd` and Gemini's `695df6a`; its tree is identical to the reviewed integration head. PR #33 was then confirmed closed, with no unique branch changes remaining outside main. The workflows remain byte-identical to `3a2d6b3`'s manual-only policy. The rebase onto actual main completed without conflicts; the rebased implementation is `4686d8b`.

AGY's `feat/p22-agy-job-source-ui` at `36c811d` changes only its Jobs component, tests and report. There are no shared changed files. Its source filter accepts the existing `sources` array with string `id` and `display_name`; Lever and Ashby supply both, retain `live_verified=false`, and default to `configuration_required`. The saved-job filter does not imply live readiness. Canonical OpenAPI remains identical to the Phase 2.1 integrated checkout.

The fresh focused provider/security/application run passed **276 tests with zero failures or skips**, including the PostgreSQL 17.11 restart, concurrency and one-connection cases. Ruff, full-app Bandit, compilation and the tracked-private-artifact guard passed. Full-suite results and exact tested SHA belong in the private final manifest and delivery report.

The native secret hook exposed two publication-check regressions: the credential-shaped documentation placeholder was detected, and inserting settings above a reviewed example shifted an existing baseline line reference. The commands now reference a privately supplied fixture environment variable, and the empty ATS settings are appended to the example file. The native hook passed after correction. No secret baseline, detector policy, production behavior or frontend file was changed. The two provisional full-suite attempts stopped for the publication-check fix and actual-main rebase are not counted as passing runs.

Owner-approved live employer boards and online PostgreSQL remain prerequisites for external acceptance. The earlier 27-listing timeout is still undiagnosed; no fixture result establishes its resolution. Suitable real discovery-to-packet acceptance and delivered Telegram acceptance also remain outstanding. No provider activation, paid request, hosted CI, deployment, application sending or messaging is part of this preparation.
