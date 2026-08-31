"""
Screening & Audit Models
=========================
Tracks screening decisions and the immutable audit trail.
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime,
    ForeignKey, Index
)
from sqlalchemy.orm import relationship
from app.db.engine import Base


class ScreeningDecision(Base):
    """Records each screening decision event (supports history of changes)."""

    __tablename__ = "screening_decisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False)

    # --- Screening Stage ---
    stage = Column(String(32), nullable=False)  # title_abstract, full_text

    # --- Screening Questions ---
    q1_fl_comparison = Column(String(32), nullable=True)  # YES, NO, UNCLEAR
    q2_non_iid = Column(String(32), nullable=True)
    q3_superiority_claim = Column(String(32), nullable=True)
    q4_full_text_available = Column(String(32), nullable=True)

    # --- Decision ---
    decision = Column(String(64), nullable=True)  # include, exclude, borderline, awaiting_full_text
    exclusion_reason = Column(String(255), nullable=True)

    # --- LLM Assistance (future) ---
    llm_recommendation = Column(String(64), nullable=True)
    llm_reason = Column(Text, nullable=True)
    llm_model = Column(String(128), nullable=True)
    llm_timestamp = Column(DateTime, nullable=True)
    human_override_reason = Column(Text, nullable=True)

    # --- Metadata ---
    decided_by = Column(String(64), default="user")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    paper = relationship("Paper", back_populates="screening_decisions")

    __table_args__ = (
        Index("ix_screening_paper_stage", "paper_id", "stage"),
    )


class AuditLog(Base):
    """
    Immutable audit trail.
    Records every important action for reproducibility.
    """

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # --- What happened ---
    action = Column(String(128), nullable=False)
    entity_type = Column(String(64), nullable=False)  # paper, search_run, screening, config
    entity_id = Column(Integer, nullable=True)

    # --- Details ---
    description = Column(Text, nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)

    # --- Who ---
    actor = Column(String(64), nullable=False)  # user, system

    # --- When ---
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    # --- Optional link to paper ---
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=True)
    paper = relationship("Paper", back_populates="audit_logs")

    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id"),
        Index("ix_audit_timestamp", "timestamp"),
    )

    def __repr__(self):
        return f"<AuditLog(id={self.id}, action='{self.action}', actor='{self.actor}')>"
