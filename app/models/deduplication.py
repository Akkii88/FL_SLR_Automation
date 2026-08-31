"""
Deduplication Log Model
========================
Tracks every deduplication decision for auditability.
Every duplicate pair found, confirmed, or overridden is recorded here.
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime,
    ForeignKey, Float, Boolean, Index
)
from sqlalchemy.orm import relationship
from app.db.engine import Base


class DeduplicationLog(Base):
    """
    Records a deduplication decision event.
    Each time two papers are compared and a decision is made, we log it.
    """

    __tablename__ = "deduplication_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # --- The two papers being compared ---
    paper_id_a = Column(Integer, ForeignKey("papers.id"), nullable=False)
    paper_id_b = Column(Integer, ForeignKey("papers.id"), nullable=False)

    # --- Decision ---
    match_type = Column(String(64), nullable=False)
    # doi_exact, openalex_id_exact, title_year_exact, fuzzy_title, author_year

    match_confidence = Column(Float, nullable=False)
    # 1.0 = exact match, 0.0-1.0 = fuzzy confidence

    match_status = Column(String(64), nullable=False)
    # auto_detected, confirmed_duplicate, rejected_not_duplicate, manually_overridden

    # --- Resolution ---
    # Which paper is canonical (the one we keep as primary)
    canonical_paper_id = Column(Integer, nullable=True)
    # Which paper is the duplicate (the one that references the canonical)
    duplicate_paper_id = Column(Integer, nullable=True)

    # --- Override ---
    is_override = Column(Boolean, default=False)
    override_reason = Column(Text, nullable=True)
    overridden_by = Column(String(64), nullable=True)

    # --- Who / When ---
    actor = Column(String(64), default="system")  # system, user
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # --- Relationships ---
    paper_a = relationship("Paper", foreign_keys=[paper_id_a])
    paper_b = relationship("Paper", foreign_keys=[paper_id_b])

    __table_args__ = (
        Index("ix_dedup_log_papers", "paper_id_a", "paper_id_b"),
        Index("ix_dedup_log_status", "match_status"),
        Index("ix_dedup_log_type", "match_type"),
    )

    def __repr__(self):
        return (
            f"<DeduplicationLog(id={self.id}, "
            f"A={self.paper_id_a}, B={self.paper_id_b}, "
            f"type={self.match_type}, confidence={self.match_confidence})>"
        )
