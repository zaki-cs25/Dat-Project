"""Condition-scoped retrieval from the separate reviewed ICMR collection."""
import json
from pathlib import Path
import httpx
from central_park.config import load
from central_park.care_catalogue import catalogue, normalized
from central_park.telemetry import timed

CATALOGUE = json.loads((Path(__file__).parent / 'data/care_conditions.json').read_text())


@timed('care_evidence.match')
def match_conditions(conditions):
    matched, uncovered = {}, []
    entries = catalogue(base=CATALOGUE)
    for condition in conditions:
        verification = {c.get('code') for c in condition.get('verificationStatus', {}).get('coding', [])}
        if verification & {'refuted', 'entered-in-error', 'provisional', 'differential', 'unconfirmed'}:
            continue
        concept = condition.get('code', {})
        names = {normalized(concept.get('text', ''))} | {normalized(c.get('display', '')) for c in concept.get('coding', [])}
        codes = {(c.get('system'), c.get('code')) for c in concept.get('coding', [])}
        found = False
        for slug, entry in entries.items():
            prefix_match = any(system == allowed_system and code and code.startswith(prefix) for system, code in codes for allowed_system, prefix in entry.get('code_prefixes', []))
            if names & {normalized(a) for a in entry['aliases']} or codes & {tuple(c) for c in entry['codes']} or prefix_match:
                matched.setdefault(slug, []).append(condition['id'])
                found = True
        if not found:
            uncovered.append(concept.get('text') or next(iter(names - {''}), condition.get('id', 'Unknown condition')))
    return matched, uncovered


@timed('care_evidence.request')
def request(path, body):
    cfg = load()
    r = httpx.post(cfg.iris_rest_base_url + '/care-guidelines/' + path, json=body,
                   auth=(cfg.fhir_user, cfg.fhir_password) if cfg.fhir_user else None, timeout=120)
    if not r.is_success:
        try:
            detail = r.json().get('error')
        except (ValueError, AttributeError):
            detail = None
        if isinstance(detail, str):
            raise httpx.HTTPStatusError(f'Care-guideline {path} failed (HTTP {r.status_code}): {detail}',
                                        request=r.request, response=r)
    r.raise_for_status()
    result = r.json()
    if result.get('error'):
        raise ValueError(result['error'])
    return result


@timed('care_evidence.retrieve')
def retrieve(matched, concerns):
    passages, missing = {}, []
    seen = set()
    for condition in matched:
        hits = request('search', {'condition': condition, 'query': condition + ' ' + concerns,
                                  'k': 5, 'library': 'markdown'})['hits']
        # The current app generates adult drafts. Keep source population labels;
        # a bulk import never turns explicitly pediatric context into adult evidence.
        valid = [p for p in hits if p.get('reviewed') is True and p.get('condition') == condition
                 and p.get('workflow_review', {}).get('population') != 'pediatric']
        if not valid:
            missing.append(condition)
        for p in valid[:5]:
            signature = (condition, p.get('category'), p.get('text'), p.get('applicability'), p.get('exceptions'))
            if signature in seen:
                continue
            seen.add(signature)
            passages[p['passage_id']] = p
    return list(passages.values()), missing
