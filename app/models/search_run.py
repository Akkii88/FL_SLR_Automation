"""
Search Run & Provenance Models
===============================
Tracks every search operation and which papers came from which search.
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime,
    ForeignKey, Index, Float
)
from sqlalchemy.orm import relationship
from app.db.engine import Base


class SearchRun(Base):
    """Records a single search operation (one query against one source)."""

    __tablename__ = "search_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # --- Search Identity ---
    source = Column(String(64), nullable=False)  # OpenAlex, Semantic Scholar, etc.
    search_family = Column(String(16), nullable=False)  # A, B, C, D, E, F
    exact_query = Column(Text, nullable=False)

    # --- Timestamps ---
    search_date = Column(DateTime, nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=True)

    # --- Filters ---
    year_filter = Column(String(128), nullable=True)
    document_filter = Column(String(255), nullable=True)

    # --- Results ---
    total_matching_count = Column(Integer, nullable=True)  # OpenAlex meta.count (NULL if unavailable)
    results_retrieved = Column(Integer, default=0)  # Total records yielded by OpenAlex
    records_parsed = Column(Integer, default=0)  # Records successfully parsed
    records_failed = Column(Integer, default=0)  # Records that failed parsing
    records_deduplicated = Column(Integer, default=0)  # Records skipped as duplicates
    records_saved = Column(Integer, default=0)  # New records saved to database
    pages_retrieved = Column(Integer, default=0)
    duration_seconds = Column(Float, nullable=True)

    # --- Errors & Diagnostics ---
    errors = Column(Text, nullable=True)  # JSON-serialized error list
    retries = Column(Integer, default=0)
    notes = Column(Text, nullable=True)

    # --- Software Version ---
    software_version = Column(String(32), nullable=True)
    config_version = Column(String(32), nullable=True)

    # --- Timestamps ---
    created_at = Column(DateTime, default=datetime.utcnow)

    # --- Relationships ---
    papers = relationship("SearchRunPaper", back_populates="search_run")

    __table_args__ = (
        Index("ix_search_runs_family", "search_family", "source"),
    )

    def __repr__(self):
        return f"<SearchRun(id={self.id}, family={self.search_family}, source={self.source})>"


class SourceProvenance(Base):
    """Links a paper to its discovery source(s). Many-to-many via search runs."""

    __tablename__ = "source_provenance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False)
    source = Column(String(64), nullable=False)
    search_family = Column(String(16), nullable=True)
    retrieval_timestamp = Column(DateTime, nullable=False)

    paper = relationship("Paper", back_populates="provenance")


class SearchRunPaper(Base):
    """Association table: which papers were found by which search runs."""

    __tablename__ = "search_run_papers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    search_run_id = Column(Integer, ForeignKey("search_runs.id"), nullable=False)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    search_run = relationship("SearchRun", back_populates="papers")
    paper = relationship("Paper", back_populates="search_runs")
