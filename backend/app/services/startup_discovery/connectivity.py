"""Owner-triggered public checks, durable source pacing and fresh truthful status."""

import asyncio
import hashlib
import json
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select

from backend.app.core.config import get_settings
from backend.app.models.discovery import now
from backend.app.models.startup import ProviderAccessWindow, ProviderConnectionCheck
from backend.app.schemas.discovery import (
    DiscoveryError,
    DiscoveryQuery,
    DiscoveryStatus,
)
from backend.app.services.discovery_budget import insert_for
from backend.app.services.job_sources.factory import JobSourceFactory
from backend.app.services.startup_discovery.normalizer import utc
from backend.app.services.startup_discovery.source_registry import (
    INTERVALS,
    PUBLIC_SOURCES,
    startup_sources,
)


async def claim_access(factory, source, *, clock=None):
    if source not in INTERVALS:
        raise ValueError("Only documented free public endpoints can be checked")
    async with factory() as session:
        instant = (
            clock()
            if clock
            else await session.scalar(select(func.clock_timestamp()))
            if session.bind.dialect.name == "postgresql"
            else now()
        )
        await reserve_access(session, source, instant)
        await session.commit()


async def reserve_access(session, source, instant):
    """Compose the same atomic quota claim into a caller's dispatch transaction."""
    if source not in INTERVALS:
        raise ValueError("Only documented free public endpoints can be checked")
    statement = insert_for(session)(ProviderAccessWindow).values(
        provider=source,
        next_allowed_at=instant + timedelta(seconds=INTERVALS[source]),
    )
    claimed = (
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[ProviderAccessWindow.provider],
                set_={
                    "next_allowed_at": instant + timedelta(seconds=INTERVALS[source])
                },
                where=ProviderAccessWindow.next_allowed_at <= instant,
            ).returning(ProviderAccessWindow.provider)
        )
    ).scalar_one_or_none()
    if claimed is None:
        raise DiscoveryError(
            DiscoveryStatus.RATE_LIMITED, "Source request interval has not elapsed"
        )


def configuration_fingerprint(provider, settings):
    configuration = {"provider": provider, "adapter_version": 1}
    if provider == "greenhouse":
        configuration["boards"] = settings.GREENHOUSE_BOARDS
    elif provider in {"lever", "ashby"}:
        configuration["boards"] = getattr(settings, provider.upper() + "_BOARDS")
        if provider == "lever":
            configuration["region"] = settings.LEVER_REGION
    return hashlib.sha256(
        json.dumps(configuration, sort_keys=True).encode()
    ).hexdigest()


def check_output(check):
    return dict(
        id=str(check.id),
        provider=check.provider,
        operation=check.operation,
        state=check.state,
        checked_at=utc(check.checked_at).isoformat(),
        finished_at=utc(check.finished_at).isoformat() if check.finished_at else None,
        http_status=check.http_status,
        result_count=check.result_count,
        schema_valid=check.schema_valid,
        is_live=check.is_live,
        evidence_urls=check.evidence_urls,
        error_category=check.error_category,
    )


class ProviderConnectivity:
    def __init__(self, session, factory, settings=None):
        self.session, self.factory = session, factory
        self.settings = settings or get_settings()

    async def status(self):
        result = []
        for source in startup_sources(self.settings):
            check = await self.session.scalar(
                select(ProviderConnectionCheck)
                .where(ProviderConnectionCheck.provider == source["provider"])
                .order_by(
                    ProviderConnectionCheck.checked_at.desc(),
                    ProviderConnectionCheck.id,
                )
                .limit(1)
            )
            state = (
                "unsupported"
                if source["availability"] == "unsupported"
                else "not_configured"
                if not source["configured"]
                else "authorization_required"
                if not source["authorized"]
                else "configured_not_tested"
            )
            fresh = bool(
                check
                and check.is_live
                and check.configuration_fingerprint
                == configuration_fingerprint(source["provider"], self.settings)
                and check.finished_at
                and utc(check.finished_at)
                >= now()
                - timedelta(hours=self.settings.PROVIDER_VERIFICATION_TTL_HOURS)
            )
            if (
                source["configured"]
                and source["authorized"]
                and check
                and check.is_live
            ):
                state = check.state
                if state == "live_verified" and not fresh:
                    state = "configured_not_tested"
                if state == "testing" and utc(check.checked_at) < now() - timedelta(
                    seconds=self.settings.DISCOVERY_TIMEOUT_SECONDS + 60
                ):
                    state = "failed"
            window = await self.session.get(ProviderAccessWindow, source["provider"])
            if (
                check
                and check.error_category == "local_rate_limit"
                and window
                and utc(window.next_allowed_at) > now()
            ):
                state = "rate_limited"
            result.append(
                {
                    **source,
                    "next_allowed_at": utc(window.next_allowed_at).isoformat()
                    if window
                    else None,
                    "state": state,
                    "live_verified": state == "live_verified" and fresh,
                    "verification_fresh": fresh,
                    "last_check": check_output(check) if check else None,
                }
            )
        return {
            "providers": result,
            "verification_ttl_hours": self.settings.PROVIDER_VERIFICATION_TTL_HOURS,
        }

    async def check(self, provider, adapter=None):
        source = next(
            (s for s in startup_sources(self.settings) if s["provider"] == provider),
            None,
        )
        if source is None:
            raise ValueError("Unknown startup provider")
        # Injected transports are always labeled mocked; a caller cannot request a live label.
        check_id = uuid4()
        async with self.factory() as audit:
            check = ProviderConnectionCheck(
                id=check_id,
                provider=provider,
                state="testing",
                is_live=adapter is None,
                configuration_fingerprint=configuration_fingerprint(
                    provider, self.settings
                ),
            )
            audit.add(check)
            await audit.commit()
        state, error, count, valid, status = "unsupported", None, None, None, None
        urls = []
        attempted = False
        try:
            if provider not in PUBLIC_SOURCES:
                state = (
                    "authorization_required"
                    if source["pricing"] == "paid"
                    else "unsupported"
                )
            elif not source["configured"]:
                state = "not_configured"
            else:
                await claim_access(self.factory, provider)
                attempted = True
                adapter = adapter or JobSourceFactory.get_adapter(
                    provider,
                    **(
                        {"settings": self.settings}
                        if provider in {"lever", "ashby"}
                        else {}
                    ),
                )
                async with asyncio.timeout(self.settings.DISCOVERY_TIMEOUT_SECONDS):
                    result = await adapter.discover(DiscoveryQuery(limit=1))
                status = getattr(adapter, "last_http_status", None)
                valid = (
                    result.status
                    in (DiscoveryStatus.SUCCESS, DiscoveryStatus.NO_RESULTS)
                    and not result.errors
                )
                count = len(result.jobs)
                urls = [j.original_url for j in result.jobs[:3]]
                state = (
                    "live_verified"
                    if valid
                    else "rate_limited"
                    if result.status == DiscoveryStatus.RATE_LIMITED
                    else "authorization_required"
                    if result.status == DiscoveryStatus.AUTH_REQUIRED
                    else "failed"
                )
                error = None if valid else str(result.status)
        except DiscoveryError as exc:
            state, error = (
                "rate_limited"
                if exc.status == DiscoveryStatus.RATE_LIMITED
                else "failed",
                "local_rate_limit"
                if not attempted and exc.status == DiscoveryStatus.RATE_LIMITED
                else str(exc.status),
            )
        except BaseException as exc:
            state, error = (
                "failed",
                "cancelled"
                if isinstance(exc, asyncio.CancelledError)
                else "timeout"
                if isinstance(exc, TimeoutError)
                else "provider_error",
            )
            if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                await asyncio.shield(
                    self.finish(
                        check_id, state, error, count, valid, status, urls, attempted
                    )
                )
                raise
        return await self.finish(
            check_id, state, error, count, valid, status, urls, attempted
        )

    async def finish(
        self, check_id, state, error, count, valid, status, urls, attempted
    ):
        async with self.factory() as audit:
            check = await audit.get(ProviderConnectionCheck, check_id)
            check.is_live = check.is_live and attempted
            check.state = (
                state
                if check.is_live or state != "live_verified"
                else "configured_not_tested"
            )
            (
                check.error_category,
                check.result_count,
                check.schema_valid,
                check.http_status,
            ) = error, count, valid, status
            check.evidence_urls = urls
            check.finished_at = now()
            await audit.commit()
            return check_output(check)
