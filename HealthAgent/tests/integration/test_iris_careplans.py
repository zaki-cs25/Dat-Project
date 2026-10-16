"""Run against the isolated docker-compose.integration.yml database only.

Artificial embedding provider + scripted model: validates wiring, not clinical accuracy.
"""
import copy
import json
import os
from pathlib import Path
import time
import subprocess
from uuid import uuid4
from fastapi.testclient import TestClient
import httpx
import pytest
from central_park import agent, care_jobs, careplan, care_evidence, main
from central_park.care_context import put, read

pytestmark = pytest.mark.skipif(os.getenv('CP_RUN_IRIS_TESTS') != '1', reason='Explicit isolated IRIS integration run required')


@pytest.fixture(autouse=True)
def config(monkeypatch):
    monkeypatch.setenv('CP_CARE_GENERATION_MODE', 'grounded')
    monkeypatch.setenv('CP_FHIR_BASE_URL', 'http://127.0.0.1:52774/care-test/fhir/r4')
    monkeypatch.setenv('CP_IRIS_REST_BASE_URL', 'http://127.0.0.1:52774/centralpark')
    monkeypatch.setenv('CP_FHIR_USER', 'care-test-user')
    monkeypatch.setenv('CP_FHIR_PASSWORD', 'CareSynthetic1!')


def passage(condition='hypertension', version='test-v1', identifier='p1'):
    document, filename = ('icmr-md-hypertension', 'hypertension.md') if condition == 'hypertension' else ('icmr-md-volume-1', 'stw_manual_v1_stw_i.md')
    return {'document_id': document, 'version_id': version,
            'passage_id': f'synthetic:{condition}:{version}:{identifier}', 'condition': condition,
            'reviewed': True, 'reviewer': 'Synthetic test', 'page': None, 'section': 'Test',
            'source_format': 'markdown', 'source_file': filename, 'line_start': 10, 'line_end': 12,
            'text': 'SYNTHETIC ONLY: Review recorded measurements with the clinician.',
            'original_text': 'SYNTHETIC ONLY: Review recorded measurements with the clinician.',
            'applicability': 'Established condition in adult test fixture.', 'exceptions': 'No prescribing.',
            'publisher': 'Synthetic test fixture', 'checksum': version,
            'title': 'Synthetic test workflow', 'version': version, 'official_url': 'https://example.invalid'}


def import_passages(*passages):
    return care_evidence.request('import', {'document_id': passages[0]['document_id'], 'version_id': passages[0]['version_id'], 'passages': list(passages)})


def markdown_passage(version):
    return passage(version=version)


def test_bulk_context_acceptance_and_rejected_candidate_guard():
    p = passage(version='bulk-context-v1')
    approval = {'actor': 'synthetic-user', 'approved_at': '2026-10-08T00:00:00Z',
                'scope': 'non-rejected-context', 'clinical_validation_complete': False}
    p.update(review_policy='showcase-bulk', evidence_role='context', original_decision='needs-review',
             clinical_validation_complete=False, bulk_approval=approval,
             workflow_review={'population': 'unknown'})
    import_passages(p)
    import_passages(p)
    hits = care_evidence.request('search', {'condition': 'hypertension', 'query': 'measurements'})['hits']
    assert any(h['evidence_role'] == 'context' and h['clinical_validation_complete'] is False for h in hits)
    bad = {**p, 'version_id': 'bulk-bad-v1', 'passage_id': 'synthetic-rejected', 'original_decision': 'exclude'}
    with pytest.raises(httpx.HTTPStatusError, match='non-rejected context'):
        import_passages(bad)
    bad = {**p, 'version_id': 'bulk-bad-v1', 'passage_id': 'synthetic-invalid-approval', 'clinical_validation_complete': True}
    with pytest.raises(httpx.HTTPStatusError, match='clinical validation'):
        import_passages(bad)


def test_enriched_draft_persists_model_and_context_attribution(monkeypatch):
    monkeypatch.setenv('CP_CARE_GENERATION_MODE', 'enriched')
    fixture = copy.deepcopy(json.loads(Path('src/python/tests/fixtures/care-evaluation.json').read_text())[1]['context'])
    patient = 'synthetic-enriched-patient'
    fixture['patient']['id'] = patient
    new_qr = fixture['questionnaire']
    new_qr.update(id='synthetic-enriched-questionnaire', subject={'reference': 'Patient/' + patient})
    assessment = fixture['assessment']
    assessment.update(id='synthetic-enriched-assessment', subject={'reference': 'Patient/' + patient},
                      priority='routine', note=[{'text': 'QR: synthetic-enriched-questionnaire'}])
    for index, condition in enumerate(fixture['conditions']):
        condition.update(id=f'synthetic-enriched-condition-{index}', subject={'reference': 'Patient/' + patient})
    for resource in [fixture['patient'], *fixture['conditions'], new_qr, assessment]:
        put(resource)
    job = care_jobs.enqueue(patient, new_qr['id'], assessment['id'])
    task = read('Task', job['job_id'])
    if care_jobs.metadata(task).get('status') != 'queued':
        care_jobs.transition(task, 'failed', 'Synthetic enriched integration reset')
        care_jobs.retry(job['job_id'])
    src = passage(version='enriched-save-v1')
    monkeypatch.setattr(careplan, 'retrieve', lambda *a: ([src], []))
    proposed = {'title': 'Synthetic enriched draft', 'activities': [
        {'category': 'follow-up', 'description': 'Discuss monitoring at the next clinician review.',
         'timing': 'At the next review', 'provenance': 'model', 'source_ids': []}],
        'missing_information': [], 'uncovered_conditions': [], 'review_notes': []}
    class Provider:
        calls = 0
        def complete(self, **kwargs):
            self.calls += 1
            return json.dumps(proposed if self.calls == 1 else {'approved': True, 'issues': [], 'review_notes': []})
    provider = Provider()
    monkeypatch.setattr(careplan, 'get_provider', lambda: provider)
    care_jobs.process(read('Task', job['job_id']))
    result = care_jobs.detail(job['job_id'])
    assert result['status'] == 'completed'
    assert result['draft']['generation_mode'] == 'enriched'
    assert result['draft']['activities'][0]['provenance'] == 'model'
    assert result['draft']['related_icmr_context'][0]['passage_id'] == src['passage_id']
    assert read('CarePlan', job['job_id'])['status'] == 'draft'
    assert care_jobs.detail(job['job_id'])['draft'] == result['draft']
    assert provider.calls == 2


def test_unicode_source_round_trip_and_idempotent_import():
    p = passage(version='unicode-v1')
    p.update(title='SYNTHETIC — Hypertension',
             text='SYNTHETIC ONLY: BP ≥140/90 mmHg; BMI <23 kg/m²; • हिन्दी.',
             original_text='SYNTHETIC ONLY: BP ≥140/90 mmHg; BMI <23 kg/m²; • हिन्दी.',
             applicability='SYNTHETIC adults ≥65; documented threshold.',
             exceptions='SYNTHETIC: clarify unknown BP ≥140/90.')
    import_passages(p)
    import_passages(p)
    hits = care_evidence.request('search', {'condition': 'hypertension', 'query': 'SYNTHETIC ≥140/90 हिन्दी'})['hits']
    found = next(h for h in hits if h['passage_id'] == p['passage_id'])
    for field in ('title', 'text', 'original_text', 'applicability', 'exceptions'):
        assert found[field] == p[field]


def archive_legacy_passage(p):
    """Simulate a previously indexed PDF without using the now-restricted importer."""
    legacy = {**p, 'document_id': 'icmr-hypertension', 'source_format': 'pdf', 'page': 1,
              'passage_id': 'legacy:' + p['passage_id']}
    literal = lambda value: '"' + value.replace('"', '""') + '"'
    output = iris_script('\n'.join([
        'set rs=##class(%SQL.Statement).%ExecDirect(,"DELETE FROM CentralPark_Data.CarePassage WHERE PassageID=?",' + literal(legacy['passage_id']) + ')',
        'set rs=##class(%SQL.Statement).%ExecDirect(,"INSERT INTO CentralPark_Data.CarePassage (PassageID,DocumentID,VersionID,ConditionTag,Reviewed,Text,Metadata,Embedding,EmbeddingProfile) SELECT ?,?,?,?,1,?,?,Embedding,EmbeddingProfile FROM CentralPark_Data.CarePassage WHERE PassageID=?",' + ','.join(literal(v) for v in [legacy['passage_id'], legacy['document_id'], legacy['version_id'], legacy['condition'], legacy['text'], json.dumps(legacy), p['passage_id']]) + ')',
        'write "ARCHIVED=",rs.%ROWCOUNT,!',
        'set rs=##class(%SQL.Statement).%ExecDirect(,"DELETE FROM CentralPark_Data.CareDocument WHERE DocumentID=?","icmr-hypertension")',
        'set rs=##class(%SQL.Statement).%ExecDirect(,"INSERT INTO CentralPark_Data.CareDocument (DocumentID,ActiveVersion) VALUES (?,?)","icmr-hypertension",' + literal(p['version_id']) + ')',
    ]))
    assert 'ARCHIVED=1' in output
    return legacy


def test_import_idempotence_activation_rollback_and_triage_isolation():
    p = passage(version='atomic-v1')
    import_passages(p)
    import_passages(p)
    legacy = archive_legacy_passage(p)
    hits = care_evidence.request('search', {'condition': 'hypertension', 'query': 'measurement', 'k': 5})['hits']
    assert [h['passage_id'] for h in hits if h['document_id'] == p['document_id']] == [p['passage_id']]
    assert not any(h['document_id'] == legacy['document_id'] for h in hits)
    explicit_hits = care_evidence.request('search', {'condition': 'hypertension', 'query': 'measurement', 'library': 'markdown'})['hits']
    assert not any(h['document_id'] == legacy['document_id'] for h in explicit_hits)
    with pytest.raises(httpx.HTTPStatusError, match='Unknown care evidence library'):
        care_evidence.request('search', {'condition': 'hypertension', 'query': 'measurement', 'library': 'pdf'})
    with pytest.raises(httpx.HTTPStatusError, match='five configured Markdown'):
        import_passages(legacy)
    new = passage(version='atomic-v2')
    bad = {**passage(version='atomic-v2', identifier='p2'), 'text': 'FORCE_EMBEDDING_FAILURE'}
    with pytest.raises(httpx.HTTPStatusError):
        import_passages(new, bad)
    hits = care_evidence.request('search', {'condition': 'hypertension', 'query': 'measurement'})['hits']
    assert next(h for h in hits if h['document_id'] == p['document_id'])['version_id'] == 'atomic-v1'
    with pytest.raises(httpx.HTTPStatusError):
        import_passages({**new, 'reviewed': False})
    import_passages(new)
    hits = care_evidence.request('search', {'condition': 'hypertension', 'query': 'measurement'})['hits']
    own = [h for h in hits if h['document_id'] == p['document_id']]
    assert len(own) == 1 and own[0]['version_id'] == 'atomic-v2'
    # Wrong condition cannot return the document. Interview collection remains separate.
    assert care_evidence.request('search', {'condition': 'unsupported', 'query': 'measurement'})['hits'] == []
    from central_park.tools.vector import search_guidelines
    assert not any(p['passage_id'] in str(hit) for hit in search_guidelines('measurement'))


@pytest.mark.parametrize('change,reason', [
    ({'source_format': 'pdf', 'page': 1}, 'Only Markdown'),
    ({'source_file': 'unlisted.md'}, 'filename'),
    ({'line_start': 0}, 'line reference'),
    ({'line_end': 9}, 'line reference'),
    ({'page': 1}, 'source lines'),
])
def test_import_rejects_non_markdown_or_invalid_source_references(change, reason):
    with pytest.raises(httpx.HTTPStatusError, match=reason):
        import_passages({**passage(version='invalid-source'), **change})


def test_condition_tags_expand_without_changing_the_eight_original_names():
    p = {**passage('synthetic-new-condition', 'expanded-v1'),
         'document_id': 'icmr-md-volume-2', 'source_file': 'stw_v2.md'}
    import_passages(p)
    hits = care_evidence.request('search', {'condition': 'synthetic-new-condition', 'query': 'measurements'})['hits']
    assert [h['passage_id'] for h in hits] == [p['passage_id']]
    for bad in ('../escape', 'UPPERCASE', 'bad_tag', 'a'*65):
        with pytest.raises(httpx.HTTPStatusError, match='Invalid condition tag'):
            import_passages({**p, 'condition': bad})


class ScriptedProvider:
    def __init__(self):
        self.care_calls = 0
    def complete(self, system, messages, **kwargs):
        payload = json.loads(messages[0]['content'].split('\nRepair feedback:')[0])
        if 'SCHEMA:' in system:
            self.care_calls += 1
            return json.dumps({'title': 'SYNTHETIC INTEGRATION draft', 'activities': [{
                'category': 'monitoring', 'description': 'Review recorded measurements with the clinician.',
                'provenance': 'icmr', 'source_ids': [payload['evidence'][0]['passage_id']]}],
                'missing_information': [], 'uncovered_conditions': [], 'review_notes': ['Synthetic scripted model; no clinical validation.']})
        if 'applicable_source_ids' in system:
            return json.dumps({'approved': True, 'issues': [], 'applicable_source_ids': [p['passage_id'] for p in payload['evidence']]})
        if 'verdict' in system:
            return json.dumps({'verdict': 'confirm', 'note': ''})
        return json.dumps({'triage_level': 'urgent-care', 'chief_complaint': 'Synthetic test concern',
            'hpi': 'Synthetic test handoff.', 'red_flags': [], 'recommended_actions': ['Seek urgent care now.'], 'citations': []})


def seed_one():
    fixture = json.loads(Path('src/python/tests/fixtures/care-evaluation.json').read_text())[1]['context']
    for r in [fixture['patient'], *fixture['conditions'], fixture['questionnaire']]:
        put(r)
    return fixture['patient']['id'], fixture['questionnaire']['id']


def wait_for(job_id, states, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = care_jobs.detail(job_id)
        if result['status'] in states:
            return result
        time.sleep(.1)
    pytest.fail('Worker did not reach expected state')


def test_interview_automatic_task_cited_draft_reopen_and_restart(monkeypatch):
    import_passages(markdown_passage('e2e-v1'))
    # Even when legacy evidence is active, new drafts search only Markdown.
    archive_legacy_passage(markdown_passage('e2e-v1'))
    hits, missing = care_evidence.retrieve({'hypertension': ['test-condition']}, 'measurement')
    assert not missing and all(p['document_id'] == 'icmr-md-hypertension' for p in hits)
    provider = ScriptedProvider()
    monkeypatch.setattr(agent, 'get_provider', lambda: provider)
    monkeypatch.setattr(careplan, 'get_provider', lambda: provider)
    monkeypatch.setattr(agent, 'search_guidelines', lambda *args, **kwargs: [])
    for name in ['wait_for_fhir', 'seed_questionnaire', 'seed_demo_patients', 'seed_guidelines']:
        monkeypatch.setattr(main, name, lambda: None)
    patient, questionnaire = seed_one()
    # Stable IDs make rerunning the test idempotent; reset only this synthetic test Task.
    job_id = care_jobs.key(patient, questionnaire)
    task = read('Task', job_id, optional=True)
    if task:
        care_jobs.transition(task, 'failed', 'Synthetic integration reset')
        care_jobs.retry(job_id)
    with TestClient(main.app) as client:
        response = client.post('/interview', json={'patient_id': patient, 'questionnaire_response_id': questionnaire})
        assert response.status_code == 200, response.text
        handoff = response.json()
        assert handoff['triage_level'] == 'urgent-care'
        assert handoff['care_plan_job_id'] == job_id
        result = wait_for(job_id, {'completed'})
        assert result['draft']['activities'][0]['provenance'] == 'assessment'
        assert result['draft']['evidence_sources'][0]['page'] is None
        assert result['draft']['evidence_sources'][0]['line_start'] == 10
        plan = read('CarePlan', job_id)
        assert plan['status'] == 'draft' and all(a['detail']['status'] == 'not-started' for a in plan['activity'])
        count = provider.care_calls
        assert client.get('/careplans/' + job_id).status_code == 200
        assert provider.care_calls == count
        again = client.post('/careplan', json={'patient_id': patient, 'questionnaire_response_id': questionnaire,
                                               'assessment_id': handoff['service_request_id']})
        assert again.json()['job_id'] == job_id
    # Persist a running state as if the service crashed after saving the CarePlan.
    task = read('Task', job_id)
    care_jobs.transition(task, 'running')
    with TestClient(main.app):
        wait_for(job_id, {'completed'})
    assert provider.care_calls == count
    # A replacement corpus doesn't alter citation versions in a reopened draft.
    import_passages(markdown_passage('e2e-v2'))
    assert care_jobs.detail(job_id)['draft']['evidence_sources'][0]['version_id'] == 'e2e-v1'


def test_new_patient_registration_interview_and_worklist(monkeypatch):
    from central_park import interview
    from central_park.care_context import search
    from central_park.tools.fhir import post_questionnaire_response, get_patient_context
    monkeypatch.setenv('CP_CARE_GENERATION_MODE', 'enriched')
    provider = ScriptedProvider()
    monkeypatch.setattr(agent, 'get_provider', lambda: provider)
    monkeypatch.setattr(agent, 'search_guidelines', lambda *args, **kwargs: [])
    monkeypatch.setattr(interview, 'search_guidelines', lambda *args, **kwargs: [])
    class Questions:
        def complete(self, **kwargs):
            return json.dumps({'done': False, 'question': {'kind': 'text', 'link_id': 'duration', 'prompt': 'How long has this been bothering you?'}})
    class Care:
        def complete(self, system, **kwargs):
            if 'SCHEMA:' in system:
                return json.dumps({'title': 'Synthetic new-patient draft', 'activities': [{
                    'category': 'follow-up', 'description': 'Discuss the current concern with the clinician.',
                    'provenance': 'model', 'source_ids': []}],
                    'missing_information': ['Past clinical history is unrecorded.'],
                    'uncovered_conditions': [], 'review_notes': []})
            return json.dumps({'approved': True, 'issues': [], 'review_notes': []})
    monkeypatch.setattr(interview, 'get_provider', lambda: Questions())
    monkeypatch.setattr(careplan, 'get_provider', lambda: Care())
    monkeypatch.setattr(careplan, 'retrieve', lambda *args: ([], []))
    for name in ['wait_for_fhir', 'seed_questionnaire', 'seed_demo_patients', 'seed_guidelines']:
        monkeypatch.setattr(main, name, lambda: None)
    registration = {'registration_id': str(uuid4()), 'full_name': 'SYNTHETIC New Patient हिन्दी',
                    'birth_date': '1980-01-01', 'gender': 'unknown'}
    with TestClient(main.app) as client:
        response = client.post('/patients', json=registration)
        assert response.status_code == 200, response.text
        patient = response.json()['patient_id']
        assert client.post('/patients', json=registration).json()['patient_id'] == patient
        record = read('Patient', patient)
        assert record['name'][0]['text'] == registration['full_name']
        assert get_patient_context(patient)['patient']['name'] == registration['full_name']
        matches = search('Patient', identifier='urn:central-park:patient-registration|' + registration['registration_id'])
        assert len(matches) == 1
        for kind in ['Condition', 'MedicationRequest', 'AllergyIntolerance', 'Observation']:
            assert search(kind, patient=patient) == []
        answers = [{'link_id': 'chief-complaint', 'question': 'What brings you here?', 'answer': 'A mild concern for a clinician review.'}]
        question = client.post('/interview/next', json={'patient_id': patient, 'answers': answers, 'language': 'Hindi'})
        assert question.status_code == 200 and not question.json()['done']
        questionnaire = post_questionnaire_response(patient, answers)
        response = client.post('/interview', json={'patient_id': patient, 'questionnaire_response_id': questionnaire})
        assert response.status_code == 200, response.text
        result = wait_for(response.json()['care_plan_job_id'], {'completed'})
        assert result['draft']['generation_mode'] == 'enriched'
        assert result['context']['patient']['id'] == patient
        assert result['context']['conditions'] == []
        assert read('CarePlan', result['job_id'])['status'] == 'draft'
        row = next(r for r in care_jobs.worklist(0, 1000000)['items'] if r['job_id'] == result['job_id'])
        assert row['patient_name'] == registration['full_name']


def test_insufficient_urgent_draft_and_retry(monkeypatch):
    provider = ScriptedProvider()
    monkeypatch.setattr(careplan, 'get_provider', lambda: provider)
    patient, questionnaire = seed_one()
    key = care_jobs.key(patient, questionnaire)
    task = read('Task', key)
    care_jobs.transition(task, 'failed', 'Synthetic test')
    care_jobs.retry(key)
    actual_retrieve = careplan.retrieve
    monkeypatch.setattr(careplan, 'retrieve', lambda *args: ([], ['hypertension']))
    care_jobs.process(read('Task', key))
    result = care_jobs.detail(key)
    assert result['status'] == 'insufficient-evidence'
    assert result['draft']['activities'][0]['provenance'] == 'assessment'
    monkeypatch.setattr(careplan, 'retrieve', actual_retrieve)
    care_jobs.retry(key)
    care_jobs.process(read('Task', key))
    assert care_jobs.detail(key)['status'] == 'completed'


def iris_script(script, settings=None):
    command = ['docker', 'compose', '-p', 'icmr-eval', '-f', 'docker-compose.integration.yml', 'exec', '-T']
    for key, value in (settings or {}).items():
        command += ['-e', key + '=' + str(value)]
    command += ['iris', 'iris', 'session', 'IRIS', '-U', 'CENTRALPARK']
    result = subprocess.run(command, input=script + '\nhalt\n', text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return result.stdout


def configure_embedding(model='synthetic-384', dimensions=384, provider='openai_compatible', **overrides):
    settings = {'CP_EMBEDDING_PROVIDER': provider, 'CP_EMBEDDING_MODEL': model,
                'CP_EMBEDDING_DIMENSIONS': dimensions, 'CP_EMBEDDING_BASE_URL': 'http://embedding-fixture:8080/tenant/v1',
                'CP_EMBEDDING_API_KEY': 'synthetic-embedding-key', 'CP_EMBEDDING_SEND_DIMENSIONS': 'false',
                'CP_EMBEDDING_REVISION': '', 'OPENAI_API_KEY': 'synthetic-fallback-key', **overrides}
    return iris_script('set sc=##class(CentralPark.Install).InstallEmbeddingConfig()\nwrite "CONFIG_STATUS=",$select(sc:1,1:0),!', settings)


@pytest.fixture
def embedding_config_snapshot():
    # Only the isolated database; don't change production configs or credentials.
    iris_script('set c=##class(CentralPark.Embedding.Service).Config()\nset ^CareTestConfig=$listbuild(c.EmbeddingClass,c.Configuration,c.VectorLength,c.Description)')
    yield
    iris_script('set c=##class(CentralPark.Embedding.Service).Config()\nset c.EmbeddingClass=$list(^CareTestConfig,1),c.Configuration=$list(^CareTestConfig,2),c.VectorLength=$list(^CareTestConfig,3),c.Description=$list(^CareTestConfig,4)\ndo c.%Save()\nkill ^CareTestConfig')


def fixture_calls():
    response = httpx.get('http://127.0.0.1:52775/calls')
    response.raise_for_status()
    return response.json()


def vector_request(path, body):
    response = httpx.post('http://127.0.0.1:52774/centralpark/vector/' + path, json=body,
                          auth=('care-test-user', 'CareSynthetic1!'), timeout=60)
    response.raise_for_status()
    return response.json()


def test_custom_embedding_models_dimensions_reindex_and_ollama(embedding_config_snapshot):
    p = passage('asthma', 'custom-embedding-v1')
    seed = [{'slug': 'synthetic-embedding-test', 'source': 'Synthetic fixture', 'snippet': 'SYNTHETIC ONLY measurement review'}]
    assert 'CONFIG_STATUS=1' in configure_embedding()
    import_passages(p)
    before = len(fixture_calls())
    import_passages(p)
    assert len(fixture_calls()) == before  # same source and model: no re-embedding
    assert care_evidence.request('search', {'condition': 'asthma', 'query': 'measurement'})['hits'][0]['passage_id'] == p['passage_id']
    assert vector_request('seed', seed)['errors'] == 0
    assert vector_request('search', {'query': 'measurement'})['hits']
    request = fixture_calls()[-1]
    assert request['path'] == '/tenant/v1/embeddings'
    assert request['auth'] == 'Bearer synthetic-embedding-key'
    assert request['body']['model'] == 'synthetic-384' and 'dimensions' not in request['body']

    # Even a model change with equal dimensions requires reindexing.
    assert 'CONFIG_STATUS=1' in configure_embedding('synthetic-384-v2')
    with pytest.raises(httpx.HTTPStatusError, match='503'):
        care_evidence.request('search', {'condition': 'asthma', 'query': 'measurement'})
    import_passages(p)
    assert care_evidence.request('search', {'condition': 'asthma', 'query': 'measurement'})['hits']

    # A different vector dimension works without truncation, padding or data deletion.
    assert 'CONFIG_STATUS=1' in configure_embedding('synthetic-768', 768)
    with pytest.raises(httpx.HTTPStatusError, match='503'):
        care_evidence.request('search', {'condition': 'asthma', 'query': 'measurement'})
    with pytest.raises(httpx.HTTPStatusError):
        vector_request('search', {'query': 'measurement'})
    import_passages(p)
    assert care_evidence.request('search', {'condition': 'asthma', 'query': 'measurement'})['hits'][0]['version_id'] == 'custom-embedding-v1'
    iris_script('set rs=##class(%SQL.Statement).%ExecDirect(,"UPDATE CentralPark_Data.CarePassage SET EmbeddingProfile=NULL WHERE ConditionTag=\'asthma\'")')
    with pytest.raises(httpx.HTTPStatusError, match='republish'):
        care_evidence.request('search', {'condition': 'asthma', 'query': 'measurement'})
    import_passages(p)  # older installations without fingerprints can be upgraded in place
    assert vector_request('seed', seed)['errors'] == 0
    assert vector_request('search', {'query': 'measurement'})['hits']
    before = len(fixture_calls())
    assert 'CONFIG_STATUS=1' in configure_embedding('synthetic-768', 768, CP_EMBEDDING_API_KEY='synthetic-rotated-key')
    import_passages(p)
    assert len(fixture_calls()) == before  # rotating credentials doesn't change vector space

    assert 'CONFIG_STATUS=1' in configure_embedding('synthetic-384', 384, CP_EMBEDDING_SEND_DIMENSIONS='true')
    import_passages(p)
    assert fixture_calls()[-1]['body']['dimensions'] == 384
    assert 'CONFIG_STATUS=1' in configure_embedding('synthetic-384', 384, provider='ollama', CP_EMBEDDING_BASE_URL='http://embedding-fixture:8080', CP_EMBEDDING_API_KEY='')
    import_passages(p)
    assert care_evidence.request('search', {'condition': 'asthma', 'query': 'measurement'})['hits']
    request = fixture_calls()[-1]
    assert request['path'] == '/api/embed' and request['body']['truncate'] is False
    assert request['auth'] is None


def test_native_embedding_model_and_dimensions_are_configurable(embedding_config_snapshot):
    assert 'CONFIG_STATUS=1' in configure_embedding('text-embedding-3-large', 3072, provider='openai', CP_EMBEDDING_BASE_URL='', CP_EMBEDDING_API_KEY='')
    output = iris_script('set c=##class(CentralPark.Embedding.Service).Config(),d={}.%FromJSON(c.Configuration)\nwrite "CLASS=",c.EmbeddingClass,";MODEL=",d.%Get("modelName"),";DIMENSIONS=",c.VectorLength,";KEY_FALLBACK=",(d.%Get("apiKey")="synthetic-fallback-key"),!')
    assert 'CLASS=%Embedding.OpenAI;MODEL=text-embedding-3-large;DIMENSIONS=3072;KEY_FALLBACK=1' in output


@pytest.mark.parametrize('kind', ['wrong', 'string', 'zero', 'error'])
def test_invalid_embedding_response_rejected(kind, embedding_config_snapshot):
    assert 'CONFIG_STATUS=1' in configure_embedding('synthetic-384-' + kind)
    reason = {'wrong': 'dimension mismatch', 'string': 'non-numeric', 'zero': 'zero vector', 'error': 'HTTP 401'}[kind]
    with pytest.raises(httpx.HTTPStatusError, match=reason):
        import_passages(passage('copd', 'invalid-response-' + kind))


@pytest.mark.parametrize('setting,value', [('CP_EMBEDDING_DIMENSIONS', '0'), ('CP_EMBEDDING_PROVIDER', 'unknown'),
                                          ('CP_EMBEDDING_BASE_URL', 'file:///tmp/model'), ('CP_EMBEDDING_SEND_DIMENSIONS', 'maybe')])
def test_invalid_embedding_config_preserves_previous(setting, value, embedding_config_snapshot):
    fingerprint = iris_script('write "PROFILE=",##class(CentralPark.Embedding.Service).Profile(##class(CentralPark.Embedding.Service).Config()),!').split('PROFILE=')[-1].splitlines()[0]
    assert 'CONFIG_STATUS=0' in configure_embedding(**{setting: value})
    after = iris_script('write "PROFILE=",##class(CentralPark.Embedding.Service).Profile(##class(CentralPark.Embedding.Service).Config()),!').split('PROFILE=')[-1].splitlines()[0]
    assert after == fingerprint


def test_embedding_reindex_failure_saves_urgent_instruction(embedding_config_snapshot):
    fixture = copy.deepcopy(json.loads(Path('src/python/tests/fixtures/care-evaluation.json').read_text())[1]['context'])
    patient, questionnaire, assessment = 'synthetic-embedding-failure', 'synthetic-embedding-failure-qr', 'synthetic-embedding-failure-assessment'
    fixture['patient']['id'] = patient
    fixture['questionnaire'].update(id=questionnaire, subject={'reference': 'Patient/' + patient})
    fixture['assessment'].update(id=assessment, subject={'reference': 'Patient/' + patient}, priority='urgent',
                                 note=[{'text': 'QR: ' + questionnaire}, {'text': 'Action: Seek urgent care now.'}])
    for condition in fixture['conditions']:
        condition.update(id=patient + '-condition', subject={'reference': 'Patient/' + patient})
    for resource in [fixture['patient'], *fixture['conditions'], fixture['questionnaire'], fixture['assessment']]:
        put(resource)
    assert 'CONFIG_STATUS=1' in configure_embedding()
    job = care_jobs.enqueue(patient, questionnaire, assessment)
    if job['status'] == 'failed':
        care_jobs.retry(job['job_id'])
    care_jobs.process(read('Task', job['job_id']))
    result = care_jobs.detail(job['job_id'])
    assert result['status'] == 'failed' and 'republish' in result['reason']
    assert result['draft']['activities'][0]['provenance'] == 'assessment'
    plan = read('CarePlan', job['job_id'])
    assert plan['status'] == 'draft' and 'addresses' not in plan
