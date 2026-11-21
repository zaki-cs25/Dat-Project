from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, UnicodeError, json.JSONDecodeError) as e:
        raise ValueError(f"Cannot read {path}: {e}") from e
    if any(not isinstance(x, dict) for x in rows):
        raise ValueError(f"{path}: each JSONL row must be an object")
    return rows


def load_dataset(root: Path) -> dict:
    """Load cases, criteria and reference lists, and verify their frozen fingerprint."""
    cases_dir, rubrics_dir = root / "cases", root / "rubrics"
    cases = [row for f in sorted(cases_dir.glob("*.jsonl")) for row in read_jsonl(f)]
    rubrics = [row for f in sorted(rubrics_dir.glob("*.jsonl")) for row in read_jsonl(f)]
    if not cases:
        raise ValueError(f"No case JSONL files found under {cases_dir}")
    sources = {}
    for f in sorted(root.glob("sources-*.json")):
        value = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(value, list): raise ValueError(f"{f}: expected an array")
        sources[f.name] = value
    case_by_id = {}
    for c in cases:
        cid = c.get("case_id")
        if not isinstance(cid, str) or cid in case_by_id: raise ValueError(f"Invalid or duplicate case_id: {cid!r}")
        case_by_id[cid] = c
    rubric_by_id = {}
    for r in rubrics:
        cid = r.get("case_id")
        if cid not in case_by_id or cid in rubric_by_id: raise ValueError(f"Invalid or duplicate rubric case_id: {cid!r}")
        rubric_by_id[cid] = r
    if set(case_by_id) != set(rubric_by_id): raise ValueError("Every case must have exactly one rubric")
    for c in cases: validate_case(c)
    for r in rubrics: validate_rubric(r)
    by_split = {s: [c for c in cases if c.get("split") == s] for s in ("development", "evaluation")}
    if len(cases) != 100 or len(by_split["development"]) != 20 or len(by_split["evaluation"]) != 80:
        raise ValueError("Dataset must contain 100 cases: 20 development and 80 evaluation")
    groups = {g: sum(c.get("group") == g for c in cases) for g in ("opd", "chronic", "injury")}
    if groups != {"opd": 50, "chronic": 30, "injury": 20}:
        raise ValueError(f"Dataset group counts must be 50 OPD, 30 chronic, 20 injury; got {groups}")
    family_splits = {}
    for c in cases:
        family_splits.setdefault(c["family_id"], set()).add(c["split"])
    if any(len(splits) != 1 for splits in family_splits.values()):
        raise ValueError("A case family appears in both development and evaluation")
    source_ids = {s.get("id") for values in sources.values() for s in values if isinstance(s, dict)}
    for rubric in rubrics:
        for criterion in rubric["criteria"]:
            refs = criterion.get("source_ids", [])
            if any(ref not in source_ids for ref in refs):
                raise ValueError(f"{rubric['case_id']}: criterion {criterion['id']} references an unknown source ID")
    fingerprint = sha(canonical({"cases": cases, "rubrics": rubrics, "sources": sources}))
    expected_file = root / "manifest.json"
    if expected_file.exists():
        manifest = json.loads(expected_file.read_text(encoding="utf-8"))
        expected = manifest.get("dataset_sha256")
        if expected and expected != fingerprint: raise ValueError("Dataset fingerprint does not match manifest.json")
    else: manifest = {"dataset_sha256": fingerprint}
    return {"cases": case_by_id, "rubrics": rubric_by_id, "sources": sources,
            "fingerprint": fingerprint, "manifest": manifest}


def validate_case(c: dict) -> None:
    required = ("case_id", "group", "condition", "scenario", "split", "family_id", "clinical_input", "interview_script")
    if any(k not in c for k in required): raise ValueError(f"{c.get('case_id')}: missing required case fields")
    if c["split"] not in ("development", "evaluation"): raise ValueError(f"{c['case_id']}: invalid split")
    packet=c["clinical_input"]
    expected={"patient","established_conditions","medications","allergies","observations","narrative","missing_information","request","as_of_date","clinician_disposition"}
    if not isinstance(packet, dict) or set(packet)!=expected: raise ValueError(f"{c['case_id']}: clinical_input fields do not match packet schema")
    p = packet.get("patient", {})
    if not isinstance(p,dict) or set(p)!={"age","sex"} or not isinstance(p.get("sex"),str) or not p["sex"].strip(): raise ValueError(f"{c['case_id']}: patient must include age and sex")
    if type(p.get("age")) is not int or not 18 <= p["age"] <= 120: raise ValueError(f"{c['case_id']}: invalid age")
    if packet.get("as_of_date") != "2026-10-24": raise ValueError(f"{c['case_id']}: unexpected as_of_date")
    for key in ("established_conditions","medications","allergies","observations","missing_information"):
        if not isinstance(packet.get(key),list): raise ValueError(f"{c['case_id']}: {key} must be an array")
    if any(not isinstance(x,dict) or not all(k in x for k in ("name","value","unit","when")) for x in packet["observations"]):
        raise ValueError(f"{c['case_id']}: malformed observation")
    if any(not isinstance(packet.get(k),str) for k in ("narrative","request")): raise ValueError(f"{c['case_id']}: narrative and request must be strings")
    if packet.get("clinician_disposition") not in ("routine","urgent","emergency"): raise ValueError(f"{c['case_id']}: invalid clinician_disposition")
    script = c["interview_script"]
    if not isinstance(script, list) or len(script) != 4 or any(not isinstance(t, dict) or not t.get("question") or not t.get("answer") for t in script):
        raise ValueError(f"{c['case_id']}: interview_script must contain four question/answer pairs")


def validate_rubric(r: dict) -> None:
    criteria = r.get("criteria")
    if not isinstance(criteria, list) or not 5 <= len(criteria) <= 8: raise ValueError(f"{r.get('case_id')}: rubric needs 5–8 criteria")
    ids = set()
    for idx,c in enumerate(criteria,1):
        if not isinstance(c, dict) or not isinstance(c.get("id"), str) or c["id"] in ids: raise ValueError(f"{r['case_id']}: invalid/duplicate criterion ID")
        if c["id"]!=f"{r['case_id']}-C{idx}": raise ValueError(f"{r['case_id']}: unknown criterion ID {c['id']!r}; expected sequential case criterion IDs")
        ids.add(c["id"])
        if type(c.get("critical")) is not bool or type(c.get("weight")) is not int or (type(c.get("weight")) is not int or c.get("weight") not in (1, 2, 3)): raise ValueError(f"{r['case_id']}: invalid criterion critical/weight")
        if not c.get("requirement") or not isinstance(c.get("source_ids", []), list): raise ValueError(f"{r['case_id']}: invalid criterion")
