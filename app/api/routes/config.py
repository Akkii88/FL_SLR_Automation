"""
API Routes - Configuration
===========================
Endpoints for managing the review configuration.
"""

from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.core.config import settings
from app.core.review_config import ReviewConfig, get_config_path, load_or_create_config

router = APIRouter()


class ConfigResponse(BaseModel):
    title: str
    version: str
    start_date: str
    end_date: str
    primary_source: str
    max_candidates_per_family: int
    search_families: list[dict]


class ConfigUpdateRequest(BaseModel):
    title: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    max_candidates_per_family: Optional[int] = None


@router.get("/", response_model=ConfigResponse)
async def get_config():
    """Get the current review configuration."""
    config_path = get_config_path(settings.project_root)
    config = load_or_create_config(settings.project_root)

    return ConfigResponse(
        title=config.title,
        version=config.version,
        start_date=str(config.start_date),
        end_date=str(config.end_date),
        primary_source=config.primary_source,
        max_candidates_per_family=config.max_candidates_per_family,
        search_families=[sf.model_dump() for sf in config.search_families],
    )


@router.put("/")
async def update_config(update: ConfigUpdateRequest):
    """Update review configuration."""
    config = load_or_create_config(settings.project_root)

    if update.title is not None:
        config.title = update.title
    if update.start_date is not None:
        config.start_date = date.fromisoformat(update.start_date)
    if update.end_date is not None:
        config.end_date = date.fromisoformat(update.end_date)
    if update.max_candidates_per_family is not None:
        config.max_candidates_per_family = update.max_candidates_per_family

    config_path = get_config_path(settings.project_root)
    config.save(config_path)

    return {"status": "updated", "config": config.model_dump()}
