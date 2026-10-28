# Phase 4 source and site evidence

Research date: 2026-10-28. Documentation establishes supported interfaces, not a right to use every employer. Regression acceptance uses fictional/intercepted provider and employer content. The final combined integration additionally performed five bounded credential-free public GETs across Ashby, Lever and SmartRecruiters. One genuine Bengaluru engineering listing and its source observation were saved to the existing approved online PostgreSQL database and matched locally against the current approved profile. A second Ashby observation updated the same saved job with zero new inserts and preserved its application state. Unknown country, experience, skills, salary and company size were preserved. No suitable vacancy or genuine applicant-site acceptance is certified. See the sanitized [live observation receipt](live-source-observations.json); earlier standalone-agent receipts below remain historical. No genuine Gmail messages, paid provider collections or employer applications are claimed.

## Discovery interfaces

| Source | Implemented path | Permission and evidence boundary |
| --- | --- | --- |
| Greenhouse | Existing public Job Board GET adapter, explicit boards | Official [Job Board API](https://docs.greenhouse.io/job-board.html) documents credential-free GET endpoints. Submission endpoints are outside discovery. |
| Lever, including EU | Existing public postings adapter, explicit sites | Official [Postings API](https://github.com/lever/postings-api) describes published postings and the global/EU endpoints. No internal jobs or application POSTs are used. |
| Ashby | Existing public posting API, explicit boards | Official [Job Postings API](https://developers.ashbyhq.com/docs/public-job-posting-api) documents listed jobs, publication and precise workplace types. Hidden/unlisted entries are excluded. |
| SmartRecruiters | New public company postings/detail GET adapter | Official [authentication guide](https://developers.smartrecruiters.com/docs/authentication), [endpoints](https://developers.smartrecruiters.com/docs/endpoints) and [objects](https://developers.smartrecruiters.com/docs/objects) document public Posting API reads. No token or internal-posting scope is supplied. Detail links must match configured company and listing identity. The source-supplied application URL may use the documented `oga=true` view. |
| Remotive, Arbeitnow, Hacker News hiring | Existing bounded adapters retained | Existing source restrictions and durable pacing remain in force. No new live run was made. |
| Simplify Jobs | Manual URL/factual listing import | [Simplify terms](https://simplify.jobs/terms), updated August 19, 2026, require expressly authorized automated access and say technical accessibility is insufficient. No documented permitted job-seeker collection API or separate collection authorization was found. No board scraping, hidden endpoint probing, session access or bot bypass was implemented. |
| Workday | Manual import of reviewed employer posting URLs | Official [Workday job-posting setup considerations](https://doc.workday.com/admin-guide/en-us/human-capital-management/recruiting/job-postings/ayo1575554886570.html) describe tenant integrations, Core Connector, web services and RaaS. No general unauthenticated job-seeker collection permission was established. Undocumented career-site endpoints are not used. A future employer-authorized feed can use a separate reviewed adapter. |
| Company career pages | Manual URL and factual listing import | No unrestricted crawler or arbitrary server-side fetch. A company-specific permitted feed requires its own adapter/configuration. |

The employer-facing Simplify HR API at [help.simplify.hr](https://help.simplify.hr/reference/getting-started-1) is a different ATS/account integration. It does not establish job-seeker access to simplify.jobs and is not used.

The genuine SmartRecruiters check used the documented `smartrecruiters` public company identifier, limit one, and the production adapter. Both listing and detail requests returned HTTP 200; normalization succeeded with no rejected records. It transmitted no credential or candidate data and made no database write. Its sanitized receipt is outside Git at `~/Library/Application Support/Automated Apply/phase4-codex-evidence/smartrecruiters-public-read.json`. This proves one public feed/schema path, not exhaustive company coverage, India/startup suitability or an employer application workflow.

Company size remains separate observed evidence. A feed's employer name, job count, funding stage or description is never converted into headcount. Existing startup search supports role/technology/location/remote and 2–10/11–50 evidence filters; new job search uses those same size-resolution rules.

## Form compatibility matrix

| Destination | URL eligibility | Verified engineering behavior | Genuine site acceptance |
| --- | --- | --- | --- |
| Greenhouse | Recognizable board/job path | Shared engine with intercepted native controls; existing guarded browser suites | Not run |
| Lever/global and EU | Recognizable site/post path | Same engine; EU identity normalized; existing real React/browser suites | Not run |
| Ashby | Recognizable board/job/application path | Same engine; reviewed public-source destination | Not run |
| SmartRecruiters | Company/post path; exact `oga=true` permitted | Same engine; source/application identity agrees | Not run |
| Workday | Recognizable tenant applicant `/job/` path | Same engine on fictional native controls; dynamic/server-dependent widgets remain manual as needed | Not run |
| Taleo / Oracle Careers | Name recognition only; no dedicated vendor adapter | Generic dashboard inspection requires a separately approved exact public origin; no vendor workflow acceptance | Not run |
| Simplify Jobs | Manual discovery import only; form assistance rejected before DOM inspection | No collection authorization, dedicated adapter or applicant workflow verified | Not run |
| Generic HTML/React | Exact operator-approved public origin | Dashboard dedicated browser with pinned public DNS, or gesture-only extension native controls; separate command worker hands off | Not run |
| Google Forms | Recognizable forms path | Shared engine and existing MV3 fixture/native coverage | Not run |
| Complex/custom, login, sensitive, CAPTCHA, server-save steps | Manual handoff where unsupported | Explicit unsupported/needs-input states, no claimed fill | Not automated |

The seven-site matrix runs actual Chromium with a native-control fixture intercepted at seven URL shapes. It verifies empty-field filling, text/textarea/native select/radio/checkbox behavior, existing-value preservation, manual uploads/legal consent/self-identification, custom-widget disclosure, one-shot use and refresh invalidation with zero form POSTs. It does not reproduce an entire current vendor frontend, a physical extension toolbar gesture, login, a live Workday workflow, or a real employer's permission decision.

The inherited guarded dashboard browser engine additionally verifies safe custom dropdowns, explicit multi-step review, conditional/re-render handoff, cancellation, resume digest/file validation and restoration after process loss. Actual installed React isolated-world tests verify controlled-state event correctness. The MV3/native suite verifies worker restart, extension/browser reload and native-host failure/reconnect; that suite does not claim to read/fill live form fields. Extension widgets whose framework state cannot safely be updated remain manual.

Submission remains off and owner-operated. No genuine employer submission, mailbox modification, personal LinkedIn cookie/outreach or provider spend occurred. Apify/Apollo metadata/rights/budget gates are retained, without rotating accounts or authorizing collection from metadata alone.

The combined dashboard displays registry availability and adapter type without inferred “Verified” badges. Its vendor-name detector displays no supported controls until actual DOM inspection supplies per-field flags. Country, exact source seniority, publication age, supported company-size bands and approved numeric-experience fit are server filters applied before pagination. Optional salary/deadline refinements explicitly apply only to the displayed page; salary currencies are not converted or estimated.
