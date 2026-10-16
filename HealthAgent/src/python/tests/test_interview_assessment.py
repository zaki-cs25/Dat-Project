"""Synthetic regressions for current answers versus earlier FHIR encounters."""
import json
import pytest
from central_park import agent
from central_park.tools.fhir import _trim_observation


@pytest.mark.parametrize('field,value', [('valueBoolean', False), ('valueBoolean', True),
    ('valueInteger', 0), ('valueString', 'Historical report')])
def test_observation_keeps_value_and_encounter_provenance(field, value):
    resource = {'id': 'old-symptom', 'code': {'text': 'Synthetic symptom'}, 'status': 'final',
        'effectiveDateTime': '2025-01-01T09:00:00Z', 'encounter': {'reference': 'Encounter/earlier'}, field: value}
    trimmed = _trim_observation(resource)
    assert trimmed['value'] == value and type(trimmed['value']) is type(value)
    assert trimmed['id'] == 'old-symptom' and trimmed['encounter'] == 'Encounter/earlier'
    assert trimmed['effective'] == resource['effectiveDateTime']


class Provider:
    def __init__(self):
        self.payloads = []

    def complete(self, system, messages):
        self.payloads.append(json.loads(messages[0]['content']))
        if len(self.payloads) == 1:
            return json.dumps({'triage_level': 'see-gp', 'chief_complaint': 'Review; historical anaphylaxis in the record.',
                'hpi': 'Routine follow-up; previous encounter symptoms need reconciliation.', 'red_flags': [],
                'recommended_actions': ['Clinician review.'], 'citations': []})
        return json.dumps({'verdict': 'confirm', 'level': 'see-gp', 'note': ''})


@pytest.fixture
def assessment(monkeypatch):
    provider = Provider()
    answers = [{'link_id': 'complaint', 'question': 'Why today?', 'answer': 'Routine follow-up; no new symptoms.'},
        {'link_id': 'symptoms', 'question': 'Any of these symptoms?', 'answer': 'None of these'},
        {'link_id': 'exertion', 'question': 'Does activity trigger discomfort?', 'answer': 'No'}]
    context = {'patient': {'id': 'synthetic'}, 'conditions': [], 'medications': [], 'allergies': [],
        'observations': [_trim_observation({'id': 'earlier', 'code': {'text': 'Chest pain'}, 'valueBoolean': True,
            'effectiveDateTime': '2025-01-01T09:00:00Z', 'encounter': {'reference': 'Encounter/earlier'}})]}
    monkeypatch.setattr(agent, 'get_patient_context', lambda _: context)
    monkeypatch.setattr(agent, 'get_questionnaire_response', lambda *_a, **_k: answers)
    monkeypatch.setattr(agent, 'get_provider', lambda: provider)
    monkeypatch.setattr(agent, 'search_guidelines', lambda *a, **k: [])
    monkeypatch.setattr(agent, '_persist_fhir', lambda *a, **k: dict(encounter_id='new-encounter',
        service_request_id='new-assessment', observation_ids=[], detected_issue_ids=[]))
    return provider, answers, context


def test_assessment_reviewer_receives_all_current_denials_and_historical_sources(assessment):
    provider, answers, context = assessment
    result = agent.run_interview('synthetic', 'current-questionnaire')
    assert result['triage_level'] == 'see-gp' and result['red_flags'] == []
    assert result['detected_issues'] == []
    assert provider.payloads[0]['patient_context']['observations'][0]['encounter'] == 'Encounter/earlier'
    review = provider.payloads[1]
    assert review['interview_transcript'] == answers
    assert review['message'] == ' '.join(a['answer'] for a in answers)
    assert 'anaphylaxis' not in review['message']  # generated summary cannot trigger patient-answer safety gates
    assert review['patient_context'] == context  # retain historical risks instead of hiding the earlier observation


def test_current_red_flag_still_enforces_emergency_floor(assessment):
    _, answers, _ = assessment
    answers[0]['answer'] = 'My face is drooping.'
    result = agent.run_interview('synthetic', 'current-questionnaire')
    assert result['triage_level'] == 'ed' and 'facial droop' in result['red_flags']


def test_current_medication_safety_finding_still_enforces_emergency_floor(assessment):
    _, answers, context = assessment
    context['medications'] = [{'display': 'Lisinopril'}]
    answers[0]['answer'] = 'My tongue is swollen.'
    result = agent.run_interview('synthetic', 'current-questionnaire')
    assert result['triage_level'] == 'ed'
    assert result['detected_issues'][0]['code'] == 'ace-inhibitor-angioedema'
