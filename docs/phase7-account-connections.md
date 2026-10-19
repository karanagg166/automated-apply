# Account connection center

Connection pages read the existing integration registry, startup connectivity checks, contact-provider readiness and Gmail account service. A configuration flag is never a live verification claim. Tokens and passwords are not accepted in browser forms; operator credentials belong in private backend configuration.

| Provider | Supported operation | Configuration / permission | Live claim and cost boundary | Next action |
| --- | --- | --- | --- | --- |
| Gemini | Grounded application answers on explicit request | Server API key and reviewed model | Configured is not live verified; monthly request cap | Configure privately and separately authorize generation |
| Secondary Gmail | OAuth identity, local drafts, exact-content approved sending | Owner-selected secondary identity, correct scopes, encryption key ring; sending defaults disabled | Read actual account scopes/verification; preview and confirmation do not claim delivery | Complete official OAuth consent, verify identity, approve each draft and exact send |
| Serper | Permitted official-company professional research | Enabled key, rights/retention evidence, credit budget | Search may cost credits; never a LinkedIn scraper | Review permissions and approve each limited research run |
| Apollo | People search / permitted person enrichment | Key, enabled flag, reviewed provider rights and account-specific maximum lookup credits | Provider reported is not mailbox verified; local monthly and per-run caps | Review a one-person preview, cost, then separately approve execution |
| SignalHire | Identifier-based enrichment | Key, enabled flag, account-specific cost and permitted person identifier | Synchronous supported operations only; unknown outcomes retain reserved cost | Configure privately; preview one contact and approve cost |
| Apify | Only operator-reviewed licensed actors | Token, exact actor configuration, terms, USD caps | No paid execution from filter changes or connection page | Review actor rights and configure explicit account budget |
| Naukri | Packet preparation / Manual Handoff | No verified OAuth account-linking protocol | No portal login or automatic submission | Review packet, visit official site manually |
| Instahyre | Existing source capability / Manual Handoff | Source-dependent discovery; no new portal login | UI follows registry; submission not authorized or verified | Configure only an existing permitted source or hand off manually |
| Wellfound | Existing approved source / Manual Handoff | Licensed source configuration and consent | Directory access does not grant bulk collection rights | Review source permissions; never collect portal passwords |
| Greenhouse | Public board reads / Manual Handoff | Operator-selected public boards | Existing durable live-check evidence; minimum 60s source interval | Configure specific boards and run approved public discovery |
| LinkedIn | Retained permitted professional links for manual visiting | No login, cookies, scraping or website automation | No send/follow/connect automation; no second-account workaround | Open a permitted profile manually |
| Notifications | In-app updates | Explicit owner preferences | No external delivery worker started | Save opt-in, quiet hours, digest and pause preferences |

## Gmail routing

The BFF preserves the existing HttpOnly OAuth browser-binding cookie returned by `/integrations/gmail/connect/start`. The registered callback remains the existing FastAPI `/api/v1/integrations/gmail/oauth/callback`. In deployment, route this exact path to FastAPI on the same public hostname as the frontend. The backend must reconstruct the exact registered HTTPS URI through a trusted ingress. Different unrelated frontend/backend hostnames cannot share the browser-binding cookie and require further OAuth routing work; do not claim this setup connected.

Initially request identity/metadata consent for the designated secondary address. Sending authorization is a separate operation for the already established identity. Disconnect revokes via the existing service. A local draft is never represented as a Gmail draft. The send sequence is: grounded local draft → exact edit/revision → eligibility → approval → short-lived send preview → review sender/recipient/body → explicit exact send. The existing backend locks, hashes, limits and idempotency remain authoritative, including against MCP bypass. Unknown attempt outcomes require manual reconciliation, not retry.

## Verified execution status

No live Gmail, Gemini, Apollo, SignalHire, Serper or Apify operation was executed as part of Phase 7 implementation. No real portal login, application submission, paid lookup or outbound notification occurred. Runtime connection cards inspect the actual configured environment; isolated tests clear local credentials and block outbound provider HTTP. Actual owner credentials, account consent and live verification remain operator work.
