from fastapi import FastAPI, HTTPException, UploadFile
from pydantic import BaseModel
from backend.agent import get_agent_response
from dotenv import load_dotenv
import os

load_dotenv()

app = FastAPI()

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default"

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.post("/chat")
async def chat(request: ChatRequest):
    try:
        response = await get_agent_response(request.message, request.thread_id)
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

from backend.mock_data import CLAIMS, ANALYTICS

from backend.agents.claims_agent import analyze_claim_document

class DocumentRequest(BaseModel):
    text: str

@app.post("/analyze")
async def analyze_document(request: DocumentRequest):
    result = await analyze_claim_document(request.text)
    return result

from backend.supabase_client import supabase

@app.get("/claims")
async def get_claims():
    if not supabase:
        return CLAIMS
        
    try:
        response = supabase.table("claims").select("*").order("created_at", desc=True).execute()
        # If table exists but is empty, we might want to return mock data for the demo
        if response.data and len(response.data) > 0:
            return response.data
        return CLAIMS # Fallback if empty or error
    except Exception as e:
        print(f"Supabase error: {e}")
        return CLAIMS

@app.get("/claims/{claim_id}")
async def get_claim(claim_id: str):
    if supabase:
        try:
            response = supabase.table("claims").select("*").eq("id", claim_id).execute()
            if response.data:
                return response.data[0]
        except Exception:
            pass
        
    # Fallback to mock data
    for claim in CLAIMS:
        if claim["id"] == claim_id:
            return claim
    raise HTTPException(status_code=404, detail="Claim not found")

class NewClaim(BaseModel):
    id: str
    policyHolder: str
    incidentDate: str
    status: str
    severity: str
    vehicle: str
    confidence: int
    documentUrl: str | None = None

@app.post("/claims")
async def create_claim(claim: NewClaim):
    claim_data = claim.dict()
    
    if not supabase:
        CLAIMS.insert(0, claim_data)
        return claim

    try:
        supabase.table("claims").insert(claim_data).execute()
    except Exception as e:
        print(f"Supabase insert error: {e}")
        # Fallback to in-memory
        CLAIMS.insert(0, claim_data)
    return claim

@app.get("/analytics")
async def get_analytics():
    return ANALYTICS


# ---------------------------------------------------------------------------
# Health Claims Adjudication Endpoint
# ---------------------------------------------------------------------------

from pypdf import PdfReader
from io import BytesIO

from backend.agents.health_adjudicator import adjudicate_claim


@app.post("/adjudicate")
async def adjudicate(files: list[UploadFile]):
    """
    Accept one or more PDF files. Extract text from each, combine into a
    single prompt, and return an adjudication verdict.
    """
    if not files:
        raise HTTPException(status_code=400, detail="At least one PDF file is required")

    documents_text_parts = []

    for i, file in enumerate(files, start=1):
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=400,
                detail=f"File '{file.filename}' is not a PDF. Only PDF files are accepted."
            )

        try:
            content = await file.read()
            pdf = PdfReader(BytesIO(content))
            pages_text = []
            for page_num, page in enumerate(pdf.pages, start=1):
                text = page.extract_text()
                if text:
                    pages_text.append(f"[Page {page_num}]\n{text}")

            if not pages_text:
                documents_text_parts.append(
                    f"=== Document {i} ({file.filename}) ===\n\n"
                    f"(No extractable text found in this PDF)\n\n"
                )
            else:
                documents_text_parts.append(
                    f"=== Document {i} ({file.filename}) ===\n\n"
                    + "\n".join(pages_text)
                    + "\n"
                )
        except Exception as e:
            documents_text_parts.append(
                f"=== Document {i} ({file.filename}) ===\n\n"
                f"(Error reading PDF: {e})\n\n"
            )

    combined_text = "\n" + "\n".join(documents_text_parts) + "\n"

    result = await adjudicate_claim(combined_text)
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
