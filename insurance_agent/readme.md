# Insurance Health Claims

An AI-powered system for the automated adjudication of health insurance claims, built for the **Indian insurance context** (IRDAI-regulated).

Upload any number of PDF documents — policy certificates, discharge summaries, hospital bills, claim forms, lab reports, pharmacy bills — and receive a structured verdict with reasoning in seconds.

---

## What This Project Does

### Health Claims Adjudication (Core)

The system acts as an AI claims adjudicator. A user drops any PDFs into the upload zone, and the AI:

1. **Identifies** each document from its content (filenames don't matter)
2. **Extracts** key facts: sum insured, room rent limits, co-pay, waiting periods, diagnosis, dates, bills
3. **Cross-references** facts across all documents against policy terms
4. **Returns** a verdict with detailed reasoning

```
Drop any PDFs (any count, any names)
        │
        ▼
  POST /adjudicate (multipart form)
        │
        ├── pypdf extracts text from each PDF
        ├── LLM identifies each document from its CONTENT
        ├── Cross-references: room rent vs policy limit, co-pay,
        │   sum insured, exclusions, waiting periods, consistency
        └── Returns verdict + reasoning
                │
                ▼
     APPROVE | REJECT | PARTIAL | ESCALATE
```

**Four verdicts:**

| Verdict | When |
|---|---|
| `APPROVE` | Everything covered, within limits, documents consistent |
| `REJECT` | Excluded treatment, within waiting period, policy expired, condition of cover not met |
| `PARTIAL` | Room rent over limit, co-pay applies, sub-limits cap the amount |
| `ESCALATE` | Missing documents, conflicting dates/amounts, needs human review |

### Benchmark Evaluation

A 1000-case benchmark dataset tests the adjudicator against gold truth across:

- **Verdict accuracy** — exact match on APPROVE / PARTIAL / REJECT / ESCALATE
- **Payable amount** — exact match and within ±1% tolerance
- **Clause citation** — precision, recall, and F1 against gold clause sets
- **Reliability** — pass@k scores across multiple independent runs
- **Agent behaviour** — completion rate, tool call patterns, error recovery

### Motor Claims Dashboard (Original)

The project originated as a motor/vehicle claims management system. The dashboard provides a claims inbox, detail pages with evidence graphs, analytics, and an AI chat assistant. Currently uses mock data.

---

## Architecture

```
Browser (Next.js :3000) → FastAPI Backend (:8000) → LLM Router → vLLM (Qwen3.6-27B :9000)
```

| Layer | Tech | Role |
|---|---|---|
| **Frontend** | Next.js 16 (App Router), Tailwind CSS | Dashboard UI, file upload, verdict display |
| **Backend** | FastAPI, Pydantic | REST API, PDF extraction, request routing |
| **Agents** | LangChain, LangGraph | Health adjudicator, claims analyzer, benchmark adapter |
| **LLM Router** | Custom YAML-driven router | Provider-agnostic, multi-backend, auto-failover |
| **LLM** | Qwen3.6-27B via vLLM | Core reasoning engine (swap via `router_config.yaml`) |
| **Database** | Supabase (PostgreSQL) / in-memory | Claims storage (optional); health adjudication is stateless |

### Agent Design

| Component | File | Role |
|---|---|---|
| **Health Adjudicator** | `backend/agents/health_adjudicator.py` | Reads documents, cross-references facts, returns verdict + reasoning. Two modes: web UI and benchmark. |
| **Benchmark Adapter** | `backend/agents/benchmark_adapter.py` | Wraps the adjudicator in a tool-calling loop (`list_documents`, `read_document`, `submit`) for the benchmark. |
| **Claims Analyzer** | `backend/agents/claims_agent.py` | Parses repair estimates into structured line items and risk factors (motor claims). |
| **Chat Agent** | `backend/agent.py` | LangGraph-based conversational agent for the claims assistant. |
| **LLM Router** | `backend/router.py` | Reads `router_config.yaml`, tries backends in order, falls back to `.env`. No code changes to swap providers. |

---

## Directory Structure

```
├── backend/
│   ├── main.py                  # FastAPI app (all API endpoints)
│   ├── router.py                # LLM router (multi-backend, failover)
│   ├── router_config.yaml       # Backend configuration (edit here to swap LLMs)
│   ├── agent.py                 # Chat agent (LangGraph)
│   ├── agents/
│   │   ├── health_adjudicator.py   # Health claims adjudicator
│   │   ├── benchmark_adapter.py    # Benchmark-compliant agent loop
│   │   └── claims_agent.py         # Motor claims document analyzer
│   ├── supabase_client.py       # Optional Supabase integration
│   ├── mock_data.py             # Mock claims data
│   ├── scripts/
│   │   ├── generate_samples.py  # Generate sample PDF documents
│   │   ├── generate_testcases.py
│   │   ├── benchmark_runner.py
│   │   └── benchmark_evaluator.py
│   └── requirements.txt
├── frontend/
│   └── src/                     # Next.js app (dashboard, upload, verdict UI)
├── dataset/
│   ├── public/                  # Benchmark dataset (1000 cases)
│   │   ├── cases/               # One folder per case with PDFs
│   │   ├── wordings/            # Policy wordings per product
│   │   ├── index.jsonl          # Case index (case_id, product, documents)
│   │   ├── AGENT_BRIEF.md       # Adjudication conventions
│   │   ├── reference_prompt.md  # Baseline system prompt
│   │   └── METRICS.md           # Scoring contract
│   └── gold.jsonl               # Ground truth answers
├── samples/                     # Sample PDF documents for testing
├── scripts/
│   ├── run_evaluation.py        # Run adjudicator on benchmark cases
│   ├── evaluate_single_case.py  # Evaluate one case
│   └── score_results.py         # Score results against gold truth
├── results/                     # Benchmark evaluation results
├── run.sh                       # tmux quick-start (backend + frontend)
└── readme.md
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- A running LLM server (vLLM with Qwen3.6-27B recommended, or any OpenAI-compatible endpoint)

### Option A: tmux Quick-Start

```bash
./run.sh
```

Launches a tmux session with two panes: backend (port 8000) and frontend (port 3000).

### Option B: Manual Start

**1. Configure the LLM backend**

Edit `backend/.env` or set environment variables:

```bash
LLM_BASE_URL=http://127.0.0.1:9000/v1
LLM_API_KEY=key
LLM_MODEL=Qwen3.6-27B
```

Or use `backend/router_config.yaml` for multi-backend configuration with failover.

**2. Backend**

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd ..
uvicorn backend.main:app --reload
```

**3. Frontend**

```bash
cd frontend
npm install
npm run dev
```

**4. (Optional) Generate sample PDFs**

```bash
python3 backend/scripts/generate_samples.py
```

### Open the App

- **Dashboard**: http://localhost:3000
- **Health Claims**: http://localhost:3000/health-claims

---

## API Reference

### Health Claims

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/adjudicate` | Upload PDFs, receive verdict + reasoning |

**`POST /adjudicate`** — multipart form with `files` field (one or more `.pdf` files):

```json
{
  "verdict": "PARTIAL",
  "reasoning": "Room rent of Rs. 5,500/day exceeds the policy limit...",
  "document_summary": [
    { "filename": "...", "identified_type": "...", "key_facts": "..." }
  ],
  "extracted_details": {
    "patient_name": "...",
    "total_claimed": 226490,
    "room_rent_per_day": 5500
  }
}
```

### Motor Claims

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/chat` | Chat with the claims assistant |
| `POST` | `/analyze` | Analyze a repair estimate document |
| `GET` | `/claims` | List all claims |
| `GET` | `/claims/{id}` | Get single claim |
| `POST` | `/claims` | Create new claim |
| `GET` | `/analytics` | Dashboard analytics |

---

## Running the Benchmark

```bash
# Quick sample run (60 cases, 1 run each)
python3 scripts/run_evaluation.py --sample 60 --runs 1

# Full run (all 1000 cases, 4 runs each)
python3 scripts/run_evaluation.py --runs 4

# Specific cases
python3 scripts/run_evaluation.py --case-ids case-000000 case-000010 --runs 1
```

Results are written to `results.jsonl` in METRICS.md-compliant format. Score against gold truth with `scripts/score_results.py`.

---

## Sample Documents

Six realistic Indian health insurance documents are included in `samples/`:

| Document | Description |
|---|---|
| `ir dai_policy_certificate.pdf` | IRDAI policy certificate — ₹10L sum insured, ₹5K/day room rent limit, 10% co-pay, 48-month PED waiting period |
| `discharge_summary.pdf` | Hospital discharge — laparoscopic cholecystectomy, 6-day stay (2 ICU), ICD-10 K81.0 |
| `hospital_bill.pdf` | Itemized bill — room rent ₹5,500/day, surgery, diagnostics, pharmacy, GST 18%, total ~₹2.26L |
| `claim_form.pdf` | Reimbursement claim form — expense breakdown, bank details, declarations |
| `pharmacy_bill.pdf` | Post-hospitalization medicines — ₹2,060 |
| `diagnostic_report.pdf` | Pre-admission lab + USG — acute calculous cholecystitis findings |

Upload all six through the UI or via curl:

```bash
curl -X POST http://localhost:8000/adjudicate \
  -F "files=@samples/ir dai_policy_certificate.pdf" \
  -F "files=@samples/discharge_summary.pdf" \
  -F "files=@samples/hospital_bill.pdf" \
  -F "files=@samples/claim_form.pdf" \
  -F "files=@samples/pharmacy_bill.pdf" \
  -F "files=@samples/diagnostic_report.pdf" \
  | python3 -m json.tool
```

Expected verdict: **PARTIAL** (room rent exceeds limit, co-pay applies).

---

## Key Design Decisions

- **Untagged upload** — PDFs are identified by content, not filename. Rename them to anything and the AI still knows what they are.
- **Stateless processing** — health adjudication requires no database. PDFs are read, processed, and discarded.
- **Two adjudication modes** — a simple "dump-and-decide" mode for the web UI, and a tool-calling agentic loop for the benchmark.
- **Provider-agnostic** — swap the LLM backend by editing `router_config.yaml`. Supports vLLM, OpenAI, Gemini, OpenRouter, and any OpenAI-compatible API.
- **Indian insurance context** — IRDAI-style policies, rupee amounts, ICD-10 diagnoses, standard hospital billing formats.

---

## Further Reading

| Document | What it covers |
|---|---|
| `ARCHITECTURE.md` | Agentic architecture, technology stack, process flow |
| `dataset/public/AGENT_BRIEF.md` | Full adjudication conventions, clause reference, deduction order |
| `dataset/public/METRICS.md` | Scoring contract, what to report, submission format |
| `DEMO.md` | Demo checklist with curl commands for every endpoint |
| `diff.md` | What changed from the original Azure-hardcoded version |

---

## License

MIT
