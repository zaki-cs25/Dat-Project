"""Synthetic registration checks; FHIR writes are simulated, no models called."""
import copy
import json
from datetime import date, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from central_park import main, patients
from central_park.tools.fhir import _trim_patient


@pytest.fixture
def registration():
    return {'registration_id': str(uuid4()), 'full_name': '  Synthetic नया Patient  ',
            'birth_date': '1980-04-01', 'gender': 'female'}


@pytest.fixture
def fhir(monkeypatch):
    state = {'patients': {}, 'writes': [], 'lose_response': False, 'status': None}
    def respond(request):
        if state['status']:
            return httpx.Response(state['status'])
        if request.method == 'GET':
            patient = state['patients'].get(request.url.path)
            return httpx.Response(200, json=patient) if patient else httpx.Response(404)
        assert request.method == 'PUT'
        assert request.headers['if-none-match'] == '*'
        patient = json.loads(request.content)
        state['patients'][request.url.path] = patient
        state['writes'].append(copy.deepcopy(patient))
        if state['lose_response']:
            state['lose_response'] = False
            raise httpx.ReadTimeout('Synthetic lost create response', request=request)
        return httpx.Response(201, headers={'Location': str(request.url) + '/_history/1'})
    monkeypatch.setattr(patients, '_client', lambda: httpx.Client(base_url='http://synthetic', transport=httpx.MockTransport(respond)))
    return state


def test_register_retry_persists_one_patient_without_inferred_history(registration, fhir):
    api = TestClient(main.app)
    first = api.post('/patients', json=registration)
    assert first.status_code == 200
    second = api.post('/patients', json=registration)
    assert second.json() == first.json()
    assert len(fhir['writes']) == 1
    resource = fhir['writes'][0]
    assert resource['id'] == first.json()['patient_id']
    assert resource['name'] == [{'use': 'usual', 'text': registration['full_name'].strip()}]
    assert resource['birthDate'] == '1980-04-01' and resource['gender'] == 'female'
    assert set(resource) == {'resourceType', 'id', 'active', 'identifier', 'name', 'birthDate', 'gender'}
    assert _trim_patient(resource)['name'] == registration['full_name'].strip()


def test_lost_successful_fhir_write_response_can_retry_without_duplicate(registration, fhir):
    api = TestClient(main.app)
    fhir['lose_response'] = True
    assert api.post('/patients', json=registration).status_code == 503
    assert api.post('/patients', json=registration).status_code == 200
    assert len(fhir['writes']) == 1


def test_registration_id_cannot_overwrite_existing_demographics(registration, fhir):
    api = TestClient(main.app)
    first = api.post('/patients', json=registration).json()
    changed = {**registration, 'full_name': 'Different synthetic person'}
    response = api.post('/patients', json=changed)
    assert response.status_code == 409
    assert first['patient_id'] in response.json()['detail']
    assert len(fhir['writes']) == 1


def test_independent_registrations_have_distinct_patient_ids(registration, fhir):
    api = TestClient(main.app)
    one = api.post('/patients', json=registration).json()
    two = api.post('/patients', json={**registration, 'registration_id': str(uuid4())}).json()
    assert one['patient_id'] != two['patient_id']
    assert len(fhir['writes']) == 2


@pytest.mark.parametrize('updates', [
    {'full_name': '   '}, {'full_name': 'x' * 201}, {'birth_date': 'not-a-date'},
    {'birth_date': (date.today() + timedelta(days=1)).isoformat()},
    {'gender': 'invalid'}, {'registration_id': 'not-a-uuid'}, {'conditions': ['hypertension']},
])
def test_invalid_registration_never_writes_to_fhir(registration, fhir, updates):
    response = TestClient(main.app).post('/patients', json={**registration, **updates})
    assert response.status_code == 422
    assert not fhir['writes']


def test_fhir_error_is_not_an_empty_record_or_registration_success(registration, fhir):
    fhir['status'] = 500
    response = TestClient(main.app).post('/patients', json=registration)
    assert response.status_code == 502
    assert not fhir['writes']


@pytest.mark.parametrize('name, expected', [
    ({'text': 'Synthetic single name'}, 'Synthetic single name'),
    ({'given': ['Synthetic'], 'family': 'Person'}, 'Synthetic Person'),
    ({'given': ['Synthetic']}, 'Synthetic'),
])
def test_interview_names_support_full_text_and_existing_structured_names(name, expected):
    assert _trim_patient({'name': [name]})['name'] == expected
