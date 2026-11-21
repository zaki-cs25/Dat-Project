"""Reviewed extensible condition mapping. Symptoms never establish diagnoses."""
import json
from pathlib import Path
import re
from central_park.config import load

BASE = json.loads((Path(__file__).parent / 'data/care_conditions.json').read_text())
TAG = re.compile(r'^[a-z][a-z0-9-]{0,63}$')
# Text-only retrieval synonyms for sections actually present in the ICMR corpus.
# They do not create diagnoses/codes or assert that a passage applies to an adult.
RETRIEVAL_ALIASES = {
    'eczema-dermatitis': ['contact dermatitis', 'established contact dermatitis'],
    'headache': ['episodic tension headache', 'established episodic tension headache'],
    'lower-back-pain': ['nonspecific low back pain', 'established nonspecific low back pain'],
    'pharyngitis-and-sore-throat': ['viral pharyngitis', 'established viral pharyngitis',
                                   'uncomplicated viral pharyngitis'],
    'ckd': ['ckd g3a', 'ckd g3b'],
}


def normalized(value):
    return re.sub(r'\s+', ' ', str(value).casefold()).strip()


def catalogue(path=None, base=None):
    result = dict(BASE if base is None else base)
    target = Path(path or load().care_catalogue_path)
    if not target.exists():
        return result
    data = json.loads(target.read_text())
    if data.get('schema_version') != 2 or not isinstance(data.get('entries'), dict):
        raise ValueError('Invalid care workflow catalogue; prepare/review schema version 2')
    for tag, entry in data['entries'].items():
        if entry.get('reviewed') is not True or entry.get('enabled') is not True:
            continue
        if not TAG.fullmatch(tag) or not entry.get('reviewer') or not entry.get('reviewed_at'):
            raise ValueError('Invalid reviewed care catalogue entry: ' + tag)
        allowed_populations = ('adult', 'mixed', 'unknown', 'pediatric') if entry.get('approval_kind') == 'showcase-bulk' else ('adult', 'mixed')
        if entry.get('population') not in allowed_populations:
            raise ValueError('Adult applicability must be reviewed for care catalogue: ' + tag)
        aliases, codes = entry.get('aliases', []), entry.get('codes', [])
        if not isinstance(aliases, list) or any(not isinstance(a, str) or not a.strip() for a in aliases):
            raise ValueError('Invalid condition aliases: ' + tag)
        if not isinstance(codes, list) or any(not isinstance(c, list) or len(c) != 2
            or any(not isinstance(v, str) or not v for v in c) for c in codes):
            raise ValueError('Invalid explicit condition codes: ' + tag)
        if not aliases and not codes:
            raise ValueError('Condition needs at least one reviewed alias or code: ' + tag)
        old = result.get(tag, {})
        result[tag] = dict(aliases=sorted({normalized(a) for a in aliases + old.get('aliases', [])}),
                           codes=[list(c) for c in sorted({tuple(c) for c in codes + old.get('codes', [])})],
                           code_prefixes=old.get('code_prefixes', []))
    for tag, aliases in RETRIEVAL_ALIASES.items():
        if tag in result:
            result[tag] = {**result[tag], 'aliases': sorted(set(result[tag]['aliases'] + aliases))}
    return result


def inventory_catalogue(reviews, existing=None):
    """Candidate mappings only. No inferred code families or automatic activation."""
    entries = dict((existing or {}).get('entries', {}))
    checksums = {}
    for review in reviews:
        checksums[review['document_id']] = review['checksum']
        for workflow in review['workflows']:
            tag = workflow['condition']
            entry = entries.setdefault(tag, dict(title=workflow['title'], aliases=[], codes=[],
                population=workflow['population'], reviewed=False, enabled=False,
                reviewer='', reviewed_at=None, workflow_ids=[]))
            # Source changes invalidate prior approvals. Never silently merge new
            # source aliases/codes into an already approved entry.
            if workflow['workflow_id'] not in entry['workflow_ids']:
                entry['workflow_ids'].append(workflow['workflow_id'])
                entry.update(reviewed=False, enabled=False)
            entry.setdefault('candidate_aliases', [])
            if workflow['title'].casefold() not in entry['candidate_aliases']:
                entry['candidate_aliases'].append(workflow['title'].casefold())
            entry.setdefault('candidate_codes', [])
            entry.setdefault('candidate_other_codes', [])
            for other in workflow.get('other_codes', []):
                candidate = dict(other, workflow_id=workflow['workflow_id'])
                if candidate not in entry['candidate_other_codes']:
                    entry['candidate_other_codes'].append(candidate)
            for code in workflow['codes']:
                coding = ['http://hl7.org/fhir/sid/icd-10', code]
                if coding not in entry['candidate_codes']:
                    entry['candidate_codes'].append(coding)
    if existing and existing.get('source_checksums') != checksums:
        for entry in entries.values():
            entry.update(reviewed=False, enabled=False)
    return dict(schema_version=2, source_checksums=checksums, entries=entries)
