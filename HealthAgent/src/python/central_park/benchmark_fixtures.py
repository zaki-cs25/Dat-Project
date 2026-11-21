"""Create isolated, deterministic synthetic FHIR fixtures for benchmark runs."""
from __future__ import annotations

import re
import threading
from copy import deepcopy
from datetime import date
from uuid import UUID

from central_park import benchmark_context, care_context
from central_park.care_catalogue import BASE as CATALOGUE
from central_park.patients import RegistrationConflictError
from central_park.patient_facts import AGE_EXT

FIXTURE_SYSTEM = 'urn:central-park:benchmark-fixture'
AS_OF_EXT = 'https://centralpark.example/fhir/StructureDefinition/benchmark-as-of-date'
FIXTURE_LOCK = threading.Lock()

_EMPTY = {
    'unknown', 'not known', 'n/a', 'na', 'none', 'nil', 'none reported',
    'no known allergies', 'no known drug allergies', 'no known medications',
    'no current medications', 'no medications', 'no allergies', 'not reported',
    'not applicable', 'not elicited',
}
_QUALIFIERS = {'confirmed', 'current', 'diagnosed', 'established'}


def _norm(value: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9]+', ' ', value.casefold())).strip()


def _is_missing(value: str) -> bool:
    normalized = _norm(value)
    return (normalized in _EMPTY or normalized.startswith((
        'unknown ', 'not sure', 'not provided', 'not available', 'no known ',
        'no medication', 'no allergy', 'none ',
    )))


def _safe_qualifier(suffix: str) -> bool:
    if suffix in _QUALIFIERS or suffix == 'previously diagnosed by a clinician':
        return True
    if re.fullmatch(r'stage (?:[1-5](?:[a-d])?|[ivx]+|unknown)(?: documented| unknown| not documented)?', suffix):
        return True
    if re.fullmatch(r'documented for (?:at least )?\d+ (?:days?|weeks?|months?|years?)', suffix):
        return True
    return False


def _condition(label: str) -> dict | None:
    """Return a curated mapping only for a unique exact or safely qualified label."""
    normalized = _norm(label)
    candidates = []
    for tag, definition in CATALOGUE.items():
        aliases = { _norm(tag.replace('-', ' ')), *(_norm(alias) for alias in definition.get('aliases', [])) }
        for alias in aliases:
            if normalized == alias:
                candidates.append((len(alias), tag, definition))
            elif normalized.startswith(alias + ' '):
                suffix = normalized[len(alias):].strip()
                if _safe_qualifier(suffix):
                    candidates.append((len(alias), tag, definition))
    if not candidates:
        return None
    most_specific = max(length for length, _, _ in candidates)
    matches = {(tag, tuple(tuple(code) for code in definition.get('codes', [])))
               for length, tag, definition in candidates if length == most_specific}
    if len(matches) != 1:
        return None
    tag, _ = next(iter(matches))
    return CATALOGUE[tag]


def _reference_date(patient: dict) -> date | None:
    for extension in patient.get('extension', []):
        if extension.get('url') == AS_OF_EXT:
            try:
                return date.fromisoformat(extension['valueDate'])
            except (KeyError, ValueError):
                raise RegistrationConflictError('Stored benchmark fixture has an invalid pinned date')
    return None


def _ensure(resource: dict, expected: dict, fixture_id: UUID, packet_hash: str) -> None:
    existing = care_context.read(resource['resourceType'], resource['id'], optional=True)
    if existing is None:
        care_context.put(resource)
        return
    identifiers = existing.get('identifier', [])
    owns = {'system': FIXTURE_SYSTEM, 'value': str(fixture_id)} in identifiers
    if not owns:
        raise RegistrationConflictError('A benchmark fixture resource ID is already in use')
    if resource['resourceType'] == 'Patient':
        stored_packet = benchmark_context.read_packet(existing)
        if stored_packet is None or benchmark_context.digest(stored_packet) != packet_hash:
            raise RegistrationConflictError('This benchmark fixture ID was already used with different clinical input')
    if _comparable(existing) != _comparable(expected):
        raise RegistrationConflictError('A benchmark fixture resource does not match its deterministic input')


def _resource_id(fixture_id: UUID, kind: str, index: int | None = None) -> str:
    return f'bench-{fixture_id.hex}-{kind}' + (f'-{index:03d}' if index is not None else '')


def _comparable(resource: dict) -> dict:
    """Remove only FHIR server-owned root metadata and generated narrative."""
    comparable = deepcopy(resource)
    comparable.pop('meta', None)
    comparable.pop('text', None)
    return comparable


def _base(resource_type: str, resource_id: str, patient_id: str, fixture_id: UUID) -> dict:
    return {
        'resourceType': resource_type,
        'id': resource_id,
        'subject' if resource_type in {'Condition', 'Observation', 'MedicationStatement'} else 'patient': {
            'reference': f'Patient/{patient_id}'
        },
        'identifier': [{'system': FIXTURE_SYSTEM, 'value': str(fixture_id)}],
    }


def _conditions(packet: dict, patient_id: str, fixture_id: UUID) -> list[dict]:
    rows = []
    for index, label in enumerate(packet['established_conditions']):
        definition = _condition(label)
        codings = ([{'system': system, 'code': code, 'display': definition['aliases'][0]}
                    for system, code in definition.get('codes', [])] if definition else [])
        concept = {'text': label}
        if codings:
            concept['coding'] = codings
        rows.append({**_base('Condition', _resource_id(fixture_id, 'condition', index), patient_id, fixture_id),
                     'clinicalStatus': {'coding': [{'system': 'http://terminology.hl7.org/CodeSystem/condition-clinical', 'code': 'active'}]},
                     'verificationStatus': {'coding': [{'system': 'http://terminology.hl7.org/CodeSystem/condition-ver-status', 'code': 'confirmed'}]},
                     'code': concept})
    return rows


def _reported_rows(packet: dict, patient_id: str, fixture_id: UUID, field: str) -> list[dict]:
    kind = 'medication' if field == 'medications' else 'allergy'
    resource_type = 'MedicationStatement' if field == 'medications' else 'AllergyIntolerance'
    rows = []
    for index, label in enumerate(packet[field]):
        if _is_missing(label):
            continue
        row = _base(resource_type, _resource_id(fixture_id, kind, index), patient_id, fixture_id)
        if field == 'medications':
            row.update({
                'status': 'unknown',
                'medicationCodeableConcept': {'text': label},
                'informationSource': {'reference': f'Patient/{patient_id}'},
                'note': [{'text': 'Patient-reported medication history. Resource status is unspecified; '
                                  'this does not negate the supplied medication history.'}],
            })
        else:
            row.update({
                'clinicalStatus': {'coding': [{'system': 'http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical', 'code': 'active'}]},
                'verificationStatus': {'coding': [{'system': 'http://terminology.hl7.org/CodeSystem/allergyintolerance-verification', 'code': 'unconfirmed'}]},
                'code': {'text': label},
            })
        rows.append(row)
    return rows


def _observations(packet: dict, patient_id: str, fixture_id: UUID) -> list[dict]:
    rows = []
    for index, item in enumerate(packet['observations']):
        row = _base('Observation', _resource_id(fixture_id, 'observation', index), patient_id, fixture_id)
        row.update({'status': 'final', 'code': {'text': item['name']}})
        value = item['value']
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            quantity = {'value': value}
            if item['unit']:
                quantity['unit'] = item['unit']
            row['valueQuantity'] = quantity
        else:
            row['note'] = [{'text': f'Reported value: {value!s}'}]
        # Relative timing is preserved as text; no effective timestamp is invented.
        timing = f"Reported timing: {item['when']}"
        row.setdefault('note', []).append({'text': timing})
        rows.append(row)
    return rows


def provision(fixture_id: UUID, packet: dict) -> dict:
    """Idempotently provision synthetic resources scoped only to ``fixture_id``."""
    fixture_id = fixture_id if isinstance(fixture_id, UUID) else UUID(str(fixture_id))
    packet = benchmark_context.snapshot(packet)
    from central_park.benchmark_context import ClinicalPacket
    packet = ClinicalPacket.model_validate(packet).model_dump(mode='json')
    packet_hash = benchmark_context.digest(packet)
    patient_id = f'bench-{fixture_id.hex}'

    with FIXTURE_LOCK:
        existing = care_context.read('Patient', patient_id, optional=True)
        if existing is not None:
            if {'system': FIXTURE_SYSTEM, 'value': str(fixture_id)} not in existing.get('identifier', []):
                raise RegistrationConflictError('A benchmark patient ID is already in use')
            stored = benchmark_context.read_packet(existing)
            if stored is None or benchmark_context.digest(stored) != packet_hash:
                raise RegistrationConflictError('This benchmark fixture ID was already used with different clinical input')
            pinned = _reference_date(existing)
            if pinned is None:
                raise RegistrationConflictError('Stored benchmark fixture has no pinned reference date')
            as_of = pinned
        else:
            as_of = date.fromisoformat(packet['as_of_date']) if packet.get('as_of_date') else date.today()

        patient = {
            'resourceType': 'Patient', 'id': patient_id, 'active': True,
            'identifier': [{'system': FIXTURE_SYSTEM, 'value': str(fixture_id)}],
            'name': [{'use': 'usual', 'text': f'Synthetic benchmark patient {fixture_id.hex[:8]}'}],
        }
        sex = packet['patient']['sex'].casefold()
        patient['gender'] = {'woman': 'female', 'man': 'male'}.get(
            sex, sex if sex in {'female', 'male', 'other', 'unknown'} else 'unknown')
        patient['extension'] = [{'url': AS_OF_EXT, 'valueDate': as_of.isoformat()},
                                {'url': AGE_EXT, 'valueInteger': packet['patient']['age']}]
        benchmark_context.attach_packet(patient, packet)

        resources = [patient, *_conditions(packet, patient_id, fixture_id),
                     *_reported_rows(packet, patient_id, fixture_id, 'medications'),
                     *_reported_rows(packet, patient_id, fixture_id, 'allergies'),
                     *_observations(packet, patient_id, fixture_id)]
        ids: dict[str, list[str]] = {}
        # Patient is always first; partial writes can safely resume on retry.
        for resource in resources:
            _ensure(resource, resource, fixture_id, packet_hash)
            ids.setdefault(resource['resourceType'], []).append(resource['id'])

    return {'patient_id': patient_id, 'clinical_input_sha256': packet_hash, 'resource_ids': ids}
