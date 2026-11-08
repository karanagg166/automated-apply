# uv migration — 2026-11-08

Implementation revision: `e25f6cee516615bf1cb2ee2c407acaa06accd5e3`. Base: `78c291c7c554c696604429446ba1f25a02b62fcd`
on `fix/live-prepare-discovery-20261030`; this is a narrow stacked tooling change.

Docker and the three manual GitHub Actions workflows now install dependencies
through uv 0.13.7. The Docker distribution is pinned by digest and the setup action
by commit. Runtime/browser separation, existing requirements/constraints, security
audits, non-root startup and workflow dispatch policy are preserved. Active setup
and upgrade instructions use uv virtual environments. Extension prerequisite
messages use uv. Historical evidence of previous pip executions remains historical.

| Verification | Result | Scope |
| --- | --- | --- |
| Runtime Docker build | PASS | Existing pinned Python 3.11 base; uv installs unchanged runtime requirements |
| Dependency compatibility | PASS | 95 runtime packages; 100 with fixture test dependencies |
| Optional browser requirements | PASS | uv dry-run resolves unchanged browser requirements; no browser launched |
| Migration preflight fixtures | 13 passed, 1 skipped | Disposable container; PostgreSQL-specific case skipped without its dedicated database URL |
| Workflow YAML and installer ordering | PASS | uv setup precedes every installation; all three workflows remain manual-only |
| Extension prerequisite messages | PASS | JavaScript syntax checked through pnpm; no browser test executed |
| Requirement/lockfile and whitespace checks | PASS | No dependency specification or lockfile changes |

Prepared in a separately registered worktree. The primary checkout, existing
installed releases, private configuration, browser/profile, application services,
DB/storage and previous worktrees are unchanged. No hosted workflow was dispatched,
no provider inference ran, and this is not application/live-portal acceptance.
No installed application upgrade or source merge is claimed. Owner review remains
required before merge under this repository's workspace policy. The existing
application rollout and live-portal acceptance items remain open.
