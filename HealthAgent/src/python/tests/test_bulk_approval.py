import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from central_park import bulk_approve_care as bulk


class BulkApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.docs = self.root / 'docs'
        self.workspace = self.docs / '.preparation'
        (self.workspace / 'reviews').mkdir(parents=True)
        (self.workspace / 'prepared').mkdir(parents=True)
        self.source = self.docs / 'manual.md'
        self.source.write_text('# Workflow\nfirst paragraph\n\nsecond paragraph\n', encoding='utf-8')
        self.doc_id = 'synthetic-doc'
        self.checksum = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self._manifest = self.root / 'manifest.json'
        self._manifest.write_text(json.dumps([dict(document_id=self.doc_id, filename='manual.md')]), encoding='utf-8')
        self.old_manifest = bulk.MANIFEST
        bulk.MANIFEST = self._manifest
        self._write_inputs()

    def tearDown(self):
        bulk.MANIFEST = self.old_manifest
        self.temp.cleanup()

    def _write_inputs(self, altered=False):
        full = self.source.read_text(encoding='utf-8')
        checksum = hashlib.sha256(self.source.read_bytes()).hexdigest()
        wf = dict(workflow_id='synthetic-doc:L1', condition='synthetic-condition', title='Synthetic Condition',
                  population='unknown', codes=['X00'])
        pediatric = dict(workflow_id='synthetic-doc:L7', condition='synthetic-pediatric', title='Synthetic Pediatric',
                         population='pediatric', codes=['P00'])
        parts = [
            dict(passage_id='include-id', decision='include', category='lifestyle', line_start=2, line_end=2,
                 original_text='first paragraph\n', text='first paragraph\n', context_spans=[]),
            dict(passage_id='context-id', decision='supporting-context', category=None, line_start=2, line_end=2,
                 original_text='first paragraph\n', text='first paragraph\n', context_spans=[]),
            dict(passage_id='review-id', decision='needs-review', category='not-a-category', line_start=4, line_end=4,
                 original_text='second paragraph\n', text='second paragraph\n', context_spans=[]),
            dict(passage_id='excluded-id', decision='exclude', category=None, line_start=2, line_end=2,
                 original_text='first paragraph\n', text='first paragraph\n', context_spans=[]),
            dict(passage_id='explicit-reject-id', decision='include', category='monitoring', line_start=4, line_end=4,
                 original_text='second paragraph\n', text='second paragraph\n', context_spans=[]),
            dict(passage_id='pediatric-id', decision='needs-review', category=None, workflow_id=pediatric['workflow_id'],
                 line_start=4, line_end=4, original_text='second paragraph\n', text='second paragraph\n', context_spans=[]),
        ]
        data = dict(schema_version=2, document_id=self.doc_id, filename='manual.md', source_format='markdown',
                    checksum=checksum, workflows=[wf, pediatric], passages=parts, reviewed=False)
        path = self.workspace / 'reviews' / (self.doc_id + '.json')
        bulk.write_json(path, data)
        bulk.write_json(self.workspace / 'prepared' / path.name, data)
        bulk.write_json(self.workspace / 'first-batch-review.json', dict(decisions=[dict(passage_id='explicit-reject-id', decision='rejected')]))
        bulk.write_json(self.workspace / 'catalogue.json', dict(schema_version=2, source_checksums={self.doc_id: checksum}, entries={
            'synthetic-condition': dict(title='Synthetic Condition', aliases=['verified alias'], codes=[], population='unknown',
                reviewed=False, enabled=False, reviewer='', reviewed_at=None, workflow_ids=[wf['workflow_id']],
                candidate_aliases=['candidate alias'], candidate_codes=[['http://hl7.org/fhir/sid/icd-10','X00']])}))

    def test_bulk_selects_nonrejected_and_keeps_codes_unverified(self):
        report = bulk.approve(self.docs, self.workspace, 'user')
        data = json.loads((self.workspace / 'reviews' / (self.doc_id + '.json')).read_text())
        rows = {x['passage_id']: x for x in data['passages']}
        self.assertTrue(rows['include-id']['include'])
        self.assertTrue(rows['context-id']['include'])
        self.assertTrue(rows['review-id']['include'])
        self.assertEqual(rows['review-id']['category'], 'context')
        self.assertEqual(rows['review-id']['decision'], 'needs-review')
        self.assertEqual(rows['review-id']['original_classifier_decision'], 'needs-review')
        self.assertFalse(rows['review-id']['clinical_validation_complete'])
        self.assertFalse(rows['explicit-reject-id']['include'])
        self.assertEqual(rows['include-id']['population'], 'unknown')
        entry = json.loads((self.workspace / 'catalogue.json').read_text())['entries']['synthetic-condition']
        self.assertEqual(entry['codes'], [])
        self.assertEqual(set(entry['aliases']), {'verified alias', 'candidate alias', 'Synthetic Condition'})
        self.assertEqual(entry['approval_kind'], 'showcase-bulk')
        self.assertEqual(rows['pediatric-id']['population'], 'pediatric')
        pediatric_entry = json.loads((self.workspace / 'catalogue.json').read_text())['entries']['synthetic-pediatric']
        self.assertEqual(pediatric_entry['population'], 'pediatric')
        for workflow in data['workflows']:
            self.assertTrue(workflow['reviewed'])
            self.assertEqual(workflow['reviewer'], 'user')
            self.assertEqual(workflow['approval_kind'], 'showcase-bulk')
            self.assertFalse(workflow['clinical_validation_complete'])
        self.assertEqual([w['population'] for w in data['workflows']], ['unknown', 'pediatric'])
        self.assertEqual(report['totals']['approved'], 4)
        self.assertEqual(report['totals']['explicit_rejections'], 1)

    def test_oversized_paragraphs_split_and_unbreakable_is_reported(self):
        text = ('a' * 3500) + '\n\n' + ('b' * 3500) + '\n'
        self.source.write_text('# Workflow\n' + text, encoding='utf-8')
        checksum = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self._manifest.write_text(json.dumps([dict(document_id=self.doc_id, filename='manual.md')]), encoding='utf-8')
        data = json.loads((self.workspace / 'reviews' / (self.doc_id + '.json')).read_text())
        data['checksum'] = checksum
        data['passages'] = [dict(passage_id='splittable', decision='needs-review', category=None, workflow_id='synthetic-doc:L1',
            line_start=2, line_end=5, original_text=text, text=text, context_spans=[])]
        bulk.write_json(self.workspace / 'reviews' / (self.doc_id + '.json'), data)
        bulk.write_json(self.workspace / 'prepared' / (self.doc_id + '.json'), data)
        cat = json.loads((self.workspace / 'catalogue.json').read_text())
        cat['source_checksums'][self.doc_id] = checksum
        bulk.write_json(self.workspace / 'catalogue.json', cat)
        report = bulk.approve(self.docs, self.workspace, 'user')
        approved = json.loads((self.workspace / 'reviews' / (self.doc_id + '.json')).read_text())['passages']
        self.assertEqual(len(approved), 2)
        self.assertEqual([p['line_start'] for p in approved], [2, 4])
        self.assertTrue(all(len(p['text']) <= bulk.MAX_TEXT for p in approved))
        self.assertEqual(report['totals']['blocked'], 0)

    def test_source_mismatch_performs_no_writes(self):
        before = sorted(str(p.relative_to(self.workspace)) for p in self.workspace.rglob('*'))
        self.source.write_text('changed\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            bulk.approve(self.docs, self.workspace, 'user')
        after = sorted(str(p.relative_to(self.workspace)) for p in self.workspace.rglob('*'))
        self.assertEqual(before, after)
        self.assertFalse((self.workspace / 'history').exists())

    def test_unsplittable_content_is_reported_by_id(self):
        source_text = 'z' * 7000 + '\n'
        self.source.write_text(source_text, encoding='utf-8')
        checksum = hashlib.sha256(self.source.read_bytes()).hexdigest()
        data = json.loads((self.workspace / 'reviews' / (self.doc_id + '.json')).read_text())
        data['checksum'] = checksum
        data['passages'] = [dict(passage_id='unsafe-unit', decision='include', category='monitoring', workflow_id='synthetic-doc:L1',
            line_start=1, line_end=1, original_text=source_text, text=source_text, context_spans=[])]
        bulk.write_json(self.workspace / 'reviews' / (self.doc_id + '.json'), data)
        bulk.write_json(self.workspace / 'prepared' / (self.doc_id + '.json'), data)
        cat = json.loads((self.workspace / 'catalogue.json').read_text())
        cat['source_checksums'][self.doc_id] = checksum
        bulk.write_json(self.workspace / 'catalogue.json', cat)
        report = bulk.approve(self.docs, self.workspace, 'user')
        self.assertEqual(report['documents'][0]['blocked'][0]['passage_id'], 'unsafe-unit')
        self.assertIn('no safe complete paragraph boundary', report['documents'][0]['blocked'][0]['reason'])

    def test_repeat_is_idempotent(self):
        bulk.approve(self.docs, self.workspace, 'user')
        tracked = [self.workspace / 'reviews' / (self.doc_id + '.json'), self.workspace / 'prepared' / (self.doc_id + '.json'),
                   self.workspace / 'catalogue.json', self.workspace / 'bulk-approval-report.json']
        before = [p.read_bytes() for p in tracked]
        archives_before = sorted((self.workspace / 'history').iterdir())
        bulk.approve(self.docs, self.workspace, 'user')
        self.assertEqual(before, [p.read_bytes() for p in tracked])
        self.assertEqual(archives_before, sorted((self.workspace / 'history').iterdir()))

    def test_repeat_repairs_missing_workflow_metadata_without_new_approval_time(self):
        report = bulk.approve(self.docs, self.workspace, 'user')
        approved_at = report['bulk_approval']['approved_at']
        path = self.workspace / 'reviews' / (self.doc_id + '.json')
        data = json.loads(path.read_text())
        for workflow in data['workflows']:
            workflow.update(reviewed=False, reviewer='', reviewed_at=None, approval_kind=None)
        bulk.write_json(path, data)
        bulk.write_json(self.workspace / 'prepared' / path.name, data)
        before_count = report['totals']['approved']
        repaired = bulk.approve(self.docs, self.workspace, 'user')
        after = json.loads(path.read_text())
        self.assertEqual(repaired['bulk_approval']['approved_at'], approved_at)
        self.assertEqual(repaired['totals']['approved'], before_count)
        self.assertTrue(repaired['workflow_metadata_repaired'])
        self.assertTrue(all(w['reviewed'] and w['reviewer'] == 'user' for w in after['workflows']))
        archives = list((self.workspace / 'history').iterdir())
        self.assertEqual(len(archives), 2)


if __name__ == '__main__':
    unittest.main()
