"""
Paper Model
===========
Represents a bibliographic record collected from any source.
Each paper is a unique bibliographic entity (by DOI or OpenAlex ID).
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime,
    Float, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship
from app.db.engine import Base


class Paper(Base):
    """A bibliographic record for a single work."""

    __tablename__ = "papers"

    # --- Primary Key ---
    id = Column(Integer, primary_key=True, autoincrement=True)

    # --- OpenAlex Identifiers ---
    openalex_id = Column(String(255), unique=True, nullable=True, index=True)
    doi = Column(String(512), unique=True, nullable=True, index=True)

    # --- Bibliographic Metadata ---
    title = Column(Text, nullable=False)
    normalized_title = Column(String(1024), nullable=True, index=True)
    abstract = Column(Text, nullable=True)
    publication_date = Column(String(64), nullable=True)
    publication_year = Column(Integer, nullable=True, index=True)

    # --- Authors & Institutions ---
    authors = Column(Text, nullable=True)  # JSON-serialized list of author names
    institutions = Column(Text, nullable=True)  # JSON-serialized list

    # --- Source / Venue ---
    source = Column(String(512), nullable=True)  # journal/conference name
    source_type = Column(String(64), nullable=True)  # work type
    language = Column(String(16), nullable=True)

    # --- Metrics ---
    citation_count = Column(Integer, nullable=True)

    # --- Open Access ---
    is_open_access = Column(Boolean, default=False)
    oa_status = Column(String(64), nullable=True)
    oa_url = Column(String(2048), nullable=True)
    best_oa_location = Column(String(2048), nullable=True)
    pdf_url = Column(String(2048), nullable=True)

    # --- Quality Flags ---
    is_retracted = Column(Boolean, default=False)

    # --- Deduplication ---
    canonical_record_id = Column(Integer, nullable=True, index=True)
    duplicate_of = Column(Integer, nullable=True)
    duplicate_reason = Column(String(255), nullable=True)
    duplicate_confidence = Column(Float, nullable=True)
    duplicate_status = Column(
        String(64),
        default="unique",
        index=True
    )  # unique, probable_duplicate, confirmed_duplicate, manually_retained

    # --- Screening ---
    screening_status = Column(
        String(64),
        default="not_screened",
        index=True
    )  # not_screened, include, exclude, borderline, awaiting_full_text, duplicate
    screening_decision = Column(String(64), nullable=True)
    exclusion_reason = Column(String(255), nullable=True)
    screening_notes = Column(Text, nullable=True)

    # --- Timestamps ---
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # --- Relationships ---
    provenance = relationship("SourceProvenance", back_populates="paper", cascade="all, delete-orphan")
    search_runs = relationship("SearchRunPaper", back_populates="paper")
    pdf_files = relationship("PdfFile", back_populates="paper", cascade="all, delete-orphan")
    screening_decisions = relationship("ScreeningDecision", back_populates="paper", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="paper", cascade="all, delete-orphan")
    dedup_logs_a = relationship("DeduplicationLog", foreign_keys="DeduplicationLog.paper_id_a", cascade="all, delete-orphan")
    dedup_logs_b = relationship("DeduplicationLog", foreign_keys="DeduplicationLog.paper_id_b", cascade="all, delete-orphan")
    notes = relationship("PaperNote", back_populates="paper", cascade="all, delete-orphan")
    claims = relationship("Claim", back_populates="paper", cascade="all, delete-orphan")
    ai_screening_results = relationship("AIScreeningResult", back_populates="paper", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_papers_year_status", "publication_year", "screening_status"),
    )

    def __repr__(self):
        return f"<Paper(id={self.id}, title='{self.title[:50]}...', year={self.publication_year})>"
