# Phase 2 backend discovery evidence — 2026-10-27

The Codex branch starts at verified baseline `975b8fc` and incorporates the manual CI policy merge `3a2d6b3`. Phase 1 is closed. Its latest private command-closure cutover record confirms the installed baseline release; older tracked readiness documents describe earlier checkpoints and were not reopened.

## Implementation

The existing adapters, ingestion/deduplication repositories, matcher, packet services, command tools and Telegram handler are retained. No migration, API schema, frontend contract, scheduler or installed runtime was changed.

- Public feed responses are streamed with an 8 MiB decoded-body cap, existing deadlines, fixed hosts, GET-only requests, disabled redirects and bounded retries. Adapter state resets between calls; malformed pagination is an upstream error.
- Arbeitnow category tags are retained as source evidence instead of asserted required skills. Provider-specific fields and attribution are preserved in existing JSON provenance. Greenhouse retains the configured board identity and source publication/update fields.
- Skill matching uses complete mentions in visible description text, preventing matches such as Go inside Django or C inside C++. Missing company, headcount, publication date, salary, requirements and experience remain explicit unknowns. Match explanations reflect the final preference score and require eligibility review.
- Discovery materializes the profile through a short-lived session before source pacing and HTTP. This fixes the genuine one-connection runtime pool deadlock without changing its configuration. A broken rollback invalidates the disconnected session before the independent failure audit.
- The existing startup lease-expiry rendering is shared by ordinary discovery. Expired runs report `recovery_required`; retries never silently replay a provider or spend a retained reservation. The durable interrupted record is preserved for inspection.

## Genuine public-source work

Arbeitnow was prioritized. Its [official API announcement](https://www.arbeitnow.com/blog/job-board-api) describes a free endpoint requiring no API key. [Its API terms](https://www.arbeitnow.com/terms) require a link back; normalized evidence retains the attribution URL and original listing link. No private paid endpoint was used.

Greenhouse documents [unauthenticated public GET access](https://docs.greenhouse.io/job-board.html). The board token was verified through Razorpay's [official careers page](https://razorpay.com/careers/) linking to its [public Greenhouse board](https://job-boards.greenhouse.io/razorpaysoftwareprivatelimited). This board was configured only in the isolated operator process; installed configuration was untouched. No Harvest API, submission POST, credentialed employer session or paid service was used.

Two successful bounded discovery runs made one actual GET per provider. Each normalized, matched and saved three genuine source listings in the approved dedicated Supabase project through its existing restricted runtime identity and public schema. Identical idempotency-key replays made no HTTP calls. Re-ingesting their normalized saved observations inserted zero duplicates and retained the same job IDs. There are six new real listings; the two pre-existing jobs and two packets were preserved. Full URLs, identifiers, timestamps, response bodies, normalized evidence and profile-version rankings are private.

The captured responses contained 300 Arbeitnow listings and 27 Greenhouse listings. All 327 were normalized for local review using the existing adapters against those recorded genuine responses; this replay made no additional external calls and did not persist the remaining listings. None established a suitable saved-profile match. The Arbeitnow role candidates did not establish the preferred geography, and the Greenhouse response did not match the saved target roles. Company stage, size, required skills and personal eligibility were not inferred.

**No new real application packet was created:** selecting an unsuitable vacancy would misstate acceptance. The discovery-to-packet journey remains limited by live suitability. Fictional packet creation, review, canonical/stale-resume handling, duplicate requests and exact job selection are covered separately by local regression tests. No fixture is described as a real vacancy or submitted application.

The current approved profile and all 87 reviewed facts across four approved contexts were read without modification. The existing canonical resume selector reported an available confirmed resource; no resume contents were exported to Git or sent to a provider.

The canonical command tools retrieved the exact saved real job, an honest zero-match result, the two existing packet statuses and canonical resume availability through both owner and Telegram actor gates. The actual Telegram reply handler was also exercised in process. Probe writes were rolled back; no outbox, polling offset, campaign-worker heartbeat or installed service was changed. This is an in-process test against real saved data, **not a delivered Telegram message**.

## Preserved boundaries and limits

Owner authentication, review and action gates remain in place. No employer application, Gmail send/draft, LinkedIn action, CAPTCHA/OTP/legal-consent handling, paid request, external personal-data AI call, browser profile, poller, launchd change, migration or deployment occurred. The full Phase 2 branch must receive integration review with the separate frontend branch before any merge or installation.

An initial operator preflight held the only pooled connection and failed before a run was saved. A second attempt exposed the profile/pacing deadlock and retained an interrupted audit. A subsequent 27-listing Greenhouse ingestion exceeded the 90-second discovery deadline: the batch rolled back with zero jobs committed and a truthful upstream-error audit. The three-record runs then succeeded. These failures remain in private evidence; larger online batches are not claimed verified.

The full feed is not the entire job market, and missing freshness or eligibility evidence is not proof that a vacancy is suitable. Existing interrupted runs require inspection and an explicit new request key when appropriate. Hosted CI is never dispatched automatically by this work.

See [CI cutover](codex-ci-cost-control.md) and [local validation](codex-local-validation.md). Detailed evidence is private under the existing application-support directory's `phase2-codex-evidence`; it must remain outside Git.
