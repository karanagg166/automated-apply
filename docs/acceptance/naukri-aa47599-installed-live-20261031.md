# Exact aa47599 installed: genuine Date sorting; first application still blocked

Branch `fix/live-prepare-discovery-20261030`, base `main`, [OPEN PR #48](https://github.com/karanagg166/automated-apply/pull/48).
[Sanitized measurements](naukri-aa47599-installed-live-20261031-metrics.json).
Current queue snapshot: **2026-10-31 18:10:33 UTC**.

**Zero new Apply admissions, submissions or confirmed receipts.** The retained
QTrino receipt has not been replayed. AUTOMATIC is not enabled. The first real
application remains unaccepted; passing fixtures do not change that result.

## Approved installation and preserved components

The owner explicitly approved exactly
[`aa47599a3bd8bfb2848844835fbc36654def361b`](https://github.com/karanagg166/automated-apply/commit/aa47599a3bd8bfb2848844835fbc36654def361b).
Only the execution worker and stable same-ID extension were replaced.

| Component | Actual installed source / result |
| --- | --- |
| Execution worker | **aa47599a3bd8bfb2848844835fbc36654def361b**, own immutable source/venv, new PID 70048 |
| Profile 8 extension | **1.3.7**, same aa47599 SHA, same ID/key/permissions, 22/22 exact files, ordinary Reload and displayed version verified |
| API | **331ce17711667d21bc96c42d8dc74793d670095f**, unchanged |
| Telegram / frontend / native host | **fc91a219d5b824f934bb733eaf20166661e1f08b**, unchanged |
| New parser correction | **cf686f853b2c40642e950bba92fcb07ef8b655c1**, extension 1.3.8, built **NOT INSTALLED** |

At 17:50:35 the previously running queue had 267 records: 96 DISCOVERED,
25 NEEDS_INPUT, 145 SKIPPED and one historical receipt. Stop took **7.199 s**,
producing STOPPED revision 14. Both API pages were checked; no active or unknown
write was present. All eight protected references and the previous/candidate
extension inventories were revalidated before replacing files.

The original worker PID 58182 exited at **17:51:11** before plist replacement.
Existing API readiness returned 200 in **2.456 s**, Chrome displayed 1.3.7 at
**17:51:17**, and readiness returned 200 again in **2.406 s**. Installation checks
passed **17:51:33**, preserving policy, account binding, all 267 records and the
historical receipt. Only the execution plist changed among protected references.
All previous releases, native files, private configuration and rollback files remain.

Canonical PDF verification after cutover passed: **100,198 bytes**, valid PDF
prefix, decrypted in memory, saved digest match and confirmed profile/resume.
Approved account binding revision 1 is unchanged. A supported, read-only actual
profile-UI comparison subsequently returned `COMPARED` at **18:04:40 UTC**.
No profile writes were permitted or performed; the original optional comparison
policy was restored at revision 7. No identity/resume questions were re-asked.

The queue resumed **RUNNING revision 15 at 17:52:38**, retaining SUPERVISED cap 1,
hourly cap 1, minimum score 80, two-day age limit, applicant threshold 10,000,
unknown-applicant review, global daily cap 80 and concurrency **one**. Seven
backend-failed metadata reads were retried once, each excluding prepared packets,
admitted actions and uncertain outcomes. Existing other failure states were retained.

## Actual discovery and remaining inspection work

An independent observation of the worker-owned inactive actual
`https://www.naukri.com/backend-developer-jobs` tab captured **Date selected and
20 real cards**. The installed consumer selected Date itself; the observer only
read the result. No owner tab was focused, typed into or adopted.

| Actual installed discovery cycle, UTC | Newly admitted distinct URLs | Duration |
| --- | ---: | ---: |
| 17:52:57–17:53:18 | 7 | 20.795 s |
| 17:58:24–17:58:44 | 3 | 19.518 s |
| 18:03:27–18:03:54 | 8 | 26.987 s |
| 18:08:55–18:09:18 | 0 | 22.795 s |

The configured interval remains 300 seconds; busy work can delay a cycle's start.
Total queue records increased **267 → 285**. Source admission counter increased
254 → 272; it excludes other saved sources and the historical receipt.
Sixteen current Date-search metadata reads were prioritized without changing
eligibility; 92 others were deferred ten minutes with prior availability preserved.
That temporary delay expired. No excluded or uncertain submission was replayed.

The requested **original 128 pending IDs** are tracked separately from newly
discovered work. At **18:10:06**, 45 had an inspection outcome: 35 SKIPPED and
10 NEEDS_INPUT; **83 remained DISCOVERED**. Thirty-two already progressed between
the preceding report and this cutover; the rest progressed during this phase.
The full original backlog has **not** been completed, and its uninspected jobs
have no eligibility claim. Processing continues with the saved concurrency one.

| Persistent queue at 18:10:33 UTC | Count |
| --- | ---: |
| DISCOVERED: queued / leased | 95 / 1 |
| SKIPPED: `posting_outside_age_limit` | 149 |
| SKIPPED: `current_profile_preferences_or_required_skills_exclude_job` | 5 |
| NEEDS_INPUT: `posting_age_requires_review` | 19 |
| NEEDS_INPUT: `applicant_count_requires_review` | 3 |
| NEEDS_INPUT: `job_required_facts_unrecognized` | 12 |
| Retained historical `SUBMITTED_RECORDED` | 1 |
| READY / new Apply admissions / new confirmed receipts / unknown submissions | 0 / 0 / 0 / 0 |

## Highest-ranked observed candidates: none yet eligible

A read-only diagnostic applied the unchanged saved matcher and policy to
**174 real persisted browser fact records at 18:08:01**. It created no Job,
packet, action or receipt and changed no stored score. **None reached 80; the
highest score was 70.** These are diagnostic scores from actual observed facts,
not fixture results or successful applications.

| Real job link | Score | Exact observed blockers |
| --- | ---: | --- |
| [Qualcomm Software Engineer](https://www.naukri.com/job-listings-software-engineer-qualcomm-bengaluru-0-to-1-years-261026005898) | 70 | Posted 2026-10-26: `posting_outside_age_limit`; `minimum_match_score_required`; employment/company-stage/startup evidence unknown |
| [Talentzo Software Development Engineer](https://www.naukri.com/job-listings-software-development-engineer-at-a-fintech-company-talentzo-delhi-pune-0-to-5-years-141026040702) | 56.67 | Posted 2026-10-14; age, missing required skill, minimum score and unknown required facts |
| [Creative Hands Software Engineer](https://www.naukri.com/job-listings-software-engineer-creative-hands-hr-hyderabad-chennai-bengaluru-0-to-2-years-301026011205) | 42.31 | Recent candidate; 2026-10-30 date-only precision requires review; missing required skills; score below 80 |
| [Cisco Software Engineer](https://www.naukri.com/job-listings-software-engineer-cisco-bengaluru-0-to-1-years-301026504736) | 38 | Recent candidate; same date-only age ambiguity, missing required skills and score below 80 |
| [Nxtwave Python Fullstack Developer](https://www.naukri.com/job-listings-python-fullstack-developer-nxtwave-disruptive-technologies-hyderabad-0-to-1-years-301026024476) | 35 | Recent candidate; age ambiguity, missing required skills and score below 80 |

There is no established highest-ranked **eligible** candidate to submit.
The uninspected backlog is not declared ineligible. Lower-bound labels such as
50+ or 100+ cannot establish the configured applicant upper limit; exact counts
were not invented. Company-stage facts were not inferred from an employer name.
An essential missing personal answer has not been established, so Telegram was
not used to ask the owner to resolve platform metadata or change filters.

## Reproduced parser defect and conservative correction

Three actual DOM captures, covering two unique jobs, showed experience **“0 years”**:
[Creative Solutions UI/UX / React developer](https://www.naukri.com/job-listings-immediate-hiring-for-ui-ux-react-js-developer-creative-solutions-bengaluru-0-to-0-years-091026036794)
and [HighRadius Forward Deployed Engineer](https://www.naukri.com/job-listings-forward-deployed-engineer-expansion-highradius-technologies-pvt-ltd-hyderabad-0-to-0-years-140826028442).
All other required containers were present. Installed 1.3.7 accepts only a range,
so the exact stage is read-only inspection, `job_required_facts_unrecognized`.

Their genuine structured data also says **monthsOfExperience = 1**, while the
visible label says zero years. This property represents a minimum requirement.
[Schema.org definition](https://schema.org/monthsOfExperience).
The provider facts disagree; the correction must not silently grant a zero-experience fit.
Their observed posting dates are October 9 and October 22, so neither becomes
eligible under the two-day policy even if the layout parser is corrected.

Source [cf686f853b2c40642e950bba92fcb07ef8b655c1](https://github.com/karanagg166/automated-apply/commit/cf686f853b2c40642e950bba92fcb07ef8b655c1)
recognizes explicit single-year values, reads supported structured employment
labels (including the actual “Full Time, Permanent”), and recognizes work mode
only from an explicit unambiguous header location label. Missing facts stay unknown.
It returns `experience_requirement_evidence_conflict` when a structured minimum
exceeds the displayed band, and `structured_experience_requires_review` for an
unreadable structured requirement. No qualification, timestamp, count or country is invented.

| New correction validation | Exact result | Scope |
| --- | --- | --- |
| Observation + queue Node regressions | **57 passed, 1.159 s** | Isolated fixtures; 20 new observer cases |
| Chromium queue/observer journey | **8 cases passed, 56.104 s** | Actual isolated inactive tabs, fictional pages, zero live/unexpected provider requests or choosers |
| Retained live DOM replay | **3 captures / 2 unique jobs** correctly return experience conflict | Offline replay, not installed live acceptance |
| Prettier, diff, same-ID extension build | PASS | 22/22 exact candidate files, unchanged key/permissions |

No backend, frontend or broad unrelated suite was rerun for this extension-only
correction. Prior aa47599 validation remains linked in the
[preceding report](naukri-real-execution-20261031.md); those fixture counts are not
relabelled as new live results. Installed releases were not edited as source.

Reproduction from the correction SHA, using isolated fixtures only:

```sh
node --test extension/tests/naukri-observation.test.mjs extension/tests/naukri-queue.test.mjs
node extension/tests/naukri-queue.browser.mjs
pnpm -C extension build
```

## Lock, timing and acceptance limits

The retained first **113 mixed API requests after cutover all returned 200**,
min/median/max **1.523 / 2.771 / 17.278 s**. This is a bounded sample, not a
claim of eliminated contention or 24/7 reliability. A direct operator priority
transaction still hit `lock_timeout`, rolled back, then succeeded. One operator
monitor query failed with DBAPIError; its precise code was not retained, so its
cause is unproven. No application action depended on that failed observation.

The prior mixed sample was 1.552 / 2.997 / 13.273 s with three HTTP 503s.
Loads and operations differ: this is **not a controlled speedup comparison**.
Native owner transactions and repeated remote SQL round trips remain slow.
CPU/RAM before/after benchmarks were not performed. Production connection caps,
pool sizes and timeouts are unchanged. Concurrent operator probes were reduced;
monitoring now requests small server-side aggregates instead of repeated full descriptions.

| Requirement | Status | Remaining work |
| --- | --- | --- |
| Exact approved worker / same-ID 1.3.7 installed | PASS observed | Protected other components unchanged |
| Canonical local PDF and current account binding / profile UI | PASS observed | Per-application fresh provider PDF proof still required |
| Actual automatic Date selection and repeated discovery | PASS bounded | Preserve source limits; URLs are not applications |
| Original 128 inspection backlog completed | FAIL: incomplete | 83 remained at 18:10:06; queue continues, concurrency one |
| First genuinely eligible job / supported Apply / independent new receipt | BLOCKED | No eligible observed candidate; do not weaken filters |
| Remaining single-year parsing | BLOCKED installation / provider conflict | Reviewed correction built; conflicting requirements still require review |
| Database/native responsiveness accepted | FAIL: still open | No native HTTP error in retained sample, but slow requests/operator contention remain |
| Actual questionnaire / Cohere / Telegram receipt update | NOT TESTED | No eligible first application reached; no success message fabricated |
| Recurring AUTOMATIC | NOT ENABLED | First actual receipt and critical live acceptance required |
| Locked Mac browser submissions / extended reliability | NOT TESTED | No definitive locked-browser submission observation; heartbeat alone is insufficient |

## Exact prepared next cutover and rollback

The **extension-only 1.3.8 candidate cf686f853b2c40642e950bba92fcb07ef8b655c1**
has a separate immutable extension snapshot, verified 22-file build and a backup
of all 22 installed 1.3.7 files. Eight protected service/config/native references
are inventoried. It is **not installed**. The owner's aa47599 approval does not
approve this different SHA.

After exact-SHA approval: stop/fence the queue, verify no active/uncertain write,
revalidate inventories, replace only those extension files and use ordinary
same-ID Reload. Verify displayed 1.3.8, all protected references and existing
account/resume/policy/receipt state, then resume the standing cap-one scope.
API stays 331, worker stays aa47599, Telegram/frontend/native stay fc91.
Only affected metadata with no packet/admitted action may be retried.

On failure keep the queue stopped, restore all exact 1.3.7 extension files,
ordinary Reload and verify protected hashes/readiness. Never restore database
outcomes, erase a receipt or replay an uncertain Apply. No dependency-version,
permission, schema, API/native contract or service reference change is needed.

The installed supervised pipeline remains running. PR #48 remains OPEN.
No merge, hosted Actions, historical release deletion, cleanup, Gmail sending,
other-platform activation, QTrino replay or policy relaxation occurred.
