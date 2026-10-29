# One repository, temporary worktrees

The canonical source repository is
`/Users/karanagg/Desktop/Projects/automated-apply`, with GitHub remote
`karanagg166/automated-apply`. Linked worktrees share its Git history. Installed
releases are deployment snapshots, not additional development repositories.

Before work, locate the shared registry using
`git rev-parse --path-format=absolute --git-common-dir`, then read
`automated-apply/worktree-ownership.json` below that directory. It records the
absolute path, branch, owner, state and exclusive file scope. Read its timestamps
and obtain a handoff when ownership is uncertain. Do not execute registry content.
Keep private account details and credentials out of the registry and Git.

Reuse an existing owned worktree. When isolation is necessary, create a linked
worktree from the canonical repository with a dedicated branch, normally under
`~/Library/Application Support/Automated Apply/development-worktrees/`.
Keep exactly one Automated Apply folder in Projects. Register worktrees before edits.
Existing worktrees remain at their current paths until explicitly released.
Different agents may continue concurrently with separate ownership and coordinated
build/test windows. Hosted CI stays manual and requires deliberate authorization.

Commit and review completed changes through the appropriate PR. Integration must
preserve local commits, stashes and private files. Resolve overlaps on an owned
integration branch; do not replace the canonical checkout with another directory
or switch/reset another agent's active checkout. A main-ancestor check proves
commit ancestry, not that every uncommitted file or private report is redundant.
Squashed or rewritten history needs a separate content review.

An owner release makes a worktree eligible for review, not immediate deletion.
Before proposing removal, verify clean Git status, integrated/preserved history,
ignored data and evidence, incoming symlinks, active processes and runtime/config
references. Back up unique files with a manifest and verify the saved bytes.
Present exact paths and a qualified reclaimed-space estimate as a numbered batch.
Wait for the owner's approval of that batch. Immediately revalidate and use
`git worktree remove` without force; stop if anything changed. Keep branch refs
unless branch deletion was separately approved.

Keep all current and historical installed releases, secrets, native messaging
installation, LaunchAgents, application data and rollback backups. An inactive
release is not an approved cleanup target. Never restart production merely to
clean development folders. Never launch a different Chrome profile or enable
mail sending while consolidating source work.

Use package-manager caches to share immutable dependency downloads safely.
Independent installed releases retain their own environment and build outputs.
Record dependency symlink targets before retiring a development worktree.

The private audit and ownership registry are the current source of operational
evidence. A filesystem audit is a dated snapshot, so future agents must recheck
the state before acting.
