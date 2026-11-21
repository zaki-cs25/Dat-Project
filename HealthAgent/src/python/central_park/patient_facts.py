"""Deterministic demographic facts shared by intake and care generation."""
from datetime import date
import re

AS_OF_EXT = 'https://centralpark.example/fhir/StructureDefinition/benchmark-as-of-date'
AGE_EXT = 'https://centralpark.example/fhir/StructureDefinition/reported-age-years'
AGE_STATEMENT = re.compile(r'(?P<age>\d{1,3})(?=\s*[- ]year[- ]old\b)|'
                           r'(?<=age is )\d{1,3}\b|(?<=aged )\d{1,3}\b|'
                           r'(?<=patient is )\d{1,3}\b', re.I)


def demographic_facts(patient, as_of=None):
    extensions = {e.get('url'): e for e in patient.get('extension', [])}
    pinned = extensions.get(AS_OF_EXT, {}).get('valueDate')
    reference = as_of or (date.fromisoformat(pinned) if pinned else date.today())
    if isinstance(reference, str):
        reference = date.fromisoformat(reference)
    reported = extensions.get(AGE_EXT, {}).get('valueInteger')
    age, source = None, 'unavailable'
    if type(reported) is int and 0 <= reported <= 120:
        # An age is not a birth date. Do not extrapolate to another date.
        if pinned and reference.isoformat() == pinned:
            age, source = reported, 'reported-age-at-reference-date'
    elif patient.get('birthDate'):
        try:
            born = date.fromisoformat(patient['birthDate'])
            if born <= reference:
                age = reference.year - born.year - ((reference.month, reference.day) < (born.month, born.day))
                source = 'recorded-birth-date'
        except (TypeError, ValueError):
            pass
    return {'as_of_date': reference.isoformat(), 'age_years': age,
            'age_source': source, 'recorded_gender': patient.get('gender'),
            'birth_date_recorded': bool(patient.get('birthDate'))}
