# Reliability investigation and candidate: production acceptance pending

Recorded 2026-10-30. Branch: `fix/live-prepare-discovery-20261030`; PR:
[48](https://github.com/karanagg166/automated-apply/pull/48), base `main` at
`f745068cbfac7e6c052429745a613ebd9ad8844e`.

Exact implementation candidate:
[`48e6c3a2ba7a0283a2e07e79ab2c59ecddd45a14`](https://github.com/karanagg166/automated-apply/commit/48e6c3a2ba7a0283a2e07e79ab2c59ecddd45a14).
Installed API/execution/frontend source remains
[`b06909293b1866e8191277d17fc284c398b4307b`](https://github.com/karanagg166/automated-apply/commit/b06909293b1866e8191277d17fc284c398b4307b).
Telegram remains on `4bf2503076380c74a88d0d9c34bd913bcbb8177c`.

**Production reliability remains FAIL.** The candidate has passed local regression
and disposable PostgreSQL checks, but has not been installed or accepted on the
live accounts. Exact-SHA review and owner installation approval are required.
No merge, production installation/restart, migration, connection-limit increase,
browser command, autofill, employer submission, email send or hosted CI job was
performed by this investigation. Existing services continued their existing work.

## Stage 0 publication

The previously unavailable installed commit is now on the feature branch. Its
[sanitized installed acceptance report](installed-b069092.md) was published in
[`5ac189c62f2216415ee6c8883dc8090b160fe2f3`](https://github.com/karanagg166/automated-apply/commit/5ac189c62f2216415ee6c8883dc8090b160fe2f3).
Two real Open → Prepare cycles and the observed restart recovery remain historical
PASS evidence; locked-Mac DOM completion remains untested. They are not counted
as acceptance of this new candidate.

## Measurements from the actual Mac and database

The runtime connects directly to PostgreSQL on port 5432, using TLS and the
restricted runtime role. It is not using a Supabase transaction pooler. Read-only
inspection found role connection limit **5**, server `max_connections` **60**,
`lock_timeout` **2s**, `statement_timeout` **30s**, and idle transaction timeout
**30s**. All runtime application pools were size **1**, overflow **0**, with
pre-ping, 300-second recycling and a 30-second pool wait. No limit was changed.

| Live window, UTC | Health | Ready | Profile status | Timing |
| --- | --- | --- | --- | --- |
| Initial 24 samples, starting 09:34:49 | 23 HTTP 200; 1 transport ReadError | 19 HTTP 200; 5 HTTP 503 | Wrong observer route: 24 HTTP 404 | Ready median 2.2895s, max 6.499s |
| Correct status route, 18 samples, starting 09:35:46 | 18/18 HTTP 200 | 16 HTTP 200; 2 HTTP 503 | 18/18 HTTP 200 | Ready max 5.019s; profile median 4.7985s, max 9.094s |
| Reproducible monitor, 12 samples, 09:47:29–09:48:25 | 12/12 HTTP 200 | 12/12 HTTP 200 | 11 HTTP 200; 1 HTTP 503 | Health mean/max 0.0304/0.0785s; ready 2.2073/4.6494s; profile 3.8116/5.6524s |
| Fixed release, live after installation | NOT TESTED | NOT TESTED | NOT TESTED | Installation approval required |

The first two windows overlap and must not be summed as independent trials. The
incorrect route is retained as an observer mistake. The second observer's DB
connection was rejected while the first observer was still connected; its HTTP
observations continued without opening a new DB session. Later monitoring used
only one observer. These setup failures are not hidden or relabeled as PASS.

In the final live window every database sample showed **5/5** runtime slots used,
including the one observer connection. A dedicated Telegram advisory-lock session
accounted for one persistent slot in addition to its ordinary session pool. Normal
API + execution + Telegram pools plus that lease use four slots; a diagnostic
observer consumes the fifth, leaving no room for an acceptance helper. An earlier
sample captured a real blocked transaction waiting on another runtime session.
The final window's maximum observed transaction age was 1.742335s; its post-HTTP
DB snapshots missed lock waits and therefore do not prove an absence of waits.

| Process, final 12-sample window | Count range | Maximum observed CPU | RSS range, KiB |
| --- | --- | --- | --- |
| API | 1–1 | 5.0% | 29,696–43,584 |
| Execution | 1–1 | 2.1% | 4,336–31,408 |
| Telegram | 1–1 | 6.3% | 3,584–40,704 |
| Frontend server | 1–1 | 0.0% | 2,192–2,224 |

These are sampled `ps` CPU/RSS observations, not physical-footprint limits or a
long-term leak test. The 8 GiB Mac also had 7,825.19 MiB swap used in an earlier
system snapshot. Later `memory_pressure -Q` reported 30% free. Host memory
pressure is material but these observations do not establish it as the cause of
an individual 503, or attribute the pressure to this application.

At the initial LaunchAgent check, API and execution each had one process and one
run since their approved cutover. Telegram recorded **56 runs**, then **57** at a
later check, with last exit code 1. Retained stack frames identified the exit in
`run_worker → questions.deliver_one → store.memory_row` on SQLSTATE `55P03`.
This is a restart loop, not evidence of simultaneous Telegram workers.

After the owner's pause/resume, a read-only recheck found the Mac had rebooted at
2026-10-30 10:04:01 UTC. The existing LaunchAgents were running again at the same
installed source versions, one process per service. This supports the observed
launch-at-login recovery only. No new DOM cycle, Telegram delivery, locked-screen
execution or independent task reconciliation was demonstrated by that observation.

## Root causes and limits of attribution

1. **Role connection exhaustion, confirmed.** The role cap is five, despite a
   server cap of 60. Per-process pools do not constitute a shared budget. The
   extra permanent Telegram lease and overlapping diagnostic/acceptance processes
   explain the observed `TooManyConnectionsError` without assuming a session leak.
2. **Owner-row contention, confirmed.** Profile status acquired the global owner
   lock before its read/reconciliation work. Recurring ticks, execution and
   campaign claims, legacy Gmail source polls, watch checks and empty Telegram
   question polling also took this lock while idle. On the remote database the
   lock survives all subsequent transaction round trips. The 2-second lock
   timeout produces explicit transaction aborts on competing requests.
3. **Telegram crash/restart amplification, confirmed.** Database failures in the
   question-delivery path escaped the Telegram loop, whose handler only caught
   Telegram transport errors. KeepAlive restarted the worker, causing another
   startup catalog audit, database connection and Telegram verification.
4. **Readiness starvation, supported but not individually proven for every 503.**
   The five-second readiness deadline includes waiting for the API's single pool
   slot, DNS, connection/pre-ping, the query and connection cleanup. A status
   request holding that slot behind the owner lock can consume this deadline.
   The old readiness logger discarded exception categories; it is impossible to
   assign an exact individual cause to every historical readiness 503 from those
   logs. No claim that all historical 503s have been explained is made.

There is no observed API/execution duplication in these windows. Existing session
contexts close/rollback normally; the sampled results do not prove or disprove a
slow leak outside these windows. Reviewed Gmail guards commit before their HTTP
reads. Full startup security/catalog audits and standalone operator context audits
remain in place. Heavy preparation and other active command paths still need
representative installed load acceptance; fixture success does not establish their
steady-state latency.

## Candidate changes

- Idle status, claim, watch, source and question reads avoid the global lock.
  Real mutations reacquire it and re-read current state, revision, configuration,
  cadence and leases before acting. Profile expiry still distinguishes queued
  expiry from leased/executing `outcome_unknown`.
- Worker heartbeats commit in their own short transaction before owner-lock work.
  This also avoids reversing the lock order used by Gmail guards that update
  the health row while holding the owner lock.
- A same-user kernel file lease prevents duplicate execution/Telegram processes
  across linked worktrees and immutable releases on this Mac. Crashes release
  the descriptor; the lock file is never unlinked. Telegram no longer requires a
  separate permanent database connection for its singleton lease. This is a
  **single-host** process guard; database action fences remain authoritative. It
  is not a distributed-worker lease across several Macs.
- Telegram database failures back off without exiting or resetting an ambiguous
  delivery to pending. A database outage does not trigger another database write
  merely to store that outage. Raw asyncpg connection-limit errors are handled
  alongside SQLAlchemy errors. API connection-limit failures return 503 without
  a safe-replay header.
- Default pools become 1/0, matching the existing live configuration. Explicit
  configured values are respected. SQL sessions get fixed process labels, and
  sanitized failure codes distinguish pool timeout, probe timeout, lock timeout,
  connection limit and other fixed categories without logging SQL or secrets.
- [The bounded monitor](../../backend/scripts/measure_reliability.py) records only
  HTTP codes/timing, process counts/CPU/RSS and aggregate session metrics. It
  stores no response bodies or SQL text, refuses non-loopback API targets, does
  not follow redirects, and creates a new mode-0600 output file.

If all three Python services use this candidate with pools 1/0, their expected
steady-state pool budget becomes **3** rather than four, before observers or
temporary tools. This is a calculated budget, **not a measured production after
result**. Live concurrency and retained-connection behavior must still be tested.

## Before/after comparison and validation

The disposable PostgreSQL fixture held the owner row through a separate real
connection. Reproducing the previous unconditional lock entry failed with
SQLSTATE `55P03` after **0.2046s** at a deliberately configured **200ms** fixture
lock timeout. The candidate then completed **10 status + idle-claim cycles**, mean
**0.0095s/cycle**, while the owner row remained locked. This compares the old lock
entry with the candidate path; it is not a whole-release live old/new benchmark.

| Check | Result | Scope |
| --- | --- | --- |
| Focused backend regression suite | PASS — 342 tests, 39.64s | Fictional isolated SQLite/mocks plus actual local subprocess lease tests |
| Disposable PostgreSQL suite | PASS — 5 tests, 1.99s | Real local PostgreSQL 14.24; no candidate data or production fault injection |
| Owner contention / idle status and claim | PASS | Ten real-PostgreSQL cycles while another session holds the owner fence |
| Cancellation wins during status lock wait | PASS | Two pools; observed blocking; cancelled state/version preserved after re-read |
| Eight concurrent claims / restart / stale fence / Pause / unknown dispatch | PASS | Real PostgreSQL fixture; only one claim admitted; unknown submission not replayed |
| Real role connection-limit refusal and recovery | PASS | Disposable role cap 2; third refused, close then reconnect; cap unchanged |
| Readiness DB outage/recovery; health independent | PASS | Disposable role NOLOGIN/LOGIN; ready 200 → 503 → 200, health 200 |
| Duplicate process / crash release | PASS | Actual child processes for both service leases; no DB connection required |
| Isolated Ruff E9/F/I and diff checks | PASS | Changed Python files |
| New frontend/extension build | NOT TESTED | No frontend/extension contract or asset changes in this reliability commit |
| Fixed release sustained production health/readiness and resource leak checks | NOT TESTED | Installation approval required |
| Fixed release Chrome, restart and locked-Mac DOM cycles | NOT TESTED | Installation and real acceptance still required |
| Live employer fill/submission/independent receipt | BLOCKED | Separate specific authorization and supported channel required |

Local PostgreSQL was an existing Homebrew 14.24 binary, not the managed production
database or the repository's PostgreSQL 17 CI environment. Its cluster was
loopback-only, with 16 MiB shared buffers and 12 maximum connections. Test databases
and roles were disposable. The private cluster/log directory was retained; no
development worktree or historical release was deleted. The fixture process was
no longer running at the post-resume recheck. No hosted workflow was dispatched.

An intermediate suite had one expected-contract failure after moving heartbeat
publication to the worker boundary. The existing test was updated to exercise
that real worker boundary; the final 342-test suite passed. One attempted test
command named a nonexistent test file and collected no tests; it was corrected,
and is not counted as a passing run. An initial fixture startup command failed
because a path with spaces reached PostgreSQL's option parser; the corrected
loopback-only startup succeeded. All final results above come from completed runs.

## Reproduction

Use an existing development Python environment, not an installed release as
editable source. Run from the repository root:

```sh
.venv/bin/python -m pytest \
  backend/tests/test_reliability.py backend/tests/test_chrome_profiles.py \
  backend/tests/test_execution_naukri.py backend/tests/test_naukri_recurring.py \
  backend/tests/test_naukri_alert_email.py backend/tests/test_telegram_pairing.py \
  backend/tests/test_agent_execution.py backend/tests/test_live_prepare_recovery.py \
  backend/tests/test_local_gmail_discovery.py backend/tests/test_operational_health.py \
  backend/tests/test_config.py backend/tests/test_extension_tasks.py \
  backend/tests/test_packet_telegram_questions.py backend/tests/test_database_safety.py \
  backend/tests/test_phase1_installation.py -q

# PROFILE_TEST_DATABASE_URL must identify a disposable localhost database named
# candidate_profile_test with permission to create disposable databases/roles.
.venv/bin/python -m pytest backend/tests/test_reliability_postgres.py -q -s

# One observer at a time. --database consumes one runtime slot; do not run an
# acceptance helper concurrently against the current five-slot configuration.
.venv/bin/python backend/scripts/measure_reliability.py \
  --env-file "$HOME/Library/Application Support/Automated Apply/phase54.private.env" \
  --output /tmp/automated-apply-reliability-new.jsonl \
  --samples 12 --interval-seconds 5 --database
git diff --check
```

The monitor refuses to overwrite an existing output file. Its profile-status GET
can perform the product's existing command expiry reconciliation; it does not
admit new commands. Never point the disposable PostgreSQL tests at real data.

Sanitized numerical evidence is versioned in
[reliability-metrics-20261030.json](reliability-metrics-20261030.json).
Original logs and process/database snapshots remain in the private
`reliability-20261030` evidence directory. Only sanitized summaries are published.

## Required next actions

1. Review the exact candidate SHA linked above and authorize its production
   installation, including the Telegram service whose older code still exits on
   DB failures. Preserve immutable releases, rollback definitions, credentials,
   selected Profile 8, extension UUID/permissions and account generation.
2. After that approval, install/reconcile the exact source, verify startup audits,
   process/session labels, singleton rejection and bounded DB recovery. Repeat
   sustained monitoring under representative native-command workload; publish
   actual before/after connection counts, latencies and resource trends. Do not
   label production PASS until this completes.
3. Complete three real Open → Prepare cycles including restart and an awake,
   screen-locked DOM cycle. Reconcile request IDs, revisions, tab bindings,
   terminal commands and zero unsafe replays; keep unrelated Chrome tabs intact.
4. Only then expand discovery, matching/preparation and supported actions in the
   requested order. Keep the saved match threshold, unanswered-question fences,
   no automatic email sending and the unsupported Naukri submission boundary.

Design references: [SQLAlchemy async sessions](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
and [Supabase connection management](https://supabase.com/docs/guides/database/connection-management).
Neither reference is evidence of this application's production acceptance.
