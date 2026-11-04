"""Only the complete pinned worker migration is an accepted public catalog."""
import json
from copy import deepcopy

import pytest

from backend.app.local_agent.public_database import (
    BUNDLE,
    verified_catalog_version,
    verify_bundle,
)


def catalogs():
    manifest = verify_bundle()
    initial = json.loads((BUNDLE / 'catalog.json').read_text())
    compose = deepcopy(initial)
    previous, worker = manifest['followups']
    compose['constraints'][previous['constraint']] = previous['after']
    complete = deepcopy(compose)
    for change in worker['changes']:
        complete[change['section']][change['key']] = change['after']
    return manifest, initial, compose, complete


def test_accepts_original_compose_and_complete_worker_catalogs():
    manifest, initial, compose, complete = catalogs()
    followups = manifest['followups']
    assert verified_catalog_version(initial, initial, followups) == []
    assert verified_catalog_version(compose, initial, followups) == [followups[0]['file']]
    assert verified_catalog_version(complete, initial, followups) == [f['file'] for f in followups]


@pytest.mark.parametrize('index', range(11))
def test_rejects_every_partial_worker_constraint_or_function_update(index):
    manifest, initial, compose, complete = catalogs()
    change = manifest['followups'][-1]['changes'][index]
    complete[change['section']][change['key']] = compose[change['section']][change['key']]
    with pytest.raises(RuntimeError, match='public_catalog_drift_or_unsafe_grants'):
        verified_catalog_version(complete, initial, manifest['followups'])


def test_unrelated_catalog_drift_is_not_accepted_with_worker_update():
    manifest, initial, _, complete = catalogs()
    complete['constraints']['application_packets.application_packets_revision_check'] = 'CHECK (true)|true'
    with pytest.raises(RuntimeError, match='public_catalog_drift_or_unsafe_grants'):
        verified_catalog_version(complete, initial, manifest['followups'])
