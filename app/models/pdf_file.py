"""
PDF File Model
==============
Tracks downloaded PDF files and their metadata.
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey
)
from sqlalchemy.orm import relationship
from app.db.engine import Base


class PdfFile(Base):
    """Records a downloaded PDF file for a paper."""

    __tablename__ = "pdf_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False)

    # --- Source ---
    download_url = Column(String(2048), nullable=True)
    source = Column(String(64), nullable=True)  # OpenAlex cached, OA URL, etc.

    # --- File Info ---
    file_path = Column(String(1024), nullable=True)
    file_hash = Column(String(128), nullable=True)  # SHA-256
    file_size = Column(Integer, nullable=True)  # bytes

    # --- Status ---
    download_status = Column(
        String(64),
        default="pending"
    )  # pending, downloaded, failed, invalid

    download_date = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    paper = relationship("Paper", back_populates="pdf_files")


class PaperNote(Base):
    """
    Researcher notes associated with a paper.
    Can be linked to specific locations (page, section, table, figure).
    """

    __tablename__ = "paper_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False)

    # --- Note content ---
    content = Column(Text, nullable=False)
    note_type = Column(String(64), default="general")
    # general, method, result, limitation, decision, evidence, code, other

    # --- Location reference (optional) ---
    page = Column(Integer, nullable=True)
    section = Column(String(255), nullable=True)
    table_ref = Column(String(128), nullable=True)
    figure_ref = Column(String(128), nullable=True)

    # --- Metadata ---
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    paper = relationship("Paper", back_populates="notes")
