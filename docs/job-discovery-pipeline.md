# Phase 2B: job and startup discovery

The backend discovers, normalizes, stores and ranks opportunities. It does not submit applications,
send messages, connect LinkedIn accounts, or run recurring workers. All examples use fictional data.

## Source status

`GET /api/v1/discovery/sources` reports deployment configuration without credentials. `available`
means a supported configured pathway, not a verified account connection; `live_verified` remains
false because a historical smoke check cannot establish ongoing availability.

| Source | Pathway | Default status | Verification |
| --- | --- | --- | --- |
| Greenhouse | Public board GET API; company-specific tokens/names | configuration_required | Offline fixtures; Figma board HTTP 200 smoke check |
| Remotive | Public remote-jobs GET API | available | Offline fixtures; HTTP 200 smoke check |
| Arbeitnow | Public job-board GET API | available | Offline fixtures; HTTP 200 smoke check |
| HN Hiring | Algolia index of Who is hiring threads and top-level comments | available | Offline fixtures; story search HTTP 200 smoke check |
| Naukri | Explicit platform-specific Apify configuration | configuration_required; disabled | Offline fixtures only; no actor vetted or executed |
| Instahyre | Explicit platform-specific Apify configuration | configuration_required; disabled | Offline fixtures only; no actor vetted or executed |
| Wellfound | Explicit platform-specific Apify configuration | configuration_required; disabled | Offline fixtures only; no actor vetted or executed |
| YC Work at a Startup | `work_at_a_startup` Apify configuration | configuration_required; disabled | Offline fixtures only; no actor vetted or executed |
| Internshala | Validated user-provided records | manual_import_only | Offline fixtures; no permitted live connector verified |
| LinkedIn | Permitted public search index or supplied URLs | authorization_required for direct collection | Mock search and manual import tested; no LinkedIn HTTP requests |
| Gmail alerts | Legacy offline parser/manual import | manual_import_only in discovery runner | No account connection verified; subject-only alerts no longer become jobs |
| Cutshort, Hirist, Foundit, Indeed, Glassdoor | Optional explicit Apify mappings | configuration_required; disabled | Not live verified |

The generic `apify` source cannot execute anything. Select an explicit platform. Unknown source
names raise `UnknownSourceError`; they cannot fall back to Naukri. Platform names replace the
legacy `apify_*` normalized names. Existing database rows are preserved unchanged.

Official references inspected during implementation:

- [Greenhouse Job Board API](https://docs.greenhouse.io/job-board): public GET, board tokens,
  `content=true`, listing URLs, publication versus update timestamps. Board slugs are not company domains.
- [Remotive API](https://github.com/remotive-com/remote-jobs-api): preserve attribution and listing
  URL; public data is delayed 24 hours. Follow their recommended maximum four fetches per day.
  There is no scheduler or automatic polling here; the operator controls explicit calls.
- [Arbeitnow API](https://www.arbeitnow.com/blog/job-board-api): public feed; do not equate
  `remote=false` with proof of onsite work. Server-provided next URLs are never fetched.
- [HN search API](https://hn.algolia.com/api): select Who is hiring rather than Who wants to be hired;
  use parent ID filtering and bounded pages. Comment observations do not confirm a vacancy is open.
- [Apify run API](https://docs.apify.com/api/v2/actors-runs-post) and
  [datasets](https://docs.apify.com/storage/dataset): bounded run timeout, charge cap, pinned build,
  terminal status, and dataset `offset`/`limit`. HTTP waits alone do not stop an actor.
- [Serper](https://serper.dev/): authorized search API. Prices depend on the account's credit package;
  this implementation reserves query credits and makes no claim of an exact dollar charge.

Smoke checks were performed on 2026-10-19 IST. A HubSpot Greenhouse token returned 404; a Figma
token returned 200. These are endpoint observations, not an account onboarding guarantee.

## Configuration and costs

Configure `JOB_AGENT_API_TOKEN` and apply migrations 001–004 to a development database first.
Supply Greenhouse board tokens and their factual display names as JSON:

```dotenv
GREENHOUSE_BOARDS={"your_board_token":"Your Company"}
APIFY_API_TOKEN=
APIFY_SOURCES={}
APIFY_MONTHLY_LIMIT_USD=0
APIFY_PER_RUN_CAP_USD=0
PEOPLE_SEARCH_ENABLED=false
SERPER_API_KEY=
SERPER_MONTHLY_LIMIT=100
DISCOVERY_TIMEOUT_SECONDS=90
DISCOVERY_MAX_CONCURRENCY=2
```

No production credentials or actor identifiers are seeded. For each Apify platform the operator
must verify the actor exists, that collection is permitted, its current input schema, pinned build,
and current pricing. Configure that source only after review. Example configuration shape (the
identifier and evidence URLs below are fictional and must be replaced):

```json
{
  "instahyre": {
    "actor_id": "your-publisher/your-reviewed-actor",
    "build": "0.1.2",
    "enabled": true,
    "reviewed": true,
    "schema_evidence_url": "https://example.com/actor-input-schema",
    "pricing_evidence_url": "https://example.com/actor-pricing",
    "permission_evidence_url": "https://example.com/permitted-use",
    "pricing_model": "PAY_PER_EVENT",
    "estimated_per_item_usd": 0.001,
    "estimated_start_usd": 0,
    "field_map": {"query": "actualQueryField", "locations": "actualLocationsField", "limit": "actualLimitField"},
    "fixed_input": {}
  }
}
```

Mappings are source-specific and must match that actor's documented schema; do not copy example
input fields into an unverified actor. Supported logical input values are `query` (string),
`keywords` (list), `location` (string), `locations` (list), and `limit` (integer). A unique limit
mapping is mandatory. Actor page >1 is explicitly unsupported until a provider-specific pagination
mapping is verified. Not every adapter supports every discovery parameter; the service applies
explicit local filters and keeps unknown fields visible. Saved preferences guide queries and ranking.

Running a paid actor additionally requires `allow_paid=true`, enabled/reviewed configuration,
a token, positive monthly/per-run caps and a durable reservation. Estimated start/item rates are
operator-supplied estimates with evidence, not exact charges. The implementation currently permits
only configured PAY_PER_EVENT actors; other billing models require a separately reviewed extension.

`discovery_monthly_budgets` and `discovery_budget_reservations` follow the independent-transaction
usage-manager pattern from Phase 2A. Conditional upserts reserve the entire run cap atomically
across processes, rounded conservatively to micro-units. Reservations survive failed jobs, transport
timeouts and cancellation. They are not released using preliminary provider billing. Repeated
reservation IDs cannot authorize another run. Provider-reported actual cost is recorded separately
and idempotently. Thus monthly cap use can exceed actual charges; it is deliberately conservative.

The run API passes `maxTotalChargeUsd`, `maxItems`, a 60-second actor timeout, a pinned build,
and disables automatic restart. It polls a bounded number of times and reads datasets only after
`SUCCEEDED`. Queued/running/failed/aborted/timed-out runs return errors; pending runs are aborted
when possible. A lost POST response may prevent identifying an actor for abortion: the provider's
run timeout and cap plus the retained reservation remain the fallback. No paid start is retried.
429 responses record a provider cooldown. Serper reserves one monthly query credit per call,
including failed responses. Existing integer credit pools are retained; they cannot safely enforce
concurrent dollar budgets, hence the separate ledger.

## Normalization and identity

`NormalizedJob` retains old field names and adds canonical/application URLs, tri-state remote
information, explicit compensation units, preferred skills, equity, country/region, observed times,
quality flags, provenance and company intelligence. Blank/missing companies stay unknown; jobs
may have no company FK. Neither company domains nor publication dates are synthesized from
board slugs or retrieval timestamps. Update times are kept in provenance. Unparseable records
are individually rejected; the run reports partial results and rejected/failed counts.

All submitted URLs are validated, never fetched. Only HTTPS public hostnames, without credentials,
private/reserved literal addresses or unusual ports, are accepted. URL parsing removes tracking
parameters, fragments and trailing slashes while preserving meaningful query IDs. Known Greenhouse
host aliases converge. Observed per-job ATS application URLs can establish a common identity;
a generic careers URL cannot. Unknown custom redirects are not followed. HTTP-only legacy rows
are preserved but new imports must use HTTPS.

Identity hierarchy:

1. Source posting identity or exact canonical job URL, including a recognizable shared ATS application URL.
2. Same domain-backed company identity, exact normalized title/location/remote policy and exact normalized description of at least 200 characters.
3. Same company/title without sufficient evidence is reported as a possible duplicate and remains separate.

`JobSourceObservation` keeps each platform ID and original link on the canonical job. Nullable
unique canonical/content keys protect newly observed identities without rewriting legacy rows.
A PostgreSQL transaction advisory lock serializes bounded ingestion batches across workers;
unique indexes remain the final constraint. Savepoints contain record-level database errors.
The entire successful batch and final run audit commit together. Re-observation never changes
application status, human match explanation/notes, review/shortlist decisions or application history.
Legacy boolean `is_remote`, `job_url` and `salary_range` remain; v2 clients should use `remote_type`.
Failure of a fetch never closes or deletes a job.

## Preferences and startup intelligence

`JobDiscoveryMatcher` overlays the existing `ApplicationAssistant`. It uses saved factual skills,
experience and target roles. Company/title/keyword exclusions are hard filters in job search;
location, remote policy, employment type, salary, startup priority and observed stage affect ranking.
Scores include matched/missing skills, positive/negative factors, exclusions and unknown fields.
The original assistant's contract remains intact; no Gemini calls occur during discovery.

A minimum salary needs both matching currency and matching `salary_period` in saved preferences.
Undisclosed salary, a bare ambiguous `$` symbol, currency mismatch, period mismatch or overlapping
range yields unknown comparison, never a guessed conversion or automatic rejection. Hybrid and
onsite require explicit evidence. Missing experience remains unknown.

Observed startup stage, batch, technologies, source company/founder links, equity and freshness
are persisted with job metadata and company `metadata.startup_discovery`. Missing fields stay
missing; a title mentioning YC is not evidence of company batch membership. Startup records are
linked to hiring jobs even when founders are unknown. Profile URL discovery is a separate explicit
request; it does not launch a paid search for every job.

## LinkedIn and public people discovery

`public_search` calls only `https://google.serper.dev/search`, requires configuration and per-request
paid approval, and processes index snippets. It never requests LinkedIn pages, private APIs, cookies,
credentials, sessions, CAPTCHAs or company pages. User-supplied published team-page evidence and
LinkedIn URLs are supported through manual import. Standard profile URLs and explicit company
page normalization are validated without network access.

A role/company mention in a snippet is `source_reported`, not verified identity. Missing role evidence,
weak company association and same-name/different-URL ambiguity require review. Duplicate profile
URLs collapse without silently choosing among different identities. Saved records retain evidence,
observed timestamps, source and `outreach_mode=manual`. No emails or professional titles are guessed.
The discovered-people table is separate from contact enrichment so existing email/enrichment state
is untouched. No LinkedIn account password is requested or stored.

## REST examples

Every endpoint below requires the bearer token and returns `Cache-Control: no-store`.

```bash
curl -H "Authorization: Bearer $JOB_AGENT_API_TOKEN" http://localhost:8000/api/v1/discovery/sources
curl -H "Authorization: Bearer $JOB_AGENT_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"source":"arbeitnow","query":{"keywords":["Python"],"limit":10}}' \
  http://localhost:8000/api/v1/discovery/preview
```

Preview is planning-only: zero provider calls, no job/run writes, no charges. It returns configuration,
query defaults and a clearly labeled configured estimate when possible. To explicitly execute:

```json
POST /api/v1/discovery/runs
{"source":"arbeitnow","idempotency_key":"search_001","query":{"limit":20},"use_profile":true}
```

Same key/body returns the existing run, including `running` for a concurrent request; a changed body
returns 409. Runs expose source, status, timestamps, provider ID, counts, errors, conservative usage
and explainable profile-versioned rankings. `GET /api/v1/discovery/runs/{uuid}` retrieves the audit.
A process crash can leave a durable `running` audit; there is no automatic replay or reconciler in
this milestone. Do not replay uncertain paid starts with a new key without checking the provider.

Manual import uses the same pipeline, for example:

```json
POST /api/v1/discovery/runs
{
  "source":"internshala", "query":{"limit":1}, "manual_jobs":[{
    "source_name":"internshala", "source_job_id":"user-record-1",
    "original_url":"https://internshala.com/your-observed-listing",
    "company_name":"Example Company", "title":"Python Intern",
    "remote_type":"unknown", "employment_type":"internship"
  }]
}
```

Use `source=manual` for permitted records from other platforms including supplied LinkedIn job links.
Manual imports are marked `requires_review`, not proof of accepting applications.

```text
GET /api/v1/jobs/search?page=1&limit=20&platform=wellfound&role=Engineer&remote_type=remote&sort=match&rank=true
GET /api/v1/jobs/search?minimum_match_score=60&max_age_days=30&exclude_preferences=true
POST /api/v1/discovery/people/search
{"company_name":"Example Startup","company_domain":"example.com","roles":["founder","cto","recruiter"],"limit":10,"source":"public_search","allow_paid":true}
GET /api/v1/companies/{uuid}/people
```

Job search returns company/startup intelligence, published equity and up to 20 recent source
observations per job, including original listing links and provenance. It supports location/employment
filters, observed freshness and explicit sort order. Ranking
requires a saved profile. Rankings are computed before pagination; narrow queries to at most 5000
jobs. No ranking updates overwrite human job records. The legacy jobs list now also requires a
bearer token because it can expose private match information. Legacy MCP fetch/ingest/connectivity
functions are no longer registered as unauthenticated tools; ingestion directs clients to REST.
Existing unrelated MCP tools are not a hardened multi-user interface and should remain private.

Outcomes include `success`, `no_results`, `partial`, `source_unavailable`, `missing_credentials`,
`rate_limited`, `unsupported_operation`, `authentication_required`, `configuration_required`,
`manual_input_required`, `upstream_error`, `budget_exhausted`, `failed` and `cancelled`.
Provider failures are persisted as run outcomes (HTTP 200 audit response); invalid HTTP requests use
400/422, unauthorized 401, missing server auth 503, missing record 404, idempotency conflict 409,
oversized body 413, and people timeout 504. Raw provider errors and server keys are never returned.
Discovery bodies are capped at 1 MiB before JSON parsing; query/result/page bounds and timeouts
apply. Concurrency limits are per worker; durable money/credit limits apply across workers.

## Migration and verification

Apply `supabase/migrations/004_job_discovery.sql` after 001–003 only to an approved database.
It adds jobs metadata and creates five isolated `job_agent` tables with RLS enabled and no public
client access policies. Existing contacts, profiles, evidence, drafts, jobs and public objects remain.
No previous migration is rewritten. New tables require backend database privileges; do not expose
them directly with Supabase anon/client credentials. Production migration and deployment are not
part of this change.

```bash
python -m pip install -r backend/requirements.txt
python -m compileall -q backend/app
pytest backend/tests -v
git diff --check
# Local administrative test DB only; scripts create/drop uniquely named children:
PROFILE_TEST_DATABASE_URL=postgresql://YOUR_LOCAL_ROLE@127.0.0.1:5432/candidate_profile_test pytest backend/tests -v
```

All automated provider access uses HTTP fixtures; `conftest.py` blocks real HTTP transports. CI
provides disposable PostgreSQL 16 and runs all three migration/concurrency suites. Without the
local test URL PostgreSQL tests explicitly skip; skips are not PostgreSQL verification. Live smoke
checks are separate from fixtures, never execute paid actors and do not constitute portal account
authorization. Later work: explicitly approved enrichment, followed by separately approved outreach.
