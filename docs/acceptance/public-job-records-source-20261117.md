# Seven public job record parsers — source checkpoint 2026-11-17

Implementation [037a00698bb561788ed471789e3680c38091e14c](https://github.com/karanagg166/automated-apply/commit/037a00698bb561788ed471789e3680c38091e14c), branch `feat/rust-agent-runtime`, [PR 50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source; these parsers are not yet connected feed transports.

Native pure record parsers now cover Greenhouse, Lever, Ashby, SmartRecruiters, Remotive, Arbeitnow and top-level Hacker News hiring comments. They compose the actual normalized job contract, configured employer attribution, hosted posting/application identity checks, public visibility/active/detail checks, explicit compensation units and unknown remote/publication evidence. Lever does not invent a publication date; Ashby isRemote cannot establish remote rather than hybrid without workplaceType. Arbeitnow feed categories are not promoted to required skills. HN text/entity processing uses the already-pinned HTML tokenizer locally and follows no links.

As an intentional privacy tightening, new provenance omits arbitrary `source_fields` dictionaries, recruiter fields and raw vendor JSON; Greenhouse updated_at is retained only as a bounded valid RFC3339 string. Malformed scalar provider IDs and unknown structural types fail conservatively. Local parsing is separate from source rights, HTTP/pagination, live vacancy checks and application authority. Bounds are 1-MiB input envelopes and the existing 256-KiB normalized output. No new dependency was added.

Primary references reviewed include [Greenhouse public jobs](https://docs.greenhouse.io/job-board), [Lever fields](https://github.com/lever/postings-api/blob/master/README.md), [Ashby posting API](https://developers.ashbyhq.com/docs/public-job-posting-api), [SmartRecruiters public endpoints](https://developers.smartrecruiters.com/docs/endpoints) and [Remotive's documented usage limits](https://github.com/remotive-com/remote-jobs-api/blob/main/README.md). These are design references, not current feed verification; final transport must preserve source intervals and attribution.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Seven record parsers, shared remote/employment/date/salary/URL rules and formatting applied; provider transports and ingestion follow |
| Standard additions | NOT TESTED | 5 declarations: 80 actual helper cases, 28 hosted URL cases, 84 actual parser cases (12 per source), 24 date cases, plus conservative bounds; 216 actual comparisons declared, none executed |
| Current tests/build/check/lint/types | NOT TESTED | New executed tests: 0; complete agreed source precedes combined gates |
| Actual Mac/provider/install | NOT TESTED | No real feed, account, application, browser, production database or installation operation |
| Timing/resources | NOT TESTED | Pure bounds and reused library only; no measured performance/binary/memory comparison |

The deferred parser oracle extracts the actual seven parser functions/methods without importing application settings or HTTP clients, pins fictional observation time and removes only the documented source_fields provenance difference before comparison. These selected cases do not establish complete parser parity or live provider compatibility. Fixed failures include `public_job_record_invalid`, `invalid_normalized_job`, `normalized_job_input_limit` and `normalized_job_record_limit`; no executed failure logs or private evidence is published.

Deferred reproduction: `cargo test --locked -p automated-apply-agents --test public_job_records`, the earlier job contract suite and full `uv run --no-project python scripts/run_acceptance.py` after remaining agreed source. Next: fixed-host provider GETs, bounded pagination/deduplication, durable access windows/retained observations and atomic startup job-led ingestion; reviewed Apify execution and other runtime/platform source remain.

Last validated `9c4ace570535a5856184775f8045ee89eafdd05f` remains 193 standard +262 dedicated native PG =455 distinct passes, not current-source evidence. Estimate remains 58% /42%. STOP162, lifetime4/hourly1, three uncertain quarantines, zero strict worker receipts and all identity/PDF/filter/focus constraints remain unchanged. No hosted Actions, merge, cleanup, sending or installation occurred.
