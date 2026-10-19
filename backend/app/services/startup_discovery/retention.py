"""Explicit owner maintenance; never called by discovery, API startup or a scheduler."""

from datetime import timedelta

from sqlalchemy import delete

from backend.app.models.discovery import DiscoveredPerson, now
from backend.app.models.startup import CompanySourceObservation, ProviderConnectionCheck


async def prune_startup_data(
    session, company_days=180, diagnostic_days=30, people_days=90
):
    if (
        not 1 <= company_days <= 3650
        or not 1 <= diagnostic_days <= 3650
        or not 1 <= people_days <= 3650
    ):
        raise ValueError("Retention periods must be between 1 and 3650 days")
    observations = await session.execute(
        delete(CompanySourceObservation).where(
            CompanySourceObservation.observed_at < now() - timedelta(days=company_days),
            CompanySourceObservation.verification_status != "human_confirmed",
        )
    )
    checks = await session.execute(
        delete(ProviderConnectionCheck).where(
            ProviderConnectionCheck.finished_at
            < now() - timedelta(days=diagnostic_days)
        )
    )
    people = await session.execute(
        delete(DiscoveredPerson).where(
            DiscoveredPerson.observed_at < now() - timedelta(days=people_days),
            DiscoveredPerson.source == "public_search",
            DiscoveredPerson.verification_status != "human_confirmed",
        )
    )
    # ContactIdentity's existing person FK becomes NULL; canonical contact and suppression survive.
    return {
        "company_snapshots_deleted": observations.rowcount,
        "diagnostics_deleted": checks.rowcount,
        "public_search_people_deleted": people.rowcount,
    }
