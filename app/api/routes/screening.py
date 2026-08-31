"""
API Routes - Screening
=======================
Endpoints for title/abstract and full-text screening.

Screening questions:
Q1: Does the study experimentally compare at least two FL algorithms/methods?
Q2: Does it evaluate those methods under Non-IID or heterogeneous conditions?
Q3: Does it contain an explicit comparative/superiority claim?
Q4: Is enough full text available to verify eligibility?

Decisions: include, exclude, borderline, awaiting_full_text, duplicate
"""

import logging
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy.orm import Session

from app.db.engine import get_db
from app.models.paper import Paper
from app.models.screening import ScreeningDecision
from app.services.screening import (
    ScreeningService,
    VALID_ANSWERS,
    VALID_DECISIONS,
    VALID_EXCLUSION_REASONS,
    STAGE_TITLE_ABSTRACT,
    STAGE_FULL_TEXT,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# --- Request/Response Models ---

class ScreeningSubmission(BaseModel):
    paper_id: int
    stage: str = STAGE_TITLE_ABSTRACT
    q1_fl_comparison: Optional[str] = Field(None, description="YES, NO, UNCLEAR")
    q2_non_iid: Optional[str] = Field(None, description="YES, NO, UNCLEAR")
    q3_superiority_claim: Optional[str] = Field(None, description="YES, NO, UNCLEAR")
    q4_full_text_available: Optional[str] = Field(None, description="YES, NO, UNCLEAR")
    decision: Optional[str] = Field(None, description="include, exclude, borderline, awaiting_full_text")
    exclusion_reason: Optional[str] = Field(None, description="Required if decision=exclude")
    exclusion_reason_detail: Optional[str] = Field(None, description="Free-text detail")
    notes: Optional[str] = None


class BulkScreeningItem(BaseModel):
    paper_id: int
    stage: str = STAGE_TITLE_ABSTRACT
    q1_fl_comparison: Optional[str] = None
    q2_non_iid: Optional[str] = None
    q3_superiority_claim: Optional[str] = None
    q4_full_text_available: Optional[str] = None
    decision: Optional[str] = None
    exclusion_reason: Optional[str] = None
    exclusion_reason_detail: Optional[str] = None
    notes: Optional[str] = None


class BulkScreeningRequest(BaseModel):
    decisions: list[BulkScreeningItem]


# --- Endpoints ---

@router.get("/questions")
async def get_screening_questions():
    """
    Return the four screening questions with explanations.
    Useful for building the UI.
    """
    return {
        "questions": [
            {
                "id": "q1",
                "field": "q1_fl_comparison",
                "text": "Does the study experimentally compare at least two FL algorithms/methods?",
                "help": "Look for empirical comparison of at least two federated learning methods. "
                        "A single-method study with only baselines does NOT qualify.",
                "options": list(VALID_ANSWERS),
            },
            {
                "id": "q2",
                "field": "q2_non_iid",
                "text": "Does it evaluate those methods under Non-IID or heterogeneous conditions?",
                "help": "Non-IID means clients have different data distributions. "
                        "IID-only evaluation does NOT qualify.",
                "options": list(VALID_ANSWERS),
            },
            {
                "id": "q3",
                "field": "q3_superiority_claim",
                "text": "Does it contain an explicit comparative/superiority claim?",
                "help": "Look for claims like 'our method outperforms', 'superior to', "
                        "'state-of-the-art', or explicit comparison conclusions.",
                "options": list(VALID_ANSWERS),
            },
            {
                "id": "q4",
                "field": "q4_full_text_available",
                "text": "Is enough full text available to verify eligibility?",
                "help": "Can you access the full text (PDF, open access, etc.)? "
                        "If only abstract is available, mark NO.",
                "options": list(VALID_ANSWERS),
            },
        ],
        "decisions": list(VALID_DECISIONS),
        "exclusion_reasons": list(VALID_EXCLUSION_REASONS),
        "stages": [STAGE_TITLE_ABSTRACT, STAGE_FULL_TEXT],
    }


@router.get("/next")
async def get_next_paper(
    stage: str = Query(STAGE_TITLE_ABSTRACT),
    db: Session = Depends(get_db),
):
    """
    Get the next paper that needs screening.
    Automatically skips duplicates and already-screened papers.
    """
    service = ScreeningService(db)
    paper = service.get_next_paper_to_screen(stage=stage)

    if not paper:
        return {"message": "No more papers to screen at this stage.", "paper": None}

    return {
        "paper": {
            "id": paper.id,
            "title": paper.title,
            "abstract": paper.abstract,
            "authors": paper.authors,
            "publication_year": paper.publication_year,
            "source": paper.source,
            "doi": paper.doi,
            "openalex_id": paper.openalex_id,
            "is_open_access": paper.is_open_access,
            "pdf_url": paper.pdf_url,
            "screening_status": paper.screening_status,
        },
        "stage": stage,
    }


@router.post("/submit")
async def submit_screening(submission: ScreeningSubmission, db: Session = Depends(get_db)):
    """Submit a screening decision for a paper."""
    service = ScreeningService(db)

    try:
        result = service.submit_decision(
            paper_id=submission.paper_id,
            stage=submission.stage,
            q1=submission.q1_fl_comparison,
            q2=submission.q2_non_iid,
            q3=submission.q3_superiority_claim,
            q4=submission.q4_full_text_available,
            decision=submission.decision,
            exclusion_reason=submission.exclusion_reason,
            exclusion_reason_detail=submission.exclusion_reason_detail,
            notes=submission.notes,
            actor="user",
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/bulk-submit")
async def bulk_submit(request: BulkScreeningRequest, db: Session = Depends(get_db)):
    """Submit multiple screening decisions at once."""
    service = ScreeningService(db)

    decisions = [item.model_dump() for item in request.decisions]
    result = service.bulk_submit(decisions, actor="user")
    return result


@router.get("/history/{paper_id}")
async def get_screening_history(paper_id: int, db: Session = Depends(get_db)):
    """Get the full screening history for a paper."""
    service = ScreeningService(db)
    history = service.get_screening_history(paper_id)
    return {"paper_id": paper_id, "history": history, "count": len(history)}


@router.get("/progress")
async def get_screening_progress(db: Session = Depends(get_db)):
    """Get screening progress statistics."""
    service = ScreeningService(db)
    return service.get_screening_progress()


@router.get("/list")
async def list_screening_queue(
    stage: str = Query(STAGE_TITLE_ABSTRACT),
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """
    List papers in the screening queue.
    Filter by stage and/or status.
    """
    query = db.query(Paper)

    # Exclude confirmed duplicates
    query = query.filter(
        Paper.duplicate_status.not_in(["probable_duplicate", "confirmed_duplicate"])
    )

    if status:
        query = query.filter(Paper.screening_status == status)
    elif stage == STAGE_TITLE_ABSTRACT:
        # For title/abstract: show not_screened, borderline, awaiting_full_text
        query = query.filter(
            Paper.screening_status.in_([
                "not_screened", "borderline", "awaiting_full_text"
            ])
        )
    elif stage == STAGE_FULL_TEXT:
        # For full-text: show included papers that haven't been full-text screened
        subquery = (
            db.query(ScreeningDecision.paper_id)
            .filter(ScreeningDecision.stage == STAGE_FULL_TEXT)
            .subquery()
        )
        query = query.filter(
            Paper.screening_status == "include",
            ~Paper.id.in_(subquery),
        )

    total = query.count()
    papers = query.order_by(Paper.id).offset((page - 1) * page_size).limit(page_size).all()

    return {
        "stage": stage,
        "status_filter": status,
        "total": total,
        "page": page,
        "page_size": page_size,
        "papers": [
            {
                "id": p.id,
                "title": p.title,
                "abstract": p.abstract,
                "authors": p.authors,
                "publication_year": p.publication_year,
                "source": p.source,
                "doi": p.doi,
                "is_open_access": p.is_open_access,
                "pdf_url": p.pdf_url,
                "screening_status": p.screening_status,
                "screening_decision": p.screening_decision,
                "exclusion_reason": p.exclusion_reason,
            }
            for p in papers
        ],
    }


@router.get("/full-text/{paper_id}")
async def get_full_text_screening(paper_id: int, db: Session = Depends(get_db)):
    """
    Get full-text screening details for a paper that passed title/abstract screening.
    Shows the paper metadata and any previous screening decisions.
    """
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    service = ScreeningService(db)
    history = service.get_screening_history(paper_id)

    return {
        "paper": {
            "id": paper.id,
            "title": paper.title,
            "abstract": paper.abstract,
            "authors": paper.authors,
            "publication_year": paper.publication_year,
            "source": paper.source,
            "doi": paper.doi,
            "is_open_access": paper.is_open_access,
            "pdf_url": paper.pdf_url,
            "oa_url": paper.oa_url,
        },
        "screening_history": history,
    }
