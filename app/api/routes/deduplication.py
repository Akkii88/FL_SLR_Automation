"""
API Routes - Deduplication
===========================
Endpoints for running deduplication, reviewing results, and manual overrides.
"""

import logging
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from app.db.engine import get_db
from app.models.paper import Paper
from app.models.deduplication import DeduplicationLog
from app.services.deduplication import DeduplicationEngine

router = APIRouter()
logger = logging.getLogger(__name__)


class DedupRunRequest(BaseModel):
    dry_run: bool = False
    families: Optional[list[str]] = None


class DedupConfirmRequest(BaseModel):
    paper_id_a: int
    paper_id_b: int
    canonical_id: int


class DedupRejectRequest(BaseModel):
    paper_id_a: int
    paper_id_b: int
    reason: str = ""


class DedupOverrideRequest(BaseModel):
    paper_id: int
    new_status: str  # unique, probable_duplicate, confirmed_duplicate, manually_retained
    reason: str
    canonical_id: Optional[int] = None


@router.post("/run")
async def run_deduplication(
    request: DedupRunRequest = None,
    db: Session = Depends(get_db),
):
    """
    Run the deduplication engine.
    Detects potential duplicates using multiple matching strategies.
    """
    if request is None:
        request = DedupRunRequest()

    engine = DeduplicationEngine(db)

    try:
        results = engine.run_deduplication(
            dry_run=request.dry_run,
            families=request.families,
        )

        if not request.dry_run:
            db.commit()

        return {
            "status": "complete",
            "dry_run": request.dry_run,
            "total_matches": len(results),
            "results": [r.to_dict() for r in results],
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Deduplication failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Don't close db — it's managed by FastAPI dependency
        pass


@router.get("/groups")
async def get_duplicate_groups(db: Session = Depends(get_db)):
    """Get all groups of duplicate papers."""
    engine = DeduplicationEngine(db)
    groups = engine.get_duplicate_groups()
    return {"groups": groups, "total_groups": len(groups)}


@router.get("/stats")
async def get_dedup_stats(db: Session = Depends(get_db)):
    """Get deduplication statistics."""
    engine = DeduplicationEngine(db)
    return engine.get_deduplication_stats()


@router.get("/review")
async def review_potential_duplicates(
    status: str = Query("probable_duplicate"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """
    Review papers with a given duplicate status.
    Default: review probable duplicates that need human confirmation.
    """
    query = db.query(Paper).filter(Paper.duplicate_status == status)
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
                "doi": p.doi,
                "openalex_id": p.openalex_id,
                "publication_year": p.publication_year,
                "duplicate_status": p.duplicate_status,
                "duplicate_of": p.duplicate_of,
                "duplicate_reason": p.duplicate_reason,
                "duplicate_confidence": p.duplicate_confidence,
                "canonical_record_id": p.canonical_record_id,
            }
            for p in papers
        ],
    }


@router.post("/confirm")
async def confirm_duplicate(
    request: DedupConfirmRequest,
    db: Session = Depends(get_db),
):
    """Manually confirm that two papers are duplicates."""
    engine = DeduplicationEngine(db)
    try:
        log = engine.confirm_duplicate(
            paper_id_a=request.paper_id_a,
            paper_id_b=request.paper_id_b,
            canonical_id=request.canonical_id,
        )
        return {
            "status": "confirmed",
            "log_id": log.id,
            "canonical_paper_id": log.canonical_paper_id,
            "duplicate_paper_id": log.duplicate_paper_id,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reject")
async def reject_duplicate(
    request: DedupRejectRequest,
    db: Session = Depends(get_db),
):
    """Reject a duplicate detection — mark papers as NOT duplicates."""
    engine = DeduplicationEngine(db)
    try:
        log = engine.reject_duplicate(
            paper_id_a=request.paper_id_a,
            paper_id_b=request.paper_id_b,
            reason=request.reason,
        )
        return {
            "status": "rejected",
            "log_id": log.id,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/override")
async def override_duplicate_status(
    request: DedupOverrideRequest,
    db: Session = Depends(get_db),
):
    """Manually override the duplicate status of a paper."""
    valid_statuses = {"unique", "probable_duplicate", "confirmed_duplicate", "manually_retained"}
    if request.new_status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {valid_statuses}",
        )

    engine = DeduplicationEngine(db)
    try:
        log = engine.manual_override(
            paper_id=request.paper_id,
            new_status=request.new_status,
            reason=request.reason,
            canonical_id=request.canonical_id,
        )
        return {
            "status": "overridden",
            "log_id": log.id,
            "paper_id": request.paper_id,
            "new_status": request.new_status,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/log")
async def get_dedup_log(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    match_type: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get the deduplication log with optional filters."""
    query = db.query(DeduplicationLog)

    if match_type:
        query = query.filter(DeduplicationLog.match_type == match_type)
    if status:
        query = query.filter(DeduplicationLog.match_status == status)

    total = query.count()
    logs = query.order_by(DeduplicationLog.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "logs": [
            {
                "id": log.id,
                "paper_id_a": log.paper_id_a,
                "paper_id_b": log.paper_id_b,
                "match_type": log.match_type,
                "match_confidence": log.match_confidence,
                "match_status": log.match_status,
                "canonical_paper_id": log.canonical_paper_id,
                "duplicate_paper_id": log.duplicate_paper_id,
                "is_override": log.is_override,
                "override_reason": log.override_reason,
                "actor": log.actor,
                "notes": log.notes,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
    }
