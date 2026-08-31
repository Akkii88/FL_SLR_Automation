"""
API Routes - Dashboard
=======================
Endpoints for dashboard statistics.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.engine import get_db
from app.models.paper import Paper
from app.models.search_run import SearchRun, SourceProvenance
from app.models.screening import AuditLog

router = APIRouter()


@router.get("/")
async def dashboard_stats(db: Session = Depends(get_db)):
    """Get dashboard statistics."""
    total = db.query(Paper).count()
    unique_count = db.query(Paper).filter(Paper.duplicate_status == "unique").count()
    duplicate_count = db.query(Paper).filter(
        Paper.duplicate_status.in_(["probable_duplicate", "confirmed_duplicate"])
    ).count()

    # Screening status counts
    included = db.query(Paper).filter(Paper.screening_status == "include").count()
    excluded = db.query(Paper).filter(Paper.screening_status == "exclude").count()
    borderline = db.query(Paper).filter(Paper.screening_status == "borderline").count()
    awaiting = db.query(Paper).filter(Paper.screening_status == "awaiting_full_text").count()
    not_screened = db.query(Paper).filter(Paper.screening_status == "not_screened").count()

    # Papers by year
    year_counts = (
        db.query(Paper.publication_year, func.count(Paper.id))
        .filter(Paper.publication_year.isnot(None))
        .group_by(Paper.publication_year)
        .order_by(Paper.publication_year)
        .all()
    )

    # Papers by source
    source_counts = (
        db.query(Paper.source, func.count(Paper.id))
        .filter(Paper.source.isnot(None))
        .group_by(Paper.source)
        .order_by(func.count(Paper.id).desc())
        .limit(20)
        .all()
    )

    # Papers by search family
    family_counts = (
        db.query(
            SourceProvenance.search_family,
            func.count(func.distinct(SourceProvenance.paper_id))
        )
        .filter(SourceProvenance.search_family.isnot(None))
        .group_by(SourceProvenance.search_family)
        .order_by(SourceProvenance.search_family)
        .all()
    )

    # Search run statistics
    total_searches = db.query(func.count(SearchRun.id)).scalar()
    total_retries = db.query(func.coalesce(func.sum(SearchRun.retries), 0)).scalar()
    total_pages = db.query(func.coalesce(func.sum(SearchRun.pages_retrieved), 0)).scalar()

    # Recent audit activity
    recent_audit = db.query(func.count(AuditLog.id)).scalar()

    # Evidence quality stats (if any claims have been assessed)
    from app.models.extraction import Claim, EvidenceQuality
    total_claims = db.query(func.count(Claim.id)).scalar()
    assessed_claims = db.query(func.count(EvidenceQuality.id)).scalar()
    direct_stats_count = db.query(func.count(EvidenceQuality.id)).filter(
        EvidenceQuality.direct_statistical_test == True
    ).scalar()

    return {
        "total_records": total,
        "unique_papers": unique_count,
        "duplicates": duplicate_count,
        "screening": {
            "not_screened": not_screened,
            "included": included,
            "excluded": excluded,
            "borderline": borderline,
            "awaiting_full_text": awaiting,
        },
        "by_year": [{"year": y, "count": c} for y, c in year_counts],
        "by_source": [{"source": s, "count": c} for s, c in source_counts],
        "by_family": [
            {"family": f, "paper_count": c}
            for f, c in family_counts
            if f
        ],
        "search_stats": {
            "total_searches": total_searches,
            "total_retries": total_retries,
            "total_pages": total_pages,
        },
        "audit_entries": recent_audit,
        "evidence": {
            "total_claims": total_claims,
            "assessed_claims": assessed_claims,
            "direct_statistical_tests": direct_stats_count,
        },
    }
