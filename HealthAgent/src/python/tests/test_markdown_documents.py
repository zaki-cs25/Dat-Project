"""Source integrity, recommendation boundaries and Markdown-only retrieval."""
import copy
import json
from pathlib import Path

import pytest
from central_park import import_care_documents as importer, care_evidence


@pytest.fixture
def source(tmp_path, monkeypatch):
    path = tmp_path / 'synthetic.md'
    path.write_text('# ADULT WORKFLOW\n## Monitoring\nIf stable, review measurements.\n\n| Branch | Exception |\n| --- | --- |\n| ALL criteria | Do not use in acute illness |\n\n* Footnote: confirm stability first.\n\n## Follow-up\nReview only after stabilization.\n\n# OTHER WORKFLOW\nDo not import unrelated content.\n')
    document = dict(document_id='icmr-md-synthetic', filename=path.name, source_format='markdown',
                    publisher='Synthetic fixture', official_url='https://example.invalid',
                    official_url_kind='catalogue', title='SYNTHETIC ONLY', version='unknown',
                    workflows=[dict(condition='hypertension', start='# ADULT WORKFLOW', end='# OTHER WORKFLOW')])
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps([document]))
    monkeypatch.setattr(importer, 'MANIFEST', manifest)
    return path, document


def reviewed(source):
    path, document = source
    data = importer.prepare(path, document)
    data.update(reviewed=True, reviewer='Synthetic review', reviewed_at='2026-10-07T00:00:00Z')
    for p in data['passages']:
        p.update(reviewed=True, applicability='Established adult condition; confirm clinical stability.',
                 exceptions='Acute illness requires assessment before routine follow-up.')
    return data


def test_preparation_preserves_complete_table_branches_and_footnote(source):
    path, document = source
    data = importer.prepare(path, document)
    assert not data['reviewed']
    table = next(p for p in data['passages'] if p['section'] == 'Monitoring')
    assert '| ALL criteria |' in table['original_text']
    assert 'Footnote: confirm stability first.' in table['original_text']
    assert all(p['page'] is None for p in data['passages'])
    assert not any('unrelated content' in p['text'] for p in data['passages'])
    assert all(not p['reviewed'] for p in data['passages'])


def test_import_has_stable_ids_and_review_revision(source):
    path, _ = source
    data = reviewed(source)
    first = importer.import_body(data, path)
    assert importer.import_body(copy.deepcopy(data), path) == first
    assert all(p['line_start'] > 0 and p['reviewed'] for p in first['passages'])
    data['passages'][1]['exceptions'] += ' Confirm prerequisites.'
    second = importer.import_body(data, path)
    assert second['version_id'] != first['version_id']
    assert second['passages'][1]['passage_id'] != first['passages'][1]['passage_id']


@pytest.mark.parametrize('change,reason', [
    (lambda d: d.update(reviewed=False), 'review'),
    (lambda d: d['passages'][0].update(reviewed=False), 'review'),
    (lambda d: d['passages'][0].update(applicability=importer.PENDING), 'unreviewed'),
    (lambda d: d['passages'][0].update(original_text='fabricated'), 'excerpt'),
    (lambda d: d['passages'][0].update(line_end=999), 'lines'),
    (lambda d: d['passages'][0].update(condition='asthma'), 'workflow'),
    (lambda d: d['passages'][0].update(page=5), 'page'),
    (lambda d: d.update(official_url='https://fabricated.invalid'), 'identity'),
    (lambda d: d['passages'][0].update(text='x' * (importer.MAX_TEXT+1)), 'Oversized'),
])
def test_invalid_passages_never_publish(source, change, reason, monkeypatch):
    path, _ = source
    data = reviewed(source)
    change(data)
    monkeypatch.setattr(importer, 'request', lambda *a: pytest.fail('Invalid review reached IRIS'))
    with pytest.raises(ValueError, match=reason):
        importer.publish(data, path)


def test_source_edit_invalidates_review(source):
    path, _ = source
    data = reviewed(source)
    path.write_text(path.read_text() + '\nSource edited.\n')
    with pytest.raises(ValueError, match='checksum'):
        importer.validate_review(data, path)


def test_pdf_input_rejected_by_preparation_and_publishing(source, monkeypatch):
    path, document = source
    data = reviewed(source)
    pdf = path.with_suffix('.pdf')
    pdf.write_bytes(path.read_bytes())  # Synthetic content; no original corpus.
    monkeypatch.setattr(importer, 'request', lambda *a: pytest.fail('PDF reached IRIS'))
    with pytest.raises(ValueError, match='Only Markdown'):
        importer.prepare(pdf, document)
    with pytest.raises(ValueError, match='Only Markdown'):
        importer.publish(data, pdf)


def test_duplicate_and_missing_workflow_boundaries_fail(source):
    path, document = source
    path.write_text(path.read_text() + '# ADULT WORKFLOW\n')
    with pytest.raises(ValueError, match='workflow start'):
        importer.prepare(path, document)
    document['workflows'][0]['start'] = '# NOT PRESENT'
    with pytest.raises(ValueError, match='workflow start'):
        importer.prepare(path, document)


def test_out_of_scope_manual_does_not_require_fake_review(source, monkeypatch):
    path, document = source
    document['workflows'] = []
    importer.MANIFEST.write_text(json.dumps([document]))
    data = importer.prepare(path, document)
    monkeypatch.setattr(importer, 'request', lambda *a: pytest.fail('Empty manual reached IRIS'))
    assert importer.publish(data, path)['status'] == 'out-of-scope'


def test_retrieval_explicitly_selects_markdown_library(monkeypatch):
    calls = []
    def search(path, body):
        calls.append((path, body))
        return {'hits': []}
    monkeypatch.setattr(care_evidence, 'request', search)
    assert care_evidence.retrieve({'hypertension': ['c']}, 'concerns') == ([], ['hypertension'])
    assert calls[0][1]['library'] == 'markdown'
