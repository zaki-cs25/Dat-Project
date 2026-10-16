"""Queue/input integrity independent of a running FHIR or model server."""
import copy
import json
from uuid import uuid4

import pytest

from central_park import benchmark_context as bench, care_jobs, care_context
from test_careplan import ctx, draft


@pytest.fixture
def job_store(monkeypatch):
    data = {}
    context = ctx()
    def read(kind, identifier, optional=False):
        result = data.get(kind + '/' + identifier)
        if result is None and not optional:
            raise ValueError('Resource missing')
        return copy.deepcopy(result)
    def put(resource):
        data[resource['resourceType'] + '/' + resource['id']] = copy.deepcopy(resource)
        return resource
    monkeypatch.setattr(care_jobs.fhir, 'read', read)
    monkeypatch.setattr(care_jobs.fhir, 'put', put)
    monkeypatch.setattr(care_jobs.fhir, 'linked', lambda *a: ({}, {}))
    monkeypatch.setattr(care_jobs.fhir, 'context', lambda *a: copy.deepcopy(context))
    return data, context


def test_generation_uses_frozen_context_and_options(monkeypatch, job_store):
    store, context = job_store
    options = {'mode': 'enriched', 'use_icmr_context': False}
    job = care_jobs.enqueue('p', 'q', 'a', options=options,
                            correlation={'run_id': 'run-1', 'case_id': 'HTN-01'})
    context['observations'].append({'id': 'later-fact'})
    seen = []
    monkeypatch.setattr(care_jobs, 'generate', lambda c: seen.append(c) or {
        **draft(), 'condition_ids': [], 'evidence_sources': [], 'result_status': 'completed'})
    care_jobs.process(store['Task/' + job['job_id']])
    assert seen[0]['observations'] == []
    assert seen[0]['care_options'] == options
    result = care_jobs.detail(job['job_id'])
    assert result['draft']['care_options'] == options
    events = care_jobs.metadata(store['Task/' + job['job_id']])['trace']
    assert events[0]['run_id'] == 'run-1' and events[0]['job_id'] == job['job_id']


def test_changed_model_does_not_execute_queued_job(monkeypatch, job_store):
    store, _ = job_store
    monkeypatch.setenv('CP_OPENAI_MODEL', 'model-A')
    job = care_jobs.enqueue('p', 'q', 'a')
    monkeypatch.setenv('CP_OPENAI_MODEL', 'model-B')
    monkeypatch.setattr(care_jobs, 'generate', lambda c: pytest.fail('Changed model must not run'))
    care_jobs.process(store['Task/' + job['job_id']])
    result = care_jobs.detail(job['job_id'])
    assert result['status'] == 'failed'
    assert 'configuration changed' in result['reason']


def test_frozen_context_tampering_rejected(monkeypatch, job_store):
    store, _ = job_store
    job = care_jobs.enqueue('p', 'q', 'a')
    task = store['Task/' + job['job_id']]
    data = care_jobs.metadata(task)
    data['frozen_context']['observations'] = [{'id': 'tampered'}]
    care_jobs.attach(task, data)
    monkeypatch.setattr(care_jobs, 'generate', lambda c: pytest.fail('Tampered input must not run'))
    care_jobs.process(task)
    assert 'hash mismatch' in care_jobs.detail(job['job_id'])['reason']


def test_paired_jobs_reuse_identical_assessment_with_different_context_options(job_store):
    store, _ = job_store
    first = care_jobs.enqueue('p', 'q', 'a', generation_id=uuid4(),
                             options={'mode': 'enriched', 'use_icmr_context': True})
    second = care_jobs.enqueue('p', 'q', 'a', generation_id=uuid4(),
                              options={'mode': 'enriched', 'use_icmr_context': False})
    assert first['job_id'] != second['job_id']
    a = care_jobs.metadata(store['Task/' + first['job_id']])
    b = care_jobs.metadata(store['Task/' + second['job_id']])
    assert a['context_sha256'] == b['context_sha256']
    assert a['assessment_id'] == b['assessment_id'] == 'a'


def test_same_generation_cannot_change_options(job_store):
    care_jobs.enqueue('p', 'q', 'a', options={'mode': 'grounded', 'use_icmr_context': True})
    with pytest.raises(ValueError, match='different care-generation options'):
        care_jobs.enqueue('p', 'q', 'a', options={'mode': 'enriched', 'use_icmr_context': True})


def test_actual_packet_audit_requires_inclusion():
    packet = {'narrative': 'Exact Unicode: सांस; newline\nend'}
    ctx_input = {'supplemental_clinical_context': packet, 'clinical_input_sha256': bench.digest(packet)}
    token = bench.EVENTS.set([])
    try:
        bench.audit_model_input('care.generation', {'context': ctx_input}, ctx_input)
        assert bench.EVENTS.get()[0]['packet_verified'] is True
        with pytest.raises(ValueError, match='omitted or changed'):
            bench.audit_model_input('care.review', {'context': {}}, ctx_input)
    finally:
        bench.EVENTS.reset(token)


def test_fixture_age_uses_pinned_reference_date():
    patient = {'birthDate': '1970-04-01', 'extension': [{
        'url': 'https://centralpark.example/fhir/StructureDefinition/benchmark-as-of-date',
        'valueDate': '2026-10-15'}]}
    assert care_context.age_years(patient) == 56
