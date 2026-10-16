import os
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
from typing import List, Optional

from backend.router import get_llm_langchain

# Data Models for Structured Output
class LineItem(BaseModel):
    item: str = Field(description="Description of the repair item or labor")
    type: str = Field(description="Type of item: 'Part', 'Labor', or 'Other'")
    cost: float = Field(description="Cost of the item")

class AnalysisResult(BaseModel):
    line_items: List[LineItem] = Field(description="List of repair line items extracted from the document")
    total_amount: float = Field(description="Total cost of the repair")
    risk_factors: List[str] = Field(description="List of potential risks or inconsistencies found")
    confidence_score: float = Field(description="Confidence score between 0 and 1")

# Prompts
ANALYSIS_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an expert Insurance Claims Adjuster AI.
    Your task is to analyze repair estimates and extract structured data.
    You must also identify potential risks such as:
    - High labor rates (>$100/hr is suspicious)
    - Duplicate items
    - Non-OEM parts used when OEM is required
    - Inconsistencies with the vehicle type (e.g., Tesla parts on a Honda)

    Return the output in strictly valid JSON format matching the requested schema.
    {format_instructions}
    """),
    ("user", "Analyze the following repair estimate document text:\n\n{document_text}")
])

ANALYSIS_PROMPT = ANALYSIS_PROMPT.partial(format_instructions=JsonOutputParser(pydantic_object=AnalysisResult).get_format_instructions())

async def analyze_claim_document(document_text: str) -> dict:
    """
    Analyzes a document text using the router's LLM to extract claim details and risks.
    """
    llm = get_llm_langchain(temperature=0)
    parser = JsonOutputParser(pydantic_object=AnalysisResult)
    chain = ANALYSIS_PROMPT | llm | parser

    try:
        result = await chain.ainvoke({"document_text": document_text})
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error in analysis: {e}")
        return {
            "line_items": [],
            "total_amount": 0.0,
            "risk_factors": ["Error processing document"],
            "confidence_score": 0.0
        }
