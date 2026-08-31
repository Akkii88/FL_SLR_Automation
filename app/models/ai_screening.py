"""
AI Screening Model
===================
Stores AI-assisted first-pass screening results separately from human decisions.
Supports caching, batch processing, and full audit trail.
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime,
    ForeignKey, Float, Boolean, Index, UniqueConstraint
)
from sqlalchemy.orm import relationship
from app.db.engine import Base


class AIScreeningResult(Base):
    """
    AI-generated screening assessment for a paper.
    
    This stores the LLM's recommendation separately from the human decision.
    The same paper can have multiple AI screening records (e.g., if re-screened
    with a different model), but only one should be 'active' at a time.
    """

    __tablename__ = "ai_screening_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False)

    # --- Screening Questions ---
    q1_fl_comparison = Column(String(32), nullable=True)  # YES, NO, UNCLEAR
    q2_non_iid = Column(String(32), nullable=True)
    q3_superiority_claim = Column(String(32), nullable=True)
    q4_info_available = Column(String(32), nullable=True)

    # --- AI Assessment ---
    recommendation = Column(String(32), nullable=True)  # likely_include, likely_exclude, unclear
    confidence = Column(String(16), nullable=True)  # high, medium, low
    reasoning = Column(Text, nullable=True)

    # --- Evidence ---
    q1_evidence = Column(Text, nullable=True)
    q2_evidence = Column(Text, nullable=True)
    q3_evidence = Column(Text, nullable=True)
    q4_evidence = Column(Text, nullable=True)

    # --- LLM Metadata ---
    model = Column(String(128), nullable=True)
    provider = Column(String(64), nullable=True)
    prompt_version = Column(String(32), default="1.0")

    # --- Cache Control ---
    is_active = Column(Boolean, default=True)  # Most recent result for this paper
    is_cached = Column(Boolean, default=False)  # Whether this was served from cache

    # --- Processing Status ---
    processing_status = Column(
        String(32),
        default="pending"
    )  # pending, processing, completed, failed

    error_message = Column(Text, nullable=True)

    # --- Timestamps ---
    created_at = Column(DateTime, default=datetime.utcnow)

    # --- Relationships ---
    paper = relationship("Paper", back_populates="ai_screening_results")

    __table_args__ = (
        Index("ix_ai_screening_paper", "paper_id"),
        Index("ix_ai_screening_active", "paper_id", "is_active"),
        Index("ix_ai_screening_status", "processing_status"),
    )

    def __repr__(self):
        return (
            f"<AIScreeningResult(id={self.id}, paper={self.paper_id}, "
            f"rec={self.recommendation}, conf={self.confidence})>"
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "paper_id": self.paper_id,
            "q1_fl_comparison": self.q1_fl_comparison,
            "q2_non_iid": self.q2_non_iid,
            "q3_superiority_claim": self.q3_superiority_claim,
            "q4_info_available": self.q4_info_available,
            "recommendation": self.recommendation,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "q1_evidence": self.q1_evidence,
            "q2_evidence": self.q2_evidence,
            "q3_evidence": self.q3_evidence,
            "q4_evidence": self.q4_evidence,
            "model": self.model,
            "provider": self.provider,
            "prompt_version": self.prompt_version,
            "is_active": self.is_active,
            "processing_status": self.processing_status,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
