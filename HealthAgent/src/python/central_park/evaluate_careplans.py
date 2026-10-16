"""Reproducible synthetic evaluation. --protocol checks software; --live evaluates configured models.

Clinical support/applicability remains an independent human scoring task.
"""
import argparse
import json
from pathlib import Path
from unittest.mock import patch
import httpx
from central_park import careplan
from central_park.care_evidence import match_conditions


class Scripted:
    def __init__(self, fault):
        self.fault = fault
    def complete(self, system, messages, **kwargs):
        data = json.loads(messages[0]['content'].split('\nRepair feedback:')[0])
        if self.fault == 'malformed-output':
            return '{'
        if 'SCHEMA:' in system:
            source_ids = [p['passage_id'] for p in data['evidence']]
            if self.fault == 'fabricated-citation':
                source_ids = ['fabricated']
            return json.dumps({'title': 'Synthetic protocol draft', 'activities': [{
                'category': 'monitoring', 'description': 'Start metformin 500 mg daily.' if self.fault == 'prohibited-prescribing' else 'Review recorded measurements with the clinician.',
                'provenance': ('context-informed' if source_ids else 'model') if data.get('generation_mode') == 'enriched' else 'icmr', 'source_ids': source_ids}], 'missing_information': [],
                'uncovered_conditions': [], 'review_notes': ['Synthetic protocol only.']})
        if data.get('generation_mode') == 'enriched':
            return json.dumps({'approved': self.fault != 'conflicting-recommendations',
                'issues': ['Unresolved contradictory advice'] if self.fault == 'conflicting-recommendations' else [],
                'review_notes': []})
        return json.dumps({'approved': self.fault != 'conflicting-recommendations',
            'issues': ['Unresolved contradictory advice'] if self.fault == 'conflicting-recommendations' else [],
            'applicable_source_ids': [p['passage_id'] for p in data['evidence']]})


def protocol_sources(matched, concerns):
    return ([{'passage_id': 'synthetic-' + c, 'condition': c, 'reviewed': True,
              'text': 'SYNTHETIC: Review recorded measurements with the clinician.',
              'applicability': 'Synthetic established adult condition.', 'exceptions': 'No prescribing.',
              'publisher': 'Synthetic evaluation fixture', 'document_id': 'synthetic-' + c,
              'version_id': 'synthetic-v1', 'page': 1, 'section': 'Synthetic'} for c in matched], [])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, default=Path('src/python/tests/fixtures/care-evaluation.json'))
    parser.add_argument('--output', type=Path, required=True)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--protocol', action='store_true')
    modes.add_argument('--live', action='store_true')
    parser.add_argument('--generation-mode', choices=['enriched', 'grounded'], default='enriched')
    parser.add_argument('--compare-context', action='store_true', help='Run the same cases with retrieval enabled and disabled')
    parser.add_argument('--case-id', action='append', help='Run only the specified case IDs (repeatable)')
    args = parser.parse_args()
    results = []
    cases = json.loads(args.cases.read_text())
    if args.case_id:
        available = {c['case_id'] for c in cases}
        if set(args.case_id) - available:
            parser.error('Unknown case ID: ' + ', '.join(sorted(set(args.case_id) - available)))
        cases = [c for c in cases if c['case_id'] in args.case_id]
    runs = [(case, enabled) for case in cases for enabled in ([True, False] if args.compare_context else [True])]
    for case, enabled in runs:
        context, fault = case['context'], case.get('fault')
        row = {'case_id': case['case_id'], 'expected_conditions': case['expected_conditions'],
               'context_enabled': enabled, 'generation_mode': args.generation_mode}
        try:
            if fault == 'fhir-failure':
                raise httpx.ConnectError('Synthetic failed FHIR read; no empty-context fallback')
            if args.protocol:
                retrieval = (lambda *a: ([], case['expected_conditions'])) if fault == 'no-evidence' else protocol_sources
                with patch.object(careplan, 'get_provider', lambda: Scripted(fault)), patch.object(careplan, 'retrieve', retrieval):
                    draft = careplan.generate(context, mode=args.generation_mode, use_context=enabled)
            else:
                if fault and fault != 'no-evidence':
                    row.update(status='not-run', reason='Fault injection belongs to protocol mode')
                    results.append(row)
                    continue
                if fault == 'no-evidence':
                    with patch.object(careplan, 'retrieve', lambda *a: ([], case['expected_conditions'])):
                        draft = careplan.generate(context, mode=args.generation_mode, use_context=enabled)
                else:
                    draft = careplan.generate(context, mode=args.generation_mode, use_context=enabled)
            expected = set(case['expected_conditions'])
            covered = {s['condition'] for s in draft['evidence_sources']}
            ids = {s['passage_id'] for s in draft['evidence_sources']}
            unknown = sum(1 for a in draft['activities'] if a['provenance'] in ('icmr', 'context-informed') and not set(a['source_ids']) <= ids)
            nonurgent = {k: draft[k] for k in ('title', 'activities', 'missing_information', 'uncovered_conditions', 'review_notes')}
            nonurgent['activities'] = [a for a in nonurgent['activities'] if a['provenance'] != 'assessment']
            try:
                careplan.validate(careplan.Draft.model_validate(nonurgent), draft['evidence_sources'], context, mode=args.generation_mode)
                prohibited = 0
            except ValueError:
                prohibited = 1
            row.update(status=draft['result_status'], covered_conditions=sorted(covered),
                       retrieved_context_count=len(draft.get('related_icmr_context', [])),
                       retrieved_context_conditions=sorted({s['condition'] for s in draft.get('related_icmr_context', [])}),
                       model_generated_activity_count=sum(a['provenance'] == 'model' for a in draft['activities']),
                       context_informed_activity_count=sum(a['provenance'] == 'context-informed' for a in draft['activities']),
                       evidence_coverage=(len(expected & covered) / len(expected) if expected else None),
                       unsupported_citation_count=unknown, urgent_first=bool(draft['activities'] and draft['activities'][0]['provenance'] == 'assessment'),
                       prohibited_content_accepted=prohibited, draft=draft)
        except Exception as exc:
            row.update(status='failed', reason=str(exc), prohibited_content_accepted=0)
        row['clinical_unsupported_recommendations'] = 'unscored: independent clinical review required'
        results.append(row)
    report = {'mode': 'synthetic-protocol' if args.protocol else 'configured-live-model',
              'generation_mode': args.generation_mode, 'context_comparison': args.compare_context,
              'clinical_accuracy_established': False, 'cases': results,
              'summary': {'case_count': len(results), 'completed': sum(r['status'] == 'completed' for r in results),
                          'insufficient_evidence': sum(r['status'] == 'insufficient-evidence' for r in results),
                          'failed': sum(r['status'] == 'failed' for r in results),
                          'unsupported_citations_accepted': sum(r.get('unsupported_citation_count', 0) for r in results),
                          'prohibited_content_accepted': sum(r.get('prohibited_content_accepted', 0) for r in results)}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['summary']))


if __name__ == '__main__':
    main()
