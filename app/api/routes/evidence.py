"""
API Routes - Evidence Dashboard
=================================
Endpoints for evidence quality visualization and ranking stability analysis.
"""

import logging
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.db.engine import get_db
from app.services.ranking_engine import RankingStabilityEngine

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/overview")
async def get_evidence_overview(db: Session = Depends(get_db)):
    """
    Get overall evidence quality statistics for the main dashboard.
    Shows the 5 dimensions across all assessed claims.
    """
    engine = RankingStabilityEngine(db)
    return engine.get_overall_evidence_stats()


@router.get("/claim/{claim_id}")
async def get_claim_evidence(claim_id: int, db: Session = Depends(get_db)):
    """
    Get detailed evidence summary for a single claim.
    Includes the 5-dimension evidence profile.
    """
    engine = RankingStabilityEngine(db)
    try:
        summary = engine.get_evidence_summary(claim_id)
        rankings = engine.analyze_claim_rankings(claim_id)
        return {
            "evidence": summary,
            "rankings": rankings,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/ranking-analysis/{claim_id}")
async def get_ranking_analysis(claim_id: int, db: Session = Depends(get_db)):
    """
    Get ranking stability analysis for a claim.
    Shows how rankings change across conditions.
    """
    engine = RankingStabilityEngine(db)
    try:
        return engine.analyze_claim_rankings(claim_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/by-dimension/{dimension}")
async def get_by_dimension(dimension: str, db: Session = Depends(get_db)):
    """
    Get evidence quality breakdown by dimension.
    
    Dimensions:
    - repetition
    - uncertainty
    - direct_statistics
    - fairness
    - ranking
    """
    engine = RankingStabilityEngine(db)
    stats = engine.get_overall_evidence_stats()

    dimension_map = {
        "repetition": stats.get("dimension_1_repetition", {}),
        "uncertainty": stats.get("dimension_2_uncertainty", {}),
        "direct_statistics": stats.get("dimension_3_direct_statistics", {}),
        "fairness": stats.get("dimension_4_fairness", {}),
        "ranking": stats.get("dimension_5_ranking", {}),
    }

    if dimension not in dimension_map:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid dimension. Must be one of: {list(dimension_map.keys())}",
        )

    return {"dimension": dimension, "data": dimension_map[dimension]}
