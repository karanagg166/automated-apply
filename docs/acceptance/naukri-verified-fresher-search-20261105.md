# Verified Fresher search and exact local installation

[PR #48](https://github.com/karanagg166/automated-apply/pull/48), branch
`fix/live-prepare-discovery-20261030`. Implementation and installed API/extension:
[`b8b380c6443bd2a2c293c376d9c5129ced10385b`](https://github.com/karanagg166/automated-apply/commit/b8b380c6443bd2a2c293c376d9c5129ced10385b).
Times below are November4 UTC (November5 IST).
**Naukri remains OPEN: one new Apply admission, zero new independently verified worker receipts.**

## Genuine portal evidence and change

A genuine Date-sorted generic search returned20 cards;19 required2–18 years.
The experience slider reported zero while its visible label was **Any**, inside
an unselected slider. Zero alone cannot establish the Fresher criterion.

In an owned inactive setup tab, the ordinary search UI exposed
**Fresher (less than1 year)**. Selecting it and searching emitted:

```text
https://www.naukri.com/software-engineer-jobs?k=software%20engineer&experience=0&nignbevent_src=jobsearchDeskGNB
```

The real page returned20 junior cards. Ordinary Date selection retained the
Fresher criterion; an independent document reload again showed the input value
Fresher, a selected slider with visible0 and value0, and20 cards. Sort reset to
Recommended on reload, so Date still requires an ordinary verified transition.
Actual Next links dropped the query; the implementation therefore does not invent
filtered pagination. Original unfiltered searches retain their bounded page1–3
sweeps and saved role preferences.

The API interleaves this observed query with every original role for a candidate
whose verified experience is less than one year. The extension checks both the
query and current rendered Fresher controls before any sorting/result admission.
Any, missing/hydrating controls, duplicate controls, changed keywords or a lost
filter cannot confirm filtered results. The consumer retains its existing40-step/
10-second bound. No timeout, connection limit, provider API or filter exemption
was added. Owner adoption also remains fenced across synchronous DOM steps.

Two genuine20-card observations (Recommended and Date) admitted **6+10 new durable
discovery records** through existing batch dedup;24 observations were already
known or fenced. Those16 records still require normal full-listing filtering and
matching. They are not eligible-application or submission counts. The UI search
preserved the front-window/active-tab snapshot; no keyboard, clipboard or active
personal tab was used. Raw DOM, URLs, private account evidence and intents remain
private; no application action occurred during this search inspection.

## Targeted verification

| Check | Result | Scope |
| --- | --- | --- |
| Backend background queue |71 PASS,9.21s |Fixtures; search rotation, unchanged filters/preferences and bounded original pagination |
| Node Date-sort and queue |71 PASS,1.103s |Fixtures; real control shapes, Any/zero distinction, adoption and existing consumer timeout |
| Isolated Chromium queue |27 PASS,51.627s |Fictional provider responses; real inactive tabs; zero live/unexpected requests and zero chooser events |
| Exact independent API candidate |71 PASS,9.02s |Same backend tests, overlapping source count; own venv, requirements and pip check PASS |
| Exact extension build |PASS |25 files, same key/permissions/ID, version1.3.31 |
| Ruff E9/F/I and diff |PASS |Changed Python and source whitespace |

An initial run exposed three stale Date-helper expectations left over from its
previous asynchronous implementation. The harness now drives synchronous state
steps; unchanged cards/missing layout/unconfirmed sorting stay pending, while
existing queue tests and the browser Any case verify bounded refusal. These were
fixture expectations, not evidence of successful live applications. No unchanged
full execution/browser suite was repeated.

Reproduce from the exact commit with project dependencies installed:

```sh
.venv/bin/python -m pytest backend/tests/test_naukri_background_queue.py -q
pnpm -C extension exec node --test tests/naukri-date-sort.test.mjs tests/naukri-queue.test.mjs
pnpm -C extension exec node tests/naukri-queue.browser.mjs --report /tmp/fresher-search-browser.json
pnpm -C extension build
.venv/bin/ruff check --isolated --select E9,F,I backend/app/execution/naukri_native.py backend/tests/test_naukri_background_queue.py
git diff --check
```

## Actual installation and preservation

The installer acquired the owner lock, verified that total Apply admissions were
still one, and stopped the queue at **STOP137,18:35:48 UTC**. If the newly allowed
second Apply had been admitted, maintenance would have refused without stopping
or replacing anything. Exact previous API and all25 previous extension files,
hashes and protected service/runtime inventories were retained before replacement.

Installation passed **18:36:31 UTC**:

| Component | Actual installed evidence |
| --- | --- |
| API |Exact b8b380c above; full catalog readiness200, same process across checks |
| Extension |Exact b8b380c,1.3.31,25/25 files; stable ID `gdjbmkffcpicbpiikcohlmokkmcpipgp`; ordinary Reload in owned inactive manager |
| Native connection |Fresh selected Profile8 heartbeat, CONNECTED and commands enabled after reload |
| Execution / Telegram / native host |`b6b069051cdddc26683e67ef64646a90a2a7f753`, preserved |
| Frontend |`ae66975691a75cb0a3a43010dcfdba26a5100128`, login200; real Start control verified |
| Data / identity |2,096 work records, profile5, approved binding1 preserved exactly |
| Protection / focus |Private environment/native/other LaunchAgent hashes unchanged; front-window and active-tab snapshots equal |
| Queue restart |Actual frontend RUN138, SUPERVISED lifetime2/hour1, any-skill/score50/age14days/applicants1,000/unknown-count review |

The rollback restores API498dfe7 and extensiondc47f94/1.3.30 under STOP, verifies
catalog003 readiness/native reconnect/account/profile/policy/history, and retains
all releases. No database restore, schema narrowing, quota refund, replay or cleanup
is part of rollback. No frontend, Telegram, execution or native-host replacement
was needed for this change.

A subsequent actual installed unfiltered search completed with no source error
and zero new identities. The next explicit-filter production cycle is still being
observed; genuine manual UI evidence above is distinct from scheduled-worker
acceptance. The five-minute source interval remains unchanged.

## Remaining acceptance

| Requirement | Result | Evidence / next action |
| --- | --- | --- |
| Actual Fresher controls/query and independent reload |PASS |Real inactive portal document,20 cards; Any/zero distinction confirmed |
| Exact installation, preservation and real dashboard Start |PASS |STOP137/RUN138,2,096 records, approved identity/profile, fresh native reconnect |
| Repeated scheduled explicit-filter searches |NOT TESTED at this snapshot |Observe installed native search/result admission at existing intervals |
| One additional distinct eligible attempt |AUTHORIZED / AVAILABLE |Lifetime2/hour1; first admission remains consumed |
| First verified new receipt / recurring AUTOMATIC |NOT ACHIEVED |One original uncertain Apply remains quarantined; no repeated Apply |
| Real locked filling/submission, complete project and other platforms |OPEN / NOT TESTED |Heartbeat, fixture and search evidence do not establish these outcomes |

The original lost questionnaire remains SUBMISSION_UNKNOWN after bounded history
checks, with one truthful dashboard uncertainty notice and one actual sent
Telegram delivery. No second admission or worker receipt was present in the
pre-install full-ledger sample; zero duplicate requisitions were found. QTrino
and all uncertain identities remain fenced. Lower-bound-only50+/100+ applicant
counts stay held pending the already asked owner decision. No other platform,
Gmail sending, paid plan, hosted workflow, merge or deletion was activated.
