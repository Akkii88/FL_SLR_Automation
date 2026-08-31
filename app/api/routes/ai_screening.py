"""
API Routes - AI Screening
===========================
Endpoints for AI-assisted first-pass screening.
"""

import logging
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, not_, exists

from app.db.engine import get_db
from app.models.paper import Paper
from app.models.ai_screening import AIScreeningResult
from app.services.ai_screening import AIScreeningService

router = APIRouter()
logger = logging.getLogger(__name__)


class BatchScreenRequest(BaseModel):
    batch_size: int = 25


@router.get("/status")
async def ai_screening_status(db: Session = Depends(get_db)):
    """Get AI screening configuration status."""
    service = AIScreeningService(db)
    return {
        "configured": service.is_configured(),
        "provider": service.provider or "not set",
        "model": service.model or "not set",
    }


@router.get("/summary")
async def ai_screening_summary(db: Session = Depends(get_db)):
    """Get AI screening progress summary."""
    service = AIScreeningService(db)
    return service.get_screening_summary()


@router.post("/batch-screen")
async def batch_screen(
    request: BatchScreenRequest = None,
    db: Session = Depends(get_db),
):
    """
    Run AI screening on a batch of unscreened papers.
    Processes papers that haven't been AI-screened yet.
    """
    if request is None:
        request = BatchScreenRequest()

    service = AIScreeningService(db)

    if not service.is_configured():
        raise HTTPException(
            status_code=400,
            detail="LLM not configured. Set LLM_PROVIDER, LLM_API_KEY, and LLM_MODEL in .env",
        )

    result = service.batch_screen(batch_size=request.batch_size)
    return result


@router.post("/screen/{paper_id}")
async def screen_single_paper(
    paper_id: int,
    use_cache: bool = True,
    db: Session = Depends(get_db),
):
    """Screen a single paper using AI."""
    service = AIScreeningService(db)

    if not service.is_configured():
        raise HTTPException(
            status_code=400,
            detail="LLM not configured.",
        )

    try:
        result = service.screen_paper(paper_id, use_cache=use_cache)
        return result.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/results")
async def get_ai_screening_results(
    recommendation: Optional[str] = None,
    confidence: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """
    Get AI screening results with optional filters.
    Returns only active (most recent) results.
    """
    from sqlalchemy import and_

    query = db.query(AIScreeningResult).filter(
        AIScreeningResult.is_active == True
    )

    if recommendation:
        query = query.filter(AIScreeningResult.recommendation == recommendation)
    if confidence:
        query = query.filter(AIScreeningResult.confidence == confidence)

    total = query.count()
    results = query.order_by(AIScreeningResult.paper_id).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "results": [r.to_dict() for r in results],
    }


@router.get("/paper/{paper_id}")
async def get_paper_ai_screening(paper_id: int, db: Session = Depends(get_db)):
    """Get AI screening result for a specific paper."""
    result = db.query(AIScreeningResult).filter(
        and_(
            AIScreeningResult.paper_id == paper_id,
            AIScreeningResult.is_active == True,
        )
    ).first()

    if not result:
        raise HTTPException(status_code=404, detail="No AI screening result found for this paper.")

    return result.to_dict()


@router.get("/queue")
async def get_screening_queue(
    status: str = Query("not_screened"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """
    Get papers in the screening queue.
    status: 'not_screened', 'ai_screened', 'human_decided'
    """
    from sqlalchemy import not_, exists

    if status == "not_screened":
        # Papers without any AI screening result
        screened_ids = db.query(AIScreeningResult.paper_id).filter(
            AIScreeningResult.is_active == True
        ).subquery()
        query = db.query(Paper).filter(~Paper.id.in_(screened_ids))

    elif status == "ai_screened":
        # Papers with AI screening but no human decision
        from app.models.screening import ScreeningDecision
        ai_screened = db.query(AIScreeningResult.paper_id).filter(
            AIScreeningResult.is_active == True
        ).subquery()
        human_decided = db.query(ScreeningDecision.paper_id).filter(
            ScreeningDecision.decision.isnot(None)
        ).subquery()
        query = db.query(Paper).filter(
            Paper.id.in_(ai_screened),
            ~Paper.id.in_(human_decided),
        )

    elif status == "human_decided":
        # Papers with human decision
        from app.models.screening import ScreeningDecision
        human_decided = db.query(ScreeningDecision.paper_id).filter(
            ScreeningDecision.decision.isnot(None)
        ).subquery()
        query = db.query(Paper).filter(Paper.id.in_(human_decided))

    else:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    total = query.count()
    papers = query.order_by(Paper.id).offset((page - 1) * page_size).limit(page_size).all()

    return {
        "status_filter": status,
        "total": total,
        "page": page,
        "page_size": page_size,
        "papers": [
            {
                "id": p.id,
                "title": p.title,
                "abstract": p.abstract,
                "publication_year": p.publication_year,
                "source": p.source,
                "doi": p.doi,
                "screening_status": p.screening_status,
            }
            for p in papers
        ],
    }
