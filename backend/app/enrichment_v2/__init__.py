"""Phase 5 free-tier recruiter email enrichment (cost-protected 3-tier waterfall).

Tier 0: public.enrichment_cache by company domain (0 credits).
Tier 1: regex over the JD + the company's public careers/contact pages (0 credits).
Tier 2: Apollo -> Apify -> SignalHire, each skipped when unconfigured, on cooldown or
        at its daily free cap in public.enrichment_credits (reserved before the call).
Never fabricates or guesses an address: NO_EMAIL_FOUND is a normal outcome.
"""
