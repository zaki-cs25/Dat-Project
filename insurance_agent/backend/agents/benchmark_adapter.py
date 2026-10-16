"""
Benchmark Adapter — wraps the health adjudicator agent to conform to the
claims adjudication benchmark tool interface (list_documents, read_document,
submit) as defined in dataset/public/reference_prompt.md.

Usage:
    from backend.agents.benchmark_adapter import run_case
    result = await run_case(case_id, case_info, wording_path, documents_dir,
                            agent_brief_text, case_dir)
"""

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from backend.router import get_llm

# ---------------------------------------------------------------------------
# System prompt assembly (reference_prompt.md + AGENT_BRIEF.md)
# ---------------------------------------------------------------------------

SYSTEM_PREFIX = """\
You are a claims adjudicator at an Indian health insurer. You settle one claim at
a time, from the documents on file.

Work from the documents. Every policy in this queue is different, so read the
wording and the certificate for the case in front of you and take the numbers
from there. Nothing you remember about another policy applies here.

You have tools to list and read the documents. Read what you need before you
decide; a document you have not read cannot support your decision. When you have
the facts, call submit exactly once.

The brief that follows sets out the conventions your decision is judged against:
what each verdict means, when to escalate, the order deductions apply in, how to
round, and which clause identifiers to cite. Follow it exactly.
"""


def _build_system_prompt(agent_brief_text: str) -> str:
    """Combine reference prompt prefix + AGENT_BRIEF.md."""
    return SYSTEM_PREFIX + "\n\n---\n\n" + agent_brief_text


# ---------------------------------------------------------------------------
# PDF text cache (same extraction for all k runs of a case)
# ---------------------------------------------------------------------------

_pdf_cache: dict[str, list[str]] = {}


def _extract_pdf_text(pdf_path: str) -> list[str]:
    """Extract text from a PDF, one string per page. Cached by path."""
    if pdf_path in _pdf_cache:
        return _pdf_cache[pdf_path]
    try:
        reader = PdfReader(pdf_path)
        pages = []
        for page in reader.pages:
            text = page.extract_text() or ""
            pages.append(text.strip())
        _pdf_cache[pdf_path] = pages
        return pages
    except Exception as e:
        _pdf_cache[pdf_path] = [f"(Error reading PDF: {e})"]
        return _pdf_cache[pdf_path]


# ---------------------------------------------------------------------------
# Tool implementations (from reference_prompt.md)
# ---------------------------------------------------------------------------

_DOC_NAME_MAP = {
    "policy_certificate.pdf": "policy_certificate",
    "claim_form.pdf": "claim_form",
    "discharge_summary.pdf": "discharge_summary",
    "hospital_bill.pdf": "hospital_bill",
}

_WORDING_DOC_NAME = "policy_wording"


class _CaseContext:
    """Holds extracted texts for one case."""

    def __init__(self, case_dir: str, documents: list[str], wording_path: str,
                 base_dir: str):
        self.docs: dict[str, list[str]] = {}

        for doc_path_rel in documents:
            pdf_path = os.path.join(base_dir, doc_path_rel)
            basename = os.path.basename(pdf_path)
            doc_name = _DOC_NAME_MAP.get(basename)
            if doc_name:
                self.docs[doc_name] = _extract_pdf_text(pdf_path)

        abs_wording = os.path.join(base_dir, wording_path)
        self.docs[_WORDING_DOC_NAME] = _extract_pdf_text(abs_wording)

    def list_documents(self) -> list[dict]:
        result = []
        if _WORDING_DOC_NAME in self.docs:
            result.append({
                "name": _WORDING_DOC_NAME,
                "pages": len(self.docs[_WORDING_DOC_NAME])
            })
        for name in ["policy_certificate", "claim_form", "discharge_summary",
                      "hospital_bill"]:
            if name in self.docs:
                result.append({
                    "name": name,
                    "pages": len(self.docs[name])
                })
        return result

    def read_document(self, name: str, page: int | None = None) -> str:
        if name not in self.docs:
            raise ValueError(
                f"Document '{name}' not found. "
                f"Available: {', '.join(self.list_documents())}"
            )
        pages = self.docs[name]
        if page is not None:
            if page < 1 or page > len(pages):
                raise ValueError(
                    f"Page {page} out of range for '{name}' "
                    f"(has {len(pages)} pages)"
                )
            return pages[page - 1]
        return "\n\n".join(pages)


# ---------------------------------------------------------------------------
# OpenAI function-calling tools definition
# ---------------------------------------------------------------------------

FUNCTIONS = [
    {
        "type": "function",
        "function": {
            "name": "list_documents",
            "description": "List all documents available for this case",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_document",
            "description": "Read a document by name, optionally a specific 1-based page number",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Document name: policy_wording, policy_certificate, claim_form, discharge_summary, hospital_bill"
                    },
                    "page": {
                        "type": "integer",
                        "description": "Specific 1-based page number to read (omit to read all pages)"
                    }
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "submit",
            "description": "Submit your final claim decision",
            "parameters": {
                "type": "object",
                "properties": {
                    "verdict": {
                        "type": "string",
                        "enum": ["APPROVE", "PARTIAL", "REJECT", "ESCALATE"],
                        "description": "Your verdict"
                    },
                    "payable": {
                        "type": "integer",
                        "description": "Amount payable in Indian Rupees"
                    },
                    "clauses": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of clause identifiers that apply"
                    },
                    "explanation": {
                        "type": "string",
                        "description": "Brief explanation of your decision"
                    }
                },
                "required": ["verdict", "payable", "clauses", "explanation"]
            }
        }
    }
]


# ---------------------------------------------------------------------------
# Fallback: parse tool calls from free-text (for models without native tool support)
# ---------------------------------------------------------------------------

def _parse_tool_call_from_text(text: str) -> tuple[str, dict] | None:
    """
    Try to parse a tool call from free-text response.
    Returns (tool_name, arguments_dict) or None.
    """
    if not text:
        return None

    # Try JSON blocks
    json_text = text
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        json_text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + 3
        end = text.rindex("```")
        json_text = text[start:end].strip()

    try:
        obj = json.loads(json_text)
        if isinstance(obj, dict):
            if "tool" in obj and "arguments" in obj:
                return obj["tool"], obj["arguments"]
            if "name" in obj and "arguments" in obj:
                return obj["name"], obj["arguments"]
            if "verdict" in obj and "payable" in obj:
                return "submit", obj
            if "name" in obj and "page" in obj:
                return "read_document", obj
            if "name" in obj:
                return "read_document", {"name": obj["name"]}
    except (json.JSONDecodeError, ValueError):
        pass

    # Try function call patterns: tool_name(...)
    import re
    m = re.search(r'(submit|read_document|list_documents)\s*\(([\s\S]*)\)', text)
    if m:
        tool_name = m.group(1)
        args_str = m.group(2).strip()
        args = {}
        try:
            for part in args_str.split(","):
                part = part.strip()
                if "=" in part:
                    k, v = part.split("=", 1)
                    k = k.strip().strip("'\"")
                    v = v.strip().strip("'\"")
                    try:
                        v = json.loads(v)
                    except json.JSONDecodeError:
                        pass
                    args[k] = v
        except Exception:
            pass
        return tool_name, args

    return None


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------

async def run_case(
    case_id: str,
    case_info: dict,
    wording_path: str,
    documents: list[str],
    agent_brief_text: str,
    case_dir: str,
    base_dir: str,
    max_turns: int = 30,
    temperature: float = 0,
) -> dict:
    """
    Run the agent on one case through the tool-calling loop.

    Returns a result dict conforming to METRICS.md submission format.
    """
    start_time = time.time()
    ctx = _CaseContext(case_dir, documents, wording_path, base_dir)
    system_prompt = _build_system_prompt(agent_brief_text)

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Settle claim {case_id} (product: {case_info.get('product_id', 'unknown')}).\n"
                "Use the tools to list and read documents, then submit your decision."
            )
        }
    ]

    llm = get_llm(temperature=temperature)
    trace: list[dict] = []
    total_input_tokens = 0
    total_output_tokens = 0
    completed = False
    verdict = None
    payable = None
    clauses = None
    explanation = None
    round_trips = 0

    for turn in range(max_turns):
        try:
            response = await llm.chat(messages, tools=FUNCTIONS)
            round_trips += 1

            # Track tokens
            total_input_tokens += response.get("input_tokens", 0)
            total_output_tokens += response.get("output_tokens", 0)

            # Prefer native tool_calls from the LLM
            tool_calls = response.get("tool_calls", [])
            content = response.get("content")

            if tool_calls:
                # Handle each tool call
                handled = False
                for tc in tool_calls:
                    tool_name = tc["name"]
                    args = tc["arguments"]
                    tc_id = tc.get("id", "")

                    if tool_name == "list_documents":
                        result = ctx.list_documents()
                        trace.append({
                            "step": turn,
                            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "tool": "list_documents",
                            "arguments": {},
                            "outcome": "ok",
                            "error": None,
                        })
                        messages.append({
                            "role": "assistant",
                            "tool_calls": [{"id": tc_id, "type": "function",
                                           "function": {"name": tool_name, "arguments": "{}"}}]
                        })
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": json.dumps(result, indent=2)
                        })
                        handled = True

                    elif tool_name == "read_document":
                        doc_name = args.get("name", "")
                        page = args.get("page", None)
                        try:
                            if isinstance(page, str):
                                page = int(page) if page else None
                            text = ctx.read_document(doc_name, page)
                            trace.append({
                                "step": turn,
                                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "tool": "read_document",
                                "arguments": {"name": doc_name, "page": page},
                                "outcome": "ok",
                                "error": None,
                            })
                            assistant_msg = {
                                "role": "assistant",
                                "tool_calls": [{"id": tc_id, "type": "function",
                                               "function": {"name": tool_name, "arguments": json.dumps(args)}}]
                            }
                            if content:
                                assistant_msg["content"] = content
                            messages.append(assistant_msg)
                            # Truncate if too long
                            if len(text) > 8000:
                                text = text[:8000] + "\n...(truncated)"
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "content": f"=== {doc_name}{' page ' + str(page) if page else ''} ===\n\n{text}"
                            })
                            handled = True
                        except ValueError as e:
                            trace.append({
                                "step": turn,
                                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "tool": "read_document",
                                "arguments": args,
                                "outcome": "tool_error",
                                "error": str(e),
                            })
                            messages.append({
                                "role": "assistant",
                                "tool_calls": [{"id": tc_id, "type": "function",
                                               "function": {"name": tool_name, "arguments": json.dumps(args)}}]
                            })
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "content": f"Error: {e}"
                            })
                            handled = True

                    elif tool_name == "submit":
                        verdict = args.get("verdict", verdict)
                        if "payable" in args:
                            try:
                                payable = int(args["payable"])
                            except (ValueError, TypeError):
                                payable = 0
                        clauses = args.get("clauses", [])
                        explanation = args.get("explanation", "")

                        if verdict not in ("APPROVE", "PARTIAL", "REJECT", "ESCALATE"):
                            verdict = None
                            trace.append({
                                "step": turn,
                                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "tool": "submit",
                                "arguments": args,
                                "outcome": "schema_error",
                                "error": f"Invalid verdict: {verdict}",
                            })
                            messages.append({
                                "role": "assistant",
                                "tool_calls": [{"id": tc_id, "type": "function",
                                               "function": {"name": tool_name, "arguments": json.dumps(args)}}]
                            })
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "content": f"Error: Invalid verdict. Must be one of: APPROVE, PARTIAL, REJECT, ESCALATE."
                            })
                            handled = True
                            continue

                        trace.append({
                            "step": turn,
                            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "tool": "submit",
                            "arguments": {"verdict": verdict, "payable": payable,
                                          "clauses": clauses, "explanation": explanation},
                            "outcome": "ok",
                            "error": None,
                        })
                        completed = True
                        handled = True
                        break  # exit the for tc loop

                if completed:
                    break
                if handled:
                    continue

            # Fallback: parse tool call from free-text content
            if content:
                parsed = _parse_tool_call_from_text(content)
                if parsed:
                    tool_name, args = parsed
                    # ... (reuse the tool-handling logic above)
                    if tool_name == "list_documents":
                        result = ctx.list_documents()
                        trace.append({
                            "step": turn,
                            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "tool": "list_documents",
                            "arguments": {},
                            "outcome": "ok",
                            "error": None,
                        })
                        messages.append({"role": "assistant", "content": content})
                        messages.append({
                            "role": "tool",
                            "content": json.dumps(result, indent=2)
                        })
                        continue

                    elif tool_name == "read_document":
                        doc_name = args.get("name", "")
                        page = args.get("page", None)
                        try:
                            if isinstance(page, str):
                                page = int(page) if page else None
                            text = ctx.read_document(doc_name, page)
                            trace.append({
                                "step": turn,
                                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "tool": "read_document",
                                "arguments": {"name": doc_name, "page": page},
                                "outcome": "ok",
                                "error": None,
                            })
                            messages.append({"role": "assistant", "content": content})
                            if len(text) > 8000:
                                text = text[:8000] + "\n...(truncated)"
                            messages.append({
                                "role": "tool",
                                "content": f"=== {doc_name}{' page ' + str(page) if page else ''} ===\n\n{text}"
                            })
                            continue
                        except ValueError as e:
                            trace.append({
                                "step": turn,
                                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "tool": "read_document",
                                "arguments": args,
                                "outcome": "tool_error",
                                "error": str(e),
                            })
                            messages.append({"role": "assistant", "content": content})
                            messages.append({
                                "role": "tool",
                                "content": f"Error: {e}"
                            })
                            continue

                    elif tool_name == "submit":
                        verdict = args.get("verdict", verdict)
                        if "payable" in args:
                            try:
                                payable = int(args["payable"])
                            except (ValueError, TypeError):
                                payable = 0
                        clauses = args.get("clauses", [])
                        explanation = args.get("explanation", "")

                        if verdict not in ("APPROVE", "PARTIAL", "REJECT", "ESCALATE"):
                            verdict = None
                            trace.append({
                                "step": turn,
                                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "tool": "submit",
                                "arguments": args,
                                "outcome": "schema_error",
                                "error": f"Invalid verdict: {verdict}",
                            })
                            messages.append({"role": "assistant", "content": content})
                            messages.append({
                                "role": "tool",
                                "content": f"Error: Invalid verdict. Must be one of: APPROVE, PARTIAL, REJECT, ESCALATE."
                            })
                            continue

                        trace.append({
                            "step": turn,
                            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "tool": "submit",
                            "arguments": {"verdict": verdict, "payable": payable,
                                          "clauses": clauses, "explanation": explanation},
                            "outcome": "ok",
                            "error": None,
                        })
                        completed = True
                        break

                # No tool call found — encourage the model
                messages.append({"role": "assistant", "content": content})
                messages.append({
                    "role": "user",
                    "content": (
                        "Please use one of the available tools: list_documents, read_document, or submit."
                    )
                })

        except Exception as e:
            trace.append({
                "step": turn,
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "tool": "_error",
                "arguments": {},
                "outcome": "tool_error",
                "error": str(e),
            })
            break

    wall_clock = time.time() - start_time

    return {
        "case_id": case_id,
        "run_index": 0,
        "product_id": case_info.get("product_id"),
        "agent_version": "benchmark-adapter-0.1.0",
        "model": "vllm/Qwen3.6-27B",
        "prompt_id": "claims-ref-1",
        "verdict": verdict,
        "payable": payable,
        "clauses": clauses if clauses else [],
        "explanation": explanation or "",
        "completed": completed,
        "trace": trace,
        "usage": {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "round_trips": round_trips,
        },
        "wall_clock_seconds": round(wall_clock, 2),
    }
