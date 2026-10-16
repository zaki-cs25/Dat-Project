"""Minimal patient registration for intake; no clinical history is inferred."""
from datetime import date
from threading import Lock
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from central_park.tools.fhir import _client

REGISTRATION_SYSTEM = 'urn:central-park:patient-registration'
LOCK = Lock()  # The application runs one API process, as required by its job worker.


class PatientRegistration(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')

    registration_id: UUID
    full_name: str = Field(min_length=1, max_length=200)
    birth_date: date
    gender: Literal['female', 'male', 'other', 'unknown'] = 'unknown'

    @field_validator('birth_date')
    @classmethod
    def not_in_future(cls, value):
        if value > date.today():
            raise ValueError('Date of birth cannot be in the future')
        return value


class RegisteredPatient(BaseModel):
    patient_id: str
    full_name: str


class RegistrationConflictError(ValueError):
    pass


def register(req: PatientRegistration) -> dict:
    # A browser retains this UUID across request retries, including a lost
    # response after a successful FHIR write. The patient ID survives restarts.
    patient_id = 'patient-' + req.registration_id.hex
    identifier = {'system': REGISTRATION_SYSTEM, 'value': str(req.registration_id)}
    payload = {
        'resourceType': 'Patient', 'id': patient_id, 'active': True,
        'identifier': [identifier],
        # A full name is not guessed into culturally specific given/family parts.
        'name': [{'use': 'usual', 'text': req.full_name}],
        'birthDate': req.birth_date.isoformat(), 'gender': req.gender,
    }

    def same_registration(patient):
        if (identifier not in patient.get('identifier', []) or
                not any(n.get('text') == req.full_name for n in patient.get('name', [])) or
                patient.get('birthDate') != payload['birthDate'] or
                patient.get('gender') != req.gender):
            raise RegistrationConflictError(f'This registration was already saved as {patient_id} with different details. Choose Existing patient and use this ID to continue.')

    with LOCK, _client() as client:
        existing = client.get('/Patient/' + patient_id)
        if existing.status_code != 404:
            existing.raise_for_status()
            same_registration(existing.json())
        else:
            result = client.put('/Patient/' + patient_id, json=payload,
                                headers={'Content-Type': 'application/fhir+json', 'If-None-Match': '*'})
            if result.status_code == 412:
                existing = client.get('/Patient/' + patient_id)
                existing.raise_for_status()
                same_registration(existing.json())
            else:
                result.raise_for_status()
    return {'patient_id': patient_id, 'full_name': req.full_name}
