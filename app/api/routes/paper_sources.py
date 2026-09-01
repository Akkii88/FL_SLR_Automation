"""
API Routes - Paper Sources
============================
Endpoints for accessing paper source links and full-text availability.
"""

import logging
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session

from app.db.engine import get_db
from app.models.paper import Paper
from app.models.pdf_file import PdfFile
from app.models.search_run import SourceProvenance

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/source-stats")
async def get_source_stats(db: Session = Depends(get_db)):
    """
    Get statistics about source availability across all papers.
    Useful for planning full-text screening.
    """
    from sqlalchemy import func, case

    total = db.query(func.count(Paper.id)).scalar()

    # Count by source type
    with_doi = db.query(func.count(Paper.id)).filter(
        Paper.doi.isnot(None), Paper.doi != ""
    ).scalar()

    with_oa = db.query(func.count(Paper.id)).filter(Paper.is_open_access == True).scalar()

    with_pdf_url = db.query(func.count(Paper.id)).filter(
        Paper.pdf_url.isnot(None), Paper.pdf_url != ""
    ).scalar()

    # Downloaded PDFs
    downloaded = db.query(func.count(func.distinct(PdfFile.paper_id))).filter(
        PdfFile.download_status == "downloaded"
    ).scalar()

    # OA status breakdown
    oa_status_counts = db.query(
        Paper.oa_status,
        func.count(Paper.id)
    ).group_by(Paper.oa_status).all()

    return {
        "total_papers": total,
        "with_doi": with_doi,
        "with_open_access": with_oa,
        "with_pdf_url": with_pdf_url,
        "pdf_downloaded": downloaded,
        "without_source": total - max(with_doi, with_oa, with_pdf_url),
        "oa_status_breakdown": [
            {"status": s or "unknown", "count": c} for s, c in oa_status_counts
        ],
    }


@router.get("/{paper_id}/sources")
async def get_paper_sources(paper_id: int, db: Session = Depends(get_db)):
    """
    Get all source links and access information for a paper.

    Returns only non-sensitive source metadata.
    Never exposes API keys or credentials.
    """
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Build source links (only include if URL actually exists)
    sources = {
        "doi": None,
        "doi_url": None,
        "openalex_id": None,
        "openalex_url": None,
        "publisher_url": None,
        "oa_url": None,
        "pdf_url": None,
        "pdf_available": False,
        "pdf_downloaded": False,
        "best_oa_location": None,
        "source_type": None,
    }

    # DOI
    if paper.doi:
        sources["doi"] = paper.doi
        sources["doi_url"] = f"https://doi.org/{paper.doi}"

    # OpenAlex
    if paper.openalex_id:
        sources["openalex_id"] = paper.openalex_id
        # Extract the work ID from full URL if needed
        oa_id = paper.openalex_id
        if oa_id.startswith("http"):
            oa_id = oa_id.rstrip("/").split("/")[-1]
        sources["openalex_url"] = f"https://openalex.org/{oa_id}"

    # OA URL
    if paper.oa_url:
        sources["oa_url"] = paper.oa_url

    # Best OA location
    if paper.best_oa_location:
        sources["best_oa_location"] = paper.best_oa_location

    # PDF URL
    if paper.pdf_url:
        sources["pdf_url"] = paper.pdf_url
        sources["pdf_available"] = True

    # Check if PDF has been downloaded
    downloaded_pdf = db.query(PdfFile).filter(
        PdfFile.paper_id == paper_id,
        PdfFile.download_status == "downloaded",
    ).first()
    if downloaded_pdf:
        sources["pdf_downloaded"] = True
        sources["local_pdf_path"] = downloaded_pdf.file_path

    # Determine primary source type
    if paper.pdf_url:
        sources["source_type"] = "open_access_pdf"
    elif paper.oa_url:
        sources["source_type"] = "open_access_page"
    elif paper.doi:
        sources["source_type"] = "doi"
    elif paper.openalex_id:
        sources["source_type"] = "openalex_only"
    else:
        sources["source_type"] = "metadata_only"

    # Build response
    return {
        "paper_id": paper.id,
        "title": paper.title,
        "authors": paper.authors,
        "year": paper.publication_year,
        "venue": paper.source,
        "doi": paper.doi,
        "is_open_access": paper.is_open_access,
        "oa_status": paper.oa_status,
        "sources": sources,
        # Convenient link array for UI (only includes available links)
        "links": _build_links_array(sources),
    }


def _build_links_array(sources: dict) -> list:
    """Build a convenient array of available links for the UI."""
    links = []

    if sources.get("pdf_url"):
        links.append({
            "type": "pdf",
            "label": "📄 PDF",
            "url": sources["pdf_url"],
            "priority": 1,
        })

    if sources.get("oa_url"):
        links.append({
            "type": "oa",
            "label": "🟢 Open Access",
            "url": sources["oa_url"],
            "priority": 2,
        })

    if sources.get("doi_url"):
        links.append({
            "type": "doi",
            "label": "🔗 DOI",
            "url": sources["doi_url"],
            "priority": 3,
        })

    if sources.get("openalex_url"):
        links.append({
            "type": "openalex",
            "label": "🔎 OpenAlex",
            "url": sources["openalex_url"],
            "priority": 4,
        })

    # Sort by priority
    links.sort(key=lambda x: x["priority"])

    return links


@router.get("/source-stats")
async def get_source_stats(db: Session = Depends(get_db)):
    """
    Get statistics about source availability across all papers.
    Useful for planning full-text screening.
    """
    from sqlalchemy import func, case

    total = db.query(func.count(Paper.id)).scalar()

    # Count by source type
    with_doi = db.query(func.count(Paper.id)).filter(
        Paper.doi.isnot(None), Paper.doi != ""
    ).scalar()

    with_oa = db.query(func.count(Paper.id)).filter(Paper.is_open_access == True).scalar()

    with_pdf_url = db.query(func.count(Paper.id)).filter(
        Paper.pdf_url.isnot(None), Paper.pdf_url != ""
    ).scalar()

    # Downloaded PDFs
    downloaded = db.query(func.count(func.distinct(PdfFile.paper_id))).filter(
        PdfFile.download_status == "downloaded"
    ).scalar()

    # OA status breakdown
    oa_status_counts = db.query(
        Paper.oa_status,
        func.count(Paper.id)
    ).group_by(Paper.oa_status).all()

    return {
        "total_papers": total,
        "with_doi": with_doi,
        "with_open_access": with_oa,
        "with_pdf_url": with_pdf_url,
        "pdf_downloaded": downloaded,
        "without_source": total - max(with_doi, with_oa, with_pdf_url),
        "oa_status_breakdown": [
            {"status": s or "unknown", "count": c} for s, c in oa_status_counts
        ],
    }
