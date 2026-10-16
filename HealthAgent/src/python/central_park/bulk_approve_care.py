"""Approve non-rejected private care candidates for context-only showcase indexing.

This pass records a user's showcase scope approval. It does not represent
clinical validation or endorsement of the source recommendations.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil

MANIFEST = Path(__file__).parent / 'data/icmr_markdown_manifest.json'
MAX_TEXT = 6000


APPROVABLE = {'include', 'supporting-context', 'needs-review'}
REJECTED = {'reject', 'rejected', 'exclude'}
PLACEHOLDER = 'Unverified context; read the full source workflow and its prerequisites before clinical use.'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def normalized(value):
    return re.sub(r'\s+', ' ', str(value).casefold()).strip()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    tmp.replace(path)


def _is_list(line):
    return bool(re.match(r'^\s*(?:[-+*]|\d+[.)])\s+', line))


def _is_table(line):
    return line.strip().startswith('|') and line.strip().endswith('|')


def _safe_chunks(text, maximum):
    """Split at blank paragraph boundaries, keeping lists/tables/fences intact."""
    if len(text) <= maximum:
        return [text]
    lines = text.splitlines(keepends=True)
    if not lines:
        return None
    # A boundary is safe only at a blank line outside fences and between
    # ordinary paragraphs. Blank lines near list/table/code structures stay in
    # the block so those structures cannot be severed.
    boundary_offsets = []
    offset = 0
    fence = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        is_fence = re.match(r'^(```+|~~~+)', stripped)
        if is_fence:
            marker = is_fence.group(1)[:3]
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
        if not stripped and fence is None:
            before = next((x for x in reversed(lines[:index]) if x.strip()), '')
            after = next((x for x in lines[index + 1:] if x.strip()), '')
            unsafe = (_is_list(before) or _is_list(after) or _is_table(before) or
                      _is_table(after) or before.lstrip().startswith(('>', '<!--')) or
                      after.lstrip().startswith(('>', '<!--')))
            if not unsafe:
                boundary_offsets.append(offset + len(line))
        offset += len(line)
    if fence is not None:
        return None
    if not boundary_offsets:
        return None
    chunks, start = [], 0
    while len(text) - start > maximum:
        possible = [point for point in boundary_offsets if start < point <= start + maximum]
        if not possible:
            return None
        end = possible[-1]
        chunks.append(text[start:end])
        start = end
    if start < len(text):
        chunks.append(text[start:])
    if any(not x.strip() or len(x) > maximum for x in chunks):
        return None
    return chunks


def _line_spans(text, start_line):
    """Return line spans for text pieces that are exact contiguous source text."""
    spans, offset, line = [], 0, start_line
    for chunk in text:
        left = line
        line += chunk.count('\n')
        if chunk.endswith('\n'):
            right = max(left, line - 1)
        else:
            right = line
        spans.append((left, right))
        offset += len(chunk)
    return spans


def _split_passage(passage, maximum):
    text = passage.get('text', '')
    original = passage.get('original_text', '')
    contexts = passage.get('context_spans', []) or []
    if len(text) <= maximum:
        return [passage], None
    # Preserve attached context on every chunk only when it fits. Context is
    # source material, so it is never silently dropped to satisfy the limit.
    context_texts = [span.get('original_text', '') for span in contexts]
    context_suffix = ''
    if context_texts:
        # Existing preparation uses verbatim separator joins. Do not guess if
        # the candidate text does not begin with its exact source excerpt.
        if not text.startswith(original):
            return None, 'candidate text is not a verbatim prefix of its source span'
        if text != '\n\n'.join([original, *context_texts]):
            return None, 'attached context cannot be mapped to the source span safely'
        context_suffix = text[len(original):]
        if any(len(x) + len(context_suffix) > maximum for x in (_safe_chunks(original, maximum) or [])):
            return None, 'attached context prevents safe splitting under the text limit'
        base = original
    else:
        base = text
        if original != text:
            return None, 'candidate text differs from source and has no verifiable context mapping'
    chunks = _safe_chunks(base, maximum - len(context_suffix))
    if chunks is None:
        return None, 'no safe complete paragraph boundary fits the text limit'
    # Source candidate text itself must be the original excerpt; char-level
    # selections require a reviewed selection map that bulk approval cannot add.
    if original != base:
        return None, 'selected source excerpt requires character offsets; refusing inferred citation spans'
    line_spans = _line_spans(chunks, passage['line_start'])
    result = []
    for i, (chunk, (left, right)) in enumerate(zip(chunks, line_spans), 1):
        if not chunk.strip():
            return None, 'split produced an empty source unit'
        row = dict(passage)
        row['passage_id'] = passage['passage_id'] + f':B{i}'
        row['parent_passage_id'] = passage.get('parent_passage_id', passage['passage_id'])
        row['line_start'], row['line_end'] = left, right
        row['original_text'] = chunk
        row['text'] = chunk + context_suffix
        row['context_spans'] = contexts
        row['bulk_split'] = dict(parent_passage_id=passage['passage_id'], part=i, parts=len(chunks))
        result.append(row)
    return result, None


def _explicit_rejections(workspace):
    rejected, excluded_spans = set(), []
    files = [workspace / 'first-batch-review.json', workspace / 'hypertension-review.json',
             workspace / 'hypertension-selected-review.json']
    for path in files:
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding='utf-8'))
        rows = data.get('decisions', [])
        if isinstance(rows, dict):
            rows = list(rows.values())
        for row in rows:
            if not isinstance(row, dict):
                continue
            decision = normalized(row.get('reviewer_decision') or row.get('decision') or
                                  row.get('proposed_disposition') or row.get('disposition') or '')
            if decision in REJECTED:
                for key in ('passage_id', 'parent_passage_id', 'id', 'candidate_id'):
                    if isinstance(row.get(key), str) and row[key]:
                        rejected.add(row[key])
        if path.name == 'hypertension-selected-review.json':
            for row in data.get('excluded_source_content', []):
                lines = row.get('source_lines') if isinstance(row, dict) else None
                if isinstance(lines, list) and len(lines) == 2 and all(type(x) is int for x in lines):
                    excluded_spans.append((row.get('source_review_id'), lines[0], lines[1]))
    return rejected, excluded_spans


def _archive(workspace, stamp):
    archive = workspace / 'history' / ('bulk-approval-' + stamp)
    suffix = 1
    while archive.exists():
        archive = workspace / 'history' / ('bulk-approval-' + stamp + '-' + str(suffix))
        suffix += 1
    for name in ('reviews', 'prepared', 'catalogue.json'):
        source = workspace / name
        if source.is_dir():
            shutil.copytree(source, archive / name, dirs_exist_ok=True)
        elif source.is_file():
            (archive / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, archive / name)
    return archive


def _workflow_approval_complete(workflow, actor, approved_at):
    return (workflow.get('reviewed') is True and workflow.get('reviewer') == actor and
            workflow.get('reviewed_at') == approved_at and workflow.get('approval_kind') == 'showcase-bulk' and
            workflow.get('clinical_validation_complete') is False)


def _approve_workflows(data, actor, approved_at):
    for workflow in data.get('workflows', []):
        workflow.update(reviewed=True, reviewer=actor, reviewed_at=approved_at,
                        approval_kind='showcase-bulk', clinical_validation_complete=False)


def approve(directory, workspace, actor):
    directory, workspace = Path(directory).resolve(), Path(workspace).resolve()
    if not actor or not actor.strip():
        raise ValueError('Actor must be a non-empty identifier')
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    documents = {d['document_id']: d for d in manifest}
    review_dir, prepared_dir = workspace / 'reviews', workspace / 'prepared'
    review_paths = sorted(review_dir.glob('*.json'))
    if not review_paths:
        raise ValueError('No prepared review JSON artifacts found')
    reviews = {json.loads(p.read_text(encoding='utf-8')).get('document_id'): (p, json.loads(p.read_text(encoding='utf-8'))) for p in review_paths}
    # Validate every source before writing an archive or changing any artifact.
    for doc_id, (_, data) in reviews.items():
        if doc_id not in documents:
            raise ValueError('Review document is not in the curated source manifest: ' + str(doc_id))
        source = directory / documents[doc_id]['filename']
        if not source.is_file() or digest(source.read_bytes()) != data.get('checksum'):
            raise ValueError('Source checksum mismatch for ' + doc_id + '; no files were changed')
    explicit_rejections, excluded_spans = _explicit_rejections(workspace)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    approval_time = datetime.now(timezone.utc).isoformat()
    already = all(data.get('review_policy') == 'showcase-bulk' and data.get('bulk_approval', {}).get('actor') == actor
                  for _, data in reviews.values()) and (workspace / 'catalogue.json').is_file()
    if already:
        report_path = workspace / 'bulk-approval-report.json'
        report = json.loads(report_path.read_text()) if report_path.exists() else {'status': 'already-approved'}
        if all(_workflow_approval_complete(workflow, actor, data['bulk_approval']['approved_at'])
               for _, data in reviews.values() for workflow in data.get('workflows', [])):
            return report
        # Repair older bulk artifacts without issuing a new approval timestamp.
        # Archive their exact prior state before filling workflow approval fields.
        archive = _archive(workspace, stamp)
        for path, data in reviews.values():
            approved_at = data['bulk_approval']['approved_at']
            _approve_workflows(data, actor, approved_at)
            write_json(path, data)
            prepared_path = prepared_dir / path.name
            if prepared_path.exists():
                write_json(prepared_path, data)
        report['archive'] = str(archive)
        report['workflow_metadata_repaired'] = True
        if report_path.exists():
            write_json(report_path, report)
        return report
    archive = _archive(workspace, stamp)
    report_docs, mutations, code_unverified = [], {}, 0
    catalogue_path = workspace / 'catalogue.json'
    catalogue_data = json.loads(catalogue_path.read_text(encoding='utf-8')) if catalogue_path.exists() else {'schema_version': 2, 'source_checksums': {}, 'entries': {}}
    catalogue_data.setdefault('entries', {})
    catalogue_data.setdefault('source_checksums', {})
    for doc_id, (path, data) in reviews.items():
        workflow_map = {w.get('workflow_id'): w for w in data.get('workflows', [])}
        updated, approved_n, excluded_n, split_n, line_blocked_n = [], 0, 0, 0, 0
        explicit_rejection_ids = []
        blockers = []
        for passage in data.get('passages', []):
            decision = passage.get('decision')
            if decision not in APPROVABLE or passage.get('passage_id') in explicit_rejections or passage.get('parent_passage_id') in explicit_rejections:
                row = dict(passage)
                if decision in APPROVABLE and (row.get('passage_id') in explicit_rejections or row.get('parent_passage_id') in explicit_rejections):
                    excluded_n += 1
                    explicit_rejection_ids.append(row.get('passage_id'))
                    row.update(include=False, reviewed=False, explicit_rejection=True)
                updated.append(row)
                continue
            matching_exclusions = [span for span in excluded_spans
                if doc_id == 'icmr-md-hypertension' and type(passage.get('line_start')) is int and
                   type(passage.get('line_end')) is int and passage['line_start'] <= span[2] and
                   span[1] <= passage['line_end'] and not (
                       isinstance(passage.get('selection_review'), dict) and
                       passage['selection_review'].get('reviewed') is True and
                       type(passage.get('char_start')) is int and type(passage.get('char_end')) is int)]
            if matching_exclusions:
                details = ', '.join(f'{span[1]}-{span[2]} ({span[0]})' for span in matching_exclusions)
                reason = 'overlaps explicitly excluded source lines ' + details
                updated.append(dict(passage, include=False, reviewed=False, bulk_approval_blocked=reason))
                blockers.append({'passage_id': passage.get('passage_id'), 'reason': reason})
                line_blocked_n += 1
                continue
            parts, reason = _split_passage(passage, MAX_TEXT)
            if reason:
                blockers.append({'passage_id': passage.get('passage_id'), 'reason': reason})
                updated.append(dict(passage, include=False, reviewed=False, bulk_approval_blocked=reason))
                continue
            if len(parts) > 1:
                split_n += len(parts) - 1
            workflow = workflow_map.get(passage.get('workflow_id'), {})
            category = passage.get('category')
            for row in parts:
                row['include'] = True
                row['reviewed'] = True
                row['reviewed_by'] = actor
                row['reviewed_at'] = approval_time
                row['category'] = category if category in {'monitoring','investigation','referral','lifestyle','follow-up','medication-review'} else 'context'
                row['source_role'] = 'context'
                row['evidence_role'] = 'context'
                row['original_classifier_decision'] = decision
                row['original_decision'] = decision
                row['clinical_validation_complete'] = False
                row['bulk_approval'] = dict(actor=actor, approved_at=approval_time, scope='non-rejected-context', clinical_validation_complete=False)
                if not isinstance(row.get('applicability'), str) or not row['applicability'].strip() or 'review required' in row['applicability'].casefold() or 'unverified' in row['applicability'].casefold():
                    row['applicability'] = PLACEHOLDER
                if not isinstance(row.get('exceptions'), str) or not row['exceptions'].strip() or 'review required' in row['exceptions'].casefold() or 'unverified' in row['exceptions'].casefold():
                    row['exceptions'] = PLACEHOLDER
                row['population'] = workflow.get('population', 'unknown')
                approved_n += 1
                updated.append(row)
        data = dict(data)
        data['passages'] = updated
        _approve_workflows(data, actor, approval_time)
        data['review_policy'] = 'showcase-bulk'
        data['reviewed'] = True
        data['reviewer'] = actor
        data['reviewed_at'] = approval_time
        data['bulk_approval'] = dict(actor=actor, approved_at=approval_time, scope='non-rejected-context', clinical_validation_complete=False)
        mutations[path] = data
        prepared_path = prepared_dir / path.name
        if prepared_path.exists():
            mutations[prepared_path] = data
        # Enable only alias-based showcase mapping. Existing codes remain exactly
        # as curated; candidate code arrays are deliberately never promoted.
        workflows = data.get('workflows', [])
        for workflow in workflows:
            tag = workflow.get('condition')
            entry = catalogue_data['entries'].setdefault(tag, dict(title=workflow.get('title',''), aliases=[], codes=[], candidate_aliases=[], candidate_codes=[], population=workflow.get('population','unknown'), workflow_ids=[]))
            aliases = set(entry.get('aliases', []))
            aliases.update(a for a in entry.get('candidate_aliases', []) if isinstance(a, str))
            title = workflow.get('title')
            if title:
                aliases.add(title)
            for alias in workflow.get('aliases', []) if isinstance(workflow.get('aliases'), list) else []:
                if isinstance(alias, str): aliases.add(alias)
            entry['aliases'] = sorted(aliases, key=normalized)
            entry['reviewed'] = True
            entry['enabled'] = True
            entry['reviewer'] = actor
            entry['reviewed_at'] = approval_time
            entry['approval_kind'] = 'showcase-bulk'
            # Population remains source-derived, including pediatric/unknown.
            entry['population'] = workflow.get('population', entry.get('population', 'unknown'))
            entry.setdefault('codes', [])
            code_unverified += len(entry.get('candidate_codes', []))
        catalogue_data['source_checksums'][doc_id] = data['checksum']
        report_docs.append(dict(document_id=doc_id, candidates=len(data['passages']), approved=approved_n,
            explicit_rejections=excluded_n, explicit_line_exclusions=line_blocked_n,
            explicit_rejection_ids=explicit_rejection_ids,
            excluded_by_classifier=sum(p.get('decision') == 'exclude' for p in data['passages']),
            split_parts_added=split_n, blocked=blockers,
            decisions={d:sum(p.get('decision') == d for p in data['passages']) for d in ('include','supporting-context','needs-review','exclude')}))
    for path, data in mutations.items():
        write_json(path, data)
    write_json(catalogue_path, catalogue_data)
    report = dict(schema_version=2, review_policy='showcase-bulk', bulk_approval=dict(actor=actor, approved_at=approval_time,
        scope='non-rejected-context', clinical_validation_complete=False), archive=str(archive),
        documents=report_docs, totals=dict(approved=sum(d['approved'] for d in report_docs),
            explicit_rejections=sum(d['explicit_rejections'] for d in report_docs),
            explicit_line_exclusions=sum(d['explicit_line_exclusions'] for d in report_docs),
            classifier_excludes=sum(d['excluded_by_classifier'] for d in report_docs),
            split_parts_added=sum(d['split_parts_added'] for d in report_docs),
            blocked=sum(len(d['blocked']) for d in report_docs), candidate_codes_left_unverified=code_unverified))
    write_json(workspace / 'bulk-approval-report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path('md_care_documents'))
    parser.add_argument('--workspace', type=Path, help='Private artifacts directory; default <directory>/.preparation')
    parser.add_argument('--actor', required=True)
    args = parser.parse_args()
    workspace = args.workspace.resolve() if args.workspace else args.directory.resolve() / '.preparation'
    try:
        report = approve(args.directory, workspace, args.actor)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, 'bulk approval failed: ' + str(exc) + '\n')
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
