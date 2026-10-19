"""Validate a private input locally; write only via existing authenticated profile API on --apply."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.operations.configuration import (
    OperationRejected,
    load_settings,
    require_staging,
)
from backend.app.operations.onboarding import assess_profile, reject_placeholders
from backend.app.schemas.candidate_profile import CandidateProfileCreate


async def import_profile(client, data, expected_version):
    current = await client.get("/api/v1/profile")
    if current.status_code == 404:
        if expected_version != 0:
            raise OperationRejected("profile_version_conflict")
        headers = {}
    else:
        if current.status_code != 200:
            raise OperationRejected("profile_read_failed")
        if current.json().get("version") != expected_version:
            raise OperationRejected("profile_version_conflict")
        headers = {"If-Match": f'"{expected_version}"'}
    response = await client.put(
        "/api/v1/profile", json=data.model_dump(mode="json"), headers=headers
    )
    if response.status_code not in (200, 201):
        raise OperationRejected("profile_write_failed_or_version_conflict")
    # Full profile and connection details must not be printed.
    return {"status": "applied", "profile_version": response.json()["version"]}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--env-file")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--owner-confirmed", action="store_true")
    parser.add_argument("--expected-version", type=int)
    parser.add_argument("--base-url")
    parser.add_argument("--confirm-staging-target")
    args = parser.parse_args()
    try:
        if args.input.stat().st_size > 65536:
            raise OperationRejected("profile_input_too_large")
        data = CandidateProfileCreate.model_validate_json(args.input.read_bytes())
        reject_placeholders(data)
        if not args.apply:
            result = assess_profile(data).model_dump()
            result["mode"] = "dry_run_no_connections"
        else:
            settings = load_settings(args.env_file)
            require_staging(settings, args.confirm_staging_target)
            if (
                not args.owner_confirmed
                or args.expected_version is None
                or not settings.JOB_AGENT_API_TOKEN
            ):
                raise OperationRejected(
                    "owner_confirmation_version_and_api_token_required"
                )
            url = urlsplit(args.base_url or "")
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or url.path not in ("", "/")
                or url.query
                or url.fragment
                or url.hostname not in settings.API_ALLOWED_HOSTS
            ):
                raise OperationRejected("trusted_https_staging_api_required")
            async with httpx.AsyncClient(
                base_url=args.base_url,
                timeout=15,
                follow_redirects=False,
                headers={
                    "Authorization": "Bearer "
                    + settings.JOB_AGENT_API_TOKEN.get_secret_value()
                },
            ) as client:
                health = await client.get("/health")
                if (
                    health.status_code != 200
                    or health.json().get("environment") != "staging"
                ):
                    raise OperationRejected("staging_api_environment_mismatch")
                result = await import_profile(client, data, args.expected_version)
        print(json.dumps(result, indent=2))
        return 0
    except (ValidationError, json.JSONDecodeError):
        print(
            json.dumps(
                {"status": "blocked", "error": "invalid_profile_input_values_redacted"}
            )
        )
        return 2
    except OperationRejected as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}))
        return 2
    except Exception:
        print(json.dumps({"status": "failed", "error": "profile_import_unavailable"}))
        return 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
