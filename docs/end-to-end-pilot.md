# End-to-end pilot

The reusable runner calls StartupDiscoveryService → existing job discovery/ingestion → existing
matching/ranking → ApplicationPacketService. It contains no duplicate provider adapters or
submission client. The limits are goals, never padded totals: at most 20 results, unknown company
size retained and labelled, actual source URLs, ambiguity, hiring freshness and ranking reasons.
Suggested default roles/India-city/remote filters are request defaults, not stored owner facts.
With explicit profile-use approval, saved preferences take precedence over those defaults.
Override locations/roles on the command when needed; do not change the owner's profile implicitly.

## Three modes

```sh
# 1. Safe offline CI: disposable SQLite, injected HTTP/model fixtures, zero external calls.
backend/venv/bin/python backend/scripts/smoke_test.py --mode local-offline

# 2. Real staging DB SELECTs only; no provider requests, token refresh or credit reservations.
backend/venv/bin/python backend/scripts/smoke_test.py --mode staging-read-only \
  --env-file staging.private.env --confirm-staging-target "$STAGING_DATABASE_ID"

# 3. Separate explicit owner action: approved free discovery; persisted staging jobs and packet.
backend/venv/bin/python backend/scripts/run_startup_pilot.py --env-file staging.private.env \
  --confirm-staging-target "$STAGING_DATABASE_ID" --authorize-public-discovery \
  --source hacker_news --idempotency-key owner-pilot-0001
```

Mode 2 does not read private profile data unless `--approve-profile-inspection` is added. Mode 3
without `--approve-profile-use` neither reads the profile nor uses it for matching. To prepare a
real packet, first complete profile onboarding, then explicitly add `--approve-profile-use
--prepare-packet`. Public discovery never enables paid sources or calls Gemini. A packet requires
a saved safe application destination, a confirmed resume and owner-reviewed profile facts.
To run mode 3 through the smoke entry point, pass its independently authorized arguments:

```sh
backend/venv/bin/python backend/scripts/smoke_test.py --mode explicit-live-pilot -- \
  --env-file staging.private.env --confirm-staging-target "$STAGING_DATABASE_ID" \
  --authorize-public-discovery --source hacker_news --idempotency-key owner-pilot-0001
```

Use a stable idempotency key for retries. Reusing it does not replay external calls; changing
filters with the same key is rejected. Expired running leases require investigation; never
clear source windows or reservations to get a fresh run. The runner does not automatically
shortlist, approve answers or mark a job applied. Read the candidate list, review identities and
size evidence, and use the existing shortlist endpoint for deliberate selections.

## Packet review and handoff

Naukri preparation remains available. A narrow local public-listing adapter now prepares packets
for Greenhouse, Arbeitnow, Remotive and HN records. It checks source label/host, source-reported
verification and an explicit saved HTTPS application URL. It never guesses an application URL
from text or treats an HN discussion comment as the employer's application form. Feed records
without a destination remain blocked; locate the official employer page manually and review it
before saving evidence. URL syntax/source consistency do not prove employer ownership.

For a saved job use existing REST endpoints (authenticated owner bearer):

1. POST `/api/v1/jobs/{job_id}/application-preview` to inspect match, facts, selected resume and gaps.
2. POST `/api/v1/jobs/{job_id}/application-packets` with an idempotency key and actual screening
   questions copied by the owner; generated checklist fields are not claimed to be a scraped form.
3. If authorized to send personal facts to Gemini, POST the existing packet field generate endpoint
   for that exact question/revision. Validate missing_information, evidence references and length.
   Without that separate consent, leave narrative fields unresolved or supply owner-written answers.
4. GET `/api/v1/application-packets/{packet_id}`, review every effective answer and exact resume,
   then approve that revision through its review endpoint, confirming the destination and resume.
5. GET its handoff endpoint and open the official application site manually. Upload bytes yourself
   if requested. Packet preparation does not authorize or record a submission or provider receipt.

See the exact endpoint schemas in [application preparation](application-preparation.md). A real
pilot is complete only after genuine job evidence, confirmed candidate facts, authorized generation
where used, and actual human review. The offline demonstration simulates that review using fictional
facts and a fake model; it ends at handoff with not_applied and creates no fabricated receipt.

## Reports and actual evidence

Scripts generate `reports/phase6b-pilot-summary.json` and `.md` (or an explicit --output directory).
Reports contain timestamp/revision/environment, HTTP attempts/responses, diagnostics, actual counts,
size evidence, matching status, packet review links, zero communication/submission counts, blockers
and manual interventions. Offline actual company/job totals are zero; fixture totals are labelled.
A partial source result or absent profile is never converted into `real_pilot_verified=true`.

The Phase 6B local public fallback on 2026-10-19 UTC received one successful Arbeitnow diagnostic
and an HN discovery with partial normalization. It stored 9 jobs/9 associated company records in
**temporary SQLite**, and returned 2 role/location-filter candidates. Their company sizes and
candidate suitability were unverified; neither was asserted to be a small startup. No real profile,
Gemini call, independent founder verification or genuine packet existed. Runtime reports retain
the exact public evidence locally and are deliberately uncommitted. This is execution evidence for
a bounded fallback, not evidence of a deployed staging or production environment. Earlier Phase 6A
checks are retained separately in docs/phase6a-live-verification.json with their original timestamps.

A sandbox-blocked attempt was retained separately from the subsequently network-authorized attempt.
No Remotive call, usage reset or forced pacing bypass was used by the fallback. The shortfall from
five relevant opportunities remains visible. Owner configuration/profile and further appropriately
paced permitted searches are the next work, not invented result rows.
