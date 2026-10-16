"""Synthetic manuals only: coverage, review gates and citation integrity."""
import copy
import json
from pathlib import Path
import pytest
from central_park import care_preparation as prep, import_care_documents as importer, care_evidence
from central_park.care_catalogue import catalogue, inventory_catalogue


@pytest.fixture(autouse=True)
def grounded_generation_contract(monkeypatch):
    monkeypatch.setenv('CP_CARE_GENERATION_MODE', 'grounded')


@pytest.fixture
def manual(tmp_path, monkeypatch):
    source = tmp_path / 'synthetic.md'
    source.write_text('# Standard Treatment Workflow (STW) for the Management of\n'
        '# SYNTHETIC ALPHA IN ADULTS\n# ICD-10-J60\n'
        '## Monitoring\nOnly when stable.\n\n| Branch | Exception |\n| --- | --- |\n'
        '| ALL criteria | Exclude acute illness |\n\n* Footnote: retain the prerequisite.\n\n'
        'Standard Treatment Workflow (STW) for the Management of SYNTHETIC BETA\n'
        'ICD-10-K70.9\n### Follow-up\nReview documented results with clinician.\n')
    document = dict(document_id='icmr-md-synthetic', filename=source.name, source_format='markdown',
        publisher='Synthetic fixture', official_url='https://example.invalid', official_url_kind='catalogue',
        title='Synthetic manual', version='synthetic-v1', workflow_mode='discover')
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps([document]))
    monkeypatch.setattr(importer, 'MANIFEST', manifest)
    return source, document


def approve(manual):
    source, document = manual
    data = importer.prepare(source, document)
    data.update(reviewed=True, reviewer='Synthetic reviewer', reviewed_at='2026-10-08')
    for w in data['workflows']:
        w.update(reviewed=True, reviewer='Synthetic reviewer', reviewed_at='2026-10-08', population='adult')
    p = next(p for p in data['passages'] if p['section'] == 'Monitoring')
    p.update(include=True, reviewed=True, decision='include', category='monitoring',
             applicability='Established adult synthetic condition; stable.', exceptions='Exclude acute illness.')
    candidate = inventory_catalogue([data])
    for entry in candidate['entries'].values():
        entry.update(reviewed=True, enabled=True, population='adult', reviewer='Synthetic reviewer',
            reviewed_at='2026-10-08', aliases=entry['candidate_aliases'], codes=entry['candidate_codes'])
    target = source.parent / '.preparation/catalogue.json'
    importer.write_json(target, candidate)
    return data, p, target


def test_discovery_plain_split_markers_and_code_only_headers(manual):
    source, document = manual
    data = importer.prepare(source, document)
    assert len(data['workflows']) == 2
    assert [w['codes'] for w in data['workflows']] == [['J60'], ['K70.9']]
    assert data['workflows'][0]['title'] == 'SYNTHETIC ALPHA IN ADULTS'
    assert data['workflows'][0]['line_end'] < data['workflows'][1]['line_start']
    assert all(not w['reviewed'] for w in data['workflows'])
    assert all(not p['include'] and not p['reviewed'] for p in data['passages'])


def test_plain_bold_title_is_not_skipped_for_next_subsection():
    lines = ['Standard Treatment Workflow (STW) for the\n', '**SYNTHETIC CONDITION**\n',
             'ICD-10-J60\n', '# WHEN TO SUSPECT?\n', 'Data.\n']
    workflows = prep.discover(lines, {'document_id': 'test'})
    assert workflows[0]['title'] == 'SYNTHETIC CONDITION'
    assert workflows[0]['codes'] == ['J60']


def test_fenced_workflow_text_and_secondary_body_codes_are_not_inventory():
    lines = ['# Standard Treatment Workflow (STW) SYNTHETIC ALPHA\n', 'ICD-10-J60\n',
             '## Monitoring\n', 'Associated ICD-10-K70.9 is body context.\n', '```\n',
             'Standard Treatment Workflow (STW) IGNORE EXAMPLE\n', '```\n']
    workflows = prep.discover(lines, {'document_id': 'test'})
    assert len(workflows) == 1 and workflows[0]['codes'] == ['J60']


def test_large_subtree_splits_at_headings_and_retains_parent_context():
    lines = ['# Standard Treatment Workflow (STW) SYNTHETIC ALPHA\n', '## Monitoring\n',
             'Only when stable.\n', '### Branch A\n', 'x'*4000+'\n', '### Branch B\n', 'y'*4000+'\n']
    w = prep.discover(lines, {'document_id': 'test'})[0]
    spans = list(prep.source_spans(lines, w))
    branch = next(p for p in spans if p['section'] == 'Branch A')
    assert branch['parent_context_spans'][0]['original_text'].endswith('Only when stable.\n')
    assert all(len(p['original_text']) <= 6000 for p in spans)


def test_reviewed_new_condition_can_publish_with_line_citations(manual):
    source, _ = manual
    data, p, _ = approve(manual)
    body = importer.import_body(data, source)
    assert len(body['passages']) == 1
    row = body['passages'][0]
    assert row['condition'] not in care_evidence.CATALOGUE
    assert row['workflow_title'] == data['workflows'][0]['title']
    assert row['page'] is None and row['line_start'] == p['line_start']
    assert '| ALL criteria |' in row['text'] and 'Footnote' in row['text']


def test_unselected_parent_context_and_classifier_notes_never_enter_rag(manual):
    source, _ = manual
    data, p, _ = approve(manual)
    p['parent_context_spans'] = [{'original_text': 'UNSELECTED diagnostic and prescribing context'}]
    p['decision_reason'] = 'Private classifier explanation'
    first = importer.import_body(data,source)
    p['decision_reason'] = 'Changed private explanation'
    assert first == importer.import_body(data,source)
    encoded = json.dumps(importer.import_body(data,source))
    assert 'UNSELECTED' not in encoded and 'Private classifier' not in encoded


@pytest.fixture
def reviewed_cell(manual):
    source, _ = manual
    row = '| Stable adults ≥65<br>Measure `a|b` and escaped \\| values; exclude acute illness. | UNSELECTED medication change 99 mg |\n'
    source.write_text('# Standard Treatment Workflow (STW) SYNTHETIC ALPHA IN ADULTS\n'
        'ICD-10-J60\n## Monitoring\n| Recommendation | Excluded |\n| --- | --- |\n' + row)
    data, p, target = approve(manual)
    context = dict(line_start=1, line_end=2, original_text=''.join(source.read_text().splitlines(keepends=True)[:2]))
    start, end = 1, row.index('| UNSELECTED')
    p.update(line_start=6, line_end=6, original_text=row, char_start=start, char_end=end,
        selection_review=dict(reviewed=True, reviewer='Synthetic reviewer', reviewed_at='2026-10-08',
            unit_type='complete-table-cell', rationale='Entire conditional cell selected with its exception.'),
        context_spans=[context], text=row[start:end] + '\n\n' + context['original_text'])
    return source, data, p, target


def test_reviewed_cell_exports_only_exact_selection_and_preserves_citation(reviewed_cell):
    source, data, p, _ = reviewed_cell
    body = importer.import_body(data, source)
    row = body['passages'][0]
    assert row['original_text'] == p['original_text'][p['char_start']:p['char_end']]
    assert row['text'] == p['text'] and row['line_start'] == row['line_end'] == 6
    assert (row['char_start'], row['char_end']) == (p['char_start'], p['char_end'])
    assert row['source_line_checksum'] == importer.digest(p['original_text'].encode())
    assert '≥65' in row['text'] and 'exclude acute illness' in row['text']
    assert '`a|b`' in row['text'] and '\\|' in row['text']
    assert 'UNSELECTED' not in json.dumps(body) and '99 mg' not in json.dumps(body)
    assert 'UNSELECTED' in p['original_text']  # private audit span remains intact
    assert importer.import_body(data, source) == body  # stable IDs/version on repeat


@pytest.mark.parametrize('change,reason', [
    (lambda p: p.pop('char_end'), 'character offsets'),
    (lambda p: p.update(char_start=True), 'character offsets'),
    (lambda p: p.update(char_end=1.5), 'character offsets'),
    (lambda p: p.update(char_start=-1), 'character offsets'),
    (lambda p: p.update(char_end=9999), 'character offsets'),
    (lambda p: p.update(char_end=20), 'complete table cell'),
    (lambda p: p.update(char_end=len(p['original_text'])-2), 'complete table cell'),
    (lambda p: p.update(selection_review={}), 'selection review'),
    (lambda p: p['selection_review'].update(reviewed=False), 'selection review'),
    (lambda p: p['selection_review'].update(reviewer=''), 'selection review'),
    (lambda p: p['selection_review'].update(unit_type='partial-bullet'), 'selection review'),
    (lambda p: p.update(text='Rewritten selected recommendation'), 'verbatim'),
    (lambda p: p.update(original_text='fabricated audit line'), 'excerpt'),
])
def test_cell_selection_rejects_fabrication_incomplete_branches_and_missing_review(reviewed_cell, change, reason):
    source, data, p, _ = reviewed_cell
    change(p)
    with pytest.raises(ValueError, match=reason):
        importer.import_body(data, source)


def test_supporting_cell_context_does_not_expose_adjacent_excluded_material(reviewed_cell):
    source, data, p, _ = reviewed_cell
    selected_context = {k: copy.deepcopy(p[k]) for k in (
        'line_start', 'line_end', 'original_text', 'char_start', 'char_end', 'selection_review')}
    heading = p['context_spans'][0]
    selected_text = p['original_text'][p['char_start']:p['char_end']]
    for k in ('char_start', 'char_end', 'selection_review'):
        p.pop(k)
    p.update(**heading, context_spans=[selected_context], text=heading['original_text']+'\n\n'+selected_text)
    row = importer.import_body(data, source)['passages'][0]
    assert row['context_spans'][0]['original_text'] == selected_text
    assert row['context_spans'][0]['char_start'] == selected_context['char_start']
    assert 'UNSELECTED' not in json.dumps(row)


def test_cell_selection_offsets_invalidate_version_without_duplicating_selected_text(reviewed_cell):
    source, data, p, _ = reviewed_cell
    first = importer.import_body(data, source)
    # Trimming only surrounding cell whitespace is still an exact full-cell selection.
    p['char_start'] += 1
    p['text'] = p['original_text'][p['char_start']:p['char_end']] + '\n\n' + p['context_spans'][0]['original_text']
    second = importer.import_body(data, source)
    assert first['version_id'] != second['version_id']
    assert len(second['passages']) == 1


def test_expanded_condition_generates_a_cited_draft(manual, monkeypatch):
    from central_park import careplan
    from test_careplan import Provider, draft, approved
    source, _ = manual
    data, _, target = approve(manual)
    passage = importer.import_body(data,source)['passages'][0]
    monkeypatch.setenv('CP_CARE_CATALOGUE_PATH',str(target))
    monkeypatch.setattr(care_evidence,'request',lambda *a: {'hits':[passage]})
    monkeypatch.setattr(careplan,'get_provider',lambda: Provider(draft(ids=[passage['passage_id']]), approved([passage['passage_id']])))
    ctx = dict(patient={'id':'synthetic','birthDate':'1970-01-01'},
        conditions=[{'id':'new-condition','code':{'text':'SYNTHETIC ALPHA IN ADULTS'}}],
        questionnaire={'id':'q','status':'completed','item':[]}, assessment={'id':'a','priority':'routine'},
        medications=[],allergies=[],observations=[])
    result = careplan.generate(ctx)
    assert result['result_status'] == 'completed'
    assert result['condition_ids'] == ['new-condition'] and not result['uncovered_conditions']
    assert result['evidence_sources'][0]['passage_id'] == passage['passage_id']


def test_retrieval_consolidates_exact_duplicates_without_dropping_exceptions(monkeypatch):
    base = dict(passage_id='a',condition='synthetic-extra',reviewed=True,text='SYNTHETIC review.',
        applicability='Stable adults.',exceptions='Exclude acute illness.',category='monitoring')
    monkeypatch.setattr(care_evidence,'request',lambda *a:{'hits':[
        base, dict(base,passage_id='same-text-other-document'), dict(base,passage_id='different-exception',exceptions='Another exception.')]})
    sources,missing = care_evidence.retrieve({'synthetic-extra':['c']},'measurements')
    assert not missing and [s['passage_id'] for s in sources] == ['a','different-exception']


@pytest.mark.parametrize('change,reason', [
    (lambda d,p: d['workflows'][0].update(reviewed=False), 'mapping review'),
    (lambda d,p: d['workflows'][0].update(population='pediatric'), 'Adult applicability'),
    (lambda d,p: p.update(decision='exclude'), 'management recommendations'),
    (lambda d,p: p.update(category='diagnosis'), 'management recommendations'),
    (lambda d,p: p.update(text='Rewritten instruction'), 'verbatim'),
    (lambda d,p: p.update(line_end=999), 'boundary'),
    (lambda d,p: p.update(context_spans=[dict(line_start=999,line_end=999,original_text='invented')]), 'boundary'),
    (lambda d,p: p.update(original_text='invented'), 'excerpt'),
    (lambda d,p: p.update(condition='another-workflow'), 'mapped workflow'),
])
def test_new_review_validation_blocks_incomplete_or_fabricated_selection(manual, change, reason):
    source, _ = manual
    data, p, _ = approve(manual)
    change(data, p)
    with pytest.raises(ValueError, match=reason):
        importer.import_body(data, source)


def test_pending_mapping_never_indexes_or_matches_patient(manual, monkeypatch):
    source, _ = manual
    data, p, target = approve(manual)
    mappings = json.loads(target.read_text())
    for entry in mappings['entries'].values():
        entry.update(reviewed=False, enabled=False)
    target.write_text(json.dumps(mappings))
    monkeypatch.setenv('CP_CARE_CATALOGUE_PATH', str(target))
    with pytest.raises(ValueError, match='catalogue mappings'):
        importer.import_body(data, source)
    matched, uncovered = care_evidence.match_conditions([{'id':'new', 'code':{'text':'synthetic alpha in adults'}}])
    assert matched == {} and uncovered


def test_expanded_matching_uses_reviewed_exact_codes_and_names(manual, monkeypatch):
    _, _, target = approve(manual)
    monkeypatch.setenv('CP_CARE_CATALOGUE_PATH', str(target))
    matched, _ = care_evidence.match_conditions([{'id':'new','code':{'coding':[
        {'system':'http://hl7.org/fhir/sid/icd-10','code':'J60'}]}}])
    assert 'synthetic-alpha-in-adults' in matched
    assert care_evidence.match_conditions([{'id':'wrong','code':{'coding':[
        {'system':'https://wrong.invalid','code':'J60'}]}}])[0] == {}
    assert care_evidence.match_conditions([{'id':'wrong','code':{'coding':[
        {'system':'http://hl7.org/fhir/sid/icd-10','code':'K70.90'}]}}])[0] == {}


def test_source_revision_disables_existing_candidate_catalogue_approvals(manual):
    source, _ = manual
    data, _, target = approve(manual)
    old = json.loads(target.read_text())
    data['checksum'] = 'new-source-hash'
    result = inventory_catalogue([data], old)
    assert all(not e['reviewed'] and not e['enabled'] for e in result['entries'].values())


def test_duplicate_recommendations_preserve_alternative_source_lines(manual):
    source, _ = manual
    data, p, _ = approve(manual)
    duplicate = dict(p, passage_id='different-source-id')
    data['passages'].append(duplicate)
    body = importer.import_body(data, source)
    assert len(body['passages']) == 1
    assert body['passages'][0]['duplicate_sources'][0]['passage_id'] == 'different-source-id'


def test_excluded_workflows_do_not_force_an_activity(manual):
    source, _ = manual
    data, p, _ = approve(manual)
    p.update(include=False)
    assert importer.import_body(data, source)['passages'] == []


def test_classification_cache_and_application_do_not_approve_sources(manual, tmp_path):
    source, document = manual
    data = importer.prepare(source, document)
    p = next(p for p in data['passages'] if p['section'] == 'Monitoring')
    w = data['workflows'][0]
    lines = source.read_text().splitlines(keepends=True)
    decisions = [dict(line_start=p['line_start'],line_end=p['line_end'],decision='include',
        category='monitoring',reason='Synthetic monitoring with complete table and prerequisites.',context_spans=[])]
    class Provider:
        calls = 0
        def complete(self, **kwargs):
            self.calls += 1
            assert kwargs['max_tokens'] == 3072
            return json.dumps(dict(decisions=decisions))
    provider = Provider()
    for _ in range(2):
        prep.classify_section(p,w,lines,provider,tmp_path/'cache','synthetic-model')
    assert provider.calls == 1
    prep.classify_section(p,w,lines,provider,tmp_path/'cache','changed-model')
    assert provider.calls == 2
    records = dict(document_id=data['document_id'],checksum=data['checksum'],sections={p['passage_id']:dict(decisions=decisions)})
    result = importer.apply_classification(data,source,records)
    assert any(p['decision'] == 'include' for p in result['passages'])
    assert all(not p['include'] and not p['reviewed'] for p in result['passages'])


def test_oversized_context_is_not_silently_truncated_or_sent_to_model(manual, tmp_path):
    source,document = manual
    data = importer.prepare(source,document)
    p = next(p for p in data['passages'] if p['section']=='Monitoring')
    p['parent_context_spans'] = [dict(original_text='x'*4001)]
    class Provider:
        def complete(self,**kwargs): pytest.fail('Unbounded context reached model')
    result = prep.classify_section(p,data['workflows'][0],source.read_text().splitlines(keepends=True),Provider(),tmp_path,'synthetic')
    assert not result['decisions'] and 'context' in result['error']


def test_classification_cli_resumes_without_duplicate_units_or_approvals(manual, tmp_path, monkeypatch):
    source,document = manual
    monkeypatch.setattr('sys.argv',['importer','prepare','--directory',str(source.parent)])
    with pytest.raises(SystemExit) as exc: importer.main()
    assert exc.value.code == 0
    workspace = source.parent/'.preparation'
    prepared = json.loads((workspace/'prepared'/f'{document["document_id"]}.json').read_text())
    p = next(p for p in prepared['passages'] if p['section']=='Monitoring')
    records = dict(document_id=document['document_id'],checksum=prepared['checksum'],sections={p['passage_id']:dict(
        decisions=[dict(line_start=p['line_start'],line_end=p['line_end'],decision='include',category='monitoring',reason='Synthetic complete recommendation.',context_spans=[])])})
    decisions_dir=tmp_path/'decisions'
    importer.write_json(decisions_dir/f'{document["document_id"]}.json',records)
    monkeypatch.setattr('sys.argv',['importer','classify','--directory',str(source.parent),'--decisions-dir',str(decisions_dir)])
    results=[]
    for _ in range(2):
        with pytest.raises(SystemExit) as exc: importer.main()
        assert exc.value.code == 0
        results.append(json.loads((workspace/'reviews'/f'{document["document_id"]}.json').read_text()))
    assert results[0] == results[1]
    assert all(not p['include'] and not p['reviewed'] for p in results[1]['passages'])
    assert (workspace/'review-summary.md').is_file()


@pytest.mark.parametrize('kind', ['gap','outside','fabricated-category','cross-workflow-context','table-fragment'])
def test_invalid_classification_is_rejected(manual, kind):
    source, document = manual
    data = importer.prepare(source, document)
    p = next(p for p in data['passages'] if p['section']=='Monitoring')
    lines = source.read_text().splitlines(keepends=True)
    item = dict(line_start=p['line_start'],line_end=p['line_end'],decision='include',category='monitoring',reason='Synthetic',context_spans=[])
    decisions = [item]
    if kind == 'gap': item['line_start'] += 1
    if kind == 'outside': item['line_end'] = 999
    if kind == 'fabricated-category': item['category'] = 'diagnosis'
    if kind == 'cross-workflow-context': item['context_spans']=[dict(line_start=999,line_end=999)]
    if kind == 'table-fragment':
        cut = next(i+1 for i,line in enumerate(lines) if line.startswith('| ALL'))
        item['line_end'] = cut-1
        decisions.append(dict(item,line_start=cut,line_end=p['line_end']))
    with pytest.raises(ValueError):
        prep.validate_decisions(p,decisions,data['workflows'][0],lines)
