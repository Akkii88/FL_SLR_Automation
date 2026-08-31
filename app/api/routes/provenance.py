"""
API Routes - Provenance
========================
Endpoints for tracking paper provenance (which searches found which papers).
"""

import json
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.engine import get_db
from app.models.paper import Paper
from app.models.search_run import SearchRunPaper, SourceProvenance

router = APIRouter()


@router.get("/paper/{paper_id}")
async def get_paper_provenance(paper_id: int, db: Session = Depends(get_db)):
    """
    Get full provenance for a paper: which search families and sources found it.
    A paper may be found by multiple searches — all are retained.
    """
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Get all source provenance records
    provenance = db.query(SourceProvenance).filter(
        SourceProvenance.paper_id == paper_id
    ).order_by(SourceProvenance.retrieval_timestamp).all()

    # Get all search runs that found this paper
    search_runs = db.query(SearchRunPaper).filter(
        SearchRunPaper.paper_id == paper_id
    ).all()

    return {
        "paper_id": paper_id,
        "title": paper.title,
        "found_by_count": len(provenance),
        "provenance": [
            {
                "source": p.source,
                "search_family": p.search_family,
                "retrieval_timestamp": p.retrieval_timestamp.isoformat() if p.retrieval_timestamp else None,
            }
            for p in provenance
        ],
        "search_run_ids": [sr.search_run_id for sr in search_runs],
    }


@router.get("/family/{family_name}")
async def get_family_papers(
    family_name: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Get all papers found by a specific search family."""
    papers = (
        db.query(Paper)
        .join(SourceProvenance, Paper.id == SourceProvenance.paper_id)
        .filter(SourceProvenance.search_family == family_name)
        .order_by(Paper.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    total = (
        db.query(func.count(Paper.id))
        .join(SourceProvenance, Paper.id == SourceProvenance.paper_id)
        .filter(SourceProvenance.search_family == family_name)
        .scalar()
    )

    return {
        "family": family_name,
        "total": total,
        "page": page,
        "page_size": page_size,
        "papers": [
            {
                "id": p.id,
                "title": p.title,
                "publication_year": p.publication_year,
                "source": p.source,
                "doi": p.doi,
                "screening_status": p.screening_status,
            }
            for p in papers
        ],
    }


@router.get("/summary")
async def get_provenance_summary(db: Session = Depends(get_db)):
    """Get a summary of provenance: how many papers from each family."""
    results = (
        db.query(
            SourceProvenance.search_family,
            func.count(func.distinct(SourceProvenance.paper_id))
        )
        .group_by(SourceProvenance.search_family)
        .order_by(SourceProvenance.search_family)
        .all()
    )

    return {
        "by_family": [
            {"family": family, "paper_count": count}
            for family, count in results
            if family
        ],
        "total_provenance_records": db.query(func.count(SourceProvenance.id)).scalar(),
        "total_papers_with_provenance": db.query(
            func.count(func.distinct(SourceProvenance.paper_id))
        ).scalar(),
    }
