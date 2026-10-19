# Discovery provider setup and diagnostics

No production credentials, database migration or deployment is implied by this phase. Apply migration 009 only through the deployment's separately authorized migration process. See [startup discovery](live-startup-discovery.md) for API examples and the current capability matrix.

## Free public sources

HN/Algolia, Remotive and Arbeitnow need no API key. Greenhouse needs an explicit `GREENHOUSE_BOARDS` mapping of public board token to employer display name. Obtain tokens from the employer's official careers link; never guess a company domain from a board token. Only fixed provider hosts are requested. External platform writes are excluded.

Startup connectivity checks and normal REST job discovery share durable per-source request windows. Default minimum intervals are six hours for Remotive and 60 seconds for HN/Algolia, Arbeitnow and Greenhouse. The latter are conservative local deployment limits, not assertions about provider quotas. Remotive is not retried automatically, honoring its recommended four requests per day; other public transport/server failures have at most one bounded retry. Greenhouse accesses at most ten configured boards per job run. Arbeitnow follows integer pages without following arbitrary upstream links. HN pages comments of the current hiring thread; Remotive/Greenhouse use bounded local pagination where needed. Responses are normalized and per-record failures stay visible.

An owner can POST `/api/v1/startups/integrations/arbeitnow/check` with the existing bearer token. One normalized result is requested; zero results with a valid collection is different from malformed JSON or invalid records. Check outcomes persist separately from jobs. The check does not ingest a live sample company/job. A check for a paid provider never executes it and returns authorization-required. Narrow smoke scripts likewise use temporary local SQLite and produce a JSON audit without touching the operator database.

`GET /api/v1/startups/integrations/status` and the existing integration registry expose configuration separately from recent actual checks. States: `not_configured`, `configured_not_tested`, `testing`, `live_verified`, `failed`, `authorization_required`, `rate_limited`, `unsupported`. `PROVIDER_VERIFICATION_TTL_HOURS=24` bounds successful verification freshness. Provider/board configuration is fingerprinted so changing boards invalidates a previous verification. Mocks cannot set live verification. An expired testing lease becomes failed in the read view; an expired discovery execution requires owner recovery. There is no automatic replay after a process crash.

A `live_verified` record only means its bounded operation returned valid data at that time; it is not a service-level guarantee or proof of hiring truth. Results contain HTTP status when available, schema outcome, count, original evidence URLs, actual check times, and a sanitized category. Provider response bodies and credentials are never included in errors. Recheck explicitly after limits permit; do not delete rate windows to bypass a provider's request policy.

## Serper and professional evidence

Configuration remains disabled by default:

```dotenv
PEOPLE_SEARCH_ENABLED=false
SERPER_API_KEY=
PUBLIC_SEARCH_RIGHTS_REVIEWED=false
PUBLIC_SEARCH_PERMISSION_EVIDENCE_URL=
PUBLIC_SEARCH_ALLOWED_DOMAINS={}
LINKEDIN_SEARCH_RETENTION_AUTHORIZED=false
SERPER_MONTHLY_LIMIT=100
```

Before enabling, establish the provider account's permitted use, applicable personal-data retention rights, company-domain permission, and account-specific credit costs. Record an actual permission URL. For official-domain search, the map associates the exact employer domain with its permission document. `allow_paid=true` is separately required for each search. The existing database reservation ledger charges one reserved Serper query unit per request and retains uncertain reservations after failure/timeout. The local configured quota is not the actual provider account balance. The live check route does not automatically spend a Serper credit. Use the research route only after completing configuration and cost authorization. Leave LinkedIn retention disabled without applicable consent/rights.

## Wellfound / YC actors

No actor is selected or claimed as vetted. [Apify's current pricing documentation](https://docs.apify.com/actors/running/actors-in-store) explains actor-specific charges, account discounts and separately billed platform/storage usage. A run's `maxTotalChargeUsd` caps pay-per-event charges; it does not establish a universal cap on every account/platform/dataset charge. Store publication does not establish source-data rights. YC terms restrict automated extraction, and Wellfound has access/load restrictions. Review both underlying-source permissions and provider licensing.

A reviewed `APIFY_SOURCES` entry must identify the actual actor owner/ID, pinned numeric build, input mapping (including a unique bounded limit field), exact output contract, schema/pricing/permission evidence URLs, account-specific prices, and supported pagination. The adapter supports bounded initial discovery and dataset offset pages, not an invented portal continuation protocol. Page >1 is unsupported unless implemented and verified for that provider.

Paid execution also requires `enabled`, `reviewed`, `platform_usage_included`, `account_spending_limit_verified`, a legitimate `APIFY_API_TOKEN`, positive `APIFY_PER_RUN_CAP_USD`, sufficient `APIFY_MONTHLY_LIMIT_USD`, and `allow_paid=true`. The new pricing flags are operator attestations: verify inclusive platform pricing and an account-wide hard spending limit covering dataset reads before setting them. Sources missing these reviews report configuration-required. An actor that cannot satisfy bounded-cost requirements is unsupported by this backend. Use provider-side `maxTotalChargeUsd`, `maxItems`, finite actor runtime and no restart; reserve the full cap in the database before the request. Uncertain costs remain reserved. Do not run a paid actor as a connectivity probe. No exact actor, price, account permission or dataset was verified in this phase because none was supplied with authorized paid execution.

## Retention and operations

Company snapshots expose historical/conflicting claims and stop contributing current size/attributes after 180 days. Contact evidence uses existing cache/retention settings; expired observations remain stale, suppression keys survive pruning, and human corrections must be preserved. Operational checks and discovery runs carry no raw provider response body. Shortlists retain an explicit reviewed snapshot even if current ranking later changes.

Use existing `prune_provider_data` for unconfirmed provider contacts (including public-search/official-company candidates), and `startup_discovery.retention.prune_startup_data` for old company snapshots, finished diagnostics and expired public-search people. These shared maintenance functions require an explicit owner-controlled transaction and commit; no scheduled broad collection or automatic deletion is added. Retention preserves human-confirmed observations, canonical contacts and hashed suppression identities so old candidates cannot silently re-enter recommendations. Set periods according to the actual source license. Keep permission-confirmed human records under the owner's chosen retention policy. Do not treat observation validity as permission to retain personal information indefinitely. Source-side deletion/consent withdrawal must also be honored. Review snapshots containing references before pruning companies/runs.

Troubleshooting:

- `not_configured`: configure the actual board or credential and finish required reviews.
- `authorization_required`: approve a permitted operation and verify rights; credentials alone do not suffice.
- `rate_limited`: honor the durable request window/provider cooldown before a new owner action.
- `failed` with schema errors: inspect provider schema in a safe environment; HTTP 200 alone is insufficient.
- `configured_not_tested`: no recent successful real check exists for this configuration; mocks and old reports are insufficient.
- `recovery_required`: inspect the saved child run/provider-run ID, retained reservations and shortlist before choosing a new idempotency key.
- Too many companies/jobs: narrow the source filters; reads do not launch broad network discovery.

The full fictional demo and actual bounded smoke are separate commands. See [recorded live results](phase6a-live-verification.json); do not seed those historical diagnostics into a deployment as fresh verification.

## Phase 6B deployment validation

Use [real provider validation](real-provider-validation.md) and [operations](phase6b-operations.md)
for explicit pinned-staging diagnostics and existing durable source pacing. Configured credentials
are never live verification. Free connectivity checks persist audits/windows; read-only staging
smoke does not. Remotive retains its six-hour interval. Deliberately configure Greenhouse boards
using employer references; never substitute arbitrary large employers as small startup evidence.
Paid account/pricing/permission review is independent of API-key presence, actor marketplace
visibility and Google-index availability. No automatic paid request, Gmail send or submission exists.
