"""Portal adapter registry and pasted-URL -> external_job_id parsing."""

from __future__ import annotations

from typing import Any

from backend.app.browser_v2.adapters.base import PortalAdapter
from backend.app.browser_v2.adapters.naukri import NaukriAdapter, external_job_id


def default_adapters(*, otp_provider: Any = None, security_code_provider: Any = None) -> dict[str, PortalAdapter]:
    """All Phase 6A adapters + the Milestone 2 Ashby applier (each portal still runs only when enabled
    in portal_rules). `security_code_provider` lets hosted Greenhouse forms read their post-submit
    email security code (read-only mail)."""
    from backend.app.browser_v2.adapters.ashby import AshbyAdapter
    from backend.app.browser_v2.adapters.greenhouse import GreenhouseAdapter
    from backend.app.browser_v2.adapters.himalayas import HimalayasAdapter
    from backend.app.browser_v2.adapters.hiringcafe import HiringCafeAdapter
    from backend.app.browser_v2.adapters.instahyre import InstahyreAdapter
    from backend.app.browser_v2.adapters.internshala import InternshalaAdapter
    from backend.app.browser_v2.adapters.lever import LeverAdapter
    from backend.app.browser_v2.adapters.public_sources import (
        ArbeitnowAdapter,
        HackerNewsAdapter,
        RemotiveAdapter,
        SmartRecruitersAdapter,
    )
    from backend.app.browser_v2.adapters.we_work_remotely import WeWorkRemotelyAdapter
    from backend.app.browser_v2.adapters.wellfound import WellfoundAdapter
    from backend.app.browser_v2.adapters.work_at_a_startup import WorkAtAStartupAdapter

    adapters: list[Any] = [
        NaukriAdapter(otp_provider=otp_provider), GreenhouseAdapter(), LeverAdapter(), HimalayasAdapter(),
        WeWorkRemotelyAdapter(), HiringCafeAdapter(), InstahyreAdapter(), InternshalaAdapter(), WellfoundAdapter(),
        WorkAtAStartupAdapter(), AshbyAdapter(), SmartRecruitersAdapter(), RemotiveAdapter(), ArbeitnowAdapter(),
        HackerNewsAdapter()]
    for adapter in adapters:
        applier = getattr(adapter, "applier", None)
        if applier is not None and security_code_provider is not None:
            applier.security_code_provider = security_code_provider
    return {adapter.platform: adapter for adapter in adapters}


def job_id_from_url(platform: str, url: str) -> str | None:
    """Stable external_job_id for a pasted job URL (CLI/MCP test-apply)."""
    import re
    from urllib.parse import urlsplit

    from backend.app.browser_v2.adapters.common import InteractivePortalAdapter

    parts = urlsplit(url)
    if parts.scheme != "https":
        return None
    segments = [s for s in parts.path.split("/") if s]
    if platform == "naukri":
        return external_job_id(url)
    if platform == "greenhouse":
        if len(segments) >= 3 and segments[1] == "jobs" and segments[2].isdigit():
            return segments[2]
        # Live 2026-11-26: custom career sites (stripe.com/jobs/search?gh_jid=<id>) and the
        # hosted embed form (job-boards.greenhouse.io/embed/job_app?for=<board>&token=<id>).
        from urllib.parse import parse_qs

        query = parse_qs(parts.query)
        candidate = (query.get("gh_jid") or (query.get("token") if "embed/job_app" in parts.path else None)
                     or [""])[0]
        return candidate if re.fullmatch(r"\d{1,20}", candidate) else None
    if platform == "lever":
        return segments[1] if len(segments) >= 2 and re.fullmatch(r"[0-9a-f-]{8,64}", segments[1]) else None
    if platform == "we_work_remotely":
        return segments[1] if len(segments) == 2 and segments[0] == "remote-jobs" else None
    if platform == "hacker_news":
        from urllib.parse import parse_qs as _qs

        item = (_qs(parts.query).get("id") or [""])[0]
        return item if parts.hostname == "news.ycombinator.com" and item.isdigit() else None
    if platform == "ashby":
        return segments[1] if parts.hostname == "jobs.ashbyhq.com" and len(segments) >= 2 and re.fullmatch(
            r"[0-9a-f-]{8,64}", segments[1]) else None
    if platform == "himalayas":
        from backend.app.browser_v2.adapters.himalayas import job_id

        return job_id(url, None, None) if "/jobs/" in parts.path else None
    adapters = default_adapters()
    adapter = adapters.get(platform)
    if isinstance(adapter, InteractivePortalAdapter):
        match = re.match(adapter.config.job_path, parts.path)
        return match.group(1) if match else None
    return None
