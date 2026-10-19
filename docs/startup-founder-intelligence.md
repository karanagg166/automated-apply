# Startup founder and professional intelligence

Use the existing owner-authenticated `POST /api/v1/discovery/people/search`. Review-only research is separate from account interaction and message delivery.

## Evidence priority and available paths

Prefer permission-confirmed official team/about evidence, then licensed official founder/company profiles, then authorized search-index results, then owner-confirmed professional URLs and cached observations. This phase does not introduce an HTML crawler. Official evidence can be entered as a bounded manual observation; Serper can search an operator-approved company domain without fetching result URLs.

An official observation uses `source=manual`, `permission_confirmed=true`, `company_name`, `company_domain`, and `official_people`. Each entry requires `full_name`, `role_title`, original `evidence_url`, `permission_evidence_url`, and actual `observed_at`. A stable individual `professional_url` helps reconcile identity across evidence sources. `human_confirmed=true` is an explicit owner identity/employer confirmation, not an automatic verification claim. Team-page URLs alone are not treated as a unique person's identity. Evidence must belong to the stated employer's exact domain or www hostname; unresolved employer associations remain review-required.

Official research via Serper uses `research_mode=official_company`, an approved `company_domain`, `allow_paid=true`, configured credentials, reviewed retention rights and a domain-specific permission evidence URL. Existing `PublicSearchAdapter` provides the single fixed-host search client. Parsed title/snippet candidates always require identity review. Results from other domains, including LinkedIn, are dropped in this mode. No result URL is fetched.

## LinkedIn restrictions

Reviewed on 2026-10-19: [LinkedIn User Agreement section 8.2](https://www.linkedin.com/legal/user-agreement) addresses unauthorized scraping and copying, security circumvention, indirect content use through search tools/data brokers, and account automation. [LinkedIn's software guidance](https://www.linkedin.com/help/linkedin/answer/a1341387/prohibited-software-and-extensions) reinforces those restrictions. [Serper's terms](https://serper.dev/terms) leave third-party content rights unresolved. A Serper key or Google index presence is insufficient authorization.

Professional profile search (`research_mode=public_profiles`, the legacy default) is blocked unless the operator separately verifies applicable rights, records permission evidence, and sets `LINKEDIN_SEARCH_RETENTION_AUTHORIZED=true`. Setting a flag does not create permission. Leave it false when consent or licensed retention cannot be established. Owner-supplied permitted URLs and independently sourced company/role evidence may be retained with review. A snippet never independently confirms identity or employment. No LinkedIn HTTP requests, cookies, passwords, private APIs, browser automation, messages or connection requests are implemented.

## Reconciliation, suppression and freshness

Official observations use existing `ContactIdentityResolver` and `ContactEvidence`. Authorized profile results also retain existing `DiscoveredPerson` records and reconcile their IDs into contacts. Source/profile identities are scoped to the employer; same-name professionals at different companies are never silently merged. Conflicting names/URLs remain review-required. Professional URL presence contributes no identity verification. No email is invented or inferred by this bridge, and business-email presence is separate from mailbox verification.

Identity confirmation and human corrections survive later unconfirmed observations. Suppressed contacts retain identity mappings and are excluded from recommendations. Stale evidence cannot become send-ready. Founder/technical-leader roles get a small-company relevance boost only when fresh size evidence supports it; recruiters and managers remain useful for larger employers. Hiring responsibility is not inferred from a leadership title. Existing enrichment and grounded outreach preparation remain opt-in; this phase never sends messages.

Read evidence through existing contact detail endpoints and read contacts through existing company recommendations. The startup MCP contact tool uses the same cached service and suppression rules. Ambiguous candidates are not counted as verified professional contact evidence in startup relevance scoring.

For configuration, retention, costs and troubleshooting, see [provider setup](discovery-provider-setup.md). For the complete offline flow, run `python backend/scripts/startup_discovery_demo.py`; all names, domains and observations in that demo are fictional.
