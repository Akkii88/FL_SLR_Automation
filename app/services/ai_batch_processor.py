"""
AI Screening Batch Processor
==============================
Processes AI screening batches asynchronously in the background.

Key design:
- batch-screen endpoint creates a job and returns immediately
- Background thread processes papers one at a time
- Each paper commits independently
- Progress is tracked in the database
- Frontend polls for progress
"""

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.db.engine import SessionLocal
from app.models.paper import Paper
from app.models.ai_screening import AIScreeningResult
from app.models.ai_batch import AIScreeningBatch
from app.models.screening import AuditLog
from app.services.ai_screening import AIScreeningService

logger = logging.getLogger(__name__)

# Active batch jobs (in-memory tracking)
_active_batches = {}
_batch_lock = threading.Lock()


def start_batch(batch_size: int = 25, requested_by: str = "user") -> AIScreeningBatch:
    """
    Start a new AI screening batch job.
    Creates the batch record and launches a background thread.
    Returns the batch record immediately.
    """
    # Reset provider status for new batch
    from app.services.llm_manager import reset_provider_status
    reset_provider_status()

    db = SessionLocal()
    try:
        # Create batch record
        batch = AIScreeningBatch(
            status="pending",
            batch_size=batch_size,
            requested_by=requested_by,
        )
        db.add(batch)
        db.commit()
        db.refresh(batch)

        # Start background thread
        thread = threading.Thread(
            target=_process_batch,
            args=(batch.id, batch_size),
            daemon=True,
            name=f"ai-batch-{batch.id}",
        )

        with _batch_lock:
            _active_batches[batch.id] = {
                "thread": thread,
                "cancelled": False,
            }

        thread.start()
        logger.info(f"Started AI screening batch {batch.id} (size={batch_size})")

        return batch

    finally:
        db.close()


def cancel_batch(batch_id: int) -> bool:
    """Cancel a running batch job."""
    with _batch_lock:
        if batch_id in _active_batches:
            _active_batches[batch_id]["cancelled"] = True
            logger.info(f"Cancelled AI screening batch {batch_id}")
            return True
    return False


def get_batch_status(batch_id: int) -> Optional[dict]:
    """Get the current status of a batch job."""
    db = SessionLocal()
    try:
        batch = db.query(AIScreeningBatch).filter(AIScreeningBatch.id == batch_id).first()
        if not batch:
            return None
        return batch.to_dict()
    finally:
        db.close()


def list_batches(limit: int = 10) -> list:
    """List recent batch jobs."""
    db = SessionLocal()
    try:
        batches = db.query(AIScreeningBatch).order_by(
            AIScreeningBatch.created_at.desc()
        ).limit(limit).all()
        return [b.to_dict() for b in batches]
    finally:
        db.close()


def _process_batch(batch_id: int, batch_size: int):
    """
    Background worker that processes papers for a batch.
    Each paper is processed and committed independently.
    """
    db = SessionLocal()
    service = AIScreeningService(db)

    try:
        # Mark batch as running
        batch = db.query(AIScreeningBatch).filter(AIScreeningBatch.id == batch_id).first()
        if not batch:
            logger.error(f"Batch {batch_id} not found")
            return

        batch.status = "running"
        batch.started_at = datetime.now(timezone.utc)
        db.commit()

        # Find papers that haven't been AI-screened yet
        already_screened = db.query(AIScreeningResult.paper_id).filter(
            AIScreeningResult.is_active == True,
        ).subquery()

        papers = db.query(Paper).filter(
            ~Paper.id.in_(already_screened)
        ).order_by(Paper.id).limit(batch_size).all()

        batch.total_papers = len(papers)
        db.commit()

        if not papers:
            batch.status = "completed"
            batch.finished_at = datetime.now(timezone.utc)
            db.commit()
            return

        request_delay = 0.5  # seconds between requests

        for i, paper in enumerate(papers):
            # Check if cancelled
            with _batch_lock:
                if _active_batches.get(batch_id, {}).get("cancelled", False):
                    batch.status = "cancelled"
                    batch.finished_at = datetime.now(timezone.utc)
                    db.commit()
                    logger.info(f"Batch {batch_id} cancelled at paper {paper.id}")
                    return

            batch.current_paper_id = paper.id
            db.commit()

            try:
                # Pace requests
                if i > 0 and request_delay > 0:
                    time.sleep(request_delay)

                # Process single paper (uses retry logic internally)
                result = service.screen_paper(paper.id, use_cache=False)
                batch.processed += 1
                batch.llm_calls += 1

                if result.processing_status == "completed":
                    batch.succeeded += 1
                else:
                    batch.failed += 1

                db.commit()

                logger.info(
                    f"Batch {batch_id}: paper {paper.id} "
                    f"({i+1}/{len(papers)}) -> {result.processing_status}"
                )

            except Exception as e:
                batch.processed += 1
                batch.failed += 1
                db.commit()
                logger.error(f"Batch {batch_id}: paper {paper.id} failed: {e}")

        # Mark batch as completed
        batch.status = "completed"
        batch.finished_at = datetime.now(timezone.utc)
        batch.current_paper_id = None
        db.commit()

        logger.info(
            f"Batch {batch_id} completed: {batch.succeeded} succeeded, "
            f"{batch.failed} failed, {batch.processed} total"
        )

    except Exception as e:
        logger.error(f"Batch {batch_id} failed with exception: {e}")
        try:
            batch = db.query(AIScreeningBatch).filter(AIScreeningBatch.id == batch_id).first()
            if batch:
                batch.status = "failed"
                batch.error_message = str(e)
                batch.finished_at = datetime.now(timezone.utc)
                db.commit()
        except:
            pass

    finally:
        with _batch_lock:
            _active_batches.pop(batch_id, None)
        db.close()
