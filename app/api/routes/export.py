"""
API Routes - Export
====================
Endpoints for exporting data in various formats (CSV, JSON).
"""

import io
import csv
import json
import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional

from app.db.engine import get_db
from app.models.paper import Paper
from app.models.search_run import SearchRun, SourceProvenance
from app.models.screening import ScreeningDecision, AuditLog

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/search-log")
async def export_search_log(format: str = "json", db: Session = Depends(get_db)):
    """
    Export the search log.
    Format: 'json' or 'csv'
    """
    runs = db.query(SearchRun).order_by(SearchRun.search_date.desc()).all()

    data = [
        {
            "search_id": r.id,
            "source": r.source,
            "search_family": r.search_family,
            "exact_query": r.exact_query,
            "search_date": r.search_date.isoformat() if r.search_date else "",
            "start_time": r.start_time.isoformat() if r.start_time else "",
            "end_time": r.end_time.isoformat() if r.end_time else "",
            "year_filter": r.year_filter or "",
            "document_filter": r.document_filter or "",
            "results_retrieved": r.results_retrieved,
            "records_saved": r.records_saved,
            "pages_retrieved": r.pages_retrieved,
            "duration_seconds": r.duration_seconds or 0,
            "errors": r.errors or "",
            "retries": r.retries,
            "notes": r.notes or "",
        }
        for r in runs
    ]

    if format.lower() == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=data[0].keys() if data else [])
        writer.writeheader()
        writer.writerows(data)
        output.seek(0)
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode()),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=search_log.csv"},
        )

    return {"search_log": data, "count": len(data)}


@router.get("/candidates")
async def export_candidates(format: str = "json", db: Session = Depends(get_db)):
    """
    Export master candidate list (all papers).
    Format: 'json' or 'csv'
    """
    papers = db.query(Paper).order_by(Paper.id).all()

    data = [
        {
            "id": p.id,
            "openalex_id": p.openalex_id or "",
            "doi": p.doi or "",
            "title": p.title,
            "authors": p.authors or "",
            "publication_year": p.publication_year or "",
            "source": p.source or "",
            "is_open_access": p.is_open_access,
            "oa_status": p.oa_status or "",
            "pdf_url": p.pdf_url or "",
            "citation_count": p.citation_count or 0,
            "screening_status": p.screening_status,
            "screening_decision": p.screening_decision or "",
            "exclusion_reason": p.exclusion_reason or "",
            "duplicate_status": p.duplicate_status,
            "duplicate_of": p.duplicate_of or "",
            "search_families": ", ".join(
                set(
                    prov.search_family
                    for prov in p.provenance
                    if prov.search_family
                )
            ),
        }
        for p in papers
    ]

    if format.lower() == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=data[0].keys() if data else [])
        writer.writeheader()
        writer.writerows(data)
        output.seek(0)
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode()),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=candidates.csv"},
        )

    return {"candidates": data, "count": len(data)}


@router.get("/audit-log")
async def export_audit_log(format: str = "json", db: Session = Depends(get_db)):
    """
    Export the audit log.
    Format: 'json' or 'csv'
    """
    logs = db.query(AuditLog).order_by(AuditLog.timestamp).all()

    data = [
        {
            "id": log.id,
            "timestamp": log.timestamp.isoformat() if log.timestamp else "",
            "action": log.action,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id or "",
            "description": log.description,
            "old_value": log.old_value or "",
            "new_value": log.new_value or "",
            "actor": log.actor,
            "paper_id": log.paper_id or "",
        }
        for log in logs
    ]

    if format.lower() == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=data[0].keys() if data else [])
        writer.writeheader()
        writer.writerows(data)
        output.seek(0)
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode()),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=audit_log.csv"},
        )

    return {"audit_log": data, "count": len(data)}


@router.get("/screening-results")
async def export_screening_results(format: str = "json", db: Session = Depends(get_db)):
    """
    Export screening results with all decisions and question answers.
    Format: 'json' or 'csv'
    """
    decisions = (
        db.query(ScreeningDecision)
        .order_by(ScreeningDecision.paper_id, ScreeningDecision.created_at)
        .all()
    )

    data = [
        {
            "decision_id": d.id,
            "paper_id": d.paper_id,
            "stage": d.stage,
            "q1_fl_comparison": d.q1_fl_comparison or "",
            "q2_non_iid": d.q2_non_iid or "",
            "q3_superiority_claim": d.q3_superiority_claim or "",
            "q4_full_text_available": d.q4_full_text_available or "",
            "decision": d.decision or "",
            "exclusion_reason": d.exclusion_reason or "",
            "notes": d.notes or "",
            "decided_by": d.decided_by,
            "created_at": d.created_at.isoformat() if d.created_at else "",
        }
        for d in decisions
    ]

    if format.lower() == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=data[0].keys() if data else [])
        writer.writeheader()
        writer.writerows(data)
        output.seek(0)
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode()),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=screening_results.csv"},
        )

    return {"screening_results": data, "count": len(data)}


@router.get("/claims")
async def export_claims(format: str = "json", db: Session = Depends(get_db)):
    """
    Export all claims with evidence quality data.
    Format: 'json' or 'csv'
    """
    from app.models.extraction import Claim, EvidenceQuality

    claims = db.query(Claim).order_by(Claim.paper_id, Claim.id).all()

    data = []
    for claim in claims:
        eq = db.query(EvidenceQuality).filter(EvidenceQuality.claim_id == claim.id).first()
        data.append({
            "claim_id": claim.id,
            "paper_id": claim.paper_id,
            "claim_text": claim.claim_text or "",
            "claim_scope": claim.claim_scope or "",
            "winner_algorithm": claim.winner_algorithm or "",
            "non_iid_type": claim.non_iid_type or "",
            "partition_method": claim.partition_method or "",
            "heterogeneity_param": claim.heterogeneity_param or "",
            "evidence_page": claim.evidence_page or "",
            "evidence_section": claim.evidence_section or "",
            "evidence_table": claim.evidence_table or "",
            "evidence_figure": claim.evidence_figure or "",
            "direct_statistical_test": eq.direct_statistical_test if eq else "",
            "uncertainty_reporting": eq.uncertainty_reporting if eq else "",
            "ranking_robustness": eq.ranking_robustness if eq else "",
            "independent_runs": eq.independent_runs if eq else "",
            "effect_size_reported": eq.effect_size_reported if eq else "",
            "author_claim_vs_evidence": eq.author_claim_vs_evidence if eq else "",
        })

    if format.lower() == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=data[0].keys() if data else [])
        writer.writeheader()
        writer.writerows(data)
        output.seek(0)
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode()),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=claims.csv"},
        )

    return {"claims": data, "count": len(data)}
