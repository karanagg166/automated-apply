"""Explicit API composition; route implementations stay in domain modules."""


def install_routes(app):
    from backend.app.agent.router import router as agent_command_router
    from backend.app.api.v1.application_answers import (
        router as application_answers_router,
    )
    from backend.app.api.v1.applications import router as applications_router
    from backend.app.api.v1.automation_v2 import router as automation_v2_router
    from backend.app.api.v1.contact_enrichment import (
        router as contact_enrichment_router,
    )
    from backend.app.api.v1.discovery import router as discovery_router
    from backend.app.api.v1.integrations import router as integrations_router
    from backend.app.api.v1.outreach import router as outreach_router
    from backend.app.api.v1.profile import router as profile_router
    from backend.app.api.v1.provider_research import router as provider_research_router
    from backend.app.api.v1.saved import router as saved_router
    from backend.app.api.v1.startups import router as startups_router
    from backend.app.automation.router import router as automation_router
    from backend.app.browser.router import assistant_router
    from backend.app.browser.router import router as browser_router
    from backend.app.dashboard.router import router as dashboard_router
    from backend.app.execution.router import router as execution_router
    from backend.app.local_agent.router import router as local_agent_router
    from backend.app.resume_sync.router import router as resume_sync_router

    for router in (
        profile_router,
        dashboard_router,
        resume_sync_router,
        automation_router,
        automation_v2_router,
        local_agent_router,
        agent_command_router,
        application_answers_router,
        applications_router,
        discovery_router,
        contact_enrichment_router,
        integrations_router,
        outreach_router,
        startups_router,
        browser_router,
        assistant_router,
        provider_research_router,
        execution_router,
        # Static discovery paths (notably /jobs/search) precede /jobs/{job_id}.
        saved_router,
    ):
        app.include_router(router)
