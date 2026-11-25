"""Enrichment configuration from the private env file / process env (keys never logged)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

PROVIDERS = ("apollo", "apify", "signalhire")
DEFAULT_DAILY_CAPS = {"apollo": 10, "apify": 5, "signalhire": 5}
CAP_ENVS = {"apollo": "ENRICHMENT_APOLLO_DAILY_CAP", "apify": "ENRICHMENT_APIFY_DAILY_CAP",
            "signalhire": "ENRICHMENT_SIGNALHIRE_DAILY_CAP"}
KEY_ENVS = {"apollo": "APOLLO_API_KEY", "apify": "APIFY_API_TOKEN", "signalhire": "SIGNALHIRE_API_KEY"}
DEFAULT_APIFY_ACTOR = "vdrmota/contact-info-scraper"
MAX_DAILY_CAP = 100
TRUE = {"1", "true", "yes", "on"}


def _int(value: Any, default: int) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return min(max(number, 0), MAX_DAILY_CAP)


def _secret(env: Mapping[str, str], name: str) -> str | None:
    value = (env.get(name) or "").strip()
    return value or None


@dataclass(frozen=True)
class EnrichmentConfig:
    keys: dict[str, str | None] = field(default_factory=dict)
    caps: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_DAILY_CAPS))
    apify_actor: str = DEFAULT_APIFY_ACTOR
    fetch_pages: bool = True
    timeout_sec: float = 20.0
    disabled: bool = False
    timezone: str = "Asia/Kolkata"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> EnrichmentConfig:
        if env is None:
            from backend.app.ai_v2.router import load_env

            env = load_env()
        return cls(
            keys={name: _secret(env, KEY_ENVS[name]) for name in PROVIDERS},
            caps={name: _int(env.get(CAP_ENVS[name]), DEFAULT_DAILY_CAPS[name]) for name in PROVIDERS},
            apify_actor=(env.get("APIFY_CONTACT_ACTOR_ID") or DEFAULT_APIFY_ACTOR).strip(),
            fetch_pages=(env.get("ENRICHMENT_FETCH_CAREERS_PAGE") or "true").strip().lower() in TRUE,
            disabled=(env.get("ENRICHMENT_V2_DISABLED") or "").strip().lower() in TRUE,
        )

    def configured(self, provider: str) -> bool:
        return bool(self.keys.get(provider))

    def public(self) -> dict[str, Any]:
        """Config state for status endpoints: which env vars are set, never their values."""
        return {"disabled": self.disabled, "fetch_pages": self.fetch_pages,
                "providers": {name: {"configured": self.configured(name), "daily_cap": self.caps[name],
                                     "key_env": KEY_ENVS[name], "cap_env": CAP_ENVS[name]}
                              for name in PROVIDERS}}
