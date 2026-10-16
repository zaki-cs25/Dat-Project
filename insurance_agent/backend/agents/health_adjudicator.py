"""
Health Insurance Claims Adjudicator Agent (Indian Context).

Reads any number of PDF documents (policy certificate, discharge summary,
hospital bill, claim form, lab reports, pharmacy bills, etc.), identifies
each from its content, cross-references facts, and returns a verdict:
  APPROVE | REJECT | PARTIAL | ESCALATE
with detailed reasoning.

Supports both the original API (for the web UI) and the benchmark-compliant
API (for the claims adjudication benchmark).
"""

import json as _json

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field
from typing import List, Optional

from backend.router import get_llm_langchain

# ---------------------------------------------------------------------------
# Output schema — original (for the web UI)
# ---------------------------------------------------------------------------

class DocumentSummary(BaseModel):
    filename: str = Field(description="Original filename of the document")
    identified_type: str = Field(
        description="What this document is, identified from its content."
    )
    key_facts: str = Field(
        description="1-3 line summary of the most important facts from this document"
    )


class AdjudicationResult(BaseModel):
    verdict: str = Field(description="One of: APPROVE, REJECT, PARTIAL, ESCALATE")
    reasoning: str = Field(
        description="Detailed reasoning explaining the verdict."
    )
    document_summary: List[DocumentSummary] = Field(
        description="Summary of each document, identified by content, not filename"
    )
    extracted_details: dict = Field(
        description="Key extracted fields."
    )


# ---------------------------------------------------------------------------
# Output schema — benchmark compliant
# ---------------------------------------------------------------------------

class BenchmarkAdjudicationResult(BaseModel):
    verdict: str = Field(description="One of: APPROVE, PARTIAL, REJECT, ESCALATE")
    payable: int = Field(description="Whole number of rupees payable. Zero for REJECT or ESCALATE.")
    clauses: List[str] = Field(
        description="Clause identifiers from the benchmark clause list."
    )
    explanation: str = Field(
        description="Two or three sentences a claimant could understand, citing the clauses."
    )


# ---------------------------------------------------------------------------
# System prompt — original (for the web UI)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an expert Health Insurance Claims Adjudicator AI operating in the Indian \
insurance context (IRDAI-regulated).

You will receive multiple documents. The filenames are NOT reliable indicators \
of document type -- identify each document from its CONTENT.

## STEP 1 — IDENTIFY EACH DOCUMENT
For every document, determine what it is (policy certificate, discharge summary, \
hospital bill, claim form, pharmacy receipt, lab report, etc.)

## STEP 2 — EXTRACT KEY FACTS
Extract: insured name, policy number, sum insured, room rent limit, co-pay, \
waiting periods, patient name, admission/discharge dates, diagnosis (ICD-10), \
procedures, room rent/day, total bill amount, etc.

## STEP 3 — CROSS-REFERENCE AND EVALUATE
Check coverage, room rent limits, co-pay, sum insured, consistency of dates \
and procedures between documents, and red flags.

## STEP 4 — RETURN VERDICT
Choose exactly ONE of: APPROVE, REJECT, PARTIAL, ESCALATE.

## IMPORTANT
- Always cite specific facts from the documents.
- Reference exact amounts, dates, and ICD-10 codes.
- If documents are missing, note that and consider ESCALATE.
"""


# ---------------------------------------------------------------------------
# System prompt — benchmark (AGENT_BRIEF.md + reference prompt baked in)
# ---------------------------------------------------------------------------

BENCHMARK_SYSTEM_PROMPT = """\
You are a claims adjudicator at an Indian health insurer. You settle one claim at \
a time, from the documents on file.

Work from the documents. Every policy in this queue is different, so read the \
wording and the certificate for the case in front of you and take the numbers \
from there. Nothing you remember about another policy applies here.

The brief that follows sets out the conventions your decision is judged against: \
what each verdict means, when to escalate, the order deductions apply in, how to \
round, and which clause identifiers to cite. Follow it exactly.

---

# Task brief

You are settling health insurance claims for an Indian insurer.

## 1. What you are given

| Document | Who wrote it | What it gives you |
|---|---|---|
| Policy wording | the insurer | what the policy covers, what it does not, and on what conditions |
| Certificate of insurance | the insurer | this policy's sum insured, period, members, and the limits that apply to it |
| Claim form | the claimant | the claimant's own account of the admission and what is claimed |
| Discharge summary | the hospital | the clinical record: dates, diagnosis, procedure, treating doctor |
| Hospital bill | the hospital | the charges, itemised |

A case may be missing one of the claimant's documents. The insurer's \
certificate and wording are always present.

## 2. The four verdicts

| Verdict | When |
|---|---|
| `APPROVE` | Something is paid, and the only things that reduced it were items the policy never pays for as separate charges, a deductible, or a co-payment. |
| `PARTIAL` | Something is paid, and a limit or an exclusion cut part of the claim. |
| `REJECT` | Nothing is paid: a condition of cover was not met, or nothing survived the deductions. |
| `ESCALATE` | You cannot decide, because a document is missing or two documents contradict each other, and the gap could change the outcome. |

## 3. When to escalate

- **A required document is missing.** If the discharge summary is missing, escalate. \
If the bill or the claim form is missing, escalate — unless the claim already fails \
a condition of cover on the documents you do have, in which case decide it.
- **Two documents disagree.** If dates differ between claim form and hospital docs, \
work the claim both ways. If verdict/amount differ, escalate. If the amount claimed \
differs from the bill total, escalate — unless the claim already fails a condition \
of cover.

Check whether the claim fails a condition of cover **before** you consider \
escalating. A claim that plainly fails one is `REJECT`, not `ESCALATE`.

## 4. Working out the amount

Start from the bill. Apply what the policy says in this order:

1. Drop expenses dated outside the pre/post hospitalisation window.
2. Remove bill lines the policy does not pay for (non-payable items, exclusions).
3. If room rate exceeds the limit, apply proportionate deduction.
4. The same for ICU, against its own limit.
5. Cap at disease/procedure sub-limits.
6. Cap at system-of-medicine limits (AYUSH).
7. Subtract the deductible.
8. Subtract the co-payment.
9. Cap at the sum insured + cumulative bonus.

**Rounding:** Round each step's deduction to nearest rupee (halves up). \
Do not round the running total. Every amount is a whole number of rupees. \
A rejected or escalated claim pays nothing — report `0`.

## 5. Which clauses to cite

Cite the clauses that explain your outcome. Use only these identifiers:

**Hospitalisation**
| Clause | What it is |
|---|---|
| `2.1_min_hospitalisation` | Minimum duration |
| `2.2_day_care` | Day-care treatment |

**Limits**
| Clause | What it is |
|---|---|
| `3.1_room_rent_limit` | Room rent limit and proportionate deduction |
| `3.2_icu_limit` | ICU charges limit |
| `3.3_disease_sublimit` | Disease/procedure sub-limit |
| `3.4_ayush` | AYUSH treatment |
| `3.5_pre_hospitalisation` | Pre-hospitalisation expenses |
| `3.6_post_hospitalisation` | Post-hospitalisation expenses |

**Waiting periods and exclusions**
| Clause | What it is |
|---|---|
| `4.1_ped_waiting` | Pre-existing disease waiting period |
| `4.2_specific_disease_waiting` | Specified disease/procedure waiting period |
| `4.2_accident_exception` | Accident exception to specified disease wait |
| `4.3_initial_waiting` | Initial waiting period |
| `4.3_accident_exception` | Accident exception to initial waiting period |
| `4.8_cosmetic_surgery` | Cosmetic/plastic surgery |
| `4.14_dietary_supplements` | Dietary supplements |
| `4.15_refractive_error` | Refractive error |
| `4.17_sterility_infertility` | Sterility and infertility |
| `4.18_maternity` | Maternity |

**What the policyholder bears**
| Clause | What it is |
|---|---|
| `5.1_deductible` | Deductible |
| `5.2_copay` | Co-payment |
| `5.3_sum_insured` | Sum insured and cumulative bonus |

**Policy & claim papers**
| Clause | What it is |
|---|---|
| `6.1_policy_period` | Policy period |
| `7.1_missing_documents` | Required claim documents |
| `7.2_document_mismatch` | Consistency of claim documents |
| `A1_non_payable_items` | List of non-payable items |

If you reject, cite **every** condition the claim failed. If you escalate, cite \
only escalation clauses. Otherwise cite every step that reduced the amount and \
every exception you relied on.

## 6. What to return

One JSON object with: `verdict`, `payable` (whole number), `clauses` (list), \
`explanation` (2-3 sentences a claimant could understand).
"""


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict:
    """Extract a JSON object from LLM output, stripping markdown, whitespace, etc."""
    text = text.strip()
    # Try direct parse first
    try:
        return _json.loads(text)
    except _json.JSONDecodeError:
        pass
    # Try extracting from ```json ... ``` blocks
    import re
    m = re.search(r'```(?:json)?\s*\n?([\s\S]*?)```', text)
    if m:
        try:
            return _json.loads(m.group(1))
        except _json.JSONDecodeError:
            pass
    # Try finding the first { and last }
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        try:
            return _json.loads(text[start:end+1])
        except _json.JSONDecodeError:
            pass
    raise _json.JSONDecodeError("Could not extract JSON from LLM output", text, 0)


def _get_format_instructions(model_cls):
    """Get JSON schema as a string for a Pydantic model."""
    schema = model_cls.model_json_schema()
    return _json.dumps(schema, indent=2)


# Build prompts with SystemMessage (no template parsing for system text,
# so JSON schema braces are NOT treated as LangChain variables)

_FMT_ADJ = _get_format_instructions(AdjudicationResult)
_FMT_BM = _get_format_instructions(BenchmarkAdjudicationResult)

ADJUDICATION_PROMPT = ChatPromptTemplate(
    messages=[
        SystemMessage(content=SYSTEM_PROMPT + "\n\nReturn ONLY valid JSON matching this schema:\n" + _FMT_ADJ),
        MessagesPlaceholder("documents_text"),
    ]
)

BENCHMARK_ADJUDICATION_PROMPT = ChatPromptTemplate(
    messages=[
        SystemMessage(content=BENCHMARK_SYSTEM_PROMPT + "\n\nReturn ONLY valid JSON matching this schema:\n" + _FMT_BM),
        MessagesPlaceholder("documents_text"),
    ]
)


# ---------------------------------------------------------------------------
# Public API — original (web UI)
# ---------------------------------------------------------------------------

async def adjudicate_claim(documents_text: str) -> dict:
    """
    Adjudicates a health insurance claim given the combined text of all
    uploaded documents. Returns verdict, reasoning, document_summary,
    and extracted_details.
    """
    llm = get_llm_langchain(temperature=0)
    chain = ADJUDICATION_PROMPT | llm | StrOutputParser()

    try:
        raw = await chain.ainvoke({
            "documents_text": [HumanMessage(content="Adjudicate the following documents:\n\n" + documents_text)]
        })
        return _extract_json(raw)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Adjudication error: {e}")
        return {
            "verdict": "ESCALATE",
            "reasoning": f"System error during automated adjudication: {e}. "
                         f"Manual review required.",
            "document_summary": [],
            "extracted_details": {},
        }


# ---------------------------------------------------------------------------
# Public API — benchmark compliant
# ---------------------------------------------------------------------------

async def adjudicate_benchmark(documents_text: str) -> dict:
    """
    Benchmark-compliant adjudication. Uses the AGENT_BRIEF.md conventions.
    Returns verdict, payable, clauses, explanation.
    """
    llm = get_llm_langchain(temperature=0)
    chain = BENCHMARK_ADJUDICATION_PROMPT | llm | StrOutputParser()

    try:
        raw = await chain.ainvoke({
            "documents_text": [HumanMessage(content="Adjudicate the following documents:\n\n" + documents_text)]
        })
        return _extract_json(raw)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Benchmark adjudication error: {e}")
        return {
            "verdict": None,
            "payable": 0,
            "clauses": [],
            "explanation": f"System error during automated adjudication: {e}",
        }
