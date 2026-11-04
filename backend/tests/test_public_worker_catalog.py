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


def test_restored_literal_array_casts_preserve_complete_check_and_partial_index():
    expected = {
        'constraints': {'packets.state': "CHECK (((state)::text = ANY ((ARRAY['created'::character varying, 'submitting'::character varying])::text[])))|true"},
        'indexes': {'one_active': "CREATE UNIQUE INDEX one_active ON tasks (source) WHERE ((state)::text = ANY ((ARRAY['queued'::character varying, 'running'::character varying])::text[]))"},
    }
    restored = {
        'constraints': {'packets.state': "CHECK (((state)::text = ANY (ARRAY[('created'::character varying)::text, ('submitting'::character varying)::text])))|true"},
        'indexes': {'one_active': "CREATE UNIQUE INDEX one_active ON tasks (source) WHERE ((state)::text = ANY (ARRAY[('queued'::character varying)::text, ('running'::character varying)::text]))"},
    }
    assert verified_catalog_version(restored, expected, []) == []
    restored['constraints']['packets.state'] = restored['constraints']['packets.state'].replace("'submitting'", "'unapproved'")
    with pytest.raises(RuntimeError, match='public_catalog_drift_or_unsafe_grants'):
        verified_catalog_version(restored, expected, [])


def test_restored_email_grouping_preserves_exact_length_and_regex_checks():
    expected = {'constraints': {'candidate_profiles.ck_candidate_email': "CHECK ((((length((email)::text) >= 3) AND (length((email)::text) <= 254)) AND ((email)::text ~ 'fixed_rule'::text)))|true"}}
    restored = {'constraints': {'candidate_profiles.ck_candidate_email': "CHECK (((length((email)::text) >= 3) AND (length((email)::text) <= 254) AND ((email)::text ~ 'fixed_rule'::text)))|true"}}
    assert verified_catalog_version(restored, expected, []) == []
    for changed in [restored['constraints']['candidate_profiles.ck_candidate_email'].replace('254', '255'), restored['constraints']['candidate_profiles.ck_candidate_email'].replace('fixed_rule', '.*')]:
        with pytest.raises(RuntimeError, match='public_catalog_drift_or_unsafe_grants'):
            verified_catalog_version({'constraints': {'candidate_profiles.ck_candidate_email': changed}}, expected, [])


def test_deparse_handling_never_normalizes_function_bodies_or_extra_predicates():
    base = {'constraints': {'state': "CHECK ((state = 'created'))|true"}, 'functions': {'guard()': 'protected body'}}
    for changed in [
        {**base, 'constraints': {'state': "CHECK ((state = 'created') OR true)|true"}},
        {**base, 'functions': {'guard()': 'different body'}},
    ]:
        with pytest.raises(RuntimeError, match='public_catalog_drift_or_unsafe_grants'):
            verified_catalog_version(changed, base, [])
