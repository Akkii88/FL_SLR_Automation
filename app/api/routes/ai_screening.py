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


@router.post("/retry/{paper_id}")
async def retry_failed_paper(
    paper_id: int,
    db: Session = Depends(get_db),
):
    """
    Retry AI screening for a specific failed paper.

    Validates:
    - Paper exists
    - No completed active result exists
    - Latest status is failed or retryable

    Runs screening for ONLY this paper (no batch processing).
    Uses rate-limit retry/backoff logic.
    Preserves previous failed attempts for audit history.
    """
    service = AIScreeningService(db)

    if not service.is_configured():
        raise HTTPException(
            status_code=400,
            detail="LLM not configured. Set LLM_PROVIDER, LLM_API_KEY, and LLM_MODEL in .env",
        )

    # 1. Verify paper exists
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    # 2. Verify no completed active result exists
    existing_completed = db.query(AIScreeningResult).filter(
        and_(
            AIScreeningResult.paper_id == paper_id,
            AIScreeningResult.is_active == True,
            AIScreeningResult.processing_status == "completed",
        )
    ).first()

    if existing_completed:
        raise HTTPException(
            status_code=409,
            detail=f"Paper {paper_id} already has a completed AI screening result. Cannot retry.",
        )

    # 3. Verify latest status is failed or retryable
    latest_result = db.query(AIScreeningResult).filter(
        AIScreeningResult.paper_id == paper_id
    ).order_by(AIScreeningResult.created_at.desc()).first()

    if latest_result and latest_result.processing_status not in ("failed", "pending"):
        raise HTTPException(
            status_code=409,
            detail=f"Paper {paper_id} has status '{latest_result.processing_status}'. Only failed or pending papers can be retried.",
        )

    # 4. Run screening for ONLY this paper (bypass cache to force re-LLM-call)
    try:
        result = service.screen_paper(paper_id, use_cache=False)

        return {
            "status": "success" if result.processing_status == "completed" else "failed",
            "paper_id": paper_id,
            "processing_status": result.processing_status,
            "recommendation": result.recommendation,
            "confidence": result.confidence,
            "error_message": result.error_message,
            "result_id": result.id,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
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
    Returns only active (most recent) results with paper titles.
    """
    from sqlalchemy import and_

    query = db.query(AIScreeningResult, Paper).join(
        Paper, AIScreeningResult.paper_id == Paper.id
    ).filter(
        AIScreeningResult.is_active == True
    )

    if recommendation:
        query = query.filter(AIScreeningResult.recommendation == recommendation)
    if confidence:
        query = query.filter(AIScreeningResult.confidence == confidence)

    total = query.count()
    rows = query.order_by(AIScreeningResult.paper_id).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    results = []
    for ai_result, paper in rows:
        d = ai_result.to_dict()
        d['title'] = paper.title
        results.append(d)

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "results": results,
    }


@router.get("/paper/{paper_id}")
async def get_paper_ai_screening(paper_id: int, db: Session = Depends(get_db)):
    """Get AI screening result for a specific paper."""
    from sqlalchemy import and_
    result = db.query(AIScreeningResult, Paper).join(
        Paper, AIScreeningResult.paper_id == Paper.id
    ).filter(
        and_(
            AIScreeningResult.paper_id == paper_id,
            AIScreeningResult.is_active == True,
        )
    ).first()

    if not result:
        raise HTTPException(status_code=404, detail="No AI screening result found for this paper.")

    ai_result, paper = result
    d = ai_result.to_dict()
    d['title'] = paper.title
    return d


@router.get("/failed-papers")
async def get_failed_papers(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """
    Get papers that have failed AI screening and can be retried.
    Returns papers where the latest AI screening result is 'failed'.
    """
    from sqlalchemy import and_, func

    # Subquery: get the latest result timestamp for each paper
    latest = db.query(
        AIScreeningResult.paper_id,
        func.max(AIScreeningResult.created_at).label('max_created')
    ).group_by(AIScreeningResult.paper_id).subquery()

    # Join to get papers where the latest result is failed
    query = db.query(AIScreeningResult, Paper).join(
        Paper, AIScreeningResult.paper_id == Paper.id
    ).join(
        latest,
        and_(
            AIScreeningResult.paper_id == latest.c.paper_id,
            AIScreeningResult.created_at == latest.c.max_created,
        )
    ).filter(
        AIScreeningResult.processing_status == 'failed'
    ).order_by(AIScreeningResult.paper_id)

    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()

    # Count attempts per paper
    attempt_counts = {}
    for ai_result, paper in rows:
        count = db.query(func.count(AIScreeningResult.id)).filter(
            AIScreeningResult.paper_id == ai_result.paper_id
        ).scalar()
        attempt_counts[ai_result.paper_id] = count

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "papers": [
            {
                "id": paper.id,
                "title": paper.title,
                "error_message": ai_result.error_message,
                "attempts": attempt_counts.get(paper.id, 1),
            }
            for ai_result, paper in rows
        ],
    }
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
