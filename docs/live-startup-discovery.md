# Live startup discovery (Phase 6A)

The backend discovers companies through existing job providers and accepts independently sourced company evidence without creating a job. Startup discovery is owner triggered. It does not crawl arbitrary websites, run a scheduler, submit applications, or send messages.

## Source capability matrix

Permission/documentation review: 2026-10-19. Deployment configuration and historical smoke results are different facts. Query `/api/v1/startups/integrations/status` for the current database's actual checks; the repository report is never imported as a live deployment connection.

| Source | Supported operation | Default configuration | Permission basis / limitation | Mock coverage | Actual Phase 6A smoke |
| --- | --- | --- | --- | --- | --- |
| HN hiring / Algolia | Job-led company discovery | No key required | Documented public [search API](https://hn.algolia.com/api), [official API reference](https://github.com/HackerNews/API); comments are leads, not proof of current hiring | Yes | HTTP 200, one valid job |
| Greenhouse | Configured public boards; job-led companies | `GREENHOUSE_BOARDS={}` | [Public GET endpoints](https://docs.greenhouse.io/job-board.html); no submission endpoint used | Yes | HTTP 200, one valid job, with a temporary explicitly configured Razorpay board |
| Remotive | Job-led company discovery | No key required | [API terms](https://github.com/remotive-com/remote-jobs-api): attribution, original Remotive link, 24-hour feed delay, no redistribution to third-party job sites; this is a private job-search backend | Yes | HTTP 200, one valid job |
| Arbeitnow | Job-led company discovery | No key required | [Official API announcement](https://www.arbeitnow.com/blog/job-board-api) and linked documentation; primarily European coverage | Yes | HTTP 200, one valid job |
| YC company directory | Manual reference / rights-confirmed import | Unsupported automated directory operation | No supported directory API or dataset license verified; [terms](https://www.ycombinator.com/legal/) restrict automated extraction; [robots](https://www.ycombinator.com/robots.txt) restrict parameterized directory URLs | Unsupported path tested | No collection performed |
| YC Work at a Startup / Wellfound via Apify | Optional job-led evidence only | `configuration_required` | Actor-specific permission, ownership, build, schemas, pricing and account limits must be reviewed; [Wellfound terms](https://wellfound.com/terms), [robots](https://wellfound.com/robots.txt); store presence is not a data license | Yes, fictional actor | No paid requests |
| Serper | Official-domain professional research; separately authorized professional URL search | Disabled; rights review required | [Serper terms](https://serper.dev/terms) do not resolve third-party content rights; see founder guide | Yes | No key/rights/cost authorization used |
| Manual authorized evidence | Company-first observations and official professional evidence | Available per import after permission confirmation | Owner must possess collection/retention rights and attach permission evidence; publicly accessible alone is insufficient | Yes | Fictional offline demo only |
| Apollo / SignalHire | Existing opt-in contact enrichment | Existing disabled/configuration defaults | Existing account-specific licensing and credit controls remain in force | Existing tests | No Phase 6A paid check |

A job feed does not establish that an employer is a startup or has fewer than 50 people. No company directory provider is advertised as working without verified permission. Company-first operation currently uses bounded, permission-confirmed imports. Automated company-first discovery reports `unsupported` for unavailable sources.

## Evidence and identity

`companies`, `jobs`, `discovered_company_people`, contact identities, and `discovery_runs` remain canonical. Migration 009 adds:

- `company_source_observations`: append-only normalized snapshots, source identity, content hash, source/permission URLs, observation time and optional run FK.
- `startup_shortlist_entries`: one owner-reviewed shortlist entry per company; repeated requests preserve the original note and score snapshot.
- `provider_connection_checks`: separate real/mocked diagnostics, HTTP status, result count, schema outcome, evidence links and sanitized error category.
- `provider_access_windows`: atomic cross-worker pacing shared by startup checks and normal job discovery.

Domain or previously observed source identity resolves aliases. Same-name employers with different domains stay separate. Domainless names are review-sensitive; a confirmed owner observation can associate a unique, unambiguous domainless company with a domain. If multiple known companies share a name, a new unqualified job is stored against a separate domainless, review-required company rather than arbitrarily choosing one. A later domain cannot silently resolve that ambiguous container. Established source/URL observations retain their original company when another namesake appears. No fuzzy name merge is performed. A domain change conflicting with an established source identity fails the batch. Identity hashing is scoped to the provider and prefixes IDs/domains/URLs.

Imported observations require original source and permission evidence URLs, actual timezone-aware observation time, and a verification category. This is an owner assertion with an audit trail, not an independently established license. Human-confirmed attributes take priority over automated reports; source ingestion never rewrites the canonical company name or human company metadata. Evidence APIs expose competing and historical claims. Current-size eligibility uses observations no older than 180 days. Explicit maintenance, rather than startup or scheduled tasks, controls retention (see provider setup).

Size bands are 1–10, 11–50, 51–200, 201–500, 500+ (over 500), and unknown. Default search focuses on at most 50 employees and includes unknown sizes. A strict search sets `include_unknown_size=false`. Contradictory current counts produce an unknown count and `conflicting` evidence status. A band spanning the requested maximum cannot establish eligibility. Funding stage never supplies a count. Employee count refers to the company, not necessarily its engineering team.

## Hiring and ranking

Fresh attributable current-job evidence confirms hiring. Greenhouse observations describe a current public board listing. HN comments and delayed or unconfirmed feeds provide possible hiring leads. Old/explicitly expired jobs become unknown; no jobs does not imply no hiring. An authoritative explicit company statement is required for `not_currently_hiring`. Job publication timestamps remain nullable; retrieval dates are never substituted.

Scores describe relevance, not identity probabilities. Factors: best existing `JobDiscoveryMatcher` result (up to 55 points), reported technology overlap (10), evidence-backed small company (10), fresh confirmed hiring (15; possible 5), saved/requested location or remote compatibility (5), saved stage preference (3), and fresh strong contact evidence (2). Missing information and exclusions remain visible. Salary comparison remains with the existing matcher and never turns unknown salary into zero. Saved verified skills, target roles, locations, exclusions, salary units and stage preferences are reused. Explicit query filters override relevant defaults. Work eligibility still requires review; remote does not guarantee global eligibility.

Company-first ranking can be useful before a job exists and explicitly reports the missing job/contact facts. Startup searches are bounded to 500 candidate companies and 500 jobs per company; narrow the source filter when the bound is exceeded. Sorting uses descending score, company name, and stable company ID. Pagination is deterministic for a fixed saved dataset/profile.

## REST

All startup routes require the existing owner bearer token and return `Cache-Control: no-store`. Invalid inputs are sanitized. Reads never execute providers. POST preview performs no provider calls or writes. Execution has bounded inputs, timeouts, durable idempotency and explicit paid approval. A retry with the same key returns the original run; a different request using that key returns 409. Never blindly replay a crashed paid run with a new key. An expired running lease is shown as `recovery_required`; inspect child runs and retained reservations first.

```sh
curl -H "Authorization: Bearer $JOB_AGENT_API_TOKEN" \
  http://localhost:8000/api/v1/startups/sources

# Saved-company search, including unknown size. This is an example query, not a saved preference.
curl -X POST -H "Authorization: Bearer $JOB_AGENT_API_TOKEN" \
  -H 'Content-Type: application/json' \
  http://localhost:8000/api/v1/startups/search \
  -d '{"skills":["Python"],"locations":["Bengaluru","Delhi NCR","Hyderabad","Pune"],"remote_preference":"remote","max_employees":50,"include_unknown_size":true}'

# Explicit free public-feed run. No paid services are authorized.
curl -X POST -H "Authorization: Bearer $JOB_AGENT_API_TOKEN" \
  -H 'Content-Type: application/json' \
  http://localhost:8000/api/v1/startups/discovery/runs \
  -d '{"mode":"job_led","source":"hacker_news","idempotency_key":"startup-hn-20261019-001","query":{"keywords":["Python"],"limit":20},"filters":{"max_employees":50,"include_unknown_size":true},"allow_paid":false}'
```

Company-first POST `/discovery/runs` takes `source=manual`, `mode=company_first`, `permission_confirmed=true`, and at most `query.limit` typed `companies` (maximum 100). Each includes `name`, `domain` if known, `source`, `source_url`, `permission_evidence_url`, `observed_at`, and evidence-backed fields. Never submit fictional examples into a real database. Use the offline script below for complete executable fixture examples.

Available routes under `/api/v1/startups`: `GET /sources`, `POST /discovery/preview`, `POST /discovery/runs`, `GET /discovery/runs/{run_id}`, `GET|POST /search`, `GET /{company_id}`, `GET /{company_id}/jobs`, `GET /{company_id}/evidence`, `POST /{company_id}/shortlist`, `GET /shortlist`, `GET /integrations/status`, `POST /integrations/{provider}/check`. GET search accepts the same typed filters as query parameters (repeated parameters for arrays); POST is convenient for structured filters.

People search and contacts reuse `/api/v1/discovery/people/search` and `/api/v1/companies/{company_id}/recommended-contacts`. There is no duplicate startup people-search execution endpoint. Detail output links existing contact enrichment, application-preview and outreach workflows. Saving a company or shortlist does not create or send outreach.

## MCP

The existing secure FastMCP server registers `search_discovered_startups(filters)`, `get_startup_intelligence(company_id)`, `get_startup_hiring_opportunities(company_id)`, `get_startup_professional_contacts(company_id)`, and `get_startup_discovery_status()`. Each calls shared services, requires its existing read capability, and performs only cached reads. No MCP live-discovery/check tool is added. There is no paid execution, application submission or sending path through these tools.

## Reproducible validation

```sh
# Full fictional flow: company without job -> observed job -> founder evidence -> ranking
# -> saved shortlist -> existing application preview -> local outreach draft.
python backend/scripts/startup_discovery_demo.py --output /tmp/startup-offline.json

# Optional actual public network request. Temporary SQLite only; no account credentials.
python backend/scripts/startup_discovery_demo.py --live --source hacker_news \
  --output /tmp/startup-live.json

# Greenhouse board must be deliberately chosen from an official employer reference.
python backend/scripts/startup_discovery_demo.py --live --source greenhouse \
  --greenhouse-board razorpaysoftwareprivatelimited \
  --greenhouse-company 'Razorpay Software Private Limited'

# Disposable local PostgreSQL; creates/drops only a unique test database.
PROFILE_TEST_DATABASE_URL=postgresql://YOUR_LOCAL_ROLE@127.0.0.1:5432/candidate_profile_test \
  python backend/scripts/verify_phase6a_migration.py
```

CI blocks external HTTP and mocks all paid calls. It applies migrations 001–009 in disposable PostgreSQL, repeats 009, verifies legacy/public preservation, RLS/grants/FKs, append-only snapshots, rollback, identity/run/shortlist/window/budget concurrency and durable idempotency. Production migrations are never applied by startup or by these demos.

[The actual smoke report](phase6a-live-verification.json) records four real source checks with exact UTC timestamps and evidence URLs. It does not establish a live founder search or a fully verified small-startup shortlist. The full end-to-end demonstration is explicitly fictional/offline. The sample Greenhouse employer is a connectivity example, not a claim that it satisfies the small-company filter.
