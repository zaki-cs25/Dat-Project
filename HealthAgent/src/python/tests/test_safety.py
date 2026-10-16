"""Unit tests for the deterministic safety / interaction agent (tools/safety.py)."""

from __future__ import annotations

from central_park.tools import safety


def _ctx(meds=None, allergies=None):
    return {"medications": [{"display": m} for m in (meds or [])],
            "allergies": [{"display": a} for a in (allergies or [])]}


def test_anticoagulant_bleeding_is_high():
    issues = safety.screen(_ctx(meds=["Warfarin 5mg"]), "I have some bleeding from my gums")
    assert len(issues) == 1
    assert issues[0]["code"] == "anticoagulant-bleeding"
    assert issues[0]["severity"] == "high"
    assert safety.safety_floor(issues) == "ed"


def test_no_issue_without_matching_symptom():
    issues = safety.screen(_ctx(meds=["Warfarin 5mg"]), "I have a mild sore throat")
    assert issues == []
    assert safety.safety_floor(issues) == ""


def test_no_issue_without_matching_drug():
    issues = safety.screen(_ctx(meds=["Paracetamol"]), "I noticed some bleeding")
    assert issues == []


def test_ace_inhibitor_angioedema():
    issues = safety.screen(_ctx(meds=["Lisinopril 10mg"]), "my lips and tongue are swelling")
    assert any(i["code"] == "ace-inhibitor-angioedema" for i in issues)
    assert safety.safety_floor(issues) == "ed"


def test_nsaid_gi_bleed_is_moderate_floor():
    issues = safety.screen(_ctx(meds=["Ibuprofen"]), "bad stomach pain and black stool")
    assert any(i["code"] == "nsaid-gi-bleed" for i in issues)
    assert safety.safety_floor(issues) == "urgent-care"


def test_allergy_exposure_flag():
    issues = safety.screen(_ctx(allergies=["Penicillin"]), "I took some penicillin yesterday")
    assert any(i["code"] == "allergy-exposure" for i in issues)
    assert safety.safety_floor(issues) == "ed"


def test_floor_takes_highest_severity():
    issues = [
        {"code": "a", "severity": "moderate", "detail": "", "medication": ""},
        {"code": "b", "severity": "high", "detail": "", "medication": ""},
    ]
    assert safety.safety_floor(issues) == "ed"


def test_denials_and_historical_symptoms_do_not_trigger_safety_floor():
    ctx = _ctx(meds=["Warfarin"], allergies=["Penicillin"])
    assert safety.screen(ctx, "No bleeding, but slurred speech") == []  # no neurologic drug rule
    assert safety.screen(ctx, "No bleeding; no penicillin exposure") == []
    assert safety.screen(ctx, "I had bleeding years ago; no current symptoms") == []


def test_positive_symptom_after_a_denial_is_retained():
    issues = safety.screen(_ctx(meds=["Warfarin"]), "No fever, but now there is bleeding")
    assert [i["code"] for i in issues] == ["anticoagulant-bleeding"]


def test_unrelated_drug_exposure_does_not_trigger_allergy_flag():
    issues = safety.screen(_ctx(allergies=["Penicillin"]), "I took aspirin; allergic to penicillin")
    assert issues == []


def test_negated_allergy_exposure_does_not_trigger_flag():
    assert safety.screen(_ctx(allergies=["Penicillin"]), "I did not take penicillin") == []
