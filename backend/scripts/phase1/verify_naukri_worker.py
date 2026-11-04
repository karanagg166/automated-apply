"""Exercise the real public SQL constraints on a disposable loopback database.

Bootstrap a fresh cluster with verify_public.py first. No online configuration,
credentials, provider requests or real candidate data are accepted here.
"""
import argparse
import asyncio
import hashlib
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


async def verify(url, pin_catalog=False):
    target = urlsplit(url)
    if (target.hostname != '127.0.0.1' or target.username != 'postgres'
            or not re.fullmatch(r'/candidate_profile_test(?:_worker[0-9]+)?', target.path) or target.query
            or target.port in {None, 5432, 54322} or target.password):
        raise ValueError('disposable_loopback_postgresql_required')
    import asyncpg
    from cryptography.fernet import Fernet
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.app.core.config import Settings, configure_operator
    key = Fernet.generate_key()
    config = Settings(_env_file=None, ENVIRONMENT='testing', DATABASE_SCHEMA='public',
                      DATABASE_URL=url.replace('postgresql://postgres@', 'postgresql+asyncpg://postgres:fictional_fixture_only@', 1),
                      DB_REQUIRE_TLS=False, RESUME_ENCRYPTION_KEY=key.decode(),
                      COHERE_ENABLED=False, GEMINI_ENABLED=False, OLLAMA_ENABLED=False,
                      GMAIL_LOCAL_ACCOUNTS_ENABLED=False, GMAIL_SENDING_ENABLED=False)
    configure_operator(config)
    from backend.app.dashboard.models import OwnerPreference, PrivateResume
    from backend.app.execution import application_queue as queue
    from backend.app.execution import naukri_submission as submission
    from backend.app.local_agent.profile_confirmation import confirm_profile
    from backend.app.local_agent.public_database import BUNDLE, verify_public_database
    from backend.app.models.application_answer import CandidateResource
    from backend.app.models.application_packet import ApplicationPacket
    from backend.app.operations.migrations import catalog
    from backend.app.repositories.candidate_profile import CandidateProfileRepository
    from backend.app.schemas.candidate_profile import CandidateProfileCreate
    from backend.tests.test_naukri_submission import (
        admit,
        apply_ready,
        finish,
        history_ready,
        observation,
    )
    admin = await asyncpg.connect(url)
    engine = create_async_engine(config.DATABASE_URL, hide_parameters=True,
        pool_size=1, max_overflow=0,
        connect_args={'server_settings': {'search_path': 'public', 'role': 'job_agent_runtime'}})
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    import backend.app.db.session as session_module
    session_module._engine, session_module._session_factory = engine, factory
    results = []
    try:
        assert not await admin.fetchval('SELECT count(*) FROM public.candidate_profiles')
        if 'compose' not in await admin.fetchval("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='oauth_states_authorization_mode_check'"):
            await admin.execute((BUNDLE / 'followups/002_gmail_compose.sql').read_text())
        raw = b'%PDF-1.4\nFictional public-schema Naukri worker regression\n%%EOF'
        async with factory() as session:
            profile = await CandidateProfileRepository(session).create_primary_profile(CandidateProfileCreate(
                full_name='Alex Fictional', email='alex@example.com', verified_experience_years=2,
                verified_skills=['Python'], summary='Verified fictional summary',
                preferences={'target_titles': ['Backend Developer'], 'preferred_locations': ['India']},
            ))
            private_id = uuid4()
            resource = CandidateResource(id=uuid4(), candidate_profile_id=profile.id, resource_type='resume',
                label='Fictional canonical PDF', source_type='private_upload', user_confirmed=True,
                is_primary=True, url='private-resume:' + str(private_id))
            session.add(resource)
            await session.flush()
            private = PrivateResume(id=private_id, label='Fictional canonical PDF', resource_id=resource.id,
                confirmed=True, ciphertext=Fernet(key).encrypt(raw), sha256=hashlib.sha256(raw).hexdigest())
            session.add(private)
            resource.url = 'private-resume:' + str(private.id)
            await confirm_profile(session, profile, profile.version)
            await session.commit()
            case = SimpleNamespace(key=key, private=private, settings=config, raw=raw)
            context, item, work = await apply_ready(session, case)
            packet_id = (await queue.load(session, item['id'])).value['packet_id']
            try:
                await admit(session, case, context, work)
            except DBAPIError as exc:
                assert getattr(exc.orig, 'sqlstate', None) == '23514'
                await session.rollback()
                results.append('original_public_schema_rejects_apply_state_23514')
            else:
                raise AssertionError('original_schema_failure_not_reproduced')
            current = (await queue.load(session, item['id'])).value
            assert not current['admitted_actions']
            await session.rollback()
            before = await catalog(admin, 'public')
            await admin.execute((BUNDLE / 'followups/003_naukri_worker.sql').read_text())
            after = await catalog(admin, 'public')
            manifest_path = BUNDLE / 'manifest.json'
            manifest = json.loads(manifest_path.read_text())
            followup = manifest['followups'][-1]
            allowed = {(c['section'], c['key']) for c in followup['changes']}
            actual_changes = {(section, k) for section in before for k in set(before[section]) | set(after[section])
                              if before[section].get(k) != after[section].get(k)}
            assert actual_changes == allowed, actual_changes ^ allowed
            for change in followup['changes']:
                assert change['before'] == before[change['section']][change['key']]
                actual = after[change['section']][change['key']]
                if pin_catalog:
                    change['after'] = actual
                else:
                    assert change['after'] == actual
            if pin_catalog:
                manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
            async with admin.transaction():
                await admin.execute('SET LOCAL ROLE job_agent_runtime')
                verified = await verify_public_database(admin, config)
                assert verified['verified_followups'] == [f['file'] for f in manifest['followups']]
            results.append('only_eight_constraints_three_functions_change_catalog_and_security_verified')
            await admin.execute((BUNDLE / 'followups/003_naukri_worker.rollback.sql').read_text())
            assert await catalog(admin, 'public') == before
            await admin.execute((BUNDLE / 'followups/003_naukri_worker.sql').read_text())
            assert await catalog(admin, 'public') == after
            results.append('empty_worker_history_allows_exact_catalog_rollback_and_reapply')
            work = await admit(session, case, context, work)
            packet = await session.get(ApplicationPacket, __import__('uuid').UUID(packet_id), populate_existing=True)
            assert packet.lifecycle_state == 'submitting'
            assert len((await queue.load(session, item['id'])).value['admitted_actions']) == 1
            results.append('durable_apply_and_packet_commit_before_any_browser_action')
            await finish(session, case, context, work,
                observation(work, 'CLICKED', document_id=work['execution']['document_id']))
            for _ in range(2):
                history = await history_ready(session, case, context)
                await finish(session, case, context, history,
                    observation(history, 'APPLICATION_SENT', title='Backend Developer', company='Fictional Labs'))
            value = (await queue.load(session, item['id'])).value
            assert value['stage'] == 'SUBMITTED_CONFIRMED' and len(value['admitted_actions']) == 1
            receipt = await session.get(OwnerPreference, submission.RECEIPT_PREFIX + value['requisition'])
            assert receipt and receipt.value['persistent_after_reload']
            results.append('two_document_receipt_evidence_and_verified_packet_commit_under_public_guards')
            await session.rollback()
        async with factory() as reader:
            packet = await reader.get(ApplicationPacket, __import__('uuid').UUID(packet_id))
            assert packet.lifecycle_state == 'provider_confirmed_submitted'
            results.append('new_connection_persists_canonical_verified_outcome')
            await reader.rollback()
            for column, value in [('lifecycle_state', 'created'), ('snapshot', '{}')]:
                try:
                    await reader.execute(text(f'UPDATE public.application_packets SET {column}=:value WHERE id=:id'),
                                         {'value': value, 'id': packet_id})
                    await reader.commit()
                except DBAPIError:
                    await reader.rollback()
                else:
                    raise AssertionError('verified_history_mutation_accepted')
            results.append('verified_history_and_content_cannot_be_reopened_or_erased')
        try:
            await admin.execute((BUNDLE / 'followups/003_naukri_worker.rollback.sql').read_text())
        except asyncpg.RaiseError:
            await admin.execute('ROLLBACK')
            results.append('worker_history_blocks_rollback_without_erasing_evidence')
        else:
            raise AssertionError('rollback_erased_worker_history')
        try:
            await admin.execute((BUNDLE / 'followups/003_naukri_worker.sql').read_text())
        except asyncpg.RaiseError:
            await admin.execute('ROLLBACK')
            results.append('migration_replay_rejected')
        else:
            raise AssertionError('migration_replay_accepted')
        print(json.dumps({'fixture_only': True, 'public_sql_bootstrap': True, 'cases_passed': len(results),
                          'provider_requests': 0, 'real_applications': 0, 'remote_ddl': False, 'results': results}))
    finally:
        await engine.dispose()
        await admin.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--pin-catalog', action='store_true')
    args = parser.parse_args()
    asyncio.run(verify(args.url, args.pin_catalog))
