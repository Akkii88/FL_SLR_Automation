"""
API Routes - Papers
====================
Endpoints for viewing and managing paper records.
"""

import json
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from app.db.engine import get_db
from app.models.paper import Paper
from app.models.search_run import SourceProvenance
from app.models.pdf_file import PdfFile, PaperNote
from app.models.screening import ScreeningDecision

router = APIRouter()


class PaperSummary(BaseModel):
    id: int
    title: str
    authors: Optional[str]
    publication_year: Optional[int]
    source: Optional[str]
    doi: Optional[str]
    openalex_id: Optional[str]
    is_open_access: bool
    screening_status: str
    duplicate_status: str


class PaperDetail(PaperSummary):
    abstract: Optional[str]
    publication_date: Optional[str]
    institutions: Optional[str]
    source_type: Optional[str]
    language: Optional[str]
    citation_count: Optional[int]
    oa_status: Optional[str]
    oa_url: Optional[str]
    pdf_url: Optional[str]
    is_retracted: bool
    created_at: str
    updated_at: str


@router.get("/")
async def list_papers(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: Optional[str] = None,
    year: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """List papers with pagination and optional filters."""
    query = db.query(Paper)

    if status:
        query = query.filter(Paper.screening_status == status)
    if year:
        query = query.filter(Paper.publication_year == year)

    total = query.count()
    papers = query.order_by(Paper.id).offset((page - 1) * page_size).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "papers": [
            {
                "id": p.id,
                "title": p.title,
                "authors": p.authors,
                "publication_year": p.publication_year,
                "source": p.source,
                "doi": p.doi,
                "openalex_id": p.openalex_id,
                "is_open_access": p.is_open_access,
                "screening_status": p.screening_status,
                "duplicate_status": p.duplicate_status,
            }
            for p in papers
        ],
    }


@router.get("/{paper_id}")
async def get_paper(paper_id: int, db: Session = Depends(get_db)):
    """Get detailed information about a single paper."""
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    return {
        "id": paper.id,
        "title": paper.title,
        "normalized_title": paper.normalized_title,
        "abstract": paper.abstract,
        "authors": json.loads(paper.authors) if paper.authors else [],
        "institutions": json.loads(paper.institutions) if paper.institutions else [],
        "publication_date": paper.publication_date,
        "publication_year": paper.publication_year,
        "source": paper.source,
        "source_type": paper.source_type,
        "language": paper.language,
        "citation_count": paper.citation_count,
        "doi": paper.doi,
        "openalex_id": paper.openalex_id,
        "is_open_access": paper.is_open_access,
        "oa_status": paper.oa_status,
        "oa_url": paper.oa_url,
        "pdf_url": paper.pdf_url,
        "is_retracted": paper.is_retracted,
        "screening_status": paper.screening_status,
        "screening_decision": paper.screening_decision,
        "exclusion_reason": paper.exclusion_reason,
        "duplicate_status": paper.duplicate_status,
        "duplicate_of": paper.duplicate_of,
        "created_at": paper.created_at.isoformat() if paper.created_at else None,
        "updated_at": paper.updated_at.isoformat() if paper.updated_at else None,
        "provenance": [
            {
                "source": p.source,
                "search_family": p.search_family,
                "retrieval_timestamp": p.retrieval_timestamp.isoformat() if p.retrieval_timestamp else None,
            }
            for p in paper.provenance
        ],
        "pdf_files": [
            {
                "id": pf.id,
                "download_url": pf.download_url,
                "source": pf.source,
                "file_path": pf.file_path,
                "file_size": pf.file_size,
                "file_hash": pf.file_hash,
                "download_status": pf.download_status,
                "download_date": pf.download_date.isoformat() if pf.download_date else None,
                "notes": pf.notes,
            }
            for pf in paper.pdf_files
        ],
        "screening_history": [
            {
                "id": s.id,
                "stage": s.stage,
                "q1": s.q1_fl_comparison,
                "q2": s.q2_non_iid,
                "q3": s.q3_superiority_claim,
                "q4": s.q4_full_text_available,
                "decision": s.decision,
                "exclusion_reason": s.exclusion_reason,
                "notes": s.notes,
                "decided_by": s.decided_by,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in paper.screening_decisions
        ],
        "notes": [
            {
                "id": n.id,
                "content": n.content,
                "note_type": n.note_type,
                "page": n.page,
                "section": n.section,
                "table_ref": n.table_ref,
                "figure_ref": n.figure_ref,
                "created_at": n.created_at.isoformat() if n.created_at else None,
                "updated_at": n.updated_at.isoformat() if n.updated_at else None,
            }
            for n in paper.notes
        ],
    }


# --- Paper Notes Endpoints ---

class NoteCreate(BaseModel):
    paper_id: int
    content: str
    note_type: str = "general"
    page: Optional[int] = None
    section: Optional[str] = None
    table_ref: Optional[str] = None
    figure_ref: Optional[str] = None


class NoteUpdate(BaseModel):
    content: Optional[str] = None
    note_type: Optional[str] = None
    page: Optional[int] = None
    section: Optional[str] = None
    table_ref: Optional[str] = None
    figure_ref: Optional[str] = None


@router.post("/notes")
async def create_note(note: NoteCreate, db: Session = Depends(get_db)):
    """Create a note for a paper."""
    paper = db.query(Paper).filter(Paper.id == note.paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    new_note = PaperNote(
        paper_id=note.paper_id,
        content=note.content,
        note_type=note.note_type,
        page=note.page,
        section=note.section,
        table_ref=note.table_ref,
        figure_ref=note.figure_ref,
    )
    db.add(new_note)
    db.commit()
    db.refresh(new_note)

    return {
        "status": "created",
        "note_id": new_note.id,
        "paper_id": new_note.paper_id,
    }


@router.put("/notes/{note_id}")
async def update_note(note_id: int, update: NoteUpdate, db: Session = Depends(get_db)):
    """Update an existing note."""
    note = db.query(PaperNote).filter(PaperNote.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    if update.content is not None:
        note.content = update.content
    if update.note_type is not None:
        note.note_type = update.note_type
    if update.page is not None:
        note.page = update.page
    if update.section is not None:
        note.section = update.section
    if update.table_ref is not None:
        note.table_ref = update.table_ref
    if update.figure_ref is not None:
        note.figure_ref = update.figure_ref

    db.commit()
    return {"status": "updated", "note_id": note_id}


@router.delete("/notes/{note_id}")
async def delete_note(note_id: int, db: Session = Depends(get_db)):
    """Delete a note."""
    note = db.query(PaperNote).filter(PaperNote.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    db.delete(note)
    db.commit()
    return {"status": "deleted", "note_id": note_id}


@router.get("/{paper_id}/notes")
async def get_paper_notes(paper_id: int, db: Session = Depends(get_db)):
    """Get all notes for a paper."""
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    notes = db.query(PaperNote).filter(
        PaperNote.paper_id == paper_id
    ).order_by(PaperNote.created_at).all()

    return {
        "paper_id": paper_id,
        "total": len(notes),
        "notes": [
            {
                "id": n.id,
                "content": n.content,
                "note_type": n.note_type,
                "page": n.page,
                "section": n.section,
                "table_ref": n.table_ref,
                "figure_ref": n.figure_ref,
                "created_at": n.created_at.isoformat() if n.created_at else None,
                "updated_at": n.updated_at.isoformat() if n.updated_at else None,
            }
            for n in notes
        ],
    }
