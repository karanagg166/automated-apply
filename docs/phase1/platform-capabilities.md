# Platform capabilities reviewed for Phase 1

No applicant platform is connected for submission. A credential, public listing API, browser session or user preference is not an employer's authorization to submit through an API.

| Connection | Phase 1 capability | Owner action / limits | Official evidence |
|---|---|---|---|
| Google Forms / employer forms | User-gesture URL preview only; no DOM answers collected | Review and apply manually; no upload or submit | [Chrome Native Messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging) |
| Naukri | Manual only; automatic_preferred saved as a preference | No verified authorized applicant submission API; terms page blocked automated research access; no bypass attempted | [Official site](https://www.naukri.com/), [terms](https://www.naukri.com/termsconditions) |
| Wellfound | Manual only | No authorized personal-account submission API verified; no scraping/login/session capture | [Talent terms](https://wellfound.com/terms), [jobs](https://wellfound.com/jobs) |
| Instahyre | Manual only | Applicant API unverified; official terms/privacy research could not be retrieved | [Official site](https://www.instahyre.com/) |
| YC Work at a Startup | Manual only | Applicant submission API unverified; use official application UI | [Official site](https://www.workatastartup.com/) |
| Internshala | Manual only | No authorized personal-account API verified | [Official terms](https://internshala.com/terms/), [jobs](https://internshala.com/jobs/) |
| LinkedIn | Manual only | No automated login, scraping, messaging or applications | [User Agreement](https://www.linkedin.com/legal/user-agreement) |
| Greenhouse | Existing public listing adapter retained | Public GETs differ from submission: POST requires an employer board API key; no submission authorized here | [Job Board API](https://docs.greenhouse.io/job-board.html) |
| Lever | Public postings documentation available; existing supported adapters retained | No live listing run or submission capability claimed | [Official Postings API](https://github.com/lever/postings-api) |
| Ashby | Public job postings API documented; capability reference only | No new live adapter or applicant submission authorization claimed | [Public Job Postings API](https://developers.ashbyhq.com/docs/public-job-posting-api) |
| Gmail | Existing encrypted OAuth identity/state/PKCE flow plus compose scope upgrade | Identity first, then owner compose consent. No real draft created or email sent. gmail.compose permits drafting and sending at Google's scope layer; our application keeps sends disabled. gmail.send is not requested for compose | [Draft creation authorization scopes](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.drafts/create) |
| Apollo / SignalHire | Existing cached-contact / enrichment adapters retained | Credentials don't verify entitlements. No enrichment requests or provider credits used. Cache remains first | [Apollo API docs](https://docs.apollo.io/), [SignalHire API](https://www.signalhire.com/api) |
| AGY | Authenticated CLI quota read verified with zero model turns; restricted adapter/local tests pass; structured generation unverified | Two separately authorized fictional attempts returned no valid answer (latest: gemini-3.8-flash-high, high, timeout). No attempt usage was reported; no further generation authorized | [Headless CLI](https://antigravity.google/docs/cli/headless/), [credit overage default](https://antigravity.google/docs/cli/reference/) |
| Ollama | Executable detection only | Service/model readiness not inferred. No model automatically installed | [Official docs](https://docs.ollama.com/) |
| Gemini / Cohere | Existing Gemini contract retained; Cohere unsupported pending free entitlement | No paid fallback or live provider call | [Gemini API](https://ai.google.dev/gemini-api/docs), [Cohere](https://docs.cohere.com/) |

Discovery scheduling remains deployment-disabled. Existing matching, durable leases, quotas, idempotency, saved presets and evidence-based 2–10 employee filtering are retained. The new saved search preferences validate and persist title, skills, location, work arrangement, employment types, experience/salary bounds, categories/stages, employee bounds, source, recency, relevance, applied status, saved-only and blocked companies. Saving never executes discovery or fills missing properties. Future execution must explicitly map these preferences to supported adapter/filter capabilities.
