"""
Search Checkpoint Service
==========================
Manages resumable searches by saving cursor state to the database.
If a search is interrupted, it can be resumed from the last cursor.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


def get_checkpoint_path() -> Path:
    """Return the path to the checkpoint file."""
    return settings.project_root / "data" / "raw" / "search_checkpoint.json"


def save_checkpoint(
    search_run_id: int,
    cursor: str,
    records_retrieved: int,
    pages_retrieved: int,
    family_name: str,
    query: str,
) -> None:
    """
    Save the current search state to a checkpoint file.
    This allows resuming a search after interruption.
    """
    checkpoint = {
        "search_run_id": search_run_id,
        "cursor": cursor,
        "records_retrieved": records_retrieved,
        "pages_retrieved": pages_retrieved,
        "family_name": family_name,
        "query": query,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "software_version": "1.0.0",
    }

    path = get_checkpoint_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, indent=2)

    logger.info(
        f"Checkpoint saved: run={search_run_id}, cursor={cursor[:20]}..., "
        f"records={records_retrieved}"
    )


def load_checkpoint() -> Optional[dict]:
    """
    Load the last checkpoint if it exists.
    Returns None if no checkpoint found.
    """
    path = get_checkpoint_path()
    if not path.exists():
        return None

    with open(path, "r", encoding="utf-8") as f:
        checkpoint = json.load(f)

    logger.info(
        f"Checkpoint loaded: run={checkpoint.get('search_run_id')}, "
        f"records={checkpoint.get('records_retrieved')}"
    )
    return checkpoint


def clear_checkpoint() -> None:
    """Remove the checkpoint file after a successful search."""
    path = get_checkpoint_path()
    if path.exists():
        path.unlink()
        logger.info("Checkpoint cleared.")


def has_checkpoint() -> bool:
    """Check if a checkpoint exists."""
    return get_checkpoint_path().exists()
