"""
API Routes - PDF Management
============================
Endpoints for PDF discovery, download, status, and serving.
"""

import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from app.db.engine import get_db
from app.models.paper import Paper
from app.models.pdf_file import PdfFile
from app.services.pdf_discovery import PdfDiscoveryService
from app.services.pdf_download import PdfDownloadService

router = APIRouter()
logger = logging.getLogger(__name__)


class PdfDownloadRequest(BaseModel):
    paper_id: int
    url: str
    source: str = "manual"


# --- Discovery Endpoints ---

@router.post("/discover/{paper_id}")
async def discover_pdf(paper_id: int, db: Session = Depends(get_db)):
    """Discover PDF availability for a single paper."""
    service = PdfDiscoveryService(db)
    try:
        result = service.discover_for_paper(paper_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/discover")
async def discover_all_pdfs(
    status_filter: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Discover PDF availability for all papers.
    Optionally filter by screening status (e.g., 'include').
    """
    service = PdfDiscoveryService(db)
    results = service.discover_all(status_filter=status_filter)
    return results


# --- Download Endpoints ---

@router.post("/download")
async def download_pdf(request: PdfDownloadRequest, db: Session = Depends(get_db)):
    """
    Download a PDF for a paper from a specific URL.
    Only downloads openly accessible content.
    """
    service = PdfDownloadService(db)
    try:
        result = service.download_for_paper(
            paper_id=request.paper_id,
            url=request.url,
            source=request.source,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/download/{pdf_file_id}")
async def download_by_record(pdf_file_id: int, db: Session = Depends(get_db)):
    """Download a PDF using an existing PdfFile record ID."""
    service = PdfDownloadService(db)
    try:
        result = service.download_pdf(pdf_file_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Status Endpoints ---

@router.get("/status/{paper_id}")
async def get_pdf_status(paper_id: int, db: Session = Depends(get_db)):
    """Get PDF status for a paper."""
    service = PdfDiscoveryService(db)
    try:
        return service.get_pdf_status(paper_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/stats")
async def get_download_stats(db: Session = Depends(get_db)):
    """Get overall PDF download statistics."""
    service = PdfDownloadService(db)
    return service.get_download_stats()


@router.get("/pending")
async def list_pending_downloads(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List PDFs pending download."""
    query = db.query(PdfFile).filter(PdfFile.download_status == "pending")
    total = query.count()
    records = query.order_by(PdfFile.id).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pdfs": [
            {
                "id": r.id,
                "paper_id": r.paper_id,
                "download_url": r.download_url,
                "source": r.source,
                "download_status": r.download_status,
                "notes": r.notes,
            }
            for r in records
        ],
    }


# --- Serve Endpoint ---

@router.get("/serve/{pdf_file_id}")
async def serve_pdf(pdf_file_id: int, db: Session = Depends(get_db)):
    """
    Serve a downloaded PDF file for viewing.
    Returns the file as a response.
    """
    pdf_record = db.query(PdfFile).filter(PdfFile.id == pdf_file_id).first()
    if not pdf_record:
        raise HTTPException(status_code=404, detail="PDF record not found")

    if pdf_record.download_status != "downloaded":
        raise HTTPException(status_code=404, detail="PDF not yet downloaded")

    if not pdf_record.file_path:
        raise HTTPException(status_code=404, detail="PDF file path not recorded")

    file_path = Path(pdf_record.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found on disk")

    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        filename=file_path.name,
    )
