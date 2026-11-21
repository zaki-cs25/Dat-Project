from copy import deepcopy
import json
from pathlib import Path
from uuid import UUID
from uuid import uuid5, NAMESPACE_URL

import pytest

from central_park import benchmark_fixtures, care_context
from central_park.patients import RegistrationConflictError


FIXTURE = UUID('12345678-1234-5678-1234-567812345678')
ROOT = Path(__file__).resolve().parents[3]
ALL_CASES = [case for file in sorted((ROOT / 'benchmarks/custom').glob('cases_*.json'))
             for case in json.loads(file.read_text())]


def packet():
    return {
        'patient': {'age': 56, 'sex': 'female'},
        'established_conditions': ['hypertension (diagnosed)'],
        'medications': ['Amlodipine 5 mg daily (patient-reported)', 'unknown'],
        'allergies': ['Penicillin reaction (patient-reported)', 'unknown'],
        'observations': [
            {'name': 'Blood pressure', 'value': 128, 'unit': 'mmHg', 'when': 'today'},
            {'name': 'Symptoms', 'value': 'not recorded', 'unit': '', 'when': 'recently'},
        ],
        'narrative': 'Synthetic narrative with no added confirmation.',
        'missing_information': ['medication status'],
        'request': 'Prepare a cautious review plan.',
    }


@pytest.fixture
def fhir_store(monkeypatch):
    store = {}
    writes = []

    def read(kind, identifier, optional=False):
        found = store.get((kind, identifier))
        if found is None and not optional:
            raise AssertionError(f'unexpected missing resource {kind}/{identifier}')
        return deepcopy(found)

    def put(resource):
        key = (resource['resourceType'], resource['id'])
        store[key] = deepcopy(resource)
        writes.append(key)
        return resource

    monkeypatch.setattr(care_context, 'read', read)
    monkeypatch.setattr(care_context, 'put', put)
    return store, writes


def test_provision_creates_only_explicit_synthetic_facts(fhir_store):
    store, _ = fhir_store
    result = benchmark_fixtures.provision(FIXTURE, packet())

    assert result['patient_id'] == 'bench-' + FIXTURE.hex
    assert len(result['clinical_input_sha256']) == 64
    patient = store[('Patient', result['patient_id'])]
    assert patient['name'][0]['text'].startswith('Synthetic benchmark patient')
    assert 'birthDate' not in patient  # age is recorded as an extension, not a synthetic birth date
    assert {'url': benchmark_fixtures.AGE_EXT, 'valueInteger': packet()['patient']['age']} in patient['extension']
    # The app stores the validated packet, which includes optional fields set to None.
    validated = benchmark_fixtures.benchmark_context.ClinicalPacket.model_validate(packet()).model_dump(mode='json')
    assert benchmark_fixtures.benchmark_context.read_packet(patient) == validated
    assert patient['extension'][0]['url'] == benchmark_fixtures.AS_OF_EXT

    conditions = [v for (kind, _), v in store.items() if kind == 'Condition']
    assert len(conditions) == 1
    assert conditions[0]['code']['coding'][0]['system'] == 'http://snomed.info/sct'
    assert conditions[0]['code']['text'] == 'hypertension (diagnosed)'
    assert conditions[0]['clinicalStatus']['coding'][0]['code'] == 'active'

    medications = [v for (kind, _), v in store.items() if kind == 'MedicationStatement']
    assert len(medications) == 1
    assert medications[0]['status'] == 'unknown'
    assert medications[0]['subject'] == {'reference': 'Patient/' + result['patient_id']}
    assert 'patient' not in medications[0]
    assert medications[0]['medicationCodeableConcept']['text'].startswith('Amlodipine')
    assert not any(kind == 'MedicationRequest' for kind, _ in store)

    allergies = [v for (kind, _), v in store.items() if kind == 'AllergyIntolerance']
    assert len(allergies) == 1
    assert allergies[0]['verificationStatus']['coding'][0]['code'] == 'unconfirmed'

    observations = [v for (kind, _), v in store.items() if kind == 'Observation']
    assert len(observations) == 2
    assert observations[0]['valueQuantity'] == {'value': 128, 'unit': 'mmHg'}
    assert 'effectiveDateTime' not in observations[0]
    assert observations[0]['note'][0]['text'] == 'Reported timing: today'
    assert 'valueQuantity' not in observations[1]
    assert observations[1]['note'][0]['text'] == 'Reported value: not recorded'


def test_same_uuid_and_packet_is_idempotent_and_payload_is_frozen(fhir_store):
    store, writes = fhir_store
    first = benchmark_fixtures.provision(FIXTURE, packet())
    first_count = len(writes)
    second = benchmark_fixtures.provision(FIXTURE, packet())
    assert first == second
    assert len(writes) == first_count
    assert len(store) == len(first['resource_ids']['Patient']) + sum(
        len(ids) for kind, ids in first['resource_ids'].items() if kind != 'Patient')

    changed = packet()
    changed['narrative'] += ' Changed.'
    with pytest.raises(RegistrationConflictError, match='different clinical input'):
        benchmark_fixtures.provision(FIXTURE, changed)


def test_server_meta_and_generated_narrative_are_ignored_but_clinical_edits_conflict(fhir_store, monkeypatch):
    store, writes = fhir_store
    benchmark_fixtures.provision(FIXTURE, packet())
    write_count = len(writes)

    def server_read(kind, identifier, optional=False):
        resource = deepcopy(store.get((kind, identifier)))
        if resource is None:
            if optional:
                return None
            raise AssertionError(f'unexpected missing resource {kind}/{identifier}')
        resource['meta'] = {'versionId': '2', 'lastUpdated': '2030-01-01T00:00:00Z'}
        resource['text'] = {'status': 'generated', 'div': '<div>FHIR server narrative</div>'}
        return resource

    monkeypatch.setattr(care_context, 'read', server_read)
    benchmark_fixtures.provision(FIXTURE, packet())
    assert len(writes) == write_count

    condition_id = 'bench-' + FIXTURE.hex + '-condition-000'
    store[('Condition', condition_id)]['code']['text'] = 'Tampered clinical condition'
    with pytest.raises(RegistrationConflictError, match='does not match its deterministic input'):
        benchmark_fixtures.provision(FIXTURE, packet())


def test_collision_with_unrelated_patient_is_never_overwritten(fhir_store):
    store, writes = fhir_store
    patient_id = 'bench-' + FIXTURE.hex
    store[('Patient', patient_id)] = {'resourceType': 'Patient', 'id': patient_id,
                                      'name': [{'text': 'Existing person'}]}
    with pytest.raises(RegistrationConflictError, match='already in use'):
        benchmark_fixtures.provision(FIXTURE, packet())
    assert not writes
    assert store[('Patient', patient_id)]['name'][0]['text'] == 'Existing person'


def test_unmatched_established_condition_stays_uncoded_and_narrative_symptoms_are_ignored(fhir_store):
    store, _ = fhir_store
    value = packet()
    value['established_conditions'] = ['asthma exacerbation']
    value['narrative'] += ' Also mentions chest pain.'
    result = benchmark_fixtures.provision(FIXTURE, value)
    conditions = [resource for (kind, _), resource in store.items() if kind == 'Condition']
    assert len(conditions) == 1
    assert conditions[0]['code'] == {'text': 'asthma exacerbation'}  # FHIR forbids empty arrays, so no coding key
    assert len(result['resource_ids']['Condition']) == 1


def test_unknown_and_no_known_allergy_or_medication_do_not_create_facts(fhir_store):
    store, _ = fhir_store
    value = packet()
    value['medications'] = ['unknown medications', 'No current medications']
    value['allergies'] = ['No known food allergies', 'unknown allergy history']
    value['observations'] = []
    result = benchmark_fixtures.provision(FIXTURE, value)
    assert result['resource_ids'] == {'Patient': ['bench-' + FIXTURE.hex], 'Condition': [
        'bench-' + FIXTURE.hex + '-condition-000']}
    assert not any(kind in {'MedicationStatement', 'AllergyIntolerance'} for kind, _ in store)


@pytest.mark.parametrize('case', ALL_CASES, ids=lambda case: case['case_id'])
def test_all_custom_benchmark_packets_provision_and_roundtrip_without_mutation(case, fhir_store):
    store, _ = fhir_store
    original = deepcopy(case['clinical_input'])
    fixture_id = uuid5(NAMESPACE_URL, 'central-park-benchmark:' + case['case_id'])
    result = benchmark_fixtures.provision(fixture_id, original)

    patient = store[('Patient', result['patient_id'])]
    assert benchmark_fixtures.benchmark_context.read_packet(patient) == original
    assert result['clinical_input_sha256'] == benchmark_fixtures.benchmark_context.digest(original)
    assert benchmark_fixtures.benchmark_context.digest(
        benchmark_fixtures.benchmark_context.read_packet(patient)) == result['clinical_input_sha256']
    assert patient['name'][0]['text'].startswith('Synthetic benchmark patient')
    assert patient['gender'] in {'female', 'male', 'other', 'unknown'}
    assert result['resource_ids']['Patient'] == [result['patient_id']]


@pytest.mark.parametrize(('sex', 'gender'), [('woman', 'female'), ('man', 'male')])
def test_common_sex_labels_map_to_fhir_gender(sex, gender, fhir_store):
    store, _ = fhir_store
    value = packet()
    value['patient']['sex'] = sex
    result = benchmark_fixtures.provision(FIXTURE, value)
    assert store[('Patient', result['patient_id'])]['gender'] == gender
