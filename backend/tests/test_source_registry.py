import pytest
from backend.app.services.job_sources.registry import (
    source_registry,
    UnknownSourceError,
)
from backend.app.services.job_sources.factory import JobSourceFactory
from backend.app.schemas.discovery import DiscoveryQuery
from backend.tests.discovery_fakes import settings, actor_config


@pytest.mark.parametrize(
    "source", ["naukri", "instahyre", "wellfound", "work_at_a_startup"]
)
def test_explicit_factory_identity(source):
    adapter = JobSourceFactory.get_adapter(source)
    assert adapter.source_name == source
    assert adapter.get_capabilities()["mutations"] == []


def test_unknown_source_typed_error():
    with pytest.raises(UnknownSourceError):
        JobSourceFactory.get_adapter("naukrii")


def test_status_is_configuration_not_live_verification():
    sources = source_registry(settings(APIFY_SOURCES={"instahyre": actor_config()}))
    assert sources["instahyre"].enabled
    assert sources["instahyre"].availability == "available"
    assert sources["instahyre"].live_verified is False
    assert not sources["naukri"].enabled
    assert sources["internshala"].availability == "manual_import_only"
    assert sources["linkedin"].availability == "authorization_required"
    assert all(s.read_only and not s.mutation_capabilities for s in sources.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["internshala", "linkedin", "apify"])
async def test_unavailable_never_calls_provider(source):
    result = await JobSourceFactory.get_adapter(source).discover(DiscoveryQuery())
    assert not result.jobs
    assert result.status in (
        "manual_input_required",
        "unsupported_operation",
        "authentication_required",
    )
