"""Opt-in, bounded fictional-evidence model evaluation through existing provider and usage manager."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.core.config import configure_operator
from backend.app.operations.configuration import (
    OperationRejected,
    load_settings,
    require_staging,
)
from backend.app.operations.reports import execution_metadata, write_report


async def evaluate(manager, provider):
    from backend.app.ai.base import ProviderError
    from backend.app.ai.validation import validate_grounding

    evidence = [
        {
            "reference": {
                "source_type": "verified_project",
                "source_id": "fictional-model-probe",
            },
            "facts": {
                "contribution": "I implemented authentication using Python and FastAPI."
            },
        }
    ]
    try:
        response = await manager.generate(
            provider,
            "Describe your Python contribution",
            {"evidence": evidence},
            {
                "style_instruction": "Professional first person; use only supplied fictional facts.",
                "max_characters": 400,
                "max_words": 70,
            },
        )
        failure = validate_grounding(response.content, evidence, 400, 70)
        return dict(
            status="grounding_checks_failed"
            if failure
            else "schema_and_grounding_checks_passed",
            error_code=failure,
            usage=response.usage.model_dump(),
            human_quality_review="required",
            factual_accuracy_proven=False,
            personal_data_sent=False,
            response_body_persisted=False,
        )
    except ProviderError as exc:
        return dict(
            status="provider_failed", error_code=exc.code, personal_data_sent=False
        )


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file")
    parser.add_argument("--confirm-staging-target")
    parser.add_argument("--authorize-live-gemini", action="store_true")
    parser.add_argument("--output", default="reports/gemini")
    args = parser.parse_args()
    settings = load_settings(args.env_file)
    require_staging(settings, args.confirm_staging_target)
    if (
        not args.authorize_live_gemini
        or not settings.GEMINI_API_KEY
        or not settings.LLM_MODEL
    ):
        raise OperationRejected(
            "valid_credentials_and_explicit_potentially_billable_gemini_authorization_required"
        )
    # At most two reservations including an existing-manager retry. Does not reset usage.
    bounded = settings.model_copy(
        update={
            "LLM_MAX_OUTPUT_TOKENS": min(256, settings.LLM_MAX_OUTPUT_TOKENS),
            "LLM_MONTHLY_MAX_REQUESTS": min(2, settings.LLM_MONTHLY_MAX_REQUESTS),
            "LLM_MAX_CONCURRENCY": 1,
        }
    )
    configure_operator(bounded)
    from backend.app.ai.provider_factory import create_provider
    from backend.app.ai.usage import LLMUsageManager
    from backend.app.db.session import close_db_engine, get_session_factory
    from backend.app.operations.migrations import inspect_database
    from backend.app.operations.network import NetworkAudit

    if (await inspect_database(settings)).status != "verified":
        raise OperationRejected("migration_preflight_required")
    try:
        with NetworkAudit({"generativelanguage.googleapis.com"}) as network:
            result = await evaluate(
                LLMUsageManager(get_session_factory(), bounded),
                create_provider(bounded),
            )
        report = {
            **execution_metadata("explicit_fictional_gemini_probe", "staging"),
            **result,
            **network.output(),
            "maximum_requests_including_retries": 2,
            "maximum_output_tokens_per_request": bounded.LLM_MAX_OUTPUT_TOKENS,
        }
        write_report(args.output, report)
        print(json.dumps(report, indent=2))
        return 0 if result["status"] == "schema_and_grounding_checks_passed" else 2
    finally:
        await close_db_engine()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except OperationRejected as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}))
        raise SystemExit(2)
    except Exception:
        print(
            json.dumps(
                {"status": "failed", "error": "model_evaluation_failed_values_redacted"}
            )
        )
        raise SystemExit(3)
