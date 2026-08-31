"""
API Routes - PRISMA & Exports
==============================
Endpoints for PRISMA flow tracking, Excel export, and citation formats.
"""

import logging
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.engine import get_db
from app.models.paper import Paper
from app.services.prisma import PrismaService
from app.services.excel_export import ExcelExportService
from app.services.notebooklm import NotebookLMPrepService, generate_ris_citation, generate_bibtex_citation

router = APIRouter()
logger = logging.getLogger(__name__)


# --- PRISMA Endpoints ---

@router.get("/flow")
async def get_prisma_flow(db: Session = Depends(get_db)):
    """Get the complete PRISMA flow data."""
    service = PrismaService(db)
    return service.get_prisma_flow()


@router.get("/counts")
async def get_prisma_counts(db: Session = Depends(get_db)):
    """Get simplified PRISMA counts for the flow diagram."""
    service = PrismaService(db)
    return service.get_prisma_counts()


# --- Excel Export ---

@router.get("/excel")
async def export_excel(db: Session = Depends(get_db)):
    """
    Generate and download the complete Excel export.
    Returns the .xlsx file.
    """
    service = ExcelExportService(db)
    try:
        output_path = service.generate_full_export()
        return FileResponse(
            path=output_path,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=output_path.name,
        )
    except Exception as e:
        logger.error(f"Excel export failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# --- NotebookLM Batch Preparation ---

@router.post("/notebooklm-prep")
async def prepare_notebooklm(
    screening_status: str = Query("include"),
    batch_size: int = Query(50),
    db: Session = Depends(get_db),
):
    """
    Prepare PDF batches for NotebookLM upload.
    Creates organized batch folders and manifest.
    """
    service = NotebookLMPrepService(db)
    result = service.prepare_batches(
        screening_status=screening_status,
        batch_size=batch_size,
    )
    return result


# --- Citation Formats ---

@router.get("/ris")
async def export_ris(db: Session = Depends(get_db)):
    """Export all papers in RIS format."""
    papers = db.query(Paper).order_by(Paper.id).all()
    ris_content = "\n\n".join([generate_ris_citation(p) for p in papers])

    output_path = Path("data/exports/references.ris")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ris_content)

    return FileResponse(
        path=output_path,
        media_type="application/x-research-info-systems",
        filename="references.ris",
    )


@router.get("/bibtex")
async def export_bibtex(db: Session = Depends(get_db)):
    """Export all papers in BibTeX format."""
    papers = db.query(Paper).order_by(Paper.id).all()
    bibtex_content = "\n\n".join([generate_bibtex_citation(p) for p in papers])

    output_path = Path("data/exports/references.bib")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(bibtex_content)

    return FileResponse(
        path=output_path,
        media_type="application/x-bibtex",
        filename="references.bib",
    )
