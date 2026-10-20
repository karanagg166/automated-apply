# Real provider validation

The source of truth is timestamped diagnostics/usage ledgers in the selected environment.
Configuration, mocked tests, live connectivity, permitted retention and factual quality are
separate. A sample HTTP 200 does not establish company size, current job eligibility or identity.

| Provider | Operational path | Required evidence / limits |
|---|---|---|
| Hacker News / Algolia | Existing fixed-host read adapter | Top-level hiring posts, original HN URLs, conservative minute spacing; posts may fail normalization |
| Arbeitnow | Existing public feed | One bounded page; source attribution, page cursor and date/remote normalization |
| Remotive | Existing public API | Keep attribution/feed delay; durable six-hour request interval; no retries within an attempt |
| Greenhouse | Existing public board GET | Deliberately configured employer-verified board token/name; local pagination over bounded boards |
| Gemini | Existing SDK + LLMUsageManager | Owner credential/model, request/token cap, fictional initial test, grounding + human review |
| Serper | Existing public_search service | Rights review, permission URL, exact allowed employer domains, separate LinkedIn retention consent, explicit paid approval |
| Apollo / SignalHire | Existing enrichment providers | Actual account endpoint authorization, maximum credits per lookup, monthly/per-run budgets, suppression/retention |
| Apify / Wellfound / YC jobs | Existing opt-in actor adapter | Pinned reviewed actor/schema, permission/pricing evidence, account spending limits, durable reservations and explicit allow_paid |
| YC company directory | Manual reference | No supported permitted company-directory collector is verified |
| Gmail | Existing metadata OAuth status | Redirect/keyring/expected sender/scopes, actual account verification timestamp; no sends in this phase |

Official references: [HN API documentation](https://hn.algolia.com/api),
[Arbeitnow API](https://www.arbeitnow.com/api/job-board-api),
[Remotive API documentation](https://github.com/remotive-com/remote-jobs-api), and
[Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html). Greenhouse public GET
access does not authorize an application POST. Review current provider terms before deployment.

## Explicit public checks

```sh
backend/venv/bin/python backend/scripts/check_providers.py --env-file staging.private.env \
  --confirm-staging-target "$STAGING_DATABASE_ID" --authorize-public-check --source arbeitnow
```

This persists ProviderConnectionCheck and its access window; it is not a read-only database
inspection, although the external provider operation is read-only. A same-source discovery
must wait until next_allowed_at. Do not delete the window or reset budget reservations to force
requests. There are no paid-provider diagnostics hidden behind this command. Configured but
untested sources remain so; old successful checks expire by PROVIDER_VERIFICATION_TTL_HOURS.

Historical local fallback (retired): `public_source_smoke.py` now rejects live
execution because real job/workflow state must use approved online PostgreSQL.
Use the existing `run_startup_pilot.py` with an approved staging target. The prior
temporary-SQLite result below is historical evidence only:
one Arbeitnow sample and one HN job discovery capped at 20 records. It excludes Remotive, writes
an attempt marker before HTTP, and refuses to overwrite that marker. Use durable staging pacing
for further runs rather than removing reports. It is not PostgreSQL or deployment verification.
Transient failures, invalid records and zero results stay visible and are not padded with fixtures.

## Gemini

```sh
backend/venv/bin/python backend/scripts/validate_gemini.py --env-file staging.private.env \
  --confirm-staging-target "$STAGING_DATABASE_ID" --authorize-live-gemini
```

This can incur a provider charge. It uses only fictional contribution evidence, the existing SDK,
existing concurrency limiter and durable reservations. There are at most two requests including
one existing-manager retry, each at most 256 output tokens. Its effective monthly cap is the
smaller of the configured cap and two; existing monthly usage is never reset, so it can refuse a
probe when prior requests already consume that allowance. Token counts are provider-reported;
no account balance, exact charge or live model availability is guessed. Small input is fixed by
the script. Reports retain evaluation status, usage and fixed errors, not prompts/answer bodies.
Claim/length checks catch unsupported facts, but cannot prove accuracy, naturalness or professional
quality; the owner must inspect actual authorized application drafts before using them.

## Paid providers and founder evidence

Operations status exposes configuration, supported operations, configured caps, unknown
permission/account/pricing status, available successful/failed request timestamps, and explicit
per-call approval requirements. It never queries balances. Paid execution is false for this
inspection; existing enrichment APIs still require their own enabled flags, account-confirmed
prices and `allow_paid` budget reservation. A configured API key does not prove endpoint access.
Search snippets remain candidates needing human verification. Official employer evidence and
search-index evidence retain their existing provenance distinctions. Without retention rights,
keep LinkedIn-derived retention disabled and research manually. No direct LinkedIn fetching,
login, cookies, private endpoints, messaging or connection requests are added.

Gmail status decrypts an existing refresh envelope locally to test key usability but never
refreshes it, changes scopes or verifies identity over the network. Sender identity is reported
as a boolean, not an email address. Scopes and last persisted verification are visible. Missing
key/scopes/identity requires owner reauthorization through existing PKCE routes; a configuration
check is not a successful OAuth connection. Sending remains disabled and no send test is available.
