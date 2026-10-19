"""Fictional company evidence only; never passed off as live provider results."""

from datetime import timedelta

from backend.app.models.discovery import now
from backend.app.services.startup_discovery.schemas import CompanyObservation


def observation(**changes):
    return CompanyObservation.model_validate(
        dict(
            name="Fictional Robotics",
            domain="fictional.example",
            source="manual",
            source_company_id="fixture-robotics",
            source_url="https://fictional.example/about",
            permission_evidence_url="https://fictional.example/permission",
            observed_at=now(),
            verification_status="source_reported",
            employee_count=18,
            location="Bengaluru, India",
            remote_policy="remote",
            technology_stack=["Python", "FastAPI"],
            stage="seed",
            **changes,
        )
    )


def observed(**changes):
    values = observation().model_dump()
    values.update(changes)
    if "employee_count" in changes and "team_size_band" not in changes:
        values["team_size_band"] = "unknown"
    return CompanyObservation.model_validate(values)


def old_observation():
    return observed(observed_at=now() - timedelta(days=365))
