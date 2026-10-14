"""Tests for FastAPI HTTP endpoints."""

import pytest


@pytest.mark.asyncio
async def test_health_endpoint(async_client):
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "job-pulse-agent-api"
    assert data["schema"] == "job_agent"
    assert "X-Process-Time" in response.headers


@pytest.mark.asyncio
async def test_ready_endpoint(async_client):
    response = await async_client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["database"] == "connected"


@pytest.mark.asyncio
async def test_credits_status_endpoint(async_client):
    response = await async_client.get("/api/v1/credits/status")
    assert response.status_code == 200
    data = response.json()
    assert "providers" in data
    assert "total_credits_remaining" in data


@pytest.mark.asyncio
async def test_jobs_list_endpoint(async_client):
    response = await async_client.get("/api/v1/jobs")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
