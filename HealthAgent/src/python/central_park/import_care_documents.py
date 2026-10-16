"""Private Markdown -> reviewable recommendation sections -> IRIS care evidence.

No PDF conversion or downloads. Source files are never modified. Preparation is
offline; only explicitly reviewed recommendation units can be published.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from dataclasses import replace
from pathlib import Path
import re

from central_park.care_evidence import request
from central_park import care_preparation as preparation
from central_park.care_catalogue import BASE, TAG, catalogue, inventory_catalogue

MANIFEST = Path(__file__).parent / 'data/icmr_markdown_manifest.json'
MAX_TEXT = 6000
PENDING = 'Review required: record prerequisites and exclusions for this recommendation.'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def workflow_ranges(lines, document):
    """Explicit boundaries prevent mentions of a disease tagging other workflows."""
    for workflow in document['workflows']:
        starts = [i for i, line in enumerate(lines) if line.strip() == workflow['start']]
        if len(starts) != 1:
            raise ValueError(f"Expected one workflow start for {workflow['condition']}; found {len(starts)}")
        start = starts[0]
        if workflow['end'] is None:
            end = len(lines)
        else:
            ends = [i for i in range(start + 1, len(lines)) if lines[i].strip() == workflow['end']]
            if len(ends) != 1:
                raise ValueError(f"Expected one workflow end for {workflow['condition']}; found {len(ends)}")
            end = ends[0]
            # Remove the next workflow's generic banner/ICD prefix from this range.
            while end > start and (not lines[end - 1].strip() or
                    lines[end - 1].strip() in ('# Standard Treatment Workflow (STW)', 'Standard Treatment Workflow (STW)')):
                end -= 1
        yield workflow['condition'], start, end


def prepare(source, document):
    if source.suffix.lower() != '.md':
        raise ValueError('Only Markdown sources are supported')
    content = source.read_bytes()
    lines = content.decode('utf-8-sig').splitlines(keepends=True)
    if document.get('workflow_mode') == 'discover':
        return prepare_discovered(source, document, content, lines)
    passages = []
    for condition, start, end in workflow_ranges(lines, document):
        headings = [i for i in range(start + 1, end) if re.match(r'^#{1,6}\s+\S', lines[i])
                    and not re.match(r'^#{1,6}\s+(?:ICD|Standard Treatment Workflow)', lines[i])]
        boundaries = sorted(set([start, *headings, end]))
        for left, right in zip(boundaries, boundaries[1:]):
            # Keep complete tables, lists, nested branches and adjacent footnotes.
            while right > left and not lines[right - 1].strip():
                right -= 1
            excerpt = ''.join(lines[left:right])
            if not excerpt.strip():
                continue
            section = re.sub(r'^#{1,6}\s*', '', lines[left].strip())
            passages.append(dict(passage_id=f'{condition}-L{left+1}-L{right}',
                condition=condition, section=section, page=None,
                source_file=source.name, line_start=left+1, line_end=right,
                original_text=excerpt, text=excerpt, applicability=PENDING,
                exceptions=PENDING, include=True, reviewed=False,
                oversized=len(excerpt) > MAX_TEXT))
    return {**document, 'checksum': digest(content), 'prepared_at': datetime.now(timezone.utc).isoformat(),
            'reviewed': False, 'reviewer': '', 'reviewed_at': None, 'passages': passages}


def prepare_discovered(source, document, content, lines):
    workflows = preparation.discover(lines, document)
    passages = []
    for workflow in workflows:
        names = {workflow['title'].casefold(), workflow['title'].split(':')[0].casefold(),
                 re.sub(r'\s+in adults?$', '', workflow['title'].casefold())}
        matches = [tag for tag, entry in BASE.items() if names & set(entry['aliases'])]
        if len(matches) == 1:
            workflow['condition'] = matches[0]
        for span in preparation.source_spans(lines, workflow):
            decision, reason = preparation.rule_decision(span)
            passages.append(dict(**span, passage_id=workflow['workflow_id'] + ':L' + str(span['line_start']),
                workflow_id=workflow['workflow_id'], condition=workflow['condition'], page=None,
                source_file=source.name, text=span['original_text'], applicability=PENDING, exceptions=PENDING,
                context_spans=[], category=None, include=False, reviewed=False,
                decision=decision, decision_reason=reason, oversized=len(span['original_text']) > MAX_TEXT))
    return {**document, 'schema_version': 2, 'pipeline': preparation.PIPELINE, 'workflows': workflows,
            'checksum': digest(content), 'prepared_at': datetime.now(timezone.utc).isoformat(),
            'reviewed': False, 'reviewer': '', 'reviewed_at': None, 'passages': passages}


def validate_review(data, source):
    if data.get('checksum') != digest(source.read_bytes()):
        raise ValueError('Markdown checksum differs from reviewed source; prepare a new revision')
    # Empty, out-of-scope manuals need inventory validation, not invented review.
    out_of_scope = source.suffix.lower() == '.md' and data.get('workflows') == [] and data.get('passages') == []
    if not out_of_scope and (data.get('reviewed') is not True or not data.get('reviewer') or not data.get('reviewed_at')):
        raise ValueError('Markdown passage review must be recorded before indexing')
    if source.suffix.lower() != '.md' or data.get('source_format') != 'markdown':
        raise ValueError('Only Markdown sources are supported')
    canonical = next((d for d in json.loads(MANIFEST.read_text()) if d['document_id'] == data.get('document_id')), None)
    if canonical is None:
        raise ValueError('Document is not in the five-file Markdown manifest')
    fields = ['filename', 'publisher', 'official_url', 'official_url_kind']
    if canonical.get('workflow_mode') != 'discover':
        fields.append('workflows')
    for field in fields:
        if data.get(field) != canonical[field]:
            raise ValueError('Source identity differs from curated Markdown manifest: ' + field)
    if source.name != canonical['filename']:
        raise ValueError('Source filename differs from manifest')
    if out_of_scope:
        return []
    lines = source.read_text(encoding='utf-8-sig').splitlines(keepends=True)
    if canonical.get('workflow_mode') == 'discover':
        return validate_discovered(data, lines)
    ranges = {condition: (start+1, end) for condition, start, end in workflow_ranges(lines, canonical)}
    selected = [p for p in data.get('passages', []) if p.get('include') is True]
    if not selected and ranges:
        raise ValueError('No reviewed passages for supported workflows')
    seen = set()
    for p in selected:
        if p.get('reviewed') is not True:
            raise ValueError('Every included passage must be reviewed: ' + str(p.get('passage_id')))
        for field in ('passage_id', 'condition', 'section', 'original_text', 'text', 'applicability', 'exceptions'):
            if not isinstance(p.get(field), str) or not p[field].strip() or p[field] == PENDING:
                raise ValueError('Missing or unreviewed passage field: ' + field)
        left, right = p.get('line_start'), p.get('line_end')
        limits = ranges.get(p['condition'])
        if type(left) is not int or type(right) is not int or not limits or not (limits[0] <= left <= right <= limits[1]):
            raise ValueError('Invalid source lines or condition workflow')
        if p.get('source_file') != source.name or p['original_text'] != ''.join(lines[left-1:right]):
            raise ValueError('Original excerpt does not match cited Markdown lines')
        if p.get('page') is not None:
            raise ValueError('Markdown has no verified PDF page references; use source lines')
        if p['passage_id'] in seen:
            raise ValueError('Duplicate passage ID')
        seen.add(p['passage_id'])
        if len(p['text']) > MAX_TEXT:
            raise ValueError('Oversized recommendation: split manually at complete recommendation boundaries')
    return selected


def table_cells(text):
    """Return complete Markdown cell offsets, ignoring escaped/code pipes."""
    if not text.strip().startswith('|') or not text.strip().endswith('|'):
        return []
    pipes, code_ticks, index = [], 0, 0
    while index < len(text):
        char = text[index]
        backslashes, previous = 0, index - 1
        while previous >= 0 and text[previous] == '\\':
            backslashes += 1
            previous -= 1
        if backslashes % 2:
            index += 1
            continue
        if char == '`':
            end = index + 1
            while end < len(text) and text[end] == '`':
                end += 1
            count = end - index
            if not code_ticks:
                code_ticks = count
            elif count == code_ticks:
                code_ticks = 0
            index = end
            continue
        if char == '|' and not code_ticks:
            pipes.append(index)
        index += 1
    if code_ticks:
        return []
    return [(left + 1, right) for left, right in zip(pipes, pipes[1:])]


def selected_source_span(span, lines, workflow):
    """Verify the full audit span, then an explicitly reviewed complete cell."""
    a, b = span.get('line_start'), span.get('line_end')
    if type(a) is not int or type(b) is not int or not workflow['line_start'] <= a <= b <= workflow['line_end']:
        raise ValueError('Source lines cross workflow boundary')
    original = ''.join(lines[a-1:b])
    if span.get('original_text') != original:
        raise ValueError('Original excerpt does not match cited Markdown lines')
    if 'char_start' not in span and 'char_end' not in span:
        return original, dict(span)
    start, end = span.get('char_start'), span.get('char_end')
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(original):
        raise ValueError('Invalid source character offsets')
    review = span.get('selection_review', {})
    if not isinstance(review, dict) or review.get('reviewed') is not True or not all(
            isinstance(review.get(k), str) and review[k].strip()
            for k in ('reviewer', 'reviewed_at', 'rationale')) or review.get('unit_type') != 'complete-table-cell':
        raise ValueError('Source cell selection review is required')
    selected = original[start:end]
    if a != b or not selected.strip() or not any(
            left <= start < end <= right and selected.strip() == original[left:right].strip()
            for left, right in table_cells(original)):
        raise ValueError('Select a complete table cell with all branches and exceptions')
    # Keep the mixed full line only in private review artifacts. Model inputs,
    # saved citations and vector metadata receive the selected cell alone.
    return selected, dict(span, original_text=selected, source_line_checksum=digest(original.encode()))


def validate_discovered(data, lines):
    if data.get('schema_version') != 2 or data.get('pipeline') != preparation.PIPELINE:
        raise ValueError('Prepare schema-version-2 Markdown workflow review')
    workflows = data.get('workflows', [])
    lookup, previous = {}, 0
    for w in sorted(workflows, key=lambda w: w.get('line_start', 0)):
        left, right = w.get('line_start'), w.get('line_end')
        if type(left) is not int or type(right) is not int or not previous < left <= right <= len(lines):
            raise ValueError('Invalid or overlapping workflow boundaries')
        previous = right
        if not TAG.fullmatch(w.get('condition', '')) or w.get('workflow_id') in lookup:
            raise ValueError('Invalid condition tag or duplicate workflow ID')
        if w.get('workflow_id') != data['document_id'] + ':L' + str(left):
            raise ValueError('Workflow identity differs from source boundary')
        lookup[w['workflow_id']] = w
    bulk = data.get('review_policy') == 'showcase-bulk'
    if bulk:
        approval = data.get('bulk_approval', {})
        if not approval.get('actor') or not approval.get('approved_at') or approval.get('scope') != 'non-rejected-context' or approval.get('clinical_validation_complete') is not False:
            raise ValueError('Showcase context requires explicit non-clinical bulk approval')
    selected, seen = [], set()
    for p in data.get('passages', []):
        if p.get('include') is not True:
            continue
        w = lookup.get(p.get('workflow_id'))
        if not w or p.get('condition') != w['condition']:
            raise ValueError('Passage does not belong to the mapped workflow')
        if w.get('reviewed') is not True or not w.get('reviewer') or not w.get('reviewed_at'):
            raise ValueError('Workflow boundary/mapping review is required before indexing')
        populations = ('adult', 'mixed', 'unknown', 'pediatric') if bulk else ('adult', 'mixed')
        if w.get('population') not in populations:
            raise ValueError('Adult applicability must be established for workflow')
        decisions = ('include', 'supporting-context', 'needs-review') if bulk else ('include',)
        categories = preparation.CATEGORIES | {'context'} if bulk else preparation.CATEGORIES
        if p.get('reviewed') is not True or p.get('decision') not in decisions or p.get('category') not in categories:
            raise ValueError('Only reviewed, included management recommendations can be indexed')
        if bulk and (p.get('evidence_role') != 'context' or p.get('clinical_validation_complete') is not False):
            raise ValueError('Bulk-approved passages must be labelled non-clinical context')
        for field in ('passage_id', 'section', 'text', 'original_text', 'applicability', 'exceptions'):
            if not isinstance(p.get(field), str) or not p[field].strip() or p[field] == PENDING:
                raise ValueError('Missing or unreviewed passage field: ' + field)
        if p.get('passage_id') in seen:
            raise ValueError('Duplicate passage ID')
        seen.add(p['passage_id'])
        if p.get('source_file') != data['filename'] or p.get('page') is not None:
            raise ValueError('Invalid Markdown source reference')
        context, verified_spans = [], []
        for span in [p, *p.get('context_spans', [])]:
            excerpt, verified = selected_source_span(span, lines, w)
            context.append(excerpt)
            verified_spans.append(verified)
        expected = '\n\n'.join(context)
        if p['text'] != expected:
            raise ValueError('Indexed text must preserve the selected source and context verbatim')
        if len(expected) > MAX_TEXT:
            raise ValueError('Oversized recommendation; refine complete recommendation boundaries')
        selected.append(dict(verified_spans[0], context_spans=verified_spans[1:],
            workflow_title=w['title'], workflow_codes=w['codes'],
            workflow_review=dict(reviewer=w['reviewer'], reviewed_at=w['reviewed_at'], population=w['population'])))
    # A wholly excluded workflow is valid; no invented recommendation is required.
    # Exact duplicate units are consolidated only when qualifications also match.
    unique = {}
    for p in selected:
        key = (p['condition'], p['category'], p['text'], p['applicability'], p['exceptions'])
        if key not in unique:
            unique[key] = dict(p)
        else:
            row = unique[key]
            row.setdefault('duplicate_sources', []).append({k: p[k] for k in (
                'source_file', 'line_start', 'line_end', 'passage_id', 'char_start', 'char_end') if k in p})
    return list(unique.values())


def import_body(data, source, catalogue_path=None):
    passages = validate_review(data, source)
    if data.get('schema_version') == 2 and passages:
        target = catalogue_path or source.parent / '.preparation/catalogue.json'
        mappings = catalogue(path=target, base={})
        if any(p['condition'] not in mappings for p in passages):
            raise ValueError('Selected recommendations need reviewed/enabled catalogue mappings before indexing')
    metadata_fields = ('document_id', 'filename', 'source_format', 'publisher', 'title', 'official_url',
        'official_url_kind', 'publication_date', 'version', 'retrieved_at', 'checksum', 'usage_notice',
        'reviewer', 'reviewed_at', 'review_policy', 'bulk_approval', 'clinical_validation_complete')
    metadata = {k: data[k] for k in metadata_fields if k in data}
    publication_fields = ('passage_id', 'condition', 'section', 'page', 'source_file', 'line_start', 'line_end',
        'original_text', 'text', 'applicability', 'exceptions', 'category', 'context_spans',
        'char_start', 'char_end', 'selection_review', 'source_line_checksum',
        'workflow_id', 'workflow_title', 'workflow_codes', 'workflow_review', 'duplicate_sources',
        'evidence_role', 'original_decision', 'clinical_validation_complete', 'bulk_approval')
    published_passages = [{k: p[k] for k in publication_fields if k in p} for p in passages]
    # v2 decodes UTF-8 JSON on import. Retire previously misdecoded indexes without
    # mutating immutable passage IDs or the versions cited by existing plans.
    revision = digest(json.dumps(dict(index_format_version=2, metadata=metadata, passages=published_passages), sort_keys=True, ensure_ascii=False).encode())
    version = data['checksum'] + '-' + revision[:16]
    prepared = []
    for p in published_passages:
        # Candidate parent context/classifier diagnostics are review artifacts,
        # never evidence. Only explicitly selected supporting spans enter RAG.
        row = {**metadata, **p, 'passage_id': data['document_id'] + ':' + version + ':' + p['passage_id'],
               'version_id': version, 'reviewed': True}
        # Match the IRIS persisted metadata limit, including JSON escaping.
        if len(json.dumps(row)) > 32000:
            raise ValueError('Passage metadata exceeds IRIS limit; reduce the reviewed recommendation unit')
        prepared.append(row)
    return {'document_id': data['document_id'], 'version_id': version, 'passages': prepared}


def publish(data, source):
    body = import_body(data, source)
    return request('import', body) if body['passages'] else {'status': 'out-of-scope', 'passages': 0}


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    temporary.replace(path)


def classification_tasks(data):
    workflows = {w['workflow_id']: w for w in data['workflows']}
    return dict(schema_version=2, checksum=data['checksum'], document_id=data['document_id'],
                tasks=[dict(passage_id=p['passage_id'], workflow=workflows[p['workflow_id']], section=p)
                       for p in data['passages'] if p['decision'] == 'needs-review'])


def apply_classification(data, source, records):
    if records.get('checksum') != data['checksum'] or digest(source.read_bytes()) != data['checksum']:
        raise ValueError('Classification/source checksum mismatch')
    if records.get('document_id') != data['document_id']:
        raise ValueError('Classification document identity mismatch')
    if data.get('reviewed') or any(p.get('reviewed') for p in data['passages']):
        raise ValueError('Archive reviewed revision before reclassification')
    lines = source.read_text(encoding='utf-8-sig').splitlines(keepends=True)
    workflows = {w['workflow_id']: w for w in data['workflows']}
    known = {p['passage_id'] for p in data['passages']}
    if not set(records.get('sections', {})) <= known:
        raise ValueError('Classification references unknown passage IDs')
    passages = []
    for p in data['passages']:
        record = records.get('sections', {}).get(p['passage_id'])
        if not record or not record.get('decisions'):
            passages.append(p)
            continue
        w = workflows[p['workflow_id']]
        decisions = preparation.validate_decisions(p, record['decisions'], w, lines)
        for index, decision in enumerate(decisions):
            a, b = decision['line_start'], decision['line_end']
            original = ''.join(lines[a-1:b])
            contexts = [dict(line_start=span['line_start'], line_end=span['line_end'],
                             original_text=''.join(lines[span['line_start']-1:span['line_end']]))
                        for span in decision.get('context_spans', [])]
            unit = dict(p, passage_id=p['passage_id'] + ':D' + str(index), parent_passage_id=p['passage_id'],
                        line_start=a, line_end=b, original_text=original, context_spans=contexts,
                        text='\n\n'.join([original, *[s['original_text'] for s in contexts]]),
                        decision=decision['decision'], decision_reason=decision['reason'],
                        category=decision.get('category'), classifier=record.get('classifier', 'external'),
                        include=False, reviewed=False)
            unit['oversized'] = len(unit['text']) > MAX_TEXT
            passages.append(unit)
    return dict(data, passages=passages, reviewed=False)


def report(data):
    counts = {decision: 0 for decision in preparation.DECISIONS}
    for p in data['passages']:
        counts[p.get('decision', 'needs-review')] += 1
    return dict(document_id=data['document_id'], checksum=data['checksum'], workflows=len(data['workflows']),
                workflow_review_pending=sum(w.get('reviewed') is not True for w in data['workflows']),
                passages=len(data['passages']), decisions=counts,
                oversized=sum(p.get('oversized') is True for p in data['passages']),
                selected=sum(p.get('include') is True for p in data['passages']),
                reviewed=sum(p.get('reviewed') is True for p in data['passages']))


def write_review_summary(workspace, reviews):
    """Private, compact inventory; excluded text never copied into searchable data."""
    output = ['# Markdown care evidence review queue', '',
        'Classification proposes selections; it does not approve evidence. Sources remain unchanged.', '',
        '| Document | Workflows | Include candidates | Needs review | Excluded |',
        '| --- | ---: | ---: | ---: | ---: |']
    for data in reviews:
        counts = report(data)
        output.append(f'| {data["filename"]} | {counts["workflows"]} | {counts["decisions"]["include"]} | {counts["decisions"]["needs-review"]} | {counts["decisions"]["exclude"]} |')
    for data in reviews:
        output.extend(['', '## ' + data['filename'], '',
            'Review mappings in catalogue.json and boundaries/populations in reviews/' + data['document_id'] + '.json.', '',
            '| Workflow | Source lines | Mapping reviewed | Include candidates | Unresolved |',
            '| --- | --- | --- | ---: | ---: |'])
        for workflow in data['workflows']:
            units = [p for p in data['passages'] if p['workflow_id'] == workflow['workflow_id']]
            title = workflow['title'].replace('|', '\\|')
            output.append(f'| {title} | {workflow["line_start"]}–{workflow["line_end"]} | {workflow["reviewed"]} | {sum(p["decision"] == "include" for p in units)} | {sum(p["decision"] == "needs-review" for p in units)} |')
    (workspace / 'review-summary.md').write_text('\n'.join(output) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'classify', 'catalogue', 'report', 'validate', 'publish'])
    parser.add_argument('--directory', type=Path, default=Path('md_care_documents'))
    parser.add_argument('--document', help='One Markdown document ID; default all five files')
    parser.add_argument('--workspace', type=Path, help='Private artifacts directory; default <directory>/.preparation')
    parser.add_argument('--decisions-dir', type=Path, help='Apply agent-produced <document_id>.json decisions without API calls')
    parser.add_argument('--use-llm', action='store_true', help='Opt in to bounded calls to the configured chat endpoint')
    parser.add_argument('--classification-model', help='Override chat model only for classification')
    parser.add_argument('--limit', type=int, default=20, help='Maximum model calls per invocation, default 20')
    parser.add_argument('--retry-errors', action='store_true', help='Explicitly retry failed/oversized classification tasks')
    args = parser.parse_args()
    root = args.directory.resolve()
    workspace = args.workspace.resolve() if args.workspace else root / '.preparation'
    if args.limit < 1:
        parser.error('--limit must be positive')
    if args.action == 'classify' and bool(args.decisions_dir) == bool(args.use_llm):
        parser.error('Choose exactly one of --decisions-dir or --use-llm')
    documents = json.loads(MANIFEST.read_text())
    if args.document:
        documents = [d for d in documents if d['document_id'] == args.document]
    if not documents:
        parser.error('Unknown Markdown document ID')
    errors, pending, reports, reviews = [], [], [], []
    calls = 0
    for document in documents:
        try:
            source = root / document['filename']
            if not source.is_file():
                raise FileNotFoundError(f'Missing Markdown source: {source}')
            review = workspace / 'reviews' / (document['document_id'] + '.json')
            if args.action == 'prepare':
                if review.exists():
                    existing = json.loads(review.read_text())
                    if existing.get('checksum') != digest(source.read_bytes()):
                        raise ValueError('Source changed; archive its existing review and prepare a new revision')
                    print(f'{source.name}: existing review preserved at {review}')
                    continue
                data = prepare(source, document)
                write_json(review, data)
                if data.get('schema_version') == 2:
                    write_json(workspace / 'prepared' / (document['document_id'] + '.json'), data)
                    write_json(workspace / 'tasks' / (document['document_id'] + '.json'), classification_tasks(data))
                oversized = sum(p['oversized'] for p in data['passages'])
                print(f'{source.name}: {len(data["passages"])} candidate sections ({oversized} oversized), review at {review}')
                reviews.append(data)
                reports.append(report(data))
            elif args.action in ('classify', 'catalogue', 'report'):
                data = json.loads(review.read_text())
                if data.get('checksum') != digest(source.read_bytes()):
                    raise ValueError('Source changed; prepare a reviewed revision')
                if data.get('schema_version') != 2:
                    raise ValueError('This action requires schema-version-2 preparation')
                if args.action == 'classify':
                    if data.get('reviewed') or any(p.get('reviewed') for p in data['passages']) or any(w.get('reviewed') for w in data['workflows']):
                        raise ValueError('Archive reviewed revision before reclassification')
                    data = json.loads((workspace / 'prepared' / (document['document_id'] + '.json')).read_text())
                    if args.decisions_dir:
                        records = json.loads((args.decisions_dir / (document['document_id'] + '.json')).read_text())
                    else:
                        from central_park.config import load
                        from central_park.llm import get_provider
                        cfg = load()
                        if args.classification_model:
                            cfg = replace(cfg, **{cfg.llm_provider + '_model': args.classification_model})
                        provider = get_provider(cfg)
                        model_id = cfg.llm_provider + ':' + getattr(cfg, cfg.llm_provider + '_model')
                        endpoint = cfg.openai_base_url if cfg.llm_provider == 'openai' else cfg.ollama_base_url if cfg.llm_provider == 'ollama' else 'anthropic'
                        model_id += ':' + digest(str(endpoint).encode())[:12]
                        record_path = workspace / 'decisions' / (document['document_id'] + '.json')
                        records = json.loads(record_path.read_text()) if record_path.exists() else dict(
                            document_id=document['document_id'], checksum=data['checksum'], classifier_id=model_id,
                            prompt_digest=digest(preparation.CLASSIFY_PROMPT.encode()), sections={})
                        if records.get('checksum') != data['checksum']:
                            raise ValueError('Cached decisions refer to a previous source revision')
                        if records.get('classifier_id') != model_id or records.get('prompt_digest') != digest(preparation.CLASSIFY_PROMPT.encode()):
                            raise ValueError('Classification model/prompt changed; archive decisions or use a new workspace')
                        lines = source.read_text(encoding='utf-8-sig').splitlines(keepends=True)
                        workflows = {w['workflow_id']: w for w in data['workflows']}
                        for p in data['passages']:
                            old_record = records['sections'].get(p['passage_id'])
                            if p['decision'] != 'needs-review' or (old_record and (old_record.get('decisions') or not args.retry_errors)):
                                continue
                            if calls >= args.limit:
                                break
                            calls += 1
                            try:
                                records['sections'][p['passage_id']] = preparation.classify_section(
                                    p, workflows[p['workflow_id']], lines, provider, workspace / 'cache', model_id)
                            except Exception as exc:
                                records['sections'][p['passage_id']] = dict(error=str(exc), decisions=[])
                            write_json(record_path, records)
                    data = apply_classification(data, source, records)
                    write_json(review, data)
                reviews.append(data)
                reports.append(report(data))
                print(document['document_id'], json.dumps(reports[-1]))
            else:
                data = json.loads(review.read_text())
                body = import_body(data, source, workspace / 'catalogue.json')
                pending.append(body)
                print(f'{source.name}: validated {len(body["passages"])} reviewed passages')
        except Exception as exc:
            errors.append(f'{document["filename"]}: {exc}')
    if not errors and args.action == 'catalogue':
        target = workspace / 'catalogue.json'
        existing = json.loads(target.read_text()) if target.exists() else None
        # Always assemble from all prepared documents, not only a --document subset.
        all_reviews = [json.loads(p.read_text()) for p in sorted((workspace / 'reviews').glob('*.json'))]
        write_json(target, inventory_catalogue(all_reviews, existing))
        print('Candidate catalogue:', target)
    if reports:
        write_json(workspace / 'report.json', dict(pipeline=preparation.PIPELINE, documents=reports))
        if reviews:
            write_review_summary(workspace, reviews)
    # Validate the entire selected library before making any network writes.
    if not errors and args.action == 'publish':
        for body in pending:
            if not body['passages']:
                continue
            try:
                print(body['document_id'], request('import', body))
            except Exception as exc:
                errors.append(f'{body["document_id"]}: {exc}')
                break
    for error in errors:
        print('FAILED:', error)
    raise SystemExit(1 if errors else 0)


if __name__ == '__main__':
    main()
