"""Durable interview-completion API tests with an in-memory FHIR store."""
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

from central_park import benchmark_context as bench, care_jobs, interview_completion, main
from central_park.patients import RegistrationConflictError


SUBMISSION = UUID('12345678-1234-5678-1234-567812345678')


def packet(narrative='A supplemental clinical note.'):
    return {'patient': {'age': 42, 'sex': 'woman'},
            'established_conditions': ['hypertension'], 'medications': [], 'allergies': [],
            'observations': [], 'narrative': narrative, 'missing_information': [],
            'request': 'Create a clinician-facing follow-up draft.'}


@pytest.fixture
def fhir_store(monkeypatch):
    store = {}
    store['Patient/p'] = {'resourceType': 'Patient', 'id': 'p', 'gender': 'female', 'birthDate': '1984-01-01'}

    def read(kind, identifier, optional=False):
        value = store.get(kind + '/' + identifier)
        if value is None and not optional:
            raise KeyError(kind + '/' + identifier)
        return deepcopy(value) if value is not None else None

    def put(resource):
        store[resource['resourceType'] + '/' + resource['id']] = deepcopy(resource)
        return resource

    monkeypatch.setattr(interview_completion.fhir, 'read', read)
    monkeypatch.setattr(interview_completion.fhir, 'put', put)
    monkeypatch.setattr(interview_completion.fhir, 'age_years', lambda _patient: 42)
    return store


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(main, 'load', lambda: SimpleNamespace(
        care_generation_mode='grounded', benchmark_api_enabled=False))


def request(*, submission_id=SUBMISSION, context=None, options=None, correlation=None):
    return main.InterviewCompletionRequest(
        submission_id=submission_id, patient_id='p',
        transcript=[{'link_id': 'chief-complaint', 'question': 'What brings you in?', 'answer': 'Mild headache.'}],
        supplemental_clinical_context=context,
        care_options=options or {'mode': 'enriched', 'use_icmr_context': False},
        correlation=correlation or {'run_id': 'run-17', 'case_id': 'case-a'})


def completed_result(*_args):
    return {'triage_level': 'see-gp', 'chief_complaint': 'Mild headache.',
            'red_flags': [], 'recommended_actions': [], 'citations': [],
            'questionnaire_response_id': 'unused', 'service_request_id': 'assessment-1'}


def test_repeated_completion_uuid_reuses_assessment_through_main_endpoint(
        monkeypatch, fhir_store, configured):
    calls = {'assessment': 0, 'enqueue': 0}

    def assess(*args):
        calls['assessment'] += 1
        return completed_result()

    def enqueue(*args, **kwargs):
        calls['enqueue'] += 1
        return {'job_id': 'job-1', 'status': 'queued'}

    monkeypatch.setattr(interview_completion, 'run_interview', assess)
    monkeypatch.setattr(care_jobs, 'enqueue', enqueue)
    req = request(context=packet())
    first = main.complete_interview(req)
    second = main.complete_interview(req)
    assert calls == {'assessment': 1, 'enqueue': 2}
    assert first['service_request_id'] == second['service_request_id'] == 'assessment-1'
    assert first['clinical_input_sha256'] == bench.digest(packet())
    assert first['care_plan_job_id'] == second['care_plan_job_id'] == 'job-1'


@pytest.mark.parametrize('change', ['packet', 'options'])
def test_reused_uuid_rejects_changed_packet_or_options(monkeypatch, fhir_store, configured, change):
    monkeypatch.setattr(interview_completion, 'run_interview', completed_result)
    monkeypatch.setattr(care_jobs, 'enqueue', lambda *args, **kwargs: {'job_id': 'job-1', 'status': 'queued'})
    first = request(context=packet())
    main.complete_interview(first)
    if change == 'packet':
        second = request(context=packet('Changed packet with different clinical content.'))
    else:
        second = request(context=packet(), options={'mode': 'grounded', 'use_icmr_context': False})
    with pytest.raises(HTTPException) as error:
        main.complete_interview(second)
    assert error.value.status_code == 409


def test_lost_enqueue_response_retry_uses_cached_assessment(monkeypatch, fhir_store, configured):
    calls = {'assessment': 0, 'enqueue': 0}

    def assess(*args):
        calls['assessment'] += 1
        return completed_result()

    def enqueue(*args, **kwargs):
        calls['enqueue'] += 1
        if calls['enqueue'] == 1:
            # Model the server committing the task before its response is lost.
            raise TimeoutError('response lost after enqueue commit')
        return {'job_id': 'job-1', 'status': 'queued'}

    monkeypatch.setattr(interview_completion, 'run_interview', assess)
    monkeypatch.setattr(care_jobs, 'enqueue', enqueue)
    monkeypatch.setattr(care_jobs, 'record_enqueue_failure', lambda *_args: None)
    req = request(context=packet())
    first = main.complete_interview(req)
    second = main.complete_interview(req)
    assert first['care_plan_status'] == 'unqueued'
    assert second['care_plan_status'] == 'queued'
    assert calls == {'assessment': 1, 'enqueue': 2}


def test_questionnaire_response_stores_exact_packet_and_canonical_hash(
        monkeypatch, fhir_store, configured):
    monkeypatch.setattr(interview_completion, 'run_interview', completed_result)
    monkeypatch.setattr(care_jobs, 'enqueue', lambda *args, **kwargs: {'job_id': 'job-1', 'status': 'queued'})
    clinical = packet('Exact Unicode note: Patient says “dizzy” — no other details.')
    main.complete_interview(request(context=clinical))
    qr_id = 'qr-' + SUBMISSION.hex
    stored = fhir_store['QuestionnaireResponse/' + qr_id]
    assert stored['item'][0]['answer'][0]['valueString'] == 'Mild headache.'
    assert bench.read_packet(stored) == clinical
    assert bench.digest(bench.read_packet(stored)) == bench.digest(clinical)


def test_unfinished_previous_task_cannot_replay_inference(monkeypatch, fhir_store, configured):
    req = request(context=packet())
    transcript = [item.model_dump() for item in req.transcript]
    options = main.effective_options(req.care_options)
    correlation = req.correlation.model_dump(exclude_none=True)
    request_body = {'patient_id': 'p', 'transcript': transcript,
                    'supplemental_clinical_context': packet(), 'care_options': options,
                    'correlation': correlation}
    task = {'resourceType': 'Task', 'id': 'int-' + SUBMISSION.hex,
            'status': 'in-progress', 'code': {'text': interview_completion.CODE}}
    care_jobs.attach(task, {'status': 'assessing', 'request_sha256': bench.digest({k: v for k, v in request_body.items() if k != 'correlation'}),
                            'result': None})
    fhir_store['Task/' + task['id']] = task
    monkeypatch.setattr(interview_completion, 'run_interview', lambda *_: pytest.fail('Inference replayed'))
    with pytest.raises(HTTPException) as error:
        main.complete_interview(req)
    assert error.value.status_code == 409
    assert 'unfinished' in error.value.detail


def test_successful_retry_can_have_new_transport_correlation(monkeypatch, fhir_store, configured):
    calls = []
    monkeypatch.setattr(interview_completion, 'run_interview', lambda *a: calls.append(a) or completed_result())
    monkeypatch.setattr(care_jobs, 'enqueue', lambda *a, **kw: {'job_id': 'job-1', 'status': 'queued'})
    first = main.complete_interview(request(context=packet(), correlation={'run_id': 'original-run'}))
    retry = main.complete_interview(request(context=packet(), correlation={'run_id': 'retry-run'}))
    assert first == retry and len(calls) == 1


def test_assessment_only_completion_reuses_assessment_without_auto_enqueue(monkeypatch, fhir_store, configured):
    calls = []
    monkeypatch.setattr(interview_completion, 'run_interview', lambda *a: calls.append(a) or completed_result())
    monkeypatch.setattr(care_jobs, 'enqueue', lambda *a, **kw: pytest.fail('Assessment-only completion must not enqueue'))
    req = request(context=packet()).model_copy(update={'enqueue_care_plan': False})
    first = main.complete_interview(req)
    second = main.complete_interview(req)
    assert first == second and len(calls) == 1
    assert first['care_plan_job_id'] is None and first['care_plan_status'] == 'not-requested'


def test_http_request_id_and_trace_export(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv('CP_BENCHMARK_API_ENABLED', 'true')
    api = TestClient(main.app)
    response = api.get('/health')
    assert response.status_code == 200
    request_id = response.headers['X-Request-ID']
    UUID(request_id)
    trace = api.get('/benchmark/requests/' + request_id + '/trace')
    assert trace.status_code == 200
    assert trace.json()['request_id'] == request_id
    assert trace.json()['trace'][-1]['stage'] == 'api.request.finished'


def test_trace_endpoint_is_gated(monkeypatch, fhir_store, configured):
    with pytest.raises(HTTPException) as error:
        main.submission_trace(SUBMISSION)
    assert error.value.status_code == 404

    task = {'resourceType': 'Task', 'id': 'int-' + SUBMISSION.hex,
            'code': {'text': interview_completion.CODE}}
    care_jobs.attach(task, {'status': 'completed', 'correlation': {'run_id': 'trace-run'},
                            'trace': [{'stage': 'interview.assessment.started'}]})
    fhir_store['Task/' + task['id']] = task
    monkeypatch.setattr(main, 'load', lambda: SimpleNamespace(benchmark_api_enabled=True))
    trace = main.submission_trace(SUBMISSION)
    assert trace['correlation'] == {'run_id': 'trace-run'}
    assert trace['trace'] == [{'stage': 'interview.assessment.started'}]
