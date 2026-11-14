# Canonical source and owner-authorized storage cleanup

Branch: `feat/rust-agent-runtime`, [PR #50](https://github.com/karanagg166/automated-apply/pull/50).
Rust implementation: [`c7c73e3`](https://github.com/karanagg166/automated-apply/commit/c7c73e37930284a4e78c9856fee6e7f22ad56e1b).
The owner requested all code in the canonical project directory and removal of unused old
versions and duplicate Library storage. This supersedes the earlier blanket retention of
historical release directories. **The full Rust migration remains in progress.**

Development now uses `/Users/karanagg/Desktop/Projects/automated-apply`. The existing Rust
history was fast-forwarded locally through a temporary integration branch; the old primary
branch remains preserved. No duplicate clone was created. Current support/configuration/data
storage was renamed on the same filesystem into the ignored `.local/runtime-support/`.
The old Library entry is a compatibility symlink, not a second copy. Existing configured
paths, including the installed extension path, still require that link until runtime cutover.
Do not clear `.local/`: it contains current credentials, application data and configured
components. Nothing under it is published.

| Check | Result | Evidence |
| --- | --- | --- |
| Old Rust build removal | PASS | Cargo removed 116,127 regenerable files, reporting22.3GiB |
| Retired source/release directory cleanup | PASS | 111 unique directories removed:95 old linked worktrees plus16 standalone obsolete build snapshots |
| Unique source preservation | PASS | Existing Git history/branch/archive refs retained; six local preservation commits capture historical uncommitted source/policy edits; those archival commits were not pushed |
| Unique private-file preservation | PASS | 1,462 file records reduce to288 unique SHA-256-verified blobs, totaling9,701,899bytes in ignored owner-only storage; actual private names/content/hashes are not published |
| Ordinary Git removal | PASS | No force/reset/stash drop; four attempts left immutable-file remnants after removing Git administration; exact source/private bytes reverified before clearing only retired UF_IMMUTABLE flags and removing remnants |
| Current component and configuration integrity | PASS | 35 critical files byte-identical, seven retained worktree HEADs identical, Git worktree repair passed after storage relocation |
| Current runtime references | PASS | Six configured release directories protected from deletion; seven retained worktrees reside inside the canonical root; Library entry is a symlink to canonical storage |
| No duplicate future development path | PASS | Cargo metadata reports canonical workspace and canonical target directory; policy forbids new Library source/build trees; dev/test profiles disable debug information and incremental state |
| Canonical Rust rebuild | PASS | 114 standard tests passed,94 dedicated PostgreSQL cases intentionally skipped by this command; cold test-profile compile1m20s; fresh target925MiB versus the removed accumulated22.3GiB target, not a like-for-like benchmark |
| Canonical native PostgreSQL / shared build reuse | PASS | All94 dedicated cases passed in28.08s; harness workspace selection reused the ordinary test artifact in0.49s rather than compiling another package-feature variant; total208 distinct Rust tests passed |
| Live runtime/application/focus acceptance | NOT TESTED | No service restart, browser action, application attempt or message send during cleanup; four project LaunchAgents were unregistered and their files disabled at preflight |
| Hosted Actions / merge | NOT TESTED | No dispatch or remote merge |
| Whole-project Rust completion | NOT TESTED | Remaining service/API/tool ports and installed/live acceptance are still required |

The initial plan listed24 release snapshots that were also registered worktrees within
the95. Those are overlapping entries, not24 additional removals. The first pass removed91
directories and retained four immutable remnants. The final pass resolved those four and
removed16 additional unregistered snapshots. Final unresolved cleanup failures: **zero**.
The [sanitized exact removal inventory](storage-cleanup-20261115.json) records all111 paths
relative to the old support directory and their preserved source SHAs.

Before cleanup, `du` reported17GiB in historical releases,21GiB in release candidates
(including retained current components), and5.8GiB in archived worktrees, in addition to
the old Rust target. These directory totals are logical accounting, not guaranteed physical
reclamation: APFS sharing and other concurrent laptop activity affect free-space changes.
The disk's available space increased from approximately34GiB at preflight to96GiB after
cleanup; do not attribute every byte of that global change exclusively to this operation.
The retained support directory measures8.2GiB; the unique private preservation store10MiB;
the shared Git directory31MiB. Git history replaces large checked-out old versions.

Recheck from the canonical directory without starting services:

```sh
git worktree list
cargo metadata --locked --no-deps --format-version 1
cargo fmt --all --check
git diff --check
du -sh .local/runtime-support .local/preserved-data .git
df -h .
```

Source/package caches and current runtime environments are distinct: current referenced
components were moved intact, never merged or edited as development trees. The minimal
Library compatibility link remains useful while their configured paths are retained.
