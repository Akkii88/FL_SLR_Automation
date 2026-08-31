"""
AI Screening Batch Processor (Persistent/Recoverable)
======================================================
Processes AI screening batches with database-backed state.

Key improvements over previous version:
- Persistent batch state survives server restarts
- Heartbeat tracking for stale worker detection
- Startup recovery for interrupted batches
- Papers claim-based processing (no in-memory paper list)
- Each paper commits independently
- Stale processing papers are recoverable
"""

import logging
import threading
import time
import os
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.db.engine import SessionLocal
from app.models.paper import Paper
from app.models.ai_screening import AIScreeningResult
from app.models.ai_batch import AIScreeningBatch
from app.services.ai_screening import AIScreeningService

logger = logging.getLogger(__name__)

# Active batch jobs (in-memory tracking)
_active_batches = {}
_batch_lock = threading.Lock()

# Stale worker timeout (seconds without progress)
STALE_WORKER_TIMEOUT = 120  # 2 minutes


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
            is_recoverable=True,
        )
        db.add(batch)
        db.commit()
        db.refresh(batch)

        # Start background thread
        thread = threading.Thread(
            target=_process_batch_persistent,
            args=(batch.id,),
            daemon=True,
            name=f"ai-batch-{batch.id}",
        )

        with _batch_lock:
            _active_batches[batch.id] = {
                "thread": thread,
                "cancelled": False,
                "pid": str(os.getpid()),
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


def recover_interrupted_batches(db_session=None):
    """
    Called on application startup.
    Detects and recovers batches that were running when the server stopped.
    """
    if db_session is None:
        db_session = SessionLocal()
        should_close = True
    else:
        should_close = False

    try:
        # Find batches that are still marked as "running" but no worker is alive
        running_batches = db_session.query(AIScreeningBatch).filter(
            AIScreeningBatch.status == "running"
        ).all()

        for batch in running_batches:
            # Check if this batch has an active worker in the current process
            with _batch_lock:
                is_active = (
                    batch.id in _active_batches and
                    _active_batches[batch.id]["thread"].is_alive()
                )

            if not is_active:
                logger.warning(f"Recovering interrupted batch {batch.id}")

                # Reset any papers in "processing" state that were started by this batch
                stuck_papers = db_session.query(AIScreeningResult).filter(
                    AIScreeningResult.processing_status == "processing",
                    AIScreeningResult.created_at >= batch.started_at
                ).all()

                for sp in stuck_papers:
                    sp.processing_status = "pending"
                    sp.error_message = f"Recovered from interrupted batch {batch.id}"
                    logger.info(f"  Reset paper {sp.paper_id} from processing to pending")

                # Mark batch as interrupted (can be resumed)
                batch.status = "interrupted"
                batch.error_message = "Worker terminated (server restart)"
                batch.finished_at = datetime.now(timezone.utc)

        # Commit batch changes
        db_session.commit()

        # Also reset any "processing" papers not associated with any running batch
        stale_processing = db_session.query(AIScreeningResult).filter(
            AIScreeningResult.processing_status == "processing"
        ).all()

        for sp in stale_processing:
            sp.processing_status = "pending"
            sp.error_message = "Recovered from stale processing state (startup)"
            logger.info(f"Reset stale paper {sp.paper_id} from processing to pending")

        db_session.commit()

    finally:
        if should_close:
            db_session.close()


def _process_batch_persistent(batch_id: int):
    """
    Background worker with persistent state and heartbeat.
    """
    db = SessionLocal()
    service = AIScreeningService(db)
    pid = str(os.getpid())

    try:
        # Mark batch as running
        batch = db.query(AIScreeningBatch).filter(AIScreeningBatch.id == batch_id).first()
        if not batch:
            logger.error(f"Batch {batch_id} not found")
            return

        batch.status = "running"
        batch.started_at = datetime.now(timezone.utc)
        batch.last_progress_at = datetime.now(timezone.utc)
        batch.worker_pid = pid
        db.commit()

        logger.info(f"Batch {batch_id} started (pid={pid})")

        # Process papers in a claim-based manner
        # Each iteration claims the next available paper
        processed_count = 0
        succeeded_count = 0
        failed_count = 0

        while True:
            # Check if cancelled
            with _batch_lock:
                if _active_batches.get(batch_id, {}).get("cancelled", False):
                    batch.status = "cancelled"
                    batch.finished_at = datetime.now(timezone.utc)
                    db.commit()
                    logger.info(f"Batch {batch_id} cancelled")
                    return

            # Claim the next pending paper
            # Priority: papers in 'pending' (recovered), then unscreened papers
            next_paper = _claim_next_paper(db, batch_id)

            if next_paper is None:
                # No more papers to process
                break

            paper_id = next_paper
            batch.current_paper_id = paper_id
            batch.last_progress_at = datetime.now(timezone.utc)
            db.commit()

            try:
                # Process the paper
                result = service.screen_paper(paper_id, use_cache=False)
                processed_count += 1

                if result.processing_status == "completed":
                    succeeded_count += 1
                else:
                    failed_count += 1

                # Update batch progress
                batch.processed = processed_count
                batch.succeeded = succeeded_count
                batch.failed = failed_count
                batch.last_progress_at = datetime.now(timezone.utc)
                batch.total_papers = batch.batch_size  # Target count
                db.commit()

                logger.info(
                    f"Batch {batch_id}: paper {paper_id} "
                    f"({processed_count}/{batch.batch_size}) -> {result.processing_status}"
                )

            except Exception as e:
                processed_count += 1
                failed_count += 1
                batch.processed = processed_count
                batch.succeeded = succeeded_count
                batch.failed = failed_count
                batch.last_progress_at = datetime.now(timezone.utc)
                db.commit()
                logger.error(f"Batch {batch_id}: paper {paper_id} failed: {e}")

            # Check if we've reached the batch size
            if processed_count >= batch.batch_size:
                break

        # Mark batch as completed
        batch.status = "completed"
        batch.finished_at = datetime.now(timezone.utc)
        batch.current_paper_id = None
        batch.total_papers = processed_count
        db.commit()

        logger.info(
            f"Batch {batch_id} completed: {succeeded_count} succeeded, "
            f"{failed_count} failed, {processed_count} total"
        )

    except Exception as e:
        logger.error(f"Batch {batch_id} failed with exception: {e}")
        try:
            batch = db.query(AIScreeningBatch).filter(AIScreeningBatch.id == batch_id).first()
            if batch:
                batch.status = "failed"
                batch.error_message = str(e)[:500]
                batch.finished_at = datetime.now(timezone.utc)
                db.commit()
        except:
            pass

    finally:
        with _batch_lock:
            _active_batches.pop(batch_id, None)
        db.close()


def _claim_next_paper(db: Session, batch_id: int) -> Optional[int]:
    """
    Claim the next paper for processing.
    Priority:
    1. Papers in 'pending' state (recovered from interrupted batches)
    2. Papers that have never been screened
    """
    # First, try to claim a pending paper (recovered)
    pending = db.query(AIScreeningResult).filter(
        AIScreeningResult.processing_status == "pending"
    ).order_by(AIScreeningResult.paper_id).first()

    if pending:
        # Mark as processing to claim it
        pending.processing_status = "processing"
        pending.created_at = datetime.now(timezone.utc)
        db.commit()
        return pending.paper_id

    # Then, find papers that have never been screened
    already_screened = db.query(AIScreeningResult.paper_id).subquery()

    unscreened = db.query(Paper).filter(
        ~Paper.id.in_(already_screened)
    ).order_by(Paper.id).first()

    if unscreened:
        # Create a processing record to claim it
        claim = AIScreeningResult(
            paper_id=unscreened.id,
            processing_status="processing",
        )
        db.add(claim)
        db.commit()
        return unscreened.id

    return None
