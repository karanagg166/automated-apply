# Codex local validation — 2026-10-27

These are local results. Hosted CI was not dispatched or rerun. CI policy landed separately through PR #32; the full feature branch remains unmerged and uninstalled.

The isolated worktree is `/Users/karanagg/Desktop/Projects/automated-apply-codex-phase2`, branch `feat/phase2-codex-live-discovery`. It starts at baseline `975b8fc` and includes manual-policy main `3a2d6b3`. The final implementation commit and tested SHA are recorded in the PR and private final manifest. No private runtime configuration was copied into the repository.

## Environment and commands

Python 3.11 isolated dependencies were installed using:

```sh
python3.11 -m venv backend/venv
backend/venv/bin/python -m pip install -r backend/requirements.txt ruff bandit pyyaml detect-secrets pip-audit
backend/venv/bin/python -m pip install -r backend/requirements-browser.txt
```

Runtime requirements inherit `backend/requirements.lock`. PostgreSQL used the existing `postgres:17-alpine` image in a dedicated `codex-phase2-pg17` container, limited to 512 MiB and published only on `127.0.0.1:55432`. `PROFILE_TEST_DATABASE_URL` pointed only to its disposable `candidate_profile_test` database, with fictional credentials. Migration verifiers created and removed unique local databases. All ordinary HTTP tests enforce the existing outbound-transport denial fixture.

The full suite ran sequentially, without another Codex heavyweight suite:

```sh
PROFILE_TEST_DATABASE_URL="$PROFILE_TEST_DATABASE_URL" backend/venv/bin/python -u backend/scripts/run_backend_ci.py \
  --output "$PRIVATE_EVIDENCE/full-backend" --seconds 900 \
  backend/venv/bin/python -u -m pytest backend/tests -q --durations=15 \
  -o faulthandler_timeout=60 --junitxml="$PRIVATE_EVIDENCE/full-backend/pytest.xml"
```

Result: **2,264 passed, zero failed/skipped, 744.84 seconds**. The supervisor exited 0 in 748.77 seconds. Two existing pypdf fixture deprecation warnings remain. This includes PostgreSQL migrations, source/deduplication races, identical-key retries, partial ingestion, rollback, provider failures, budgets, profile/skill matching, unknown facts/first-person validation, packet creation/review/staleness/idempotency, exact selection, command/Telegram behavior, permission denials, browser security and disabled real sending/submission paths.

Earlier targeted milestones passed 58 tests, then 40, then 113. The new provider/recovery file has 19 cases; the dedicated PostgreSQL test also passed with a one-connection pool and an actual server-side backend disconnect. Its verifier checks the failed batch rollback, durable failure audit, retained idempotency key and unchanged owner decisions. Initial local failures were a nonexistent test filename, an ORM-vs-schema test setup mistake, and integer-vs-float score display assertion; these were corrected. They are retained privately and are not reported as implementation successes.

After the full suite, a separate private operator check actually stopped and restarted **only the dedicated disposable container**. It verified explicit outage failure, rollback of an uncommitted ingestion, exact same-key replay after restart and duplicate re-observation without overwriting a fictional owner tracking decision. It used zero external HTTP calls and removed its unique fixture database afterward. No online database or installed application service was restarted.

## Static, security and contract checks

```sh
backend/venv/bin/ruff check --isolated --select E9,F,I \
  backend/app/services/application_assistant.py \
  backend/app/services/job_discovery_matcher.py \
  backend/app/services/job_discovery_service.py \
  backend/app/services/job_sources/direct_api.py \
  backend/app/services/startup_discovery/service.py \
  backend/scripts/verify_phase2b_migration.py backend/tests/test_phase2_live_discovery.py
backend/venv/bin/bandit -q -r backend/app
backend/venv/bin/python -m compileall -q backend/app
backend/venv/bin/python -m pip_audit -r backend/requirements.lock --no-deps --disable-pip
/tmp/phase2-actionlint/actionlint -shellcheck=
git diff --check
```

All passed; the pinned audit found zero known vulnerabilities. Bandit emitted one existing unused-`nosec` notice. The dependency audit emitted its existing recommendation to use fully hashed pins. Actionlint skipped unavailable Shellcheck. The secret hook and tracked-private-file guard are recorded with the final manifest.

The OpenAPI exporter was run in this worktree and a separate `git archive` of the verified baseline, using the same isolated interpreter. Their parsed JSON contracts were identical. Only ignored reports were written; no frontend contract was regenerated or modified.

## Live evidence and limitations

See [live discovery](codex-live-discovery.md) for the six genuine persisted jobs, repeat-ingestion/idempotency checks and honest zero-suitability result. The current approved profile, 87 reviewed facts and canonical resume selector were inspected through the restricted runtime. No suitable real vacancy was established, so no new packet was manufactured. Packet acceptance uses clearly fictional local fixtures.

Only three-record online batches succeeded. A larger Greenhouse batch hit the existing discovery deadline and rolled back. A pool deadlock found by live verification was fixed and covered with a real PostgreSQL regression. Interrupted audit records remain available and require deliberate recovery; same-key retries do not silently repeat provider work. Telegram transport delivery was not tested; shared command/handler probes ran in process with no outbound message.

No frontend tests/build were run by Codex; that work belongs to the separate frontend agent. No deployment, release replacement, paid provider activation or real submission/send is included in these results.

**Local tests passed; hosted CI not run by cost policy.**
