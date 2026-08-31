"""
API Routes - Search
====================
Endpoints for running searches and viewing search history.
"""

import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from app.db.engine import get_db, SessionLocal
from app.core.config import settings
from app.core.review_config import load_or_create_config
from app.services.search_service import SearchService
from app.models.search_run import SearchRun

router = APIRouter()
logger = logging.getLogger(__name__)


class SearchRequest(BaseModel):
    family: str  # A, B, C, D, E, F
    max_candidates: Optional[int] = None


class SearchResponse(BaseModel):
    search_run_id: int
    family: str
    query: str
    records_saved: int
    records_seen: int
    errors: list[str]


@router.post("/run", response_model=SearchResponse)
async def run_search(request: SearchRequest, db: Session = Depends(get_db)):
    """Run a single search family against OpenAlex."""
    config = load_or_create_config(settings.project_root)

    service = SearchService(db, config)
    try:
        result = service.run_search_family(
            family_name=request.family,
            max_candidates=request.max_candidates,
        )

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        return SearchResponse(**result)
    finally:
        service.close()


@router.post("/run-all")
async def run_all_searches(max_candidates: Optional[int] = None, db: Session = Depends(get_db)):
    """Run all enabled search families."""
    config = load_or_create_config(settings.project_root)
    service = SearchService(db, config)
    results = []

    try:
        for family in config.search_families:
            if family.enabled:
                result = service.run_search_family(
                    family_name=family.name,
                    max_candidates=max_candidates,
                )
                results.append(result)
    finally:
        service.close()

    return {"results": results}


@router.post("/resume")
async def resume_search(max_candidates: Optional[int] = None, db: Session = Depends(get_db)):
    """Resume a search from the last checkpoint."""
    from app.services.checkpoint import has_checkpoint, load_checkpoint

    if not has_checkpoint():
        raise HTTPException(status_code=400, detail="No checkpoint found to resume from.")

    checkpoint = load_checkpoint()
    family_name = checkpoint.get("family_name", "A")

    config = load_or_create_config(settings.project_root)
    service = SearchService(db, config)

    try:
        result = service.run_search_family(
            family_name=family_name,
            max_candidates=max_candidates,
            resume=True,
        )

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        result["resumed_from"] = checkpoint
        return result
    finally:
        service.close()


@router.get("/history")
async def search_history(db: Session = Depends(get_db)):
    """Get search run history."""
    runs = db.query(SearchRun).order_by(SearchRun.created_at.desc()).all()
    return [
        {
            "id": r.id,
            "source": r.source,
            "search_family": r.search_family,
            "exact_query": r.exact_query,
            "search_date": r.search_date.isoformat() if r.search_date else None,
            "start_time": r.start_time.isoformat() if r.start_time else None,
            "end_time": r.end_time.isoformat() if r.end_time else None,
            "year_filter": r.year_filter,
            "document_filter": r.document_filter,
            "total_matching_count": r.total_matching_count,
            "results_retrieved": r.results_retrieved,
            "records_parsed": r.records_parsed,
            "records_failed": r.records_failed,
            "records_deduplicated": r.records_deduplicated,
            "records_saved": r.records_saved,
            "pages_retrieved": r.pages_retrieved,
            "duration_seconds": r.duration_seconds,
            "errors": r.errors,
            "retries": r.retries,
            "notes": r.notes,
        }
        for r in runs
    ]
