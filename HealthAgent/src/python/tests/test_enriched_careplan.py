"""Synthetic checks for model knowledge plus optional, truthfully attributed context."""
import copy
import json
import httpx
import pytest
from central_park import careplan, care_jobs, care_evidence
from central_park.config import load
from test_careplan import ctx, source, draft, Provider


@pytest.fixture(autouse=True)
def enriched(monkeypatch):
    monkeypatch.setenv('CP_CARE_GENERATION_MODE', 'enriched')


def model_draft(description='Discuss recorded blood-pressure monitoring with the clinician.'):
    result = draft(description, ids=[])
    result['activities'][0]['provenance'] = 'model'
    result['activities'][0]['timing'] = 'At the next clinician review, subject to current findings.'
    return result


def review(**changes):
    return {'approved': True, 'issues': [], 'review_notes': [], **changes}


def setup(monkeypatch, *responses, sources=None):
    provider = Provider(*responses)
    monkeypatch.setattr(careplan, 'get_provider', lambda: provider)
    monkeypatch.setattr(careplan, 'retrieve', lambda *a: (sources or [], []))
    return provider


def test_no_context_does_not_gate_model_suggestions(monkeypatch):
    provider = setup(monkeypatch, model_draft(), review())
    result = careplan.generate(ctx())
    assert provider.calls == 2 and result['result_status'] == 'completed'
    assert result['generation_mode'] == 'enriched'
    assert result['activities'][0]['provenance'] == 'model'
    assert result['activities'][0]['timing']
    assert result['evidence_sources'] == result['related_icmr_context'] == []
    assert result['context_status'] == 'no-matching-passages'
    assert 'hypertension' in result['uncovered_conditions']


def test_context_is_stored_even_when_not_cited(monkeypatch):
    setup(monkeypatch, model_draft(), review(), sources=[source()])
    result = careplan.generate(ctx())
    assert result['related_icmr_context'] == [source()]
    assert result['evidence_sources'] == []
    assert result['uncovered_conditions'] == []


def test_related_reference_is_not_labelled_icmr_grounding(monkeypatch):
    proposed = draft()
    setup(monkeypatch, proposed, review(), sources=[source()])
    result = careplan.generate(ctx())
    assert result['activities'][0]['provenance'] == 'context-informed'
    assert result['evidence_sources'][0]['passage_id'] == 's1'


def test_context_disabled_comparison_never_searches(monkeypatch):
    setup(monkeypatch, model_draft(), review())
    monkeypatch.setattr(careplan, 'retrieve', lambda *a: pytest.fail('Context-free comparison searched'))
    result = careplan.generate(ctx(), use_context=False)
    assert result['context_status'] == 'disabled' and result['context_enabled'] is False
    assert result['result_status'] == 'completed'


def test_retrieval_outage_is_disclosed_but_model_can_generate(monkeypatch):
    setup(monkeypatch, model_draft(), review())
    def failure(*args):
        raise httpx.ConnectError('Synthetic context service unavailable')
    monkeypatch.setattr(careplan, 'retrieve', failure)
    result = careplan.generate(ctx())
    assert result['result_status'] == 'completed'
    assert result['context_status'] == 'unavailable'
    assert any('retrieval unavailable' in note for note in result['review_notes'])


@pytest.mark.parametrize('priority', ['stat', 'urgent'])
def test_urgent_assessment_is_first_even_without_context(monkeypatch, priority):
    setup(monkeypatch, model_draft(), review())
    result = careplan.generate(ctx(priority=priority))
    assert result['result_status'] == 'completed'
    assert result['activities'][0]['provenance'] == 'assessment'
    assert result['activities'][0]['source_ids'] == ['ServiceRequest/a']


@pytest.mark.parametrize('bad', ['not-json', draft(ids=['fabricated']), model_draft('Start metformin 500 mg daily.')])
def test_malformed_fabricated_and_prohibited_output_still_fail(monkeypatch, bad):
    provider = setup(monkeypatch, bad, bad, sources=[source()])
    with pytest.raises(ValueError, match='one repair'):
        careplan.generate(ctx())
    assert provider.calls == 2


def test_reviewer_may_note_absent_support_without_blocking(monkeypatch):
    setup(monkeypatch, model_draft(), review(review_notes=['This model suggestion is not supported by supplied excerpts.']), sources=[source()])
    result = careplan.generate(ctx())
    assert result['result_status'] == 'completed'
    assert any('not supported' in note for note in result['review_notes'])


def test_prohibited_reviewer_narrative_is_also_rejected(monkeypatch):
    provider = setup(monkeypatch, model_draft(), review(review_notes=['Start metformin 500 mg daily.']),
                     model_draft(), review(review_notes=['Start metformin 500 mg daily.']))
    with pytest.raises(ValueError, match='dose|drug'):
        careplan.generate(ctx())
    assert provider.calls == 4


def test_invented_patient_fact_review_rejection_still_blocks(monkeypatch):
    reject = review(approved=False, issues=['Invented normal BP not present in record'])
    provider = setup(monkeypatch, model_draft(), reject, model_draft(), reject)
    with pytest.raises(ValueError, match='Invented normal BP'):
        careplan.generate(ctx())
    assert provider.calls == 4


def test_budget_preserves_whole_passages_and_multiple_conditions():
    a, b, c = source(identifier='a'), source(identifier='b'), source('ckd', 'c')
    a['text'] = 'x' * 300
    b['text'] = 'y' * 300
    c['text'] = 'z' * 300
    budget = len(json.dumps(careplan.model_source(a))) + len(json.dumps(careplan.model_source(c)))
    result = careplan.bounded_context([a, b, c], budget)
    assert result == [a, c]
    assert a['text'] == 'x' * 300 and c['text'] == 'z' * 300


def test_grounded_comparison_cannot_claim_bulk_context_as_evidence(monkeypatch):
    monkeypatch.setattr(careplan, 'retrieve', lambda *a: ([{**source(), 'evidence_role': 'context'}], []))
    monkeypatch.setattr(careplan, 'get_provider', lambda: pytest.fail('Grounded mode used unverified context'))
    assert careplan.generate(ctx(), mode='grounded')['result_status'] == 'insufficient-evidence'


def test_adult_retrieval_does_not_promote_explicit_pediatric_context(monkeypatch):
    monkeypatch.setattr(care_evidence, 'request', lambda *a: {'hits': [{**source(), 'workflow_review': {'population': 'pediatric'}}]})
    assert care_evidence.retrieve({'hypertension': ['c']}, '') == ([], ['hypertension'])


@pytest.mark.parametrize('name,value', [('CP_CARE_GENERATION_MODE', 'anything'), ('CP_CARE_CONTEXT_MAX_CHARS', '10')])
def test_invalid_generation_configuration_fails(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        load()
