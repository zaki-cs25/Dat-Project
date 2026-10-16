"""Adaptive intake interview.

The v1 intake was a fixed six-question form. This module makes it agentic: after
the patient states their complaint, the model chooses the *next* question to ask
from what it has already heard plus the patient's FHIR risk factors, and stops
once it has enough to triage confidently.

The contract is one question at a time:

    next_question(patient_id, answers) -> {"done": bool, "question": {...} | None}

The frontend renders `question` (text / scale / choices), collects the answer,
appends it to `answers`, and calls again until `done`. A hard cap bounds the
interview so it always terminates. Provider failures and malformed model
outputs are explicit errors so the client can retry without marking the
interview complete.

Two link ids are reserved so the downstream FHIR Observation coding keeps
working (tools/fhir.py): `severity` (a 1-10 scale) and `associated-symptoms`
(the SNOMED-mapped checklist). The model is told to reuse them when it asks
those canonical questions; everything else gets a free-form link id.
"""

from __future__ import annotations

import json
import logging
import pathlib

from central_park.llm import get_provider
from central_park.errors import ModelOutputError, ModelServiceError
from central_park.tools import get_patient_context, search_guidelines
from central_park.telemetry import timed, model_stage

_log = logging.getLogger("central_park.interview")

_PROMPT = (pathlib.Path(__file__).parent / "prompts" / "next_question.txt").read_text(encoding="utf-8")

# The interview always terminates: at most this many questions including the
# fixed opening complaint the client asks before the first /next call.
MAX_QUESTIONS = 7
# Don't stop before we have at least the complaint plus a couple of follow-ups.
MIN_QUESTIONS = 3

_VALID_KINDS = {"text", "scale", "choices"}


@timed('interview.parse')
def _loads(raw: str) -> dict:
    try:
        parsed = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
    except json.JSONDecodeError as exc:
        raise ModelOutputError("Interview model returned malformed JSON") from exc
    if not isinstance(parsed, dict):
        raise ModelOutputError("Interview model output must be a JSON object")
    return parsed


@timed('interview.validation')
def _normalize_question(q: dict, asked_link_ids: set[str]) -> dict | None:
    """Validate and coerce a model-proposed question into the UI contract.

    Returns None if the question is malformed or duplicates one already asked;
    the caller turns that into an explicit model-output error.
    """
    if not isinstance(q, dict):
        return None
    kind = q.get("kind")
    link_id = q.get("link_id", "")
    prompt = q.get("prompt", "")
    if not isinstance(link_id, str) or not isinstance(prompt, str):
        return None
    link_id, prompt = link_id.strip(), prompt.strip()
    if not isinstance(kind, str) or kind not in _VALID_KINDS or not link_id or not prompt or link_id in asked_link_ids:
        return None

    def optional_text(key: str, default: str = "") -> str | None:
        value = q.get(key, default)
        return value.strip() if isinstance(value, str) else None

    short = optional_text("short", prompt)
    help_text = optional_text("help")
    if short is None or help_text is None:
        return None

    out: dict = {
        "link_id": link_id,
        "kind": kind,
        "short": (short or prompt)[:40],
        "prompt": prompt,
        "help": help_text or None,
    }
    if kind == "text":
        placeholder = optional_text("placeholder")
        if placeholder is None:
            return None
        out["placeholder"] = placeholder or None
    elif kind == "scale":
        minimum, maximum = q.get("min", 1), q.get("max", 10)
        min_label = optional_text("min_label", "Barely noticeable")
        max_label = optional_text("max_label", "Worst imaginable")
        if (type(minimum) is not int or type(maximum) is not int or
                minimum < 1 or maximum > 10 or minimum >= maximum or
                min_label is None or max_label is None):
            return None
        out["min"], out["max"] = minimum, maximum
        out["min_label"], out["max_label"] = min_label, max_label
    elif kind == "choices":
        none_option = optional_text("none_option", "None of these")
        raw_options = q.get("options", [])
        if not none_option or not isinstance(raw_options, list) or not all(isinstance(o, str) for o in raw_options):
            return None
        # The UI appends none_option itself, so drop any echo of it from the
        # model's options (case-insensitive) and de-duplicate, otherwise the
        # patient sees two "None of these" rows.
        options: list[str] = []
        for o in raw_options:
            label = o.strip()
            if not label or label.casefold() == none_option.casefold():
                continue
            if any(label.casefold() == seen.casefold() for seen in options):
                continue
            options.append(label)
        if not options:
            return None
        out["options"] = options
        out["none_option"] = none_option
    return out


@timed('interview.next')
def next_question(patient_id: str, answers: list[dict], language: str = "English") -> dict:
    """Decide the next intake question, or that the interview is complete.

    `answers` is the list of {link_id, question, answer} gathered so far (the
    client sends the fixed opening complaint as the first entry). `language` is
    the patient's chosen language; question prompts and helper text are written
    in it (link ids and the option keywords stay canonical for FHIR coding).
    Returns {"done": True, "question": None} or {"done": False, "question": {...}}.
    """
    asked = {a.get("link_id", "") for a in answers}

    # Hard stop once the budget is spent.
    if len(answers) >= MAX_QUESTIONS:
        return {"done": True, "question": None, "stop_reason": "max_questions"}

    patient_context = get_patient_context(patient_id)
    # Seed retrieval from the complaint + earliest answers so the model sees the
    # guidelines relevant to what the patient has said so far.
    query = " ".join(a.get("answer", "") for a in answers[:3] if a.get("answer"))
    guidelines = search_guidelines(query, k=5) if query else []

    payload = json.dumps(
        {
            "patient_context": patient_context,
            "guidelines": guidelines,
            "answers_so_far": answers,
            "asked_link_ids": sorted(asked),
            "questions_asked": len(answers),
            "min_questions": MIN_QUESTIONS,
            "max_questions": MAX_QUESTIONS,
            "language": language or "English",
        },
        ensure_ascii=False,
    )
    try:
        with model_stage('interview.question', input_chars=len(payload)):
            raw = get_provider().complete(system=_PROMPT, messages=[{"role": "user", "content": payload}])
    except Exception as exc:
        _log.warning("next_question: provider call failed (%s)", exc)
        raise ModelServiceError("Interview question service is unavailable") from exc
    parsed = _loads(raw)
    if type(parsed.get("done")) is not bool:
        raise ModelOutputError("Interview model must return a boolean done field")

    # The model may only declare itself done once the minimum is met; before that
    # we keep its proposed question even if it tried to stop early.
    wants_done = bool(parsed.get("done")) and len(answers) >= MIN_QUESTIONS
    if wants_done:
        return {"done": True, "question": None, "stop_reason": "model_complete"}

    try:
        question = _normalize_question(parsed.get("question") or {}, asked)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ModelOutputError("Interview model returned an invalid question") from exc
    if question is None:
        raise ModelOutputError("Interview model did not provide a valid, new question")
    return {"done": False, "question": question, "stop_reason": None}
