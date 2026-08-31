"""
API Routes - LLM Assistance
=============================
Optional LLM-assisted extraction and screening.

IMPORTANT:
- LLM suggestions are recommendations only.
- Human researcher remains the final decision maker.
- All LLM outputs include evidence snippets and confidence.
"""

import logging
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from app.db.engine import get_db
from app.services.llm_extraction import LLMExtractionService

router = APIRouter()
logger = logging.getLogger(__name__)


class LLMExtractionRequest(BaseModel):
    paper_id: int
    extraction_type: str = "full"  # full, algorithms, datasets, non_iid, evidence


@router.get("/status")
async def get_llm_status():
    """Check if LLM is configured."""
    service = LLMExtractionService(None)
    return {
        "configured": service.is_configured(),
        "provider": service.provider or "not set",
        "model": service.model or "not set",
    }


@router.post("/extract")
async def llm_extract(
    request: LLMExtractionRequest,
    db: Session = Depends(get_db),
):
    """
    Get LLM extraction suggestions for a paper.
    
    The LLM suggests structured data based on the paper's abstract/metadata.
    All suggestions include evidence snippets and confidence scores.
    Human verification is required before accepting any suggestion.
    """
    service = LLMExtractionService(db)

    if not service.is_configured():
        raise HTTPException(
            status_code=400,
            detail="LLM not configured. Set LLM_PROVIDER, LLM_API_KEY, and LLM_MODEL in .env",
        )

    try:
        result = service.suggest_extraction(
            paper_id=request.paper_id,
            extraction_type=request.extraction_type,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"LLM extraction failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/screen/{paper_id}")
async def llm_screen(
    paper_id: int,
    db: Session = Depends(get_db),
):
    """
    Get LLM screening suggestion for a paper.
    
    The LLM answers the four screening questions based on the abstract.
    The human researcher makes the final decision.
    """
    service = LLMExtractionService(db)

    if not service.is_configured():
        raise HTTPException(
            status_code=400,
            detail="LLM not configured. Set LLM_PROVIDER, LLM_API_KEY, and LLM_MODEL in .env",
        )

    try:
        result = service.suggest_screening(paper_id=paper_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"LLM screening failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config")
async def get_llm_config():
    """
    Get current LLM configuration (without exposing API key).
    """
    service = LLMExtractionService(None)
    return {
        "configured": service.is_configured(),
        "provider": service.provider or "not set",
        "model": service.model or "not set",
            "supported_providers": ["openai", "anthropic", "groq"],
    }
