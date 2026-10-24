"""Exactly one owner-authorized fictional invocation. Exclusive marker prevents repeats."""
import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', required=True)
    parser.add_argument('--attempt-id', choices=['initial', 'owner-approved-followup'], default='initial')
    parser.add_argument('--owner-authorized-one-fictional-request', action='store_true', required=True)
    args = parser.parse_args()
    from backend.app.ai.base import ProviderError
    from backend.app.ai.providers.agy import AgyProvider
    from backend.app.core.config import Settings
    name = 'agy-smoke.private.json' if args.attempt_id == 'initial' else 'agy-smoke-owner-approved-followup.private.json'
    output = ROOT / 'reports/phase1' / name
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as marker:
        output.chmod(0o600)
        marker.write(json.dumps({'state':'attempt_reserved','model':args.model,'retries':0}))
    config = Settings(_env_file=None, AGY_ENABLED=True, AGY_MODEL=args.model,
        AGY_EFFORT='high', AGY_QUOTA_AUTHORIZED=True, AGY_TIMEOUT_SECONDS=90)
    evidence = {'model':args.model,'effort':'high','invocations':1,'application_retries':0,
        'fictional_only':True,'timestamp':datetime.now(timezone.utc).isoformat(),
        'quota_entitlement':'not_exposed_by_cli','paid_overage_authorized':False}
    try:
        provider = AgyProvider(config)
        result = await provider.generate_structured_answer(
            'Describe a fictional Python software engineering skill for fictional Northstar Labs.',
            {'candidate_evidence':[{'id':'fictional-1','description':'Alex Example built a fictional Python service with unit tests.'}]},
            {'style_instruction':'concise','max_characters':500})
        evidence |= {'state':'structured_response_verified','result':result.model_dump(mode='json'), 'execution_metadata':provider.execution_metadata}
    except ProviderError as exc:
        evidence |= {'state':'failed_no_retry','error_code':exc.code, 'execution_metadata':provider.execution_metadata}
    output.write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps(evidence,indent=2))

if __name__ == '__main__':
    asyncio.run(main())
