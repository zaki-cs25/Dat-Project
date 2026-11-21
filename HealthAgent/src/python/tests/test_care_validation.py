"""Review evidence/transport contracts, not proof of clinical model accuracy."""
import copy
import json
import pytest
from central_park import careplan, care_context
from central_park.care_validation import ReviewContractError, validate_review_contract
from test_careplan import ctx, draft, source, approved, rejected, setup_model, Provider


def test_exact_evidence_supports_consistent_rejection():
    candidate = careplan.Draft.model_validate(draft('Take aspirin.'))
    review = careplan.Review.model_validate(rejected('Take aspirin.', 'Treatment selection', 'medication_scope'))
    validate_review_contract(review, candidate)


@pytest.mark.parametrize('change', [
    {'quote': 'invented words'}, {'field': 'context.patient'},
    {'field': 'title'}, {'quote': '   '}, {'explanation': '   '},
])
def test_invalid_issue_evidence_fails_closed(change):
    value = rejected('Take aspirin.', 'Treatment selection', 'medication_scope')
    value['issues'][0].update(change)
    with pytest.raises(ReviewContractError):
        validate_review_contract(careplan.Review.model_validate(value), careplan.Draft.model_validate(draft('Take aspirin.')))


@pytest.mark.parametrize('kind', ['approved_with_issue', 'failed_without_issue', 'issue_on_passed_check'])
def test_decision_and_check_coverage_must_agree(kind):
    value = rejected('Take aspirin.', 'Treatment selection', 'medication_scope')
    if kind == 'approved_with_issue':
        value['approved'] = True
    elif kind == 'failed_without_issue':
        value['issues'] = []
    else:
        value['checks']['medication_scope'] = True
    with pytest.raises(ReviewContractError):
        validate_review_contract(careplan.Review.model_validate(value), careplan.Draft.model_validate(draft('Take aspirin.')))


def test_all_checks_required():
    value = approved()
    value['checks'].pop('urgency')
    with pytest.raises(ValueError):
        careplan.Review.model_validate(value)


@pytest.mark.parametrize('text', [
    'Do not adjust doses or change medications.',
    'Review monitoring given the use of losartan.',
    'Renal impairment can increase drug levels.',
    'Confirmation of current medication use and allergies.',
])
def test_language_reaches_semantic_review_without_regex_veto(monkeypatch, text):
    provider = setup_model(monkeypatch, draft(text), approved())
    assert careplan.generate(ctx(), mode='grounded')['result_status'] == 'completed'
    assert provider.calls == 2


def test_invalid_review_corrected_without_regenerating_draft(monkeypatch):
    provider = setup_model(monkeypatch, draft(), {}, approved())
    assert careplan.generate(ctx(), mode='grounded')['result_status'] == 'completed'
    assert provider.calls == 3


def test_valid_rejection_repairs_patient_draft(monkeypatch):
    provider = setup_model(monkeypatch, draft('Take aspirin.'),
                           rejected('Take aspirin.', 'Treatment selection', 'medication_scope'),
                           draft(), approved())
    assert careplan.generate(ctx(), mode='grounded')['result_status'] == 'completed'
    assert provider.calls == 4


def test_citation_alias_roundtrip_and_urgency_shared(monkeypatch):
    captured = []
    class Capture(Provider):
        def complete(self, **kwargs):
            captured.append(json.loads(kwargs['messages'][0]['content'].split('\nRepair feedback:')[0]))
            return super().complete(**kwargs)
    provider = Capture(draft(ids=['S1']), approved(['S1']))
    monkeypatch.setattr(careplan, 'get_provider', lambda: provider)
    monkeypatch.setattr(careplan, 'retrieve', lambda *a: ([source(identifier='long-stored-id')], []))
    context = ctx(priority='stat')
    result = careplan.generate(context, mode='grounded')
    assert result['activities'][1]['source_ids'] == ['long-stored-id']
    for payload in captured:
        assert payload['evidence'][0]['passage_id'] == 'S1'
        assert payload['urgency_context']['effective_disposition'] == 'emergency'
        assert payload['application_activities'][0]['provenance'] == 'assessment'
    assert captured[1]['draft']['activities'][0]['source_ids'] == ['S1']


@pytest.mark.parametrize('priority,disposition,expected', [
    ('stat', 'routine', 'emergency'), ('routine', 'emergency', 'emergency'),
    ('routine', 'urgent', 'urgent'), ('urgent', 'routine', 'urgent'),
])
def test_disposition_is_a_floor(priority, disposition, expected):
    assert care_context.effective_disposition({'priority': priority}, {'clinician_disposition': disposition}) == expected


def test_unknown_citation_is_never_fuzzy_matched():
    with pytest.raises(ValueError, match='unknown citation'):
        careplan.resolve_citations(['s-1'], {'S1': 'stored-id'}, 'activities[0].source_ids')


@pytest.mark.parametrize('change', [{'provenance': 'assessment'}, {'category': 'urgent'}])
def test_application_owned_fields_remain_deterministic(change):
    value = draft()
    value['activities'][0].update(change)
    with pytest.raises(ValueError):
        careplan.validate(careplan.Draft.model_validate(value), [source()], ctx())
