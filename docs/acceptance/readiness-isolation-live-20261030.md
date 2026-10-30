# Approved readiness-isolation release: live acceptance in progress

Branch `fix/live-prepare-discovery-20261030`, base `main`; [PR 48](https://github.com/karanagg166/automated-apply/pull/48).
Exact owner-approved installed source:
[`5ca05d844fbaa7ca0ada093aa37556c831c89edf`](https://github.com/karanagg166/automated-apply/commit/5ca05d844fbaa7ca0ada093aa37556c831c89edf).
The owner replied “yes approved” to the pending question naming this exact SHA
and read-only reliability/Chrome acceptance. This does not authorize real field
filling, employer submissions, email sends, a merge or cleanup.

The [previous real cycle and nine readiness 503s](chrome-live.md) remain retained
as failures of `48e6c3a…`. The [replacement investigation](reliability.md#follow-up-native-workload-failure-and-replacement-candidate)
explains why one bounded API-only readiness slot is isolated from business
transactions. General pools and the database role/server limits are unchanged.

## Installation evidence

On 2026-10-30, the approval receipt and a new hash-verified 12-file rollback
backup were recorded at 10:55:57 UTC. All old immutable releases and private
data/configuration remain in place. A new detached release was built at the
approved SHA with its own venv and dependency/build directories. Constrained pip
install, `pip check`, pnpm 12.15.0 frozen install, frontend build and extension
build all passed. The full restricted-role/TLS/catalog preflight passed before
cutover; tracked release source is clean. No schema migration was performed.

The old API, execution, Telegram and frontend were stopped before replacements
started. Their existing LaunchAgent definitions and the stable native wrapper
were changed to the approved source. API readiness passed in **3.635s** before
the other services started, and frontend startup passed. The native manifest
and allowed extension origin were preserved.

The existing Profile 8 extension remains at its old `b069092…/extension/dist`
directory. All **17** installed files match the approved build byte-for-byte,
with identical ID/key/permission declarations. No extension reinstall, Chrome
preference edit, profile switch or permission prompt was required. The initial
backend observation reported the selected profile **CONNECTED**, with command
channel enabled and a fresh heartbeat. This is transport evidence, not a DOM
acceptance result.

| Initial check | Status | Actual evidence / scope |
| --- | --- | --- |
| Exact owner approval, release identity and rollback | PASS | Approval tied to full SHA, clean tracked source and hash-verified definitions/configuration backup |
| Dependency and frontend/extension builds | PASS | Completed local release builds; `pip check` reports no broken requirements |
| Full DB preflight / startup audit | PASS | Restricted runtime, pinned target, TLS and catalog verified |
| Nine initial HTTP checks | PASS | Health, three readiness checks, profile status, paused task, automation status, mailbox metadata and plan metadata all 200 |
| Warm readiness checks | PASS for these samples | 1.277s, 1.097s, 1.144s |
| Selected Profile 8 / old terminal commands | PASS | Existing binding and historical terminal command values retained |
| Installed framed native transport | PASS | Actual wrapper process, response request ID reconciled |
| Readiness stability under real native workload | NOT TESTED to completion | HTTP-only monitor and first real cycle started; no final PASS yet |
| Three cycles / restart / crash / locked DOM | NOT TESTED to completion | Subsequent acceptance pending |
| Real filling / employer application / email sending | NOT TESTED / not authorized here | No such action performed by installation |

Other initial durations: health 0.021s; profile status 2.094s; paused task 0.950s;
automation status 5.068s; mailbox metadata 1.258s; plans 1.263s. No mailbox body
was fetched by these checks. Full response bodies remain private.

## Validation and current acceptance plan

The approved source's fixture evidence remains **345 backend tests passed in
37.21s**, **7 disposable PostgreSQL tests passed in 2.44s**, and isolated Ruff
E9/F/I plus diff checks passed. Those runs are documented in the replacement
report and are not relabeled as new installed tests.

The native workload monitor is HTTP-only because the three service pools plus
one readiness pool consume four of the five role slots. One acceptance helper
may use the fifth. An independent DB observer must not run at the same time.
The monitor records status/timing and process CPU/RSS only; it does not read
page content, Gmail bodies, native secrets or credentials.

Continue with three real read-only Open → Prepare cycles, a backend/worker
restart, unexpected worker-crash recovery, concurrent Stop fencing and an awake,
manually screen-locked DOM cycle. Reconcile original request IDs, task revisions,
exact tab/window/session binding and packet/plan identities. Retain all failures
and unknown outcomes. Do not mark workload or complete automation PASS from the
initial checks above.

## Reproduction and private evidence

```sh
release="$HOME/Library/Application Support/Automated Apply/releases/5ca05d844fbaa7ca0ada093aa37556c831c89edf"
git -C "$release" rev-parse HEAD
git -C "$release" status --porcelain --untracked-files=no
# HTTP-only monitoring alongside a single approved native acceptance helper.
"$release/.venv/bin/python" "$release/backend/scripts/measure_reliability.py" \
  --env-file "$HOME/Library/Application Support/Automated Apply/phase54.private.env" \
  --output /tmp/automated-apply-probe-isolation-new.jsonl \
  --samples 120 --interval-seconds 5
```

Use a new output filename. Do not start another monitor while the current one
is running. The private upgrade directory is
`reliability-probe-upgrade-20261030T105557Z`. It retains approval, backup manifest,
build/preflight, cutover, initial HTTP/native/history verification and new native
cycle/monitor receipts. Only sanitized summaries are published. No hosted CI,
merge, credential rotation, cleanup or production DB fault injection occurred.
