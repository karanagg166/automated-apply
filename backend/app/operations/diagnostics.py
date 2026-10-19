"""Read-only summaries of persisted evidence; no OAuth refresh, provider call or reservation."""

from datetime import timedelta

from sqlalchemy import func, select

from backend.app.models.application_answer import LLMMonthlyUsage
from backend.app.models.company import Company
from backend.app.models.connected_account import ConnectedAccount
from backend.app.models.credit import ProviderUsageLog
from backend.app.models.discovery import DiscoveryRun, now
from backend.app.models.job import Job
from backend.app.models.startup import CompanySourceObservation
from backend.app.operations.onboarding import profile_readiness
from backend.app.operations.readiness import environment_readiness
from backend.app.services.startup_discovery.connectivity import ProviderConnectivity
from backend.app.services.startup_discovery.normalizer import utc


def paid_readiness(settings):
    results = []
    for name in ("apollo", "signalhire", "serper", "apify"):
        prefix = name.upper()
        configured = bool(
            getattr(
                settings, prefix + ("_API_TOKEN" if name == "apify" else "_API_KEY")
            )
        )
        monthly = getattr(
            settings,
            prefix + ("_MONTHLY_LIMIT_USD" if name == "apify" else "_MONTHLY_LIMIT"),
        )
        per_request = (
            settings.APIFY_PER_RUN_CAP_USD
            if name == "apify"
            else 1
            if name == "serper"
            else getattr(settings, prefix + "_CREDITS_PER_LOOKUP")
        )
        results.append(
            dict(
                provider=name,
                configured=configured,
                status="authorization_required"
                if configured
                else "requires_configuration",
                permission_status="unverified",
                account_authorization="unverified",
                pricing_review="unverified",
                supported_operations=["reviewed_actor_jobs"]
                if name == "apify"
                else ["public_professional_search"]
                if name == "serper"
                else ["professional_contact_enrichment"],
                monthly_budget=monthly,
                per_request_budget=per_request,
                budget_unit="USD_cap"
                if name == "apify"
                else "configured_credits_not_account_balance",
                paid_execution_enabled=False,
                explicit_call_approval_required=True,
                latest_successful_test=None,
                latest_failure=None,
            )
        )
    return results


async def gmail_readiness(session, settings):
    account = await session.scalar(
        select(ConnectedAccount).where(ConnectedAccount.provider == "gmail")
    )
    from backend.app.integrations.google_oauth import ALLOWED_SCOPE_SETS

    scopes_valid = bool(account and set(account.granted_scopes) in ALLOWED_SCOPE_SETS)
    identity_match = bool(
        account
        and settings.GMAIL_EXPECTED_EMAIL
        and account.account_email.casefold() == settings.GMAIL_EXPECTED_EMAIL.casefold()
    )
    encryption_usable = False
    if account and account.encrypted_refresh_token:
        from backend.app.integrations.token_store import TokenStore

        try:
            # Same purpose binding as the actual connection service; no refresh or network.
            TokenStore(settings).decrypt(
                account.encrypted_refresh_token, str(account.id) + ":refresh"
            )
            encryption_usable = True
        except ValueError:
            pass
    return dict(
        status=account.status if account else "not_connected",
        granted_scopes=account.granted_scopes if account else [],
        sender_identity_matches=identity_match,
        encryption_usable=encryption_usable,
        scopes_valid=scopes_valid,
        sending_enabled=settings.GMAIL_SENDING_ENABLED,
        reauthorization_required=bool(
            account
            and (
                account.status != "connected"
                or not identity_match
                or not encryption_usable
                or not scopes_valid
            )
        ),
        last_verified_at=utc(account.last_verified_at).isoformat()
        if account and account.last_verified_at
        else None,
        verification="persisted_evidence_only_no_live_identity_check",
        emails_sent=0,
    )


async def operational_status(session, factory, settings):
    result = {
        "configuration": environment_readiness(settings).model_dump(),
        "providers": await ProviderConnectivity(session, factory, settings).status(),
        "gmail": await gmail_readiness(session, settings),
        "paid_providers": paid_readiness(settings),
    }
    for provider in result["paid_providers"]:
        # Usage history is not a connectivity test; keep the distinction explicit.
        for successful, key in (
            (True, "latest_successful_request"),
            (False, "latest_failed_request"),
        ):
            record = await session.scalar(
                select(ProviderUsageLog)
                .where(
                    ProviderUsageLog.provider == provider["provider"],
                    ProviderUsageLog.is_success == successful,
                )
                .order_by(ProviderUsageLog.created_at.desc())
                .limit(1)
            )
            provider[key] = (
                {
                    "timestamp": utc(record.created_at).isoformat(),
                    "http_status": record.status_code,
                }
                if record
                else None
            )
    profile = await profile_readiness(session, live=settings.ENVIRONMENT != "testing")
    result["profile"] = profile.model_dump()
    result["metrics"] = {
        "jobs": await session.scalar(select(func.count()).select_from(Job)),
        "companies": await session.scalar(select(func.count()).select_from(Company)),
        "discovery_failures": await session.scalar(
            select(func.count())
            .select_from(DiscoveryRun)
            .where(DiscoveryRun.status.in_(["failed", "upstream_error", "cancelled"]))
        ),
        "provider_rate_limits": await session.scalar(
            select(func.count())
            .select_from(DiscoveryRun)
            .where(DiscoveryRun.status == "rate_limited")
        ),
        "stale_company_observations": await session.scalar(
            select(func.count())
            .select_from(CompanySourceObservation)
            .where(CompanySourceObservation.observed_at < now() - timedelta(days=180))
        ),
        "missing_profile": "candidate_profile" in profile.missing,
    }
    result["gemini_usage"] = [
        dict(
            month=r.month,
            requests=r.requests,
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
        )
        for r in (
            await session.scalars(
                select(LLMMonthlyUsage).order_by(LLMMonthlyUsage.month.desc()).limit(12)
            )
        ).all()
    ]
    result["migration_readiness"] = "requires_explicit_catalog_preflight"
    result["external_calls"] = 0
    return result
