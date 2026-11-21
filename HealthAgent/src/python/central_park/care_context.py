"""Strict, lossless FHIR context for care planning; interview reader stays unchanged."""
from datetime import date
from copy import deepcopy
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
    from central_park.patient_facts import demographic_facts
    return demographic_facts(patient, as_of)['age_years']


def adult(patient):
    age = age_years(patient)
    return age is not None and age >= 18


def record_facts(ctx):
    """Explicit facts for generation/review; empty lists do not establish absence."""
    from central_park.patient_facts import demographic_facts
    return {**demographic_facts(ctx['patient']),
            'record_counts': {key: len(ctx[key]) for key in ('conditions', 'medications', 'observations', 'allergies')},
            'empty_record_meaning': 'No matching resources recorded; not confirmation of absence, no medicines, normal values or resolved symptoms.'}


def effective_disposition(assessment, packet=None):
    """One existing urgency-floor policy shared by model context and app output."""
    ranks = {'routine': 0, 'urgent': 1, 'asap': 1, 'stat': 2, 'emergency': 2}
    rank = max(ranks.get(assessment.get('priority'), 0),
               ranks.get((packet or {}).get('clinician_disposition'), 0))
    return ('routine', 'urgent', 'emergency')[rank]


def model_context(ctx):
    """Normalize demographic statements for the model without changing saved assessments."""
    from central_park.patient_facts import AGE_STATEMENT
    from central_park.telemetry import event
    result = deepcopy({k: v for k, v in ctx.items() if not k.startswith('_care_')})
    age = age_years(ctx['patient'])
    corrections = []
    if age is not None:
        for note in result['assessment'].get('note', []):
            if note.get('text', '').startswith('HPI: '):
                def normalized(match):
                    if int(match.group()) != age:
                        corrections.append({'field': 'assessment.hpi.age', 'original': int(match.group()),
                                            'authoritative': age})
                    return str(age)
                note['text'] = AGE_STATEMENT.sub(normalized, note['text'])
    ctx['_care_upstream_conflicts'] = corrections
    event('careplan.context.normalized', demographic_correction_count=len(corrections))
    packet = result.get('supplemental_clinical_context') or {}
    supplied = packet.get('clinician_disposition')
    effective = effective_disposition(result['assessment'], packet)
    if effective != effective_disposition(result['assessment']):
        result['assessment']['priority'] = {'urgent': 'urgent', 'emergency': 'stat'}[effective]
        result['assessment'].setdefault('note', []).append({
            'text': 'Action: Preserve the supplied clinician disposition: ' + supplied + '.'})
    return result
