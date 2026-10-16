"""Strict, lossless FHIR context for care planning; interview reader stays unchanged."""
from datetime import date
import re
from central_park.tools.fhir import _client, PatientNotFoundError
from central_park.telemetry import timed


def valid_id(value):
    if not re.fullmatch(r'[A-Za-z0-9.-]{1,64}', value):
        raise ValueError('Invalid FHIR resource ID')
    return value


@timed('fhir.read')
def read(kind, identifier, optional=False):
    with _client() as c:
        r = c.get(f'/{kind}/{valid_id(identifier)}')
        if kind == 'Patient' and r.status_code == 404 and not optional:
            raise PatientNotFoundError(identifier)
        if optional and r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()


@timed('fhir.search')
def search(kind, **params):
    """Follow server pagination. Errors never masquerade as an empty result."""
    rows = []
    with _client() as c:
        r = c.get('/' + kind, params={**params, '_count': 100})
        seen = set()
        while True:
            r.raise_for_status()
            bundle = r.json()
            rows.extend(e['resource'] for e in bundle.get('entry', []) if 'resource' in e)
            nxt = next((l['url'] for l in bundle.get('link', []) if l.get('relation') == 'next'), None)
            if not nxt:
                return rows
            # Do not send credentials to arbitrary origins in server-provided links.
            from urllib.parse import urlparse
            if nxt in seen or (urlparse(nxt).netloc and urlparse(nxt).netloc != urlparse(str(c.base_url)).netloc):
                raise ValueError('Invalid FHIR pagination link')
            seen.add(nxt)
            r = c.get(nxt)


@timed('fhir.write')
def put(resource):
    with _client() as c:
        r = c.put(f"/{resource['resourceType']}/{valid_id(resource['id'])}", json=resource,
                  headers={'Content-Type': 'application/fhir+json'})
        r.raise_for_status()
    return resource


def linked(patient_id, questionnaire_id, assessment_id):
    read('Patient', valid_id(patient_id))
    qr = read('QuestionnaireResponse', questionnaire_id)
    assessment = read('ServiceRequest', assessment_id)
    for resource in (qr, assessment):
        if resource.get('subject', {}).get('reference') != f'Patient/{patient_id}':
            raise ValueError('Questionnaire and assessment must belong to the patient')
    if qr.get('status') != 'completed':
        raise ValueError('Questionnaire is not completed')
    if not any(n.get('text') == f'QR: {questionnaire_id}' for n in assessment.get('note', [])):
        raise ValueError('Assessment does not reference the requested questionnaire')
    return qr, assessment


@timed('care_context.load')
def context(patient_id, questionnaire_id, assessment_id):
    qr, assessment = linked(patient_id, questionnaire_id, assessment_id)
    patient = read('Patient', patient_id)
    from central_park.benchmark_context import read_packet, digest
    packet = read_packet(qr)
    result = {'patient': patient, 'questionnaire': qr, 'assessment': assessment,
            **{key: search(kind, patient=patient_id, **params) for key, kind, params in (
                ('conditions', 'Condition', {'clinical-status': 'active'}),
                ('medications', 'MedicationRequest', {'status': 'active'}),
                ('allergies', 'AllergyIntolerance', {}), ('observations', 'Observation', {}))}}
    result['medications'].extend(search('MedicationStatement', patient=patient_id, status='active,unknown'))
    if packet is not None:
        result.update(supplemental_clinical_context=packet, clinical_input_sha256=digest(packet))
    return result


def age_years(patient, as_of=None):
    try:
        born = date.fromisoformat(patient['birthDate'])
        pinned = next((e.get('valueDate') for e in patient.get('extension', [])
                       if e.get('url') == 'https://centralpark.example/fhir/StructureDefinition/benchmark-as-of-date'), None)
        today = as_of or (date.fromisoformat(pinned) if pinned else date.today())
        if born > today:
            return None
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    except (KeyError, ValueError):
        return None


def adult(patient):
    age = age_years(patient)
    return age is not None and age >= 18


def record_facts(ctx):
    """Explicit facts for generation/review; empty lists do not establish absence."""
    pinned = next((e.get('valueDate') for e in ctx['patient'].get('extension', [])
                   if e.get('url') == 'https://centralpark.example/fhir/StructureDefinition/benchmark-as-of-date'), None)
    return {'as_of_date': pinned or date.today().isoformat(), 'age_years': age_years(ctx['patient']),
            'recorded_gender': ctx['patient'].get('gender'),
            'record_counts': {key: len(ctx[key]) for key in ('conditions', 'medications', 'observations', 'allergies')},
            'empty_record_meaning': 'No matching resources recorded; not confirmation of absence, no medicines, normal values or resolved symptoms.'}
