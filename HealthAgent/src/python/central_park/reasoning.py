"""Interview citation grounding and escalate-only assessment review."""

from __future__ import annotations

import json
import logging
import pathlib

from central_park.llm import LLMProvider
from central_park.errors import ModelOutputError, ModelServiceError
from central_park.telemetry import timed, model_stage

_log = logging.getLogger("central_park.reasoning")

_PROMPTS = pathlib.Path(__file__).parent / "prompts"
_VERIFY_PROMPT = (_PROMPTS / "verify.txt").read_text(encoding="utf-8")

# Triage levels in ascending acuity. The verifier and the red-flag gate may only
# move *up* this ladder, never down.
_LEVELS = ("self-care", "see-gp", "urgent-care", "ed")


def _rank(level: str) -> int:
    try:
        return _LEVELS.index(level)
    except ValueError:
        return _LEVELS.index("see-gp")


def _higher(a: str, b: str) -> str:
    """Return whichever of the two levels is the more acute."""
    return a if _rank(a) >= _rank(b) else b


@timed('assessment.review.parse')
def _loads(raw: str) -> dict:
    """Tolerant JSON parse: strips ```json fences and shrugs off junk."""
    try:
        return json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
    except json.JSONDecodeError:
        return {}


@timed('assessment.citation_grounding')
def ground_citations(citations: list[dict], retrieved_sources: list[str]) -> list[dict]:
    """Drop citations whose source was never actually retrieved.

    Pure and deterministic: a model that invents a guideline title cannot smuggle
    it into the clinician handoff.
    """
    allowed = set(retrieved_sources)
    return [c for c in citations if c.get("source") in allowed]


@timed('assessment.review.operation')
def verify(
    provider: LLMProvider,
    *,
    level: str,
    summary: str,
    citations: list[dict],
    patient_context: dict,
    guidelines: list[dict],
    message: str,
    retrieved_sources: list[str],
    interview_transcript: list[dict] | None = None,
) -> dict:
    """Self-critique the reasoner's answer.

    Two safeguards, both one-directional:
      1. Citations are grounded against retrieved sources (deterministic).
      2. An LLM critic may escalate the level if the evidence warrants it, and
         may never downgrade. Provider or contract failures surface explicitly.
    """
    grounded = ground_citations(citations, retrieved_sources)

    payload = json.dumps(
        {
            "proposed": {"level": level, "summary": summary, "citations": grounded},
            "patient_context": patient_context,
            "guidelines": guidelines,
            "message": message,
            **({"interview_transcript": interview_transcript} if interview_transcript is not None else {}),
        },
        ensure_ascii=False,
    )
    try:
        with model_stage('assessment.review', input_chars=len(payload)):
            raw = provider.complete(system=_VERIFY_PROMPT, messages=[{"role": "user", "content": payload}])
        parsed = _loads(raw)
    except Exception as exc:
        _log.warning("verify: critic call failed (%s)", exc)
        raise ModelServiceError("Assessment reviewer is unavailable") from exc

    if not isinstance(parsed, dict):
        raise ModelOutputError("Assessment reviewer output must be a JSON object")
    verdict = parsed.get("verdict")
    if verdict not in ("confirm", "escalate"):
        raise ModelOutputError("Assessment reviewer returned an invalid verdict")
    if verdict == "escalate" and parsed.get("level") not in _LEVELS:
        raise ModelOutputError("Assessment reviewer returned an invalid triage level")
    if not isinstance(parsed.get("note", ""), str):
        raise ModelOutputError("Assessment reviewer returned an invalid note")
    note = (parsed.get("note") or "").strip()

    if verdict == "escalate":
        proposed = parsed.get("level", level)
        final_level = _higher(level, proposed)  # escalate-only guarantee
        if final_level != level:
            suffix = f" (Verifier escalated from {level}: {note})" if note else ""
            return {
                "level": final_level,
                "summary": (summary + suffix).strip(),
                "citations": grounded,
                "verifier_note": note,
            }

    return {"level": level, "summary": summary, "citations": grounded, "verifier_note": note}
