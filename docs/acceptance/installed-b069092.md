# Installed release handoff: partial acceptance

Recorded 2026-10-30. Branch: `fix/live-prepare-discovery-20261030`.
Installed implementation: [`b06909293b1866e8191277d17fc284c398b4307b`](https://github.com/karanagg166/automated-apply/commit/b06909293b1866e8191277d17fc284c398b4307b).
Base: `main` at `f745068cbfac7e6c052429745a613ebd9ad8844e`.
This is a sanitized publication of the existing private upgrade report, not a new
claim of complete live acceptance. See [implementation details](../live-automation-acceptance.md).

## Identity and preservation

The clean canonical checkout and clean tracked source of the installed immutable
release both resolve to the implementation SHA above. Current API and execution
process arguments and API, execution and frontend LaunchAgent working directories
reference that release. Extension source version is 1.3.2. The upgrade receipt
records native-host and selected Chrome Profile 8 installation with the existing
extension ID and binding preserved. This handoff did not independently re-exercise
the native host or inspect Chrome's live extension UI. Telegram still runs its
prior release, `4bf2503076380c74a88d0d9c34bd913bcbb8177c`.

All rollback material and historical releases are preserved. No schema migration,
credential change, new installation, service restart, employer submission or
hosted workflow was performed for this publication. The owner confirmed there
is no AGY agent running. Other uncertain historical checkouts remain preserved.

## Implementation summary

- Shorter owner-lock occupancy during read-only preparation checkpoints.
- Command leases and expiry retained through native operations.
- Read-only zero-field inspections persist as `NEEDS_INPUT`.
- Native retry handling distinguishes explicit transaction rollback from unknown
  outcomes; fill authorization and receipts are excluded from these retries.
- A smaller live readiness probe retains the complete startup security audit.
- Approved-account Gmail intake adds bounded incremental reads, durable cursors,
  deduplication, provenance, Stop fences and dashboard controls.

## Actual installed acceptance from the retained upgrade record

| Capability | Status | Evidence and limit |
| --- | --- | --- |
| Five approved components installed at exact SHA | PASS | Upgrade receipt; current API/worker/frontend definitions and release source independently rechecked |
| Real Open → Prepare | PASS, 2 cycles | Distinct persisted read-only `NEEDS_INPUT` plans, zero fields/actions/approved fields |
| Restart recovery | PASS for observed cycle | Full second cycle passed after approved restart; initial pre-admission status request failed |
| Pause/Start/Stop fencing | PASS for exercised cases | Queued Prepare cancelled; historical terminal commands unchanged; older paused tasks remained paused |
| Readiness reliability | FAIL | Independent monitor retained HTTP 503 on 3/5 probes; profile-status reads also failed |
| PostgreSQL connection budget | FAIL | Acceptance helper rejected before command admission at the runtime role's five-connection limit while an independent observer ran |
| Locked-Mac DOM task | NOT TESTED | Three samples were locked before/after, but no complete native cycle; owner previously deferred it |
| Approved recurring Gmail intake | PASS for empty source only | Post-restart approved-account poll persisted its cursor; zero messages/candidates and no source error |
| New discovered job / preparation | BLOCKED | No eligible source data in that poll |
| Autofill | NOT TESTED | No specific field authorization or fill |
| Employer submission / independent receipt | BLOCKED | No authorized supported mechanism established; no submission claimed |
| Frontend deployment checks | PASS | Existing build/login/private-route checks; private settings preserved |

## Failure and timing evidence

The retained private report is `live-upgrade-20261030T084759Z/FINAL-STATUS.md`
under the local application-support directory. Its timestamp is
2026-10-30T09:14:41Z. Sanitized observations:

```text
readiness.monitor: HTTP 503, 3 failures / 5 samples
readiness.final.isolated: HTTP 200, 3 / 3; 1.617s, 1.161s, 1.184s
profile_status.transaction: SQLSTATE 55P03 (lock timeout)
acceptance.pre_admission: runtime role connection limit = 5
runtime.pool: size = 1; max_overflow = 0 (per process)
locked.monitor: 3 samples; readiness success = 1 / 3; DOM cycle absent
employer_writes: 0; new_fill_authorizations: 0
```

Monitoring and acceptance were subsequently separated. Rolled-back status GETs
were retried by the helper in limited cases; that does not prove every product
caller recovers. One unlocked precondition and one connection-limit failure are
retained as failed attempts, not successful cycles. State comparisons around
Start/Pause/Stop were non-atomic and one differed while revisions changed.

Private evidence includes cycle, restart, controls, monitor, final database audit,
extension and frontend receipts. Raw account data, job identities, tokens, native
binding IDs, screenshots and raw logs are intentionally absent here.

## Validation and reproduction

Publication checks: clean source identities, installed process/LaunchAgent paths,
manual-only triggers in all three workflows, and `git diff --check` passed.
No new unit suite was run for this documentation handoff. Prior fixture tests
are not relabeled as new runtime validation; their exact counts were not in the
final private status report and are therefore not invented here.

```sh
git rev-parse HEAD
git show --stat b06909293b1866e8191277d17fc284c398b4307b
git diff --check f745068cbfac7e6c052429745a613ebd9ad8844e..b06909293b1866e8191277d17fc284c398b4307b
curl --max-time 10 -sS -o /dev/null -w '%{http_code} %{time_total}\n' http://127.0.0.1:8000/health
curl --max-time 10 -sS -o /dev/null -w '%{http_code} %{time_total}\n' http://127.0.0.1:8000/ready
```

Use the configured local API port if different. Production load and destructive
database fault injection are not part of these commands.

## Next actions and release gate

Investigate actual runtime sessions, lock waits, process count, readiness and
resource usage first. Publish measured before/after results and targeted
regressions for the smallest reliability fix. Production remains **FAIL for
reliability** until an exact-SHA-reviewed replacement is explicitly approved,
installed and tested. Then repeat three real cycles including restart and
awake/locked DOM completion. Discovery expansion waits for that reliability gate.

The feature PR links this report and the installed implementation commit.
