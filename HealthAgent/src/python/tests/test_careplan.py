"""Synthetic evidence only: software safety and persistence tests, not clinical validation."""
import copy
import hashlib
import json
import threading
from datetime import date
from concurrent.futures import ThreadPoolExecutor
import httpx
import pytest
from central_park import careplan, care_jobs, care_context, care_evidence
from central_park.import_care_documents import validate_review, digest


@pytest.fixture(autouse=True)
def original_grounded_contract(monkeypatch):
    monkeypatch.setenv('CP_CARE_GENERATION_MODE', 'grounded')


def ctx(condition='hypertension', priority='routine'):
    alias = care_evidence.CATALOGUE[condition]['aliases'][0]
    return {'patient': {'id': 'p', 'birthDate': '1970-01-01'},
            'conditions': [{'id': 'c', 'code': {'text': alias}}],
            'questionnaire': {'id': 'q', 'status': 'completed', 'item': []},
            'assessment': {'id': 'a', 'priority': priority},
            'medications': [], 'observations': [], 'allergies': []}


def source(condition='hypertension', identifier='s1'):
    return {'passage_id': identifier, 'condition': condition, 'reviewed': True,
            'text': 'SYNTHETIC TEST ONLY: Review recorded measurements with the clinician.',
            'applicability': 'Established condition in an adult.', 'exceptions': 'No prescribing.',
            'document_id': 'synthetic', 'version_id': 'test-v1', 'page': 1, 'section': 'Test',
            'publisher': 'Synthetic test fixture', 'official_url': 'https://example.invalid',
            'original_text': 'Synthetic fixture', 'checksum': 'test'}


def draft(description='Review recorded measurements with the clinician.', ids=None):
    return {'title': 'Draft', 'activities': [{'category': 'monitoring', 'description': description,
            'provenance': 'icmr', 'source_ids': ['s1'] if ids is None else ids}],
            'missing_information': [], 'uncovered_conditions': [], 'review_notes': []}


class Provider:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    def complete(self, **kwargs):
        self.calls += 1
        value = self.responses.pop(0)
        return value if isinstance(value, str) else json.dumps(value)


def approved(ids=None):
    return {'approved': True, 'issues': [], 'applicable_source_ids': ids or ['s1']}


def setup_model(monkeypatch, *responses, sources=None):
    provider = Provider(*responses)
    monkeypatch.setattr(careplan, 'get_provider', lambda: provider)
    monkeypatch.setattr(careplan, 'retrieve', lambda *args: (sources or [source()], []))
    return provider


@pytest.mark.parametrize('condition', list(care_evidence.CATALOGUE))
def test_each_established_condition_uses_scoped_evidence(monkeypatch, condition):
    calls = []
    def request(path, body):
        calls.append(body)
        return {'hits': [source(condition)]}
    monkeypatch.setattr(care_evidence, 'request', request)
    monkeypatch.setattr(careplan, 'retrieve', care_evidence.retrieve)
    monkeypatch.setattr(careplan, 'get_provider', lambda: Provider(draft(), approved()))
    result = careplan.generate(ctx(condition))
    assert result['result_status'] == 'completed'
    assert calls[0]['condition'] == condition and calls[0]['k'] == 5
    assert result['evidence_sources'][0]['condition'] == condition


@pytest.mark.parametrize('priority', ['stat', 'urgent'])
def test_urgent_survives_no_evidence_without_model(monkeypatch, priority):
    monkeypatch.setattr(careplan, 'retrieve', lambda *args: ([], ['hypertension']))
    monkeypatch.setattr(careplan, 'get_provider', lambda: pytest.fail('Model should not be called'))
    result = careplan.generate(ctx(priority=priority))
    assert result['result_status'] == 'insufficient-evidence'
    assert result['activities'][0]['provenance'] == 'assessment'
    assert result['activities'][0]['source_ids'] == ['ServiceRequest/a']
    assert 'not replace or delay' in result['activities'][0]['description']


def test_urgent_first_and_exact_assessment_actions_retained(monkeypatch):
    setup_model(monkeypatch, draft(), approved())
    context = ctx(priority='stat')
    context['assessment']['note'] = [{'text': 'Action: Call emergency services immediately.'}]
    result = careplan.generate(context)
    assert result['activities'][0]['category'] == 'urgent'
    assert 'Call emergency services immediately.' in result['activities'][0]['description']
    assert result['activities'][1]['provenance'] == 'icmr'


@pytest.mark.parametrize('bad', ['not JSON', draft(ids=['invented']), draft('Start metformin 500 mg daily.')])
def test_invalid_output_has_one_repair_and_is_never_accepted(monkeypatch, bad):
    provider = setup_model(monkeypatch, bad, bad)
    with pytest.raises(ValueError, match='one repair'):
        careplan.generate(ctx())
    assert provider.calls == 2


def test_one_repair_can_succeed(monkeypatch):
    provider = setup_model(monkeypatch, draft(ids=['fabricated']), draft(), approved())
    assert careplan.generate(ctx())['result_status'] == 'completed'
    assert provider.calls == 3


def test_derived_age_handles_birthdays_and_invalid_future_dates():
    assert care_context.age_years({'birthDate': '1970-04-01'}, date(2026, 10, 8)) == 56
    assert care_context.age_years({'birthDate': '1970-04-01'}, date(2026, 3, 31)) == 55
    assert care_context.age_years({'birthDate': '2027-01-01'}, date(2026, 10, 8)) is None
    assert care_context.age_years({}) is None


def test_incorrect_patient_age_rejected_before_model_review(monkeypatch):
    proposed = draft()
    proposed['review_notes'] = ['Orthostatic assessment omitted because the patient is 54 years old.']
    provider = setup_model(monkeypatch, proposed, proposed)
    monkeypatch.setattr(careplan, 'age_years', lambda patient: 56)
    with pytest.raises(ValueError, match='age inconsistent'):
        careplan.generate(ctx())
    assert provider.calls == 2


def test_guideline_age_threshold_is_not_a_patient_age_claim(monkeypatch):
    proposed = careplan.Draft.model_validate(draft('Review measurements. For adults 80 years old, clarify the target.'))
    careplan.validate(proposed, [source()], ctx())


def test_generation_and_review_receive_record_facts_and_empty_search_meaning(monkeypatch):
    payloads = []
    class CapturingProvider(Provider):
        def complete(self, **kwargs):
            payloads.append(json.loads(kwargs['messages'][0]['content'].split('\nRepair feedback:')[0]))
            return super().complete(**kwargs)
    provider = CapturingProvider(draft(), approved())
    monkeypatch.setattr(careplan, 'get_provider', lambda: provider)
    monkeypatch.setattr(careplan, 'retrieve', lambda *args: ([source()], []))
    context = ctx()
    context['medications'] = [{'id': 'recorded-medication'}]
    careplan.generate(context)
    for payload in payloads:
        facts = payload['patient_facts']
        assert facts['age_years'] == care_context.age_years(context['patient'])
        assert facts['record_counts']['medications'] == 1
        assert facts['record_counts']['observations'] == 0
        assert 'not confirmation of absence' in facts['empty_record_meaning']


@pytest.mark.parametrize('mode', ['grounded', 'enriched'])
def test_supplemental_packet_and_hash_reach_generation_and_review(monkeypatch, mode):
    monkeypatch.setenv('CP_CARE_GENERATION_MODE', mode)
    packet = {'note': '患者’s exact Unicode context — keep all of it.', 'unknown_field': {'x': [1, '✓']}}
    digest = hashlib.sha256(json.dumps(packet, sort_keys=True, ensure_ascii=False,
                                      separators=(',', ':')).encode('utf-8')).hexdigest()
    context = ctx()
    context['supplemental_clinical_context'] = packet
    context['clinical_input_sha256'] = digest
    captured = []

    class CapturingProvider(Provider):
        def complete(self, **kwargs):
            captured.append(json.loads(kwargs['messages'][0]['content'].split('\nRepair feedback:')[0]))
            return super().complete(**kwargs)

    proposed = draft()
    if mode == 'enriched':
        proposed['activities'][0]['provenance'] = 'model'
        proposed['activities'][0]['source_ids'] = []
    provider = CapturingProvider(proposed, {'approved': True, 'issues': [], 'review_notes': []}
                                 if mode == 'enriched' else approved())
    monkeypatch.setattr(careplan, 'get_provider', lambda: provider)
    monkeypatch.setattr(careplan, 'retrieve', lambda *args: ([source()], []))
    careplan.generate(context, mode=mode)
    assert provider.calls == 2
    for payload in captured:
        assert payload['supplemental_clinical_context'] == packet
        assert payload['clinical_input_sha256'] == digest
        assert payload['context']['supplemental_clinical_context'] == packet


def test_supplemental_hash_mismatch_fails_before_provider(monkeypatch):
    monkeypatch.setattr(careplan, 'get_provider', lambda: pytest.fail('Provider must not be invoked'))
    context = ctx()
    context['supplemental_clinical_context'] = {'note': 'changed'}
    context['clinical_input_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='hash mismatch'):
        careplan.generate(context)


def test_durable_care_options_apply_when_generate_arguments_are_omitted(monkeypatch):
    provider = Provider({'title': 'Draft', 'activities': [{'category': 'monitoring', 'description': 'Review recorded measurements.', 'provenance': 'model', 'source_ids': []}], 'missing_information': [], 'uncovered_conditions': [], 'review_notes': []}, {'approved': True, 'issues': [], 'review_notes': []})
    monkeypatch.setattr(careplan, 'get_provider', lambda: provider)
    monkeypatch.setattr(careplan, 'retrieve', lambda *args: pytest.fail('Stored context option disabled retrieval'))
    context = ctx()
    context['care_options'] = {'mode': 'enriched', 'use_icmr_context': False}
    result = careplan.generate(context)
    assert result['generation_mode'] == 'enriched'
    assert result['context_enabled'] is False
    assert result['context_status'] == 'disabled'


def test_oversized_supplemental_packet_fails_before_provider(monkeypatch):
    monkeypatch.setenv('CP_MODEL_INPUT_MAX_CHARS', '1000')
    provider = Provider()
    monkeypatch.setattr(careplan, 'get_provider', lambda: provider)
    monkeypatch.setattr(careplan, 'retrieve', lambda *args: ([source()], []))
    context = ctx()
    context['supplemental_clinical_context'] = {'note': '患者' * 1000}
    context['clinical_input_sha256'] = hashlib.sha256(json.dumps(
        context['supplemental_clinical_context'], sort_keys=True, ensure_ascii=False,
        separators=(',', ':')).encode('utf-8')).hexdigest()
    with pytest.raises(ValueError, match='exceeds configured limit'):
        careplan.generate(context)
    assert provider.calls == 0


def test_context_window_api_error_is_explicit_and_not_repaired(monkeypatch):
    class WindowProvider:
        calls = 0
        def complete(self, **kwargs):
            self.calls += 1
            raise RuntimeError('maximum context length exceeded')

    provider = WindowProvider()
    monkeypatch.setattr(careplan, 'get_provider', lambda: provider)
    monkeypatch.setattr(careplan, 'retrieve', lambda *args: ([source()], []))
    with pytest.raises(ValueError, match='context window exceeded'):
        careplan.generate(ctx(), mode='enriched')
    assert provider.calls == 1


def test_missing_threshold_review_rejection_is_bounded(monkeypatch):
    rejection = {'approved': False, 'applicable_source_ids': [],
                 'issues': ['BP threshold is unknown; unconditional every-visit timing is inapplicable.']}
    proposed = draft('Review medication adherence at every visit.')
    proposed['activities'][0]['category'] = 'medication-review'
    provider = setup_model(monkeypatch, proposed, rejection, proposed, rejection)
    with pytest.raises(ValueError, match='BP threshold is unknown'):
        careplan.generate(ctx())
    assert provider.calls == 4


def test_separate_reviewer_rejects_applicability_and_conflicts(monkeypatch):
    review = {'approved': False, 'issues': ['Prerequisite missing; conflicting recommendations'], 'applicable_source_ids': []}
    provider = setup_model(monkeypatch, draft(), review, draft(), review)
    with pytest.raises(ValueError, match='Prerequisite'):
        careplan.generate(ctx())
    assert provider.calls == 4


def test_fabricated_reviewer_citation_rejected(monkeypatch):
    setup_model(monkeypatch, draft(), approved(['ghost']), draft(), approved(['ghost']))
    with pytest.raises(ValueError, match='fabricated'):
        careplan.generate(ctx())


def test_missing_observations_and_unsupported_conditions_disclosed(monkeypatch):
    proposed = draft()
    proposed['missing_information'] = ['No current measurements recorded.']
    setup_model(monkeypatch, proposed, approved())
    context = ctx()
    context['conditions'].append({'id': 'u', 'code': {'text': 'Unsupported test condition'}})
    result = careplan.generate(context)
    assert 'Unsupported test condition' in result['uncovered_conditions']
    assert result['missing_information']


def test_interview_symptoms_cannot_establish_conditions(monkeypatch):
    context = ctx()
    context['conditions'] = []
    context['questionnaire']['item'] = [{'text': 'I think I have diabetes'}]
    seen = []
    monkeypatch.setattr(careplan, 'retrieve', lambda matched, concerns: (seen.append(matched) or [], []))
    assert careplan.generate(context)['result_status'] == 'insufficient-evidence'
    assert seen == [{}]


def test_multimorbidity_consolidated_activity_keeps_both_sources(monkeypatch):
    proposed = draft(ids=['s1', 's2'])
    setup_model(monkeypatch, proposed, approved(['s1', 's2']), sources=[source(), source('ckd', 's2')])
    context = ctx()
    context['conditions'].append({'id': 'c2', 'code': {'text': 'ckd'}})
    result = careplan.generate(context)
    assert len(result['activities']) == 1
    assert len(result['evidence_sources']) == 2
    assert result['condition_ids'] == ['c', 'c2']


def test_unreviewed_and_wrong_condition_hits_excluded(monkeypatch):
    monkeypatch.setattr(care_evidence, 'request', lambda *args: {'hits': [{**source(), 'reviewed': False}, source('asthma')]})
    assert care_evidence.retrieve({'hypertension': ['c']}, 'concerns') == ([], ['hypertension'])


def test_retrieval_failure_is_not_empty_evidence(monkeypatch):
    def fail(*args):
        raise httpx.ConnectError('FHIR/IRIS unavailable')
    monkeypatch.setattr(care_evidence, 'request', fail)
    with pytest.raises(httpx.ConnectError):
        care_evidence.retrieve({'hypertension': ['c']}, '')


def test_context_preserves_boolean_integer_components_and_empty_success(monkeypatch):
    resources = {'Patient/p': {'id': 'p', 'birthDate': '1970-01-01'},
        'QuestionnaireResponse/q': {'id': 'q', 'subject': {'reference': 'Patient/p'}, 'status': 'completed', 'item': [{'answer': [{'valueInteger': 0}, {'valueBoolean': False}]}]},
        'ServiceRequest/a': {'id': 'a', 'subject': {'reference': 'Patient/p'}, 'note': [{'text': 'QR: q'}]}}
    observations = [{'id': 'o', 'effectiveDateTime': '2026-01-01', 'valueBoolean': False,
                     'component': [{'code': {'text': 'Systolic'}, 'valueQuantity': {'value': 120, 'unit': 'mmHg'}}]}]
    def respond(request):
        key = request.url.path.lstrip('/')
        return httpx.Response(200, json=resources[key] if key in resources else {'resourceType': 'Bundle', 'entry': [{'resource': o} for o in observations] if key == 'Observation' else []})
    monkeypatch.setattr(care_context, '_client', lambda: httpx.Client(base_url='http://test', transport=httpx.MockTransport(respond)))
    result = care_context.context('p', 'q', 'a')
    assert result['observations'] == observations and result['medications'] == []
    assert result['questionnaire']['item'][0]['answer'][1]['valueBoolean'] is False


@pytest.mark.parametrize('resource', ['QuestionnaireResponse/q', 'ServiceRequest/a'])
def test_wrong_patient_context_rejected(monkeypatch, resource):
    def read(kind, identifier):
        return {'subject': {'reference': 'Patient/wrong' if kind + '/' + identifier == resource else 'Patient/p'}, 'status': 'completed', 'note': [{'text': 'QR: q'}]}
    monkeypatch.setattr(care_context, 'read', read)
    with pytest.raises(ValueError, match='belong'):
        care_context.linked('p', 'q', 'a')


def test_failed_fhir_search_raises(monkeypatch):
    monkeypatch.setattr(care_context, '_client', lambda: httpx.Client(base_url='http://test', transport=httpx.MockTransport(lambda r: httpx.Response(503))))
    with pytest.raises(httpx.HTTPStatusError):
        care_context.search('Observation', patient='p')


def test_missing_patient_cannot_enqueue_or_save_task(monkeypatch):
    from central_park.tools.fhir import PatientNotFoundError
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(404, json={'resourceType': 'OperationOutcome'})
    monkeypatch.setattr(care_context, '_client', lambda: httpx.Client(base_url='http://test', transport=httpx.MockTransport(respond)))
    with pytest.raises(PatientNotFoundError, match="Patient 'patient-2' was not found"):
        care_jobs.enqueue('patient-2', 'q', 'a')
    assert [(r.method, r.url.path) for r in requests] == [('GET', '/Patient/patient-2')]


@pytest.mark.parametrize('endpoint', ['interview', 'next'])
def test_missing_patient_interview_returns_clear_404_without_model(monkeypatch, endpoint):
    from fastapi import HTTPException
    from central_park import main, agent
    from central_park.tools import fhir
    monkeypatch.setattr(fhir, '_client', lambda: httpx.Client(base_url='http://test', transport=httpx.MockTransport(lambda r: httpx.Response(404))))
    monkeypatch.setattr(agent, 'get_provider', lambda: pytest.fail('Missing patient must not call the model'))
    with pytest.raises(HTTPException) as error:
        if endpoint == 'interview':
            main.run_interview_endpoint(main.InterviewRequest(patient_id='patient-2', questionnaire_response_id='q'))
        else:
            main.next_question_endpoint(main.NextQuestionRequest(patient_id='patient-2'))
    assert error.value.status_code == 404
    assert "Patient 'patient-2' was not found" in error.value.detail


@pytest.fixture
def store(monkeypatch):
    data = {}
    def read(kind, identifier, optional=False):
        result = data.get(kind + '/' + identifier)
        if result is None and not optional:
            raise ValueError('Resource missing')
        return copy.deepcopy(result)
    def put(resource):
        data[resource['resourceType'] + '/' + resource['id']] = copy.deepcopy(resource)
        return resource
    monkeypatch.setattr(care_jobs.fhir, 'read', read)
    monkeypatch.setattr(care_jobs.fhir, 'put', put)
    monkeypatch.setattr(care_jobs.fhir, 'linked', lambda *args: ({}, {}))
    monkeypatch.setattr(care_jobs.fhir, 'context', lambda *args: ctx())
    return data


def test_repeated_enqueue_and_restart_reuse_one_draft_without_model(monkeypatch, store):
    job = care_jobs.enqueue('p', 'q', 'a')
    assert job == care_jobs.enqueue('p', 'q', 'a')
    calls = []
    monkeypatch.setattr(care_jobs, 'generate', lambda context: calls.append(context) or {**draft(), 'evidence_sources': [source()], 'condition_ids': ['c'], 'result_status': 'completed'})
    task = store['Task/' + job['job_id']]
    care_jobs.process(task)
    plan = store['CarePlan/' + job['job_id']]
    assert plan['status'] == 'draft' and plan['activity'][0]['detail']['status'] == 'not-started'
    assert plan['supportingInfo'][0]['reference'] == 'QuestionnaireResponse/q'
    care_jobs.transition(task, 'running')  # Simulated restart after partial Task write.
    care_jobs.process(task)
    assert len(calls) == 1
    assert care_jobs.detail(job['job_id'])['draft']['evidence_sources'] == [source()]


def test_retry_after_insufficient_evidence_replaces_urgent_draft(monkeypatch, store):
    monkeypatch.setattr(care_jobs.fhir, 'context', lambda *args: ctx(priority='stat'))
    monkeypatch.setattr(careplan, 'retrieve', lambda *args: ([], ['hypertension']))
    job = care_jobs.enqueue('p', 'q', 'a')
    care_jobs.process(store['Task/' + job['job_id']])
    assert care_jobs.detail(job['job_id'])['status'] == 'insufficient-evidence'
    setup_model(monkeypatch, draft(), approved())
    care_jobs.retry(job['job_id'])
    care_jobs.process(store['Task/' + job['job_id']])
    result = care_jobs.detail(job['job_id'])
    assert result['status'] == 'completed' and len(result['draft']['activities']) == 2


def test_partial_plan_write_failure_visible_and_retryable(monkeypatch, store):
    monkeypatch.setattr(care_jobs, 'generate', lambda c: {**draft(), 'evidence_sources': [source()], 'condition_ids': [], 'result_status': 'completed'})
    real_put = care_jobs.fhir.put
    def fail(resource):
        if resource['resourceType'] == 'CarePlan':
            raise RuntimeError('Partial write failed')
        return real_put(resource)
    monkeypatch.setattr(care_jobs.fhir, 'put', fail)
    job = care_jobs.enqueue('p', 'q', 'a')
    care_jobs.process(store['Task/' + job['job_id']])
    assert care_jobs.detail(job['job_id'])['status'] == 'failed'
    assert 'RuntimeError' in care_jobs.detail(job['job_id'])['reason']
    monkeypatch.setattr(care_jobs.fhir, 'put', real_put)
    care_jobs.retry(job['job_id'])
    care_jobs.process(store['Task/' + job['job_id']])
    assert care_jobs.detail(job['job_id'])['status'] == 'completed'


def test_generation_does_not_hold_enqueue_lock(monkeypatch, store):
    entered, release = threading.Event(), threading.Event()
    def generate(context):
        entered.set()
        assert release.wait(3)
        return {**draft(), 'evidence_sources': [], 'condition_ids': [], 'result_status': 'completed'}
    monkeypatch.setattr(care_jobs, 'generate', generate)
    job = care_jobs.enqueue('p', 'q', 'a')
    with ThreadPoolExecutor() as pool:
        running = pool.submit(care_jobs.process, store['Task/' + job['job_id']])
        assert entered.wait(2)
        second = pool.submit(care_jobs.enqueue, 'p', 'q2', 'a2')
        try:
            assert second.result(timeout=1)['status'] == 'queued'
        finally:
            release.set()
        running.result(timeout=2)


def test_import_requires_review_and_correct_source_checksum(tmp_path):
    source = tmp_path / 'synthetic.md'
    source.write_text('# SYNTHETIC workflow\n')
    data = {'checksum': digest(source.read_bytes()), 'reviewed': False}
    with pytest.raises(ValueError, match='review'):
        validate_review(data, source)
    data['checksum'] = 'changed'
    with pytest.raises(ValueError, match='checksum'):
        validate_review(data, source)


def test_careplan_failure_cannot_block_completed_interview(monkeypatch):
    from central_park import main
    result = {'service_request_id': 'a', 'triage_level': 'see-gp'}
    monkeypatch.setattr(main, 'run_interview', lambda **kwargs: dict(result))
    monkeypatch.setattr(main.care_jobs, 'record_enqueue_failure', lambda *args: None)
    monkeypatch.setattr(main.care_jobs, 'enqueue', lambda *args: (_ for _ in ()).throw(RuntimeError('FHIR unavailable')))
    handoff = main.run_interview_endpoint(main.InterviewRequest(patient_id='p', questionnaire_response_id='q'))
    assert handoff['triage_level'] == 'see-gp' and handoff['care_plan_status'] == 'unqueued'


@pytest.mark.parametrize('advice', ['Take aspirin.', 'Use a statin.', 'Prescribe levothyroxine.', 'Insulin may help.'])
def test_specific_drugs_and_classes_rejected_without_dose(monkeypatch, advice):
    setup_model(monkeypatch, draft(advice), draft(advice))
    with pytest.raises(ValueError, match='specific drug'):
        careplan.generate(ctx())


def test_generic_followup_not_applicable_to_unknown_hypothyroidism_subtype(monkeypatch):
    reject = {'approved': False, 'issues': ['Primary/central subtype not documented'], 'applicable_source_ids': []}
    setup_model(monkeypatch, draft(), reject, draft(), reject, sources=[source('hypothyroidism')])
    with pytest.raises(ValueError, match='subtype'):
        careplan.generate(ctx('hypothyroidism'))


def test_icd_family_mapping_is_scoped_to_the_code_system():
    matched, _ = care_evidence.match_conditions([{'id': 'c', 'code': {'coding': [{'system': 'http://hl7.org/fhir/sid/icd-10', 'code': 'E11.9'}]}}])
    assert matched == {'type-2-diabetes': ['c']}
    matched, _ = care_evidence.match_conditions([{'id': 'c', 'code': {'coding': [{'system': 'https://unknown.example', 'code': 'E11.9'}]}}])
    assert matched == {}


def test_adult_eligibility_missing_does_not_apply_adult_evidence(monkeypatch):
    context = ctx(priority='urgent')
    context['patient'].pop('birthDate')
    monkeypatch.setattr(careplan, 'retrieve', lambda *args: pytest.fail('Adult eligibility unknown'))
    result = careplan.generate(context)
    assert result['result_status'] == 'insufficient-evidence'
    assert result['missing_information'] and result['activities'][0]['provenance'] == 'assessment'


def test_malformed_review_has_one_repair_and_never_saves(monkeypatch):
    provider = setup_model(monkeypatch, draft(), '{}', draft(), '{}')
    with pytest.raises(ValueError, match='one repair'):
        careplan.generate(ctx())
    assert provider.calls == 4


def test_failed_model_keeps_application_owned_urgent_instruction(monkeypatch, store):
    monkeypatch.setattr(care_jobs.fhir, 'context', lambda *args: ctx(priority='stat'))
    monkeypatch.setattr(care_jobs, 'generate', lambda *args: (_ for _ in ()).throw(ValueError('Invalid draft rejected')))
    job = care_jobs.enqueue('p', 'q', 'a')
    care_jobs.process(store['Task/' + job['job_id']])
    result = care_jobs.detail(job['job_id'])
    assert result['status'] == 'failed'
    assert len(result['draft']['activities']) == 1
    assert result['draft']['activities'][0]['provenance'] == 'assessment'
