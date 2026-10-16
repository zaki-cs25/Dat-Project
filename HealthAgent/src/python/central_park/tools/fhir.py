"""FHIR retrieval tool.

Issues a fan-out of FHIR R4 searches against the IRIS-hosted endpoint to
build a snapshot of the patient's clinically-relevant context. Five parallel
queries: the Patient resource itself plus four searches for active
Conditions, active MedicationRequests, the 20 most recent Observations,
and all AllergyIntolerances.

We hold the results to the fields the agent actually needs. Full FHIR
resources are noisy and would blow up the prompt budget; the agent only
cares about display strings, codes, and dates.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import TypedDict

import httpx

_log = logging.getLogger("central_park.fhir")

from central_park.config import load
from central_park.errors import ClinicalContextError
from central_park.telemetry import timed

QUESTIONNAIRE_REF = "Questionnaire/triage-intake"

class PatientNotFoundError(ValueError):
    def __init__(self, patient_id: str):
        super().__init__(f"Patient '{patient_id}' was not found. Select an existing patient ID before starting an interview.")

_SYMPTOM_CODES: dict[str, tuple[str, str]] = {
    "shortness of breath": ("267036007", "Dyspnea"),
    "chest tightness":     ("23924001",  "Chest tightness"),
    "chest pain":          ("29857009",  "Chest pain"),
    "fever":               ("386661006", "Fever"),
    "nausea":              ("422587007", "Nausea"),
    "dizziness":           ("404640003", "Dizziness"),
    "weakness":            ("299377003", "Unilateral weakness"),
}

# These rules classify mentions in English interview answers, not diagnoses.
# Commas and coordinating conjunctions retain negation across symptom lists.
_SYMPTOM_TERMS = "|".join(re.escape(term) for term in _SYMPTOM_CODES)
_SYMPTOM_MENTION = re.compile(r"\b(?:" + _SYMPTOM_TERMS + r")\b", re.I)
_SYMPTOM_CLAUSE = re.compile(
    r"[;.!?\n]|\b(?:but|however|yet|although|except)\b|"
    r"(?:,|\band\b|\bor\b)(?=\s*(?:" + _SYMPTOM_TERMS +
    r")\s+(?:is|has|started|began|developed|persists|continues)\b)", re.I)
_SYMPTOM_ASSERTION = re.compile(
    r"\b(?:i\s+(?:(?:do|now|still|currently)\s+)?"
    r"(?:have|feel|am\s+(?:having|experiencing))|there\s+(?:is|are))\b", re.I)
_SYMPTOM_NEGATION = re.compile(
    r"\b(?:no|not|without|denies|deny|denied|never|none|negative\s+for|free\s+of|"
    r"isn't|aren't|wasn't|weren't|didn't|doesn't|don't|haven't|hasn't)\b", re.I)
_SYMPTOM_NONCURRENT = re.compile(
    r"\b(?:history\s+of|used\s+to|previously|in\s+the\s+past|last\s+(?:year|month|week)|"
    r"years?\s+ago|possible|possibly|maybe|might|may\s+have|could\s+have|"
    r"unsure|uncertain|not\s+sure|cannot\s+tell|can't\s+tell|whether|if|"
    r"(?:do|could|might|may|can)\s+i|"
    r"watch\s+for|monitor\s+for|mother|father|sister|brother|partner|son|daughter)\b", re.I)
_SYMPTOM_POST_ABSENCE = re.compile(
    r"^\s*(?::|[-–—])?\s*(?:(?:is|are|was|were|has(?:\s+been)?|have(?:\s+been)?)\s+)?"
    r"(?:(?:now|currently)\s+)?"
    r"(?:no|none|absent|denied|negative|resolved|gone|"
    r"possible|uncertain|not\s+(?:present|occurring|now|today|started)|isn't\s+present|aren't\s+present|"
    r"in\s+the\s+past|last\s+(?:year|month|week)|yesterday|years?\s+ago)\b", re.I)
_SYMPTOM_NONNEGATING = re.compile(
    r"\b(?:not\s+(?:only|just)|no\s+(?:change|improvement|relief|worsening)\b)\b", re.I)
_SYMPTOM_COORDINATED_TAIL = re.compile(
    r"^(?:\s*(?:,\s*(?:(?:and|or)\s+)?|(?:and|or)\s+)"
    r"(?:" + _SYMPTOM_TERMS + r")\b)+", re.I)


def _affirmed_symptoms(qa_items: list[dict]) -> set[str]:
    """Select unqualified positive mentions; leave other mentions in the transcript.

    This bounded heuristic prevents denials, historical/uncertain mentions and
    mentions about other people from becoming positive patient observations.
    It does not create negative observations or resolve contradictory answers.
    """
    affirmed: set[str] = set()
    for item in qa_items:
        answer = item.get("answer", "").replace("’", "'")
        for clause in _SYMPTOM_CLAUSE.split(answer):
            clause = re.sub(r"\s+", " ", clause).strip()
            for mention in _SYMPTOM_MENTION.finditer(clause):
                before = clause[:mention.start()]
                # A new assertion starts a new scope: "No fever, I have nausea".
                # Preserve governing uncertainty in "not sure if I have fever".
                scope_start = 0
                for assertion in _SYMPTOM_ASSERTION.finditer(before):
                    prefix = before[:assertion.start()].rstrip()
                    if (not prefix or prefix.endswith(",") or
                            re.search(r"\b(?:and|or|so)$", prefix, re.I)):
                        scope_start = assertion.end()
                before = before[scope_start:]
                before = _SYMPTOM_NONNEGATING.sub(" ", before)
                after = clause[mention.end():]
                # Shared postfix denial: "chest pain and weakness are absent".
                # Consume only symptom-list members, never a new subject/clause.
                after = _SYMPTOM_COORDINATED_TAIL.sub("", after)
                if (_SYMPTOM_NEGATION.search(before) or
                        _SYMPTOM_NONCURRENT.search(before) or
                        _SYMPTOM_POST_ABSENCE.search(after)):
                    continue
                affirmed.add(mention.group().lower())
    return affirmed


_TRIAGE_LEVEL_SR = {
    "self-care":   ("routine", "243958005", "Self-care"),
    "see-gp":      ("routine", "306206005", "Referral to general practitioner"),
    "urgent-care": ("urgent",  "310861008", "Referral to urgent care clinic"),
    "ed":          ("stat",    "182813001", "Emergency hospital admission"),
}


class PatientContext(TypedDict):
    patient: dict
    conditions: list[dict]
    medications: list[dict]
    observations: list[dict]
    allergies: list[dict]


def _auth() -> tuple[str, str] | None:
    cfg = load()
    if cfg.fhir_user and cfg.fhir_password:
        return (cfg.fhir_user, cfg.fhir_password)
    return None


def _client() -> httpx.Client:
    cfg = load()
    return httpx.Client(
        base_url=cfg.fhir_base_url,
        auth=_auth(),
        headers={"Accept": "application/fhir+json"},
        timeout=10.0,
    )


def _coding_display(codeable: dict | None) -> str:
    """Pick the best human-readable string out of a CodeableConcept."""
    if not codeable:
        return ""
    if text := codeable.get("text"):
        return text
    for coding in codeable.get("coding", []):
        if display := coding.get("display"):
            return display
    return ""


def _entries(bundle: dict) -> list[dict]:
    return [e["resource"] for e in bundle.get("entry", []) if "resource" in e]


def _trim_patient(p: dict) -> dict:
    name = ""
    for n in p.get("name", []):
        name = n.get('text') or ' '.join([*n.get('given', []), n.get('family', '')]).strip()
        if name:
            break
    return {
        "id": p.get("id"),
        "name": name,
        "gender": p.get("gender"),
        "birthDate": p.get("birthDate"),
    }


def _trim_condition(r: dict) -> dict:
    return {
        "display": _coding_display(r.get("code")),
        "clinical_status": _coding_display(r.get("clinicalStatus")),
        "onset": r.get("onsetDateTime") or r.get("onsetPeriod", {}).get("start"),
    }


def _trim_medication(r: dict) -> dict:
    med = r.get("medicationCodeableConcept") or {}
    return {
        "display": _coding_display(med),
        "status": r.get("status"),
        "authored_on": r.get("authoredOn"),
        "dosage": (r.get("dosageInstruction") or [{}])[0].get("text"),
    }


def _trim_observation(r: dict) -> dict:
    base = {
        "display": _coding_display(r.get("code")),
        "effective": r.get("effectiveDateTime"),
        "status": r.get("status"),
    }
    if r.get("id"):
        base["id"] = r["id"]
    if r.get("encounter", {}).get("reference"):
        base["encounter"] = r["encounter"]["reference"]
    if "valueQuantity" in r:
        vq = r["valueQuantity"]
        base["value"] = vq.get("value")
        base["unit"] = vq.get("unit")
    elif "component" in r:
        # Multi-part observations like BP. Flatten to "Systolic 148 mmHg, Diastolic 94 mmHg".
        parts = []
        for c in r["component"]:
            label = _coding_display(c.get("code"))
            vq = c.get("valueQuantity") or {}
            v, u = vq.get("value"), vq.get("unit")
            if v is not None:
                parts.append(f"{label} {v} {u or ''}".strip())
        base["value"] = ", ".join(parts) or None
    else:
        for field in ("valueBoolean", "valueInteger", "valueString"):
            if field in r:
                base["value"] = r[field]
                break
    return base


def _trim_allergy(r: dict) -> dict:
    return {
        "display": _coding_display(r.get("code")),
        "clinical_status": _coding_display(r.get("clinicalStatus")),
        "criticality": r.get("criticality"),
        "reactions": [
            _coding_display(m)
            for reaction in r.get("reaction", [])
            for m in reaction.get("manifestation", [])
        ],
    }


def _extract_id(resp: httpx.Response, resource_type: str) -> str:
    """Extract the server-assigned id from a FHIR create response.

    IRIS returns HTTP 201 with an empty body; the id lives in Location header.
    """
    new_id = ""
    if resp.content:
        try:
            new_id = resp.json().get("id", "")
        except ValueError:
            pass
    if not new_id:
        location = resp.headers.get("Location") or resp.headers.get("Content-Location") or ""
        parts = [p for p in location.split("/") if p]
        if resource_type in parts:
            idx = parts.index(resource_type)
            if idx + 1 < len(parts):
                new_id = parts[idx + 1]
    return new_id


@timed('fhir.write.questionnaire_response')
def post_questionnaire_response(patient_id: str, qa_items: list[dict]) -> str:
    """POST a QuestionnaireResponse to FHIR and return the server-assigned id.

    Each item in qa_items must have keys: link_id, question, answer.
    """
    authored = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "resourceType": "QuestionnaireResponse",
        "questionnaire": QUESTIONNAIRE_REF,
        "status": "completed",
        "subject": {"reference": f"Patient/{patient_id}"},
        "authored": authored,
        "item": [
            {
                "linkId": item["link_id"],
                "text": item["question"],
                "answer": [{"valueString": item["answer"]}],
            }
            for item in qa_items
        ],
    }
    with _client() as c:
        resp = c.post(
            "/QuestionnaireResponse",
            json=payload,
            headers={"Content-Type": "application/fhir+json"},
        )
        resp.raise_for_status()
    return _extract_id(resp, "QuestionnaireResponse")


@timed('fhir.read.questionnaire_response')
def get_questionnaire_response(qr_id: str, patient_id: str | None = None) -> list[dict]:
    """Fetch a QuestionnaireResponse and return items as [{link_id, question, answer}]."""
    with _client() as c:
        resp = c.get(f"/QuestionnaireResponse/{qr_id}")
        resp.raise_for_status()
    body = resp.json()
    subject = (body.get("subject") or {}).get("reference", "")
    if patient_id and subject != f"Patient/{patient_id}":
        raise ValueError("QuestionnaireResponse does not belong to the selected patient")
    items = []
    for item in body.get("item", []):
        answers = item.get("answer") or []
        items.append({
            "link_id": item.get("linkId", ""),
            "question": item.get("text", ""),
            "answer": answers[0].get("valueString", "") if answers else "",
        })
    return items


@timed('fhir.write.encounter')
def create_encounter(patient_id: str, qr_id: str | None = None) -> str:
    """Create a finished virtual triage Encounter and return its id."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload: dict = {
        "resourceType": "Encounter",
        "status": "finished",
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": "VR",
            "display": "virtual",
        },
        "type": [
            {
                "coding": [
                    {
                        "system": "http://snomed.info/sct",
                        "code": "11429006",
                        "display": "Consultation",
                    }
                ],
                "text": "Triage consultation",
            }
        ],
        "subject": {"reference": f"Patient/{patient_id}"},
        "period": {"start": now, "end": now},
    }
    # IRIS restricts reasonReference to Condition/Procedure/Observation/ImmunizationRecommendation
    # so we link the QR via reasonCode text instead
    if qr_id:
        payload["reasonCode"] = [{"text": f"Triage intake QuestionnaireResponse/{qr_id}"}]
    with _client() as c:
        resp = c.post("/Encounter", json=payload, headers={"Content-Type": "application/fhir+json"})
        resp.raise_for_status()
    return _extract_id(resp, "Encounter")


def _handoff_notes(handoff: dict) -> list[dict]:
    """Flatten the agent's narrative into ServiceRequest.note annotations.

    Each note is human-readable in the Management Portal and carries a stable
    label prefix the clinician dashboard parses back out (see ui/src/api.ts).
    The narrative is otherwise not persisted anywhere in FHIR, so a clinician
    reviewing a past case would lose the reasoning without this.
    """
    notes: list[dict] = []
    if hpi := handoff.get("hpi"):
        notes.append({"text": f"HPI: {hpi}"})
    for action in handoff.get("recommended_actions") or []:
        notes.append({"text": f"Action: {action}"})
    for flag in handoff.get("red_flags") or []:
        notes.append({"text": f"Red flag: {flag}"})
    for issue in handoff.get("detected_issues") or []:
        sev = issue.get("severity", "")
        detail = issue.get("detail", "")
        # severity|detail — parsed back by the clinician console.
        notes.append({"text": f"Interaction: {sev}|{detail}"})
    # Explainability: the agents that ran and the reviewer's verdict, so the
    # console can show how the triage was reached without re-running anything.
    for step in handoff.get("trace") or []:
        notes.append({"text": f"Trace: {step}"})
    if verifier := (handoff.get("verifier_note") or "").strip():
        notes.append({"text": f"Verifier: {verifier}"})
    for c in handoff.get("citations") or []:
        source = c.get("source") or c.get("slug") or ""
        snippet = c.get("snippet") or ""
        # source|snippet — source is a single token, snippet is last.
        notes.append({"text": f"Guideline: {source}|{snippet}"})
    if qr_id := handoff.get("qr_id"):
        notes.append({"text": f"QR: {qr_id}"})
    return notes


@timed('fhir.write.service_request')
def create_service_request(
    patient_id: str,
    encounter_id: str,
    triage_level: str,
    chief_complaint: str,
    handoff: dict | None = None,
) -> str:
    """Create a ServiceRequest from triage outcome and return its id.

    When `handoff` is supplied, the agent's narrative (HPI, recommended
    actions, red flags, cited guidelines, source QuestionnaireResponse id) is
    persisted as note annotations so the clinician dashboard can reconstruct
    the full case later without re-running the LLM.
    """
    priority, code, display = _TRIAGE_LEVEL_SR.get(
        triage_level, ("routine", "306206005", "Referral to general practitioner")
    )
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "resourceType": "ServiceRequest",
        "status": "active",
        "intent": "proposal",
        "priority": priority,
        "code": {
            "coding": [
                {"system": "http://snomed.info/sct", "code": code, "display": display}
            ],
            "text": display,
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f"Encounter/{encounter_id}"},
        "authoredOn": now,
        "reasonCode": [{"text": chief_complaint}],
    }
    if handoff and (notes := _handoff_notes(handoff)):
        payload["note"] = notes
    with _client() as c:
        resp = c.post(
            "/ServiceRequest", json=payload, headers={"Content-Type": "application/fhir+json"}
        )
        resp.raise_for_status()
    return _extract_id(resp, "ServiceRequest")


@timed('fhir.write.observations')
def create_observations(
    patient_id: str,
    encounter_id: str,
    qa_items: list[dict],
) -> list[str]:
    """Create coded Observations from interview answers and return their ids.

    Creates a severity-score Observation (LOINC 72514-3) and one SNOMED-coded
    Observation per affirmed symptom keyword in the patient's answers. Denied,
    historical and uncertain mentions stay in the transcript without a positive
    boolean observation.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    base = {
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "survey",
                        "display": "Survey",
                    }
                ]
            }
        ],
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f"Encounter/{encounter_id}"},
        "effectiveDateTime": now,
    }

    by_link = {item["link_id"]: item["answer"] for item in qa_items}
    payloads = []

    # Severity score → LOINC 72514-3. The adaptive interview may not use the
    # reserved "severity" link id, so fall back to any answer that reads like a
    # 1-10 rating ("7 out of 10"). Extract the first integer and clamp to [1, 10].
    severity_text = by_link.get("severity", "")
    if not severity_text:
        severity_text = next(
            (item["answer"] for item in qa_items if "out of 10" in item.get("answer", "").lower()),
            "",
        )
    m = re.search(r"\b(\d+)\b", severity_text)
    if m:
        score = min(10, max(1, int(m.group(1))))
        payloads.append({
            **base,
            "resourceType": "Observation",
            "status": "preliminary",
            "code": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": "72514-3",
                        "display": "Pain severity - 0-10 verbal numeric rating [Score] - Reported",
                    }
                ],
                "text": "Self-reported severity score",
            },
            "valueInteger": score,
        })

    # Preserve answer/clause boundaries and the scope of coordinated denials.
    # Scan all answer link IDs so adaptive free-form follow-ups still code.
    affirmed = _affirmed_symptoms(qa_items)
    for keyword, (code, display) in _SYMPTOM_CODES.items():
        if keyword in affirmed:
            payloads.append({
                **base,
                "resourceType": "Observation",
                "status": "preliminary",
                "code": {
                    "coding": [
                        {"system": "http://snomed.info/sct", "code": code, "display": display}
                    ],
                    "text": display,
                },
                "valueBoolean": True,
            })

    ids: list[str] = []
    with _client() as c:
        for payload in payloads:
            try:
                resp = c.post(
                    "/Observation",
                    json=payload,
                    headers={"Content-Type": "application/fhir+json"},
                )
                resp.raise_for_status()
                ids.append(_extract_id(resp, "Observation"))
            except Exception as exc:
                _log.warning(
                    "create_observation failed for %s: %s",
                    payload.get("code", {}).get("text"),
                    exc,
                )
    return ids


@timed('fhir.write.detected_issues')
def create_detected_issues(patient_id: str, issues: list[dict]) -> list[str]:
    """Persist safety-agent findings as FHIR DetectedIssue resources.

    Each issue is {code, severity, detail, medication}. Best-effort: a write
    failure is logged and skipped so a partial footprint never blocks triage.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids: list[str] = []
    with _client() as c:
        for issue in issues:
            payload = {
                "resourceType": "DetectedIssue",
                "status": "preliminary",
                "severity": issue.get("severity", "moderate"),
                "code": {"text": issue.get("code", "interaction")},
                "patient": {"reference": f"Patient/{patient_id}"},
                "identifiedDateTime": now,
                "detail": issue.get("detail", ""),
            }
            try:
                resp = c.post(
                    "/DetectedIssue", json=payload, headers={"Content-Type": "application/fhir+json"}
                )
                resp.raise_for_status()
                ids.append(_extract_id(resp, "DetectedIssue"))
            except Exception as exc:
                _log.warning("create_detected_issue failed for %s: %s", issue.get("code"), exc)
    return ids


@timed('fhir.read.patient_context')
def get_patient_context(patient_id: str) -> PatientContext:
    if not re.fullmatch(r"[A-Za-z0-9.-]{1,64}", patient_id):
        raise ValueError("Invalid patient ID")
    with _client() as c:
        patient_resp = c.get(f"/Patient/{patient_id}")
        if patient_resp.status_code == 404:
            raise PatientNotFoundError(patient_id)
        patient_resp.raise_for_status()
        conditions_resp = c.get(
            "/Condition",
            params={"patient": patient_id, "clinical-status": "active"},
        )
        meds_resp = c.get(
            "/MedicationRequest",
            params={"patient": patient_id, "status": "active"},
        )
        statements_resp = c.get(
            "/MedicationStatement",
            params={"patient": patient_id, "status": "active,unknown"},
        )
        obs_resp = c.get(
            "/Observation",
            params={"patient": patient_id, "_sort": "-date", "_count": "20"},
        )
        allergies_resp = c.get("/AllergyIntolerance", params={"patient": patient_id})

    # A failed ancillary read is unknown clinical context, never an empty,
    # reassuring list. Surface it so the caller can report unavailable data.
    for label, response in (("Condition", conditions_resp), ("MedicationRequest", meds_resp),
                            ("MedicationStatement", statements_resp),
                            ("Observation", obs_resp), ("AllergyIntolerance", allergies_resp)):
        if not response.is_success:
            raise ClinicalContextError(f"FHIR {label} context is unavailable")

    return {
        "patient": _trim_patient(patient_resp.json()),
        "conditions": [_trim_condition(r) for r in _entries(conditions_resp.json())],
        "medications": [_trim_medication(r) for r in _entries(meds_resp.json())]
        + [_trim_medication(r) for r in _entries(statements_resp.json())],
        "observations": [_trim_observation(r) for r in _entries(obs_resp.json())],
        "allergies": [_trim_allergy(r) for r in _entries(allergies_resp.json())],
    }
