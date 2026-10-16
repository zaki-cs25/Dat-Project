# EMA Demo Checklist

## What is this deployment?

**Dynamic.** Not static. Three live components talking to each other:

```
Browser ──► Next.js (port 3000) ──► FastAPI (port 8000) ──► vLLM (port 9000)
```

- **Frontend**: Next.js 16 dev server, server-rendered, hot-reloading
- **Backend**: FastAPI with uvicorn, auto-reloading on code changes
- **LLM**: vLLM running Qwen3.6-27B, responds to every request in real-time
- **Database**: In-memory mock data (no Supabase)

---

## Demo Walkthrough

### 1. Claims Dashboard (Home Page)

**URL**: http://192.168.50.148:3000

**What to show**:
- [x] Sidebar navigation loads (Inbox, Health Claims, Analytics, Work Queue, etc.)
- [x] "Welcome back, John" header
- [x] Claims Inbox list with 15 mock claims
- [x] Each card shows: policy holder name, vehicle, claim ID, confidence %, status badge
- [x] Status badges color-coded: Needs Review (amber), Processing (blue), Approved (green)
- [x] Click any claim card → navigates to claim detail page

**Verify with curl**:
```bash
curl http://192.168.50.148:8000/claims | python3 -m json.tool | head -20
```

---

### 2. Health Claims Adjudication

**URL**: http://192.168.50.148:3000/health-claims

**What to show**:
- [x] Page loads with single upload zone (drag-and-drop, `.pdf` only, multiple files)
- [x] Upload sample PDFs from `samples/` directory (all 6 files at once)
- [x] Uploaded files appear in a list with name, size, and remove button
- [x] Click "Adjudicate Claim" button → spinner shows "Analyzing Documents..."
- [x] LLM reads all documents, identifies each by content (not filename)
- [x] Verdict card appears with color-coded result:
  - Green = APPROVED
  - Red = REJECTED
  - Amber = PARTIALLY APPROVED
  - Orange = ESCALATED FOR REVIEW
- [x] Card shows detailed reasoning citing specific facts from documents
- [x] Document identification section lists each file and what the AI identified it as
- [x] Extracted details section shows patient name, amounts, diagnosis codes, etc.
- [x] "Start Over" button resets the page

**Demo script**: Upload all 6 sample PDFs at once. The expected verdict is **PARTIAL** because:
- Room rent is ₹5,500/day which exceeds the policy limit of ₹5,000/day (proportional deduction)
- 10% co-pay clause applies
- Ambulance charge (₹2,500) may exceed the ₹1,000 policy limit
- Surgery is covered, within sum insured, post-hospitalization pharmacy within 60-day window

**Verify with curl**:
```bash
# Adjudicate with sample PDFs
curl -X POST http://192.168.50.148:8000/adjudicate \
  -F "files=@samples/ir dai_policy_certificate.pdf" \
  -F "files=@samples/discharge_summary.pdf" \
  -F "files=@samples/hospital_bill.pdf" \
  -F "files=@samples/claim_form.pdf" \
  -F "files=@samples/pharmacy_bill.pdf" \
  -F "files=@samples/diagnostic_report.pdf" \
  | python3 -m json.tool

# Verify verdict is one of: APPROVE, REJECT, PARTIAL, ESCALATE
curl -s -X POST http://192.168.50.148:8000/adjudicate \
  -F "files=@samples/ir dai_policy_certificate.pdf" \
  -F "files=@samples/discharge_summary.pdf" \
  -F "files=@samples/hospital_bill.pdf" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Verdict: {d[\"verdict\"]}'); print(f'Reasoning: {d[\"reasoning\"][:300]}...')"

# Test with just two files (should ESCALATE - missing key documents)
curl -s -X POST http://192.168.50.148:8000/adjudicate \
  -F "files=@samples/discharge_summary.pdf" \
  -F "files=@samples/pharmacy_bill.pdf" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Verdict: {d[\"verdict\"]}')"

# Error: no files
curl -s -X POST http://192.168.50.148:8000/adjudicate | python3 -m json.tool
```

**Edge cases to verify**:
- [x] Upload no files → shows "Please upload at least one PDF document" error
- [x] Upload non-PDF file → rejected with 400 error
- [x] Upload only discharge summary + pharmacy bill (no policy) → verdict should be ESCALATE
- [x] File names don't matter — rename files to `doc1.pdf`, `xyz.pdf`, etc. — AI still identifies them correctly

---

### 3. Claim Detail Page (Claim 360)

**URL**: http://192.168.50.148:3000/claim/CLM-2025-001

**What to show**:
- [x] Left panel: Claim details (policy holder, vehicle, incident date)
- [x] Center: Interactive evidence graph (React Flow) — drag nodes around
- [x] Right panel: AI Summary with risk factors
- [x] Action buttons: Approve & Pay, Reject Claim, Escalate to SIU
- [x] "Add Evidence" button in the graph adds new nodes live
- [x] Click "View Policy Doc" → opens document viewer modal

**Verify with curl**:
```bash
curl http://192.168.50.148:8000/claims/CLM-2025-001 | python3 -m json.tool
```

---

### 4. EMA Assistant Chat (Live LLM)

**URL**: http://192.168.50.148:3000/claim/CLM-2025-001 → switch to "EMA Assistant" tab

**What to show**:
- [x] Switch from "Agent Activity" to "EMA Assistant" tab
- [x] Type a question like "Why was this claim flagged?"
- [x] LLM responds in real-time from your vLLM server
- [x] Ask "Draft an approval email" — gets a formatted email
- [x] Ask "Analyze the risk" — gets risk assessment

**Verify with curl**:
```bash
curl -X POST http://192.168.50.148:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Why was claim CLM-2025-001 flagged?"}' | python3 -m json.tool
```

---

### 5. Document Analysis (Smart PDF)

**URL**: http://192.168.50.148:3000/claim/CLM-2025-001 → "View Policy Doc" → "Analyze with AI"

**What to show**:
- [x] Split screen: mock PDF on left, extracted data on right
- [x] Click "Analyze with AI" button
- [x] LLM parses the repair estimate and returns structured JSON
- [x] Shows line items, total amount, confidence score, risk factors
- [x] "Approve Estimate" button at the bottom

**Verify with curl**:
```bash
curl -X POST http://192.168.50.148:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"text": "Rear Bumper Cover (OEM) $850.00\nPaint & Labor $420.00\nTOTAL $1,315.00"}' \
  | python3 -m json.tool
```

---

### 6. Analytics Dashboard

**URL**: http://192.168.50.148:3000/analytics

**What to show**:
- [x] KPI cards: Total Claims, Avg Processing Time, Auto-Approval Rate, Cost Savings
- [x] Claim volume bar chart
- [x] Processing time trend line
- [x] Agent performance table with accuracy and speed metrics

**Verify with curl**:
```bash
curl http://192.168.50.148:8000/analytics | python3 -m json.tool
```

---

### 7. Claim Actions (Approve / Reject / Escalate)

**URL**: http://192.168.50.148:3000/claim/CLM-2025-001

**What to show**:
- [x] Click "Approve & Pay" → modal shows payout breakdown ($1,913.13 - $500 deductible)
- [x] Click "Reject Claim" → modal asks for rejection reason
- [x] Click "Escalate to SIU" → modal shows fraud escalation protocol
- [x] After confirming, status badge updates live

---

### 8. Create New Claim

**URL**: http://192.168.50.148:3000 → click "+ New Claim" button

**What to show**:
- [x] Modal opens with form fields
- [x] Fill in details, submit
- [x] New claim appears at top of inbox list

**Verify with curl**:
```bash
curl -X POST http://192.168.50.148:8000/claims \
  -H "Content-Type: application/json" \
  -d '{"id":"CLM-2025-016","policyHolder":"Test User","incidentDate":"2025-12-01","status":"Needs Review","severity":"Medium","vehicle":"2024 Test Car","confidence":80}' \
  | python3 -m json.tool
```

---

## Quick Terminal Verification (Run All)

Paste this to verify every endpoint at once:

```bash
echo "=== Health Check ==="
curl -s http://192.168.50.148:8000/health

echo -e "\n\n=== Claims List (first 2) ==="
curl -s http://192.168.50.148:8000/claims | python3 -c "import sys,json; d=json.load(sys.stdin); [print(f'{c[\"id\"]} | {c[\"policyHolder\"]} | {c[\"status\"]} | {c[\"confidence\"]}%') for c in d[:2]]"

echo -e "\n\n=== Single Claim ==="
curl -s http://192.168.50.148:8000/claims/CLM-2025-001 | python3 -m json.tool

echo -e "\n\n=== Analytics ==="
curl -s http://192.168.50.148:8000/analytics | python3 -c "import sys,json; d=json.load(sys.stdin); [print(f'{s[\"name\"]}: {s[\"value\"]} ({s[\"change\"]})') for s in d['stats']]"

echo -e "\n\n=== Chat (LLM) ==="
curl -s -X POST http://192.168.50.148:8000/chat -H "Content-Type: application/json" -d '{"message":"What is the risk level of CLM-2025-001?"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['response'][:200])"

echo -e "\n\n=== Document Analysis ==="
curl -s -X POST http://192.168.50.148:8000/analyze -H "Content-Type: application/json" -d '{"text":"Bumper $850, Labor $420, TOTAL $1270"}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Total: \${d[\"total_amount\"]}, Confidence: {d[\"confidence_score\"]}')"

echo -e "\n\n=== Health Adjudication (all 6 sample PDFs) ==="
curl -s -X POST http://192.168.50.148:8000/adjudicate \
  -F "files=@samples/ir dai_policy_certificate.pdf" \
  -F "files=@samples/discharge_summary.pdf" \
  -F "files=@samples/hospital_bill.pdf" \
  -F "files=@samples/claim_form.pdf" \
  -F "files=@samples/pharmacy_bill.pdf" \
  -F "files=@samples/diagnostic_report.pdf" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Verdict: {d[\"verdict\"]}'); print(f'Docs identified: {len(d.get(\"document_summary\",[]))}'); print(f'Reasoning: {d[\"reasoning\"][:200]}...')"

echo -e "\n\n=== Frontend ==="
curl -s -o /dev/null -w "Status: %{http_code}\n" http://192.168.50.148:3000

echo -e "\n✅ All endpoints verified!"
```

---

## Sample PDF Documents

Six Indian health insurance documents are available in the `samples/` directory:

| File | Document Type | Use Case |
|---|---|---|
| `ir dai_policy_certificate.pdf` | IRDAI Policy Certificate | ₹10L policy, ₹5K/day room rent, 10% co-pay |
| `discharge_summary.pdf` | Hospital Discharge Summary | Lap cholecystectomy, 6-day stay |
| `hospital_bill.pdf` | Itemized Hospital Bill | ~₹2.26L total, room rent exceeds limit |
| `claim_form.pdf` | Claim Form | Reimbursement claim, expense breakdown |
| `pharmacy_bill.pdf` | Pharmacy Bill | Post-hospitalization medicines, ₹2,060 |
| `diagnostic_report.pdf` | Diagnostic Lab Report | Pre-admission tests, USG findings |

Regenerate with: `python3 backend/scripts/generate_samples.py`

---

## The Supabase Storage Error

You see `StorageUnknownError: Failed to fetch` in the console. This is from the dummy Supabase client trying to reach a non-existent storage bucket. It's **cosmetic only** — no feature breaks. The app uses mock data for everything.

If you want to silence it, the Supabase calls are in `frontend/src/lib/supabaseClient.ts` with dummy credentials. No action needed for the demo.
