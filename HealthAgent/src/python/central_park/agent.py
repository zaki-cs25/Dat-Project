"""Patient interview assessment, safety checks, evidence review and FHIR persistence."""

from __future__ import annotations

import json
import logging
import pathlib
import re
from typing import Literal, TypedDict

_log = logging.getLogger("central_park.agent")

from central_park import reasoning
from central_park.errors import ModelOutputError, ModelServiceError
from central_park.llm import get_provider
from central_park.tools import (
    create_detected_issues,
    create_encounter,
    create_observations,
    create_service_request,
    get_patient_context,
    get_questionnaire_response,
    safety,
    search_guidelines,
)
from central_park.telemetry import timed, model_stage

_HANDOFF_PROMPT_PATH = pathlib.Path(__file__).parent / "prompts" / "handoff.txt"
_HANDOFF_PROMPT = _HANDOFF_PROMPT_PATH.read_text(encoding="utf-8")

TriageLevel = Literal["self-care", "see-gp", "urgent-care", "ed"]


class TriageState(TypedDict, total=False):
    # Inputs
    patient_id: str
    message: str
    conversation_id: str | None
    # Populated during execution
    patient_context: dict
    guidelines: list[dict]
    level: TriageLevel
    summary: str
    citations: list[dict]
    red_flags: list[str]
    communication_id: str
    # Populated by the agentic reasoning loop + verifier
    retrieved_sources: list[str]
    tool_trace: list[dict]
    verifier_note: str
    # Populated by the deterministic safety / interaction agent
    detected_issues: list[dict]
    safety_level: str


# --- nodes ------------------------------------------------------------------


# Hard emergency phrases. A non-negated match short-circuits to ED escalation
# before the LLM runs. Keys are lowercase substrings; values are the clinical
# reason surfaced to the clinician.
#
# Scope is deliberately narrow: only presentations that warrant the emergency
# department *regardless of context* (stroke signs, airway compromise,
# anaphylaxis, major haemorrhage, syncope, suicidal ideation). Nuanced cardiac
# complaints — chest pain, chest tightness — are intentionally NOT here: they
# are common and often benign, so they need the patient's FHIR risk factors and
# guideline retrieval to triage correctly. That reasoning is the LLM's job, and
# routing them through `reason` is what the flagship chest-tightness demo
# exercises. This gate is the floor for the can't-miss cases, not a replacement
# for clinical reasoning.
_RED_FLAG_PATTERNS: tuple[tuple[str, str], ...] = (
    # Airway / breathing
    ("can't breathe", "difficulty breathing"),
    ("cant breathe", "difficulty breathing"),
    ("can not breathe", "difficulty breathing"),
    ("cannot breathe", "difficulty breathing"),
    ("struggling to breathe", "difficulty breathing"),
    ("gasping for air", "difficulty breathing"),
    # Stroke (FAST)
    ("slurred speech", "slurred speech"),
    ("speech is slurred", "slurred speech"),
    ("face is drooping", "facial droop"),
    ("face drooping", "facial droop"),
    ("facial droop", "facial droop"),
    ("weakness on one side", "unilateral weakness"),
    ("one-sided weakness", "unilateral weakness"),
    ("numbness on one side", "unilateral numbness"),
    ("worst headache", "thunderclap headache"),
    # Circulation / consciousness
    ("passed out", "syncope"),
    ("pass out", "syncope"),
    ("fainted", "syncope"),
    ("unconscious", "loss of consciousness"),
    # Major bleeding
    ("coughing up blood", "hemoptysis"),
    ("vomiting blood", "hematemesis"),
    ("severe bleeding", "severe hemorrhage"),
    ("uncontrolled bleeding", "severe hemorrhage"),
    ("won't stop bleeding", "severe hemorrhage"),
    # Allergy / psych
    ("anaphylaxis", "anaphylaxis"),
    ("suicidal", "suicidal ideation"),
    ("kill myself", "suicidal ideation"),
)

# Negation tokens that, if they appear just before a matched phrase, void the
# match — so "no slurred speech" and "denies passing out" do not escalate.
_NEGATION_RE = re.compile(r"\b(?:no|not|without|denies|deny|never|isn't|aren't|wasn't|weren't|didn't|doesn't|don't)\b", re.I)
_HISTORY_RE = re.compile(r"\b(?:history of|previously|previous|last year|years ago|used to|once|past)\b", re.I)


def _detect_red_flags(text: str) -> list[str]:
    """Return clinical reasons for each non-negated red-flag phrase in `text`."""
    lowered = text.lower()
    found: list[str] = []
    for keyword, reason in _RED_FLAG_PATTERNS:
        for match in re.finditer(re.escape(keyword), lowered):
            idx = match.start()
            # Clause boundaries keep earlier denials from masking a later
            # positive mention, including repeated mentions of the same flag.
            window = lowered[max(0, idx - 80):idx]
            window = re.split(r"[,;.!?]|\bbut\b|\bhowever\b", window)[-1]
            context = " ".join(window.split()[-8:])
            after = lowered[match.end():match.end() + 40]
            if _NEGATION_RE.search(context) or _HISTORY_RE.search(context + " " + after):
                continue
            if reason not in found:
                found.append(reason)
            break
    return found


def _validate_red_flags(state: TriageState) -> dict:
    """Deterministic safety gate, run before the LLM.

    Hits short-circuit straight to ED escalation without an LLM call; a clear
    scan falls through to `reason`. Returns an empty `red_flags` list when clear
    so the router can branch on it.
    """
    flags = _detect_red_flags(state.get("message", ""))
    if not flags:
        return {"red_flags": []}
    _log.info("validate_red_flags: hard escalation, matched %r", flags)
    summary = (
        "Deterministic red-flag screen matched: "
        + ", ".join(flags)
        + ". Escalated to the emergency department without LLM assessment as a "
        "safety precaution; immediate clinician review required."
    )
    return {"level": "ed", "summary": summary, "red_flags": flags, "citations": []}


def _route_red_flags(state: TriageState) -> Literal["escalate", "reason"]:
    return "escalate" if state.get("red_flags") else "reason"


def _route(state: TriageState) -> Literal["escalate", "end"]:
    return "escalate" if state.get("level") in ("urgent-care", "ed") else "end"



# --- explainability ---------------------------------------------------------


def _build_trace(
    *, detected_issues: list[dict], tool_trace: list[dict], red_flagged: bool
) -> list[str]:
    """A short, human-readable record of which agents ran and what they did.

    Persisted on the ServiceRequest so the clinician console can show the
    reasoning path for a past case without re-running any model.
    """
    steps = ["Context agent: pulled the patient's FHIR record"]
    if detected_issues:
        codes = ", ".join(i["code"] for i in detected_issues)
        steps.append(f"Safety agent: flagged {len(detected_issues)} interaction(s) ({codes})")
    else:
        steps.append("Safety agent: no medication/allergy interactions")
    if red_flagged:
        steps.append("Red-flag gate: matched a can't-miss emergency, escalated to ED")
        return steps
    steps.append("Red-flag gate: clear")
    for t in tool_trace:
        args = t.get("args") or {}
        detail = args.get("query") or args.get("contains") or ""
        steps.append(f"Triage agent: called {t.get('action')}({detail})".strip())
    steps.append("Reviewer agent: grounded citations and checked the level")
    return steps


# --- shared FHIR persistence ------------------------------------------------


@timed('fhir.persistence')
def _persist_fhir(
    patient_id: str,
    triage_level: str,
    chief_complaint: str,
    *,
    qr_id: str | None = None,
    qa_transcript: list[dict] | None = None,
    handoff: dict | None = None,
    detected_issues: list[dict] | None = None,
) -> dict:
    """Write the Encounter -> ServiceRequest -> Observation cascade for one triage.

    Shared by both entrypoints:
      - run_interview() supplies a QuestionnaireResponse id (linked on the
        Encounter) and a structured Q&A transcript (parsed into Observations).
      - run() (the free-text API path) supplies neither, so the Encounter has no
        QR linkage and no Observations are written — there is no structured Q&A
        to code. It still gets an Encounter + ServiceRequest so a direct API
        call leaves the same first-class FHIR footprint as the interview path.

    Every write is best-effort: failures are logged and the cascade continues,
    so a partial FHIR footprint never blocks the triage response.
    """
    encounter_id = ""
    service_request_id = ""
    observation_ids: list[str] = []
    detected_issue_ids: list[str] = []

    if detected_issues:
        try:
            detected_issue_ids = create_detected_issues(patient_id, detected_issues)
        except Exception as exc:
            _log.warning("create_detected_issues failed: %s", exc)

    try:
        encounter_id = create_encounter(patient_id, qr_id=qr_id)
    except Exception as exc:
        body = getattr(getattr(exc, "response", None), "text", "")
        _log.warning("create_encounter failed: %s | body: %s", exc, body)

    if encounter_id:
        try:
            service_request_id = create_service_request(
                patient_id, encounter_id, triage_level, chief_complaint, handoff=handoff
            )
        except Exception as exc:
            body = getattr(getattr(exc, "response", None), "text", "")
            _log.warning("create_service_request failed: %s | body: %s", exc, body)

        if qa_transcript:
            try:
                observation_ids = create_observations(patient_id, encounter_id, qa_transcript)
            except Exception as exc:
                _log.warning("create_observations failed: %s", exc)

    return {
        "encounter_id": encounter_id,
        "service_request_id": service_request_id,
        "observation_ids": observation_ids,
        "detected_issue_ids": detected_issue_ids,
    }


# --- public entrypoint ------------------------------------------------------


@timed('assessment.operation')
def run_interview(patient_id: str, questionnaire_response_id: str) -> dict:
    """Generate a clinician handoff summary from a stored QuestionnaireResponse.

    Fetches the QR from FHIR by id, retrieves matching guidelines via vector
    search, then asks the LLM to produce a structured clinician handoff.
    Called from the FastAPI /interview endpoint.
    """
    patient_context = get_patient_context(patient_id)

    # Fetch the answers the patient gave during the interview.
    qa_transcript = get_questionnaire_response(questionnaire_response_id, patient_id=patient_id)
    transcript_text = " ".join(item.get("answer", "") for item in qa_transcript)
    hard_flags = _detect_red_flags(transcript_text)

    # Use chief-complaint + onset answers as the vector search query.
    query = " ".join(
        item["answer"] for item in qa_transcript[:2] if item.get("answer")
    )
    guidelines = [] if hard_flags else search_guidelines(query, k=5)

    user_payload = json.dumps(
        {
            "patient_context": patient_context,
            "guidelines": guidelines,
            "interview_transcript": [
                {"question": item["question"], "answer": item["answer"]}
                for item in qa_transcript
            ],
        },
        ensure_ascii=False,
    )
    provider = None
    if hard_flags:
        parsed = {"triage_level": "ed", "chief_complaint": qa_transcript[0].get("answer", "Emergency symptoms"),
                  "hpi": "Deterministic red-flag screen matched: " + ", ".join(hard_flags) + ".",
                  "red_flags": hard_flags,
                  "recommended_actions": ["Seek emergency care now; immediate clinician review required."], "citations": []}
    else:
        provider = get_provider()
        try:
            with model_stage('assessment', input_chars=len(user_payload)):
                raw = provider.complete(system=_HANDOFF_PROMPT, messages=[{"role": "user", "content": user_payload}])
        except Exception as exc:
            raise ModelServiceError("Assessment model is unavailable") from exc
        try:
            parsed = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        except json.JSONDecodeError as exc:
            _log.warning("run_interview: LLM returned non-JSON: %r", raw[:200])
            raise ModelOutputError("Assessment model returned malformed JSON") from exc
    if not isinstance(parsed, dict):
        raise ModelOutputError("Assessment model output must be a JSON object")
    triage_level = parsed.get("triage_level")
    if triage_level not in ("self-care", "see-gp", "urgent-care", "ed"):
        raise ModelOutputError("Assessment model returned an invalid triage_level")
    if not isinstance(parsed.get("chief_complaint"), str) or not parsed["chief_complaint"].strip():
        raise ModelOutputError("Assessment model returned an invalid chief_complaint")
    if not isinstance(parsed.get("hpi"), str) or not parsed["hpi"].strip():
        raise ModelOutputError("Assessment model returned an invalid hpi")
    if not isinstance(parsed.get("red_flags"), list) or not all(isinstance(x, str) for x in parsed["red_flags"]):
        raise ModelOutputError("Assessment model returned invalid red_flags")
    if not isinstance(parsed.get("recommended_actions"), list) or not all(isinstance(x, str) for x in parsed["recommended_actions"]):
        raise ModelOutputError("Assessment model returned invalid recommended_actions")
    if not isinstance(parsed.get("citations"), list) or not all(isinstance(x, dict) for x in parsed["citations"]):
        raise ModelOutputError("Assessment model returned invalid citations")
    chief_complaint = parsed["chief_complaint"]
    hpi = parsed["hpi"]
    citations = parsed["citations"]

    # Deterministic safety / interaction agent over the whole transcript.
    # Safety gates must scan patient answers, never a generated summary which
    # could misattribute a historical record symptom to this presentation.
    detected_issues = safety.screen(patient_context, transcript_text)

    # Same self-critique safeguards as the free-text path: ground citations
    # against what was retrieved, then run the escalate-only verifier so the
    # handoff inherits the agent's one-directional safety guarantee.
    retrieved_sources = [g["source"] for g in guidelines]
    verified = reasoning.verify(
        provider,
        level=triage_level,
        summary=hpi,
        citations=reasoning.ground_citations(citations, retrieved_sources),
        patient_context=patient_context,
        guidelines=guidelines,
        message=transcript_text,
        interview_transcript=qa_transcript,
        retrieved_sources=retrieved_sources,
    ) if provider is not None else {"level": triage_level, "summary": hpi, "citations": citations, "verifier_note": ""}
    triage_level = verified["level"]
    hpi = verified["summary"]
    citations = verified["citations"]

    # Fold in the safety floor, one-directionally.
    safety_level = safety.safety_floor(detected_issues)
    if safety_level:
        raised = reasoning._higher(triage_level, safety_level)
        if raised != triage_level:
            codes = ", ".join(i["code"] for i in detected_issues)
            hpi = f"{hpi} (Safety agent raised to {raised}: {codes}.)".strip()
            triage_level = raised

    # Keep the patient's next step aligned with every deterministic escalation.
    if triage_level == "ed":
        parsed["recommended_actions"] = ["Seek emergency care now; immediate clinician review required."]
    elif triage_level == "urgent-care":
        parsed["recommended_actions"] = ["Arrange urgent in-person clinical assessment today."]

    # Preserve the deterministic emergency floor on the interview entry point.
    hard_flags = _detect_red_flags(transcript_text)
    if hard_flags:
        triage_level = reasoning._higher(triage_level, 'ed')
        parsed['red_flags'] = list(dict.fromkeys((parsed.get('red_flags') or []) + hard_flags))
    trace = _build_trace(
        detected_issues=detected_issues, tool_trace=[], red_flagged=bool(hard_flags)
    )
    handoff = {
        "hpi": hpi,
        "recommended_actions": parsed["recommended_actions"],
        "red_flags": parsed["red_flags"],
        "citations": citations,
        "detected_issues": detected_issues,
        "trace": trace,
        "verifier_note": verified.get("verifier_note", ""),
        "qr_id": questionnaire_response_id,
    }
    fhir = _persist_fhir(
        patient_id,
        triage_level,
        chief_complaint,
        qr_id=questionnaire_response_id,
        qa_transcript=qa_transcript,
        handoff=handoff,
        detected_issues=detected_issues,
    )

    return {
        "triage_level": triage_level,
        "chief_complaint": chief_complaint,
        "hpi": handoff["hpi"],
        "red_flags": handoff["red_flags"],
        "recommended_actions": handoff["recommended_actions"],
        "citations": handoff["citations"],
        "detected_issues": detected_issues,
        "questionnaire_response_id": questionnaire_response_id,
        "encounter_id": fhir["encounter_id"],
        "service_request_id": fhir["service_request_id"],
        "observation_ids": fhir["observation_ids"],
        "detected_issue_ids": fhir["detected_issue_ids"],
    }
