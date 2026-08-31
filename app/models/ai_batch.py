"""
AI Screening Batch Job Model
=============================
Tracks batch screening jobs for async processing.
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Float, Boolean
)
from sqlalchemy.orm import relationship
from app.db.engine import Base


class AIScreeningBatch(Base):
    """
    Tracks an AI screening batch job.
    Batches are processed in the background so HTTP requests don't block.
    """

    __tablename__ = "ai_screening_batches"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # --- Job Identity ---
    status = Column(String(32), default="pending")
    # pending, running, completed, failed, cancelled

    # --- Configuration ---
    batch_size = Column(Integer, nullable=False)
    requested_by = Column(String(64), default="user")

    # --- Progress ---
    total_papers = Column(Integer, default=0)
    processed = Column(Integer, default=0)
    succeeded = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    current_paper_id = Column(Integer, nullable=True)

    # --- Statistics ---
    llm_calls = Column(Integer, default=0)
    retries = Column(Integer, default=0)
    rate_limit_waits = Column(Integer, default=0)

    # --- Timestamps ---
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    last_progress_at = Column(DateTime, nullable=True)  # Heartbeat
    created_at = Column(DateTime, default=datetime.utcnow)

    # --- Error ---
    error_message = Column(Text, nullable=True)

    # --- Recovery ---
    worker_pid = Column(String(64), nullable=True)  # Process/thread identifier
    is_recoverable = Column(Boolean, default=True)  # Can this batch be resumed?

    def __repr__(self):
        return (
            f"<AIScreeningBatch(id={self.id}, status={self.status}, "
            f"processed={self.processed}/{self.total_papers})>"
        )

    def to_dict(self) -> dict:
        duration = None
        if self.started_at and self.finished_at:
            duration = (self.finished_at - self.started_at).total_seconds()
        elif self.started_at:
            duration = (datetime.utcnow() - self.started_at).total_seconds()

        return {
            "id": self.id,
            "status": self.status,
            "batch_size": self.batch_size,
            "total_papers": self.total_papers,
            "processed": self.processed,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "current_paper_id": self.current_paper_id,
            "llm_calls": self.llm_calls,
            "retries": self.retries,
            "rate_limit_waits": self.rate_limit_waits,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "last_progress_at": self.last_progress_at.isoformat() if self.last_progress_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "duration_seconds": duration,
            "error_message": self.error_message,
            "worker_pid": self.worker_pid,
            "is_recoverable": self.is_recoverable,
        }
