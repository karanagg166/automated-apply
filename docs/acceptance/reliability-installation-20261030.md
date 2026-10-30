# Approved reliability installation: initial verification

Branch: `fix/live-prepare-discovery-20261030`; PR
[48](https://github.com/karanagg166/automated-apply/pull/48), base `main`.
Exact approved and installed Python/native/frontend source:
[`48e6c3a2ba7a0283a2e07e79ab2c59ecddd45a14`](https://github.com/karanagg166/automated-apply/commit/48e6c3a2ba7a0283a2e07e79ab2c59ecddd45a14).
The [investigation and fixture evidence](reliability.md) remains the pre-installation
baseline; this report records the newly authorized real installation.

## Approval, preservation and build

The owner approved this exact SHA and read-only reliability/Chrome acceptance.
The private approval receipt and a hash-verified 12-file backup were created at
2026-10-30 10:12:37 UTC. They preserve the four LaunchAgents, native wrapper and
manifest, frontend launcher, external environment files and Profile 8 metadata.
Credentials and account generations were not changed. All older immutable
releases, including the previous Telegram source, remain in place for rollback.

A detached release worktree was built at its permanent SHA-specific location.
Its own venv uses the constrained requirements; dependency install and `pip check`
passed. pnpm 12.15.0 frozen install, frontend build and extension build passed.
No mutable dependency directory was shared with another release. The full
restricted-role/TLS/catalog preflight passed before cutover. Tracked release
source is clean. There is no schema migration or connection-limit increase.

## Actual Mac cutover and initial observations

Cutover ran **10:15:31–10:16:22 UTC**. Old execution, Telegram, frontend and API
processes were stopped and their exit verified before replacement. Existing
definitions were updated at their original paths; the API started first, followed
by frontend, execution and Telegram. No second Telegram poller was admitted.
The native manifest retained its stable wrapper path and allowed extension origin.

| Item | Status | Evidence / limit |
| --- | --- | --- |
| Owner exact-SHA approval | PASS | Explicit owner reply and private approval receipt |
| Source and rollback preservation | PASS | Clean tracked release; prior releases and hashed backup retained |
| API, execution, Telegram, frontend definitions | PASS | All reference the approved SHA; one LaunchAgent run and process each at initial check |
| Native wrapper smoke check | PASS | Actual framed local wrapper process, request ID reconciled; not a Chrome DOM cycle |
| Startup audit and initial readiness | PASS | Cutover readiness 200 in 1.962s; three subsequent 200s in 1.043, 1.039, 1.101s |
| Initial nine HTTP checks | PASS | Health, 3 readiness, profile status, paused task, automation status, mailbox metadata, saved plans all 200 |
| Stored selection / old terminal commands | PASS | Independent DB comparison retained selection and historical terminal values |
| Duplicate execution/Telegram start guard | PASS | Both real duplicate invocations rejected before DB engine initialization; existing services retained |
| Chrome extension location | BLOCKED — owner UI action pending | Profile 8 still records previous release directory at this milestone; owner asked to load approved directory |
| Extension ID and declared permissions | PASS for build comparison | Same key/permission declarations; 17 built files byte-identical to old installed extension |
| Sustained fixed-release production reliability | NOT TESTED to completion | Forty-sample bounded monitor running; no final PASS yet |
| Three Chrome cycles / restart / locked-screen DOM | NOT TESTED | Awaiting extension location verification and actual cycles |
| Real filling / employer submission / email send | NOT TESTED / not authorized here | No such action performed by installation |

The initial health request took 0.035s. Other initial HTTP durations were 2.196s
for profile status, 1.250s for the paused acceptance task, 5.923s for automation
status, 2.419s for mailbox metadata, and 1.474s for saved plans. Their response
bodies remain private; no Gmail contents were fetched by this verification.

Two early fixed-release monitor samples saw **4 connections including the one
observer**, compared with 5 including an observer in every final pre-fix sample.
This is an initial measured reduction of one slot, consistent with removal of
Telegram's dedicated database lease. It is not yet proof of stability under real
native preparation workload. Sustained timing and resource trends will be
published when the bounded monitor completes.

## Validation scope and reproduction

No new source was introduced after exact-SHA approval. Existing local evidence
remains **342 backend regressions passed**, **5 real disposable PostgreSQL tests
passed**; those fixtures are not relabeled as installed acceptance. New live
evidence here is the cutover, nine initial HTTP checks, framed native transport,
stored-history comparison and the two rejected duplicate process invocations.

```sh
release="$HOME/Library/Application Support/Automated Apply/releases/48e6c3a2ba7a0283a2e07e79ab2c59ecddd45a14"
git -C "$release" rev-parse HEAD
git -C "$release" status --porcelain --untracked-files=no
launchctl print "gui/$(id -u)/com.automated-apply.api"
launchctl print "gui/$(id -u)/com.automated-apply.execution"
launchctl print "gui/$(id -u)/com.automated-apply.telegram"
"$release/.venv/bin/python" "$release/backend/scripts/measure_reliability.py" \
  --env-file "$HOME/Library/Application Support/Automated Apply/phase54.private.env" \
  --output /tmp/automated-apply-fixed-new.jsonl \
  --samples 40 --interval-seconds 15 --database
```

Do not start another observer while the current one runs. Raw launchd output,
private configuration and receipts stay local; publish only sanitized summaries.
The upgrade evidence directory is named
`reliability-upgrade-20261030T101237Z` in the private application-support root.
Its `cutover`, `verify-installed`, `native-health-installed` and `duplicate-guards`
receipts contain the exact local evidence. No cleanup was performed.

## Next actions

Verify the approved extension directory in Profile 8 through Chrome's protected
controls, complete the monitor and real Open → Prepare cycles, then test recovery
and awake/locked DOM completion. Preserve every failed or unknown attempt. Continue
to report fixed-release acceptance as pending until those checks actually finish.
Discovery expansion remains behind the reliability gate. No merge or hosted CI
was performed.
